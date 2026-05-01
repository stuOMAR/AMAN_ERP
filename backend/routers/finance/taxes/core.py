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
from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import require_permission, validate_branch_access, require_module
from utils.audit import log_activity
from utils.fiscal_lock import check_fiscal_period_open
from utils.accounting import generate_sequential_number, get_mapped_account_id, get_base_currency
from schemas.taxes import TaxRateCreate, TaxRateUpdate, TaxGroupCreate, TaxReturnCreate, TaxPaymentCreate

logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')

def _dec(v) -> Decimal:
    return Decimal(str(v or 0))

router = APIRouter()

def _dec(v: Any) -> Decimal:
    return Decimal(str(v or 0))

# ==================== TAX RATES CRUD ====================

@router.post("/settle", dependencies=[Depends(require_permission(["accounting.manage", "taxes.manage"]))], response_model=Dict[str, Any])
def create_tax_settlement(
    request: Request, body: dict,
    current_user: dict = Depends(get_current_user)
):
    """تسوية ضريبية — قيد محاسبي لتسوية رصيد ضريبة المدخلات مع المخرجات"""
    with transactional(current_user.company_id) as db:
        try:
            start = body.get("period_start")
            end = body.get("period_end")
            branch_id = validate_branch_access(current_user, body.get("branch_id"))
    
            if not start or not end:
                raise HTTPException(status_code=400, detail="يجب تحديد فترة التسوية")
    
            params = {"start": start, "end": end}
            branch_filter = ""
            if branch_id:
                branch_filter = "AND i.branch_id = :branch_id"
                params["branch_id"] = branch_id
    
            output = db.execute(text(  # noqa: sql-lint
                f"""
                SELECT COALESCE(SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate * (il.tax_rate / 100)), 0) as vat
                FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
                WHERE i.invoice_type = 'sales' AND i.status NOT IN ('draft','cancelled')
                AND i.invoice_date BETWEEN :start AND :end {branch_filter}
            """), params).scalar() or 0
    
            # T3.6 (audit #18): output VAT must be NET of sales returns; otherwise
            # we settle more than the company actually owes the tax authority.
            output_returns = db.execute(text(  # noqa: sql-lint
                f"""
                SELECT COALESCE(SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate * (il.tax_rate / 100)), 0) as vat
                FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
                WHERE i.invoice_type = 'sales_return' AND i.status NOT IN ('draft','cancelled')
                AND i.invoice_date BETWEEN :start AND :end {branch_filter}
            """), params).scalar() or 0
    
            input_v = db.execute(text(  # noqa: sql-lint
                f"""
                SELECT COALESCE(SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate * (il.tax_rate / 100)), 0) as vat
                FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
                WHERE i.invoice_type = 'purchase' AND i.status NOT IN ('draft','cancelled')
                AND i.invoice_date BETWEEN :start AND :end {branch_filter}
            """), params).scalar() or 0
    
            # T3.6 (audit #18): input VAT must be NET of purchase returns.
            input_returns = db.execute(text(  # noqa: sql-lint
                f"""
                SELECT COALESCE(SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate * (il.tax_rate / 100)), 0) as vat
                FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
                WHERE i.invoice_type = 'purchase_return' AND i.status NOT IN ('draft','cancelled')
                AND i.invoice_date BETWEEN :start AND :end {branch_filter}
            """), params).scalar() or 0
    
            output_dec = (_dec(output) - _dec(output_returns)).quantize(_D2, ROUND_HALF_UP)
            input_dec = (_dec(input_v) - _dec(input_returns)).quantize(_D2, ROUND_HALF_UP)
            net = (output_dec - input_dec).quantize(_D2, ROUND_HALF_UP)
    
            vat_out_id = get_mapped_account_id(db, "acc_map_vat_out")
            vat_in_id = get_mapped_account_id(db, "acc_map_vat_in")
    
            if not vat_out_id or not vat_in_id:
                raise HTTPException(status_code=400, detail="حسابات ضريبة المدخلات/المخرجات غير معينة في الإعدادات")
    
            base_currency = get_base_currency(db)
            settle_amount = min(output_dec, input_dec)
            
            entry_number = None
            if settle_amount > Decimal("0"):
                # Fiscal-period lock: tax settlement posts at today's date.
                check_fiscal_period_open(db, date.today())
    
                je_lines = [
                    {
                        "account_id": vat_out_id, "debit": float(settle_amount), "credit": 0,
                        "description": "تسوية ضريبة المخرجات"
                    },
                    {
                        "account_id": vat_in_id, "debit": 0, "credit": float(settle_amount),
                        "description": "تسوية ضريبة المدخلات مع المخرجات"
                    }
                ]
                
                from services.gl_service import create_journal_entry as gl_create_journal_entry
                je_id, entry_number = gl_create_journal_entry(
                    db=db,
                    company_id=current_user.company_id,
                    date=date.today().isoformat(),
                    description=f"تسوية ضريبية — الفترة {start} إلى {end}",
                    lines=je_lines,
                    user_id=current_user.id,
                    branch_id=branch_id,
                    reference=f"TAX-SETTLE-{start}-{end}",
                    currency=base_currency,
                    exchange_rate=1.0,
                    source="tax_settlement"
                )
    
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="taxes.settlement.create", resource_type="tax_settlement",
                         resource_id=entry_number,
                         details={"period": f"{start} - {end}", "net": float(net), "je": entry_number},
                         request=request)
    
            return {
                "success": True, "message": "تم إنشاء التسوية الضريبية بنجاح",
                "journal_entry": entry_number,
                "output_vat": float(output_dec), "input_vat": float(input_dec),
                "net_amount": float(net),
                "settlement_type": "payable" if net >= Decimal("0") else "refundable"
            }
        except HTTPException:
            raise
        except Exception as e:
            pass
            logger.error(f"Error creating tax settlement: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ==================== BRANCH TAX ANALYSIS ====================

class TaxCalendarCreate(BaseModel):
    title: str
    tax_type: Optional[str] = None
    due_date: date
    reminder_days: Optional[list] = [7, 3, 1]
    is_recurring: Optional[bool] = False
    recurrence_months: Optional[int] = 3
    notes: Optional[str] = None

class TaxCalendarUpdate(BaseModel):
    title: Optional[str] = None
    tax_type: Optional[str] = None
    due_date: Optional[date] = None
    reminder_days: Optional[list] = None
    is_recurring: Optional[bool] = None
    recurrence_months: Optional[int] = None
    is_completed: Optional[bool] = None
    notes: Optional[str] = None


