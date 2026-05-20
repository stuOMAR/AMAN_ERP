"""Sales returns endpoints."""
from fastapi import APIRouter, Depends, HTTPException, status, Request, Header, Query
from utils.i18n import http_error, i18n_message
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import json
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.audit import log_activity
from utils.permissions import branch_scope_filter_from_scope, check_permission, require_permission, require_sensitive_permission, resolve_branch_scope, validate_branch_access, validate_treasury_account_access
from utils.accounting import get_mapped_account_id
from services.gl_service import create_journal_entry  # TASK-015: centralized GL posting
from services.tax_engine import resolve_line_tax
from utils.fiscal_lock import check_fiscal_period_open
from utils.party_balance import update_party_site_balance
from .schemas import SalesReturnCreate

returns_router = APIRouter()
logger = logging.getLogger(__name__)
_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')
_MAX_RATE_AGE_DAYS = 31
_TABLE_COLUMNS_CACHE: dict[tuple[str, str], frozenset[str]] = {}


def _dec(v) -> Decimal:
    return Decimal(str(v or 0))


def _company_id(user) -> str:
    return user.get("company_id") if isinstance(user, dict) else user.company_id


def _user_id(user) -> int:
    return user.get("id") if isinstance(user, dict) else user.id


def _username(user) -> str:
    return user.get("username") if isinstance(user, dict) else user.username


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
    factor = _dec(invoice_tax_amount) / raw_tax
    return max(Decimal("0"), min(Decimal("1"), factor))


def _reversal_taxable_amount(original_line, quantity) -> Decimal:
    original_qty = _dec(original_line.quantity)
    if original_qty <= 0:
        raise HTTPException(**http_error(400, "original_line_qty_invalid"))
    gross = (_dec(original_line.quantity) * _dec(original_line.unit_price)).quantize(_D2, ROUND_HALF_UP)
    taxable = gross - _dec(getattr(original_line, "discount", 0))
    ratio = _dec(quantity) / original_qty
    return (taxable * ratio).quantize(_D2, ROUND_HALF_UP)


def _load_original_sales_invoice_for_return(db, invoice_id: int, customer_id: int):
    invoice = db.execute(text("""
        SELECT id, party_id, branch_id, invoice_type, invoice_date, tax_amount
        FROM invoices
        WHERE id = :id
        FOR UPDATE
    """), {"id": invoice_id}).fetchone()
    if not invoice:
        raise HTTPException(**http_error(404, "original_invoice_not_found"))
    if invoice.invoice_type != "sales":
        raise HTTPException(**http_error(400, "return_must_link_sales_invoice"))
    if int(invoice.party_id) != int(customer_id):
        raise HTTPException(**http_error(400, "invoice_not_for_customer"))

    rows = db.execute(text("""
        SELECT product_id, quantity, unit_price, tax_rate, tax_rate_id, applied_taxes, discount
        FROM invoice_lines
        WHERE invoice_id = :id
          AND product_id IS NOT NULL
        FOR UPDATE
    """), {"id": invoice_id}).fetchall()
    by_product: dict[int, list] = {}
    for row in rows:
        by_product.setdefault(int(row.product_id), []).append(row)

    returned = db.execute(text("""
        SELECT srl.product_id, srl.unit_price, srl.tax_rate, COALESCE(SUM(srl.quantity), 0) AS qty
        FROM sales_returns sr
        JOIN sales_return_lines srl ON srl.return_id = sr.id
        WHERE sr.invoice_id = :id
          AND COALESCE(sr.status, '') != 'cancelled'
          AND srl.product_id IS NOT NULL
        GROUP BY srl.product_id, srl.unit_price, srl.tax_rate
    """), {"id": invoice_id}).fetchall()

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

    used_qty = {
        _line_key(r.product_id, r.unit_price, r.tax_rate): _dec(r.qty)
        for r in returned
    }
    for row in credited:
        key = _line_key(row.product_id, row.unit_price, row.tax_rate)
        used_qty[key] = used_qty.get(key, Decimal("0")) + _dec(row.qty)

    return invoice, by_product, used_qty, _line_tax_factor(invoice.tax_amount, rows)


def _original_line_for_return(original_lines: dict[int, list], product_id: int, unit_price):
    candidates = original_lines.get(int(product_id), [])
    if not candidates:
        raise HTTPException(**http_error(400, "item_not_in_invoice"))
    if len(candidates) == 1:
        return candidates[0]
    price = _dec(unit_price)
    matched = [row for row in candidates if _dec(row.unit_price) == price]
    if len(matched) == 1:
        return matched[0]
    raise HTTPException(**http_error(400, "multi_line_tax_ambiguity"))


def _table_columns(db, table_name: str) -> frozenset[str]:
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


@returns_router.get("/returns", response_model=Dict[str, Any], dependencies=[Depends(require_permission("sales.view"))])
def list_sales_returns(
    branch_id: Optional[int] = None,
    page: int = 1,
    limit: int = Query(default=25, le=100),
    current_user: dict = Depends(get_current_user),
):
    """عرض قائمة مرتجعات المبيعات — Fix 9: paginated, default 25, max 100."""
    skip = (page - 1) * limit
    branch_scope = resolve_branch_scope(current_user, branch_id)

    db = get_db_connection(_company_id(current_user))
    try:
        base_from = """
            FROM sales_returns r
            JOIN parties p ON r.party_id = p.id
            WHERE 1=1
        """
        params: Dict[str, Any] = {}
        filter_clause = branch_scope_filter_from_scope(branch_scope, "r.branch_id", params)

        total = db.execute(text(f"SELECT COUNT(*) {base_from} {filter_clause}"), params).scalar() or 0

        params["limit"] = limit
        params["skip"] = skip
        result = db.execute(text(f"""
            SELECT r.*, p.name as customer_name
            {base_from} {filter_clause}
            ORDER BY r.created_at DESC
            LIMIT :limit OFFSET :skip
        """), params).fetchall()

        return {
            "items": [dict(row._mapping) for row in result],
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit,
        }
    finally:
        db.close()


@returns_router.get(
    "/returns/unified",
    response_model=List[dict],
    dependencies=[Depends(require_permission("sales.view"))],
)
def list_unified_returns(request: Request, 
    branch_id: Optional[int] = None,
    source: Optional[str] = None,
    limit: int = 200,
    current_user: dict = Depends(get_current_user),
):
    """T6.6: قائمة موحّدة لجميع المرتجعات (مبيعات + نقطة بيع).

    تستعلم من الـ VIEW ``returns_unified`` الذي يجمع ``sales_returns``
    و ``pos_returns`` في صف واحد لكل مرتجع. ``source`` اختياري للتصفية
    (``sales`` أو ``pos``).
    """
    branch_scope = resolve_branch_scope(current_user, branch_id)

    if source not in (None, "sales", "pos"):
        raise HTTPException(**http_error(400, "source_must_be_sales_or_pos", request))
    limit = max(1, min(int(limit or 200), 1000))

    db = get_db_connection(_company_id(current_user))
    try:
        # Defensive: if migration 0019 has not yet been applied on this tenant
        # (or the view was dropped), fall back to an inline UNION ALL so the
        # endpoint stays available.
        view_exists = db.execute(
            text("SELECT to_regclass('public.returns_unified') AS v")
        ).scalar()
        if view_exists:
            query_str = "SELECT * FROM returns_unified WHERE 1=1"
        else:
            query_str = """
            SELECT * FROM (
                SELECT 'sales'::text AS source, sr.id AS return_id,
                       sr.return_number, sr.return_date::timestamp AS return_date,
                       sr.party_id, sr.branch_id, sr.warehouse_id,
                       sr.invoice_id AS original_doc_id,
                       COALESCE(sr.refund_amount, sr.total, 0)::numeric(18,4) AS refund_amount,
                       sr.refund_method, sr.status, sr.notes,
                       sr.created_at, sr.created_by
                FROM sales_returns sr
                UNION ALL
                SELECT 'pos'::text, pr.id, ('POS-RET-'||pr.id::text),
                       pr.created_at, NULL::int, NULL::int, NULL::int,
                       pr.original_order_id,
                       COALESCE(pr.refund_amount,0)::numeric(18,4),
                       pr.refund_method, 'completed'::text, pr.notes,
                       pr.created_at, pr.created_by
                FROM pos_returns pr
            ) u WHERE 1=1
            """
        params: dict = {}
        query_str += branch_scope_filter_from_scope(branch_scope, "branch_id", params)
        if source:
            query_str += " AND source = :source"
            params["source"] = source
        query_str += " ORDER BY return_date DESC NULLS LAST LIMIT :limit"
        params["limit"] = limit

        rows = db.execute(text(query_str), params).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


@returns_router.get("/returns/{return_id}", response_model=dict, dependencies=[Depends(require_permission("sales.view"))])
def get_sales_return(request: Request, return_id: int, current_user: dict = Depends(get_current_user)):
    """جلب تفاصيل مرتجع مبيعات"""
    db = get_db_connection(_company_id(current_user))
    try:
        header = db.execute(text("""
            SELECT r.*, p.name as customer_name, i.invoice_number
            FROM sales_returns r
            JOIN parties p ON r.party_id = p.id
            LEFT JOIN invoices i ON r.invoice_id = i.id
            WHERE r.id = :id
        """), {"id": return_id}).fetchone()

        if not header:
            raise HTTPException(**http_error(404, "return_not_found", request))

        # Enforce branch access for single resource
        if header.branch_id:
            validate_branch_access(current_user, header.branch_id)

        lines = db.execute(text("""
            SELECT l.*, p.product_name
            FROM sales_return_lines l
            LEFT JOIN products p ON l.product_id = p.id
            WHERE l.return_id = :id
        """), {"id": return_id}).fetchall()

        return {
            **dict(header._mapping),
            "items": [dict(row._mapping) for row in lines]
        }
    finally:
        db.close()


@returns_router.post("/returns", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def create_sales_return(
    request: Request,
    data: SalesReturnCreate,
    # Fix 10: Idempotency-Key prevents duplicate returns on double-submit or network retry.
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key", max_length=64),
    current_user: dict = Depends(get_current_user),
):
    """إنشاء مرتجع مبيعات جديد (مسودة)"""
    db = get_db_connection(_company_id(current_user))
    try:
        # Fix 10: Idempotency check — return existing return if key already used
        if idempotency_key:
            existing = db.execute(text("""
                SELECT id, return_number FROM sales_returns
                WHERE idempotency_key = :key LIMIT 1
            """), {"key": idempotency_key}).fetchone()
            if existing:
                return {"return_id": existing.id, "return_number": existing.return_number, "idempotent_replay": True}

        # Generate Sequential Return Number
        from utils.accounting import generate_sequential_number
        ret_num = generate_sequential_number(db, f"RET-{datetime.now().year}", "sales_returns", "return_number")

        original_invoice = None
        original_lines = {}
        already_reversed_qty = {}
        original_tax_factor = Decimal("1")
        if data.invoice_id:
            original_invoice, original_lines, already_reversed_qty, original_tax_factor = _load_original_sales_invoice_for_return(
                db, data.invoice_id, data.customer_id
            )
        return_warehouse_id = data.warehouse_id
        if original_invoice:
            original_warehouse_id = db.execute(text("""
                SELECT warehouse_id
                FROM inventory_transactions
                WHERE reference_id = :invoice_id
                  AND reference_type IN ('sales_invoice', 'invoice')
                  AND warehouse_id IS NOT NULL
                ORDER BY id ASC
                LIMIT 1
            """), {"invoice_id": data.invoice_id}).scalar()
            if return_warehouse_id and original_warehouse_id and int(return_warehouse_id) != int(original_warehouse_id):
                raise HTTPException(**http_error(400, "return_warehouse_mismatch_invoice", request))
            if not return_warehouse_id:
                return_warehouse_id = original_warehouse_id

        # Determine Branch
        branch_id = data.branch_id
        if original_invoice:
            if branch_id and original_invoice.branch_id is not None and int(branch_id) != int(original_invoice.branch_id):
                raise HTTPException(**http_error(400, "return_branch_mismatch_invoice", request))
            branch_id = original_invoice.branch_id
        branch_id = validate_branch_access(current_user, branch_id) if branch_id else None
        selected_treasury_id = data.bank_account_id
        selected_treasury = None
        if selected_treasury_id:
            selected_treasury = validate_treasury_account_access(db, current_user, selected_treasury_id, branch_id)
            if branch_id is None and selected_treasury.get("branch_id") is not None:
                branch_id = int(selected_treasury["branch_id"])
        branch_id = validate_branch_access(current_user, branch_id)

        # T10.1 P1 #110e — enforce return window. Reads
        # ``return_window_days`` from company_settings; default 30 days.
        # Set to 0 (or empty) to disable the check. Returns linked to a
        # specific invoice are validated against that invoice's date.
        if data.invoice_id:
            try:
                window_row = db.execute(text(
                    "SELECT setting_value FROM company_settings WHERE setting_key = 'return_window_days'"
                )).scalar()
                window_days = int(window_row) if window_row not in (None, "", "0") else None
            except (ValueError, TypeError):
                window_days = 30
            if window_days and window_days > 0:
                inv_row = db.execute(text(
                    "SELECT invoice_date FROM invoices WHERE id = :id"
                ), {"id": data.invoice_id}).fetchone()
                if inv_row and inv_row.invoice_date:
                    age_days = (data.return_date - inv_row.invoice_date).days
                    user_permissions = current_user.get("permissions", []) if isinstance(current_user, dict) else (getattr(current_user, "permissions", []) or [])
                    if age_days > window_days and not check_permission(user_permissions, "sales.return_outside_window"):
                        raise HTTPException(
                            status_code=400,
                            detail=(
                                f"تجاوزت نافذة الإرجاع المسموحة ({window_days} يوم) — "
                                f"عمر الفاتورة {age_days} يوم"
                            ),
                        )

        # FIN-FIX: Fiscal period lock on returns (was missing — could post to closed periods)
        from utils.fiscal_lock import check_fiscal_period_open
        check_fiscal_period_open(db, data.return_date)

        # UOM Validation: Discrete units must have integer quantities
        from utils.quantity_validation import validate_quantity_for_product
        for item in data.items:
            validate_quantity_for_product(db, item.product_id, item.quantity)

        # FIN-FIX: Calculate totals using Decimal for precision (was using float)
        subtotal = Decimal('0')
        total_tax = Decimal('0')
        lines_to_save = []

        for item in data.items:
            line_total = (_dec(item.quantity) * _dec(item.unit_price)).quantize(_D2, ROUND_HALF_UP)
            tax_rate_id = None
            applied_taxes = None
            if original_invoice:
                original_line = _original_line_for_return(original_lines, item.product_id, item.unit_price)
                reverse_key = _line_key(original_line.product_id, original_line.unit_price, original_line.tax_rate)
                already_qty = already_reversed_qty.get(reverse_key, Decimal("0"))
                available_qty = _dec(original_line.quantity) - already_qty
                if _dec(item.quantity) > available_qty:
                    raise HTTPException(**http_error(400, "return_qty_exceeds_invoice", request))
                effective_tax_rate = _dec(original_line.tax_rate)
                tax_rate_id = original_line.tax_rate_id
                applied_taxes = original_line.applied_taxes
                line_total = _reversal_taxable_amount(original_line, item.quantity)
                already_reversed_qty[reverse_key] = already_qty + _dec(item.quantity)
            elif item.product_id and branch_id:
                tax_info = resolve_line_tax(branch_id, item.product_id, db, data.return_date, customer_id=data.customer_id)
                effective_tax_rate = tax_info["tax_rate"]
                tax_rate_id = tax_info.get("tax_rate_id")
            else:
                effective_tax_rate = _dec(item.tax_rate or 0)
            tax_factor = original_tax_factor if original_invoice else Decimal("1")
            line_tax = (line_total * effective_tax_rate / Decimal('100') * tax_factor).quantize(_D2, ROUND_HALF_UP)
            final_total = line_total + line_tax

            subtotal += line_total
            total_tax += line_tax

            lines_to_save.append({
                **item.model_dump(),
                "tax_rate": effective_tax_rate,
                "tax_rate_id": tax_rate_id,
                "applied_taxes": applied_taxes,
                "total": final_total
            })

        grand_total = subtotal + total_tax

        # Validate effective exchange-rate record for foreign currency returns.
        base_currency_row = db.execute(text("SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1")).fetchone()
        if not base_currency_row:
            base_currency_row = db.execute(text("SELECT setting_value as code FROM company_settings WHERE setting_key = 'default_currency'")) .fetchone()
        base_currency = base_currency_row[0] if base_currency_row else "SYP"

        ret_currency = data.currency or base_currency
        ret_rate = _dec(data.exchange_rate or 1)
        if ret_currency != base_currency:
            if ret_rate <= 0:
                raise HTTPException(**http_error(400, "exchange_rate_must_be_positive", request))
            latest_rate_row = db.execute(text("""
                SELECT rate_date
                FROM exchange_rates
                WHERE currency_id = (SELECT id FROM currencies WHERE code = :code)
                  AND rate_date <= :date
                ORDER BY rate_date DESC
                LIMIT 1
            """), {"code": ret_currency, "date": data.return_date}).fetchone()
            if not latest_rate_row:
                raise HTTPException(status_code=400, detail=i18n_message("no_exchange_rate_for_currency", request))
            age_days = (data.return_date - latest_rate_row.rate_date).days if latest_rate_row.rate_date else 0
            if age_days > _MAX_RATE_AGE_DAYS:
                raise HTTPException(status_code=400, detail=i18n_message("exchange_rate_expired", request))

        # Save Header
        res = db.execute(text("""
            INSERT INTO sales_returns (
                return_number, party_id, invoice_id, return_date,
                subtotal, tax_amount, total, status, notes, created_by,
                refund_method, refund_amount, bank_account_id, treasury_account_id, check_number, check_date, branch_id, warehouse_id,
                currency, exchange_rate, idempotency_key
            ) VALUES (
                :num, :cust, :inv, :rdate,
                :sub, :tax, :total, 'draft', :notes, :user,
                :rmethod, :ramount, :rbank, :treasury, :rcheck, :rcheckdate, :bid, :wh_id,
                :currency, :exchange_rate, :idem_key
            ) RETURNING id
        """), {
            "num": ret_num, "cust": data.customer_id, "inv": data.invoice_id,
            "rdate": data.return_date, "sub": subtotal, "tax": total_tax,
            "total": grand_total, "notes": data.notes, "user": _user_id(current_user),
            "rmethod": data.refund_method, "ramount": data.refund_amount,
            "rbank": data.bank_account_id, "treasury": selected_treasury_id,
            "rcheck": data.check_number,
            "rcheckdate": data.check_date, "bid": branch_id, "wh_id": return_warehouse_id,
            "currency": ret_currency, "exchange_rate": ret_rate,
            "idem_key": idempotency_key,
        }).fetchone()

        ret_id = res[0]

        # Update party_site_id if provided
        if hasattr(data, 'party_site_id') and data.party_site_id:
            db.execute(text("UPDATE sales_returns SET party_site_id = :sid WHERE id = :rid"),
                      {"sid": data.party_site_id, "rid": ret_id})

        # Save Lines \u2014 T10.2 #181: switched from per-row INSERT loop
        # to a single ``executemany`` call. This collapses N round-trips
        # into one and reduces both wire overhead and lock contention.
        if lines_to_save:
            db.execute(
                text("""
                    INSERT INTO sales_return_lines (
                        return_id, product_id, description, quantity, unit_price,
                        tax_rate, tax_rate_id, applied_taxes, total, reason
                    ) VALUES (
                        :ret_id, :pid, :desc, :qty, :price,
                        :tax_rate, :tax_rate_id, CAST(:applied_taxes AS jsonb), :total, :reason
                    )
                """),
                [
                    {
                        "ret_id": ret_id,
                        "pid": line["product_id"],
                        "desc": line["description"],
                        "qty": line["quantity"],
                        "price": line["unit_price"],
                        "tax_rate": line["tax_rate"],
                        "tax_rate_id": line["tax_rate_id"],
                        "applied_taxes": _json_param(line["applied_taxes"]),
                        "total": line["total"],
                        "reason": line["reason"],
                    }
                    for line in lines_to_save
                ],
            )

        db.commit()

        cust_name = db.execute(text("SELECT name FROM parties WHERE id = :id"), {"id": data.customer_id}).scalar()
        # AUDIT LOG
        log_activity(
            db,
            user_id=_user_id(current_user),
            username=_username(current_user),
            action="sales.return.create",
            resource_type="sales_return",
            resource_id=str(ret_id),
            details={"return_number": ret_num, "total": grand_total, "customer_id": data.customer_id, "customer_name": cust_name},
            request=request,
            branch_id=branch_id
        )
        return {"id": ret_id, "return_number": ret_num}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@returns_router.post("/returns/{return_id}/approve", dependencies=[Depends(require_sensitive_permission("sales.approve_return"))], response_model=Dict[str, Any])
def approve_sales_return(return_id: int, request: Request, current_user: dict = Depends(get_current_user)):
    """اعتماد مرتجع المبيعات (تحديث المخزون وقيد محاسبي)"""
    db = get_db_connection(_company_id(current_user))
    try:
        # Get base currency
        base_currency_row = db.execute(text("SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1")).fetchone()
        if not base_currency_row:
            base_currency_row = db.execute(text("SELECT setting_value as code FROM company_settings WHERE setting_key = 'default_currency'")).fetchone()
        base_currency = base_currency_row[0] if base_currency_row else "SYP"

        # 1. Fetch Return details
        header = db.execute(text("SELECT * FROM sales_returns WHERE id = :id FOR UPDATE"), {"id": return_id}).fetchone()
        if not header or header.status != 'draft':
            raise HTTPException(**http_error(400, "return_not_found_or_already_approved", request))
        branch_id = validate_branch_access(current_user, header.branch_id)
        selected_treasury_id = header.treasury_account_id or header.bank_account_id
        selected_treasury = None
        if selected_treasury_id:
            selected_treasury = validate_treasury_account_access(db, current_user, selected_treasury_id, branch_id)

        lines = db.execute(text("SELECT * FROM sales_return_lines WHERE return_id = :id"), {"id": return_id}).fetchall()

        # 2. Update Stock
        # Determine warehouse: Use returned warehouse (header.warehouse_id) OR original invoice's warehouse if possible
        wh_id = header.warehouse_id

        if not wh_id and header.invoice_id:
            # Try to fetch warehouse from original invoice transactions
            orig_wh = db.execute(text("""
                SELECT warehouse_id FROM inventory_transactions 
                WHERE reference_id = :id AND reference_type IN ('sales_invoice', 'invoice')
                LIMIT 1
            """), {"id": header.invoice_id}).scalar()
            if orig_wh:
                wh_id = orig_wh

        if not wh_id:
            # Fallback to default warehouse
            wh_id = db.execute(text("SELECT id FROM warehouses WHERE is_default = TRUE")).scalar() or 1

        total_cost_reversal = Decimal('0')
        for line in lines:
            if line.product_id:
                # Calculate cost to reverse from COGS FIRST (before logging transaction)
                cost_price = Decimal('0')
                if header.invoice_id:
                    historical_cost = db.execute(text("""
                        SELECT unit_cost FROM inventory_transactions 
                        WHERE product_id = :pid 
                          AND reference_id = :inv_id 
                          AND reference_type IN ('sales_invoice', 'invoice')
                          AND quantity < 0 
                        LIMIT 1
                    """), {"pid": line.product_id, "inv_id": header.invoice_id}).scalar()

                    if historical_cost is not None:
                        cost_price = _dec(historical_cost)

                # Fallback to current product cost if historical not found
                if cost_price == 0:
                    cost_price = db.execute(text("SELECT cost_price FROM products WHERE id = :id"), {"id": line.product_id}).scalar() or 0
                    cost_price = _dec(cost_price)

                from services.costing_service import CostingService
                costing_method = CostingService._get_product_costing_method(db, line.product_id, wh_id)
                if costing_method in ("fifo", "lifo"):
                    try:
                        return_result = CostingService.handle_return(
                            db,
                            product_id=line.product_id,
                            warehouse_id=wh_id,
                            quantity=line.quantity,
                            unit_cost=cost_price,
                            source_document_type="sales_return",
                            source_document_id=return_id,
                            costing_method=costing_method,
                            original_source_document_type="sales_invoice" if header.invoice_id else None,
                            original_source_document_id=header.invoice_id,
                        )
                    except ValueError as exc:
                        raise HTTPException(status_code=400, detail=str(exc))
                    restored_cost = _dec(return_result.get("restored_unit_cost", cost_price))
                    restored_total = _dec(return_result.get("restored_total_cost", cost_price * _dec(line.quantity)))
                else:
                    restored_cost = cost_price
                    restored_total = (cost_price * _dec(line.quantity)).quantize(_D4, ROUND_HALF_UP)
                    CostingService.update_cost(
                        db,
                        product_id=line.product_id,
                        warehouse_id=wh_id,
                        new_qty=_dec(line.quantity),
                        new_price=restored_cost,
                    )

                # Update Inventory
                db.execute(text("""
                    INSERT INTO inventory (product_id, warehouse_id, quantity, average_cost, updated_at)
                    VALUES (:pid, :wh, :qty, :cost, NOW())
                    ON CONFLICT (product_id, warehouse_id)
                    DO UPDATE SET quantity = inventory.quantity + EXCLUDED.quantity,
                                  updated_at = NOW()
                """), {
                    "qty": line.quantity,
                    "pid": line.product_id,
                    "wh": wh_id,
                    "cost": restored_cost,
                })

                # Log Inventory Transaction
                db.execute(text("""
                    INSERT INTO inventory_transactions (
                        product_id, warehouse_id, transaction_type, 
                        reference_type, reference_id, reference_document,
                        quantity, unit_cost, total_cost, created_by
                    ) VALUES (
                        :pid, :wh, 'sales_return', 'sales_return', :ret_id, :doc_num,
                        :qty, :cost, :total_cost, :user
                    )
                """), {
                    "pid": line.product_id,
                    "wh": wh_id,
                    "ret_id": return_id,
                    "doc_num": header.return_number,
                    "qty": line.quantity,
                    "cost": restored_cost,
                    "total_cost": restored_total.quantize(_D2, ROUND_HALF_UP),
                    "user": _user_id(current_user)
                })

                total_cost_reversal += restored_total.quantize(_D2, ROUND_HALF_UP)

        # 3. Update Status
        updated = db.execute(text("""
            UPDATE sales_returns
            SET status = 'approved'
            WHERE id = :id AND status = 'draft'
            RETURNING id
        """), {"id": return_id}).fetchone()
        if not updated:
            raise HTTPException(**http_error(400, "return_not_found_or_already_approved", request))

        exchange_rate = _dec(header.exchange_rate or 1)
        if header.currency and header.currency != base_currency:
            rate_row = db.execute(text("""
                SELECT rate_date
                FROM exchange_rates
                WHERE currency_id = (SELECT id FROM currencies WHERE code = :code)
                  AND rate_date <= :date
                ORDER BY rate_date DESC
                LIMIT 1
            """), {"code": header.currency, "date": header.return_date}).fetchone()
            if not rate_row:
                raise HTTPException(status_code=400, detail=i18n_message("no_exchange_rate_for_currency", request))
            age_days = (header.return_date - rate_row.rate_date).days if rate_row.rate_date else 0
            if age_days > _MAX_RATE_AGE_DAYS:
                raise HTTPException(status_code=400, detail=i18n_message("exchange_rate_expired", request))

        def to_base(amount):
            return (_dec(amount) * exchange_rate).quantize(_D2, ROUND_HALF_UP)

        # 4. Update Customer Balance via party_site_balances (Reduction)
        # AUDIT-H1: balance must be expressed in the *document* currency,
        # because party_site_balances is keyed by `(party_site, currency)`
        # and storing a base-currency amount under a foreign-currency key
        # would double-apply the exchange rate (e.g. a USD-100 return
        # would reduce the USD balance by 375 SAR-equivalent units).
        # `gl_total` (in base currency) stays in the GL block below.
        gl_total = to_base(header.total)
        update_party_site_balance(db, party_id=header.party_id, branch_id=header.branch_id,
                                  currency=header.currency or base_currency,
                                  amount=-_dec(header.total))

        # Returns reduce receivables through their own GL/audit trail; they
        # are not cash collections, so the source invoice paid_amount is left
        # untouched for aging and payment-history reporting.

        # 5. GL Entry (Automated using Dynamic Mappings)
        acc_sales = get_mapped_account_id(db, "acc_map_sales_rev")
        acc_vat_out = get_mapped_account_id(db, "acc_map_vat_out")
        acc_ar = get_mapped_account_id(db, "acc_map_ar")
        acc_cash = get_mapped_account_id(db, "acc_map_cash_main")
        acc_bank = get_mapped_account_id(db, "acc_map_bank")
        acc_cogs = get_mapped_account_id(db, "acc_map_cogs")
        # F-31: returned goods come back into the receiving warehouse —
        # debit its mapped inventory account.
        from utils.inventory_accounts import resolve_warehouse_inventory_account
        acc_inventory = resolve_warehouse_inventory_account(db, wh_id)

        je_lines = []
        gl_subtotal = to_base(header.subtotal)
        gl_tax = to_base(header.tax_amount)

        # Debit: Sales Return (Revenue reduction)
        je_lines.append({"account_id": acc_sales, "debit": gl_subtotal, "credit": 0, "description": f"Sales Return - {header.return_number} ({header.currency})"})
        # Debit: VAT Output (Tax reduction)
        if gl_tax > 0:
            je_lines.append({"account_id": acc_vat_out, "debit": gl_tax, "credit": 0, "description": f"VAT Reduction - {header.return_number}"})
        # Credit: Accounts Receivable (Customer reduction)
        je_lines.append({"account_id": acc_ar, "debit": 0, "credit": gl_total, "description": f"AR Reduction - {header.return_number}"})

        # 6. Refund Processing (Payment Voucher + GL)
        if header.refund_method and header.refund_method != 'credit' and header.refund_amount > 0:
            from utils.accounting import generate_sequential_number
            voucher_num = generate_sequential_number(db, f"REF-{datetime.now().year}", "payment_vouchers", "voucher_number")

            # A. Create Payment Voucher
            voucher_id = db.execute(text("""
                INSERT INTO payment_vouchers (
                    voucher_number, voucher_type, voucher_date, party_type, party_id,
                    amount, payment_method, bank_account_id, treasury_account_id, check_number, check_date,
                    reference, status, created_by, branch_id
                ) VALUES (
                    :vnum, 'payment', :vdate, 'customer', :cust,
                    :amt, :method, :bank, :treasury, :check_num, :check_date,
                    :ref, 'posted', :user, :branch_id
                ) RETURNING id
            """), {
                "vnum": voucher_num, "vdate": header.return_date, "cust": header.party_id,
                "amt": header.refund_amount, "method": header.refund_method,
                "bank": header.bank_account_id, "treasury": selected_treasury_id,
                "check_num": header.check_number,
                "check_date": header.check_date,
                "ref": f"Refund for {header.return_number}", "user": _user_id(current_user),
                "branch_id": branch_id,
            }).scalar()

            # C. Update Customer Balance via party_site_balances
            # AUDIT-H1: same currency rule as #4 above — increment AR
            # by the document-currency amount, not the base-currency
            # gl_refund.
            gl_refund = to_base(header.refund_amount)
            update_party_site_balance(db, party_id=header.party_id, branch_id=header.branch_id,
                                      currency=header.currency or base_currency,
                                      amount=_dec(header.refund_amount))

            # GL for Refund
            acc_cash = get_mapped_account_id(db, "acc_map_cash_main")
            acc_bank = get_mapped_account_id(db, "acc_map_bank")

            selected_gl_id = selected_treasury.get("gl_account_id") if selected_treasury else None
            credit_acc = selected_gl_id or (acc_bank if header.refund_method == 'bank' else acc_cash)

            if credit_acc:
                # Credit Cash/Bank
                je_lines.append({"account_id": credit_acc, "debit": 0, "credit": gl_refund, "description": f"Refund Paid - {header.return_number} ({header.currency})"})
                # Debit AR
                je_lines.append({"account_id": acc_ar, "debit": gl_refund, "credit": 0, "description": f"AR Offset (Refund) - {header.return_number}"})

        # Inventory Reversal
        if total_cost_reversal > 0:
            je_lines.append({"account_id": acc_inventory, "debit": total_cost_reversal, "credit": 0, "description": f"Inv Increase - {header.return_number}"})
            je_lines.append({"account_id": acc_cogs, "debit": 0, "credit": total_cost_reversal, "description": f"COGS Reduction - {header.return_number}"})

        # Insert Journal Entry (TASK-015: centralized)
        from utils.accounting import prepare_je_lines
        valid_lines = prepare_je_lines(je_lines, source=f"RET-{header.return_number}")

        # Enrich with amount_currency/currency for gl_service
        for line in valid_lines:
            amt_curr = (
                ((_dec(line["debit"]) + _dec(line["credit"])) / exchange_rate).quantize(_D2, ROUND_HALF_UP)
                if exchange_rate else Decimal('0')
            )
            line["amount_currency"] = amt_curr
            line["currency"] = header.currency

        # Fiscal-period lock: block posting into a closed period.
        check_fiscal_period_open(db, str(header.return_date))

        je_id, je_num = create_journal_entry(
            db=db,
            company_id=_company_id(current_user),
            date=str(header.return_date),
            description=f"Sales Return {header.return_number} ({header.currency})",
            lines=valid_lines,
            user_id=_user_id(current_user),
            branch_id=header.branch_id,
            reference=header.return_number,
            status="posted",
            currency=header.currency,
            exchange_rate=1.0,  # amounts already in base currency
            source="SalesReturn",
            source_id=return_id,
            username=_username(current_user),
            idempotency_key=f"ret-{header.return_number}",
        )

        if selected_treasury_id:
            from utils.treasury_balance import recalc_treasury_from_gl
            recalc_treasury_from_gl(db, selected_treasury_id)

        db.commit()

        log_activity(
            db,
            user_id=_user_id(current_user),
            username=_username(current_user),
            action="sales.return.approve",
            resource_type="sales_return",
            resource_id=str(return_id),
            details={"return_number": header.return_number, "total": str(header.total or 0), "info": "Return Approved"},
            request=request,
            branch_id=header.branch_id
        )

        return {"status": "approved", "message": i18n_message("return_approved", request)}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error approving return: {str(e)}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@returns_router.post("/returns/{return_id}/cancel", dependencies=[Depends(require_sensitive_permission("sales.approve_return"))], response_model=Dict[str, Any])
def cancel_sales_return(return_id: int, request: Request, current_user: dict = Depends(get_current_user)):
    """Cancel a sales return. Drafts are voided; approved returns are fully reversed."""
    db = get_db_connection(_company_id(current_user))
    try:
        header = db.execute(text("""
            SELECT *
            FROM sales_returns
            WHERE id = :id
            FOR UPDATE
        """), {"id": return_id}).fetchone()
        if not header:
            raise HTTPException(**http_error(404, "return_not_found", request))
        if header.branch_id:
            validate_branch_access(current_user, header.branch_id)
        if header.status == "cancelled":
            raise HTTPException(**http_error(400, "sales_return_already_cancelled", request))

        if header.status == "draft":
            db.execute(text("""
                UPDATE sales_returns
                SET status = 'cancelled',
                    updated_at = NOW()
                WHERE id = :id AND status = 'draft'
            """), {"id": return_id})
        elif header.status == "approved":
            reversal_date = datetime.now().date()
            check_fiscal_period_open(db, reversal_date, request=request)

            je = db.execute(text("""
                SELECT id
                FROM journal_entries
                WHERE source = 'SalesReturn'
                  AND source_id = :return_id
                  AND status = 'posted'
                ORDER BY id DESC
                LIMIT 1
            """), {"return_id": return_id}).fetchone()
            if not je:
                raise HTTPException(**http_error(400, "sales_return_no_je_to_reverse", request))

            wh_id = header.warehouse_id or db.execute(text("""
                SELECT warehouse_id
                FROM inventory_transactions
                WHERE reference_type = 'sales_return'
                  AND reference_id = :return_id
                  AND warehouse_id IS NOT NULL
                ORDER BY id ASC
                LIMIT 1
            """), {"return_id": return_id}).scalar()
            if not wh_id:
                raise HTTPException(**http_error(400, "sales_return_cancel_warehouse_missing", request))

            lines = db.execute(text("""
                SELECT *
                FROM sales_return_lines
                WHERE return_id = :return_id
            """), {"return_id": return_id}).fetchall()

            from services.costing_service import CostingService
            for line in lines:
                if not line.product_id:
                    continue
                qty = _dec(line.quantity)
                tx = db.execute(text("""
                    SELECT unit_cost, total_cost
                    FROM inventory_transactions
                    WHERE reference_type = 'sales_return'
                      AND reference_id = :return_id
                      AND product_id = :product_id
                    ORDER BY id ASC
                    LIMIT 1
                    FOR UPDATE
                """), {"return_id": return_id, "product_id": line.product_id}).fetchone()
                unit_cost = _dec(tx.unit_cost) if tx and tx.unit_cost is not None else _dec(line.unit_price)
                costing_method = CostingService._get_product_costing_method(db, line.product_id, wh_id)
                if costing_method in ("fifo", "lifo"):
                    try:
                        CostingService.consume_layers(
                            db,
                            product_id=line.product_id,
                            warehouse_id=wh_id,
                            quantity=qty,
                            sale_document_type="sales_return_cancel",
                            sale_document_id=return_id,
                            costing_method=costing_method,
                        )
                    except ValueError as exc:
                        raise HTTPException(status_code=400, detail=str(exc))
                else:
                    CostingService.update_cost(
                        db,
                        product_id=line.product_id,
                        warehouse_id=wh_id,
                        new_qty=-qty,
                        new_price=unit_cost,
                    )

                stock_update = db.execute(text("""
                    UPDATE inventory
                    SET quantity = quantity - :qty,
                        updated_at = NOW()
                    WHERE product_id = :product_id
                      AND warehouse_id = :warehouse_id
                      AND quantity - COALESCE(reserved_quantity, 0) >= :qty
                    RETURNING id
                """), {
                    "qty": qty,
                    "product_id": line.product_id,
                    "warehouse_id": wh_id,
                }).fetchone()
                if not stock_update:
                    raise HTTPException(**http_error(400, "insufficient_stock_for_sales_return_cancel", request))

                total_cost = (unit_cost * qty).quantize(_D2, ROUND_HALF_UP)
                db.execute(text("""
                    INSERT INTO inventory_transactions (
                        product_id, warehouse_id, transaction_type,
                        reference_type, reference_id, reference_document,
                        quantity, unit_cost, total_cost, notes, created_by
                    ) VALUES (
                        :product_id, :warehouse_id, 'sales_return_cancel',
                        'sales_return_cancel', :return_id, :return_number,
                        :qty, :unit_cost, :total_cost, :notes, :user_id
                    )
                """), {
                    "product_id": line.product_id,
                    "warehouse_id": wh_id,
                    "return_id": return_id,
                    "return_number": header.return_number,
                    "qty": -qty,
                    "unit_cost": unit_cost,
                    "total_cost": total_cost,
                    "notes": "Cancel approved sales return",
                    "user_id": _user_id(current_user),
                })

            exchange_rate = _dec(header.exchange_rate or 1)
            gl_total = (_dec(header.total) * exchange_rate).quantize(_D2, ROUND_HALF_UP)
            # AUDIT-H1: cancel of an approved return restores AR — use
            # the document-currency amount to undo what the original
            # approve flow recorded under the same (party_site, currency)
            # key.
            update_party_site_balance(
                db,
                party_id=header.party_id,
                branch_id=header.branch_id,
                currency=header.currency or (db.execute(text("SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1")).scalar() or "SAR"),
                amount=_dec(header.total),
            )

            from services.gl_service import reverse_journal_entry
            reverse_journal_entry(
                db,
                je_id=je.id,
                user_id=_user_id(current_user),
                company_id=_company_id(current_user),
                reversal_date=str(reversal_date),
                reason=f"Cancel sales return {header.return_number}",
                request=request,
            )

            refund_vouchers = db.execute(text("""
                SELECT id, treasury_account_id, amount
                FROM payment_vouchers
                WHERE voucher_type = 'payment'
                  AND party_type = 'customer'
                  AND party_id = :party_id
                  AND reference = :reference
                  AND status = 'posted'
                FOR UPDATE
            """), {
                "party_id": header.party_id,
                "reference": f"Refund for {header.return_number}",
            }).fetchall()
            treasury_ids = {row.treasury_account_id for row in refund_vouchers if row.treasury_account_id}
            refund_reversal_total = Decimal("0")
            refund_reversal_total_fc = Decimal("0")
            for row in refund_vouchers:
                row_amount_fc = _dec(row.amount)
                refund_reversal_total += (row_amount_fc * exchange_rate).quantize(_D2, ROUND_HALF_UP)
                refund_reversal_total_fc += row_amount_fc
                db.execute(text("UPDATE payment_vouchers SET status = 'void' WHERE id = :id"), {"id": row.id})
            if refund_reversal_total > _D2:
                # AUDIT-H1: keep the FC sum on the (party_site, currency)
                # ledger; the BC equivalent is only used for treasury /
                # GL reconciliation below.
                update_party_site_balance(
                    db,
                    party_id=header.party_id,
                    branch_id=header.branch_id,
                    currency=header.currency or (db.execute(text("SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1")).scalar() or "SAR"),
                    amount=-refund_reversal_total_fc,
                )

            db.execute(text("""
                UPDATE sales_returns
                SET status = 'cancelled',
                    updated_at = NOW()
                WHERE id = :id AND status = 'approved'
            """), {"id": return_id})

            if treasury_ids:
                from utils.treasury_balance import recalc_treasury_from_gl
                for treasury_id in treasury_ids:
                    recalc_treasury_from_gl(db, treasury_id)
        else:
            raise HTTPException(**http_error(400, "sales_return_cannot_cancel_status", request))

        log_activity(
            db,
            user_id=_user_id(current_user),
            username=_username(current_user),
            action="sales.return.cancel",
            resource_type="sales_return",
            resource_id=str(return_id),
            details={"return_number": header.return_number},
            request=request,
            branch_id=header.branch_id,
        )
        db.commit()
        return {"success": True, "message": i18n_message("sales_return_cancelled", request)}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
