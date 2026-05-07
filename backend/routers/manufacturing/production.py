"""Production completion endpoint.

Feature 023 — T089.  POST /manufacturing/orders/{id}/complete
"""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db

router = APIRouter(prefix="/manufacturing/orders", tags=["manufacturing"])


class CompletionRequest(BaseModel):
    qty: float
    warehouse_id: int
    scrap_lines: Optional[list[dict]] = None
    byproduct_lines: Optional[list[dict]] = None
    notes: Optional[str] = None


@router.post("/{order_id}/complete")
async def complete_production(
    order_id: int,
    body: CompletionRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    from services.manufacturing.production_complete import complete_production
    from utils.permissions import get_current_user

    user = get_current_user(request)
    result = complete_production(
        db,
        mo_id=order_id,
        tenant_id=user.get("tenant_id", 0),
        actor=user,
        qty=Decimal(str(body.qty)),
        warehouse_id=body.warehouse_id,
        scrap_lines=body.scrap_lines,
        byproduct_lines=body.byproduct_lines,
    )
    db.commit()
    return result
