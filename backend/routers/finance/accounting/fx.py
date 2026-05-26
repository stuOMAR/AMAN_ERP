"""accounting sub-router — split from monolithic accounting.py (T6.3).

Mounted under the parent router via accounting/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error, i18n_message
from typing import Any, Dict
from sqlalchemy import text
from database import get_db_connection
from routers.auth import get_current_user
import logging
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from utils.permissions import require_permission, validate_branch_access
from utils.audit import log_activity
from utils.accounting import get_base_currency
from services.gl_service import create_journal_entry as gl_create_journal_entry
from utils.fiscal_lock import check_fiscal_period_open
from utils.limiter import limiter

logger = logging.getLogger(__name__)
_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')

def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')

router = APIRouter()

from .core import FXRevaluationRequest, _D2, _dec  # noqa: E402

@router.post("/fx-revaluation", dependencies=[Depends(require_permission("accounting.manage"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
def fx_revaluation(request: Request, req: FXRevaluationRequest, current_user: dict = Depends(get_current_user)):
    """إعادة تقييم أرصدة العملات الأجنبية — الفروقات تسجل كربح/خسارة غير محققة"""
    branch_id = validate_branch_access(current_user, req.branch_id)
    db = get_db_connection(current_user.company_id)
    trans = db.begin()
    try:
        base_currency = get_base_currency(db)

        # Fiscal-period lock: FX revaluation posts at today's date.
        check_fiscal_period_open(db, date.today())

        # Find unrealized FX gain/loss accounts
        gain_acc = db.execute(text("SELECT id FROM accounts WHERE account_number = '4202'")).fetchone()
        loss_acc = db.execute(text("SELECT id FROM accounts WHERE account_number = '5403'")).fetchone()
        ufx_gain = gain_acc.id if gain_acc else None
        ufx_loss = loss_acc.id if loss_acc else None
        if not ufx_gain and not ufx_loss:
            raise HTTPException(**http_error(400, "fx_accounts_not_found", request))

        # Find all accounts with balances in this currency
        balances = db.execute(text("""
            SELECT jl.account_id, a.account_number, a.name,
                   SUM(CASE WHEN jl.debit > 0 THEN jl.amount_currency
                            ELSE -jl.amount_currency END) as fc_balance,
                   SUM(jl.debit - jl.credit) as base_balance
            FROM journal_lines jl
            JOIN journal_entries je ON jl.journal_entry_id = je.id
            JOIN accounts a ON jl.account_id = a.id
            WHERE jl.currency = :curr AND je.status = 'posted'
                  AND a.account_type IN ('asset', 'liability')
            GROUP BY jl.account_id, a.account_number, a.name
            HAVING SUM(CASE WHEN jl.debit > 0 THEN jl.amount_currency
                            ELSE -jl.amount_currency END) != 0
        """), {"curr": req.currency_code}).fetchall()

        if not balances:
            return {"success": True, "message": i18n_message("no_balances_with_currency", request), "adjustments": []}

        adjustments = []
        total_diff = Decimal("0")
        je_lines = []

        new_rate = _dec(req.new_rate)

        for bal in balances:
            m = bal._mapping
            fc = _dec(m["fc_balance"])
            old_base = _dec(m["base_balance"])
            new_base = (fc * new_rate).quantize(_D2, ROUND_HALF_UP)
            diff = (new_base - old_base).quantize(_D2, ROUND_HALF_UP)
            if diff.copy_abs() < _D2:
                continue

            total_diff += diff
            if diff > 0:
                je_lines.append({
                    "account_id": m["account_id"],
                    "debit": abs(diff),
                    "credit": 0,
                    "description": f"تعديل سعر {req.currency_code}",
                    "amount_currency": 0,
                    "currency": base_currency,
                })
            else:
                je_lines.append({
                    "account_id": m["account_id"],
                    "debit": 0,
                    "credit": abs(diff),
                    "description": f"تعديل سعر {req.currency_code}",
                    "amount_currency": 0,
                    "currency": base_currency,
                })

            adjustments.append({
                "account_id": m["account_id"], "account_number": m["account_number"], "name": m["name"],
                "fc_balance": str(fc.quantize(_D2, ROUND_HALF_UP)),
                "old_base": str(old_base.quantize(_D2, ROUND_HALF_UP)),
                "new_base": str(new_base.quantize(_D2, ROUND_HALF_UP)),
                "difference": str(diff.quantize(_D2, ROUND_HALF_UP)),
            })

        # Post the offsetting FX gain/loss
        if total_diff > 0 and ufx_gain:
            je_lines.append({
                "account_id": ufx_gain,
                "debit": 0,
                "credit": abs(total_diff),
                "description": "أرباح فروقات عملة (غير محققة)",
                "amount_currency": 0,
                "currency": base_currency,
            })
        elif total_diff < 0 and ufx_loss:
            je_lines.append({
                "account_id": ufx_loss,
                "debit": abs(total_diff),
                "credit": 0,
                "description": "خسائر فروقات عملة (غير محققة)",
                "amount_currency": 0,
                "currency": base_currency,
            })

        je_num = None
        if je_lines:
            _, je_num = gl_create_journal_entry(
                db=db,
                company_id=current_user.company_id,
                date=str(date.today()),
                description=f"إعادة تقييم عملة {req.currency_code} بسعر {req.new_rate}",
                lines=je_lines,
                user_id=current_user.id,
                branch_id=branch_id,
                reference=f"FX-REVAL-{req.currency_code}",
                currency=base_currency,
                exchange_rate=1,
                source="fx_revaluation",
            )

        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="accounting.fx_revaluation",
                     resource_type="fx_revaluation", resource_id=str(je_num),
                     details={"currency": req.currency_code, "new_rate": req.new_rate,
                              "adjustments_count": len(adjustments)})
        trans.commit()
        return {
            "success": True, "journal_entry": je_num,
            "currency": req.currency_code, "new_rate": req.new_rate,
            "total_adjustment": str(total_diff.quantize(_D2, ROUND_HALF_UP)),
            "adjustments": adjustments,
        }
    except HTTPException:
        trans.rollback()
        raise
    except Exception:
        trans.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
