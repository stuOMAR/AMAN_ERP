"""CRM cashflow forecast endpoint.

Feature 023 — T059.  GET /crm/cashflow-forecast
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/crm", tags=["crm"])


@router.get("/cashflow-forecast")
async def get_cashflow_forecast(
    request: Request,
    horizon_days: int = Query(90, ge=7, le=365),
    db: Session = Depends(get_db),
):
    from services.crm.cashflow_feed import forecast_by_date
    from utils.permissions import get_current_user

    user = get_current_user(request)
    result = forecast_by_date(
        db,
        tenant_id=user.get("tenant_id", 0),
        horizon_days=horizon_days,
    )
    return result
