"""assets sub-router — split from monolithic assets.py (T6.3).

Mounted under the parent router via assets/__init__.py.
"""
from fastapi import Request, APIRouter, Depends, HTTPException
from utils.i18n import http_error, i18n_message
from sqlalchemy import text
from typing import Any, Dict
from decimal import Decimal
import logging
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import require_permission, validate_branch_access
from schemas.assets import (
    AssetQRUpdate,
)

logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')

def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')

router = APIRouter()


@router.put("/{asset_id}/qr", dependencies=[Depends(require_permission("assets.create"))], response_model=Dict[str, Any])
def update_asset_qr(request: Request, asset_id: int, data: AssetQRUpdate, current_user: dict = Depends(get_current_user)):
    """Update Asset QR."""
    with transactional(current_user.company_id) as conn:
        asset = conn.execute(text("SELECT branch_id FROM assets WHERE id = :id"), {"id": asset_id}).fetchone()
        if not asset:
            raise HTTPException(**http_error(404, "asset_not_found", request))
        validate_branch_access(current_user, asset.branch_id, request)

        conn.execute(text("UPDATE assets SET qr_code = :qr, barcode = :bc WHERE id = :id"),
                     {"qr": data.qr_code, "bc": data.barcode, "id": asset_id})
        return {"message": i18n_message("qr_updated", request)}


@router.get("/{asset_id}/qr", dependencies=[Depends(require_permission("assets.view"))], response_model=Dict[str, Any])
def get_asset_qr(request: Request, asset_id: int, current_user: dict = Depends(get_current_user)):
    """Get Asset QR."""
    with transactional(current_user.company_id) as conn:
        row = conn.execute(text("SELECT id, name, code, qr_code, barcode, branch_id FROM assets WHERE id = :id"),
                           {"id": asset_id}).fetchone()
        if not row:
            raise HTTPException(**http_error(404, "asset_not_found", request))
        validate_branch_access(current_user, row.branch_id, request)
        result = dict(row._mapping)
        result.pop("branch_id", None)
        return result


# ===================== B6: IAS 36 Impairment Testing =====================
