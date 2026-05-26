"""QC gate endpoints.

Feature 023 — T093.  POST /manufacturing/orders/{id}/qc/pass,
POST /manufacturing/orders/{id}/qc/fail
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from database import get_company_db
from routers.auth import get_current_user
from schemas import UserResponse
from utils.permissions import require_module, require_permission

router = APIRouter(
    prefix="/manufacturing/orders",
    tags=["manufacturing"],
    dependencies=[Depends(require_module("manufacturing"))],
)


def get_db(current_user: UserResponse = Depends(get_current_user)):
    yield from get_company_db(current_user.company_id)


class QcPassRequest(BaseModel):
    completion_ids: list[int]


class QcFailRequest(BaseModel):
    completion_ids: list[int]
    disposition: str  # 'scrap' or 'rework'
    reason: Optional[str] = None


@router.post("/{order_id}/qc/pass", dependencies=[Depends(require_permission("manufacturing.manage"))])
async def qc_pass(
    order_id: int,
    body: QcPassRequest,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from services.manufacturing.qc_gate import qc_pass

    result = qc_pass(
        db,
        mo_id=order_id,
        completion_ids=body.completion_ids,
        tenant_id=current_user.company_id,
    )
    db.commit()
    return result


@router.post("/{order_id}/qc/fail", dependencies=[Depends(require_permission("manufacturing.manage"))])
async def qc_fail(
    order_id: int,
    body: QcFailRequest,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from services.manufacturing.qc_gate import qc_fail

    result = qc_fail(
        db,
        mo_id=order_id,
        completion_ids=body.completion_ids,
        tenant_id=current_user.company_id,
        disposition=body.disposition,
        reason=body.reason,
    )
    db.commit()
    return result
