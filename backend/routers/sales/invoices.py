"""Sales invoices endpoints."""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from utils.i18n import http_error
from sqlalchemy import text
from services.tax_engine import resolve_line_tax, resolve_line_tax_group
from typing import Any, Dict, List, Optional
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import logging
from pydantic import BaseModel
from utils.cache import invalidate_company_cache, invalidate_aggregates
from utils.party_balance import update_party_site_balance

_D2 = Decimal('0.01')
_D6 = Decimal('0.000001')
_MAX_RATE_AGE_DAYS = 31

# T10.1 P1 #62 — process-local cache for ``information_schema.columns``
# lookups. The previous code re-queried the catalog on every invoice
# create which is hot-path; the schema only changes on deploy/migration.
# Keyed by (database url, table name); values are frozensets.
_TABLE_COLUMNS_CACHE: dict[tuple[str, str], frozenset[str]] = {}


def _table_columns(db, table_name: str) -> frozenset[str]:
    """Return the set of columns for ``table_name`` in ``db``'s schema.

    Cached per (engine URL, table) tuple. Use ``invalidate=True`` is
    deliberately not exposed; restart or DDL upgrade clears the cache
    naturally because deploys recycle the worker process.
    """
    try:
        url_key = str(db.bind.url) if getattr(db, "bind", None) is not None else ""
    except Exception:
        url_key = ""
    key = (url_key, table_name)
    cached = _TABLE_COLUMNS_CACHE.get(key)
    if cached is not None:
        return cached
    cols = frozenset(
        row.column_name
        for row in db.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"),
            {"t": table_name},
        ).fetchall()
    )
    _TABLE_COLUMNS_CACHE[key] = cols
    return cols


def _dec(v) -> Decimal:
    """Convert any numeric value to Decimal safely."""
    return Decimal(str(v)) if v is not None else Decimal('0')
def _prefetch_costing_methods(db, product_ids: List[int], warehouse_id: int) -> dict[int, str]:
    """Return costing method per product using bulk lookups (warehouse-first, then global)."""
    if not product_ids:
        return {}

    methods = {pid: "wac" for pid in product_ids}
    wh_rows = db.execute(text("""
        SELECT DISTINCT ON (product_id) product_id, costing_method
        FROM cost_layers
        WHERE warehouse_id = :wid
          AND product_id = ANY(:pids)
          AND is_exhausted = FALSE
        ORDER BY product_id, id DESC
    """), {"wid": warehouse_id, "pids": product_ids}).fetchall()
    for row in wh_rows:
        methods[int(row.product_id)] = row.costing_method or "wac"

    missing = [pid for pid, method in methods.items() if method == "wac"]
    if missing:
        global_rows = db.execute(text("""
            SELECT DISTINCT ON (product_id) product_id, costing_method
            FROM cost_layers
            WHERE product_id = ANY(:pids)
              AND is_exhausted = FALSE
            ORDER BY product_id, id DESC
        """), {"pids": missing}).fetchall()
        for row in global_rows:
            methods[int(row.product_id)] = row.costing_method or "wac"

    return methods
def _prefetch_product_costs(db, product_ids: List[int], warehouse_id: int, policy_type: str) -> dict[int, float]:
    """Return WAC/fallback unit cost map in one query set."""
    if not product_ids:
        return {}

    if policy_type == 'per_warehouse_wac':
        rows = db.execute(text("""
            SELECT p.id AS product_id, COALESCE(i.average_cost, p.cost_price, 0) AS unit_cost
            FROM products p
            LEFT JOIN inventory i
              ON i.product_id = p.id
             AND i.warehouse_id = :wid
            WHERE p.id = ANY(:pids)
        """), {"wid": warehouse_id, "pids": product_ids}).fetchall()
    else:
        rows = db.execute(text("""
            SELECT id AS product_id, COALESCE(cost_price, 0) AS unit_cost
            FROM products
            WHERE id = ANY(:pids)
        """), {"pids": product_ids}).fetchall()

    return {int(row.product_id): _dec(row.unit_cost or 0) for row in rows}

from database import get_db_connection
from routers.auth import get_current_user
from utils.audit import log_activity
from utils.permissions import branch_scope_filter_from_scope, require_permission, require_sensitive_permission, resolve_branch_scope, validate_branch_access, validate_treasury_account_access
from utils.accounting import get_mapped_account_id
from utils.fiscal_lock import check_fiscal_period_open
from utils.tax_precision import money_str, rate_str
from .schemas import InvoiceCreate, InvoiceResponse

invoices_router = APIRouter()
logger = logging.getLogger(__name__)

@invoices_router.post("/invoices/preview", dependencies=[Depends(require_permission("sales.create"))])
def preview_invoice_totals(invoice: InvoiceCreate, current_user: dict = Depends(get_current_user)):
    """حساب إجماليات الفاتورة بدون حفظ — للاستخدام المباشر من الواجهة"""
    from utils.accounting import compute_invoice_totals, compute_line_amounts

    db = get_db_connection(current_user.company_id)
    try:
        # Validate branch
        if not invoice.branch_id:
            raise HTTPException(status_code=400, detail="يجب تحديد الفرع")
        validate_branch_access(current_user, invoice.branch_id)

        line_details = []
        preview_lines_data = []
        for item in invoice.items:
            taxes = resolve_line_tax_group(invoice.branch_id, item.product_id, db, invoice.invoice_date, customer_id=invoice.customer_id)
            effective_tax_rate = sum((t["tax_rate"] for t in taxes), Decimal("0"))
            la = compute_line_amounts(item.quantity, item.unit_price, effective_tax_rate, item.discount, discount_is_percent=False)
            line_details.append({
                "product_id": item.product_id,
                "description": item.description,
                "quantity": money_str(item.quantity),
                "unit_price": money_str(item.unit_price),
                "tax_rate": rate_str(effective_tax_rate),
                "discount": money_str(item.discount),
                "subtotal": money_str(la["subtotal"]),
                "discount_amount": money_str(la["discount_amount"]),
                "taxable": money_str(la["taxable"]),
                "tax_amount": money_str(la["tax_amount"]),
                "line_total": money_str(la["line_total"]),
                "applied_taxes": [{"tax_name": t["tax_name"], "tax_rate": rate_str(t["tax_rate"])} for t in taxes] if len(taxes) > 1 else None,
            })
            preview_lines_data.append({
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "tax_rate": effective_tax_rate,
                "discount": item.discount,
            })

        totals = compute_invoice_totals(preview_lines_data, invoice.effect_percentage or 0, invoice.markup_amount or 0, discount_is_percent=False)

        paid = _dec(invoice.paid_amount or 0)
        grand = totals["grand_total"]

        return {
            "lines": line_details,
            "subtotal": money_str(totals["subtotal"]),
            "total_discount": money_str(totals["total_discount"]),
            "total_tax": money_str(totals["total_tax"]),
            "grand_total": money_str(grand),
            "paid_amount": money_str(paid),
            "remaining_balance": money_str(grand - paid),
            "currency": invoice.currency or "SAR",
        }
    finally:
        db.close()


@invoices_router.get("/invoices", dependencies=[Depends(require_permission("sales.view"))], response_model=Dict[str, Any])
def list_invoices(
    branch_id: Optional[int] = None,
    status_filter: Optional[str] = None,
    overdue: Optional[bool] = None,
    search: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
    current_user: dict = Depends(get_current_user)
):
    """عرض قائمة فواتير المبيعات مع ترقيم الصفحات"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    
    db = get_db_connection(current_user.company_id)
    try:
        where_clauses = ["i.invoice_type = 'sales'"]
        params = {}

        branch_condition = branch_scope_filter_from_scope(branch_scope, "i.branch_id", params, prefix="").strip()
        if branch_condition:
            where_clauses.append(branch_condition)
        if status_filter:
            where_clauses.append("i.status = :status")
            params["status"] = status_filter
        if overdue is True:
            where_clauses.append("i.due_date IS NOT NULL AND i.due_date < CURRENT_DATE AND i.status != 'paid'")
        elif overdue is False:
            where_clauses.append("(i.due_date IS NULL OR i.due_date >= CURRENT_DATE OR i.status = 'paid')")
        if search:
            where_clauses.append("(i.invoice_number ILIKE :search OR p.name ILIKE :search)")
            params["search"] = f"%{search}%"

        where_sql = " AND ".join(where_clauses)

        # Count total
        total = db.execute(text(f"""
            SELECT COUNT(*) FROM invoices i
            JOIN parties p ON i.party_id = p.id
            WHERE {where_sql}
        """), params).scalar() or 0

        # Fetch page
        params["limit"] = limit
        params["offset"] = (page - 1) * limit

        result = db.execute(text(f"""
            SELECT i.id, i.invoice_number, i.invoice_date, i.due_date, 
                   i.total, i.paid_amount, i.status, p.name as customer_name,
                   i.currency, i.exchange_rate,
                   c.code AS base_currency,
                   (COALESCE(i.total, 0) * COALESCE(NULLIF(i.exchange_rate, 0), 1)) AS total_base
            FROM invoices i
            JOIN parties p ON i.party_id = p.id
            CROSS JOIN LATERAL (
                SELECT code
                FROM currencies
                WHERE is_base = TRUE
                LIMIT 1
            ) c
            WHERE {where_sql}
            ORDER BY i.created_at DESC
            LIMIT :limit OFFSET :offset
        """), params).fetchall()

        return {
            "items": [dict(row._mapping) for row in result],
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit
        }
    finally:
        db.close()
@invoices_router.post("/invoices", response_model=InvoiceResponse, status_code=status.HTTP_201_CREATED,
                       dependencies=[Depends(require_permission("sales.create"))])
def create_sales_invoice(
    request: Request,
    invoice: InvoiceCreate,
    current_user: dict = Depends(get_current_user)
):
    """إنشاء فاتورة مبيعات (نقص من المخزون + قيد محاسبي)"""
    db = get_db_connection(current_user.company_id)
    try:
        validated_branch_id = validate_branch_access(current_user, invoice.branch_id)
        selected_treasury = None
        if invoice.treasury_id:
            selected_treasury = validate_treasury_account_access(
                db, current_user, invoice.treasury_id, validated_branch_id
            )

        # --- 0. Currency & Exchange Rate Logic ---
        # Get Company Base Currency
        base_currency_row = db.execute(text("SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1")).fetchone()
        if not base_currency_row:
             base_currency_row = db.execute(text("SELECT setting_value as code FROM company_settings WHERE setting_key = 'default_currency'")).fetchone()

        base_currency = base_currency_row[0] if base_currency_row else "SYP"

        inv_currency = invoice.currency or base_currency
        exchange_rate = _dec(invoice.exchange_rate or 1)

        def conversion_rate_needed(rate_val):
            d_rate = _dec(rate_val)
            return rate_val is None or d_rate <= 0 or d_rate == Decimal('1')

        # If currency is different from base and no rate provided, fetch latest rate
        if inv_currency != base_currency and conversion_rate_needed(invoice.exchange_rate):
             rate_row = db.execute(text("""
                SELECT rate_date, rate FROM exchange_rates 
                WHERE currency_id = (SELECT id FROM currencies WHERE code = :code) 
                AND rate_date <= :date 
                ORDER BY rate_date DESC LIMIT 1
             """), {"code": inv_currency, "date": invoice.invoice_date}).fetchone()

             if not rate_row:
                 raise HTTPException(status_code=400, detail=f"No exchange rate found for {inv_currency}")
             age_days = (invoice.invoice_date - rate_row.rate_date).days if rate_row.rate_date else 0
             if age_days > _MAX_RATE_AGE_DAYS:
                 raise HTTPException(status_code=400, detail=f"Exchange rate for {inv_currency} is expired ({age_days} days old)")
             exchange_rate = _dec(rate_row.rate)

        if inv_currency != base_currency and exchange_rate <= 0:
            raise HTTPException(status_code=400, detail="Exchange rate must be greater than zero")

        def to_base(amount):
            return (_dec(amount) * exchange_rate).quantize(_D2, ROUND_HALF_UP)

        # --- 1. Generate Sequential Invoice Number ---
        from utils.accounting import generate_sequential_number
        inv_num = generate_sequential_number(db, f"INV-{datetime.now().year}", "invoices", "invoice_number")

        # --- FISCAL-LOCK: Reject if accounting period is closed ---
        check_fiscal_period_open(db, invoice.invoice_date)

        # --- UOM Validation: Discrete units must have integer quantities ---
        from utils.quantity_validation import validate_quantities_for_products
        validate_quantities_for_products(db, invoice.items)

        # --- 2. Calculate Totals (TASK-027: unified via compute_invoice_totals) ---
        from utils.accounting import compute_invoice_totals, compute_line_amounts

        # Resolve tax per line via tax engine (branch-aware, no hardcoded rates)
        _branch_id = validated_branch_id or invoice.branch_id
        _doc_date = invoice.invoice_date if hasattr(invoice, 'invoice_date') and invoice.invoice_date else None
        items_to_save = []
        for item in invoice.items:
            taxes = resolve_line_tax_group(_branch_id, item.product_id, db, _doc_date, customer_id=invoice.customer_id)
            # Sum all taxes in the group for the line tax rate
            combined_tax_rate = sum((t["tax_rate"] for t in taxes), Decimal("0"))
            la = compute_line_amounts(
                item.quantity, item.unit_price, combined_tax_rate, item.discount, discount_is_percent=False
            )
            items_to_save.append({
                **item.model_dump(),
                "tax_rate": combined_tax_rate,
                "tax_rate_id": taxes[0]["tax_rate_id"] if len(taxes) == 1 else None,
                "applied_taxes": taxes if len(taxes) > 1 else None,
                "total": la["line_total"],
            })

        line_dicts = [
            {
                "quantity": it["quantity"],
                "unit_price": it["unit_price"],
                "tax_rate": it["tax_rate"],
                "discount": it["discount"],
            }
            for it in items_to_save
        ]

        # Header-level discount (applies only when effect_type == 'discount')
        header_disc_pct = (
            _dec(invoice.effect_percentage)
            if getattr(invoice, 'effect_type', 'discount') == 'discount'
            else Decimal('0')
        )
        markup_amt = (
            _dec(invoice.markup_amount)
            if getattr(invoice, 'effect_type', 'discount') == 'markup'
            else Decimal('0')
        )

        totals = compute_invoice_totals(
            line_dicts,
            header_discount_pct=header_disc_pct,
            markup_amount=markup_amt,
            discount_is_percent=False,
        )
        subtotal = totals["subtotal"]
        total_tax = totals["total_tax"]
        total_discount = totals["total_discount"]
        grand_total = totals["grand_total"]

        # --- 3. Handle Payment ---
        paid_amount = _dec(invoice.paid_amount or 0)

        # If payment method is immediate (cash / bank / check / card),
        # the invoice is always fully paid — the paid_amount field is hidden
        # in the frontend for these methods and defaults to 0, so we override it.
        if invoice.payment_method in ('cash', 'bank', 'check', 'card'):
            paid_amount = grand_total

        remaining_balance = grand_total - paid_amount
        inv_status = 'paid' if remaining_balance <= _D2 else ('partial' if paid_amount > 0 else 'unpaid')

        # GL amounts in base currency
        gl_subtotal = to_base(subtotal)
        gl_tax = to_base(total_tax)
        gl_discount = to_base(total_discount)
        gl_total = to_base(grand_total)
        gl_paid = to_base(paid_amount)
        remaining_gl = gl_total - gl_paid

        # --- 4. Credit Limit Check using party_site_balances ---
        customer = db.execute(text("SELECT credit_limit FROM parties WHERE id = :id FOR UPDATE"), {"id": invoice.customer_id}).fetchone()
        if customer and customer.credit_limit > 0:
            # Compute current balance from party_site_balances (in SAR)
            current_balance_sar = db.execute(text("""
                SELECT COALESCE(SUM(psb.balance * COALESCE(c.current_rate, 1)), 0)
                FROM party_sites ps
                JOIN party_site_balances psb ON psb.party_site_id = ps.id
                LEFT JOIN currencies c ON psb.currency = c.code
                WHERE ps.party_id = :pid
            """), {"pid": invoice.customer_id}).scalar() or 0
            new_balance = _dec(current_balance_sar) + remaining_gl
            if new_balance > _dec(customer.credit_limit):
                raise HTTPException(
                    status_code=400,
                    detail=f"تجاوز الحد الائتماني. الحد: {customer.credit_limit}, الرصيد الحالي: {_dec(current_balance_sar).quantize(_D2)}, المطلوب: {remaining_gl}"
                )

        # --- 5. Save Invoice Header (schema-drift tolerant) ---
        # T10.1 P1 #62 — served from process cache.
        invoice_cols = _table_columns(db, 'invoices')

        # Resolve party_id from party_site_id if provided
        party_id = invoice.customer_id
        party_site_id = None
        if invoice.party_site_id:
            site = db.execute(text("SELECT party_id FROM party_sites WHERE id = :sid"), 
                            {"sid": invoice.party_site_id}).fetchone()
            if site:
                party_id = site.party_id
                party_site_id = invoice.party_site_id

        header_cols = [
            "invoice_number", "party_id", "invoice_type", "invoice_date", "due_date",
            "subtotal", "tax_amount", "discount", "total", "paid_amount", "status", "notes",
            "created_by", "branch_id", "warehouse_id"
        ]
        header_vals = [
            ":num", ":cust", "'sales'", ":inv_date", ":due_date",
            ":sub", ":tax", ":disc", ":total", ":paid", ":status", ":notes",
            ":user", ":branch", ":wh"
        ]

        header_params = {
            "num": inv_num,
            "cust": party_id,
            "inv_date": invoice.invoice_date,
            "due_date": invoice.due_date,
            "sub": subtotal,
            "tax": total_tax,
            "disc": total_discount,
            "total": grand_total,
            "paid": paid_amount,
            "status": inv_status,
            "notes": invoice.notes,
            "user": current_user.id,
            "branch": validated_branch_id or invoice.branch_id,
            "wh": invoice.warehouse_id,
        }

        # Add party_site_id if column exists and value is provided
        if party_site_id and 'party_site_id' in invoice_cols:
            header_cols.append("party_site_id")
            header_vals.append(":party_site_id")
            header_params["party_site_id"] = party_site_id

        optional_header_map = {
            "payment_method": ("pay_method", invoice.payment_method),
            "currency": ("currency", inv_currency),
            "exchange_rate": ("exchange_rate", exchange_rate.quantize(_D6, ROUND_HALF_UP)),
            "cost_center_id": ("cc_id", invoice.cost_center_id),
            "sales_order_id": ("so_id", invoice.sales_order_id),
            "effect_type": ("effect_type", invoice.effect_type),
            "effect_percentage": ("effect_perc", invoice.effect_percentage),
            "markup_amount": ("markup_amt", invoice.markup_amount),
        }

        for col_name, (param_name, value) in optional_header_map.items():
            if col_name in invoice_cols:
                header_cols.append(col_name)
                header_vals.append(f":{param_name}")
                header_params[param_name] = value

        insert_sql = f"""
            INSERT INTO invoices ({', '.join(header_cols)})
            VALUES ({', '.join(header_vals)})
            RETURNING id
        """

        invoice_id = db.execute(text(insert_sql), header_params).scalar()

        # Update Sales Order status if linked
        if invoice.sales_order_id:
            db.execute(text("UPDATE sales_orders SET status = 'invoiced' WHERE id = :id"), {"id": invoice.sales_order_id})

        # --- 6. Save Invoice Lines + Deduct Stock ---
        total_cogs = Decimal('0')
        wh_id = invoice.warehouse_id
        if not wh_id:
            wh_id = db.execute(text("SELECT id FROM warehouses WHERE is_default = TRUE LIMIT 1")).scalar() or 1

        from services.costing_service import CostingService
        costing_service = CostingService

        product_ids = sorted({int(item["product_id"]) for item in items_to_save})
        costing_methods = _prefetch_costing_methods(db, product_ids, wh_id)
        policy_type = costing_service.get_active_policy(db)
        prefetched_unit_costs = _prefetch_product_costs(db, product_ids, wh_id, policy_type)

        # T10.1 P1 #62 — served from process cache.
        invoice_line_cols = _table_columns(db, 'invoice_lines')
        has_line_markup_col = "markup" in invoice_line_cols

        for item in items_to_save:
            # CONC-FIX: Lock inventory row before deduction to prevent overselling
            inv_row = db.execute(text("""
                SELECT quantity FROM inventory
                WHERE product_id = :pid AND warehouse_id = :wh
                FOR UPDATE
            """), {"pid": item["product_id"], "wh": wh_id}).fetchone()

            if inv_row and _dec(inv_row.quantity) < _dec(item["quantity"]):
                prod_name = item.get("description", str(item["product_id"]))
                raise HTTPException(
                    status_code=400,
                    detail=f"المخزون غير كافٍ للمنتج {prod_name}. المتوفر: {inv_row.quantity}, المطلوب: {item['quantity']}"
                )

            # Deduct inventory (row is locked by FOR UPDATE above)
            db.execute(text("""
                UPDATE inventory SET quantity = quantity - :qty
                WHERE product_id = :pid AND warehouse_id = :wh
            """), {"qty": item["quantity"], "pid": item["product_id"], "wh": wh_id})

            # Release reservation if from SO
            if invoice.sales_order_id:
                db.execute(text("""
                    UPDATE inventory 
                    SET reserved_quantity = GREATEST(0, reserved_quantity - :qty),
                        available_quantity = quantity - GREATEST(0, reserved_quantity - :qty)
                    WHERE product_id = :pid AND warehouse_id = :wh
                """), {"qty": item["quantity"], "pid": item["product_id"], "wh": wh_id})

            # Calculate COGS using costing service
            try:
                qty = _dec(item["quantity"])
                method = costing_methods.get(int(item["product_id"]), "wac")
                if method in ("fifo", "lifo"):
                    # FIFO/LIFO: consume cost layers and get precise COGS
                    item_cogs = _dec(costing_service.consume_layers(
                        db,
                        product_id=item["product_id"],
                        warehouse_id=wh_id,
                        quantity=_dec(qty),
                        sale_document_type="sales_invoice",
                        sale_document_id=invoice_id,
                        costing_method=method,
                    ))
                    unit_cost = (item_cogs / qty).quantize(_D6, ROUND_HALF_UP) if qty else Decimal('0')
                else:
                    unit_cost = _dec(prefetched_unit_costs.get(int(item["product_id"]), 0))
                    item_cogs = (unit_cost * qty).quantize(_D2, ROUND_HALF_UP)
            except Exception:
                # Fallback: use product cost_price
                qty = _dec(item["quantity"])
                fallback_cost = _dec(prefetched_unit_costs.get(int(item["product_id"]), 0))
                unit_cost = fallback_cost
                item_cogs = (fallback_cost * qty).quantize(_D2, ROUND_HALF_UP)

            total_cogs += item_cogs

            # Insert Invoice Line with frozen unit_cost
            has_line_unit_cost = "unit_cost" in invoice_line_cols
            import json as _json
            applied_taxes_json = _json.dumps(item.get("applied_taxes")) if item.get("applied_taxes") else None
            if has_line_markup_col:
                line_sql = """
                    INSERT INTO invoice_lines (
                        invoice_id, product_id, description, quantity, unit_price, tax_rate, tax_rate_id, applied_taxes, discount, markup, total, unit_cost
                    ) VALUES (
                        :inv_id, :pid, :desc, :qty, :price, :tax_rate, :tax_rate_id, :applied_taxes, :disc, :markup, :total, :unit_cost
                    )
                """
            else:
                line_sql = """
                    INSERT INTO invoice_lines (
                        invoice_id, product_id, description, quantity, unit_price, tax_rate, tax_rate_id, applied_taxes, discount, total, unit_cost
                    ) VALUES (
                        :inv_id, :pid, :desc, :qty, :price, :tax_rate, :tax_rate_id, :applied_taxes, :disc, :total, :unit_cost
                    )
                """

            db.execute(text(line_sql), {
                "inv_id": invoice_id, "pid": item["product_id"], "desc": item["description"],
                "qty": item["quantity"], "price": item["unit_price"],
                "tax_rate": item["tax_rate"], "tax_rate_id": item.get("tax_rate_id"),
                "applied_taxes": applied_taxes_json,
                "disc": item["discount"], "markup": item.get("markup", 0), "total": item["total"],
                "unit_cost": unit_cost
            })

            # Log Inventory Transaction
            db.execute(text("""
                INSERT INTO inventory_transactions (
                    product_id, warehouse_id, transaction_type,
                    reference_type, reference_id, reference_document,
                    quantity, unit_cost, total_cost, created_by
                ) VALUES (
                    :pid, :wh, 'sale',
                    'invoice', :ref_id, :ref_doc,
                    :qty, :cost, :total_cost, :user
                )
            """), {
                "pid": item["product_id"], "wh": wh_id,
                "ref_id": invoice_id, "ref_doc": inv_num,
                "qty": -_dec(item["quantity"]),
                "cost": unit_cost,
                "total_cost": item_cogs,
                "user": current_user.id
            })

        # --- 6.5 Update Customer Balance via party_site_balances ---
        update_party_site_balance(db, party_id=invoice.customer_id, branch_id=validated_branch_id or invoice.branch_id,
                           currency=inv_currency, amount=float(remaining_balance))

        # --- 6.7 Payment Voucher (if paid on creation) ---
        if paid_amount > 0:
            # Determine the actual payment method
            if invoice.payment_method and invoice.payment_method != 'credit':
                actual_method = invoice.payment_method
            elif invoice.payment_method == 'credit':
                # credit + down payment: use down_payment_method
                actual_method = getattr(invoice, 'down_payment_method', None) or 'cash'
            else:
                actual_method = None

            if actual_method:
                from utils.accounting import generate_sequential_number as gen_seq
                pv_num = gen_seq(db, f"PV-{datetime.now().year}", "payment_vouchers", "voucher_number")

                pv_id = db.execute(text("""
                    INSERT INTO payment_vouchers (
                        voucher_number, voucher_type, voucher_date, party_type, party_id,
                        amount, payment_method, treasury_account_id, reference, status, created_by, branch_id,
                        currency, exchange_rate
                    ) VALUES (
                        :vnum, 'receipt', :vdate, 'customer', :cust,
                        :amt, :method, :treasury_id, :ref, 'posted', :user, :branch,
                        :currency, :rate
                    ) RETURNING id
                """), {
                    "vnum": pv_num, "vdate": invoice.invoice_date, "cust": invoice.customer_id,
                    "amt": paid_amount, "method": actual_method,
                    "treasury_id": invoice.treasury_id,
                    "ref": inv_num,
                    "user": current_user.id, "branch": validated_branch_id or invoice.branch_id,
                    "currency": inv_currency, "rate": exchange_rate
                }).scalar()

                # Link payment allocation to invoice
                db.execute(text("""
                    INSERT INTO payment_allocations (voucher_id, invoice_id, allocated_amount)
                    VALUES (:vid, :iid, :amt)
                """), {"vid": pv_id, "iid": invoice_id, "amt": paid_amount})
        # --- 7. GL Entry ---
        acc_cash = get_mapped_account_id(db, "acc_map_cash_main")
        acc_bank = get_mapped_account_id(db, "acc_map_bank")
        acc_ar = get_mapped_account_id(db, "acc_map_ar")
        acc_sales = get_mapped_account_id(db, "acc_map_sales_rev")
        acc_vat_out = get_mapped_account_id(db, "acc_map_vat_out")
        acc_cogs = get_mapped_account_id(db, "acc_map_cogs")
        acc_inventory = get_mapped_account_id(db, "acc_map_inventory")

        je_lines = []
        # A. Debit Side
        pay_src = invoice.payment_method or "credit"
        if gl_paid > 0:
            if pay_src == 'cash':
                je_lines.append({
                    "account_id": selected_treasury["gl_account_id"] if selected_treasury else acc_cash, "debit": paid_amount if inv_currency != base_currency else gl_paid, "credit": 0,
                    "description": f"Sales Cash - {inv_num}",
                    "amount_currency": paid_amount, "currency": inv_currency
                })
            elif pay_src in ('bank', 'check'):
                je_lines.append({
                    "account_id": selected_treasury["gl_account_id"] if selected_treasury else acc_bank, "debit": paid_amount if inv_currency != base_currency else gl_paid, "credit": 0,
                    "description": f"Sales {pay_src.capitalize()} - {inv_num}",
                    "amount_currency": paid_amount, "currency": inv_currency
                })

        if remaining_gl > _D2:
             je_lines.append({
                 "account_id": acc_ar, "debit": remaining_balance if inv_currency != base_currency else remaining_gl, "credit": 0,
                 "description": f"Sales Credit - {inv_num}",
                 "amount_currency": remaining_balance, "currency": inv_currency
             })

        # B. Revenue (Credit) - Net Amount + Markup
        # T3.2 (#15): markup is added to grand_total on the debit side, so it
        # must also be credited or the entry would be unbalanced. We post it
        # as part of the sales-revenue line (a positive header markup is
        # additional revenue, not a separate account in the current COA).
        net_sales = subtotal - total_discount + markup_amt  # Foreign Currency
        net_sales_gl = gl_subtotal - gl_discount + to_base(markup_amt)  # Base Currency

        if net_sales_gl > 0:
            je_lines.append({
                "account_id": acc_sales, "debit": 0, "credit": net_sales if inv_currency != base_currency else net_sales_gl,
                "description": f"Sales Revenue - {inv_num}",
                "amount_currency": net_sales, "currency": inv_currency
            })

        # C. VAT Output (Credit)
        if gl_tax > 0:
            je_lines.append({
                "account_id": acc_vat_out, "debit": 0, "credit": total_tax if inv_currency != base_currency else gl_tax,
                "description": f"VAT Output - {inv_num}",
                "amount_currency": total_tax, "currency": inv_currency
            })

        # D. COGS & Inventory (Perpetual Inventory)
        # Always Base Currency
        if total_cogs > 0:
            je_lines.append({
                "account_id": acc_cogs, "debit": total_cogs, "credit": 0,
                "description": f"COGS - {inv_num}",
                "amount_currency": total_cogs, "currency": base_currency,
                "exchange_rate": 1
            })
            je_lines.append({
                "account_id": acc_inventory, "debit": 0, "credit": total_cogs,
                "description": f"Inventory Redn - {inv_num}",
                "amount_currency": total_cogs, "currency": base_currency,
                "exchange_rate": 1
            })

        # Insert Journal Entry
        if je_lines:
            from services.gl_service import create_journal_entry as gl_create_journal_entry
            gl_create_journal_entry(
                db=db,
                company_id=current_user.company_id,
                date=invoice.invoice_date,
                description=f"Sales Invoice {inv_num} ({inv_currency})",
                lines=je_lines,
                user_id=current_user.id,
                branch_id=validated_branch_id or invoice.branch_id,
                reference=inv_num,
                currency=inv_currency,
                exchange_rate=float(exchange_rate),
                source="Sales-Invoice",
                source_id=invoice_id
            )

        # --- 7.5 Update Treasury Balance ---
        # T1.3a: idempotent recompute from journal_lines (single source of truth)
        if invoice.treasury_id and gl_paid > 0:
            from utils.treasury_balance import recalc_treasury_from_gl
            recalc_treasury_from_gl(db, invoice.treasury_id)

        # --- 8. Insert Currency Transaction (if Foreign Currency) ---
        if inv_currency != base_currency:
             db.execute(text("""
                 INSERT INTO currency_transactions (
                     transaction_type, transaction_id, account_id, 
                     currency_code, exchange_rate, amount_fc, amount_bc, description
                 ) VALUES (
                     'invoice', :tid, :aid, :curr, :rate, :fc, :bc, :desc
                 )
             """), {
                 "tid": invoice_id,
                 "aid": acc_ar,  # Tracking AR in foreign currency
                 "curr": inv_currency,
                 "rate": exchange_rate,
                 "fc": grand_total,
                 "bc": to_base(grand_total),
                 "desc": f"Sales Invoice {inv_num}"
             })

        db.commit()
        # T12 — scoped invalidation: invoice creation affects sales + reports +
        # dashboard + customer balance, but NOT HR/CRM/inventory caches.
        invalidate_aggregates(str(current_user.company_id),
                              "invoices", "sales_kpi", "reports",
                              "dashboard", "chart_of_accounts")
        

        cust_name = db.execute(text("SELECT name FROM parties WHERE id = :id"), {"id": invoice.customer_id}).scalar()

        # AUDIT LOG
        log_activity(
            db,
            user_id=current_user.id,
            username=current_user.username,
            action="sales.invoice.create",
            resource_type="invoice",
            resource_id=str(invoice_id),
            details={
                "invoice_number": inv_num,
                "total": grand_total,
                "customer_id": invoice.customer_id,
                "customer_name": cust_name
            },
            request=request,
            branch_id=validated_branch_id or invoice.branch_id
        )

        # ZATCA-004: Auto-generate QR code for the invoice
        zatca_qr = None
        try:
            from utils.zatca import process_invoice_for_zatca
            zatca_result = process_invoice_for_zatca(db, invoice_id, current_user.company_id)
            zatca_qr = zatca_result.get("qr_base64") if zatca_result else None
        except Exception as ze:
            logger.warning(f"ZATCA QR generation skipped for {inv_num}: {ze}")

        # T1.5c (#6): ZATCA Phase 2 clearance — when enforcement is enabled
        # and the tenant is in SA, submit synchronously to ZATCA and persist
        # the remote outcome on the invoice. Hard rejection raises HTTP 422
        # so the operator must correct the data; transient/offline failures
        # mark the invoice `pending_clearance` and enqueue retry via outbox.
        try:
            from utils.zatca_clearance import attempt_clearance
            jurisdiction = (db.execute(text(
                "SELECT setting_value FROM company_settings "
                "WHERE setting_key = 'jurisdiction' LIMIT 1"
            )).scalar() or "SA")
            clr = attempt_clearance(
                db,
                invoice_id=invoice_id,
                jurisdiction=jurisdiction,
                invoice_payload={
                    "invoice_number": inv_num,
                    "grand_total": money_str(grand_total),
                    "tax_total": money_str(total_tax),
                    "uuid": inv_num,
                },
            )
            if clr["status"] == "rejected":
                # Roll back: caller transaction will discard the invoice row.
                db.rollback()
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "zatca_rejected",
                        "message_ar": "رفضت هيئة الزكاة الفاتورة",
                        "message_en": "ZATCA rejected the invoice",
                        "error": clr.get("error"),
                    },
                )
        except HTTPException:
            raise
        except Exception as ze:
            # Never let an unexpected clearance error mask the invoice
            # creation result; the local artefacts are already persisted
            # and the operator can replay via the outbox endpoint.
            logger.warning(f"ZATCA clearance attempt failed for {inv_num}: {ze}")

        # Notify finance team about new invoice
        try:
            db.execute(text("""
                INSERT INTO notifications (user_id, type, title, message, link, is_read, created_at)
                SELECT DISTINCT u.id, 'sales_invoice', :title, :message, :link, FALSE, NOW()
                FROM company_users u
                WHERE u.is_active = TRUE AND u.role IN ('admin', 'superuser')
                AND u.id != :current_uid
            """), {
                "title": "🧾 فاتورة مبيعات جديدة",
                "message": f"فاتورة {inv_num} — {cust_name or ''} — {grand_total:,.2f}",
                "link": f"/sales/invoices/{invoice_id}",
                "current_uid": current_user.id
            })
            db.commit()
        except Exception:
            logger.warning("Failed to send invoice notification", exc_info=True)

        return {
            "id": invoice_id,
            "invoice_number": inv_num,
            "customer_name": cust_name,
            "invoice_date": invoice.invoice_date,
            "total": grand_total,
            "status": inv_status,
            "zatca_qr": zatca_qr
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating invoice: {str(e)}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
@invoices_router.get("/invoices/{invoice_id}", response_model=dict, dependencies=[Depends(require_permission("sales.view"))])
def get_invoice(
    invoice_id: int,
    current_user: dict = Depends(get_current_user)
):
    """جلب تفاصيل فاتورة مبيعات محددة"""
    from utils.permissions import validate_branch_access
    
    db = get_db_connection(current_user.company_id)
    try:
        # 1. Fetch Header
        query = """
            SELECT i.*, i.party_id as customer_id, p.name as customer_name 
            FROM invoices i
            JOIN parties p ON i.party_id = p.id
            WHERE i.id = :id AND i.invoice_type = 'sales'
        """
        row = db.execute(text(query), {"id": invoice_id}).fetchone()

        if not row:
            raise HTTPException(**http_error(404, "invoice_not_found"))

        # 1.5 Enforce Branch Access for Single Resource
        # If user is restricted, they must have access to the invoice's branch
        if row.branch_id:
             validate_branch_access(current_user, row.branch_id)

        header = dict(row._mapping)

        # 2. Fetch Lines
        lines_query = """
            SELECT l.*, p.product_name, u.unit_name as unit
            FROM invoice_lines l
            LEFT JOIN products p ON l.product_id = p.id
            LEFT JOIN product_units u ON p.unit_id = u.id
            WHERE l.invoice_id = :id
        """
        lines_result = db.execute(text(lines_query), {"id": invoice_id}).fetchall()

        return {
            **header,
            "items": [dict(r._mapping) for r in lines_result]
        }
    finally:
        db.close()
@invoices_router.post("/invoices/{invoice_id}/cancel", dependencies=[Depends(require_sensitive_permission("sales.void"))], response_model=Dict[str, Any])
def cancel_invoice(
    invoice_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """إلغاء فاتورة مبيعات وعكس جميع القيود والأرصدة"""
    db = get_db_connection(current_user.company_id)
    try:
        from utils.accounting import update_account_balance

        # Get base currency
        base_currency_row = db.execute(text("SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1")).fetchone()
        if not base_currency_row:
            base_currency_row = db.execute(text("SELECT setting_value as code FROM company_settings WHERE setting_key = 'default_currency'")).fetchone()
        base_currency = base_currency_row[0] if base_currency_row else "SYP"

        # 1. Get invoice
        inv = db.execute(text("""
            SELECT id, invoice_number, party_id, total, paid_amount, status,
                   currency, exchange_rate, branch_id, invoice_type
            FROM invoices WHERE id = :id AND invoice_type = 'sales'
        """), {"id": invoice_id}).fetchone()

        if not inv:
            raise HTTPException(**http_error(404, "invoice_not_found"))
        if inv.status == 'cancelled':
            raise HTTPException(status_code=400, detail="الفاتورة ملغاة بالفعل")
        if _dec(inv.paid_amount or 0) > _D2:
            raise HTTPException(status_code=400, detail="لا يمكن إلغاء فاتورة تم السداد عليها. قم بإنشاء مرتجع بدلاً من ذلك")

        exchange_rate = _dec(inv.exchange_rate or 1)
        if exchange_rate <= 0:
            raise HTTPException(status_code=400, detail="سعر الصرف غير صالح")
        total_base = (_dec(inv.total) * exchange_rate).quantize(_D2, ROUND_HALF_UP)

        # 2. Reverse customer balance via party_site_balances
        update_party_site_balance(db, party_id=inv.party_id, branch_id=inv.branch_id,
                                  currency=inv.currency or base_currency, amount=-float(total_base))

        # 3. Reverse inventory (add back the items)
        inv_lines = db.execute(text("""
            SELECT product_id, quantity FROM invoice_lines WHERE invoice_id = :id
        """), {"id": invoice_id}).fetchall()

        # T3.8: if the invoice has product lines, the original posting must
        # have produced inventory_transactions. Fail loudly if those rows are
        # missing so the cancel does not silently skip the stock reversal.
        product_lines = [ln for ln in inv_lines if ln.product_id]
        if product_lines:
            inv_tx_count = db.execute(text("""
                SELECT COUNT(*) FROM inventory_transactions
                WHERE reference_type = 'invoice' AND reference_id = :inv_id
            """), {"inv_id": invoice_id}).scalar() or 0
            if inv_tx_count == 0:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "لا توجد حركات مخزون مرتبطة بهذه الفاتورة — "
                        "لا يمكن إلغاء الفاتورة لأن عكس المخزون غير ممكن. "
                        "تواصل مع المسؤول لمراجعة سلامة البيانات."
                    ),
                )

        for line in inv_lines:
            if line.product_id:
                db.execute(text("""
                    UPDATE inventory SET quantity = quantity + :qty 
                    WHERE product_id = :pid AND warehouse_id = (
                        SELECT warehouse_id FROM inventory_transactions 
                        WHERE reference_id = :inv_id AND reference_type = 'invoice' AND product_id = :pid
                        LIMIT 1
                    )
                """), {"qty": line.quantity, "pid": line.product_id, "inv_id": invoice_id})

        # 4. Reverse GL entries
        # T3.8: locate the originating JE by (source, source_id) instead of the
        # mutable `reference` column. The posting helper writes
        # source='Sales-Invoice', source_id=<invoice id>.
        je = db.execute(text("""
            SELECT id FROM journal_entries
            WHERE source = 'Sales-Invoice' AND source_id = :inv_id
              AND status = 'posted'
            ORDER BY id DESC
            LIMIT 1
        """), {"inv_id": invoice_id}).fetchone()

        if je:
            je_lines = db.execute(text("""
                SELECT account_id, debit, credit, amount_currency, currency
                FROM journal_lines WHERE journal_entry_id = :jid
            """), {"jid": je.id}).fetchall()

            for jl in je_lines:
                if jl.account_id:
                    # Reverse: swap debit/credit
                    update_account_balance(
                        db,
                        account_id=jl.account_id,
                        debit_base=_dec(jl.credit),
                        credit_base=_dec(jl.debit),
                        debit_curr=_dec(jl.amount_currency or 0) if _dec(jl.credit) > 0 else 0,
                        credit_curr=_dec(jl.amount_currency or 0) if _dec(jl.debit) > 0 else 0,
                        currency=jl.currency
                    )

            # Mark original JE as voided
            db.execute(text("UPDATE journal_entries SET status = 'void' WHERE id = :id"), {"id": je.id})

        # 5. Mark invoice as cancelled
        db.execute(text("UPDATE invoices SET status = 'cancelled' WHERE id = :id"), {"id": invoice_id})

        db.commit()
        # T12 — scoped invalidation (cancel)
        invalidate_aggregates(str(current_user.company_id),
                              "invoices", "sales_kpi", "reports",
                              "dashboard", "chart_of_accounts")
        

        log_activity(
            db,
            user_id=current_user.id,
            username=current_user.username,
            action="sales.invoice.cancel",
            resource_type="invoice",
            resource_id=str(invoice_id),
            details={"invoice_number": inv.invoice_number, "total": str(inv.total or 0)},
            request=request,
            branch_id=inv.branch_id
        )

        return {"success": True, "message": "تم إلغاء الفاتورة وعكس جميع القيود بنجاح"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error cancelling invoice: {str(e)}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ===========================================================================
# T16 P1 #44 — Invoice header amendment.
#
# Posted invoices CANNOT be edited in-place — that would invalidate ZATCA
# clearance, break the audit trail, and create a divergence between the GL
# and the printed document. The compliant pattern is:
#
#   * For *non-financial* header changes (notes, customer reference,
#     sales-rep, due-date) on invoices that have NOT been paid / cleared,
#     allow a header-only PATCH below. This is what 90% of "edit my
#     invoice" requests actually want.
#
#   * For *financial* changes (line amounts, products, tax) the only
#     compliant path is: issue a credit-note that fully reverses the
#     original, then create a new invoice. Front-end orchestrates this
#     via the existing ``POST /credit-notes`` + ``POST /invoices`` calls.
# ===========================================================================

class InvoiceHeaderAmend(BaseModel):
    """Editable subset of invoice header fields. All optional — only the
    fields actually present in the request body are updated."""
    notes: Optional[str] = None
    customer_reference: Optional[str] = None
    due_date: Optional[str] = None
    sales_rep_id: Optional[int] = None
    branch_id: Optional[int] = None


_AMENDABLE_HEADER_COLS = {
    "notes": "notes",
    "customer_reference": "customer_reference",
    "due_date": "due_date",
    "sales_rep_id": "sales_rep_id",
    "branch_id": "branch_id",
}


@invoices_router.patch("/invoices/{invoice_id}/header",
                        dependencies=[Depends(require_sensitive_permission("sales.edit"))],
                        response_model=Dict[str, Any])
def amend_invoice_header(invoice_id: int, payload: InvoiceHeaderAmend,
                         request: Request,
                         current_user: dict = Depends(get_current_user)):
    """Amend non-financial header fields on an unpaid, uncancelled invoice.

    Refuses to proceed if:
      * invoice is cancelled,
      * any payment has been allocated to it,
      * the invoice has been ZATCA-cleared (status starts with 'cleared')
        \u2014 a cleared invoice is final by Saudi tax law.
    """
    db = get_db_connection(current_user.company_id)
    try:
        inv = db.execute(text(
            "SELECT id, status, paid_amount, zatca_status FROM invoices WHERE id = :id FOR UPDATE"
        ), {"id": invoice_id}).fetchone()
        if not inv:
            raise HTTPException(status_code=404, detail="Invoice not found")
        if inv.status == "cancelled":
            raise HTTPException(status_code=400, detail="Cancelled invoices cannot be amended")
        if inv.paid_amount and Decimal(str(inv.paid_amount)) > 0:
            raise HTTPException(
                status_code=400,
                detail="Invoice has payments \u2014 issue a credit note rather than amending"
            )
        if (inv.zatca_status or "").startswith("cleared"):
            raise HTTPException(
                status_code=400,
                detail="ZATCA-cleared invoice cannot be amended; use credit note + reissue"
            )

        # Build a SET clause from only the fields actually supplied. Column
        # names come from a fixed whitelist \u2014 never from the request body
        # \u2014 to keep this path SQL-injection-proof.
        body = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else payload.dict(exclude_unset=True)
        sets: List[str] = []
        params: Dict[str, Any] = {"id": invoice_id}
        for k, v in body.items():
            col = _AMENDABLE_HEADER_COLS.get(k)
            if not col:
                continue
            sets.append(f"{col} = :{col}")
            params[col] = v
        if not sets:
            return {"id": invoice_id, "updated_fields": []}

        sets.append("updated_at = NOW()")
        db.execute(text(f"UPDATE invoices SET {', '.join(sets)} WHERE id = :id"), params)
        db.commit()
        try:
            invalidate_aggregates(str(current_user.company_id),
                                  "invoices", "sales_kpi", "reports", "dashboard")
        except Exception:
            pass
        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="sales.invoice.amend_header", resource_type="invoice",
                     resource_id=str(invoice_id),
                     details={"updated_fields": list(body.keys())},
                     request=request)
        return {"id": invoice_id, "updated_fields": list(body.keys())}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("amend_invoice_header failed")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@invoices_router.get("/invoices/{invoice_id}/payment-history", response_model=List[dict], dependencies=[Depends(require_permission("sales.view"))])
def get_invoice_payment_history(invoice_id: int, current_user: dict = Depends(get_current_user)):
    """سجل الدفعات لفاتورة معينة"""
    db = get_db_connection(current_user.company_id)
    try:
        result = db.execute(text("""
            SELECT 
                pv.id as voucher_id,
                pv.voucher_number,
                pv.voucher_date,
                pv.payment_method,
                pa.allocated_amount
            FROM payment_allocations pa
            JOIN payment_vouchers pv ON pa.voucher_id = pv.id
            WHERE pa.invoice_id = :invoice_id
              AND pv.voucher_type = 'receipt'
            ORDER BY pv.voucher_date DESC
        """), {"invoice_id": invoice_id}).fetchall()

        return [dict(row._mapping) for row in result]
    except Exception as e:
        logger.error(f"Error getting payment history: {str(e)}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
