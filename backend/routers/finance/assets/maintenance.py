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

from .core import _D2, _D4

@router.put("/maintenance/{maint_id}/complete", dependencies=[Depends(require_permission("assets.create"))], response_model=Dict[str, Any])
def complete_maintenance(request: Request, maint_id: int, data: MaintenanceComplete = MaintenanceComplete(), current_user: dict = Depends(get_current_user)):
    """Complete Maintenance."""
    with transactional(current_user.company_id) as conn:
        conn.execute(text("""
            UPDATE asset_maintenance SET status = 'completed', completed_date = :d,
                cost = COALESCE(:cost, cost) WHERE id = :id
        """), {"d": (data.completed_date or date.today()).isoformat(),
               "cost": data.actual_cost, "id": maint_id})
        return {"message": i18n_message("maintenance_completed", request)}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ASSET REPORTS (Static routes — MUST come before /{asset_id})
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/{asset_id}/maintenance", dependencies=[Depends(require_permission("assets.view"))], response_model=List[Dict[str, Any]])
def list_asset_maintenance(asset_id: int, current_user: dict = Depends(get_current_user)):
    """List Asset Maintenance."""
    with transactional(current_user.company_id) as conn:
        rows = conn.execute(text("SELECT * FROM asset_maintenance WHERE asset_id = :id ORDER BY scheduled_date DESC"),
                            {"id": asset_id}).fetchall()
        return [dict(r._mapping) for r in rows]


@router.post("/{asset_id}/maintenance", dependencies=[Depends(require_permission("assets.create"))], response_model=Dict[str, Any])
def add_maintenance(asset_id: int, data: MaintenanceCreate, current_user: dict = Depends(get_current_user)):
    """Add Maintenance."""
    with transactional(current_user.company_id) as conn:
        try:
            result = conn.execute(text("""
                INSERT INTO asset_maintenance (asset_id, maintenance_type, description,
                    scheduled_date, cost, vendor, status, notes, created_by)
                VALUES (:aid, :type, :desc, :date, :cost, :vendor, 'scheduled', :notes, :uid)
                RETURNING *
            """), {
                "aid": asset_id, "type": data.maintenance_type,
                "desc": data.description, "date": data.scheduled_date,
                "cost": data.cost, "vendor": data.vendor,
                "notes": data.notes, "uid": current_user.id,
            }).fetchone()
            conn.execute(text("UPDATE assets SET last_maintenance_date = :d WHERE id = :id"),
                         {"d": data.scheduled_date, "id": asset_id})
            return dict(result._mapping)
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))




# ---------- ASSET-005: QR / Barcode ----------

