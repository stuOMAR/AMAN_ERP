"""QC gate endpoints.

Feature 023 — T093.  POST /manufacturing/orders/{id}/qc/pass,
POST /manufacturing/orders/{id}/qc/fail
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db

router = APIRouter(prefix="/manufacturing/orders", tags=["manufacturing"])


class QcPassRequest(BaseModel):
    completion_ids: list[int]


class QcFailRequest(BaseModel):
    completion_ids: list[int]
    disposition: str  # 'scrap' or 'rework'
    reason: Optional[str] = None


@router.post("/{order_id}/qc/pass")
async def qc_pass(
    order_id: int,
    body: QcPassRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    from services.manufacturing.qc_gate import qc_pass
    from utils.permissions import get_current_user

    user = get_current_user(request)
    result = qc_pass(
        db,
        mo_id=order_id,
        completion_ids=body.completion_ids,
        tenant_id=user.get("tenant_id", 0),
    )
    db.commit()
    return result


@router.post("/{order_id}/qc/fail")
async def qc_fail(
    order_id: int,
    body: QcFailRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    from services.manufacturing.qc_gate import qc_fail
    from utils.permissions import get_current_user

    user = get_current_user(request)
    result = qc_fail(
        db,
        mo_id=order_id,
        completion_ids=body.completion_ids,
        tenant_id=user.get("tenant_id", 0),
        disposition=body.disposition,
        reason=body.reason,
    )
    db.commit()
    return result
