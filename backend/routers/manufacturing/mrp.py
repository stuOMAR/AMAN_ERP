"""MRP run endpoint.

Feature 023 — T077.  POST /manufacturing/mrp/run
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from database import get_company_db
from routers.auth import get_current_user
from schemas import UserResponse
from utils.permissions import require_module, require_permission

router = APIRouter(
    prefix="/manufacturing/mrp",
    tags=["manufacturing"],
    dependencies=[Depends(require_module("manufacturing"))],
)


def get_db(current_user: UserResponse = Depends(get_current_user)):
    yield from get_company_db(current_user.company_id)


def _actor(current_user: UserResponse) -> dict:
    return {
        "id": current_user.id,
        "user_id": current_user.id,
        "username": current_user.username,
        "role": current_user.role,
        "company_id": current_user.company_id,
        "tenant_id": current_user.company_id,
        "permissions": current_user.permissions or [],
    }


@router.post("/run", dependencies=[Depends(require_permission("manufacturing.manage"))])
async def run_mrp(
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from services.manufacturing.mrp import run_mrp

    user = _actor(current_user)
    result = run_mrp(db, tenant_id=user.get("tenant_id", 0), actor=user)
    db.commit()
    return result
