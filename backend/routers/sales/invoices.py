"""Sales invoices endpoints."""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import List, Optional
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import logging
from utils.cache import invalidate_company_cache

_D2 = Decimal('0.01')
_D6 = Decimal('0.000001')
_MAX_RATE_AGE_DAYS = 31
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
from utils.permissions import require_permission, require_sensitive_permission
from utils.accounting import get_mapped_account_id
from utils.fiscal_lock import check_fiscal_period_open
from .schemas import InvoiceCreate, InvoiceResponse

invoices_router = APIRouter()
logger = logging.getLogger(__name__)
@invoices_router.get("/invoices", dependencies=[Depends(require_permission("sales.view"))])
def list_invoices(
    branch_id: Optional[int] = None,
    status_filter: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
    current_user: dict = Depends(get_current_user)
):
    """عرض قائمة فواتير المبيعات مع ترقيم الصفحات"""
    from utils.permissions import validate_branch_access
    # Enforce branch access
    branch_id = validate_branch_access(current_user, branch_id)
    
    db = get_db_connection(current_user.company_id)
    try:
        where_clauses = ["i.invoice_type = 'sales'"]
        params = {}

        if branch_id:
            where_clauses.append("i.branch_id = :branch_id")
            params["branch_id"] = branch_id
        if status_filter:
            where_clauses.append("i.status = :status")
            params["status"] = status_filter
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
                   i.currency, i.exchange_rate
            FROM invoices i
            JOIN parties p ON i.party_id = p.id
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

        line_dicts = [
            {
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "tax_rate": item.tax_rate,
                "discount": item.discount,
            }
            for item in invoice.items
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
        )
        subtotal = totals["subtotal"]
        total_tax = totals["total_tax"]
        total_discount = totals["total_discount"]
        grand_total = totals["grand_total"]

        # Rebuild items_to_save with per-line totals (same helper used by the aggregator)
        items_to_save = []
        for item in invoice.items:
            la = compute_line_amounts(
                item.quantity, item.unit_price, item.tax_rate, item.discount
            )
            items_to_save.append({
                **item.model_dump(),
                "total": la["line_total"],
            })

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

        # --- 4. Credit Limit Check (CONC-FIX: lock party row to prevent concurrent bypass) ---
        customer = db.execute(text("SELECT credit_limit, current_balance FROM parties WHERE id = :id FOR UPDATE"), {"id": invoice.customer_id}).fetchone()
        if customer and customer.credit_limit > 0:
            # Check in BASE currency
            new_balance = _dec(customer.current_balance or 0) + remaining_gl
            if new_balance > _dec(customer.credit_limit):
                raise HTTPException(
                    status_code=400,
                    detail=f"تجاوز الحد الائتماني. الحد: {customer.credit_limit}, الرصيد الحالي: {customer.current_balance}, المطلوب: {remaining_gl}"
                )

        # --- 5. Save Invoice Header (schema-drift tolerant) ---
        invoice_cols = {
            row.column_name
            for row in db.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'invoices'
            """)).fetchall()
        }

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
            "cust": invoice.customer_id,
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
            "branch": invoice.branch_id,
            "wh": invoice.warehouse_id,
        }

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

        invoice_line_cols = {
            row.column_name
            for row in db.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'invoice_lines'
            """)).fetchall()
        }
        has_line_markup_col = "markup" in invoice_line_cols

        for item in items_to_save:
            if has_line_markup_col:
                line_sql = """
                    INSERT INTO invoice_lines (
                        invoice_id, product_id, description, quantity, unit_price, tax_rate, discount, markup, total
                    ) VALUES (
                        :inv_id, :pid, :desc, :qty, :price, :tax_rate, :disc, :markup, :total
                    )
                """
            else:
                line_sql = """
                    INSERT INTO invoice_lines (
                        invoice_id, product_id, description, quantity, unit_price, tax_rate, discount, total
                    ) VALUES (
                        :inv_id, :pid, :desc, :qty, :price, :tax_rate, :disc, :total
                    )
                """

            db.execute(text(line_sql), {
                "inv_id": invoice_id, "pid": item["product_id"], "desc": item["description"],
                "qty": item["quantity"], "price": item["unit_price"], "tax_rate": item["tax_rate"],
                "disc": item["discount"], "markup": item.get("markup", 0), "total": item["total"]
            })

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

        # --- 6.5 Update Customer Balance (Base + Currency) ---
        db.execute(text("""
            UPDATE parties SET current_balance = current_balance + :amt
            WHERE id = :id
        """), {"amt": remaining_gl, "id": invoice.customer_id})

        if inv_currency and inv_currency != base_currency:
            db.execute(text("""
                UPDATE parties SET balance_currency = COALESCE(balance_currency, 0) + :amt
                WHERE id = :id
            """), {"amt": remaining_balance, "id": invoice.customer_id})

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
                    "user": current_user.id, "branch": invoice.branch_id,
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
                    "account_id": acc_cash, "debit": gl_paid, "credit": 0,
                    "description": f"Sales Cash - {inv_num}",
                    "amount_currency": paid_amount, "currency": inv_currency
                })
            elif pay_src in ('bank', 'check'):
                je_lines.append({
                    "account_id": acc_bank, "debit": gl_paid, "credit": 0,
                    "description": f"Sales {pay_src.capitalize()} - {inv_num}",
                    "amount_currency": paid_amount, "currency": inv_currency
                })

        if remaining_gl > _D2:
             je_lines.append({
                 "account_id": acc_ar, "debit": remaining_gl, "credit": 0,
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
                "account_id": acc_sales, "debit": 0, "credit": net_sales_gl,
                "description": f"Sales Revenue - {inv_num}",
                "amount_currency": net_sales, "currency": inv_currency
            })

        # C. VAT Output (Credit)
        if gl_tax > 0:
            je_lines.append({
                "account_id": acc_vat_out, "debit": 0, "credit": gl_tax,
                "description": f"VAT Output - {inv_num}",
                "amount_currency": total_tax, "currency": inv_currency
            })

        # D. COGS & Inventory (Perpetual Inventory)
        # Always Base Currency
        if total_cogs > 0:
            je_lines.append({
                "account_id": acc_cogs, "debit": total_cogs, "credit": 0,
                "description": f"COGS - {inv_num}",
                "amount_currency": total_cogs, "currency": base_currency
            })
            je_lines.append({
                "account_id": acc_inventory, "debit": 0, "credit": total_cogs,
                "description": f"Inventory Redn - {inv_num}",
                "amount_currency": total_cogs, "currency": base_currency
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
                branch_id=invoice.branch_id,
                reference=inv_num,
                currency=inv_currency,
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
        invalidate_company_cache(str(current_user.company_id))
        

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
            branch_id=invoice.branch_id
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
                    "grand_total": float(grand_total),
                    "tax_total": float(invoice.tax_amount or 0),
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
            pass

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
@invoices_router.post("/invoices/{invoice_id}/cancel", dependencies=[Depends(require_sensitive_permission("sales.void"))])
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

        # 2. Reverse customer balance
        db.execute(text("""
            UPDATE parties SET current_balance = current_balance - :amt WHERE id = :id
        """), {"amt": total_base, "id": inv.party_id})

        if inv.currency and inv.currency != base_currency:
            db.execute(text("""
                UPDATE parties SET balance_currency = COALESCE(balance_currency, 0) - :amt WHERE id = :id
            """), {"amt": _dec(inv.total), "id": inv.party_id})

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
            db.execute(text("UPDATE journal_entries SET status = 'voided' WHERE id = :id"), {"id": je.id})

        # 5. Mark invoice as cancelled
        db.execute(text("UPDATE invoices SET status = 'cancelled' WHERE id = :id"), {"id": invoice_id})

        db.commit()
        invalidate_company_cache(str(current_user.company_id))
        

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
