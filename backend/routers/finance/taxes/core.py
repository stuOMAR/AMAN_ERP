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
from utils.permissions import branch_scope_filter_from_scope, require_permission, resolve_branch_scope, require_module
from utils.audit import log_activity
from utils.fiscal_lock import check_fiscal_period_open
from utils.accounting import generate_sequential_number, get_mapped_account_id, get_base_currency
from utils.currency_display import display_currency_fields, resolve_display_currency
from utils.tax_precision import get_idempotency_key, money_str
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
            branch_scope = resolve_branch_scope(current_user, body.get("branch_id"))
            branch_id = branch_scope["branch_id"]
            idempotency_key = get_idempotency_key(
                request,
                fallback=f"tax-settlement:{start}:{end}:branch:{branch_id or 'all'}",
            )
    
            if not start or not end:
                raise HTTPException(**http_error(400, "settlement_period_required", request))
    
            display_meta = resolve_display_currency(db, branch_scope)
            params = {"start": start, "end": end}
            branch_filter = branch_scope_filter_from_scope(branch_scope, "i.branch_id", params)

            def lock_invoice_vat_rows(invoice_type: str) -> None:
                row_params = {**params, "invoice_type": invoice_type}
                db.execute(text(  # noqa: sql-lint
                    f"""
                    SELECT i.id
                    FROM invoices i
                    WHERE i.invoice_type = :invoice_type
                      AND i.status NOT IN ('draft','cancelled')
                      AND i.invoice_date BETWEEN :start AND :end
                      {branch_filter}
                    FOR UPDATE
                """), row_params).fetchall()

            def invoice_vat(invoice_type: str) -> Decimal:
                row_params = {**params, "invoice_type": invoice_type}
                return _dec(db.execute(text(  # noqa: sql-lint
                    f"""
                    SELECT COALESCE(SUM(COALESCE(i.tax_amount, 0) * COALESCE(i.exchange_rate, 1)), 0) as vat
                    FROM invoices i
                    WHERE i.invoice_type = :invoice_type
                      AND i.status NOT IN ('draft','cancelled')
                      AND i.invoice_date BETWEEN :start AND :end
                      {branch_filter}
                """), row_params).scalar() or 0)

            for invoice_type in ("sales", "sales_return", "purchase", "purchase_return"):
                lock_invoice_vat_rows(invoice_type)

            output = invoice_vat("sales")
    
            # T3.6 (audit #18): output VAT must be NET of sales returns; otherwise
            # we settle more than the company actually owes the tax authority.
            output_returns = invoice_vat("sales_return")

            input_v = invoice_vat("purchase")
    
            # T3.6 (audit #18): input VAT must be NET of purchase returns.
            input_returns = invoice_vat("purchase_return")
    
            output_dec = (_dec(output) - _dec(output_returns)).quantize(_D2, ROUND_HALF_UP)
            input_dec = (_dec(input_v) - _dec(input_returns)).quantize(_D2, ROUND_HALF_UP)
            net = (output_dec - input_dec).quantize(_D2, ROUND_HALF_UP)
    
            vat_out_id = get_mapped_account_id(db, "acc_map_vat_out")
            vat_in_id = get_mapped_account_id(db, "acc_map_vat_in")
    
            if not vat_out_id or not vat_in_id:
                raise HTTPException(**http_error(400, "input_output_tax_accounts_not_configured", request))
    
            base_currency = get_base_currency(db)
            settle_amount = min(output_dec, input_dec)
            
            entry_number = None
            if settle_amount > Decimal("0"):
                # Fiscal-period lock: tax settlement posts at today's date.
                check_fiscal_period_open(db, date.today())
    
                je_lines = [
                    {
                        "account_id": vat_out_id, "debit": settle_amount, "credit": Decimal("0"),
                        "description": "تسوية ضريبة المخرجات"
                    },
                    {
                        "account_id": vat_in_id, "debit": Decimal("0"), "credit": settle_amount,
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
                    exchange_rate=Decimal("1"),
                    source="tax_settlement",
                    idempotency_key=f"tax-settlement-je:{idempotency_key}",
                )
    
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="taxes.settlement.create", resource_type="tax_settlement",
                         resource_id=entry_number,
                         details={"period": f"{start} - {end}", "net": money_str(net), "je": entry_number},
                         request=request)
    
            return {
                **display_currency_fields(display_meta),
                "success": True, "message": i18n_message("tax_settlement_created_success", request),
                "journal_entry": entry_number,
                "output_vat": money_str(output_dec), "input_vat": money_str(input_dec),
                "net_amount": money_str(net),
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
    branch_id: Optional[int] = None
    due_date: date
    reminder_days: Optional[list] = [7, 3, 1]
    is_recurring: Optional[bool] = False
    recurrence_months: Optional[int] = 3
    notes: Optional[str] = None

class TaxCalendarUpdate(BaseModel):
    title: Optional[str] = None
    tax_type: Optional[str] = None
    branch_id: Optional[int] = None
    due_date: Optional[date] = None
    reminder_days: Optional[list] = None
    is_recurring: Optional[bool] = None
    recurrence_months: Optional[int] = None
    is_completed: Optional[bool] = None
    notes: Optional[str] = None
