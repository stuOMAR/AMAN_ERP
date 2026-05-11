"""
INV-001: إشعار دائن - Sales Credit Note
INV-002: إشعار مدين - Sales Debit Note

Credit Note (إشعار دائن): Reduces customer balance (e.g., returns, price correction down)
  GL: Debit Sales Revenue + VAT Output, Credit AR/Cash

Debit Note (إشعار مدين): Increases customer balance (e.g., undercharge correction, additional charges)
  GL: Debit AR, Credit Sales Revenue + VAT Output
"""
from fastapi import APIRouter, Depends, HTTPException, status, Body, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from database import get_db_connection
from routers.auth import get_current_user
from utils.permissions import branch_scope_filter_from_scope, require_permission, require_sensitive_permission, resolve_branch_scope, validate_branch_access
from utils.audit import log_activity
from utils.accounting import (
    get_mapped_account_id,
    generate_sequential_number,
    get_base_currency,
    prepare_je_lines,
)
from services.gl_service import create_journal_entry  # TASK-015: centralized GL posting
from services.tax_engine import resolve_line_tax
from utils.party_balance import update_party_site_balance
import json
import logging

logger = logging.getLogger(__name__)

credit_notes_router = APIRouter()

_D2 = Decimal("0.01")
_D4 = Decimal("0.0001")


def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal("0")


def _json_param(value):
    if value is None:
        return None
    return value if isinstance(value, str) else json.dumps(value)


def _line_key(product_id, unit_price, tax_rate) -> tuple[int, Decimal, Decimal]:
    return (
        int(product_id),
        _dec(unit_price).quantize(_D2, ROUND_HALF_UP),
        _dec(tax_rate).quantize(_D2, ROUND_HALF_UP),
    )


def _line_tax_factor(invoice_tax_amount, original_rows) -> Decimal:
    raw_tax = Decimal("0")
    for row in original_rows:
        gross = (_dec(row.quantity) * _dec(row.unit_price)).quantize(_D2, ROUND_HALF_UP)
        taxable = gross - _dec(getattr(row, "discount", 0))
        raw_tax += (taxable * _dec(row.tax_rate) / Decimal("100")).quantize(_D2, ROUND_HALF_UP)
    if raw_tax <= 0:
        return Decimal("1")
    factor = (_dec(invoice_tax_amount) / raw_tax)
    return max(Decimal("0"), min(Decimal("1"), factor))


def _reversal_taxable_amount(original_line, quantity) -> Decimal:
    original_qty = _dec(original_line.quantity)
    if original_qty <= 0:
        raise HTTPException(**http_error(400, ("original_line_qty_invalid", request)))
    gross = (_dec(original_line.quantity) * _dec(original_line.unit_price)).quantize(_D2, ROUND_HALF_UP)
    taxable = gross - _dec(getattr(original_line, "discount", 0))
    ratio = _dec(quantity) / original_qty
    return (taxable * ratio).quantize(_D2, ROUND_HALF_UP)


def _reversal_discount_amount(original_line, quantity) -> Decimal:
    original_qty = _dec(original_line.quantity)
    if original_qty <= 0:
        return Decimal("0")
    ratio = _dec(quantity) / original_qty
    return (_dec(getattr(original_line, "discount", 0)) * ratio).quantize(_D2, ROUND_HALF_UP)


def _load_sales_invoice_reverse_context(db, invoice_id: int, party_id: int):
    orig = db.execute(text("""
        SELECT id, party_id, total, tax_amount, invoice_type, branch_id, invoice_date
        FROM invoices
        WHERE id = :id
    """), {"id": invoice_id}).fetchone()
    if not orig:
        raise HTTPException(**http_error(400, "linked_invoice_not_found"))
    if int(orig.party_id) != int(party_id):
        raise HTTPException(**http_error(400, "invoice_not_for_customer"))
    if orig.invoice_type not in ("sales",):
        raise HTTPException(**http_error(400, "credit_note_must_link_sales_invoice", request))

    rows = db.execute(text("""
        SELECT product_id, quantity, unit_price, tax_rate, tax_rate_id, applied_taxes, discount
        FROM invoice_lines
        WHERE invoice_id = :id
    """), {"id": invoice_id}).fetchall()
    by_product: dict[int, list] = {}
    for row in rows:
        if row.product_id is not None:
            by_product.setdefault(int(row.product_id), []).append(row)

    credited = db.execute(text("""
        SELECT il.product_id, il.unit_price, il.tax_rate, COALESCE(SUM(il.quantity), 0) AS qty
        FROM invoices cn
        JOIN invoice_lines il ON il.invoice_id = cn.id
        WHERE cn.related_invoice_id = :id
          AND cn.invoice_type = 'sales_credit_note'
          AND COALESCE(cn.status, '') != 'cancelled'
          AND il.product_id IS NOT NULL
        GROUP BY il.product_id, il.unit_price, il.tax_rate
    """), {"id": invoice_id}).fetchall()

    returned = db.execute(text("""
        SELECT srl.product_id, srl.unit_price, srl.tax_rate, COALESCE(SUM(srl.quantity), 0) AS qty
        FROM sales_returns sr
        JOIN sales_return_lines srl ON srl.return_id = sr.id
        WHERE sr.invoice_id = :id
          AND COALESCE(sr.status, '') != 'cancelled'
          AND srl.product_id IS NOT NULL
        GROUP BY srl.product_id, srl.unit_price, srl.tax_rate
    """), {"id": invoice_id}).fetchall()

    used_qty = {
        _line_key(r.product_id, r.unit_price, r.tax_rate): _dec(r.qty)
        for r in credited
    }
    for row in returned:
        key = _line_key(row.product_id, row.unit_price, row.tax_rate)
        used_qty[key] = used_qty.get(key, Decimal("0")) + _dec(row.qty)

    return orig, by_product, used_qty, _line_tax_factor(orig.tax_amount, rows)


def _original_line_for_reversal(original_lines: dict[int, list], product_id: int, unit_price) -> Any:
    candidates = original_lines.get(int(product_id), [])
    if not candidates:
        raise HTTPException(**http_error(400, "item_not_in_invoice", request))
    if len(candidates) == 1:
        return candidates[0]
    price = _dec(unit_price)
    matched = [row for row in candidates if _dec(row.unit_price) == price]
    if len(matched) == 1:
        return matched[0]
    raise HTTPException(**http_error(400, "multi_line_tax_ambiguity", request))


# ==================== CREDIT NOTES (إشعار دائن) ====================

@credit_notes_router.get("/credit-notes", dependencies=[Depends(require_permission("sales.view"))], response_model=Dict[str, Any])
def list_sales_credit_notes(
    party_id: Optional[int] = None,
    status_filter: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
):
    """قائمة إشعارات دائنة (مبيعات)"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        conditions = ["i.invoice_type = 'sales_credit_note'"]
        params = {}

        if party_id:
            conditions.append("i.party_id = :party_id")
            params["party_id"] = party_id
        if status_filter:
            conditions.append("i.status = :status")
            params["status"] = status_filter
        if date_from:
            conditions.append("i.invoice_date >= :date_from")
            params["date_from"] = date_from
        if date_to:
            conditions.append("i.invoice_date <= :date_to")
            params["date_to"] = date_to
        if search:
            conditions.append("(i.invoice_number ILIKE :search OR i.notes ILIKE :search)")
            params["search"] = f"%{search}%"
        branch_condition = branch_scope_filter_from_scope(branch_scope, "i.branch_id", params, prefix="").strip()
        if branch_condition:
            conditions.append(branch_condition)

        where = " AND ".join(conditions)
        total = db.execute(text(f"SELECT COUNT(*) FROM invoices i WHERE {where}"), params).scalar()

        offset = (page - 1) * limit
        params["limit"] = limit
        params["offset"] = offset

        rows = db.execute(text(f"""
            SELECT i.*,
                   p.name AS party_name,
                   ri.invoice_number AS related_invoice_number,
                   cu.username AS created_by_name
            FROM invoices i
            LEFT JOIN parties p ON i.party_id = p.id
            LEFT JOIN invoices ri ON i.related_invoice_id = ri.id
            LEFT JOIN company_users cu ON i.created_by = cu.id
            WHERE {where}
            ORDER BY i.invoice_date DESC, i.id DESC
            LIMIT :limit OFFSET :offset
        """), params).fetchall()

        return {
            "items": [dict(r._mapping) for r in rows],
            "total": total,
            "page": page,
            "pages": (total + limit - 1) // limit,
        }
    finally:
        db.close()


@credit_notes_router.get("/credit-notes/{note_id}", dependencies=[Depends(require_permission("sales.view"))], response_model=Dict[str, Any])
def get_sales_credit_note(note_id: int, current_user: dict = Depends(get_current_user)):
    """تفاصيل إشعار دائن"""
    db = get_db_connection(current_user.company_id)
    try:
        note = db.execute(text("""
            SELECT i.*,
                   p.name AS party_name, p.phone AS party_phone, p.tax_number AS party_tax,
                   ri.invoice_number AS related_invoice_number,
                   cu.username AS created_by_name
            FROM invoices i
            LEFT JOIN parties p ON i.party_id = p.id
            LEFT JOIN invoices ri ON i.related_invoice_id = ri.id
            LEFT JOIN company_users cu ON i.created_by = cu.id
            WHERE i.id = :id AND i.invoice_type = 'sales_credit_note'
        """), {"id": note_id}).fetchone()
        if not note:
            raise HTTPException(**http_error(404, "credit_note_not_found"))

        # Enforce branch access for single resource
        from utils.permissions import validate_branch_access
        if note.branch_id:
            validate_branch_access(current_user, note.branch_id)

        lines = db.execute(text("""
            SELECT il.*, pr.name AS product_name, pr.sku AS product_sku
            FROM invoice_lines il
            LEFT JOIN products pr ON il.product_id = pr.id
            WHERE il.invoice_id = :id
            ORDER BY il.id
        """), {"id": note_id}).fetchall()

        result = dict(note._mapping)
        result["lines"] = [dict(l._mapping) for l in lines]
        return result
    finally:
        db.close()


@credit_notes_router.post("/credit-notes", status_code=status.HTTP_201_CREATED,
                          dependencies=[Depends(require_sensitive_permission("sales.manage_credit_notes"))], response_model=Dict[str, Any])
def create_sales_credit_note(
    request: Request,
    data: dict = Body(...),
    current_user: dict = Depends(get_current_user),
):
    """
    إنشاء إشعار دائن (مبيعات)
    يُخفض رصيد العميل ويعكس جزء من فاتورة المبيعات.
    
    GL:
      Debit: Sales Revenue (صافي), VAT Output (ضريبة)
      Credit: AR (إجمالي)
    
    data: {
        party_id, related_invoice_id, invoice_date, lines: [{product_id, description, quantity, unit_price, tax_rate, discount}],
        notes, branch_id, currency, exchange_rate, reason
    }
    """
    db = get_db_connection(current_user.company_id)
    try:
        party_id = data.get("party_id")
        related_invoice_id = data.get("related_invoice_id")
        lines = data.get("lines", [])
        if not lines:
            raise HTTPException(**http_error(400, "min_one_item_required"))
        if not party_id:
            raise HTTPException(**http_error(400, "customer_required"))

        original_invoice = None
        original_lines = {}
        already_reversed_qty = {}
        original_tax_factor = Decimal("1")
        if related_invoice_id:
            original_invoice, original_lines, already_reversed_qty, original_tax_factor = _load_sales_invoice_reverse_context(
                db, related_invoice_id, party_id
            )

        # Calculate totals
        inv_date = data.get("invoice_date", str(date.today()))
        # SLS-010: Prevent posting to closed fiscal periods
        from utils.fiscal_lock import check_fiscal_period_open
        check_fiscal_period_open(db, inv_date)

        base_currency = get_base_currency(db)
        currency = data.get("currency", base_currency)
        exchange_rate = _dec(data.get("exchange_rate", 1))
        if exchange_rate <= 0:
            raise HTTPException(**http_error(400, "exchange_rate_must_be_positive"))
        requested_branch_id = data.get("branch_id")
        if original_invoice:
            if (
                requested_branch_id
                and original_invoice.branch_id is not None
                and int(requested_branch_id) != int(original_invoice.branch_id)
            ):
                raise HTTPException(**http_error(400, "credit_note_branch_mismatch", request))
            requested_branch_id = original_invoice.branch_id
        branch_id = validate_branch_access(current_user, requested_branch_id)

        subtotal = Decimal("0")
        tax_total = Decimal("0")
        discount_total = Decimal("0")
        computed_lines = []

        for line in lines:
            qty = _dec(line.get("quantity", 1))
            price = _dec(line.get("unit_price", 0))
            disc = _dec(line.get("discount", 0))
            product_id = line.get("product_id")
            tax_rate_id = None
            applied_taxes = None
            if original_invoice:
                if not product_id:
                    raise HTTPException(**http_error(400, "item_required_for_credit_note", request))
                original_line = _original_line_for_reversal(original_lines, int(product_id), price)
                reverse_key = _line_key(original_line.product_id, original_line.unit_price, original_line.tax_rate)
                already_qty = already_reversed_qty.get(reverse_key, Decimal("0"))
                available_qty = _dec(original_line.quantity) - already_qty
                if qty > available_qty:
                    raise HTTPException(**http_error(400, "credit_note_qty_exceeds", request))
                tax_rate = _dec(original_line.tax_rate)
                tax_rate_id = original_line.tax_rate_id
                applied_taxes = original_line.applied_taxes
                price = _dec(original_line.unit_price)
                disc = _reversal_discount_amount(original_line, qty)
                line_net = _reversal_taxable_amount(original_line, qty)
                already_reversed_qty[reverse_key] = already_qty + qty
            elif product_id and branch_id:
                tax_info = resolve_line_tax(branch_id, product_id, db, inv_date, customer_id=party_id)
                tax_rate = tax_info["tax_rate"]
                tax_rate_id = tax_info.get("tax_rate_id")
                line_gross = qty * price
                line_net = line_gross - disc
            else:
                tax_rate = _dec(line.get("tax_rate", 0))
                line_gross = qty * price
                line_net = line_gross - disc
            tax_factor = original_tax_factor if original_invoice else Decimal("1")
            line_tax = (line_net * tax_rate / Decimal("100") * tax_factor).quantize(_D2, ROUND_HALF_UP)
            line_total = (line_net + line_tax).quantize(_D2, ROUND_HALF_UP)

            subtotal += line_net
            tax_total += line_tax
            discount_total += disc
            computed_lines.append({
                "product_id": product_id,
                "description": line.get("description", ""),
                "quantity": qty,
                "unit_price": price,
                "tax_rate": tax_rate,
                "tax_rate_id": tax_rate_id,
                "applied_taxes": applied_taxes,
                "discount": disc,
                "total": line_total,
            })

        total = (subtotal + tax_total).quantize(_D2, ROUND_HALF_UP)

        # Generate number & insert
        inv_num = generate_sequential_number(db, "SCN", "invoices", "invoice_number")
        result = db.execute(text("""
            INSERT INTO invoices (
                invoice_number, invoice_type, party_id, invoice_date, 
                subtotal, tax_amount, discount, total, paid_amount, status,
                notes, branch_id, related_invoice_id,
                currency, exchange_rate, created_by, party_site_id
            ) VALUES (
                :num, 'sales_credit_note', :party, :date,
                :sub, :tax, :disc, :total, 0, 'posted',
                :notes, :branch, :rel,
                :curr, :rate, :user, :party_site_id
            ) RETURNING id
        """), {
            "num": inv_num, "party": party_id, "date": inv_date,
            "sub": subtotal, "tax": tax_total, "disc": discount_total,
            "total": total, "notes": data.get("notes", ""),
            "branch": branch_id or (current_user.allowed_branches[0] if getattr(current_user, 'allowed_branches', []) else None),
            "rel": related_invoice_id, "curr": currency,
            "rate": exchange_rate, "user": current_user.id,
            "party_site_id": data.get("party_site_id"),
        })
        note_id = result.fetchone()[0]

        # Insert lines
        for cl in computed_lines:
            db.execute(text("""
                INSERT INTO invoice_lines (
                    invoice_id, product_id, description, quantity, unit_price,
                    tax_rate, tax_rate_id, applied_taxes, discount, total
                )
                VALUES (
                    :inv, :prod, :desc, :qty, :price,
                    :tax, :tax_rate_id, CAST(:applied_taxes AS jsonb), :disc, :total
                )
            """), {
                "inv": note_id, "prod": cl["product_id"],
                "desc": cl["description"], "qty": cl["quantity"],
                "price": cl["unit_price"], "tax": cl["tax_rate"],
                "tax_rate_id": cl["tax_rate_id"],
                "applied_taxes": _json_param(cl["applied_taxes"]),
                "disc": cl["discount"], "total": cl["total"],
            })

        # === GL Journal Entry ===
        # Credit Note reverses invoice: Debit Revenue+VAT, Credit AR
        acc_ar = get_mapped_account_id(db, "acc_map_ar")
        acc_sales = get_mapped_account_id(db, "acc_map_sales_rev")
        acc_vat = get_mapped_account_id(db, "acc_map_vat_out")

        if not acc_ar or not acc_sales:
            raise HTTPException(**http_error(400, "ar_sales_revenue_accounts_incomplete", request))

        gl_sub = (subtotal * exchange_rate).quantize(_D4, ROUND_HALF_UP)
        gl_tax = (tax_total * exchange_rate).quantize(_D4, ROUND_HALF_UP)
        gl_total = (total * exchange_rate).quantize(_D4, ROUND_HALF_UP)

        je_lines = []
        # Debit: Sales Revenue
        if gl_sub > 0:
            je_lines.append({
                "account_id": acc_sales, "debit": gl_sub, "credit": 0,
                "description": f"إشعار دائن - مرتجع إيرادات {inv_num}",
                "amount_currency": subtotal, "currency": currency,
            })
        # Debit: VAT Output
        if gl_tax > 0 and acc_vat:
            je_lines.append({
                "account_id": acc_vat, "debit": gl_tax, "credit": 0,
                "description": f"إشعار دائن - عكس ضريبة {inv_num}",
                "amount_currency": tax_total, "currency": currency,
            })
        # Credit: Accounts Receivable
        je_lines.append({
            "account_id": acc_ar, "debit": 0, "credit": gl_total,
            "description": f"إشعار دائن للعميل - {inv_num}",
            "amount_currency": total, "currency": currency,
        })

        je_num = f"JE-SCN-{inv_num}"
        # Validate JE lines
        valid_lines = prepare_je_lines(je_lines, source=f"SCN-{inv_num}")

        # TASK-015: centralized GL posting
        je_id, _je_number = create_journal_entry(
            db=db,
            company_id=current_user.company_id,
            date=str(inv_date),
            description=(
                f"إشعار دائن مبيعات {inv_num}"
                + (f" - مقابل فاتورة {related_invoice_id}" if related_invoice_id else "")
            ),
            lines=valid_lines,
            user_id=current_user.id,
            branch_id=branch_id or (current_user.allowed_branches[0] if current_user.allowed_branches else None),
            reference=inv_num,
            status="posted",
            currency=currency,
            exchange_rate=1.0,  # amounts already in base currency
            source="SalesCreditNote",
            source_id=related_invoice_id,
            username=getattr(current_user, "username", None),
            idempotency_key=f"scn-{inv_num}",
        )

        # Update related invoice paid_amount (credit note reduces what's owed)
        if related_invoice_id:
            db.execute(text("""
                UPDATE invoices SET paid_amount = paid_amount + :amt,
                    status = CASE
                        WHEN paid_amount + :amt >= total THEN 'paid'
                        WHEN paid_amount + :amt > 0 THEN 'partial'
                        ELSE status
                    END
                WHERE id = :id
            """), {"amt": total, "id": related_invoice_id})

        # Update customer balance via party_site_balances (credit note REDUCES what customer owes)
        gl_total_base = (total * exchange_rate).quantize(_D4, ROUND_HALF_UP)
        effective_branch = branch_id or (current_user.allowed_branches[0] if getattr(current_user, 'allowed_branches', []) else None)
        update_party_site_balance(db, party_id=party_id, branch_id=effective_branch,
                                  currency=currency, amount=-float(gl_total_base))

        db.commit()

        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="sales.credit_note.create",
            resource_type="sales_credit_note", resource_id=inv_num,
            details={"party_id": party_id, "total": str(total or 0), "related_invoice": related_invoice_id},
            request=request, branch_id=branch_id,
        )

        return {
            "success": True, "id": note_id, "invoice_number": inv_num,
            "journal_entry_id": je_id, "journal_entry_number": je_num,
            "message": i18n_message("credit_note_created_number", request),
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating sales credit note: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ==================== DEBIT NOTES (إشعار مدين) ====================

@credit_notes_router.get("/debit-notes", dependencies=[Depends(require_permission("sales.view"))], response_model=Dict[str, Any])
def list_sales_debit_notes(
    party_id: Optional[int] = None,
    status_filter: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
):
    """قائمة إشعارات مدينة (مبيعات)"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        conditions = ["i.invoice_type = 'sales_debit_note'"]
        params = {}

        if party_id:
            conditions.append("i.party_id = :party_id")
            params["party_id"] = party_id
        if status_filter:
            conditions.append("i.status = :status")
            params["status"] = status_filter
        if date_from:
            conditions.append("i.invoice_date >= :date_from")
            params["date_from"] = date_from
        if date_to:
            conditions.append("i.invoice_date <= :date_to")
            params["date_to"] = date_to
        if search:
            conditions.append("(i.invoice_number ILIKE :search OR i.notes ILIKE :search)")
            params["search"] = f"%{search}%"
        branch_condition = branch_scope_filter_from_scope(branch_scope, "i.branch_id", params, prefix="").strip()
        if branch_condition:
            conditions.append(branch_condition)

        where = " AND ".join(conditions)
        total = db.execute(text(f"SELECT COUNT(*) FROM invoices i WHERE {where}"), params).scalar()

        offset = (page - 1) * limit
        params["limit"] = limit
        params["offset"] = offset

        rows = db.execute(text(f"""
            SELECT i.*,
                   p.name AS party_name,
                   ri.invoice_number AS related_invoice_number,
                   cu.username AS created_by_name
            FROM invoices i
            LEFT JOIN parties p ON i.party_id = p.id
            LEFT JOIN invoices ri ON i.related_invoice_id = ri.id
            LEFT JOIN company_users cu ON i.created_by = cu.id
            WHERE {where}
            ORDER BY i.invoice_date DESC, i.id DESC
            LIMIT :limit OFFSET :offset
        """), params).fetchall()

        return {
            "items": [dict(r._mapping) for r in rows],
            "total": total,
            "page": page,
            "pages": (total + limit - 1) // limit,
        }
    finally:
        db.close()


@credit_notes_router.get("/debit-notes/{note_id}", dependencies=[Depends(require_permission("sales.view"))], response_model=Dict[str, Any])
def get_sales_debit_note(note_id: int, current_user: dict = Depends(get_current_user)):
    """تفاصيل إشعار مدين"""
    db = get_db_connection(current_user.company_id)
    try:
        note = db.execute(text("""
            SELECT i.*,
                   p.name AS party_name, p.phone AS party_phone, p.tax_number AS party_tax,
                   ri.invoice_number AS related_invoice_number,
                   cu.username AS created_by_name
            FROM invoices i
            LEFT JOIN parties p ON i.party_id = p.id
            LEFT JOIN invoices ri ON i.related_invoice_id = ri.id
            LEFT JOIN company_users cu ON i.created_by = cu.id
            WHERE i.id = :id AND i.invoice_type = 'sales_debit_note'
        """), {"id": note_id}).fetchone()
        if not note:
            raise HTTPException(**http_error(404, "debit_note_not_found"))

        # Enforce branch access for single resource
        from utils.permissions import validate_branch_access
        if note.branch_id:
            validate_branch_access(current_user, note.branch_id)

        lines = db.execute(text("""
            SELECT il.*, pr.name AS product_name, pr.sku AS product_sku
            FROM invoice_lines il
            LEFT JOIN products pr ON il.product_id = pr.id
            WHERE il.invoice_id = :id
            ORDER BY il.id
        """), {"id": note_id}).fetchall()

        result = dict(note._mapping)
        result["lines"] = [dict(l._mapping) for l in lines]
        return result
    finally:
        db.close()


@credit_notes_router.post("/debit-notes", status_code=status.HTTP_201_CREATED,
                          dependencies=[Depends(require_sensitive_permission("sales.manage_credit_notes"))], response_model=Dict[str, Any])
def create_sales_debit_note(
    request: Request,
    data: dict = Body(...),
    current_user: dict = Depends(get_current_user),
):
    """
    إنشاء إشعار مدين (مبيعات)
    يزيد رصيد العميل (تصحيح نقص في الفوترة أو رسوم إضافية).
    
    GL:
      Debit: AR (إجمالي)
      Credit: Sales Revenue (صافي), VAT Output (ضريبة)
    """
    db = get_db_connection(current_user.company_id)
    try:
        party_id = data.get("party_id")
        related_invoice_id = data.get("related_invoice_id")
        lines = data.get("lines", [])
        if not lines:
            raise HTTPException(**http_error(400, "min_one_item_required"))
        if not party_id:
            raise HTTPException(**http_error(400, "customer_required"))

        # Validate related invoice if provided
        if related_invoice_id:
            orig = db.execute(text(
                "SELECT id, party_id, invoice_type FROM invoices WHERE id = :id"
            ), {"id": related_invoice_id}).fetchone()
            if not orig:
                raise HTTPException(**http_error(400, "linked_invoice_not_found"))
            if orig.party_id != party_id:
                raise HTTPException(**http_error(400, "invoice_not_for_customer"))

        inv_date = data.get("invoice_date", str(date.today()))
        # SLS-010: Prevent posting to closed fiscal periods
        from utils.fiscal_lock import check_fiscal_period_open
        check_fiscal_period_open(db, inv_date)

        base_currency = get_base_currency(db)
        currency = data.get("currency", base_currency)
        exchange_rate = _dec(data.get("exchange_rate", 1))
        if exchange_rate <= 0:
            raise HTTPException(**http_error(400, "exchange_rate_must_be_positive"))
        branch_id = validate_branch_access(current_user, data.get("branch_id"))

        subtotal = Decimal("0")
        tax_total = Decimal("0")
        discount_total = Decimal("0")
        computed_lines = []

        for line in lines:
            qty = _dec(line.get("quantity", 1))
            price = _dec(line.get("unit_price", 0))
            disc = _dec(line.get("discount", 0))
            product_id = line.get("product_id")
            if product_id and branch_id:
                tax_info = resolve_line_tax(branch_id, product_id, db, inv_date, customer_id=party_id)
                tax_rate = tax_info["tax_rate"]
            else:
                tax_rate = _dec(line.get("tax_rate", 0))
            line_gross = qty * price
            line_net = line_gross - disc
            line_tax = (line_net * tax_rate / Decimal("100")).quantize(_D2, ROUND_HALF_UP)
            line_total = (line_net + line_tax).quantize(_D2, ROUND_HALF_UP)

            subtotal += line_net
            tax_total += line_tax
            discount_total += disc
            computed_lines.append({
                "product_id": product_id,
                "description": line.get("description", ""),
                "quantity": qty, "unit_price": price,
                "tax_rate": tax_rate, "discount": disc,
                "total": line_total,
            })

        total = (subtotal + tax_total).quantize(_D2, ROUND_HALF_UP)

        inv_num = generate_sequential_number(db, "SDN", "invoices", "invoice_number")
        result = db.execute(text("""
            INSERT INTO invoices (
                invoice_number, invoice_type, party_id, invoice_date,
                subtotal, tax_amount, discount, total, paid_amount, status,
                notes, branch_id, related_invoice_id,
                currency, exchange_rate, created_by, party_site_id
            ) VALUES (
                :num, 'sales_debit_note', :party, :date,
                :sub, :tax, :disc, :total, 0, 'unpaid',
                :notes, :branch, :rel,
                :curr, :rate, :user, :party_site_id
            ) RETURNING id
        """), {
            "num": inv_num, "party": party_id, "date": inv_date,
            "sub": subtotal, "tax": tax_total, "disc": discount_total,
            "total": total, "notes": data.get("notes", ""),
            "branch": branch_id or (current_user.allowed_branches[0] if getattr(current_user, 'allowed_branches', []) else None),
            "rel": related_invoice_id, "curr": currency,
            "rate": exchange_rate, "user": current_user.id,
            "party_site_id": data.get("party_site_id"),
        })
        note_id = result.fetchone()[0]

        for cl in computed_lines:
            db.execute(text("""
                INSERT INTO invoice_lines (invoice_id, product_id, description, quantity, unit_price, tax_rate, discount, total)
                VALUES (:inv, :prod, :desc, :qty, :price, :tax, :disc, :total)
            """), {
                "inv": note_id, "prod": cl["product_id"],
                "desc": cl["description"], "qty": cl["quantity"],
                "price": cl["unit_price"], "tax": cl["tax_rate"],
                "disc": cl["discount"], "total": cl["total"],
            })

        # === GL: Debit AR, Credit Revenue + VAT ===
        acc_ar = get_mapped_account_id(db, "acc_map_ar")
        acc_sales = get_mapped_account_id(db, "acc_map_sales_rev")
        acc_vat = get_mapped_account_id(db, "acc_map_vat_out")

        if not acc_ar or not acc_sales:
            raise HTTPException(**http_error(400, "ar_sales_revenue_accounts_incomplete", request))

        gl_sub = (subtotal * exchange_rate).quantize(_D4, ROUND_HALF_UP)
        gl_tax = (tax_total * exchange_rate).quantize(_D4, ROUND_HALF_UP)
        gl_total = (total * exchange_rate).quantize(_D4, ROUND_HALF_UP)

        je_lines = []
        # Debit: AR
        je_lines.append({
            "account_id": acc_ar, "debit": gl_total, "credit": 0,
            "description": f"إشعار مدين - زيادة ذمم {inv_num}",
            "amount_currency": total, "currency": currency,
        })
        # Credit: Sales Revenue
        if gl_sub > 0:
            je_lines.append({
                "account_id": acc_sales, "debit": 0, "credit": gl_sub,
                "description": f"إشعار مدين - إيرادات إضافية {inv_num}",
                "amount_currency": subtotal, "currency": currency,
            })
        # Credit: VAT
        if gl_tax > 0 and acc_vat:
            je_lines.append({
                "account_id": acc_vat, "debit": 0, "credit": gl_tax,
                "description": f"إشعار مدين - ضريبة إضافية {inv_num}",
                "amount_currency": tax_total, "currency": currency,
            })

        je_num = f"JE-SDN-{inv_num}"
        # Validate JE lines
        valid_dn_lines = prepare_je_lines(je_lines, source=f"SDN-{inv_num}")

        # TASK-015: centralized GL posting
        je_id, _je_number = create_journal_entry(
            db=db,
            company_id=current_user.company_id,
            date=str(inv_date),
            description=f"إشعار مدين مبيعات {inv_num}",
            lines=valid_dn_lines,
            user_id=current_user.id,
            branch_id=branch_id or (current_user.allowed_branches[0] if current_user.allowed_branches else None),
            reference=inv_num,
            status="posted",
            currency=currency,
            exchange_rate=1.0,  # amounts already in base currency
            source="SalesDebitNote",
            source_id=note_id,
            username=getattr(current_user, "username", None),
            idempotency_key=f"sdn-{inv_num}",
        )

        # Update customer balance via party_site_balances (debit note INCREASES what customer owes)
        gl_total_base = (total * exchange_rate).quantize(_D4, ROUND_HALF_UP)
        effective_branch = branch_id or (current_user.allowed_branches[0] if getattr(current_user, 'allowed_branches', []) else None)
        update_party_site_balance(db, party_id=party_id, branch_id=effective_branch,
                                  currency=currency, amount=float(gl_total_base))

        db.commit()

        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="sales.debit_note.create",
            resource_type="sales_debit_note", resource_id=inv_num,
            details={"party_id": party_id, "total": str(total or 0)},
            request=request, branch_id=branch_id,
        )

        return {
            "success": True, "id": note_id, "invoice_number": inv_num,
            "journal_entry_id": je_id, "journal_entry_number": je_num,
            "message": i18n_message("debit_note_created_number", request),
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating sales debit note: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
