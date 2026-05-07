"""CRM velocity endpoint.

Feature 023 — T059.  GET /crm/velocity
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db

router = APIRouter(prefix="/crm", tags=["crm"])


@router.get("/velocity")
async def get_velocity(
    request: Request,
    period_days: int = Query(90, ge=1, le=365),
    db: Session = Depends(get_db),
):
    from services.crm.velocity import compute_velocity
    from utils.permissions import get_current_user

    user = get_current_user(request)
    result = compute_velocity(
        db,
        tenant_id=user.get("tenant_id", 0),
        period_days=period_days,
    )
    return result
