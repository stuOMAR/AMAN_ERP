"""Purchases sub-router — split from monolithic purchases.py (T6.3).

This file is auto-generated when purchases.py was split. Endpoints here
are mounted under the parent /buying prefix via purchases/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request, Header
from utils.i18n import http_error, i18n_message
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
import logging

from utils.cache import invalidate_company_cache
from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.audit import log_activity
from utils.permissions import require_permission, require_module, require_sensitive_permission, resolve_branch_scope, validate_branch_access, validate_treasury_account_access, check_permission
from utils.accounting import get_mapped_account_id, generate_sequential_number, get_base_currency
from utils.fiscal_lock import check_fiscal_period_open
from utils.party_balance import update_party_site_balance
from utils.decimal_helper import dec as _dec, D2 as _D2, D4 as _D4
from utils.tax_precision import require_idempotency_key
from services.gl_service import create_journal_entry as gl_create_journal_entry
from services.tax_engine import resolve_line_tax
from schemas.purchases import (
    PurchaseCreate, SupplierGroupCreate, POCreate, POReceiveRequest,
    SupplierPaymentCreate,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _require_account_map(db, key: str, label_ar: str) -> int:
    """Return required mapped account id or raise a clear 400 if missing."""
    acc_id = get_mapped_account_id(db, key)
    if not acc_id:
        raise HTTPException(
            status_code=400,
            detail=f"لم يتم ضبط حساب {label_ar} في إعدادات ربط الحسابات ({key})"
        )
    return int(acc_id)


def _parties_has_balance_currency(db) -> bool:
    """Return True when tenant parties table has balance_currency column."""
    return bool(db.execute(text("""
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'parties'
              AND column_name = 'balance_currency'
        )
    """)).scalar())


@router.post("/invoices/preview", dependencies=[Depends(require_permission("buying.create"))])
def preview_purchase_invoice_totals(request: Request, invoice: PurchaseCreate, current_user: dict = Depends(get_current_user)):
    """حساب إجماليات فاتورة المشتريات بدون حفظ"""
    from utils.accounting import compute_invoice_totals, compute_line_amounts

    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
        # Validate branch
        if not invoice.branch_id:
            raise HTTPException(**http_error(400, "branch_required", request))
        validate_branch_access(current_user, invoice.branch_id)

        from utils.tax_precision import money_str, rate_str

        line_details = []
        preview_lines_data = []
        for item in invoice.items:
            tax_info = resolve_line_tax(invoice.branch_id, item.product_id, db, invoice.invoice_date, customer_id=invoice.supplier_id)
            effective_tax_rate = tax_info["tax_rate"]
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


@router.get("/invoices", dependencies=[Depends(require_permission("buying.view"))], response_model=List[dict])
def list_purchase_invoices(
    supplier_id: Optional[int] = None,
    branch_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(get_current_user)
):
    """عرض فواتير المشتريات"""
    from repositories import InvoiceRepository
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    branch_scope = resolve_branch_scope(current_user, branch_id)
    with transactional(company_id) as db:
        repo = InvoiceRepository(db)
        base_currency = get_base_currency(db)
        rows = repo.list(
            invoice_type="purchase",
            party_id=supplier_id,
            branch_id=branch_scope["branch_id"],
            branch_ids=branch_scope["branch_ids"],
            limit=limit,
            offset=skip,
        )
        return [
            {
                "id": r["id"],
                "invoice_number": r["invoice_number"],
                "supplier_name": r["party_name"],
                "invoice_date": r["invoice_date"],
                "total": r["total"],
                "currency": r.get("currency") or base_currency,
                "exchange_rate": r.get("exchange_rate") or 1,
                "base_currency": base_currency,
                "total_base": str(_dec(r["total"]) * _dec(r.get("exchange_rate") or 1)),
                "status": r["status"],
            }
            for r in rows
        ]

# NOTE: Supplier CRUD endpoints consolidated in inventory/suppliers.py
# The frontend uses inventoryAPI for all supplier operations.
# Purchase-specific supplier helpers (outstanding invoices, transactions) remain below.

@router.get("/invoices/{id}", dependencies=[Depends(require_permission("buying.view"))], response_model=dict)
def get_purchase_invoice(
    id: int,
    current_user: dict = Depends(get_current_user)
):
    """جلب تفاصيل فاتورة مشتريات مع المنتجات"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
        # 1. Fetch Invoice Header
        invoice = db.execute(text("""
            SELECT i.*, p.name as supplier_name, p.party_code as supplier_code
            FROM invoices i
            JOIN parties p ON i.party_id = p.id
            WHERE i.id = :id AND i.invoice_type = 'purchase'
        """), {"id": id}).fetchone()

        if not invoice:
            raise HTTPException(**http_error(404, "invoice_not_found"))

        from utils.permissions import validate_branch_access
        validate_branch_access(current_user, invoice.branch_id)

        # Get base currency for fallback
        base_currency = get_base_currency(db)

        # 2. Fetch Invoice Lines
        lines = db.execute(text("""
            SELECT il.*, p.product_name, p.product_code
            FROM invoice_lines il
            LEFT JOIN products p ON il.product_id = p.id
            WHERE il.invoice_id = :id
        """), {"id": id}).fetchall()

        # 2.5 Calculate Returned Quantities
        # Fetch sum of quantities from all Return Invoices linked to this Reference Invoice
        returned_stats = db.execute(text("""
            SELECT il.product_id, SUM(il.quantity) as returned_qty
            FROM invoice_lines il
            JOIN invoices i ON il.invoice_id = i.id
            WHERE i.related_invoice_id = :id
              AND i.invoice_type = 'purchase_return'
              AND i.status != 'void'
            GROUP BY il.product_id
        """), {"id": id}).fetchall()

        returned_map = {row.product_id: _dec(row.returned_qty or 0) for row in returned_stats}

        # 3. Construct Response
        return {
            "id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "invoice_date": invoice.invoice_date,
            "due_date": invoice.due_date,
            "supplier_id": invoice.party_id,
            "supplier_name": invoice.supplier_name,
            "status": invoice.status,
            "subtotal": invoice.subtotal,
            "tax_amount": invoice.tax_amount,
            "discount": invoice.discount,
            "total": invoice.total,
            "paid_amount": str(invoice.paid_amount or 0),
            "currency": invoice.currency or base_currency,
            "exchange_rate": str(invoice.exchange_rate or Decimal("1")),
            "notes": invoice.notes,
            "items": [{
                "id": l.id,
                "product_id": l.product_id,
                "product_name": l.product_name or l.description,
                "description": l.description,
                "quantity": l.quantity,
                "unit_price": l.unit_price,
                "tax_rate": l.tax_rate,
                "discount": l.discount,
                "total": l.total,
                "returned_quantity": str(returned_map.get(l.product_id, Decimal('0'))),
                "remaining_quantity": str(max(Decimal('0'), _dec(l.quantity) - returned_map.get(l.product_id, Decimal('0'))))
            } for l in lines]
        }

@router.post("/invoices", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("buying.create"))], response_model=Dict[str, Any])
async def create_purchase_invoice(
    invoice: PurchaseCreate,
    request: Request,
    # M6: Idempotency-Key prevents double-submit / network-retry duplicates.
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key", max_length=64),
    current_user: dict = Depends(get_current_user)
):
    """إنشاء فاتورة مشتريات (إضافة للمخزون + قيد محاسبي)"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
        try:
            idempotency_key = require_idempotency_key(request, operation="purchase invoice")
            # M6: replay guard — return the existing invoice if this key
            # was already processed.
            existing_inv = db.execute(text("""
                SELECT id, invoice_number FROM invoices
                WHERE idempotency_key = :key
                  AND invoice_type = 'purchase'
                LIMIT 1
            """), {"key": idempotency_key}).fetchone()
            if existing_inv:
                return {"success": True, "invoice_id": existing_inv.id,
                        "invoice_number": existing_inv.invoice_number,
                        "idempotent_replay": True}

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

            base_currency = base_currency_row[0] if base_currency_row else "SAR"

            po_header = None
            if invoice.original_invoice_id:
                po_header = db.execute(text("""
                    SELECT id, party_id, branch_id, status, currency, exchange_rate
                    FROM purchase_orders
                    WHERE id = :po_id
                    FOR UPDATE
                """), {"po_id": invoice.original_invoice_id}).fetchone()
                if not po_header:
                    raise HTTPException(**http_error(404, "po_not_found", request))
                if int(po_header.party_id) != int(invoice.supplier_id):
                    raise HTTPException(**http_error(400, "po_supplier_mismatch", request))
                if po_header.status not in ("approved", "partial", "received"):
                    raise HTTPException(**http_error(400, "po_status_invalid", request))

                po_branch_id = po_header.branch_id
                requested_branch_id = invoice.branch_id
                if requested_branch_id and po_branch_id and int(requested_branch_id) != int(po_branch_id):
                    raise HTTPException(**http_error(400, "invoice_branch_mismatch_po", request))
                validated_branch_id = validate_branch_access(current_user, po_branch_id or requested_branch_id)
                if po_header.currency and invoice.currency and po_header.currency != invoice.currency:
                    raise HTTPException(**http_error(400, "invoice_currency_mismatch_po", request))

            inv_currency = invoice.currency or (po_header.currency if po_header else None) or base_currency
            exchange_rate = _dec(invoice.exchange_rate or (po_header.exchange_rate if po_header else 1) or 1)

            def conversion_rate_needed(rate_val):
                d_rate = _dec(rate_val)
                return rate_val is None or d_rate <= 0 or d_rate == Decimal('1')

            # If currency is different from base and no rate provided, fetch latest rate
            if inv_currency != base_currency and conversion_rate_needed(exchange_rate):
                 rate_row = db.execute(text("""
                    SELECT rate FROM exchange_rates
                    WHERE currency_id = (SELECT id FROM currencies WHERE code = :code)
                    AND rate_date <= :date
                    ORDER BY rate_date DESC LIMIT 1
                 """), {"code": inv_currency, "date": invoice.invoice_date}).fetchone()

                 if not rate_row:
                     raise HTTPException(status_code=400, detail=i18n_message("no_exchange_rate_for_currency", request))
                 exchange_rate = _dec(rate_row.rate)

            if inv_currency != base_currency and exchange_rate <= 0:
                raise HTTPException(**http_error(400, "exchange_rate_must_be_positive", request))

            def to_base(amount):
                return (_dec(amount) * exchange_rate).quantize(_D2, ROUND_HALF_UP)
            effective_branch_id = validated_branch_id or invoice.branch_id
            # 1. Generate Sequential Invoice Number
            from utils.accounting import generate_sequential_number
            inv_num = generate_sequential_number(db, f"PINV-{datetime.now().year}", "invoices", "invoice_number", branch_id=effective_branch_id)

            # FISCAL-LOCK: Reject if accounting period is closed
            check_fiscal_period_open(db, invoice.invoice_date)

            # 2. Preparation (Warehouse)
            wh_id = invoice.warehouse_id
            if not wh_id:
                 wh_id = db.execute(text("SELECT id FROM warehouses WHERE is_default = TRUE")).scalar() or 1

            # 2.5 Validate Warehouse-Branch Association
            if wh_id and effective_branch_id:
                wh_check = db.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": wh_id}).fetchone()
                if wh_check and wh_check[0] and wh_check[0] != effective_branch_id:
                    raise HTTPException(**http_error(400, "warehouse_not_in_current_branch", request))

            # 2.6 Check for linked PO and fetch received/invoiced quantities
            po_line_map = {}  # po_line_id -> {received_qty, invoiced_qty, product_id}
            if invoice.original_invoice_id:
                po_lines = db.execute(text("""
                    SELECT id, product_id, received_quantity, invoiced_quantity
                    FROM purchase_order_lines
                    WHERE po_id = :po_id
                    FOR UPDATE
                """), {"po_id": invoice.original_invoice_id}).fetchall()
                for pol in po_lines:
                    po_line_map[pol.id] = {
                        "product_id": pol.product_id,
                        "received_qty": _dec(pol.received_quantity or 0),
                        "invoiced_qty": _dec(pol.invoiced_quantity or 0),
                    }

                # QA-F1: block invoicing when a linked quality inspection has FAILED.
                try:
                    failed_insp = db.execute(text("""
                        SELECT COUNT(*) FROM quality_inspections
                        WHERE reference_type = 'purchase_order'
                          AND reference_id = :po_id
                          AND UPPER(COALESCE(status, '')) IN ('FAILED', 'REJECTED')
                    """), {"po_id": invoice.original_invoice_id}).scalar() or 0
                    if failed_insp > 0:
                        raise HTTPException(**http_error(400, "purchase_invoice_blocked_qc_fail", request))
                except HTTPException:
                    raise
                except Exception:
                    # quality_inspections table may not exist on some tenants; skip silently.
                    logger.debug("Skipping purchase invoice quality inspection check", exc_info=True)

            # 3. Calculate Totals (tax resolved via engine)
            from utils.accounting import compute_invoice_totals as _cit, compute_line_amounts as _cla

            lines_data = []
            _branch_id = validated_branch_id or invoice.branch_id
            _doc_date = invoice.invoice_date if hasattr(invoice, 'invoice_date') and invoice.invoice_date else None
            for item in invoice.items:
                tax_info = resolve_line_tax(_branch_id, item.product_id, db, _doc_date, customer_id=invoice.supplier_id)
                la = _cla(
                    item.quantity,
                    item.unit_price,
                    tax_info["tax_rate"],
                    item.discount,
                    discount_is_percent=False,
                )
                lines_data.append({
                    "product_id": item.product_id,
                    "po_line_id": item.po_line_id,
                    "description": item.description,
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                    "tax_rate": tax_info["tax_rate"],
                    "tax_rate_id": tax_info["tax_rate_id"],
                    "discount": item.discount,
                    "markup": getattr(item, "markup", 0.0),
                    "total": la["line_total"],
                })

            header_discount_pct = (
                _dec(invoice.effect_percentage)
                if getattr(invoice, "effect_type", "discount") == "discount"
                else Decimal("0")
            )
            markup_amount = (
                _dec(invoice.markup_amount)
                if getattr(invoice, "effect_type", "discount") == "markup"
                else Decimal("0")
            )

            _totals = _cit([
                {
                    "quantity": it["quantity"],
                    "unit_price": it["unit_price"],
                    "tax_rate": it["tax_rate"],
                    "discount": it["discount"],
                }
                for it in lines_data
            ], header_discount_pct=header_discount_pct, markup_amount=markup_amount, discount_is_percent=False)
            subtotal = _totals["subtotal"]
            total_tax = _totals["total_tax"]
            total_discount = _totals["total_discount"]
            grand_total = _totals["grand_total"]

            # 3. Handle Payment & Debt
            paid_amount = _dec(invoice.paid_amount)
            if invoice.payment_method in ["cash", "bank"] and paid_amount == 0:
                paid_amount = grand_total

            # AUDIT-H7: a purchase invoice with paid_amount > 0 (or a
            # cash/bank payment_method) implicitly creates a supplier
            # payment voucher and posts a treasury movement further
            # down. The original endpoint only required `buying.create`,
            # which let any user with invoice-creation rights move cash
            # without an explicit payment authorisation. We now require
            # `treasury.create` (or `buying.manage`/`*` for managers) when
            # the invoice carries a payment.
            if paid_amount > 0:
                user_perms = current_user.get("permissions", []) if isinstance(current_user, dict) else (getattr(current_user, "permissions", []) or [])
                has_payment_right = (
                    "*" in user_perms
                    or check_permission(user_perms, "treasury.create")
                    or check_permission(user_perms, "buying.manage")
                )
                if not has_payment_right:
                    raise HTTPException(**http_error(403, "purchase_invoice_payment_requires_treasury_permission", request))

            remaining_balance = grand_total - paid_amount

            # Determine Status
            inv_status = "paid"
            if remaining_balance > _D2:
                inv_status = "partial" if paid_amount > 0 else "unpaid"

            # 4. Insert Invoice Header. The idempotency key is written in the
            # initial INSERT so concurrent retries race on the unique index
            # before any stock / AP / GL side effects are created.
            insert_sql = """
                INSERT INTO invoices (
                    invoice_number, invoice_type, party_id, invoice_date, due_date,
                    subtotal, tax_amount, discount, total, paid_amount, status, notes,
                    down_payment_method, created_by, branch_id, warehouse_id,
                    currency, exchange_rate, effect_type, effect_percentage, markup_amount,
                    idempotency_key
                ) VALUES (
                    :num, 'purchase', :party_id, :date, :due,
                    :sub, :tax, :disc, :total, :paid, :status, :notes,
                    :dp_method, :user, :branch, :wh,
                    :currency, :exchange_rate, :effect_type, :effect_perc, :markup_amt,
                    :idempotency_key
                )
            """
            if idempotency_key:
                insert_sql += """
                ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL
                DO NOTHING
                """
            insert_sql += " RETURNING id"

            result = db.execute(text(insert_sql), {
                "num": inv_num,
                "party_id": invoice.supplier_id,
                "date": invoice.invoice_date,
                "due": invoice.due_date,
                "sub": subtotal,
                "tax": total_tax,
                "disc": total_discount,
                "total": grand_total,
                "paid": paid_amount,
                "status": inv_status,
                "notes": invoice.notes,
                "dp_method": invoice.down_payment_method,
                "user": current_user.get("id") if isinstance(current_user, dict) else current_user.id,
                "branch": effective_branch_id,
                "wh": wh_id,
                "currency": inv_currency,
                "exchange_rate": exchange_rate,
                "effect_type": invoice.effect_type,
                "effect_perc": invoice.effect_percentage,
                "markup_amt": invoice.markup_amount,
                "idempotency_key": idempotency_key
            }).fetchone()

            if not result and idempotency_key:
                existing_inv = db.execute(text("""
                    SELECT id, invoice_number FROM invoices
                    WHERE idempotency_key = :key
                    LIMIT 1
                """), {"key": idempotency_key}).fetchone()
                if existing_inv:
                    return {"success": True, "invoice_id": existing_inv.id,
                            "invoice_number": existing_inv.invoice_number,
                            "idempotent_replay": True}
                raise HTTPException(**http_error(409, "duplicate_idempotency_key", request))

            invoice_id = result[0]

            # Update party_site_id if provided
            if invoice.party_site_id:
                db.execute(text("UPDATE invoices SET party_site_id = :sid WHERE id = :iid"),
                          {"sid": invoice.party_site_id, "iid": invoice_id})

            # 5. Insert Invoice Lines & Update Stock
            receipt_accrual_reversal_base = Decimal('0')
            invoice_stock_addition_base = Decimal('0')

            for line in lines_data:
                # Calculate cost in base currency
                new_price_fc = _dec(line["unit_price"])
                new_price_bc = to_base(new_price_fc)

                db.execute(text("""
                    INSERT INTO invoice_lines (
                        invoice_id, product_id, po_line_id, description, quantity, unit_price,
                        tax_rate, tax_rate_id, discount, markup, total, unit_cost
                    ) VALUES (
                        :inv_id, :pid, :po_line_id, :desc, :qty, :price, :tax_rate, :tax_rate_id, :disc, :markup, :total, :unit_cost
                    )
                """), {
                    "inv_id": invoice_id,
                    "pid": line["product_id"],
                    "po_line_id": line.get("po_line_id"),
                    "desc": line["description"],
                    "qty": line["quantity"],
                    "price": line["unit_price"],
                    "tax_rate": line["tax_rate"],
                    "tax_rate_id": line.get("tax_rate_id"),
                    "disc": line["discount"],
                    "markup": line.get("markup", 0.0),
                    "total": line["total"],
                    "unit_cost": new_price_bc
                })

                # Stock Update & WAC Calculation
                if line["product_id"] and not invoice.is_prepayment:
                    from services.costing_service import CostingService

                    new_price_fc = _dec(line["unit_price"])
                    new_price_bc = to_base(new_price_fc)

                    # T041: Split into qty_already_received and qty_to_add
                    po_line_id = line.get("po_line_id")
                    po_line_info = po_line_map.get(po_line_id) if po_line_id else None
                    received_qty = po_line_info["received_qty"] if po_line_info else Decimal('0')
                    invoice_qty = _dec(line["quantity"])

                    # T014: Cumulative invoiced quantity validation
                    if po_line_id and po_line_info:
                        if int(po_line_info["product_id"]) != int(line["product_id"]):
                            raise HTTPException(
                                status_code=400,
                                detail=f"بند أمر الشراء {po_line_id} لا يطابق الصنف في الفاتورة"
                            )
                        already_invoiced = po_line_info["invoiced_qty"]
                        remaining_to_invoice = po_line_info["received_qty"] - already_invoiced
                        if remaining_to_invoice <= 0:
                            if po_line_info["received_qty"] <= 0:
                                raise HTTPException(
                                    status_code=400,
                                    detail="لم يتم استلام أي كمية لهذا البند بعد"
                                )
                            raise HTTPException(
                                status_code=400,
                                detail=f"تم فوترة الكمية المستلمة بالفعل للبند {po_line_id}"
                            )
                        if invoice_qty > remaining_to_invoice:
                            raise HTTPException(
                                status_code=400,
                                detail=i18n_message("qty_exceeds_remaining", request)
                            )
                        # T015: Update invoiced_quantity on PO line
                        updated_invoice_qty = db.execute(text("""
                            UPDATE purchase_order_lines
                            SET invoiced_quantity = invoiced_quantity + :qty
                            WHERE id = :line_id
                              AND invoiced_quantity + :qty <= received_quantity
                        """), {"qty": invoice_qty, "line_id": po_line_id})
                        if updated_invoice_qty.rowcount == 0:
                            raise HTTPException(
                                status_code=409,
                                detail=f"تم تغيير الكمية المفوترة للبند {po_line_id} أثناء إنشاء الفاتورة"
                            )
                    elif invoice.original_invoice_id:
                        raise HTTPException(**http_error(400, "po_line_id_required_for_invoice", request))

                    qty_already_received = Decimal('0')
                    qty_to_add = invoice_qty

                    if invoice.original_invoice_id and po_line_info:
                        qty_already_received = min(invoice_qty, received_qty)
                        qty_to_add = max(0, invoice_qty - received_qty)

                        # T042: Post price variance for already-received qty
                        if qty_already_received > 0:
                            # T017: Use po_line_id for precise receipt cost lookup
                            receipt_cost_row = db.execute(text("""
                                SELECT COALESCE(
                                           SUM(total_cost) / NULLIF(SUM(quantity), 0),
                                           MAX(unit_cost),
                                           0
                                       ) AS unit_cost,
                                       COUNT(*) AS tx_count
                                FROM po_receipt_lines
                                WHERE po_line_id = :po_line_id
                                  AND product_id = :pid
                                  AND quantity > 0
                            """), {"po_line_id": po_line_id, "pid": line["product_id"]}).fetchone()
                            if not receipt_cost_row or _dec(receipt_cost_row.tx_count) <= 0:
                                raise HTTPException(**http_error(400, "no_grn_linked_to_po", request))
                            receipt_unit_cost = _dec(receipt_cost_row.unit_cost)
                            receipt_accrual_reversal_base += (qty_already_received * receipt_unit_cost).quantize(_D2, ROUND_HALF_UP)

                    # T041: Only update cost and create layers for qty_to_add
                    if qty_to_add > 0:
                        invoice_stock_addition_base += (qty_to_add * new_price_bc).quantize(_D2, ROUND_HALF_UP)
                        CostingService.update_cost(
                            db,
                            product_id=line["product_id"],
                            warehouse_id=wh_id,
                            new_qty=str(qty_to_add),
                            new_price=new_price_bc
                        )

                        method = CostingService._get_product_costing_method(db, line["product_id"], wh_id)
                        if method in ("fifo", "lifo"):
                            CostingService.create_cost_layer(
                                db,
                                product_id=line["product_id"],
                                warehouse_id=wh_id,
                                quantity=str(qty_to_add),
                                unit_cost=new_price_bc,
                                source_document_type="purchase_invoice",
                                source_document_id=invoice_id,
                                costing_method=method,
                            )

                        # Update Inventory Quantity (only for qty_to_add)
                        inv_exists = db.execute(text("""
                            SELECT id FROM inventory WHERE product_id = :pid AND warehouse_id = :wh
                            FOR UPDATE
                        """), {"pid": line["product_id"], "wh": wh_id}).fetchone()

                        if inv_exists:
                            db.execute(text("""
                                UPDATE inventory SET quantity = quantity + :qty,
                                    updated_at = NOW()
                                WHERE product_id = :pid AND warehouse_id = :wh
                            """), {"qty": qty_to_add, "pid": line["product_id"], "wh": wh_id})
                        else:
                            db.execute(text("""
                                INSERT INTO inventory (product_id, warehouse_id, quantity, average_cost)
                                VALUES (:pid, :wh, :qty, :cost)
                                ON CONFLICT (product_id, warehouse_id)
                                DO UPDATE SET quantity = inventory.quantity + EXCLUDED.quantity,
                                              updated_at = NOW()
                            """), {"pid": line["product_id"], "wh": wh_id, "qty": qty_to_add, "cost": new_price_bc})

                    # T041: Log Inventory Transaction ONLY for qty_to_add
                    if qty_to_add > 0:
                        from utils.inventory_constants import TX_PURCHASE_INVOICE
                        db.execute(text("""
                            INSERT INTO inventory_transactions (
                                product_id, warehouse_id, transaction_type,
                                reference_type, reference_id, reference_document,
                                quantity, unit_cost, total_cost, created_by
                            ) VALUES (
                                :pid, :wh, :tx_type, 'invoice', :inv_id, :inv_num,
                                :qty, :cost, :total_cost, :user
                            )
                        """), {
                            "pid": line["product_id"],
                            "wh": wh_id,
                            "tx_type": TX_PURCHASE_INVOICE,
                            "inv_id": invoice_id,
                            "inv_num": inv_num,
                            "qty": qty_to_add,
                            "cost": new_price_bc,
                            "total_cost": (qty_to_add * new_price_bc).quantize(_D2, ROUND_HALF_UP),
                            "user": current_user.get("id") if isinstance(current_user, dict) else current_user.id
                        })

            # 6. Update Supplier Balance via party_site_balances
            if remaining_balance > _D2:
                gl_remaining = to_base(remaining_balance)
                update_party_site_balance(
                    db,
                    party_id=invoice.supplier_id,
                    branch_id=effective_branch_id,
                    currency=inv_currency,
                    amount=-remaining_balance,
                    document_type="purchase_invoice",
                )

            # 7. Record Payment Transaction
            if paid_amount and paid_amount > 0:
                from utils.accounting import generate_sequential_number
                v_num = generate_sequential_number(db, f"PAY-{datetime.now().year}", "payment_vouchers", "voucher_number")
                # Determine actual payment method for the voucher
                # If main method is 'credit', check down_payment_method
                actual_method = invoice.payment_method
                if invoice.payment_method == 'credit':
                    actual_method = invoice.down_payment_method or 'cash'

                pay_id = db.execute(text("""
                    INSERT INTO payment_vouchers (
                        voucher_number, voucher_type, voucher_date,
                        party_type, party_id, amount, payment_method,
                        reference, status, created_by,
                        currency, exchange_rate, treasury_account_id, branch_id
                    ) VALUES (
                        :num, 'payment', :date,
                        'supplier', :pid, :amt, :method,
                        :ref, 'posted', :user,
                        :currency, :exchange_rate, :treasury_id, :branch_id
                    ) RETURNING id
                """), {
                    "num": v_num,
                    "date": invoice.invoice_date,
                    "pid": invoice.supplier_id,
                    "amt": paid_amount,
                    "method": actual_method,
                    "ref": f"Payment for {inv_num}",
                    "user": current_user.get("id") if isinstance(current_user, dict) else current_user.id,
                    "currency": inv_currency,
                    "exchange_rate": exchange_rate,
                    "treasury_id": invoice.treasury_id,
                    "branch_id": effective_branch_id
                }).scalar()

                # Create Allocation
                db.execute(text("""
                    INSERT INTO payment_allocations (voucher_id, invoice_id, allocated_amount)
                    VALUES (:pid, :iid, :amt)
                """), {
                    "pid": pay_id,
                    "iid": invoice_id,
                    "amt": paid_amount
                })
            # 8. GL Entry (Automated using Dynamic Mappings)
            # F-31: book purchase against the destination warehouse's
            # inventory account so per-warehouse valuation is real. The
            # prepayment branch keeps using the global supplier-prepayment
            # mapping because no goods have been received yet.
            if invoice.is_prepayment:
                acc_inventory = _require_account_map(db, "acc_map_prepayment_supplier", "دفعة مقدمة للمورد")
            else:
                from utils.inventory_accounts import resolve_warehouse_inventory_account
                acc_inventory = resolve_warehouse_inventory_account(db, wh_id)
                if not acc_inventory:
                    raise HTTPException(
                        status_code=400,
                        detail=f"لم يتم ضبط حساب المخزون في إعدادات ربط الحسابات (acc_map_inventory)"
                    )

            acc_vat_in = _require_account_map(db, "acc_map_vat_in", "ضريبة مدخلات") if _dec(total_tax) > _D2 else None

            # Calculate Base Currency Amounts for GL (must be before acc_ap check)
            gl_total = to_base(grand_total)
            gl_subtotal = to_base(subtotal)
            gl_tax = to_base(total_tax)
            gl_paid = to_base(paid_amount)
            gl_net_purchases = gl_subtotal - to_base(total_discount)

            acc_ap = _require_account_map(db, "acc_map_ap", "الذمم الدائنة") if (gl_total - gl_paid) > _D2 else None
            acc_cash = get_mapped_account_id(db, "acc_map_cash_main")
            acc_bank = get_mapped_account_id(db, "acc_map_bank")
            acc_purchase_variance = (
                get_mapped_account_id(db, "acc_map_purchase_variance")
                or get_mapped_account_id(db, "acc_map_price_variance")
                or get_mapped_account_id(db, "acc_map_expense_other")
            )

            je_lines = []

            # A. Inventory (Debit) - Net of Discount (Base Currency)
            # Handle Accrual Reversal if created from PO
            gl_inventory_debit = gl_net_purchases - receipt_accrual_reversal_base
            gl_stock_addition = invoice_stock_addition_base if invoice.original_invoice_id else Decimal('0')
            gl_purchase_variance = gl_inventory_debit - gl_stock_addition

            # FC equivalents for amount_currency
            fc_net_purchases = subtotal - total_discount
            fc_accrual_reversal = (receipt_accrual_reversal_base / exchange_rate).quantize(_D2, ROUND_HALF_UP) if exchange_rate != 0 else Decimal('0')
            fc_inventory_debit = fc_net_purchases - fc_accrual_reversal
            fc_stock_addition = (gl_stock_addition / exchange_rate).quantize(_D2, ROUND_HALF_UP) if exchange_rate != 0 else Decimal('0')
            fc_purchase_variance = fc_inventory_debit - fc_stock_addition

            if invoice.original_invoice_id and gl_stock_addition > _D2:
                je_lines.append({
                    "account_id": acc_inventory,
                    "debit": fc_stock_addition if inv_currency != base_currency else gl_stock_addition,
                    "credit": 0,
                    "description": f"Purchase Stock - {inv_num}",
                    "amount_currency": fc_stock_addition if inv_currency != base_currency else gl_stock_addition,
                    "currency": inv_currency
                })

            if invoice.original_invoice_id and abs(gl_purchase_variance) > _D2:
                if not acc_purchase_variance:
                    raise HTTPException(**http_error(400, "purchase_price_variance_not_configured", request))
                if gl_purchase_variance > 0:
                    je_lines.append({
                        "account_id": acc_purchase_variance,
                        "debit": fc_purchase_variance if inv_currency != base_currency else gl_purchase_variance,
                        "credit": 0,
                        "description": f"Purchase Price Variance - {inv_num}",
                        "amount_currency": fc_purchase_variance if inv_currency != base_currency else gl_purchase_variance,
                        "currency": inv_currency
                    })
                else:
                    je_lines.append({
                        "account_id": acc_purchase_variance,
                        "debit": 0,
                        "credit": abs(fc_purchase_variance) if inv_currency != base_currency else abs(gl_purchase_variance),
                        "description": f"Purchase Price Variance - {inv_num}",
                        "amount_currency": abs(fc_purchase_variance) if inv_currency != base_currency else abs(gl_purchase_variance),
                        "currency": inv_currency
                    })
            elif not invoice.original_invoice_id and gl_inventory_debit > _D2:
                je_lines.append({
                    "account_id": acc_inventory,
                    "debit": fc_inventory_debit if inv_currency != base_currency else gl_inventory_debit,
                    "credit": 0,
                    "description": f"Purchase Stock - {inv_num}",
                    "amount_currency": fc_inventory_debit if inv_currency != base_currency else gl_inventory_debit,
                    "currency": inv_currency
                })
            elif not invoice.original_invoice_id and gl_inventory_debit < -_D2:
                if not acc_purchase_variance:
                    raise HTTPException(**http_error(400, "purchase_price_variance_not_configured", request))
                variance_credit = abs(gl_inventory_debit)
                fc_variance_credit = abs(fc_inventory_debit)
                je_lines.append({
                    "account_id": acc_purchase_variance,
                    "debit": 0,
                    "credit": fc_variance_credit if inv_currency != base_currency else variance_credit,
                    "description": f"Purchase Price Variance - {inv_num}",
                    "amount_currency": fc_variance_credit if inv_currency != base_currency else variance_credit,
                    "currency": inv_currency
                })

            if receipt_accrual_reversal_base > _D2:
                acc_unbilled = get_mapped_account_id(db, "acc_map_unbilled_purchases")
                if acc_unbilled:
                    je_lines.append({
                        "account_id": acc_unbilled,
                        "debit": fc_accrual_reversal if inv_currency != base_currency else receipt_accrual_reversal_base,
                        "credit": 0,
                        "description": f"Reverse Unbilled Accrual - {inv_num}",
                        "amount_currency": fc_accrual_reversal if inv_currency != base_currency else receipt_accrual_reversal_base,
                        "currency": inv_currency
                    })
                    # Balance update handled by the JE lines loop below
                else:
                     # Fallback if mapping missing but we have reversal value (should not happen if system setup right)
                     je_lines.append({
                         "account_id": acc_inventory,
                         "debit": fc_accrual_reversal if inv_currency != base_currency else receipt_accrual_reversal_base,
                         "credit": 0,
                         "description": f"Purchase Stock (No Accrual Map) - {inv_num}",
                         "amount_currency": fc_accrual_reversal if inv_currency != base_currency else receipt_accrual_reversal_base,
                         "currency": inv_currency
                     })

            # B. VAT Input (Debit) (Base Currency)
            if gl_tax > 0:
                je_lines.append({
                    "account_id": acc_vat_in,
                    "debit": total_tax if inv_currency != base_currency else gl_tax,
                    "credit": 0,
                    "description": f"VAT Input - {inv_num}",
                    "amount_currency": total_tax, "currency": inv_currency
                })

            # C. Credit Side (Cash/Bank/AP)
            actual_pay_method = invoice.payment_method
            if invoice.payment_method == 'credit':
                 actual_pay_method = invoice.down_payment_method or 'cash'

            if gl_paid > 0:
                 if actual_pay_method == "cash" or actual_pay_method == "check":
                      # Use selected treasury account if provided, else fallback to default cash map
                      cash_acc_id = acc_cash
                      if actual_pay_method == "check":
                          cash_acc_id = acc_bank # Default for checks

                      if selected_treasury:
                          cash_acc_id = selected_treasury["gl_account_id"]

                      if not cash_acc_id:
                          raise HTTPException(**http_error(400, "cash_bank_account_not_configured_payment", request))

                      je_lines.append({
                          "account_id": cash_acc_id,
                          "debit": 0,
                          "credit": paid_amount if inv_currency != base_currency else gl_paid,
                          "description": f"Purchase {actual_pay_method.capitalize()} - {inv_num}",
                          "amount_currency": paid_amount, "currency": inv_currency
                      })
                 elif actual_pay_method == "bank":
                      # Use selected treasury account if provided, else fallback to default bank map
                      bank_acc_id = acc_bank
                      if selected_treasury:
                          bank_acc_id = selected_treasury["gl_account_id"]
                      if not bank_acc_id:
                          raise HTTPException(**http_error(400, "bank_account_not_configured_payment", request))
                      je_lines.append({
                          "account_id": bank_acc_id,
                          "debit": 0,
                          "credit": paid_amount if inv_currency != base_currency else gl_paid,
                          "description": f"Purchase Bank - {inv_num}",
                          "amount_currency": paid_amount, "currency": inv_currency
                      })

            remaining_gl = gl_total - gl_paid
            if remaining_gl > _D2:
                 je_lines.append({
                     "account_id": acc_ap,
                     "debit": 0,
                     "credit": remaining_balance if inv_currency != base_currency else remaining_gl,
                     "description": f"Purchase Credit - {inv_num}",
                     "amount_currency": remaining_balance, "currency": inv_currency
                 })

            # Insert Journal Entry
            if je_lines:
                gl_create_journal_entry(
                    db=db,
                    company_id=company_id,
                    date=str(invoice.invoice_date),
                    description=f"Purchase Invoice {inv_num} ({inv_currency})",
                    reference=inv_num,
                    lines=je_lines,
                    user_id=current_user.get("id") if isinstance(current_user, dict) else current_user.id,
                    branch_id=effective_branch_id,
                    currency=inv_currency,
                    exchange_rate=exchange_rate,
                    source="purchase_invoice",
                    source_id=invoice_id,
                    idempotency_key=idempotency_key
                )

            if selected_treasury and invoice.treasury_id and gl_paid > 0:
                from utils.treasury_balance import recalc_treasury_from_gl
                recalc_treasury_from_gl(db, invoice.treasury_id)

            # --- 8. Insert Currency Transaction (if Foreign Currency) ---
            if inv_currency != base_currency:
                currency_account_id = acc_ap
                if not currency_account_id and gl_paid > 0:
                    if selected_treasury:
                        currency_account_id = selected_treasury["gl_account_id"]
                    elif actual_pay_method in ("bank", "check"):
                        currency_account_id = acc_bank
                    else:
                        currency_account_id = acc_cash
                if currency_account_id:
                    db.execute(text("""
                        INSERT INTO currency_transactions (
                            transaction_type, transaction_id, account_id,
                            currency_code, exchange_rate, amount_fc, amount_bc, description
                        ) VALUES (
                            'purchase', :tid, :aid, :curr, :rate, :fc, :bc, :desc
                        )
                    """), {
                        "tid": invoice_id,
                        "aid": currency_account_id,
                        "curr": inv_currency,
                        "rate": exchange_rate,
                        "fc": grand_total,
                        "bc": to_base(grand_total),
                        "desc": f"Purchase Invoice {inv_num}"
                    })


            supp_name = db.execute(text("SELECT name FROM parties WHERE id = :id"), {"id": invoice.supplier_id}).scalar()
            # AUDIT LOG
            log_activity(
                db,
                user_id=current_user.get("id") if isinstance(current_user, dict) else current_user.id,
                username=current_user.get("username") if isinstance(current_user, dict) else current_user.username,
                action="purchase_invoice.create",
                resource_type="invoice",
                resource_id=str(invoice_id),
                details={"invoice_number": inv_num, "total": grand_total, "supplier_id": invoice.supplier_id, "supplier_name": supp_name},
                request=request,
	                branch_id=effective_branch_id
            )

            # ── 3-Way Matching: auto-match if invoice is linked to a PO ──
            # AUDIT-C1: the matching service returns "matched" or "held"
            # (services/matching_service.py:158, 204). The previous check
            # for "exception" was unreachable, so held invoices were
            # silently posted with full GL + AR impact and no notification.
            # We now treat "held" as the failure state and notify the user.
            #
            # Optional hard block: setting `buying.block_held_invoices=true`
            # makes any held match abort the whole transaction (GL + AP +
            # stock all rollback) so invoices outside tolerance never reach
            # the books without an explicit approval workflow. The setting
            # defaults to false to preserve historical behaviour.
            match_result = None
            if invoice.original_invoice_id:
                try:
                    from services.matching_service import perform_match
                    user_id = current_user.get("id") if isinstance(current_user, dict) else current_user.id
                    match_result = perform_match(
                        db,
                        invoice_id=invoice_id,
                        po_id=invoice.original_invoice_id,
                        supplier_id=invoice.supplier_id,
                        user_id=user_id,
                    )
                    if match_result and match_result.get("match_status") == "held":
                        # Mark the invoice header as held so downstream
                        # screens/reports can surface it.
                        db.execute(text(
                            "UPDATE invoices SET status = 'held' WHERE id = :id"
                        ), {"id": invoice_id})

                        # Hard-block path: if configured, raise to roll
                        # back the whole transactional() so no GL / AP /
                        # stock side-effect leaks past tolerance.
                        block_held = db.execute(text("""
                            SELECT LOWER(COALESCE(setting_value, 'false'))
                            FROM company_settings
                            WHERE setting_key = 'buying.block_held_invoices'
                        """)).scalar() in ("1", "true", "yes", "on")
                        if block_held:
                            raise HTTPException(
                                status_code=409,
                                detail=i18n_message("purchase_invoice_held_three_way_mismatch", request),
                            )

                        # Soft-block path: notify so the held invoice is
                        # caught in operations review.
                        try:
                            from services.notification_service import NotificationService
                            ns = NotificationService(db)
                            ns.dispatch(
                                recipient_id=user_id,
                                event_type="invoice_held",
                                title="فاتورة مشتريات معلّقة - مطابقة ثلاثية",
                                body=f"الفاتورة {inv_num} تحتوي على فروقات تحتاج مراجعة",
                                reference_type="three_way_match",
                                reference_id=match_result.get("match_id"),
                            )
                        except Exception as notif_err:
                            logger.warning("Failed to dispatch matching notification: %s", notif_err)
                except HTTPException:
                    raise
                except Exception as match_err:
                    logger.warning("3-way matching failed for invoice %s: %s", invoice_id, match_err)

            return {"success": True, "message": i18n_message("purchase_invoice_created", request), "invoice_id": invoice_id, "match_result": match_result}

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error creating purchase invoice: {str(e)}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/invoices/{id}/cancel", dependencies=[Depends(require_sensitive_permission("buying.void"))], response_model=Dict[str, Any])
def cancel_purchase_invoice(
    request: Request,
    id: int,
    current_user: dict = Depends(get_current_user)
):
    """إلغاء فاتورة مشتريات مع عكس المخزون والقيد المحاسبي بأثر قابل للتدقيق."""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    user_id = current_user.get("id") if isinstance(current_user, dict) else current_user.id
    username = current_user.get("username") if isinstance(current_user, dict) else current_user.username

    with transactional(company_id) as db:
        inv = db.execute(text("""
            SELECT *
            FROM invoices
            WHERE id = :id AND invoice_type = 'purchase'
            FOR UPDATE
        """), {"id": id}).fetchone()
        if not inv:
            raise HTTPException(**http_error(404, "purchase_invoice_not_found", request))

        validate_branch_access(current_user, inv.branch_id)
        if inv.status in ("cancelled", "void"):
            raise HTTPException(**http_error(400, "purchase_invoice_already_cancelled", request))

        reversal_date = datetime.now().date()
        check_fiscal_period_open(db, reversal_date, request=request)

        linked_returns = db.execute(text("""
            SELECT COUNT(*)
            FROM invoices
            WHERE related_invoice_id = :id
              AND invoice_type = 'purchase_return'
              AND status NOT IN ('cancelled', 'void')
        """), {"id": id}).scalar() or 0
        if linked_returns:
            raise HTTPException(**http_error(400, "purchase_invoice_has_returns", request))

        purchase_je = db.execute(text("""
            SELECT id
            FROM journal_entries
            WHERE source = 'purchase_invoice'
              AND source_id = :id
              AND status = 'posted'
            ORDER BY id DESC
            LIMIT 1
        """), {"id": id}).fetchone()
        if not purchase_je and (_dec(inv.subtotal) > _D2 or _dec(inv.tax_amount) > _D2 or _dec(inv.total) > _D2):
            raise HTTPException(**http_error(400, "purchase_invoice_no_je_to_reverse", request))

        allocation_rows = db.execute(text("""
            SELECT pa.id AS allocation_id,
                   pa.voucher_id,
                   pa.allocated_amount,
                   pv.voucher_number,
                   pv.reference,
                   pv.status,
                   pv.treasury_account_id,
                   pv.amount,
                   pv.voucher_type,
                   pv.party_type,
                   pv.party_id,
                   EXISTS (
                       SELECT 1
                       FROM journal_entries je
                       WHERE je.source = 'payment_voucher'
                         AND je.source_id = pv.id
                         AND je.status = 'posted'
                   ) AS has_payment_voucher_je
            FROM payment_allocations pa
            JOIN payment_vouchers pv ON pv.id = pa.voucher_id
            WHERE pa.invoice_id = :id
            FOR UPDATE OF pa, pv
        """), {"id": id}).fetchall()

        auto_voucher_ids = set()
        treasury_ids_to_recalc = set()
        for row in allocation_rows:
            other_allocations = db.execute(text("""
                SELECT COUNT(*)
                FROM payment_allocations
                WHERE voucher_id = :voucher_id
                  AND invoice_id <> :invoice_id
            """), {"voucher_id": row.voucher_id, "invoice_id": id}).scalar() or 0
            is_inline_invoice_payment = (
                not row.has_payment_voucher_je
                and row.voucher_type == "payment"
                and row.party_type == "supplier"
                and int(row.party_id) == int(inv.party_id)
                and _dec(row.allocated_amount) <= _dec(row.amount) + _D2
            )
            if other_allocations or not is_inline_invoice_payment:
                raise HTTPException(**http_error(400, "purchase_invoice_has_payment_allocations", request))
            auto_voucher_ids.add(row.voucher_id)
            if row.treasury_account_id:
                treasury_ids_to_recalc.add(row.treasury_account_id)

        # Reverse only the stock that this invoice itself added. PO quantities
        # already received through GRN are not deducted again here.
        stock_rows = db.execute(text("""
            WITH locked_tx AS (
                SELECT product_id, warehouse_id, quantity, unit_cost, total_cost
                FROM inventory_transactions
                WHERE reference_type = 'invoice'
                  AND reference_id = :id
                  AND quantity > 0
                FOR UPDATE
            )
            SELECT product_id,
                   warehouse_id,
                   SUM(quantity) AS quantity,
                   COALESCE(SUM(total_cost) / NULLIF(SUM(quantity), 0), MAX(unit_cost), 0) AS unit_cost
            FROM locked_tx
            GROUP BY product_id, warehouse_id
        """), {"id": id}).fetchall()

        from services.costing_service import CostingService
        for row in stock_rows:
            qty = _dec(row.quantity)
            if qty <= 0:
                continue

            method = CostingService._get_product_costing_method(db, row.product_id, row.warehouse_id)
            unit_cost = _dec(row.unit_cost)
            if method in ("fifo", "lifo"):
                try:
                    CostingService.handle_return(
                        db,
                        product_id=row.product_id,
                        warehouse_id=row.warehouse_id,
                        quantity=qty,
                        unit_cost=str(unit_cost),
                        source_document_type="purchase_invoice_cancel",
                        source_document_id=id,
                        costing_method=method,
                        original_source_document_type="purchase_invoice",
                        original_source_document_id=id,
                    )
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc))
            else:
                CostingService.update_cost(
                    db,
                    product_id=row.product_id,
                    warehouse_id=row.warehouse_id,
                    new_qty=-qty,
                    new_price=unit_cost,
                )

            inv_update = db.execute(text("""
                UPDATE inventory
                SET quantity = quantity - :qty,
                    last_movement_date = NOW(),
                    updated_at = NOW()
                WHERE product_id = :pid
                  AND warehouse_id = :wh
                  AND quantity - COALESCE(reserved_quantity, 0) >= :qty
                RETURNING id
            """), {
                "qty": qty,
                "pid": row.product_id,
                "wh": row.warehouse_id,
            }).fetchone()
            if not inv_update:
                raise HTTPException(**http_error(400, "insufficient_stock_for_purchase_invoice_cancel", request))

            total_cost = (qty * unit_cost).quantize(_D2, ROUND_HALF_UP)
            db.execute(text("""
                INSERT INTO inventory_transactions (
                    product_id, warehouse_id, transaction_type,
                    reference_type, reference_id, reference_document,
                    quantity, unit_cost, total_cost, notes, created_by
                ) VALUES (
                    :pid, :wh, 'purchase_invoice_cancel',
                    'purchase_invoice_cancel', :ref_id, :ref_doc,
                    :qty, :unit_cost, :total_cost, :notes, :user
                )
            """), {
                "pid": row.product_id,
                "wh": row.warehouse_id,
                "ref_id": id,
                "ref_doc": inv.invoice_number,
                "qty": -qty,
                "unit_cost": unit_cost,
                "total_cost": total_cost,
                "notes": "Cancel purchase invoice stock",
                "user": user_id,
            })

        # Restore PO invoice counters for linked purchase order lines.
        po_rows = db.execute(text("""
            SELECT po_line_id, SUM(quantity) AS quantity
            FROM invoice_lines
            WHERE invoice_id = :id
              AND po_line_id IS NOT NULL
            GROUP BY po_line_id
        """), {"id": id}).fetchall()
        for row in po_rows:
            db.execute(text("""
                UPDATE purchase_order_lines
                SET invoiced_quantity = GREATEST(0, COALESCE(invoiced_quantity, 0) - :qty)
                WHERE id = :po_line_id
            """), {"po_line_id": row.po_line_id, "qty": _dec(row.quantity)})

        remaining_balance = (_dec(inv.total) - _dec(inv.paid_amount)).quantize(_D4, ROUND_HALF_UP)
        if remaining_balance > _D2:
            update_party_site_balance(
                db,
                party_id=inv.party_id,
                branch_id=inv.branch_id,
                currency=inv.currency or get_base_currency(db),
                amount=remaining_balance,
                document_type="purchase_invoice_cancel",
            )

        if purchase_je:
            from services.gl_service import reverse_journal_entry
            reverse_journal_entry(
                db,
                je_id=purchase_je.id,
                user_id=user_id,
                company_id=company_id,
                reversal_date=str(reversal_date),
                reason=f"Cancel purchase invoice {inv.invoice_number}",
                request=request,
            )

        for voucher_id in auto_voucher_ids:
            voucher_je = db.execute(text("""
                SELECT id
                FROM journal_entries
                WHERE source = 'payment_voucher'
                  AND source_id = :voucher_id
                  AND status = 'posted'
                ORDER BY id DESC
                LIMIT 1
            """), {"voucher_id": voucher_id}).fetchone()
            if voucher_je:
                from services.gl_service import reverse_journal_entry
                reverse_journal_entry(
                    db,
                    je_id=voucher_je.id,
                    user_id=user_id,
                    company_id=company_id,
                    reversal_date=str(reversal_date),
                    reason=f"Cancel auto payment for purchase invoice {inv.invoice_number}",
                    request=request,
                )
            db.execute(text("DELETE FROM payment_allocations WHERE voucher_id = :voucher_id AND invoice_id = :id"),
                       {"voucher_id": voucher_id, "id": id})
            db.execute(text("""
                UPDATE payment_vouchers
                SET status = 'void'
                WHERE id = :voucher_id
            """), {"voucher_id": voucher_id})

        db.execute(text("""
            UPDATE invoices
            SET status = 'cancelled',
                updated_at = NOW()
            WHERE id = :id
        """), {"id": id})

        if treasury_ids_to_recalc:
            from utils.treasury_balance import recalc_treasury_from_gl
            for treasury_id in treasury_ids_to_recalc:
                recalc_treasury_from_gl(db, treasury_id)

        invalidate_company_cache(company_id)
        log_activity(
            db,
            user_id=user_id,
            username=username,
            action="purchase_invoice.cancel",
            resource_type="invoice",
            resource_id=str(id),
            details={"invoice_number": inv.invoice_number, "total": str(inv.total or 0)},
            request=request,
            branch_id=inv.branch_id,
        )
        return {"success": True, "message": i18n_message("purchase_invoice_cancelled", request)}

# === Purchase Returns ===
