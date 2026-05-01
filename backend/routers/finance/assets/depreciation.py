"""assets sub-router — split from monolithic assets.py (T6.3).

Mounted under the parent router via assets/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pydantic import BaseModel
import logging
from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import require_permission, validate_branch_access, require_module
from utils.accounting import get_mapped_account_id
from utils.fiscal_lock import check_fiscal_period_open
from schemas.assets import (
    AssetCreate, AssetUpdate, AssetDisposal, LeasePaymentCreate,
    AssetTransferCreate, AssetRevaluationCreate, MaintenanceComplete,
    LeaseContractCreate, DecliningBalanceInput, UnitsOfProductionInput,
    InsuranceCreate, MaintenanceCreate, AssetQRUpdate, ImpairmentTestInput,
)

logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')

def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')

router = APIRouter()

from .core import DepreciationRunInput, _D2, _D4, _dec

@router.post("/run-depreciation", dependencies=[Depends(require_permission("assets.manage"))], response_model=Dict[str, Any])
def run_depreciation(
    body: Optional[DepreciationRunInput] = None,
    current_user: dict = Depends(get_current_user),
):
    """ترحيل استهلاك الأصول إلى دفتر الأستاذ (قيود تلقائية).

    - لكل سطر في asset_depreciation_schedule غير مرحَّل (posted=false)
      بتاريخ <= through_date (الافتراضي: اليوم) يُنشأ قيد متوازن:
        مدين : مصروف الإهلاك
        دائن : مجمع الإهلاك
    - مُحصَّن من التكرار عبر idempotency_key = dep-sched-{id}.
    """
    body = body or DepreciationRunInput()
    cutoff = body.through_date or date.today()
    conn = get_db_connection(current_user.company_id)
    try:
        from services.gl_service import create_journal_entry as gl_create_journal_entry
        from utils.accounting import get_base_currency

        settings_res = conn.execute(text(
            "SELECT setting_key, setting_value FROM company_settings "
            "WHERE setting_key IN ('acc_map_depr_exp', 'acc_map_acc_depr')"
        )).fetchall()
        s = {r.setting_key: r.setting_value for r in settings_res}
        dep_exp_acc = s.get('acc_map_depr_exp')
        acc_dep_acc = s.get('acc_map_acc_depr')
        if not dep_exp_acc or not acc_dep_acc:
            raise HTTPException(status_code=400, detail="لم يتم ربط حسابات الإهلاك (acc_map_depr_exp / acc_map_acc_depr)")

        params: Dict[str, Any] = {"cutoff": cutoff.isoformat()}
        asset_filter = ""
        if body.asset_id:
            asset_filter = " AND s.asset_id = :aid"
            params["aid"] = body.asset_id

        rows = conn.execute(text(f"""
            SELECT s.id, s.asset_id, s.fiscal_year, s.date, s.amount, a.code, a.name, a.currency, a.branch_id
            FROM asset_depreciation_schedule s
            JOIN assets a ON a.id = s.asset_id
            WHERE s.posted = FALSE
              AND s.date <= :cutoff
              AND a.status != 'disposed'
              AND COALESCE(s.amount, 0) > 0
              {asset_filter}
            ORDER BY s.date ASC, s.asset_id ASC
        """), params).fetchall()

        if not rows:
            return {"posted_count": 0, "total_amount": 0.0, "message": "لا توجد سطور إهلاك بحاجة للترحيل"}

        base_currency = get_base_currency(conn)
        posted_count = 0
        total_amount = Decimal("0")
        posted_ids: List[int] = []

        for r in rows:
            amount = _dec(r.amount).quantize(_D2, ROUND_HALF_UP)
            if amount <= 0:
                continue
            check_fiscal_period_open(conn, r.date)
            je_id, _ = gl_create_journal_entry(
                db=conn,
                company_id=current_user.company_id,
                date=r.date.isoformat() if hasattr(r.date, "isoformat") else str(r.date),
                description=f"Depreciation — {r.code} ({r.name}) FY{r.fiscal_year}",
                lines=[
                    {"account_id": int(dep_exp_acc), "debit": amount, "credit": 0,
                     "description": f"Depr. Expense — {r.code}"},
                    {"account_id": int(acc_dep_acc), "debit": 0, "credit": amount,
                     "description": f"Accum. Depr. — {r.code}"},
                ],
                user_id=current_user.id,
                branch_id=r.branch_id,
                reference=f"{r.code}-FY{r.fiscal_year}",
                status="posted",
                currency=r.currency or base_currency,
                source="AssetDepreciation",
                source_id=r.id,
                username=getattr(current_user, "username", None),
                idempotency_key=f"dep-sched-{r.id}",
            )
            conn.execute(text(
                "UPDATE asset_depreciation_schedule "
                "SET posted = TRUE, journal_entry_id = :je, updated_at = NOW() "
                "WHERE id = :id"
            ), {"je": je_id, "id": r.id})
            posted_ids.append(r.id)
            posted_count += 1
            total_amount += amount

        conn.commit()
        return {
            "posted_count": posted_count,
            "total_amount": float(total_amount.quantize(_D2, ROUND_HALF_UP)),
            "schedule_ids": posted_ids,
            "through_date": cutoff.isoformat(),
            "message": f"تم ترحيل {posted_count} سطر إهلاك بإجمالي {total_amount}",
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        # SEC-T2.10: do not leak internal exception text to the client.
        logger.exception("Depreciation run failed")
        raise HTTPException(status_code=500, detail="تعذّر ترحيل الإهلاك")
    finally:
        conn.close()


@router.post("/{asset_id}/depreciate/{schedule_id}", dependencies=[Depends(require_permission("assets.manage"))], response_model=Dict[str, Any])
def post_depreciation(asset_id: int, schedule_id: int, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection(current_user.company_id)
    trans = conn.begin()
    try:
        from utils.accounting import get_base_currency
        base_currency = get_base_currency(conn)
        # Verify schedule item
        item = conn.execute(text("""
            SELECT * FROM asset_depreciation_schedule 
            WHERE id = :sid AND asset_id = :aid AND posted = FALSE
        """), {"sid": schedule_id, "aid": asset_id}).fetchone()
        
        if not item:
            raise HTTPException(status_code=400, detail="Schedule item not found or already posted")
            
        # Get Asset info for name/code
        asset = conn.execute(text("SELECT * FROM assets WHERE id = :id"), {"id": asset_id}).fetchone()
            
        # Create Journal Entry
        # Dr Depreciation Expense (5210)
        # Cr Accumulated Depreciation (1519)
        # We need to find these Account IDs. For now assuming they exist or using placeholders.
        # Ideally, we should fetch them from chart of accounts based on code.

        check_fiscal_period_open(conn, item.date)
        # Use Dynamic Mappings for Depreciation
        exp_acc_id = get_mapped_account_id(conn, "acc_map_depr_exp")
        acc_depr_id = get_mapped_account_id(conn, "acc_map_acc_depr")
        
        if not exp_acc_id or not acc_depr_id:
             raise HTTPException(status_code=400, detail="Depreciation accounts (mapped roles: acc_map_depr_exp, acc_map_acc_depr) not found.")

        # Create Header
        je_lines = [
            {
                "account_id": exp_acc_id, "debit": _dec(item.amount).quantize(_D2, ROUND_HALF_UP), "credit": 0,
                "description": "Depreciation Expense"
            },
            {
                "account_id": acc_depr_id, "debit": 0, "credit": _dec(item.amount).quantize(_D2, ROUND_HALF_UP),
                "description": "Accumulated Depreciation"
            }
        ]
        
        from services.gl_service import create_journal_entry as gl_create_journal_entry
        je_id, entry_number = gl_create_journal_entry(
            db=conn,
            company_id=current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id,
            date=item.date,
            description=f"Depreciation for asset {asset.name} ({asset.code}) - {item.fiscal_year}",
            lines=je_lines,
            user_id=current_user.get("id") if isinstance(current_user, dict) else current_user.id,
            branch_id=asset.branch_id,
            reference=f"DEPR-{asset.code}-{item.fiscal_year}",
            currency=asset.currency or base_currency,
            exchange_rate=Decimal("1"),
            source="asset_depreciation",
            source_id=schedule_id
        )

        # Update Account Balances handled by gl_service

        # Update Schedule
        conn.execute(text("UPDATE asset_depreciation_schedule SET posted = TRUE, journal_entry_id = :jid WHERE id = :sid"), 
                     {"jid": je_id, "sid": schedule_id})
                     
        trans.commit()
        return {"message": "Depreciation posted successfully", "journal_entry_id": je_id}
        
    except HTTPException:
        trans.rollback()
        raise
    except Exception:
        trans.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        conn.close()
@router.post("/{asset_id}/depreciation/declining-balance", dependencies=[Depends(require_permission("assets.create"))], response_model=Dict[str, Any])
def calc_declining_balance(asset_id: int, data: DecliningBalanceInput = DecliningBalanceInput(), current_user: dict = Depends(get_current_user)):
    """Calculate Declining Balance depreciation schedule."""
    with transactional(current_user.company_id) as conn:
        asset = conn.execute(text("SELECT * FROM assets WHERE id = :id"), {"id": asset_id}).fetchone()
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")
        cost = _dec(asset.cost)
        residual = _dec(asset.residual_value or 0)
        life = int(asset.life_years or 5)
        rate = _dec(data.rate if data.rate is not None else Decimal('2') / _dec(life))  # Double declining by default
        schedule = []
        book_value = cost
        for year in range(1, life + 1):
            dep = (book_value * rate).quantize(_D2, ROUND_HALF_UP)
            if book_value - dep < residual:
                dep = (book_value - residual).quantize(_D2, ROUND_HALF_UP)
            book_value -= dep
            schedule.append({"year": year, "depreciation": float(dep), "book_value": float(book_value.quantize(_D2, ROUND_HALF_UP))})
            if book_value <= residual:
                break
        return {"asset_id": asset_id, "method": "declining_balance", "rate": float(rate), "schedule": schedule}


@router.post("/{asset_id}/depreciation/units-of-production", dependencies=[Depends(require_permission("assets.create"))], response_model=Dict[str, Any])
def calc_units_of_production(asset_id: int, data: UnitsOfProductionInput, current_user: dict = Depends(get_current_user)):
    """Depreciation based on units produced."""
    with transactional(current_user.company_id) as conn:
        asset = conn.execute(text("SELECT * FROM assets WHERE id = :id"), {"id": asset_id}).fetchone()
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")
        cost = _dec(asset.cost)
        residual = _dec(asset.residual_value or 0)
        total_units = _dec(data.total_units if data.total_units is not None else (asset.total_units or 1))
        units_used = _dec(data.units_used)
        dep_per_unit = (cost - residual) / total_units
        depreciation = (dep_per_unit * units_used).quantize(_D2, ROUND_HALF_UP)
        # Update used units
        conn.execute(text("UPDATE assets SET used_units = COALESCE(used_units,0) + :u WHERE id = :id"),
                     {"u": units_used, "id": asset_id})
        return {
            "asset_id": asset_id, "method": "units_of_production",
            "dep_per_unit": float(dep_per_unit.quantize(_D4, ROUND_HALF_UP)),
            "units_used": float(units_used), "depreciation": float(depreciation),
        }


@router.post("/{asset_id}/depreciation/sum-of-years", dependencies=[Depends(require_permission("assets.create"))], response_model=Dict[str, Any])
def calc_sum_of_years_digits(asset_id: int, current_user: dict = Depends(get_current_user)):
    """Sum of Years' Digits depreciation schedule."""
    with transactional(current_user.company_id) as conn:
        asset = conn.execute(text("SELECT * FROM assets WHERE id = :id"), {"id": asset_id}).fetchone()
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")
        cost = _dec(asset.cost)
        residual = _dec(asset.residual_value or 0)
        life = int(asset.life_years or 5)
        depreciable = cost - residual
        syd = _dec(life * (life + 1)) / Decimal('2')
        schedule = []
        for year in range(1, life + 1):
            fraction = _dec(life - year + 1) / syd
            dep = (depreciable * fraction).quantize(_D2, ROUND_HALF_UP)
            schedule.append({"year": year, "fraction": float(fraction.quantize(_D4, ROUND_HALF_UP)), "depreciation": float(dep)})
        return {"asset_id": asset_id, "method": "sum_of_years_digits", "schedule": schedule}




# ---------- ASSET-004: Insurance & Maintenance ----------

