"""taxes sub-router — split from monolithic taxes.py (T6.3).

Mounted under the parent router via taxes/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pydantic import BaseModel
import logging
import json
from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import branch_scope_filter_from_scope, require_permission, resolve_branch_scope, validate_branch_access, validate_treasury_account_access, require_module
from utils.audit import log_activity
from utils.fiscal_lock import check_fiscal_period_open
from utils.accounting import generate_sequential_number, get_mapped_account_id, get_base_currency
from utils.tax_precision import CALCULATION_VERSION, money_str, require_idempotency_key
from schemas.taxes import TaxRateCreate, TaxRateUpdate, TaxGroupCreate, TaxReturnCreate, TaxPaymentCreate

logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')

def _dec(v) -> Decimal:
    return Decimal(str(v or 0))

router = APIRouter()

from .core import _D2, _D4, _dec

@router.get("/payments", dependencies=[Depends(require_permission(["accounting.view", "taxes.view"]))], response_model=List[Dict[str, Any]])
def list_tax_payments(
    tax_return_id: Optional[int] = None,
    status: Optional[str] = None,
    branch_id: Optional[int] = None,
    year: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """جلب مدفوعات الضرائب مع فلترة حسب الفرع والسنة"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    with transactional(current_user.company_id) as db:
        where = "WHERE 1=1"
        params = {}
        if tax_return_id:
            where += " AND tp.tax_return_id = :return_id"
            params["return_id"] = tax_return_id
        if status:
            where += " AND tp.status = :status"
            params["status"] = status
        where += f" {branch_scope_filter_from_scope(branch_scope, 'tr.branch_id', params)}"
        if year:
            where += " AND EXTRACT(YEAR FROM tp.payment_date) = :year"
            params["year"] = year

        rows = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT tp.*, tr.return_number, tr.tax_period, tr.tax_type,
                   tr.branch_id, tr.jurisdiction_code,
                   b.branch_name,
                   cu.username as created_by_name
            FROM tax_payments tp
            JOIN tax_returns tr ON tp.tax_return_id = tr.id
            LEFT JOIN branches b ON tr.branch_id = b.id
            LEFT JOIN company_users cu ON tp.created_by = cu.id
            {where}
            ORDER BY tp.payment_date DESC
        """), params).fetchall()

        result = []
        for r in rows:
            item = dict(r._mapping)
            if "amount" in item:
                item["amount"] = money_str(item["amount"])
            result.append(item)
        return result


@router.post("/payments", status_code=201, dependencies=[Depends(require_permission(["accounting.edit", "taxes.manage"]))], response_model=Dict[str, Any])
def create_tax_payment(
    request: Request,
    data: TaxPaymentCreate,
    current_user: dict = Depends(get_current_user)
):
    """تسجيل دفعة ضريبية مع قيد محاسبي تلقائي"""
    with transactional(current_user.company_id) as db:
        try:
            idempotency_key = require_idempotency_key(
                request,
                operation="tax payment",
            )
            existing_by_key = db.execute(text("""
                SELECT id, payment_number, journal_entry_id
                FROM tax_payments
                WHERE idempotency_key = :key
                LIMIT 1
            """), {"key": idempotency_key}).fetchone()
            if existing_by_key:
                return {
                    "success": True,
                    "id": existing_by_key.id,
                    "payment_number": existing_by_key.payment_number,
                    "journal_entry_id": existing_by_key.journal_entry_id,
                    "message": "تم العثور على الدفعة الضريبية نفسها مسبقاً",
                    "idempotent": True,
                }

            tr = db.execute(text("SELECT * FROM tax_returns WHERE id = :id FOR UPDATE"), {"id": data.tax_return_id}).fetchone()
            if not tr:
                raise HTTPException(**http_error(404, "tax_return_not_found"))
            branch_id = validate_branch_access(current_user, tr.branch_id)
            if tr.status in ("cancelled", "draft"):
                raise HTTPException(status_code=400, detail="لا يمكن الدفع على إقرار ملغى أو مسودة. يجب تقديمه أولاً")

            check_fiscal_period_open(db, data.payment_date)
    
            paid = db.execute(text(
                "SELECT COALESCE(SUM(amount), 0) FROM tax_payments WHERE tax_return_id = :id AND status = 'confirmed'"
            ), {"id": data.tax_return_id}).scalar()
            remaining = (_dec(tr.total_amount) - _dec(paid)).quantize(_D2, ROUND_HALF_UP)
            amount_dec = _dec(data.amount).quantize(_D2, ROUND_HALF_UP)
            if amount_dec > (remaining + _D2):
                raise HTTPException(status_code=400, detail=f"المبلغ يتجاوز المتبقي ({money_str(remaining)})")
    
            payment_number = generate_sequential_number(db, "TP", "tax_payments", "payment_number")
            base_currency = get_base_currency(db)
            payment_currency = str(getattr(tr, "currency", None) or getattr(tr, "base_currency", None) or base_currency).upper()
            calc_details = {
                "version": CALCULATION_VERSION,
                "tax_return_id": data.tax_return_id,
                "return_number": tr.return_number,
                "amount": money_str(amount_dec),
                "remaining_before": money_str(remaining),
                "branch_id": branch_id,
            }
    
            result = db.execute(text("""
                INSERT INTO tax_payments (payment_number, tax_return_id, payment_date, amount,
                                          payment_method, reference, status, notes, created_by,
                                          branch_id, treasury_account_id, currency, base_currency,
                                          exchange_rate, idempotency_key, calculation_version,
                                          calculation_details)
                VALUES (:num, :return_id, :date, :amount, :method, :ref, 'confirmed', :notes, :user,
                        :branch_id, :treasury_account_id, :currency, :base_currency,
                        1, :idempotency_key, :calc_version, CAST(:calc_details AS jsonb))
                RETURNING id
            """), {
                "num": payment_number, "return_id": data.tax_return_id,
                "date": data.payment_date, "amount": amount_dec,
                "method": data.payment_method, "ref": data.reference,
                "notes": data.notes, "user": current_user.id,
                "branch_id": branch_id,
                "treasury_account_id": data.treasury_account_id,
                "currency": payment_currency,
                "base_currency": base_currency,
                "idempotency_key": idempotency_key,
                "calc_version": CALCULATION_VERSION,
                "calc_details": json.dumps(calc_details),
            })
            new_id = result.fetchone()[0]
    
            # ===== ACCOUNTING INTEGRATION =====
            vat_account_id = get_mapped_account_id(db, "acc_map_vat_out")
            if not vat_account_id:
                raise HTTPException(status_code=400, detail="حساب ضريبة المخرجات (VAT Output) غير محدد في الإعدادات")
    
            bank_account_id = None
            if data.treasury_account_id:
                bank_row = validate_treasury_account_access(
                    db, current_user, data.treasury_account_id, branch_id
                )
                bank_account_id = bank_row.get("gl_account_id")
    
            if not bank_account_id:
                if branch_id:
                    bank_row = db.execute(text(
                        """
                        SELECT gl_account_id
                        FROM treasury_accounts
                        WHERE is_active = true
                          AND gl_account_id IS NOT NULL
                          AND branch_id = :branch_id
                        LIMIT 1
                        """
                    ), {"branch_id": branch_id}).fetchone()
                else:
                    bank_row = db.execute(text(
                        "SELECT gl_account_id FROM treasury_accounts WHERE is_active = true AND gl_account_id IS NOT NULL LIMIT 1"
                    )).fetchone()
                if bank_row:
                    bank_account_id = bank_row.gl_account_id
    
            if not bank_account_id:
                raise HTTPException(status_code=400, detail="حساب البنك/الخزينة غير مهيأ لترحيل دفعة الضريبة")

            je_lines = [
                {
                    "account_id": vat_account_id, "debit": amount_dec, "credit": Decimal("0"),
                    "description": f"دفع ضريبة — {tr.tax_period}"
                },
                {
                    "account_id": bank_account_id, "debit": Decimal("0"), "credit": amount_dec,
                    "description": f"دفع ضريبة — {tr.tax_period}"
                }
            ]

            from services.gl_service import create_journal_entry as gl_create_journal_entry
            je_id, entry_number = gl_create_journal_entry(
                db=db,
                company_id=current_user.company_id,
                date=data.payment_date,
                description=f"دفع ضريبة — إقرار {tr.return_number} — فترة {tr.tax_period}",
                lines=je_lines,
                user_id=current_user.id,
                branch_id=branch_id,
                reference=payment_number,
                currency=base_currency,
                exchange_rate=Decimal("1"),
                source="tax_payment",
                source_id=new_id,
                idempotency_key=f"tax-payment-je:{idempotency_key}",
            )
            db.execute(text(
                "UPDATE tax_payments SET journal_entry_id = :jeid, updated_at = CURRENT_TIMESTAMP WHERE id = :id"
            ), {"jeid": je_id, "id": new_id})
    
            # Update return status if fully paid
            new_paid = (_dec(paid) + amount_dec).quantize(_D2, ROUND_HALF_UP)
            if new_paid >= (_dec(tr.total_amount).quantize(_D2, ROUND_HALF_UP) - _D2):
                db.execute(text("UPDATE tax_returns SET status = 'paid', updated_at = CURRENT_TIMESTAMP WHERE id = :id"), {"id": data.tax_return_id})
    
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="taxes.payment.create", resource_type="tax_payment",
                         resource_id=str(new_id),
                         details={"payment_number": payment_number, "amount": money_str(amount_dec), "return": tr.return_number},
                         request=request)
    
            return {"success": True, "id": new_id, "payment_number": payment_number,
                    "journal_entry_id": je_id, "journal_entry": entry_number,
                    "message": "تم تسجيل الدفعة الضريبية بنجاح"}
        except HTTPException:
            raise
        except Exception as e:
            pass
            logger.error(f"Error creating tax payment: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ==================== VAT REPORT ====================
