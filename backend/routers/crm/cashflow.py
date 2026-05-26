"""CRM cashflow forecast endpoint.

Feature 023 — T059.  GET /crm/cashflow-forecast
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query

from database import get_db_connection
from routers.auth import get_current_user
from utils.permissions import require_permission

router = APIRouter(prefix="/crm", tags=["crm"])


@router.get("/cashflow-forecast", dependencies=[Depends(require_permission(["sales.view", "dashboard.crm"]))])
async def get_cashflow_forecast(
    horizon_days: int = Query(90, ge=7, le=365),
    window_start: Optional[date] = None,
    window_end: Optional[date] = None,
    current_user=Depends(get_current_user),
):
    from services.crm.cashflow_feed import forecast_by_date

    db = get_db_connection(current_user.company_id)
    try:
        return forecast_by_date(
            db,
            tenant_id=current_user.company_id,
            window_start=str(window_start) if window_start else None,
            window_end=str(window_end) if window_end else None,
            horizon_days=horizon_days,
        )
    finally:
        db.close()
