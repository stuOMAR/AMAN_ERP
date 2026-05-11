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

@router.put("/{asset_id}/qr", dependencies=[Depends(require_permission("assets.create"))], response_model=Dict[str, Any])
def update_asset_qr(asset_id: int, data: AssetQRUpdate, current_user: dict = Depends(get_current_user)):
    """Update Asset QR."""
    with transactional(current_user.company_id) as conn:
        conn.execute(text("UPDATE assets SET qr_code = :qr, barcode = :bc WHERE id = :id"),
                     {"qr": data.qr_code, "bc": data.barcode, "id": asset_id})
        return {"message": i18n_message(("qr_updated", request))}


@router.get("/{asset_id}/qr", dependencies=[Depends(require_permission("assets.view"))], response_model=Dict[str, Any])
def get_asset_qr(asset_id: int, current_user: dict = Depends(get_current_user)):
    """Get Asset QR."""
    with transactional(current_user.company_id) as conn:
        row = conn.execute(text("SELECT id, name, code, qr_code, barcode FROM assets WHERE id = :id"),
                           {"id": asset_id}).fetchone()
        if not row:
            raise HTTPException(**http_error(404, "asset_not_found", request))
        return dict(row._mapping)


# ===================== B6: IAS 36 Impairment Testing =====================

