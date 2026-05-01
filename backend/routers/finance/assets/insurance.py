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

from .core import _D2, _D4

@router.get("/{asset_id}/insurance", dependencies=[Depends(require_permission("assets.view"))], response_model=List[Dict[str, Any]])
def list_asset_insurance(asset_id: int, current_user: dict = Depends(get_current_user)):
    """List Asset Insurance."""
    with transactional(current_user.company_id) as conn:
        rows = conn.execute(text("SELECT * FROM asset_insurance WHERE asset_id = :id ORDER BY end_date DESC"),
                            {"id": asset_id}).fetchall()
        return [dict(r._mapping) for r in rows]


@router.post("/{asset_id}/insurance", dependencies=[Depends(require_permission("assets.create"))], response_model=Dict[str, Any])
def add_insurance(asset_id: int, data: InsuranceCreate, current_user: dict = Depends(get_current_user)):
    """Add Insurance."""
    with transactional(current_user.company_id) as conn:
        try:
            result = conn.execute(text("""
                INSERT INTO asset_insurance (asset_id, policy_number, insurer, coverage_type,
                    premium_amount, coverage_amount, start_date, end_date, notes)
                VALUES (:aid, :pol, :ins, :cov, :prem, :covamt, :start, :end, :notes)
                RETURNING *
            """), {
                "aid": asset_id, "pol": data.policy_number, "ins": data.insurer,
                "cov": data.coverage_type, "prem": data.premium_amount,
                "covamt": data.coverage_amount,
                "start": data.start_date, "end": data.end_date,
                "notes": data.notes,
            }).fetchone()
            return dict(result._mapping)
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


