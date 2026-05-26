"""pos sub-router — split from monolithic pos.py (T6.3).

Mounted under the parent router via pos/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from utils.i18n import http_error, i18n_message
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import logging
from routers.auth import get_current_user
from utils.permissions import branch_scope_filter_from_scope, require_permission, resolve_branch_scope, validate_branch_access, validate_treasury_account_access, check_permission
from utils.fiscal_lock import check_fiscal_period_open
from utils.audit import log_activity
from schemas import UserResponse
from schemas.pos import OrderCreate, OrderResponse, ReturnCreate
from services.gl_service import create_journal_entry as gl_create_journal_entry
from services.tax_engine import resolve_line_tax
from utils.accounting import compute_invoice_totals, compute_line_amounts

logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')
def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')

router = APIRouter()

from .core import _D2, _D4, _dec, get_db  # noqa: E402


def _line_discount_pct(qty, unit_price, disc_amt) -> Decimal:
    gross = (_dec(qty) * _dec(unit_price)).quantize(_D2, ROUND_HALF_UP)
    if gross <= 0:
        return Decimal("0")
    amt = _dec(disc_amt)
    if amt <= 0:
        return Decimal("0")
    if amt > gross:
        amt = gross
    return (amt * Decimal("100") / gross).quantize(Decimal("0.000001"), ROUND_HALF_UP)


def _validate_pos_price_overrides(db: Session, order_in: OrderCreate, current_user: UserResponse, request: Request) -> None:
    user_perms = current_user.permissions or []
    can_override_price = check_permission(user_perms, "pos.price_override") or check_permission(user_perms, "pos.manage")
    for item in order_in.items:
        product_price = db.execute(
            text("SELECT selling_price, min_price, max_price FROM products WHERE id = :id"),
            {"id": item.product_id},
        ).fetchone()
        if product_price:
            requested_price = _dec(item.unit_price).quantize(_D4, ROUND_HALF_UP)
            selling_price = _dec(product_price.selling_price).quantize(_D4, ROUND_HALF_UP)
            min_price = _dec(product_price.min_price).quantize(_D4, ROUND_HALF_UP)
            max_price = _dec(product_price.max_price).quantize(_D4, ROUND_HALF_UP)
            if requested_price != selling_price:
                if not can_override_price:
                    raise HTTPException(**http_error(403, "pos_price_override_permission_required", request))
                if min_price > 0 and requested_price < min_price:
                    raise HTTPException(**http_error(400, "price_below_minimum", request))
                if max_price > 0 and requested_price > max_price:
                    raise HTTPException(**http_error(400, "price_above_maximum", request))


def _resolve_pos_order_context(db: Session, order_in: OrderCreate, current_user: UserResponse):
    pos_session = db.execute(
        text("SELECT branch_id, warehouse_id, treasury_account_id FROM pos_sessions WHERE id = :id"),
        {"id": order_in.session_id},
    ).fetchone()
    branch_id = order_in.branch_id or (pos_session.branch_id if pos_session else None)
    warehouse_id = order_in.warehouse_id or (pos_session.warehouse_id if pos_session else None)
    treasury_id = pos_session.treasury_account_id if pos_session else None
    branch_id = validate_branch_access(current_user, branch_id)
    return pos_session, branch_id, warehouse_id, treasury_id


def _build_pos_order_preview(db: Session, order_in: OrderCreate, branch_id: int, request: Request):
    resolved_taxes = {}
    for item in order_in.items:
        tax_info = resolve_line_tax(branch_id, item.product_id, db, customer_id=getattr(order_in, "customer_id", None))
        resolved_taxes[item.product_id] = tax_info

    line_dicts = [
        {
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "tax_rate": resolved_taxes[item.product_id]["tax_rate"],
            "discount": _line_discount_pct(item.quantity, item.unit_price, item.discount_amount),
        }
        for item in order_in.items
    ]

    promotion_row = None
    if order_in.promotion_id:
        promotion_row = db.execute(text("""
            SELECT id, promotion_type, value, coupon_code, min_order_amount
            FROM pos_promotions
            WHERE id = :id AND is_active = TRUE
              AND (start_date IS NULL OR start_date <= NOW())
              AND (end_date   IS NULL OR end_date   >  NOW())
        """), {"id": order_in.promotion_id}).fetchone()
        if promotion_row is None:
            raise HTTPException(**http_error(400, "pos_promotion_not_found", request))
    elif order_in.coupon_code:
        promotion_row = db.execute(text("""
            SELECT id, promotion_type, value, coupon_code, min_order_amount
            FROM pos_promotions
            WHERE coupon_code = :code AND is_active = TRUE
              AND (start_date IS NULL OR start_date <= NOW())
              AND (end_date   IS NULL OR end_date   >  NOW())
        """), {"code": order_in.coupon_code.strip()}).fetchone()
        if promotion_row is None:
            raise HTTPException(**http_error(400, "pos_coupon_invalid", request))

    gross_subtotal = sum(
        (_dec(it.quantity) * _dec(it.unit_price)).quantize(_D2, ROUND_HALF_UP)
        for it in order_in.items
    )

    header_discount_pct = Decimal("0")
    if promotion_row is not None:
        min_oa = _dec(promotion_row.min_order_amount or 0)
        if min_oa > 0 and gross_subtotal < min_oa:
            raise HTTPException(
                status_code=400,
                detail=f"الحد الأدنى لتطبيق العرض هو {min_oa:.2f}",
            )
        ptype = (promotion_row.promotion_type or "percentage").lower()
        pvalue = _dec(promotion_row.value or 0)
        if ptype == "percentage":
            header_discount_pct = pvalue
        elif ptype in ("amount", "fixed", "fixed_amount") and gross_subtotal > 0:
            header_discount_pct = (pvalue * Decimal("100") / gross_subtotal)
    elif _dec(order_in.discount_amount) > 0 and gross_subtotal > 0:
        header_discount_pct = _dec(order_in.discount_amount) * Decimal("100") / gross_subtotal

    if header_discount_pct < 0:
        header_discount_pct = Decimal("0")
    if header_discount_pct > Decimal("100"):
        header_discount_pct = Decimal("100")

    totals = compute_invoice_totals(line_dicts, header_discount_pct=header_discount_pct)
    subtotal = totals["subtotal"] - totals["total_discount"]
    tax_total = totals["total_tax"]
    total = totals["grand_total"]
    effective_discount_amount = totals["total_discount"].quantize(_D2, ROUND_HALF_UP)

    lines = []
    for item in order_in.items:
        tax_info = resolved_taxes[item.product_id]
        item_subtotal = (_dec(item.quantity) * _dec(item.unit_price)).quantize(_D2, ROUND_HALF_UP)
        line_discount_pct = _line_discount_pct(item.quantity, item.unit_price, item.discount_amount)
        line_amounts = compute_line_amounts(item.quantity, item.unit_price, tax_info["tax_rate"], line_discount_pct)
        lines.append({
            "product_id": item.product_id,
            "quantity": str(_dec(item.quantity)),
            "unit_price": str(_dec(item.unit_price).quantize(_D2, ROUND_HALF_UP)),
            "subtotal": str(item_subtotal),
            "tax_rate": str(_dec(tax_info["tax_rate"])),
            "tax_rate_id": tax_info["tax_rate_id"],
            "tax_amount": str(_dec(line_amounts["tax_amount"]).quantize(_D2, ROUND_HALF_UP)),
            "total": str(_dec(line_amounts["line_total"]).quantize(_D2, ROUND_HALF_UP)),
        })

    return {
        "resolved_taxes": resolved_taxes,
        "subtotal": subtotal.quantize(_D2, ROUND_HALF_UP),
        "tax_total": tax_total.quantize(_D2, ROUND_HALF_UP),
        "total": total.quantize(_D2, ROUND_HALF_UP),
        "effective_discount_amount": effective_discount_amount,
        "lines": lines,
    }


@router.post("/orders/preview", response_model=Dict[str, Any], dependencies=[Depends(require_permission("pos.view"))])
def preview_order(
    order_in: OrderCreate,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return backend-authoritative POS order totals without creating an order."""
    from utils.quantity_validation import validate_quantity_for_product
    for item in order_in.items:
        validate_quantity_for_product(db, item.product_id, item.quantity)

    _validate_pos_price_overrides(db, order_in, current_user, request)
    _, branch_id, warehouse_id, _ = _resolve_pos_order_context(db, order_in, current_user)

    if order_in.branch_id:
        validate_branch_access(current_user, order_in.branch_id)
    if order_in.warehouse_id:
        wh_branch = db.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": order_in.warehouse_id}).scalar()
        if wh_branch:
            validate_branch_access(current_user, wh_branch)

    preview = _build_pos_order_preview(db, order_in, branch_id, request)
    total_paid = sum(_dec(p.amount) for p in order_in.payments).quantize(_D2, ROUND_HALF_UP)
    remaining_amount = (preview["total"] - total_paid).quantize(_D2, ROUND_HALF_UP)
    if remaining_amount < 0:
        remaining_amount = Decimal("0.00")
    return {
        "branch_id": branch_id,
        "warehouse_id": warehouse_id,
        "subtotal": str(preview["subtotal"]),
        "tax_amount": str(preview["tax_total"]),
        "discount_amount": str(preview["effective_discount_amount"]),
        "total_amount": str(preview["total"]),
        "total_paid": str(total_paid),
        "remaining_amount": str(remaining_amount),
        "lines": preview["lines"],
    }


@router.post("/orders", response_model=OrderResponse, dependencies=[Depends(require_permission("pos.create"))])
def create_order(
    order_in: OrderCreate,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key", max_length=64),
):
    """Create Order."""
    # Idempotency pre-check
    if idempotency_key:
        existing = db.execute(text("""
            SELECT id, order_number, total_amount, status, created_at
            FROM pos_orders
            WHERE idempotency_key = :key
            LIMIT 1
        """), {"key": idempotency_key}).fetchone()
        if existing:
            return OrderResponse(
                id=existing.id,
                order_number=existing.order_number,
                total_amount=existing.total_amount,
                status=existing.status,
                created_at=existing.created_at,
            )

    if order_in.client_order_id and not idempotency_key:
        raise HTTPException(**http_error(400, "idempotency_key_required", request))

    # Get base currency
    from utils.accounting import get_base_currency
    base_currency = get_base_currency(db)

    # UOM Validation: Discrete units must have integer quantities
    from utils.quantity_validation import validate_quantity_for_product
    for item in order_in.items:
        validate_quantity_for_product(db, item.product_id, item.quantity)

    _validate_pos_price_overrides(db, order_in, current_user, request)

    # TASK-027 / T3.10: unified totals via compute_invoice_totals so POS
    # produces the same numbers as routers/sales/invoices for the same
    # inputs. Per-line OrderLineCreate.discount_amount is an *absolute*
    # currency amount, while compute_line_amounts expects a percentage —
    # convert per line so the unified helper sees consistent semantics.
    # Resolve branch early so tax engine can use it
    pos_session, branch_id, warehouse_id, treasury_id = _resolve_pos_order_context(db, order_in, current_user)
    preview = _build_pos_order_preview(db, order_in, branch_id, request)
    _resolved_taxes = preview["resolved_taxes"]
    subtotal = preview["subtotal"]
    tax_total = preview["tax_total"]
    total = preview["total"]
    effective_discount_amount = preview["effective_discount_amount"]

    # Strict validation: compare client-submitted grand total with authoritative backend grand total
    if order_in.submitted_grand_total is not None:
        _D2 = Decimal("0.01")
        if abs(total - order_in.submitted_grand_total) > _D2:
            raise HTTPException(**http_error(422, "submitted_grand_total_mismatch", request))

    # FISCAL-LOCK: Reject if accounting period is closed
    check_fiscal_period_open(db, datetime.now().date())

    # T3.10: total already includes the header discount via
    # compute_invoice_totals(header_discount_pct=...) — do NOT subtract
    # order_in.discount_amount again here, that would double-count it
    # and break the POS == sales-invoice equivalence.

    # Validate branch and warehouse access
    if order_in.branch_id:
        validate_branch_access(current_user, order_in.branch_id)

    if order_in.warehouse_id:
        wh_branch = db.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": order_in.warehouse_id}).scalar()
        if wh_branch:
             validate_branch_access(current_user, wh_branch)

    if order_in.client_order_id:
        existing_order = db.execute(text("""
            SELECT id, order_number, total_amount, status, created_at
            FROM pos_orders
            WHERE client_order_id = :client_order_id
            LIMIT 1
        """), {"client_order_id": order_in.client_order_id}).fetchone()
        if existing_order:
            return OrderResponse(
                id=existing_order.id,
                order_number=existing_order.order_number,
                total_amount=existing_order.total_amount,
                status=existing_order.status,
                created_at=existing_order.created_at,
            )

    total_payments = sum(_dec(p.amount) for p in order_in.payments).quantize(_D2, ROUND_HALF_UP)

    # Validate payments cover total for paid orders
    if order_in.status == 'paid':
        if total_payments < total:
            if len(order_in.payments) == 1 and abs(total_payments - total) < _D2:
                # Auto-adjust only for rounding differences
                order_in.payments[0].amount = total
                total_payments = total
            elif total_payments < total:
                raise HTTPException(status_code=400, detail=i18n_message("payment_amount_less_than_total", request))

    # Treasury validation (branch_id already resolved above)
    selected_treasury = None
    if treasury_id:
        selected_treasury = validate_treasury_account_access(db, current_user, treasury_id, branch_id)

    import uuid
    order_number = f"POS-{uuid.uuid4().hex[:8].upper()}"

    # 1. Create Order
    total_cogs = Decimal('0')
    result = db.execute(text("""
        INSERT INTO pos_orders (
            order_number, session_id, customer_id, walk_in_customer_name,
            warehouse_id, branch_id, status, subtotal, tax_amount,
            discount_amount, total_amount, paid_amount, note, client_order_id, created_by, party_site_id,
            idempotency_key
        ) VALUES (
            :num, :sess, :cust, :walkin, :wh, :branch, :status, :subtotal, :tax,
            :disc, :total, :paid, :note, :client_order_id, :uid, :party_site_id,
            :idempotency_key
        ) RETURNING id
    """), {
        "num": order_number,
        "sess": order_in.session_id,
        "cust": order_in.customer_id,
        "walkin": order_in.walk_in_customer_name,
        "wh": warehouse_id,
        "branch": branch_id,
        "status": order_in.status,
        "subtotal": subtotal,
        "tax": tax_total,
        "disc": effective_discount_amount,
        "total": total,
        "paid": total_payments if order_in.status == 'paid' else Decimal("0.00"),
        "note": order_in.note,
        "client_order_id": order_in.client_order_id,
        "uid": current_user.id,
        "party_site_id": order_in.party_site_id,
        "idempotency_key": idempotency_key,
    }).fetchone()

    order_id = result.id

    # 2. Create Items
    for item in order_in.items:
        # Fetch product details for the record
        prod_info = db.execute(text("SELECT product_name, product_code, barcode FROM products WHERE id = :id"), {"id": item.product_id}).fetchone()

        # Use pre-resolved tax info
        tax_info = _resolved_taxes[item.product_id]

        item_subtotal = (_dec(item.quantity) * _dec(item.unit_price)).quantize(_D2, ROUND_HALF_UP)
        _line_disc_pct = _line_discount_pct(item.quantity, item.unit_price, item.discount_amount)
        _la = compute_line_amounts(item.quantity, item.unit_price, tax_info["tax_rate"], _line_disc_pct)
        tax_amount = _la["tax_amount"]
        item_total = _la["line_total"]

        db.execute(text("""
            INSERT INTO pos_order_lines (
                order_id, product_id, description,
                quantity, original_price, unit_price,
                tax_rate, tax_rate_id, tax_amount, subtotal, total,
                warehouse_id
            ) VALUES (
                :oid, :pid, :desc,
                :qty, :orig, :price,
                :tax_r, :tax_rid, :tax_a, :sub, :tot,
                :wh
            )
        """), {
            "oid": order_id,
            "pid": item.product_id,
            "desc": f"{prod_info[0]} ({prod_info[1]})" if prod_info else "Unknown",
            "qty": item.quantity,
            "orig": _dec(item.unit_price).quantize(_D2, ROUND_HALF_UP),
            "price": _dec(item.unit_price).quantize(_D2, ROUND_HALF_UP),
            "tax_r": tax_info["tax_rate"],
            "tax_rid": tax_info["tax_rate_id"],
            "tax_a": tax_amount,
            "sub": item_subtotal,
            "tot": item_total,
            "wh": warehouse_id
        })

        # 3. Update Inventory if Paid
        if order_in.status == 'paid':
            # Calculate COGS before deducting stock so FIFO/LIFO checks the
            # pre-sale available balance while holding the inventory row lock.
            from services.costing_service import CostingService
            method = CostingService._get_product_costing_method(db, item.product_id, warehouse_id)
            try:
                if method in ("fifo", "lifo"):
                    item_cogs = CostingService.consume_layers(
                        db,
                        product_id=item.product_id,
                        warehouse_id=warehouse_id,
                        quantity=item.quantity,
                        sale_document_type="pos_order",
                        sale_document_id=order_id,
                        costing_method=method,
                    )
                    cost_price = (item_cogs / _dec(item.quantity)).quantize(_D4, ROUND_HALF_UP) if item.quantity else _dec(0)
                    total_cogs += _dec(item_cogs).quantize(_D2, ROUND_HALF_UP)
                else:
                    cost_price = _dec(db.execute(text("SELECT cost_price FROM products WHERE id = :id"), {"id": item.product_id}).scalar() or 0)
                    total_cogs += (cost_price * _dec(item.quantity)).quantize(_D2, ROUND_HALF_UP)
            except ValueError:
                # FIFO/LIFO layer exhaustion — surface as 400, no silent fallback
                logger.exception("FIFO/LIFO layer exhaustion on POS order create")
                raise HTTPException(status_code=400, detail=i18n_message("validation_error", request) if request else "Validation error")

            # T030: Atomic deduction with authoritative available formula
            inv_update = db.execute(text("""
                UPDATE inventory
                SET quantity = quantity - :qty,
                    last_movement_date = NOW(),
                    updated_at = NOW()
                WHERE product_id = :pid AND warehouse_id = :wh
                  AND quantity - COALESCE(reserved_quantity, 0) >= :qty
                RETURNING id, quantity
            """), {"qty": item.quantity, "pid": item.product_id, "wh": warehouse_id}).fetchone()

            if not inv_update:
                exists = db.execute(text(
                    "SELECT 1 FROM inventory WHERE product_id = :pid AND warehouse_id = :wh"
                ), {"pid": item.product_id, "wh": warehouse_id}).scalar()
                if not exists:
                    raise HTTPException(status_code=400, detail=i18n_message("no_inventory_record_product", request))
                else:
                    raise HTTPException(status_code=400, detail=i18n_message("insufficient_stock_product", request))

            # Log Inventory Transaction
            db.execute(text("""
                INSERT INTO inventory_transactions (
                    product_id, warehouse_id, transaction_type,
                    reference_type, reference_id, reference_document,
                    quantity, unit_cost, total_cost, created_by
                ) VALUES (
                    :pid, :wh, 'sales', 'pos_order', :order_id, :order_num,
                    :qty, :cost, :total_cost, :user
                )
            """), {
                "pid": item.product_id,
                "wh": warehouse_id,
                "order_id": order_id,
                "order_num": order_number,
                "qty": -item.quantity,
                "cost": cost_price,
                "total_cost": (cost_price * _dec(item.quantity)).quantize(_D2, ROUND_HALF_UP),
                "user": current_user.id
            })

    # 4. Create Payments
    for payment in order_in.payments:
        db.execute(text("""
            INSERT INTO pos_payments (order_id, session_id, payment_method, amount, reference_number)
            VALUES (:oid, :sess, :meth, :amt, :ref)
        """), {
            "oid": order_id,
            "sess": order_in.session_id,
            "meth": payment.method,
            "amt": payment.amount,
            "ref": payment.reference
        })

    # 5. Update Session Totals & Accounting
    if order_in.status == 'paid':
        # Update gross sales
        db.execute(text("""
            UPDATE pos_sessions
            SET total_sales = total_sales + :amount
            WHERE id = :id
        """), {
            "amount": total,
            "id": order_in.session_id
        })

        # --- Automated Accounting (GL Entries) ---
        # GL-FIX: Use configured account mappings with fallback to account_code lookup
        from utils.accounting import get_mapped_account_id

        def get_acc_id(code):
             return db.execute(text("SELECT id FROM accounts WHERE account_code = :code"), {"code": code}).scalar()

        acc_sales = get_mapped_account_id(db, "acc_map_sales") or get_acc_id("SALE-G")
        acc_vat_out = get_mapped_account_id(db, "acc_map_vat_output") or get_acc_id("VAT-OUT")

        # DYNAMIC TREASURY MAPPING
        acc_cash = None
        if treasury_id:
               acc_cash = selected_treasury.get("gl_account_id") if selected_treasury else None
        if not acc_cash:
             acc_cash = get_mapped_account_id(db, "acc_map_cash_main") or get_acc_id("BOX")

        acc_bank = get_mapped_account_id(db, "acc_map_bank_main") or get_acc_id("BNK")
        acc_cogs = get_mapped_account_id(db, "acc_map_cogs") or get_acc_id("CGS")
        # F-31: credit the source warehouse's inventory account so per-warehouse
        # valuation reflects the COGS movement.
        from utils.inventory_accounts import resolve_warehouse_inventory_account
        acc_inventory = resolve_warehouse_inventory_account(db, warehouse_id) or get_acc_id("INV")

        je_lines = []
        # A. Debit: Payments (Cash/Bank)
        for pmt in order_in.payments:
            acc_id = acc_cash if pmt.method == 'cash' else acc_bank
            if acc_id:
                je_lines.append({
                    "account_id": acc_id,
                    "debit": _dec(pmt.amount).quantize(_D2, ROUND_HALF_UP),
                    "credit": 0,
                    "description": f"POS Payment ({pmt.method}) - {order_number}"
                })

        # B. Credit: Sales Revenue (Gross Subtotal) & Debit: Sales Discount (if any)
        # T3.10: GL must reflect the *effective* discount (computed by
        # compute_invoice_totals incl. coupon/promotion), not the raw
        # request body field.
        discount_dec = effective_discount_amount
        if acc_sales and subtotal > 0:
            je_lines.append({
                "account_id": acc_sales,
                "debit": 0,
                "credit": subtotal,
                "description": f"POS Gross Sales - {order_number}"
            })

        # Sales Discount (separate account for proper reporting)
        if discount_dec > 0:
            acc_discount = get_mapped_account_id(db, "acc_map_sales_discount") or get_acc_id("DISC-SALE") or get_acc_id("SALE-DISC")
            if acc_discount:
                je_lines.append({
                    "account_id": acc_discount,
                    "debit": discount_dec,
                    "credit": 0,
                    "description": f"POS Discount - {order_number}"
                })
            else:
                raise HTTPException(
                    status_code=422,
                    detail="حساب خصم المبيعات غير مضبوط (acc_map_sales_discount أو DISC-SALE/SALE-DISC)",
                )

        # C. Credit: VAT
        if acc_vat_out and tax_total > 0:
            je_lines.append({
                "account_id": acc_vat_out,
                "debit": 0,
                "credit": tax_total,
                "description": f"POS Tax - {order_number}"
            })

        # D. Perpetual Inventory: COGS & Inventory Reduction
        if total_cogs > 0:
            total_cogs_q = total_cogs.quantize(_D2, ROUND_HALF_UP)
            if acc_cogs:
                je_lines.append({
                    "account_id": acc_cogs,
                    "debit": total_cogs_q,
                    "credit": 0,
                    "description": f"POS COGS - {order_number}"
                })
            if acc_inventory:
                je_lines.append({
                    "account_id": acc_inventory,
                    "debit": 0,
                    "credit": total_cogs_q,
                    "description": f"POS Inventory Deduct - {order_number}"
                })

        # Create Journal Entry if accounts are mapped
        if je_lines:
            # Validate JE lines (balance, None accounts, negatives)
            from utils.accounting import prepare_je_lines
            try:
                je_lines = prepare_je_lines(je_lines, source=f"POS-{order_number}")
            except Exception as e:
                logger.error(f"POS JE validation failed for {order_number}: {e}")
                raise

            import uuid
            # Get treasury currency
            pos_currency = selected_treasury.get("currency") if selected_treasury else base_currency

            gl_create_journal_entry(
                db=db,
                company_id=current_user.company_id,
                date=datetime.now().date(),
                description=f"POS Order {order_number} ({pos_currency})",
                lines=je_lines,
                user_id=current_user.id,
                branch_id=branch_id,
                reference=order_number,
                currency=pos_currency,
                source="POS-Order",
                source_id=order_id
            )

        # Update individual payment method totals if you have columns for them
        # For now, we assume total_sales covers it all, but you might want
        # specifically to log cash_sales and bank_sales for reconciliation.

        # 6. Update Treasury Balance — T1.3a idempotent recompute
        if treasury_id:
            from utils.treasury_balance import recalc_treasury_from_gl
            recalc_treasury_from_gl(db, treasury_id)

        # 7. Update Customer Balance (if customer-linked POS sale)
        if order_in.customer_id and order_in.status == 'paid':
            try:
                credit_payments = sum(_dec(p.amount) for p in order_in.payments if p.method in ('credit', 'on_account'))
                if credit_payments > 0:
                    credit_amt = credit_payments.quantize(_D2, ROUND_HALF_UP)

                    # Update party_site_balances (positive = increases customer balance)
                    from utils.party_balance import update_party_site_balance
                    update_party_site_balance(db, party_id=order_in.customer_id, branch_id=branch_id,
                                              currency=pos_currency, amount=credit_amt)
            except Exception:
                # SEC-T2.11: silently dropping a credit-balance UPDATE leaves the
                # customer ledger out of sync with the GL. Surface the failure
                # and let the outer transaction roll back instead of swallowing.
                logger.exception("POS: failed to update party balance for credit sale")
                db.rollback()
                raise HTTPException(**http_error(500, "customer_balance_update_failed", request))

    db.commit()

    log_activity(
        db, user_id=current_user.id, username=current_user.username,
        action="create_pos_order", resource_type="pos_order",
        resource_id=str(order_id),
        details={"order_number": order_number, "total": str(total), "status": order_in.status, "branch_id": branch_id},
        request=request, branch_id=branch_id
    )

    return OrderResponse(
        id=order_id,
        order_number=order_number,
        total_amount=total,
        status=order_in.status,
        created_at=datetime.now()
    )


# --- Hold Orders ---

@router.get("/orders/held", response_model=List[dict], dependencies=[Depends(require_permission("pos.view"))])
def get_held_orders(
    branch_id: Optional[int] = None,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all held orders for current session"""
    try:
        branch_scope = resolve_branch_scope(current_user, branch_id)
        params = {}
        branch_filter = branch_scope_filter_from_scope(branch_scope, "po.branch_id", params)
        result = db.execute(text( # noqa
                    f"""
            SELECT po.id, po.order_number, po.total_amount, po.status, po.created_at,
                   COALESCE(c.name, po.walk_in_customer_name, 'عميل نقدي') as customer_name,
                   (SELECT COUNT(*) FROM pos_order_lines WHERE order_id = po.id) as items_count
            FROM pos_orders po
            LEFT JOIN parties c ON po.customer_id = c.id
            WHERE po.status = 'hold'
            {branch_filter}
            ORDER BY po.created_at DESC
        """), params).fetchall()

        return [dict(r._mapping) for r in result]
    except Exception as e:
        logger.error(f"Error fetching held orders: {str(e)}")
        return []


@router.post("/orders/{order_id}/resume", dependencies=[Depends(require_permission("pos.manage"))], response_model=Dict[str, Any])
def resume_held_order(request: Request, 
    order_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Resume a held order - returns full order details"""
    order = db.execute(text("""
        SELECT po.*,
               COALESCE(c.name, po.walk_in_customer_name) as customer_name
        FROM pos_orders po
        LEFT JOIN parties c ON po.customer_id = c.id
        WHERE po.id = :id AND po.status = 'hold'
    """), {"id": order_id}).fetchone()

    if not order:
        raise HTTPException(**http_error(404, "held_order_not_found", request))

    if order.branch_id:
        validate_branch_access(current_user, order.branch_id)

    # Get order items
    items = db.execute(text("""
        SELECT poi.*, p.product_name as name, p.product_code as code, p.barcode
        FROM pos_order_lines poi
        JOIN products p ON poi.product_id = p.id
        WHERE poi.order_id = :id
    """), {"id": order_id}).fetchall()

    return {
        "order": dict(order._mapping),
        "items": [dict(i._mapping) for i in items]
    }


@router.delete("/orders/{order_id}/cancel-held", dependencies=[Depends(require_permission("pos.manage"))], response_model=Dict[str, Any])
def cancel_held_order(
    order_id: int,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Cancel a held order"""
    order = db.execute(text("""
        SELECT id, branch_id, order_number FROM pos_orders
        WHERE id = :id AND status = 'hold'
    """), {"id": order_id}).fetchone()

    if not order:
        raise HTTPException(**http_error(404, "held_order_not_found", request))

    if order.branch_id:
        validate_branch_access(current_user, order.branch_id)

    # Delete related records from all possible tables to avoid foreign key issues
    db.execute(text("DELETE FROM pos_order_lines WHERE order_id = :id"), {"id": order_id})
    db.execute(text("DELETE FROM pos_payments WHERE order_id = :id"), {"id": order_id})
    db.execute(text("DELETE FROM pos_orders WHERE id = :id"), {"id": order_id})
    db.commit()

    log_activity(
        db, user_id=current_user.id, username=current_user.username,
        action="cancel_held_order", resource_type="pos_order",
        resource_id=str(order_id),
        details={"order_number": getattr(order, "order_number", None)},
        request=request, branch_id=getattr(order, "branch_id", None)
    )

    return {"message": i18n_message("order_cancelled_success", request)}


# --- Returns ---

@router.post("/orders/{order_id}/return", dependencies=[Depends(require_permission("pos.returns"))], response_model=Dict[str, Any])
def create_return(
    order_id: int,
    return_in: ReturnCreate,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Process a return for a paid order"""
    # Get base currency
    from utils.accounting import get_base_currency
    base_currency = get_base_currency(db)
    # Verify original order exists and is paid
    order = db.execute(text("""
        SELECT o.id, o.order_number, o.session_id, o.warehouse_id, s.branch_id
        FROM pos_orders o
        JOIN pos_sessions s ON o.session_id = s.id
        WHERE o.id = :id AND o.status = 'paid'
    """), {"id": order_id}).fetchone()

    if not order:
        raise HTTPException(**http_error(404, "original_order_not_found_or_not_paid", request))

    branch_id = validate_branch_access(current_user, order.branch_id)

    total_refund = Decimal('0')

    # Pre-calculate total refund to check cash sufficiency
    for item in return_in.items:
        orig_item_pre = db.execute(text("""
            SELECT product_id, unit_price, quantity
            FROM pos_order_lines WHERE id = :id AND order_id = :order_id
        """), {"id": item.item_id, "order_id": order_id}).fetchone()
        if orig_item_pre:
            refund_amount = (_dec(item.quantity) * _dec(orig_item_pre.unit_price)).quantize(_D2, ROUND_HALF_UP)
            tax_info = resolve_line_tax(branch_id, orig_item_pre.product_id, db)
            refund_tax = (refund_amount * (_dec(tax_info["tax_rate"]) / Decimal('100'))).quantize(_D2, ROUND_HALF_UP)
            total_refund += refund_amount + refund_tax

    # Check cash sufficiency for cash refunds
    if return_in.refund_method == 'cash' and total_refund > 0:
        session_info = db.execute(text("""
            SELECT s.treasury_account_id, COALESCE(ta.current_balance, 0) as cash_balance
            FROM pos_sessions s
            LEFT JOIN treasury_accounts ta ON s.treasury_account_id = ta.id
            WHERE s.id = :sid
        """), {"sid": order.session_id}).fetchone()
        if session_info and session_info.treasury_account_id:
            validate_treasury_account_access(db, current_user, session_info.treasury_account_id, branch_id)
        if session_info and _dec(session_info.cash_balance) < total_refund:
            raise HTTPException(status_code=400, detail=i18n_message("insufficient_cash_for_return", request))

    total_refund = Decimal('0')  # Reset for actual calculation
    total_refund_tax = Decimal('0')  # Track VAT on returns
    return_lines = []

    for item in return_in.items:
        # Get original item details
        orig_item = db.execute(text("""
            SELECT product_id, unit_price, quantity, tax_rate
            FROM pos_order_lines WHERE id = :id AND order_id = :order_id
        """), {"id": item.item_id, "order_id": order_id}).fetchone()

        if not orig_item:
            raise HTTPException(status_code=404, detail=i18n_message("item_not_found_in_order", request))

        already_returned = db.execute(text("""
            SELECT COALESCE(SUM(ri.quantity), 0)
            FROM pos_return_items ri
            JOIN pos_returns r ON r.id = ri.return_id
            WHERE ri.original_item_id = :item_id
              AND r.original_order_id = :order_id
        """), {"item_id": item.item_id, "order_id": order_id}).scalar() or 0

        if _dec(item.quantity) + _dec(already_returned) > _dec(orig_item.quantity):
            raise HTTPException(**http_error(400, "return_qty_exceeds_original", request))

        refund_amount = (_dec(item.quantity) * _dec(orig_item.unit_price)).quantize(_D2, ROUND_HALF_UP)
        # Re-resolve tax via engine (handles exemptions, rate changes since order)
        tax_info = resolve_line_tax(branch_id, orig_item.product_id, db)
        effective_tax_rate = tax_info["tax_rate"]
        refund_tax = (refund_amount * (effective_tax_rate / Decimal('100'))).quantize(_D2, ROUND_HALF_UP)
        total_refund += refund_amount
        total_refund_tax += refund_tax
        return_lines.append({"item": item, "orig_item": orig_item})

    # Find active session to link this return to current cash count
    active_session = db.execute(text("SELECT id FROM pos_sessions WHERE user_id = :uid AND status = 'opened'"), {"uid": current_user.id}).fetchone()
    curr_session_id = active_session.id if active_session else None

    # Create return record before inventory reversal so cost layers and stock tx
    # point at the real POS return document.
    return_id = db.execute(text("""
        INSERT INTO pos_returns (
            original_order_id, user_id, session_id, refund_amount, refund_method, notes, created_at
        ) VALUES (:order_id, :user_id, :sess_id, :amount, :method, :notes, CURRENT_TIMESTAMP)
        RETURNING id
    """), {
        "order_id": order_id,
        "user_id": current_user.id,
        "sess_id": curr_session_id,
        "amount": total_refund,
        "method": return_in.refund_method,
        "notes": return_in.notes
    }).scalar()

    # Insert return items
    for line in return_lines:
        item = line["item"]
        db.execute(text("""
            INSERT INTO pos_return_items (return_id, original_item_id, quantity, reason)
            VALUES (:rid, :iid, :qty, :reason)
        """), {
            "rid": return_id,
            "iid": item.item_id,
            "qty": item.quantity,
            "reason": item.reason
        })

    total_cogs_return = Decimal('0')

    for line in return_lines:
        item = line["item"]
        orig_item = line["orig_item"]

        # Update stock (add back) - use 'inventory' table (not warehouse_stock)
        if order.warehouse_id:
            # T035-T037: Use handle_return for FIFO/LIFO cost layer reversal
            from services.costing_service import CostingService
            costing_method = CostingService._get_product_costing_method(db, orig_item.product_id, order.warehouse_id)
            orig_cost_row = db.execute(text("""
                SELECT unit_cost
                FROM inventory_transactions
                WHERE reference_type = 'pos_order'
                  AND reference_id = :order_id
                  AND product_id = :pid
                ORDER BY id DESC
                LIMIT 1
            """), {"order_id": order_id, "pid": orig_item.product_id}).fetchone()
            orig_cost = _dec(orig_cost_row.unit_cost) if orig_cost_row and orig_cost_row.unit_cost is not None else _dec(db.execute(text(
                "SELECT cost_price FROM products WHERE id = :id"
            ), {"id": orig_item.product_id}).scalar() or 0)

            if costing_method in ("fifo", "lifo"):
                try:
                    return_result = CostingService.handle_return(
                        db,
                        product_id=orig_item.product_id,
                        warehouse_id=order.warehouse_id,
                        quantity=item.quantity,
                        unit_cost=orig_cost,
                        source_document_type="pos_return",
                        source_document_id=return_id,
                        costing_method=costing_method,
                        original_source_document_type="pos_order",
                        original_source_document_id=order_id,
                    )
                    restored_cost = _dec(return_result.get("restored_unit_cost", orig_cost))
                    restored_total = _dec(return_result.get("restored_total_cost", orig_cost * _dec(item.quantity)))
                except ValueError:
                    raise HTTPException(**http_error(400, "invalid_request", request))
            else:
                restored_cost = orig_cost
                restored_total = (orig_cost * _dec(item.quantity)).quantize(_D4, ROUND_HALF_UP)
                CostingService.update_cost(
                    db,
                    product_id=orig_item.product_id,
                    warehouse_id=order.warehouse_id,
                    new_qty=item.quantity,
                    new_price=orig_cost,
                )

            db.execute(text("""
                INSERT INTO inventory (product_id, warehouse_id, quantity, average_cost, updated_at)
                VALUES (:pid, :wid, :qty, :cost, NOW())
                ON CONFLICT (product_id, warehouse_id)
                DO UPDATE SET quantity = inventory.quantity + EXCLUDED.quantity,
                              updated_at = NOW()
            """), {
                "qty": item.quantity,
                "pid": orig_item.product_id,
                "wid": order.warehouse_id,
                "cost": restored_cost,
            })

            total_cogs_return += _dec(restored_total)

            # T037: Log inventory transaction with restored cost
            db.execute(text("""
                INSERT INTO inventory_transactions (
                    product_id, warehouse_id, transaction_type,
                    reference_type, reference_id,
                    quantity, unit_cost, total_cost, created_by
                ) VALUES (
                    :pid, :wid, 'return_in',
                    'pos_return', :order_id,
                    :qty, :cost, :total_cost, :uid
                )
            """), {
                "pid": orig_item.product_id,
                "wid": order.warehouse_id,
                "qty": item.quantity,
                "order_id": return_id,
                "cost": restored_cost,
                "total_cost": restored_total,
                "uid": current_user.id
            })

    # Update session totals (subtract refund)
    db.execute(text("""
        UPDATE pos_sessions
        SET total_returns = COALESCE(total_returns, 0) + :amount
        WHERE id = :id
    """), {"amount": total_refund, "id": order.session_id})

    # FISCAL-LOCK: Reject if accounting period is closed
    check_fiscal_period_open(db, datetime.now().date())

    # --- Create GL Journal Entries for Return ---
    # GL-FIX: Use configured account mappings with fallback to account_code lookup
    from utils.accounting import get_mapped_account_id

    def get_acc_id(code):
        return db.execute(text("SELECT id FROM accounts WHERE account_code = :code"), {"code": code}).scalar()

    acc_sales = get_mapped_account_id(db, "acc_map_sales") or get_acc_id("SALE-G")
    acc_cash = get_mapped_account_id(db, "acc_map_cash_main") or get_acc_id("BOX")
    acc_cogs = get_mapped_account_id(db, "acc_map_cogs") or get_acc_id("CGS")
    # F-31: returned goods come back into the order's source warehouse, so
    # debit its mapped inventory account.
    from utils.inventory_accounts import resolve_warehouse_inventory_account
    acc_inventory = resolve_warehouse_inventory_account(db, order.warehouse_id) or get_acc_id("INV")
    acc_vat_out = get_mapped_account_id(db, "acc_map_vat_output") or get_acc_id("VAT-OUT")

    # Get treasury for session
    session_treasury = db.execute(text("SELECT treasury_account_id FROM pos_sessions WHERE id = :id"), {"id": order.session_id}).fetchone()
    if session_treasury and session_treasury.treasury_account_id:
        selected_treasury = validate_treasury_account_access(
            db, current_user, session_treasury.treasury_account_id, branch_id
        )
        acc_cash = selected_treasury.get("gl_account_id") or acc_cash

    total_refund_with_tax = (total_refund + total_refund_tax).quantize(_D2, ROUND_HALF_UP)

    if acc_sales and acc_cash:
        je_lines = []
        # Reverse: Debit Sales Revenue (net subtotal)
        je_lines.append({
            "account_id": acc_sales, "debit": total_refund, "credit": 0, "description": "POS Return Revenue Reversal"
        })
        # Reverse: Debit VAT Output (tax portion)
        if total_refund_tax > 0 and acc_vat_out:
            je_lines.append({
                "account_id": acc_vat_out, "debit": total_refund_tax, "credit": 0, "description": "POS Return VAT Reversal"
            })
        # Credit: Cash/Bank (total including tax)
        je_lines.append({
            "account_id": acc_cash, "debit": 0, "credit": total_refund_with_tax, "description": "POS Return Cash Refund"
        })

        # Reverse COGS using the restored cost from the original POS movement.
        if total_cogs_return > 0 and acc_cogs and acc_inventory:
            total_cogs_ret_q = total_cogs_return.quantize(_D2, ROUND_HALF_UP)
            je_lines.append({
                "account_id": acc_inventory, "debit": total_cogs_ret_q, "credit": 0, "description": "POS Return Inventory Restore"
            })
            je_lines.append({
                "account_id": acc_cogs, "debit": 0, "credit": total_cogs_ret_q, "description": "POS Return COGS Reversal"
            })

        gl_create_journal_entry(
            db=db,
            company_id=current_user.company_id,
            date=datetime.now().date(),
            description=f"POS Return for Order {order.order_number}",
            lines=je_lines,
            user_id=current_user.id,
            branch_id=branch_id,
            reference=f"RTN-{order.order_number}",
            currency=base_currency,
            source="POS-Return",
            source_id=return_id
        )

        # Update treasury balance only for cash refunds — T1.3a idempotent recompute
        if return_in.refund_method == 'cash' and session_treasury and session_treasury.treasury_account_id:
            from utils.treasury_balance import recalc_treasury_from_gl
            recalc_treasury_from_gl(db, session_treasury.treasury_account_id)

    db.commit()

    log_activity(
        db, user_id=current_user.id, username=current_user.username,
        action="create_pos_return", resource_type="pos_return",
        resource_id=str(return_id),
        details={"order_id": order_id, "order_number": order.order_number, "refund_amount": str(total_refund), "refund_method": return_in.refund_method},
        request=request, branch_id=order.branch_id
    )

    return {
        "return_id": return_id,
        "refund_amount": str(total_refund),
        "message": i18n_message("return_processed_success", request)
    }


@router.get("/orders/{order_id}/details", dependencies=[Depends(require_permission("pos.view"))], response_model=Dict[str, Any])
def get_order_details(request: Request, 
    order_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get full order details for returns"""
    order = db.execute(text("""
        SELECT po.*,
               COALESCE(c.name, po.walk_in_customer_name, 'عميل نقدي') as customer_name
        FROM pos_orders po
        LEFT JOIN parties c ON po.customer_id = c.id
        WHERE po.id = :id
    """), {"id": order_id}).fetchone()

    if not order:
        raise HTTPException(**http_error(404, "order_not_found", request))

    if hasattr(order, 'branch_id') and order.branch_id:
        validate_branch_access(current_user, order.branch_id)

    items = db.execute(text("""
        SELECT poi.*, p.product_name as name
        FROM pos_order_lines poi
        JOIN products p ON poi.product_id = p.id
        WHERE poi.order_id = :id
    """), {"id": order_id}).fetchall()

    return {
        "order": dict(order._mapping),
        "items": [dict(i._mapping) for i in items]
    }


# =====================================================
# 8.10 POS IMPROVEMENTS
# =====================================================

# ---------- POS-003: Promotions & Discounts ----------
