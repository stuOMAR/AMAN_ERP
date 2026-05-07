"""Customer receipts and payments (vouchers) endpoints."""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import List, Optional
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import logging
from utils.cache import invalidate_company_cache, invalidate_aggregates

from database import get_db_connection
from routers.auth import get_current_user
from utils.audit import log_activity
from utils.permissions import branch_scope_filter_from_scope, require_permission, resolve_branch_scope, validate_branch_access, validate_treasury_account_access
from utils.accounting import get_mapped_account_id
from utils.party_balance import update_party_site_balance
from services.gl_service import create_journal_entry  # TASK-015: centralized GL posting
from .schemas import CustomerReceiptCreate, CustomerPaymentCreate

vouchers_router = APIRouter()
logger = logging.getLogger(__name__)

_D2 = Decimal("0.01")
def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal("0")
# --- Customer Receipts (Payment Vouchers) ---

@vouchers_router.post("/receipts", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("sales.create"))])
def create_customer_receipt(request: Request, data: CustomerReceiptCreate, current_user: dict = Depends(get_current_user)):
    """إنشاء سند قبض من عميل"""
    db = get_db_connection(current_user.company_id)
    try:
        from utils.accounting import generate_sequential_number, get_base_currency
        base_currency = get_base_currency(db)
        branch_id = validate_branch_access(current_user, data.branch_id) if data.branch_id else None
        selected_treasury_id = getattr(data, 'treasury_id', None) or data.bank_account_id
        selected_treasury = None
        if selected_treasury_id:
            selected_treasury = validate_treasury_account_access(db, current_user, selected_treasury_id, branch_id)
            if branch_id is None and selected_treasury.get("branch_id") is not None:
                branch_id = int(selected_treasury["branch_id"])
        branch_id = validate_branch_access(current_user, branch_id)

        voucher_num = generate_sequential_number(db, f"RCV-{datetime.now().year}", "payment_vouchers", "voucher_number")

        # SLS-011: Prevent posting receipts to closed fiscal periods
        from utils.fiscal_lock import check_fiscal_period_open
        check_fiscal_period_open(db, data.voucher_date)

        # Currency & Exchange Rate
        currency = data.currency or base_currency
        exchange_rate = _dec(data.exchange_rate or 1)
        if exchange_rate <= 0:
            raise HTTPException(**http_error(400, "exchange_rate_must_be_positive"))
        amount_base = (_dec(data.amount) * exchange_rate).quantize(_D2, ROUND_HALF_UP)

        # 1. Insert Voucher Header
        result = db.execute(text("""
            INSERT INTO payment_vouchers (
                voucher_number, voucher_type, voucher_date, party_type, party_id,
                amount, payment_method, bank_account_id, treasury_account_id, check_number, check_date,
                reference, notes, status, created_by, branch_id,
                currency, exchange_rate
            ) VALUES (
                :vnum, 'receipt', :vdate, 'customer', :cust,
                :amt, :method, :bank, :treasury, :check_num, :check_date,
                :ref, :notes, 'posted', :user, :bid,
                :curr, :rate
            ) RETURNING id
        """), {
            "vnum": voucher_num, "vdate": data.voucher_date, "cust": data.customer_id,
            "amt": data.amount, "method": data.payment_method, "bank": data.bank_account_id,
            "treasury": selected_treasury_id,
            "check_num": data.check_number, "check_date": data.check_date,
            "ref": data.reference, "notes": data.notes, "user": current_user.id,
            "bid": branch_id,
            "curr": currency, "rate": exchange_rate
        }).fetchone()

        voucher_id = result[0]

        # 2. Process Allocations
        total_allocated = Decimal("0")
        for alloc in data.allocations:
            alloc_amt = _dec(alloc.allocated_amount).quantize(_D2, ROUND_HALF_UP)
            if alloc_amt <= 0:
                raise HTTPException(status_code=400, detail="مبلغ التخصيص يجب أن يكون أكبر من صفر")

            # Lock invoice row to prevent concurrent over-allocation
            inv_info = db.execute(text("""
                SELECT party_id, total, COALESCE(paid_amount, 0) AS paid_amount
                FROM invoices
                WHERE id = :iid
                FOR UPDATE
            """), {"iid": alloc.invoice_id}).fetchone()
            if not inv_info:
                raise HTTPException(status_code=404, detail=f"الفاتورة {alloc.invoice_id} غير موجودة")
            if int(inv_info.party_id) != int(data.customer_id):
                raise HTTPException(status_code=400, detail=f"الفاتورة {alloc.invoice_id} لا تتبع العميل المحدد")

            remaining = (_dec(inv_info.total) - _dec(inv_info.paid_amount)).quantize(_D2, ROUND_HALF_UP)
            if alloc_amt > remaining + _D2:
                raise HTTPException(status_code=400, detail=f"مبلغ التخصيص ({alloc_amt:.2f}) يتجاوز المتبقي على الفاتورة ({remaining:.2f})")

            total_allocated = (total_allocated + alloc_amt).quantize(_D2, ROUND_HALF_UP)

            # Insert allocation record
            db.execute(text("""
                INSERT INTO payment_allocations (voucher_id, invoice_id, allocated_amount)
                VALUES (:vid, :iid, :amt)
            """), {"vid": voucher_id, "iid": alloc.invoice_id, "amt": alloc_amt})

            # Update invoice paid_amount and status
            db.execute(text("""
                UPDATE invoices
                SET paid_amount = COALESCE(paid_amount, 0) + :amt,
                    status = CASE
                        WHEN (COALESCE(paid_amount, 0) + :amt) >= total THEN 'paid'
                        WHEN (COALESCE(paid_amount, 0) + :amt) > 0 THEN 'partial'
                        ELSE status
                    END
                WHERE id = :iid
            """), {"amt": alloc_amt, "iid": alloc.invoice_id})

        if total_allocated > (_dec(data.amount) + _D2):
            raise HTTPException(**http_error(400, "allocations_exceed_voucher_amount"))

        # 3. Update Customer Balance via party_site_balances (reduce receivables)
        update_party_site_balance(db, party_id=data.customer_id, branch_id=branch_id,
                           currency=currency, amount=-float(data.amount))

        # 4. Create GL Entry (TASK-015: centralized)
        acc_ar = get_mapped_account_id(db, "acc_map_ar")
        acc_cash = get_mapped_account_id(db, "acc_map_cash_main")
        acc_bank = get_mapped_account_id(db, "acc_map_bank")
        selected_gl_id = selected_treasury.get("gl_account_id") if selected_treasury else None

        je_lines = []
        # Debit: Cash/Bank
        if data.payment_method == "cash" and (selected_gl_id or acc_cash):
            je_lines.append({"account_id": selected_gl_id or acc_cash, "debit": amount_base, "credit": 0,
                             "description": f"Cash Receipt - {voucher_num}",
                             "amount_currency": data.amount, "currency": currency})
        elif data.payment_method in ["bank", "check"] and (selected_gl_id or acc_bank):
            je_lines.append({"account_id": selected_gl_id or acc_bank, "debit": amount_base, "credit": 0,
                             "description": f"Bank Receipt - {voucher_num}",
                             "amount_currency": data.amount, "currency": currency})

        # Credit: AR
        if acc_ar:
            je_lines.append({"account_id": acc_ar, "debit": 0, "credit": amount_base,
                             "description": f"AR Collection - {voucher_num}",
                             "amount_currency": data.amount, "currency": currency})

        if not je_lines:
            raise HTTPException(400, "خريطة حسابات القبض غير مكتملة")

        je_id, je_num = create_journal_entry(
            db=db,
            company_id=current_user.company_id,
            date=str(data.voucher_date),
            description=f"Customer Receipt {voucher_num} ({currency})",
            lines=je_lines,
            user_id=current_user.id,
            branch_id=branch_id,
            reference=voucher_num,
            status="posted",
            currency=currency,
            exchange_rate=1.0,  # amounts already in base currency
            source="CustomerReceipt",
            source_id=voucher_id,
            username=getattr(current_user, "username", None),
            idempotency_key=f"rcv-{voucher_num}",
        )

        # 5. Update Treasury Balance — T1.3a idempotent recompute
        if selected_treasury_id:
            from utils.treasury_balance import recalc_treasury_from_gl
            recalc_treasury_from_gl(db, selected_treasury_id)

        db.commit()
        # T12 — scoped invalidation: receipt voucher hits treasury + AR + reports.
        invalidate_aggregates(str(current_user.company_id),
                              "treasury", "invoices", "sales_kpi",
                              "reports", "dashboard")
        

        cust_name = db.execute(text("SELECT name FROM parties WHERE id = :id"), {"id": data.customer_id}).scalar()
        # AUDIT LOG
        log_activity(
            db,
            user_id=current_user.id,
            username=current_user.username,
            action="sales.receipt.create",
            resource_type="payment_voucher",
            resource_id=str(voucher_id),
            details={"voucher_number": voucher_num, "amount": data.amount, "customer_id": data.customer_id, "customer_name": cust_name},
            request=request,
            branch_id=branch_id
        )

        # Notify finance team
        try:
            db.execute(text("""
                INSERT INTO notifications (user_id, type, title, message, link, is_read, created_at)
                SELECT DISTINCT u.id, 'payment_received', :title, :message, :link, FALSE, NOW()
                FROM company_users u
                WHERE u.is_active = TRUE AND u.role IN ('admin', 'superuser')
                AND u.id != :current_uid
            """), {
                "title": "💵 تم تحصيل دفعة من عميل",
                "message": f"تم تحصيل {data.amount:,.2f} من العميل {cust_name or ''} — سند {voucher_num}",
                "link": f"/sales/receipts/{voucher_id}",
                "current_uid": current_user.id
            })
        except Exception:
            logger.warning("Failed to send receipt notification", exc_info=True)

        return {"id": voucher_id, "voucher_number": voucher_num}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating receipt: {str(e)}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
@vouchers_router.post("/payments", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("sales.create"))])
def create_customer_payment(request: Request, data: CustomerPaymentCreate, current_user: dict = Depends(get_current_user)):
    """إنشاء سند صرف لعميل (رد مبلغ)"""
    db = get_db_connection(current_user.company_id)
    try:
        from utils.accounting import generate_sequential_number, get_base_currency
        base_currency = get_base_currency(db)
        branch_id = validate_branch_access(current_user, data.branch_id) if data.branch_id else None
        selected_treasury_id = data.bank_account_id
        selected_treasury = None
        if selected_treasury_id:
            selected_treasury = validate_treasury_account_access(db, current_user, selected_treasury_id, branch_id)
            if branch_id is None and selected_treasury.get("branch_id") is not None:
                branch_id = int(selected_treasury["branch_id"])
        branch_id = validate_branch_access(current_user, branch_id)

        voucher_num = generate_sequential_number(db, f"PAY-{datetime.now().year}", "payment_vouchers", "voucher_number")

        # SLS-011: Prevent posting payments to closed fiscal periods
        from utils.fiscal_lock import check_fiscal_period_open
        check_fiscal_period_open(db, data.voucher_date)

        # Currency & Exchange Rate
        currency = data.currency or base_currency
        exchange_rate = _dec(data.exchange_rate or 1)
        if exchange_rate <= 0:
            raise HTTPException(**http_error(400, "exchange_rate_must_be_positive"))
        amount_base = (_dec(data.amount) * exchange_rate).quantize(_D2, ROUND_HALF_UP)

        # 1. Insert Voucher Header
        result = db.execute(text("""
            INSERT INTO payment_vouchers (
                voucher_number, voucher_type, voucher_date, party_type, party_id,
                amount, payment_method, bank_account_id, treasury_account_id, check_number, check_date,
                reference, notes, status, created_by, branch_id,
                currency, exchange_rate
            ) VALUES (
                :vnum, 'payment', :vdate, 'customer', :cust,
                :amt, :method, :bank, :treasury, :check_num, :check_date,
                :ref, :notes, 'posted', :user, :bid,
                :curr, :rate
            ) RETURNING id
        """), {
            "vnum": voucher_num, "vdate": data.voucher_date, "cust": data.customer_id,
            "amt": data.amount, "method": data.payment_method, "bank": data.bank_account_id,
            "treasury": selected_treasury_id,
            "check_num": data.check_number, "check_date": data.check_date,
            "ref": data.reference, "notes": data.notes, "user": current_user.id,
            "bid": branch_id,
            "curr": currency, "rate": exchange_rate
        }).fetchone()

        voucher_id = result[0]

        # 1.5 Process Allocations (if any)
        total_allocated = Decimal("0")
        for alloc in data.allocations:
            alloc_amt = _dec(alloc.allocated_amount).quantize(_D2, ROUND_HALF_UP)
            if alloc_amt <= 0:
                raise HTTPException(status_code=400, detail="مبلغ التخصيص يجب أن يكون أكبر من صفر")

            inv_info = db.execute(text("""
                SELECT party_id, total, COALESCE(paid_amount, 0) AS paid_amount
                FROM invoices
                WHERE id = :iid
                FOR UPDATE
            """), {"iid": alloc.invoice_id}).fetchone()
            if not inv_info:
                raise HTTPException(status_code=404, detail=f"الفاتورة {alloc.invoice_id} غير موجودة")
            if int(inv_info.party_id) != int(data.customer_id):
                raise HTTPException(status_code=400, detail=f"الفاتورة {alloc.invoice_id} لا تتبع العميل المحدد")

            remaining = (_dec(inv_info.total) - _dec(inv_info.paid_amount)).quantize(_D2, ROUND_HALF_UP)
            if alloc_amt > remaining + _D2:
                raise HTTPException(status_code=400, detail=f"مبلغ التخصيص ({alloc_amt:.2f}) يتجاوز المتبقي على الفاتورة ({remaining:.2f})")

            total_allocated = (total_allocated + alloc_amt).quantize(_D2, ROUND_HALF_UP)

            db.execute(text("""
                INSERT INTO payment_allocations (voucher_id, invoice_id, allocated_amount)
                VALUES (:vid, :iid, :amt)
            """), {"vid": voucher_id, "iid": alloc.invoice_id, "amt": alloc_amt})

            # Update invoice paid_amount
            db.execute(text("""
                UPDATE invoices
                SET paid_amount = COALESCE(paid_amount, 0) + :amt
                WHERE id = :iid
            """), {"amt": alloc_amt, "iid": alloc.invoice_id})

            # Update status
            db.execute(text("""
                UPDATE invoices
                SET status = CASE 
                    WHEN (total - COALESCE(paid_amount, 0)) <= 0.01 THEN 'paid'
                    ELSE 'partial'
                END
                WHERE id = :iid
            """), {"iid": alloc.invoice_id})

        if total_allocated > (_dec(data.amount) + _D2):
            raise HTTPException(**http_error(400, "allocations_exceed_voucher_amount"))

        # 2. Update Customer Balance via party_site_balances (increase because we're paying them)
        update_party_site_balance(db, party_id=data.customer_id, branch_id=branch_id,
                           currency=currency, amount=float(data.amount))

        # 3. Create GL Entry (TASK-015: centralized)
        from utils.accounting import get_mapped_account_id, prepare_je_lines
        acc_ar = get_mapped_account_id(db, "acc_map_ar")
        acc_cash = get_mapped_account_id(db, "acc_map_cash")
        acc_bank = get_mapped_account_id(db, "acc_map_bank") or get_mapped_account_id(db, "acc_map_cash")
        selected_gl_id = selected_treasury.get("gl_account_id") if selected_treasury else None

        je_lines = []
        # Debit: AR (reduce customer credit)
        if acc_ar:
            je_lines.append({"account_id": acc_ar, "debit": amount_base, "credit": 0,
                             "description": f"AR Payment - {voucher_num}",
                             "amount_currency": data.amount, "currency": currency})

        # Credit: Cash/Bank (money out)
        if data.payment_method == "cash" and (selected_gl_id or acc_cash):
            je_lines.append({"account_id": selected_gl_id or acc_cash, "debit": 0, "credit": amount_base,
                             "description": f"Cash Payment - {voucher_num}",
                             "amount_currency": data.amount, "currency": currency})
        elif data.payment_method in ["bank", "check"] and (selected_gl_id or acc_bank):
            je_lines.append({"account_id": selected_gl_id or acc_bank, "debit": 0, "credit": amount_base,
                             "description": f"Bank Payment - {voucher_num}",
                             "amount_currency": data.amount, "currency": currency})

        # Validate before insert
        valid_lines = prepare_je_lines(je_lines, source=f"REFUND-{voucher_num}")

        je_id, je_num = create_journal_entry(
            db=db,
            company_id=current_user.company_id,
            date=str(data.voucher_date),
            description=f"Customer Payment {voucher_num} ({currency})",
            lines=valid_lines,
            user_id=current_user.id,
            branch_id=branch_id,
            reference=voucher_num,
            status="posted",
            currency=currency,
            exchange_rate=1.0,  # amounts already in base currency
            source="CustomerPayment",
            source_id=voucher_id,
            username=getattr(current_user, "username", None),
            idempotency_key=f"pay-{voucher_num}",
        )

        if selected_treasury_id:
            from utils.treasury_balance import recalc_treasury_from_gl
            recalc_treasury_from_gl(db, selected_treasury_id)

        db.commit()
        # T12 — scoped invalidation (payment voucher)
        invalidate_aggregates(str(current_user.company_id),
                              "treasury", "invoices", "sales_kpi",
                              "reports", "dashboard")
        

        cust_name = db.execute(text("SELECT name FROM parties WHERE id = :id"), {"id": data.customer_id}).scalar()
        # AUDIT LOG
        log_activity(
            db,
            user_id=current_user.id,
            username=current_user.username,
            action="sales.payment.create",
            resource_type="payment_voucher",
            resource_id=str(voucher_id),
            details={"voucher_number": voucher_num, "amount": data.amount, "customer_id": data.customer_id, "customer_name": cust_name},
            request=request,
            branch_id=branch_id
        )
        return {"id": voucher_id, "voucher_number": voucher_num}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating receipt: {str(e)}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
@vouchers_router.get("/receipts", response_model=List[dict], dependencies=[Depends(require_permission("sales.view"))])
def list_customer_receipts(branch_id: Optional[int] = None, current_user: dict = Depends(get_current_user)):
    """قائمة سندات القبض"""
    branch_scope = resolve_branch_scope(current_user, branch_id)

    db = get_db_connection(current_user.company_id)
    try:
        query_str = """
            SELECT pv.id, pv.voucher_number, pv.voucher_date, pv.amount,
                   pv.payment_method, pv.status, p.name as customer_name
            FROM payment_vouchers pv
            JOIN parties p ON pv.party_id = p.id
            WHERE pv.voucher_type = 'receipt' AND pv.party_type = 'customer'
        """
        params = {}
        query_str += branch_scope_filter_from_scope(branch_scope, "pv.branch_id", params)

        query_str += " ORDER BY pv.created_at DESC"

        result = db.execute(text(query_str), params).fetchall()
        return [dict(row._mapping) for row in result]
    except Exception as e:
        logger.error(f"Error listing receipts: {str(e)}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
@vouchers_router.get("/payments", response_model=List[dict], dependencies=[Depends(require_permission("sales.view"))])
def list_customer_payments(branch_id: Optional[int] = None, current_user: dict = Depends(get_current_user)):
    """قائمة سندات الصرف (العملاء)"""
    branch_scope = resolve_branch_scope(current_user, branch_id)

    db = get_db_connection(current_user.company_id)
    try:
        query_str = """
            SELECT pv.id, pv.voucher_number, pv.voucher_date, pv.amount,
                   pv.payment_method, pv.status, p.name as customer_name
            FROM payment_vouchers pv
            JOIN parties p ON pv.party_id = p.id
            WHERE pv.voucher_type = 'payment' AND pv.party_type = 'customer'
        """
        params = {}
        query_str += branch_scope_filter_from_scope(branch_scope, "pv.branch_id", params)

        query_str += " ORDER BY pv.created_at DESC"

        result = db.execute(text(query_str), params).fetchall()
        return [dict(row._mapping) for row in result]
    except Exception as e:
        logger.error(f"Error listing payments: {str(e)}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
@vouchers_router.get("/payments/{voucher_id}", response_model=dict, dependencies=[Depends(require_permission("sales.view"))])
def get_payment_details(voucher_id: int, current_user: dict = Depends(get_current_user)):
    """تفاصيل سند صرف"""
    db = get_db_connection(current_user.company_id)
    try:
        # Get Header
        header = db.execute(text("""
            SELECT pv.*, p.name as customer_name, p.email as customer_email, p.phone as customer_phone
            FROM payment_vouchers pv
            JOIN parties p ON pv.party_id = p.id
            WHERE pv.id = :id AND pv.voucher_type = 'payment'
        """), {"id": voucher_id}).fetchone()

        if not header:
            raise HTTPException(status_code=404, detail="Payment not found")

        # Enforce branch access for single resource
        from utils.permissions import validate_branch_access
        if header.branch_id:
            validate_branch_access(current_user, header.branch_id)

        return dict(header._mapping)
    except Exception as e:
        logger.error(f"Error getting payment details: {str(e)}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
@vouchers_router.get("/receipts/{voucher_id}", response_model=dict, dependencies=[Depends(require_permission("sales.view"))])
def get_receipt_details(voucher_id: int, current_user: dict = Depends(get_current_user)):
    """تفاصيل سند قبض"""
    db = get_db_connection(current_user.company_id)
    try:
        # Get Header
        header = db.execute(text("""
            SELECT pv.*, p.name as customer_name, p.email as customer_email, p.phone as customer_phone
            FROM payment_vouchers pv
            JOIN parties p ON pv.party_id = p.id
            WHERE pv.id = :id AND pv.voucher_type = 'receipt'
        """), {"id": voucher_id}).fetchone()

        if not header:
            raise HTTPException(status_code=404, detail="Receipt not found")

        # Enforce branch access for single resource
        from utils.permissions import validate_branch_access
        if header.branch_id:
            validate_branch_access(current_user, header.branch_id)

        # Get Allocations
        allocations = db.execute(text("""
            SELECT pa.*, i.invoice_number
            FROM payment_allocations pa
            JOIN invoices i ON pa.invoice_id = i.id
            WHERE pa.voucher_id = :id
        """), {"id": voucher_id}).fetchall()

        return {
            **dict(header._mapping),
            "allocations": [dict(a._mapping) for a in allocations]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting receipt: {str(e)}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ==========================================================================
# PAY-F2 — Auto-match unapplied customer receipts to open invoices
# Phase-11 Sprint-5
# ==========================================================================

@vouchers_router.post(
    "/receipts/{voucher_id}/auto-match",
    dependencies=[Depends(require_permission("sales.create"))],
)
def auto_match_receipt(
    voucher_id: int,
    request: Request,
    current_user=Depends(get_current_user),
):
    """Automatically allocate the unapplied portion of a customer receipt.

    Strategy (conservative — safe to run unattended):
      1. Exact match: single unpaid invoice with remaining == unapplied.
      2. FIFO fill: apply remainder to oldest open invoices until exhausted.
    Only invoices for the same customer are considered.
    """
    db = get_db_connection(current_user.company_id)
    try:
        v = db.execute(
            text(
                """
                SELECT id, party_id, amount
                FROM payment_vouchers
                WHERE id = :id AND voucher_type = 'customer_receipt'
                FOR UPDATE
                """
            ),
            {"id": voucher_id},
        ).fetchone()
        if not v:
            raise HTTPException(**http_error(404, "voucher_not_found"))

        already = db.execute(
            text("SELECT COALESCE(SUM(allocated_amount), 0) FROM payment_allocations WHERE voucher_id = :vid"),
            {"vid": voucher_id},
        ).scalar() or 0
        unapplied = (_dec(v.amount) - _dec(already)).quantize(_D2, ROUND_HALF_UP)
        if unapplied <= _D2:
            return {"allocated": 0, "message": "no_unapplied_amount"}

        # Fetch open invoices, FIFO
        open_invs = db.execute(
            text(
                """
                SELECT id, total, COALESCE(paid_amount, 0) AS paid_amount, invoice_date
                FROM invoices
                WHERE party_id = :pid
                  AND status IN ('unpaid', 'partial', 'draft')
                  AND COALESCE(paid_amount, 0) < total
                ORDER BY invoice_date ASC, id ASC
                FOR UPDATE
                """
            ),
            {"pid": v.party_id},
        ).fetchall()

        if not open_invs:
            return {"allocated": 0, "message": "no_open_invoices"}

        allocations: list[dict] = []

        # Pass 1 — exact match
        for inv in open_invs:
            remaining = (_dec(inv.total) - _dec(inv.paid_amount)).quantize(_D2, ROUND_HALF_UP)
            if remaining == unapplied:
                allocations.append({"invoice_id": inv.id, "amount": remaining})
                unapplied = _dec("0")
                break

        # Pass 2 — FIFO fill
        if unapplied > _D2:
            for inv in open_invs:
                if unapplied <= _D2:
                    break
                if any(a["invoice_id"] == inv.id for a in allocations):
                    continue
                remaining = (_dec(inv.total) - _dec(inv.paid_amount)).quantize(_D2, ROUND_HALF_UP)
                if remaining <= 0:
                    continue
                pay = min(remaining, unapplied)
                allocations.append({"invoice_id": inv.id, "amount": pay})
                unapplied = (unapplied - pay).quantize(_D2, ROUND_HALF_UP)

        if not allocations:
            return {"allocated": 0, "message": "no_matches"}

        for a in allocations:
            db.execute(
                text(
                    """
                    INSERT INTO payment_allocations (voucher_id, invoice_id, allocated_amount)
                    VALUES (:vid, :iid, :amt)
                    """
                ),
                {"vid": voucher_id, "iid": a["invoice_id"], "amt": a["amount"]},
            )
            db.execute(
                text(
                    """
                    UPDATE invoices
                    SET paid_amount = COALESCE(paid_amount, 0) + :amt,
                        status = CASE
                            WHEN (COALESCE(paid_amount, 0) + :amt) >= total THEN 'paid'
                            WHEN (COALESCE(paid_amount, 0) + :amt) > 0 THEN 'partial'
                            ELSE status
                        END
                    WHERE id = :iid
                    """
                ),
                {"amt": a["amount"], "iid": a["invoice_id"]},
            )

        total_alloc = sum(a["amount"] for a in allocations)
        db.commit()
        log_activity(
            db,
            user_id=current_user.id,
            username=current_user.username,
            action="payments.auto_match",
            resource_type="voucher",
            resource_id=str(voucher_id),
            details={"allocations": [dict(a, amount=float(a["amount"])) for a in allocations]},
            request=request,
        )
        return {
            "allocated": float(total_alloc),
            "allocation_count": len(allocations),
            "allocations": [{"invoice_id": a["invoice_id"], "amount": float(a["amount"])} for a in allocations],
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
