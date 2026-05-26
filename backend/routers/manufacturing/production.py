"""Production completion endpoint.

Feature 023 — T089.  POST /manufacturing/orders/{id}/complete
"""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
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


class CompletionRequest(BaseModel):
    qty: Decimal = Field(gt=0)
    warehouse_id: int
    scrap_lines: Optional[list[dict]] = None
    byproduct_lines: Optional[list[dict]] = None
    notes: Optional[str] = None


@router.post("/{order_id}/complete", dependencies=[Depends(require_permission(["manufacturing.manage", "manufacturing.create"]))])
async def complete_production(
    order_id: int,
    body: CompletionRequest,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from services.manufacturing.production_complete import complete_production

    user = _actor(current_user)
    result = complete_production(
        db,
        mo_id=order_id,
        tenant_id=user.get("tenant_id", 0),
        actor=user,
        qty=body.qty,
        warehouse_id=body.warehouse_id,
        scrap_lines=body.scrap_lines,
        byproduct_lines=body.byproduct_lines,
    )
    db.commit()
    return result
