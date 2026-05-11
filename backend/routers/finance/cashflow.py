"""
AMAN ERP – Cash Flow Forecasting
التنبؤ بالتدفقات النقدية
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from utils.i18n import http_error
from sqlalchemy import text

from database import get_db_connection
from routers.auth import get_current_user
from schemas.cashflow import (
    ForecastDetailRead,
    ForecastGenerateRequest,
    ForecastLineRead,
    ForecastListResponse,
    ForecastRead,
)
from services.forecast_service import generate_cashflow_forecast
from utils.permissions import branch_scope_filter, require_permission, validate_branch_access

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/finance/cashflow", tags=["Cash Flow Forecast"])


# ── POST /generate ──

@router.post(
    "/generate",
    response_model=ForecastRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("finance.cashflow_generate"))],
)
def generate_forecast(
    body: ForecastGenerateRequest,
    current_user=Depends(get_current_user),
):
    """Generate Forecast."""
    db = get_db_connection(current_user.company_id)
    try:
        result = generate_cashflow_forecast(
            db,
            name=body.name,
            horizon_days=body.horizon_days,
            mode=body.mode,
            user_id=current_user.id,
            scenario_weights=body.scenario_weights,
        )
        row = db.execute(
            text("SELECT * FROM cashflow_forecasts WHERE id = :fid"),
            {"fid": result["forecast_id"]},
        ).fetchone()
        return ForecastRead.model_validate(row)
    except Exception:
        db.rollback()
        logger.exception("Forecast generation failed")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ── GET / ──

@router.get(
    "",
    response_model=ForecastListResponse,
    dependencies=[Depends(require_permission("finance.cashflow_view"))],
)
def list_forecasts(
    skip: int = 0,
    limit: int = 50,
    branch_id: Optional[int] = Query(None),
    current_user=Depends(get_current_user),
):
    """List Forecasts."""
    db = get_db_connection(current_user.company_id)
    try:
        where = "deleted_at IS NULL"
        params = {"lim": limit, "off": skip}
        where += " " + branch_scope_filter(current_user, branch_id, "branch_id", params)
        total = db.execute(
            text(f"SELECT COUNT(*) FROM cashflow_forecasts WHERE {where}"), params
        ).scalar()
        rows = db.execute(
            text(
                f"SELECT * FROM cashflow_forecasts WHERE {where} "
                "ORDER BY forecast_date DESC LIMIT :lim OFFSET :off"
            ),
            params,
        ).fetchall()
        return ForecastListResponse(
            items=[ForecastRead.model_validate(r) for r in rows],
            total=total,
        )
    finally:
        db.close()


# ── GET /{id} ──

@router.get(
    "/{forecast_id}",
    response_model=ForecastDetailRead,
    dependencies=[Depends(require_permission("finance.cashflow_view"))],
)
def get_forecast(forecast_id: int, current_user=Depends(get_current_user)):
    """Get Forecast."""
    db = get_db_connection(current_user.company_id)
    try:
        row = db.execute(
            text("SELECT * FROM cashflow_forecasts WHERE id = :fid AND deleted_at IS NULL"),
            {"fid": forecast_id},
        ).fetchone()
        if not row:
            raise HTTPException(**http_error(404, ("forecast_not_found", request)))

        lines = db.execute(
            text(
                "SELECT * FROM cashflow_forecast_lines WHERE forecast_id = :fid "
                "AND deleted_at IS NULL ORDER BY date"
            ),
            {"fid": forecast_id},
        ).fetchall()

        forecast = ForecastDetailRead.model_validate(row)
        forecast.lines = [ForecastLineRead.model_validate(l) for l in lines]
        return forecast
    finally:
        db.close()


# ── DELETE /{id} ──

@router.delete(
    "/{forecast_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("finance.cashflow_manage"))],
)
def delete_forecast(forecast_id: int, current_user=Depends(get_current_user)):
    """Delete Forecast."""
    db = get_db_connection(current_user.company_id)
    try:
        result = db.execute(
            text(
                "UPDATE cashflow_forecasts SET deleted_at = NOW() "
                "WHERE id = :fid AND deleted_at IS NULL"
            ),
            {"fid": forecast_id},
        )
        if result.rowcount == 0:
            raise HTTPException(**http_error(404, ("forecast_not_found", request)))
        db.commit()
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Forecast deletion failed")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
