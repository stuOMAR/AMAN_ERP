"""assets sub-router — split from monolithic assets.py (T6.3).

Mounted under the parent router via assets/__init__.py.
"""
from fastapi import Request, APIRouter, Depends, HTTPException
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

from .core import AssetRevaluation, _D2, _D4, _dec

@router.get("/revaluations", dependencies=[Depends(require_permission("assets.view"))], response_model=List[Dict[str, Any]])
def list_revaluations(asset_id: Optional[int] = None, branch_id: Optional[int] = None, current_user: dict = Depends(get_current_user)):
    """List Revaluations."""
    with transactional(current_user.company_id) as conn:
        q = """
            SELECT r.* FROM asset_revaluations r
            JOIN assets a ON r.asset_id = a.id
            WHERE 1=1
        """
        params = {}
        if asset_id:
            q += " AND r.asset_id = :aid"
            params["aid"] = asset_id
        if branch_id:
            q += " AND a.branch_id = :branch_id"
            params["branch_id"] = branch_id
        q += " ORDER BY r.revaluation_date DESC"
        rows = conn.execute(text(q), params).fetchall()
        return [dict(r._mapping) for r in rows]


@router.post("/revaluations", dependencies=[Depends(require_permission("assets.create"))], response_model=Dict[str, Any])
def create_revaluation(request: Request, data: AssetRevaluationCreate, current_user: dict = Depends(get_current_user)):
    """Create Revaluation."""
    with transactional(current_user.company_id) as conn:
        try:
            asset = conn.execute(text("SELECT * FROM assets WHERE id = :id"), {"id": data.asset_id}).fetchone()
            if not asset:
                raise HTTPException(**http_error(404, "asset_not_found", request))
            dep_sum = conn.execute(text(
                "SELECT COALESCE(SUM(amount),0) FROM asset_depreciation_schedule WHERE asset_id = :id AND posted = true"
            ), {"id": data.asset_id}).scalar()
            old_value = (_dec(asset.cost) - _dec(dep_sum or 0)).quantize(_D2, ROUND_HALF_UP)
            new_value = _dec(data.new_value).quantize(_D2, ROUND_HALF_UP)
            diff = (new_value - old_value).quantize(_D2, ROUND_HALF_UP)
    
            result = conn.execute(text("""
                INSERT INTO asset_revaluations (asset_id, revaluation_date, old_value, new_value, difference, reason, created_by)
                VALUES (:aid, :date, :old, :new, :diff, :reason, :uid)
                RETURNING *
            """), {
                "aid": data.asset_id, "date": (data.revaluation_date or date.today()).isoformat(),
                "old": old_value, "new": new_value, "diff": diff,
                "reason": data.reason, "uid": current_user.id,
            }).fetchone()
            return dict(result._mapping)
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ---------- Maintenance complete (STATIC - must be before /{asset_id}) ----------

@router.post("/{asset_id}/revalue", dependencies=[Depends(require_permission("assets.manage"))], response_model=Dict[str, Any])
def revalue_asset(request: Request, asset_id: int, reval: AssetRevaluation, current_user: dict = Depends(get_current_user)):
    """إعادة تقييم أصل ثابت — IAS 16.35-40: الزيادة تسجل في احتياطي إعادة التقييم"""
    conn = get_db_connection(current_user.company_id)
    trans = conn.begin()
    try:
        from utils.accounting import get_base_currency

        asset = conn.execute(text("SELECT * FROM assets WHERE id = :id FOR UPDATE"), {"id": asset_id}).fetchone()
        if not asset or asset.status == 'disposed':
            raise HTTPException(**http_error(400, "asset_not_found_or_disposed", request))

        acc_depr_recorded = _dec(conn.execute(text("""
            SELECT COALESCE(SUM(amount), 0) FROM asset_depreciation_schedule WHERE asset_id = :id AND posted = TRUE
        """), {"id": asset_id}).scalar())

        # T037: Use current_value (if set) rather than cost for carrying amount
        carrying_cost = _dec(asset.current_value if asset.current_value else asset.cost)
        old_book = (carrying_cost - acc_depr_recorded).quantize(_D2, ROUND_HALF_UP)
        diff = (_dec(reval.new_value) - old_book).quantize(_D2, ROUND_HALF_UP)

        if diff.copy_abs() < _D2:
            return {"success": True, "message": i18n_message("no_value_difference", request)}

        base_currency = get_base_currency(conn)
        acc_fixed = get_mapped_account_id(conn, "acc_map_fixed_assets")
        acc_reval = get_mapped_account_id(conn, "acc_map_revaluation_reserve")
        acc_loss = get_mapped_account_id(conn, "acc_map_asset_loss")
        if diff > 0 and not acc_reval:
            raise HTTPException(**http_error(400, "revaluation_reserve_account_not_configured", request))
        if diff < 0 and not acc_loss:
            raise HTTPException(**http_error(400, "asset_loss_account_not_configured", request))

        check_fiscal_period_open(conn, date.today())

        # T038: IAS 16.40 — check existing revaluation surplus before recording a decrease
        existing_surplus = _dec(asset.revaluation_surplus or 0)
        
        je_lines = []
        if diff > 0:
            # IAS 16.39: Increase → credit revaluation surplus (OCI)
            je_lines.extend([
                {"account_id": acc_fixed, "debit": abs(diff), "credit": 0, "description": f"زيادة قيمة أصل #{asset_id}"},
                {"account_id": acc_reval, "debit": 0, "credit": abs(diff), "description": "احتياطي إعادة تقييم"}
            ])
            new_surplus = (existing_surplus + abs(diff)).quantize(_D2, ROUND_HALF_UP)
        else:
            abs_diff = abs(diff)
            # IAS 16.40: Decrease first reverses any existing surplus, remainder goes to P&L
            if existing_surplus > 0 and existing_surplus >= abs_diff:
                # Entire decrease absorbed by surplus reversal
                je_lines.extend([
                    {"account_id": acc_reval, "debit": abs_diff, "credit": 0, "description": f"عكس احتياطي تقييم أصل #{asset_id}"},
                    {"account_id": acc_fixed, "debit": 0, "credit": abs_diff, "description": f"تخفيض أصل #{asset_id}"}
                ])
                new_surplus = (existing_surplus - abs_diff).quantize(_D2, ROUND_HALF_UP)
            elif existing_surplus > 0:
                # Partial surplus reversal + remainder to loss
                loss_portion = (abs_diff - existing_surplus).quantize(_D2, ROUND_HALF_UP)
                je_lines.extend([
                    {"account_id": acc_reval, "debit": existing_surplus, "credit": 0, "description": f"عكس احتياطي تقييم أصل #{asset_id}"},
                    {"account_id": acc_loss, "debit": loss_portion, "credit": 0, "description": f"انخفاض قيمة أصل #{asset_id}"},
                    {"account_id": acc_fixed, "debit": 0, "credit": abs_diff, "description": f"تخفيض أصل #{asset_id}"}
                ])
                new_surplus = Decimal(0)
            else:
                # No surplus — entire decrease to P&L
                je_lines.extend([
                    {"account_id": acc_loss, "debit": abs_diff, "credit": 0, "description": f"انخفاض قيمة أصل #{asset_id}"},
                    {"account_id": acc_fixed, "debit": 0, "credit": abs_diff, "description": f"تخفيض أصل #{asset_id}"}
                ])
                new_surplus = Decimal(0)
            
        from services.gl_service import create_journal_entry as gl_create_journal_entry
        je_id, je_num = gl_create_journal_entry(
            db=conn,
            company_id=current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id,
            date=date.today(),
            description=reval.reason or "إعادة تقييم أصل",
            lines=je_lines,
            user_id=current_user.get("id") if isinstance(current_user, dict) else current_user.id,
            branch_id=asset.branch_id,
            reference=f"ASSET-REVAL-{asset_id}",
            currency=base_currency,
            exchange_rate=Decimal("1"),
            source="asset_revaluation",
            source_id=asset_id
        )

        # T037: Update current_value (not cost) + revaluation_surplus
        conn.execute(text("""
            UPDATE assets SET current_value = :new_val, revaluation_surplus = :surplus,
                updated_at = NOW() WHERE id = :id
        """), {"new_val": _dec(reval.new_value).quantize(_D2, ROUND_HALF_UP),
               "surplus": new_surplus, "id": asset_id})

        trans.commit()
        return {
            "success": True, "asset_id": asset_id,
            "old_book_value": float(old_book.quantize(_D2, ROUND_HALF_UP)), "new_value": float(_dec(reval.new_value).quantize(_D2, ROUND_HALF_UP)),
            "difference": float(diff.quantize(_D2, ROUND_HALF_UP)), "journal_entry": je_num,
        }
    except HTTPException:
        trans.rollback()
        raise
    except Exception:
        trans.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        conn.close()


# =====================================================
# 8.14 ASSETS IMPROVEMENTS
# =====================================================

# ---------- ASSET-001: Additional Depreciation Methods ----------

