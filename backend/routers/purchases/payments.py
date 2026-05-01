"""Purchases sub-router — split from monolithic purchases.py (T6.3).

This file is auto-generated when purchases.py was split. Endpoints here
are mounted under the parent /buying prefix via purchases/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from utils.i18n import http_error
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
from utils.permissions import require_permission, require_module
from utils.accounting import get_mapped_account_id, generate_sequential_number, get_base_currency
from utils.fiscal_lock import check_fiscal_period_open
from services.gl_service import create_journal_entry as gl_create_journal_entry
from schemas.purchases import (
    PurchaseCreate, SupplierGroupCreate, POCreate, POReceiveRequest,
    SupplierPaymentCreate,
)

_D2 = Decimal("0.01")
_D4 = Decimal("0.0001")


def _dec(v) -> Decimal:
    """Convert any numeric value to Decimal safely."""
    return Decimal(str(v)) if v is not None else Decimal("0")


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/payments", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("buying.create"))], response_model=Dict[str, Any])
def create_supplier_payment(request: Request, data: SupplierPaymentCreate, current_user: dict = Depends(get_current_user)):
    """إنشاء سند صرف/قبض لمورد"""
    with transactional(current_user.company_id) as db:
        try:
            from utils.accounting import generate_sequential_number, get_base_currency
            base_currency = get_base_currency(db)
            # Validate amount
            if data.amount is None or data.amount <= 0:
                raise HTTPException(**http_error(400, "amount_must_be_positive"))
    
            # Fiscal-period lock: payment voucher posts at voucher_date.
            check_fiscal_period_open(db, data.voucher_date)
            
            # Check supplier balance (total owed)
            supplier_balance = db.execute(text("""
                SELECT COALESCE(current_balance, 0) as balance
                FROM parties
                WHERE id = :sid
                FOR UPDATE
            """), {"sid": data.supplier_id}).fetchone()
            if not supplier_balance:
                raise HTTPException(**http_error(404, "supplier_not_found"))
            
            # For payments (not refunds), warn if paying more than owed
            voucher_rate = _dec(data.exchange_rate or 1)
            if voucher_rate <= 0:
                raise HTTPException(**http_error(400, "exchange_rate_must_be_positive"))
            amount_base = (_dec(data.amount) * voucher_rate).quantize(_D2, ROUND_HALF_UP)
            if data.voucher_type != 'refund' and amount_base > (_dec(supplier_balance.balance) + _D2):
                # Allow overpayment but log warning (some businesses prepay)
                logger.warning(f"Supplier payment {data.amount} exceeds balance {supplier_balance.balance} for supplier {data.supplier_id}")
            
            # Prefix based on type
            prefix = "PAY" if data.voucher_type != 'refund' else "RCT"
            voucher_num = generate_sequential_number(db, f"{prefix}-{date.today().year}", "payment_vouchers", "voucher_number")
            
            # 1. Insert Voucher Header
            result = db.execute(text("""
                INSERT INTO payment_vouchers (
                    voucher_number, voucher_type, voucher_date, party_type, party_id, 
                    amount, payment_method, bank_account_id, treasury_account_id, check_number, check_date,
                    reference, notes, status, created_by, branch_id, currency, exchange_rate
                ) VALUES (
                    :vnum, :type, :vdate, 'supplier', :supp,
                    :amt, :method, :bank, :treasury, :check_num, :check_date,
                    :ref, :notes, 'posted', :user, :bid, :curr, :rate
                ) RETURNING id
            """), {
                "vnum": voucher_num, "type": data.voucher_type or 'payment', "vdate": data.voucher_date, "supp": data.supplier_id,
                "amt": data.amount, "method": data.payment_method, 
                "bank": data.bank_account_id if data.payment_method != 'cash' else None,
                "treasury": data.treasury_account_id or (data.bank_account_id if data.payment_method == 'cash' else None), 
                "check_num": data.check_number, "check_date": data.check_date,
                "ref": data.reference, "notes": data.notes, "user": current_user.id, "bid": data.branch_id,
                "curr": data.currency, "rate": data.exchange_rate or 1.0
            }).fetchone()
            
            voucher_id = result[0]
            
            # 2. Process Allocations
            total_allocated = Decimal('0')
            for alloc in data.allocations:
                if alloc.allocated_amount is None or alloc.allocated_amount <= 0:
                    raise HTTPException(status_code=400, detail="قيمة التخصيص يجب أن تكون أكبر من صفر")
    
                inv_row = db.execute(text("""
                    SELECT id, party_id, invoice_type, total, COALESCE(paid_amount, 0) AS paid_amount,
                           currency, exchange_rate
                    FROM invoices
                    WHERE id = :id
                    FOR UPDATE
                """), {"id": alloc.invoice_id}).fetchone()
                if not inv_row:
                    raise HTTPException(status_code=404, detail=f"الفاتورة {alloc.invoice_id} غير موجودة")
                if int(inv_row.party_id) != int(data.supplier_id):
                    raise HTTPException(status_code=400, detail=f"الفاتورة {alloc.invoice_id} لا تتبع المورد المحدد")
                if inv_row.invoice_type != 'purchase':
                    raise HTTPException(status_code=400, detail=f"التخصيص مسموح لفواتير الشراء فقط. الفاتورة {alloc.invoice_id} نوعها {inv_row.invoice_type}")
    
                alloc_amount = _dec(alloc.allocated_amount)
                total_allocated = (total_allocated + alloc_amount).quantize(_D4, ROUND_HALF_UP)
    
                db.execute(text("""
                    INSERT INTO payment_allocations (voucher_id, invoice_id, allocated_amount)
                    VALUES (:vid, :iid, :amt)
                """), {"vid": voucher_id, "iid": alloc.invoice_id, "amt": alloc_amount})
                
                inv_curr = inv_row.currency or base_currency
                inv_rate = _dec(inv_row.exchange_rate or 1)
                if inv_rate <= 0:
                    raise HTTPException(status_code=400, detail=f"سعر صرف الفاتورة {alloc.invoice_id} غير صالح")
    
                # if voucher is SYP (rate 1) and invoice is USD (rate 3.75)
                # allocated 375 SYP -> debt reduction = 375 / 3.75 = 100 USD
                reduction = (alloc_amount * (voucher_rate / inv_rate)).quantize(_D4, ROUND_HALF_UP)
    
                remaining = (_dec(inv_row.total or 0) - _dec(inv_row.paid_amount or 0)).quantize(_D4, ROUND_HALF_UP)
                if reduction > remaining + _D2:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"قيمة التخصيص للفواتير تتجاوز المتبقي في الفاتورة {alloc.invoice_id}. "
                            f"المتبقي: {remaining}, المطلوب تخصيصه: {reduction}"
                        )
                    )
    
                db.execute(text("""
                    UPDATE invoices
                    SET paid_amount = LEAST(total, COALESCE(paid_amount, 0) + :amt),
                        status = CASE
                            WHEN LEAST(total, COALESCE(paid_amount, 0) + :amt) >= total - 0.01 THEN 'paid'
                            WHEN LEAST(total, COALESCE(paid_amount, 0) + :amt) > 0.01 THEN 'partial'
                            ELSE status
                        END
                    WHERE id = :iid
                """), {"amt": reduction, "iid": alloc.invoice_id})
    
            if total_allocated > (_dec(data.amount) + _D2):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"إجمالي التخصيصات ({total_allocated}) أكبر من مبلغ السند ({data.amount})."
                    )
                )
            
            # 3. Update Supplier Balance (Base + Currency)
            amount_base = (_dec(data.amount) * voucher_rate).quantize(_D2, ROUND_HALF_UP)
            balance_change = amount_base if data.voucher_type != 'refund' else -amount_base
            
            # Update base currency balance
            db.execute(text("""
                UPDATE parties
                SET current_balance = COALESCE(current_balance, 0) + :change
                WHERE id = :sid
            """), {"change": balance_change, "sid": data.supplier_id})
            
            # Update foreign currency balance if applicable
            balance_change_fc = _dec(data.amount) if data.voucher_type != 'refund' else -_dec(data.amount)
            if data.currency and data.currency != base_currency:
                db.execute(text("""
                    UPDATE parties
                    SET balance_currency = COALESCE(balance_currency, 0) + :change
                    WHERE id = :sid
                """), {"change": balance_change_fc, "sid": data.supplier_id})
            
            # 4. Create GL Entry
            # Dynamic Treasury Lookup
            treasury_id = data.treasury_account_id or data.bank_account_id
            cash_acc = None
            treasury_curr = data.currency
            treasury_rate = voucher_rate
            amount_treasury_curr = _dec(data.amount)
            
            if treasury_id:
                # Fetch treasury account details
                treasury = db.execute(text("SELECT gl_account_id, currency FROM treasury_accounts WHERE id = :id"), {"id": treasury_id}).fetchone()
                if treasury:
                    cash_acc = treasury.gl_account_id
                    treasury_curr = treasury.currency or data.currency
                    
                    # Fetch current rate for treasury currency
                    treasury_rate = Decimal('1')
                    if treasury_curr != base_currency:
                         # Try to get rate from currencies table
                         curr_data = db.execute(text("SELECT current_rate FROM currencies WHERE code = :code"), {"code": treasury_curr}).fetchone()
                         if curr_data:
                             treasury_rate = _dec(curr_data.current_rate or 1)
                    
                    # Calculate amount in treasury's currency
                    if data.transaction_rate and data.transaction_rate > 0:
                        amount_treasury_curr = (_dec(data.amount) * _dec(data.transaction_rate)).quantize(_D4, ROUND_HALF_UP)
                    else:
                        amount_treasury_curr = (_dec(data.amount) * (voucher_rate / treasury_rate)).quantize(_D4, ROUND_HALF_UP)
                    
                    amount_base_cash = (amount_treasury_curr * treasury_rate).quantize(_D2, ROUND_HALF_UP)
                    
                    # Update Treasury account specific balance
                    # Payment decreases balance (Credit Asset), Refund increases balance (Debit Asset)
                    if data.voucher_type == 'refund':
                        balance_change_treasury = abs(amount_treasury_curr)
                    else:
                        balance_change_treasury = -abs(amount_treasury_curr)
    
                    db.execute(text("""
                        UPDATE treasury_accounts
                        SET current_balance = COALESCE(current_balance, 0) + :change
                        WHERE id = :id
                    """), {"change": balance_change_treasury, "id": treasury_id})
            
            # Fallback to legacy mappings if no treasury linked
            if not cash_acc:
                cash_acc = get_mapped_account_id(db, "acc_map_cash_main")
                if data.payment_method in ['bank', 'check']: 
                    cash_acc = get_mapped_account_id(db, "acc_map_bank")
    
            ap_acc = get_mapped_account_id(db, "acc_map_ap")
            # Ensure we have a base amount for the cash side (defaulting to voucher's base if not set)
            amount_base_cash = locals().get('amount_base_cash', amount_base)
    
            if ap_acc and cash_acc:
                je_lines = []
                if data.voucher_type == 'refund':
                    # Receipt: Debit Cash, Credit AP
                    je_lines.append({"account_id": cash_acc, "debit": amount_base_cash, "credit": 0, "description": "قبض", "amount_currency": amount_treasury_curr, "currency": treasury_curr})
                    je_lines.append({"account_id": ap_acc, "debit": 0, "credit": amount_base, "description": "من مورد", "amount_currency": data.amount, "currency": data.currency})
                else:
                    # Payment: Debit AP, Credit Cash
                    je_lines.append({"account_id": ap_acc, "debit": amount_base, "credit": 0, "description": "صرف", "amount_currency": data.amount, "currency": data.currency})
                    je_lines.append({"account_id": cash_acc, "debit": 0, "credit": amount_base_cash, "description": "من خزينة", "amount_currency": amount_treasury_curr, "currency": treasury_curr})
                
                # 5. Handle Exchange Difference to Balance the JE
                diff = (amount_base - amount_base_cash).quantize(_D2, ROUND_HALF_UP)
                if diff.copy_abs() > _D2:
                    fx_acc = get_mapped_account_id(db, "acc_map_fx_difference") or get_mapped_account_id(db, "acc_map_expense_other")
                    if fx_acc:
                        # Logic: If diff (AP-Cash) is +ve, we need More Credit (if Payment) or More Debit (if Refund)
                        je_diff = -diff if data.voucher_type != 'refund' else diff # Adjustment to Debit
                        if je_diff > 0:
                            je_lines.append({"account_id": fx_acc, "debit": abs(je_diff), "credit": 0, "description": "فرق سعر صرف"})
                        else:
                            je_lines.append({"account_id": fx_acc, "debit": 0, "credit": abs(je_diff), "description": "فرق سعر صرف"})
    
                gl_create_journal_entry(
                    db=db,
                    company_id=current_user.company_id,
                    date=str(data.voucher_date),
                    description=f"{'سند قبض من' if data.voucher_type=='refund' else 'سند صرف لـ'} مورد {voucher_num} ({data.currency})",
                    reference=voucher_num,
                    lines=je_lines,
                    user_id=current_user.id,
                    branch_id=data.branch_id,
                    currency=data.currency,
                    exchange_rate=data.exchange_rate or 1.0,
                    source="payment_voucher",
                    source_id=voucher_id
                )
    
            invalidate_company_cache(str(current_user.company_id))
            
    
            supp_name = db.execute(text("SELECT name FROM parties WHERE id = :id"), {"id": data.supplier_id}).scalar()
            log_activity(
                db_conn=db,
                user_id=current_user.id,
                username=current_user.username,
                action="buying.supplier_payment.create",
                resource_type="payment_voucher",
                resource_id=str(voucher_id),
                details={"voucher_number": voucher_num, "amount": data.amount, "supplier_name": supp_name},
                request=request,
                branch_id=data.branch_id
            )
    
            # Notify finance team
            try:
                db.execute(text("""
                    INSERT INTO notifications (user_id, type, title, message, link, is_read, created_at)
                    SELECT DISTINCT u.id, 'supplier_payment', :title, :message, :link, FALSE, NOW()
                    FROM company_users u
                    WHERE u.is_active = TRUE AND u.role IN ('admin', 'superuser')
                    AND u.id != :current_uid
                """), {
                    "title": "💳 تم صرف سند لمورد",
                    "message": f"تم صرف {data.amount:,.2f} للمورد {supp_name or ''} — سند {voucher_num}",
                    "link": f"/buying/payments/{voucher_id}",
                    "current_uid": current_user.id
                })
                db.commit()
            except Exception:
                pass
    
            return {"id": voucher_id, "message": "تم حفظ السند بنجاح"}
    
        except Exception as e:
            pass
            logger.error(f"Error creating payment: {e}")
            raise HTTPException(status_code=500, detail="حدث خطأ أثناء إنشاء سند الصرف")
        
@router.get("/payments", response_model=List[dict], dependencies=[Depends(require_permission("buying.view"))])
def list_supplier_payments(branch_id: Optional[int] = None, current_user: dict = Depends(get_current_user)):
    """قائمة سندات الصرف"""
    with transactional(current_user.company_id) as db:
        try:
            from utils.permissions import validate_branch_access
            branch_id = validate_branch_access(current_user, branch_id)
    
            query_str = """
                SELECT pv.id, pv.voucher_number, pv.voucher_date, pv.amount, pv.currency,
                       pv.payment_method, pv.status, p.name as supplier_name
                FROM payment_vouchers pv
                JOIN parties p ON pv.party_id = p.id
                WHERE pv.voucher_type = 'payment' AND pv.party_type = 'supplier'
            """
            params = {}
            if branch_id:
                query_str += " AND (pv.branch_id = :branch_id OR pv.branch_id IS NULL)"
                params["branch_id"] = branch_id
            
            query_str += " ORDER BY pv.created_at DESC"
            
            result = db.execute(text(query_str), params).fetchall()
            return [dict(row._mapping) for row in result]
        except Exception as e:
            logger.error(f"Error listing payments: {str(e)}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))

@router.get("/payments/{voucher_id}", response_model=dict, dependencies=[Depends(require_permission("buying.view"))])
def get_payment_details(voucher_id: int, current_user: dict = Depends(get_current_user)):
    """تفاصيل سند صرف"""
    with transactional(current_user.company_id) as db:
        try:
            header = db.execute(text("""
                SELECT pv.*, p.name as party_name, p.party_code
                FROM payment_vouchers pv
                JOIN parties p ON pv.party_id = p.id
                WHERE pv.id = :id AND pv.party_type = 'supplier' AND pv.voucher_type = 'payment'
            """), {"id": voucher_id}).fetchone()
            
            if not header:
                raise HTTPException(status_code=404, detail="Payment not found")
    
            from utils.permissions import validate_branch_access
            validate_branch_access(current_user, header._mapping.get("branch_id"))
    
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
            logger.error(f"Error getting payment: {str(e)}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))

@router.get("/suppliers/{supplier_id}/outstanding-invoices", response_model=List[dict], dependencies=[Depends(require_permission("buying.view"))])
def get_supplier_outstanding_invoices(
    supplier_id: int, 
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """Fetch unpaid/partial purchase invoices for a supplier"""
    with transactional(current_user.company_id) as db:
        try:
            query = """
                SELECT id, invoice_number, invoice_date, total, paid_amount, status, invoice_type,
                       currency, exchange_rate,
                       (total - COALESCE(paid_amount, 0)) as remaining_balance
                FROM invoices
                WHERE party_id = :sid
                  AND invoice_type IN ('purchase', 'purchase_return')
                  AND status IN ('unpaid', 'partial', 'posted')
            """
            params = {"sid": supplier_id}
            if branch_id:
                query += " AND branch_id = :bid"
                params["bid"] = branch_id
            
            query += " ORDER BY invoice_date ASC"
            
            result = db.execute(text(query), params).fetchall()
            return [dict(row._mapping) for row in result]
        except Exception as e:
            logger.error(f"Error fetching outstanding invoices: {str(e)}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
@router.get("/invoices/{invoice_id}/payment-history", response_model=List[dict], dependencies=[Depends(require_permission("buying.view"))])
def get_invoice_payment_history(invoice_id: int, current_user: dict = Depends(get_current_user)):
    """سجل الدفعات لفاتورة شراء معينة"""
    with transactional(current_user.company_id) as db:
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
                  AND pv.voucher_type = 'payment'
                ORDER BY pv.voucher_date DESC
            """), {"invoice_id": invoice_id}).fetchall()
            
            return [dict(row._mapping) for row in result]
        except Exception as e:
            logger.error(f"Error getting payment history: {str(e)}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
# ==================== INV-003: Purchase Credit Notes (إشعار دائن مشتريات) ====================
# Credit Note from Supplier: Reduces what we owe (e.g., supplier overcharged us, returns to supplier)
# GL: Debit AP (reduce payable), Credit Inventory/Expense + VAT Input

@router.get("/credit-notes", dependencies=[Depends(require_permission("buying.view"))], response_model=Dict[str, Any])
def list_purchase_credit_notes(
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
    """قائمة إشعارات دائنة (مشتريات)"""
    with transactional(current_user.company_id) as db:
        from utils.permissions import validate_branch_access
        branch_id = validate_branch_access(current_user, branch_id)

        conditions = ["i.invoice_type = 'purchase_credit_note'"]
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
        if branch_id:
            conditions.append("i.branch_id = :branch_id")
            params["branch_id"] = branch_id

        where = " AND ".join(conditions)
        total = db.execute(text(f"SELECT COUNT(*) FROM invoices i WHERE {where}"), params).scalar()  # noqa: sql-lint

        offset = (page - 1) * limit
        params["limit"] = limit
        params["offset"] = offset

        rows = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT i.*, p.name AS party_name,
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
            "total": total, "page": page,
            "pages": (total + limit - 1) // limit,
        }
@router.get("/credit-notes/{note_id}", dependencies=[Depends(require_permission("buying.view"))], response_model=Dict[str, Any])
def get_purchase_credit_note(note_id: int, current_user: dict = Depends(get_current_user)):
    """تفاصيل إشعار دائن مشتريات"""
    with transactional(current_user.company_id) as db:
        note = db.execute(text("""
            SELECT i.*, p.name AS party_name, p.phone AS party_phone, p.tax_number AS party_tax,
                   ri.invoice_number AS related_invoice_number,
                   cu.username AS created_by_name
            FROM invoices i
            LEFT JOIN parties p ON i.party_id = p.id
            LEFT JOIN invoices ri ON i.related_invoice_id = ri.id
            LEFT JOIN company_users cu ON i.created_by = cu.id
            WHERE i.id = :id AND i.invoice_type = 'purchase_credit_note'
        """), {"id": note_id}).fetchone()
        if not note:
            raise HTTPException(**http_error(404, "credit_note_not_found"))

        from utils.permissions import validate_branch_access
        validate_branch_access(current_user, note._mapping.get("branch_id"))

        lines = db.execute(text("""
            SELECT il.*, pr.name AS product_name, pr.sku AS product_sku
            FROM invoice_lines il LEFT JOIN products pr ON il.product_id = pr.id
            WHERE il.invoice_id = :id ORDER BY il.id
        """), {"id": note_id}).fetchall()

        result = dict(note._mapping)
        result["lines"] = [dict(l._mapping) for l in lines]
        return result
@router.post("/credit-notes", status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("buying.create"))], response_model=Dict[str, Any])
def create_purchase_credit_note(
    request: Request,
    data: dict,
    current_user: dict = Depends(get_current_user),
):
    """
    إنشاء إشعار دائن مشتريات
    GL: Debit AP, Credit Purchases/Inventory + VAT Input
    """
    with transactional(current_user.company_id) as db:
        try:
            party_id = data.get("party_id")
            related_invoice_id = data.get("related_invoice_id")
            lines = data.get("lines", [])
            if not lines:
                raise HTTPException(**http_error(400, "min_one_item_required"))
            if not party_id:
                raise HTTPException(status_code=400, detail="يجب تحديد المورد")
    
            if related_invoice_id:
                orig = db.execute(text(
                    "SELECT id, party_id, invoice_type FROM invoices WHERE id = :id"
                ), {"id": related_invoice_id}).fetchone()
                if not orig or orig.party_id != party_id:
                    raise HTTPException(status_code=400, detail="الفاتورة المرتبطة غير موجودة أو لا تخص هذا المورد")
    
            inv_date = data.get("invoice_date", str(date.today()))
            base_currency = get_base_currency(db)
            currency = data.get("currency", base_currency)
            exchange_rate = _dec(data.get("exchange_rate", 1))
            if exchange_rate <= 0:
                raise HTTPException(**http_error(400, "exchange_rate_must_be_positive"))
            branch_id = data.get("branch_id") or (current_user.allowed_branches[0] if current_user.allowed_branches else None)
    
            subtotal = Decimal('0')
            tax_total = Decimal('0')
            discount_total = Decimal('0')
            computed_lines = []
    
            for line in lines:
                qty = _dec(line.get("quantity", 1))
                price = _dec(line.get("unit_price", 0))
                tax_rate = _dec(line.get("tax_rate", 0))
                disc = _dec(line.get("discount", 0))
                line_net = (qty * price - disc).quantize(_D2, ROUND_HALF_UP)
                line_tax = (line_net * tax_rate / Decimal('100')).quantize(_D2, ROUND_HALF_UP)
                line_total = (line_net + line_tax).quantize(_D2, ROUND_HALF_UP)
                subtotal += line_net
                tax_total += line_tax
                discount_total += disc
                computed_lines.append({
                    "product_id": line.get("product_id"),
                    "description": line.get("description", ""),
                    "quantity": qty, "unit_price": price,
                    "tax_rate": tax_rate, "discount": disc, "total": line_total,
                })
    
            total = (subtotal + tax_total).quantize(_D2, ROUND_HALF_UP)
    
            inv_num = generate_sequential_number(db, "PCN", "invoices", "invoice_number")
            result = db.execute(text("""
                INSERT INTO invoices (
                    invoice_number, invoice_type, party_id, invoice_date,
                    subtotal, tax_amount, discount, total, paid_amount, status,
                    notes, branch_id, related_invoice_id, currency, exchange_rate, created_by
                ) VALUES (
                    :num, 'purchase_credit_note', :party, :date,
                    :sub, :tax, :disc, :total, 0, 'posted',
                    :notes, :branch, :rel, :curr, :rate, :user
                ) RETURNING id
            """), {
                "num": inv_num, "party": party_id, "date": inv_date,
                "sub": subtotal, "tax": tax_total, "disc": discount_total,
                "total": total, "notes": data.get("notes", ""),
                "branch": branch_id, "rel": related_invoice_id,
                "curr": currency, "rate": exchange_rate, "user": current_user.id,
            })
            note_id = result.fetchone()[0]
    
            for cl in computed_lines:
                db.execute(text("""
                    INSERT INTO invoice_lines (invoice_id, product_id, description, quantity, unit_price, tax_rate, discount, total)
                    VALUES (:inv, :prod, :desc, :qty, :price, :tax, :disc, :total)
                """), {"inv": note_id, "prod": cl["product_id"], "desc": cl["description"],
                       "qty": cl["quantity"], "price": cl["unit_price"], "tax": cl["tax_rate"],
                       "disc": cl["discount"], "total": cl["total"]})
    
            # GL: Debit AP, Credit Inventory + VAT
            acc_ap = get_mapped_account_id(db, "acc_map_ap")
            acc_inv = get_mapped_account_id(db, "acc_map_inventory")
            acc_vat = get_mapped_account_id(db, "acc_map_vat_in")
    
            if not acc_ap or not acc_inv:
                raise HTTPException(status_code=400, detail="إعدادات الحسابات غير مكتملة (AP / Inventory)")
    
            # FISCAL-LOCK: Reject if accounting period is closed
            check_fiscal_period_open(db, inv_date)
    
            gl_sub = (_dec(subtotal) * _dec(exchange_rate)).quantize(_D4, ROUND_HALF_UP)
            gl_tax = (_dec(tax_total) * _dec(exchange_rate)).quantize(_D4, ROUND_HALF_UP)
            gl_total = (_dec(total) * _dec(exchange_rate)).quantize(_D4, ROUND_HALF_UP)
    
            je_lines = []
            # Debit: AP (reduces payable)
            je_lines.append({"account_id": acc_ap, "debit": gl_total, "credit": 0,
                             "description": f"إشعار دائن مشتريات - تخفيض ذمم {inv_num}",
                             "amount_currency": total, "currency": currency})
            # Credit: Inventory/Purchases
            if gl_sub > 0:
                je_lines.append({"account_id": acc_inv, "debit": 0, "credit": gl_sub,
                                 "description": f"إشعار دائن مشتريات - تخفيض مخزون {inv_num}",
                                 "amount_currency": subtotal, "currency": currency})
            # Credit: VAT Input
            if gl_tax > 0 and acc_vat:
                je_lines.append({"account_id": acc_vat, "debit": 0, "credit": gl_tax,
                                 "description": f"إشعار دائن مشتريات - عكس ضريبة {inv_num}",
                                 "amount_currency": tax_total, "currency": currency})
    
            je_id, _ = gl_create_journal_entry(
                db=db,
                company_id=current_user.company_id,
                date=str(inv_date),
                description=f"إشعار دائن مشتريات {inv_num}",
                reference=inv_num,
                lines=je_lines,
                user_id=current_user.id,
                branch_id=branch_id,
                currency=currency,
                exchange_rate=exchange_rate,
                source="purchase_credit_note",
                source_id=note_id
            )
    
            # Reduce related invoice balance
            if related_invoice_id:
                db.execute(text("""
                    UPDATE invoices SET paid_amount = paid_amount + :amt,
                        status = CASE WHEN paid_amount + :amt >= total THEN 'paid' WHEN paid_amount + :amt > 0 THEN 'partial' ELSE status END
                    WHERE id = :id
                """), {"amt": total, "id": related_invoice_id})
    
            # Update supplier balance (credit note REDUCES what we owe supplier)
            gl_total_base = (_dec(total) * _dec(exchange_rate)).quantize(_D4, ROUND_HALF_UP)
            db.execute(text("""
                UPDATE parties SET current_balance = current_balance - :amt
                WHERE id = :pid
            """), {"amt": gl_total_base, "pid": party_id})
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="buying.credit_note.create", resource_type="purchase_credit_note",
                         resource_id=inv_num, details={"party_id": party_id, "total": str(total)},
                         request=request, branch_id=branch_id)
    
            return {"success": True, "id": note_id, "invoice_number": inv_num,
                    "journal_entry_id": je_id, "message": f"تم إنشاء الإشعار الدائن {inv_num} بنجاح"}
        except HTTPException:
            raise
        except Exception as e:
            pass
            logger.error(f"Error creating purchase credit note: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
# ==================== INV-004: Purchase Debit Notes (إشعار مدين مشتريات) ====================
# Debit Note to Supplier: Increases what we owe (e.g., undercharged, additional services)
# GL: Debit Inventory/Expense + VAT Input, Credit AP

@router.get("/debit-notes", dependencies=[Depends(require_permission("buying.view"))], response_model=Dict[str, Any])
def list_purchase_debit_notes(
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
    """قائمة إشعارات مدينة (مشتريات)"""
    with transactional(current_user.company_id) as db:
        from utils.permissions import validate_branch_access
        branch_id = validate_branch_access(current_user, branch_id)

        conditions = ["i.invoice_type = 'purchase_debit_note'"]
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
        if branch_id:
            conditions.append("i.branch_id = :branch_id")
            params["branch_id"] = branch_id

        where = " AND ".join(conditions)
        total = db.execute(text(f"SELECT COUNT(*) FROM invoices i WHERE {where}"), params).scalar()  # noqa: sql-lint
        offset = (page - 1) * limit
        params["limit"] = limit
        params["offset"] = offset

        rows = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT i.*, p.name AS party_name,
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
            "total": total, "page": page,
            "pages": (total + limit - 1) // limit,
        }
@router.get("/debit-notes/{note_id}", dependencies=[Depends(require_permission("buying.view"))], response_model=Dict[str, Any])
def get_purchase_debit_note(note_id: int, current_user: dict = Depends(get_current_user)):
    """تفاصيل إشعار مدين مشتريات"""
    with transactional(current_user.company_id) as db:
        note = db.execute(text("""
            SELECT i.*, p.name AS party_name, p.phone AS party_phone, p.tax_number AS party_tax,
                   ri.invoice_number AS related_invoice_number,
                   cu.username AS created_by_name
            FROM invoices i
            LEFT JOIN parties p ON i.party_id = p.id
            LEFT JOIN invoices ri ON i.related_invoice_id = ri.id
            LEFT JOIN company_users cu ON i.created_by = cu.id
            WHERE i.id = :id AND i.invoice_type = 'purchase_debit_note'
        """), {"id": note_id}).fetchone()
        if not note:
            raise HTTPException(**http_error(404, "debit_note_not_found"))

        from utils.permissions import validate_branch_access
        validate_branch_access(current_user, note._mapping.get("branch_id"))

        lines = db.execute(text("""
            SELECT il.*, pr.name AS product_name, pr.sku AS product_sku
            FROM invoice_lines il LEFT JOIN products pr ON il.product_id = pr.id
            WHERE il.invoice_id = :id ORDER BY il.id
        """), {"id": note_id}).fetchall()

        result = dict(note._mapping)
        result["lines"] = [dict(l._mapping) for l in lines]
        return result
@router.post("/debit-notes", status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("buying.create"))], response_model=Dict[str, Any])
def create_purchase_debit_note(
    request: Request,
    data: dict,
    current_user: dict = Depends(get_current_user),
):
    """
    إنشاء إشعار مدين مشتريات
    GL: Debit Inventory/Expense + VAT Input, Credit AP
    """
    with transactional(current_user.company_id) as db:
        try:
            party_id = data.get("party_id")
            related_invoice_id = data.get("related_invoice_id")
            lines = data.get("lines", [])
            if not lines:
                raise HTTPException(**http_error(400, "min_one_item_required"))
            if not party_id:
                raise HTTPException(status_code=400, detail="يجب تحديد المورد")
    
            inv_date = data.get("invoice_date", str(date.today()))
            base_currency = get_base_currency(db)
            currency = data.get("currency", base_currency)
            exchange_rate = _dec(data.get("exchange_rate", 1))
            if exchange_rate <= 0:
                raise HTTPException(**http_error(400, "exchange_rate_must_be_positive"))
            branch_id = data.get("branch_id") or (current_user.allowed_branches[0] if current_user.allowed_branches else None)
    
            subtotal = Decimal('0')
            tax_total = Decimal('0')
            discount_total = Decimal('0')
            computed_lines = []
    
            for line in lines:
                qty = _dec(line.get("quantity", 1))
                price = _dec(line.get("unit_price", 0))
                tax_rate = _dec(line.get("tax_rate", 0))
                disc = _dec(line.get("discount", 0))
                line_net = (qty * price - disc).quantize(_D2, ROUND_HALF_UP)
                line_tax = (line_net * tax_rate / Decimal('100')).quantize(_D2, ROUND_HALF_UP)
                line_total = (line_net + line_tax).quantize(_D2, ROUND_HALF_UP)
                subtotal += line_net
                tax_total += line_tax
                discount_total += disc
                computed_lines.append({
                    "product_id": line.get("product_id"),
                    "description": line.get("description", ""),
                    "quantity": qty, "unit_price": price,
                    "tax_rate": tax_rate, "discount": disc, "total": line_total,
                })
    
            total = (subtotal + tax_total).quantize(_D2, ROUND_HALF_UP)
    
            inv_num = generate_sequential_number(db, "PDN", "invoices", "invoice_number")
            result = db.execute(text("""
                INSERT INTO invoices (
                    invoice_number, invoice_type, party_id, invoice_date,
                    subtotal, tax_amount, discount, total, paid_amount, status,
                    notes, branch_id, related_invoice_id, currency, exchange_rate, created_by
                ) VALUES (
                    :num, 'purchase_debit_note', :party, :date,
                    :sub, :tax, :disc, :total, 0, 'unpaid',
                    :notes, :branch, :rel, :curr, :rate, :user
                ) RETURNING id
            """), {
                "num": inv_num, "party": party_id, "date": inv_date,
                "sub": subtotal, "tax": tax_total, "disc": discount_total,
                "total": total, "notes": data.get("notes", ""),
                "branch": branch_id, "rel": related_invoice_id,
                "curr": currency, "rate": exchange_rate, "user": current_user.id,
            })
            note_id = result.fetchone()[0]
    
            for cl in computed_lines:
                db.execute(text("""
                    INSERT INTO invoice_lines (invoice_id, product_id, description, quantity, unit_price, tax_rate, discount, total)
                    VALUES (:inv, :prod, :desc, :qty, :price, :tax, :disc, :total)
                """), {"inv": note_id, "prod": cl["product_id"], "desc": cl["description"],
                       "qty": cl["quantity"], "price": cl["unit_price"], "tax": cl["tax_rate"],
                       "disc": cl["discount"], "total": cl["total"]})
    
            # GL: Debit Inventory + VAT, Credit AP
            acc_ap = get_mapped_account_id(db, "acc_map_ap")
            acc_inv = get_mapped_account_id(db, "acc_map_inventory")
            acc_vat = get_mapped_account_id(db, "acc_map_vat_in")
    
            if not acc_ap or not acc_inv:
                raise HTTPException(status_code=400, detail="إعدادات الحسابات غير مكتملة (AP / Inventory)")
    
            # FISCAL-LOCK: Reject if accounting period is closed
            check_fiscal_period_open(db, inv_date)
    
            gl_sub = (_dec(subtotal) * _dec(exchange_rate)).quantize(_D4, ROUND_HALF_UP)
            gl_tax = (_dec(tax_total) * _dec(exchange_rate)).quantize(_D4, ROUND_HALF_UP)
            gl_total = (_dec(total) * _dec(exchange_rate)).quantize(_D4, ROUND_HALF_UP)
    
            je_lines = []
            # Debit: Inventory/Expense
            if gl_sub > 0:
                je_lines.append({"account_id": acc_inv, "debit": gl_sub, "credit": 0,
                                 "description": f"إشعار مدين مشتريات - زيادة مخزون {inv_num}",
                                 "amount_currency": subtotal, "currency": currency})
            # Debit: VAT Input
            if gl_tax > 0 and acc_vat:
                je_lines.append({"account_id": acc_vat, "debit": gl_tax, "credit": 0,
                                 "description": f"إشعار مدين مشتريات - ضريبة إضافية {inv_num}",
                                 "amount_currency": tax_total, "currency": currency})
            # Credit: AP
            je_lines.append({"account_id": acc_ap, "debit": 0, "credit": gl_total,
                             "description": f"إشعار مدين مشتريات - زيادة ذمم {inv_num}",
                             "amount_currency": total, "currency": currency})
    
            je_id, _ = gl_create_journal_entry(
                db=db,
                company_id=current_user.company_id,
                date=str(inv_date),
                description=f"إشعار مدين مشتريات {inv_num}",
                reference=inv_num,
                lines=je_lines,
                user_id=current_user.id,
                branch_id=branch_id,
                currency=currency,
                exchange_rate=exchange_rate,
                source="purchase_debit_note",
                source_id=note_id
            )
    
            # Update supplier balance (debit note INCREASES what we owe supplier)
            gl_total_base = (_dec(total) * _dec(exchange_rate)).quantize(_D4, ROUND_HALF_UP)
            db.execute(text("""
                UPDATE parties SET current_balance = current_balance + :amt
                WHERE id = :pid
            """), {"amt": gl_total_base, "pid": party_id})
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="buying.debit_note.create", resource_type="purchase_debit_note",
                         resource_id=inv_num, details={"party_id": party_id, "total": str(total)},
                         request=request, branch_id=branch_id)
    
            return {"success": True, "id": note_id, "invoice_number": inv_num,
                    "journal_entry_id": je_id, "message": f"تم إنشاء الإشعار المدين {inv_num} بنجاح"}
        except HTTPException:
            raise
        except Exception as e:
            pass
            logger.error(f"Error creating purchase debit note: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
# =====================================================
# 8.11 PURCHASES IMPROVEMENTS
# =====================================================

# ---------- PUR-001: Request for Quotations ----------

