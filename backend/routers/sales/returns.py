"""Sales returns endpoints."""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.audit import log_activity
from utils.permissions import branch_scope_filter_from_scope, require_permission, require_sensitive_permission, resolve_branch_scope, validate_branch_access, validate_treasury_account_access
from utils.accounting import get_mapped_account_id
from services.gl_service import create_journal_entry  # TASK-015: centralized GL posting
from services.tax_engine import resolve_line_tax
from utils.fiscal_lock import check_fiscal_period_open
from utils.party_balance import update_party_site_balance
from .schemas import SalesReturnCreate

returns_router = APIRouter()
logger = logging.getLogger(__name__)
_D2 = Decimal('0.01')
_MAX_RATE_AGE_DAYS = 31
_TABLE_COLUMNS_CACHE: dict[tuple[str, str], frozenset[str]] = {}


def _dec(v) -> Decimal:
    return Decimal(str(v or 0))


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


@returns_router.get("/returns", response_model=List[dict], dependencies=[Depends(require_permission("sales.view"))])
def list_sales_returns(branch_id: Optional[int] = None, current_user: dict = Depends(get_current_user)):
    """عرض قائمة مرتجعات المبيعات"""
    branch_scope = resolve_branch_scope(current_user, branch_id)

    db = get_db_connection(current_user.company_id)
    try:
        query_str = """
            SELECT r.*, p.name as customer_name 
            FROM sales_returns r
            JOIN parties p ON r.party_id = p.id
            WHERE 1=1
        """
        params = {}
        query_str += branch_scope_filter_from_scope(branch_scope, "r.branch_id", params)

        query_str += " ORDER BY r.created_at DESC"

        result = db.execute(text(query_str), params).fetchall()
        return [dict(row._mapping) for row in result]
    finally:
        db.close()


@returns_router.get(
    "/returns/unified",
    response_model=List[dict],
    dependencies=[Depends(require_permission("sales.view"))],
)
def list_unified_returns(
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
        raise HTTPException(status_code=400, detail="source must be 'sales' or 'pos'")
    limit = max(1, min(int(limit or 200), 1000))

    db = get_db_connection(current_user.company_id)
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
def get_sales_return(return_id: int, current_user: dict = Depends(get_current_user)):
    """جلب تفاصيل مرتجع مبيعات"""
    db = get_db_connection(current_user.company_id)
    try:
        header = db.execute(text("""
            SELECT r.*, p.name as customer_name, i.invoice_number
            FROM sales_returns r
            JOIN parties p ON r.party_id = p.id
            LEFT JOIN invoices i ON r.invoice_id = i.id
            WHERE r.id = :id
        """), {"id": return_id}).fetchone()

        if not header:
            raise HTTPException(status_code=404, detail="المرتجع غير موجود")

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
def create_sales_return(request: Request, data: SalesReturnCreate, current_user: dict = Depends(get_current_user)):
    """إنشاء مرتجع مبيعات جديد (مسودة)"""
    db = get_db_connection(current_user.company_id)
    try:
        # Generate Sequential Return Number
        from utils.accounting import generate_sequential_number
        ret_num = generate_sequential_number(db, f"RET-{datetime.now().year}", "sales_returns", "return_number")

        # Determine Branch
        branch_id = data.branch_id
        if not branch_id and data.invoice_id:
            branch_id = db.execute(text("SELECT branch_id FROM invoices WHERE id = :id"), {"id": data.invoice_id}).scalar()
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
                    if age_days > window_days:
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
            if item.product_id and branch_id:
                tax_info = resolve_line_tax(branch_id, item.product_id, db, data.return_date, customer_id=data.customer_id)
                effective_tax_rate = tax_info["tax_rate"]
            else:
                effective_tax_rate = _dec(item.tax_rate or 0)
            line_tax = (line_total * effective_tax_rate / Decimal('100')).quantize(_D2, ROUND_HALF_UP)
            final_total = line_total + line_tax

            subtotal += line_total
            total_tax += line_tax

            lines_to_save.append({
                **item.model_dump(),
                "tax_rate": effective_tax_rate,
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
                raise HTTPException(status_code=400, detail="Exchange rate must be greater than zero")
            latest_rate_row = db.execute(text("""
                SELECT rate_date
                FROM exchange_rates
                WHERE currency_id = (SELECT id FROM currencies WHERE code = :code)
                  AND rate_date <= :date
                ORDER BY rate_date DESC
                LIMIT 1
            """), {"code": ret_currency, "date": data.return_date}).fetchone()
            if not latest_rate_row:
                raise HTTPException(status_code=400, detail=f"No exchange rate found for {ret_currency}")
            age_days = (data.return_date - latest_rate_row.rate_date).days if latest_rate_row.rate_date else 0
            if age_days > _MAX_RATE_AGE_DAYS:
                raise HTTPException(status_code=400, detail=f"Exchange rate for {ret_currency} is expired ({age_days} days old)")

        # Save Header
        res = db.execute(text("""
            INSERT INTO sales_returns (
                return_number, party_id, invoice_id, return_date,
                subtotal, tax_amount, total, status, notes, created_by,
                refund_method, refund_amount, bank_account_id, treasury_account_id, check_number, check_date, branch_id, warehouse_id,
                currency, exchange_rate
            ) VALUES (
                :num, :cust, :inv, :rdate,
                :sub, :tax, :total, 'draft', :notes, :user,
                :rmethod, :ramount, :rbank, :treasury, :rcheck, :rcheckdate, :bid, :wh_id,
                :currency, :exchange_rate
            ) RETURNING id
        """), {
            "num": ret_num, "cust": data.customer_id, "inv": data.invoice_id,
            "rdate": data.return_date, "sub": subtotal, "tax": total_tax,
            "total": grand_total, "notes": data.notes, "user": current_user.id,
            "rmethod": data.refund_method, "ramount": data.refund_amount,
            "rbank": data.bank_account_id, "treasury": selected_treasury_id,
            "rcheck": data.check_number,
            "rcheckdate": data.check_date, "bid": branch_id, "wh_id": data.warehouse_id,
            "currency": ret_currency, "exchange_rate": ret_rate
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
                        return_id, product_id, description, quantity, unit_price, tax_rate, total, reason
                    ) VALUES (
                        :ret_id, :pid, :desc, :qty, :price, :tax_rate, :total, :reason
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
            user_id=current_user.id,
            username=current_user.username,
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
    db = get_db_connection(current_user.company_id)
    try:
        # Get base currency
        base_currency_row = db.execute(text("SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1")).fetchone()
        if not base_currency_row:
            base_currency_row = db.execute(text("SELECT setting_value as code FROM company_settings WHERE setting_key = 'default_currency'")).fetchone()
        base_currency = base_currency_row[0] if base_currency_row else "SYP"

        # 1. Fetch Return details
        header = db.execute(text("SELECT * FROM sales_returns WHERE id = :id"), {"id": return_id}).fetchone()
        if not header or header.status != 'draft':
            raise HTTPException(status_code=400, detail="المرتجع غير موجود أو تم اعتماده مسبقاً")
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
                WHERE reference_id = :id AND reference_type = 'invoice' 
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
                          AND quantity < 0 
                        LIMIT 1
                    """), {"pid": line.product_id, "inv_id": header.invoice_id}).scalar()

                    if historical_cost is not None:
                        cost_price = _dec(historical_cost)

                # Fallback to current product cost if historical not found
                if cost_price == 0:
                    cost_price = db.execute(text("SELECT cost_price FROM products WHERE id = :id"), {"id": line.product_id}).scalar() or 0
                    cost_price = _dec(cost_price)

                # Update Inventory
                db.execute(text("""
                    UPDATE inventory SET quantity = quantity + :qty 
                    WHERE product_id = :pid AND warehouse_id = :wh
                """), {"qty": line.quantity, "pid": line.product_id, "wh": wh_id})

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
                    "cost": cost_price,
                    "total_cost": (cost_price * _dec(line.quantity)).quantize(_D2, ROUND_HALF_UP),
                    "user": current_user.id if not isinstance(current_user, dict) else current_user.get("id")
                })

                total_cost_reversal += (cost_price * _dec(line.quantity)).quantize(_D2, ROUND_HALF_UP)

        # 3. Update Status
        db.execute(text("UPDATE sales_returns SET status = 'approved' WHERE id = :id"), {"id": return_id})

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
                raise HTTPException(status_code=400, detail=f"No exchange rate found for {header.currency}")
            age_days = (header.return_date - rate_row.rate_date).days if rate_row.rate_date else 0
            if age_days > _MAX_RATE_AGE_DAYS:
                raise HTTPException(status_code=400, detail=f"Exchange rate for {header.currency} is expired ({age_days} days old)")

        def to_base(amount):
            return (_dec(amount) * exchange_rate).quantize(_D2, ROUND_HALF_UP)

        # 4. Update Customer Balance via party_site_balances (Reduction)
        gl_total = to_base(header.total)
        update_party_site_balance(db, party_id=header.party_id, branch_id=header.branch_id,
                                  currency=header.currency or base_currency, amount=-float(gl_total))

        # 4.5 Update Original Invoice Status (Treat return as payment/settlement)
        if header.invoice_id:
            db.execute(text("""
                UPDATE invoices 
                SET paid_amount = COALESCE(paid_amount, 0) + :return_val,
                    status = CASE 
                        WHEN (COALESCE(paid_amount, 0) + :return_val) >= total THEN 'paid'
                        WHEN (COALESCE(paid_amount, 0) + :return_val) > 0 THEN 'partial'
                        ELSE status
                    END
                WHERE id = :inv_id
            """), {"return_val": header.total, "inv_id": header.invoice_id})

        # 5. GL Entry (Automated using Dynamic Mappings)
        acc_sales = get_mapped_account_id(db, "acc_map_sales_rev")
        acc_vat_out = get_mapped_account_id(db, "acc_map_vat_out")
        acc_ar = get_mapped_account_id(db, "acc_map_ar")
        acc_cash = get_mapped_account_id(db, "acc_map_cash_main")
        acc_bank = get_mapped_account_id(db, "acc_map_bank")
        acc_cogs = get_mapped_account_id(db, "acc_map_cogs")
        acc_inventory = get_mapped_account_id(db, "acc_map_inventory")

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
                "ref": f"Refund for {header.return_number}", "user": current_user.id,
                "branch_id": branch_id,
            }).scalar()

            # C. Update Customer Balance via party_site_balances
            gl_refund = to_base(header.refund_amount)
            update_party_site_balance(db, party_id=header.party_id, branch_id=header.branch_id,
                                      currency=header.currency or base_currency, amount=float(gl_refund))

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

            # Update Treasury Balance for refund — T1.3a idempotent recompute
            if selected_treasury_id:
                from utils.treasury_balance import recalc_treasury_from_gl
                recalc_treasury_from_gl(db, selected_treasury_id)
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
            company_id=current_user.company_id,
            date=str(header.return_date),
            description=f"Sales Return {header.return_number} ({header.currency})",
            lines=valid_lines,
            user_id=current_user.id,
            branch_id=header.branch_id,
            reference=header.return_number,
            status="posted",
            currency=header.currency,
            exchange_rate=1.0,  # amounts already in base currency
            source="SalesReturn",
            source_id=return_id,
            username=getattr(current_user, "username", None),
            idempotency_key=f"ret-{header.return_number}",
        )

        db.commit()

        log_activity(
            db,
            user_id=current_user.id,
            username=current_user.username,
            action="sales.return.approve",
            resource_type="sales_return",
            resource_id=str(return_id),
            details={"return_number": header.return_number, "total": str(header.total or 0), "info": "Return Approved"},
            request=request,
            branch_id=header.branch_id
        )

        return {"status": "approved", "message": "تم اعتماد المرتجع بنجاح وتحديث المخزون والقيود المحاسبية"}
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
