"""CRM velocity endpoint.

Feature 023 — T059.  GET /crm/velocity
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from database import get_db_connection
from routers.auth import get_current_user
from utils.permissions import require_permission

router = APIRouter(prefix="/crm", tags=["crm"])


@router.get("/velocity", dependencies=[Depends(require_permission(["sales.view", "dashboard.crm"]))])
async def get_velocity(
    period_days: int = Query(90, ge=1, le=365),
    current_user=Depends(get_current_user),
):
    from services.crm.velocity import compute_velocity

    db = get_db_connection(current_user.company_id)
    try:
        return compute_velocity(
            db,
            tenant_id=current_user.company_id,
            window_days=period_days,
        )
    finally:
        db.close()
