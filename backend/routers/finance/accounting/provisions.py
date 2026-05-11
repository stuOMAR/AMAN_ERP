"""accounting sub-router — split from monolithic accounting.py (T6.3).

Mounted under the parent router via accounting/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Body, Request
from utils.i18n import http_error
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from sqlalchemy import text
from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
import logging
from datetime import date
from dateutil.relativedelta import relativedelta
from utils.cache import invalidate_company_cache
from decimal import Decimal, ROUND_HALF_UP
from utils.permissions import require_permission, validate_branch_access
from utils.audit import log_activity
from utils.accounting import get_base_currency
from services.gl_service import create_journal_entry as gl_create_journal_entry
from utils.fiscal_lock import check_fiscal_period_open
from schemas.accounting import AccountCreate, AccountUpdate, FiscalYearCreate, FiscalYearClose, FiscalYearReopen
from utils.cache import cache
from utils.limiter import limiter

logger = logging.getLogger(__name__)
_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')

def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')

router = APIRouter()

from .core import ProvisionRequest, _D2, _D4, _dec

@router.post("/provisions/bad-debt", dependencies=[Depends(require_permission("accounting.manage"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
def create_bad_debt_provision(request: Request, req: ProvisionRequest, current_user: dict = Depends(get_current_user)):
    """إنشاء قيد مخصص ديون معدومة — Dr مصروف ديون معدومة / Cr مخصص الديون المعدومة"""
    from utils.accounting import get_mapped_account_id, get_base_currency
    branch_id = validate_branch_access(current_user, req.branch_id)
    db = get_db_connection(current_user.company_id)
    trans = db.begin()
    try:
        base_currency = get_base_currency(db)
        acc_bad_debt_exp = get_mapped_account_id(db, "acc_map_bad_debt_expense")
        acc_prov_doubtful = get_mapped_account_id(db, "acc_map_provision_doubtful")
        if not acc_bad_debt_exp or not acc_prov_doubtful:
            raise HTTPException(**http_error(400, "bad_debt_accounts_not_configured", request))

        # Fiscal-period lock: provisions post at today's date.
        check_fiscal_period_open(db, date.today())

        desc = req.description or "مخصص ديون معدومة"
        _, je_num = gl_create_journal_entry(
            db=db,
            company_id=current_user.company_id,
            date=str(date.today()),
            description=desc,
            lines=[
                {
                    "account_id": acc_bad_debt_exp,
                    "debit": _dec(req.amount),
                    "credit": 0,
                    "description": "مصروف ديون معدومة",
                    "amount_currency": _dec(req.amount),
                    "currency": base_currency,
                },
                {
                    "account_id": acc_prov_doubtful,
                    "debit": 0,
                    "credit": _dec(req.amount),
                    "description": "مخصص الديون المعدومة",
                    "amount_currency": _dec(req.amount),
                    "currency": base_currency,
                },
            ],
            user_id=current_user.id,
            branch_id=branch_id,
            reference="BAD-DEBT-PROV",
            currency=base_currency,
            exchange_rate=1,
            source="bad_debt_provision",
        )

        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="accounting.provision.bad_debt",
                     resource_type="provision", resource_id=str(je_num),
                     details={"amount": float(req.amount)})
        trans.commit()
        return {"success": True, "journal_entry": je_num, "amount": req.amount}
    except HTTPException:
        trans.rollback()
        raise
    except Exception:
        trans.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
# ═══════════════════════════════════════════════════════════
# GL-005: Leave Provision (مخصص إجازات)
# ═══════════════════════════════════════════════════════════

@router.post("/provisions/leave", dependencies=[Depends(require_permission("accounting.manage"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
def create_leave_provision(request: Request, req: ProvisionRequest, current_user: dict = Depends(get_current_user)):
    """إنشاء قيد مخصص إجازات — Dr مصروف إجازات / Cr مخصص الإجازات"""
    from utils.accounting import get_mapped_account_id, get_base_currency
    branch_id = validate_branch_access(current_user, req.branch_id)
    db = get_db_connection(current_user.company_id)
    trans = db.begin()
    try:
        base_currency = get_base_currency(db)
        acc_leave_exp = get_mapped_account_id(db, "acc_map_leave_expense")
        acc_leave_prov = get_mapped_account_id(db, "acc_map_provision_holiday")
        if not acc_leave_exp or not acc_leave_prov:
            raise HTTPException(**http_error(400, "leave_accounts_not_configured", request))

        # Fiscal-period lock: provisions post at today's date.
        check_fiscal_period_open(db, date.today())

        desc = req.description or "مخصص إجازات الموظفين"
        _, je_num = gl_create_journal_entry(
            db=db,
            company_id=current_user.company_id,
            date=str(date.today()),
            description=desc,
            lines=[
                {
                    "account_id": acc_leave_exp,
                    "debit": _dec(req.amount),
                    "credit": 0,
                    "description": "مصروف الإجازات",
                    "amount_currency": _dec(req.amount),
                    "currency": base_currency,
                },
                {
                    "account_id": acc_leave_prov,
                    "debit": 0,
                    "credit": _dec(req.amount),
                    "description": "مخصص الإجازات",
                    "amount_currency": _dec(req.amount),
                    "currency": base_currency,
                },
            ],
            user_id=current_user.id,
            branch_id=branch_id,
            reference="LEAVE-PROV",
            currency=base_currency,
            exchange_rate=1,
            source="leave_provision",
        )

        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="accounting.provision.leave",
                     resource_type="provision", resource_id=str(je_num),
                     details={"amount": float(req.amount)})
        trans.commit()
        return {"success": True, "journal_entry": je_num, "amount": req.amount}
    except HTTPException:
        trans.rollback()
        raise
    except Exception:
        trans.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
# ═══════════════════════════════════════════════════════════
# GL-006: FX Revaluation (تسوية العملات الأجنبية)
# ═══════════════════════════════════════════════════════════

