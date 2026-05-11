"""Demand forecasting endpoints for the inventory module."""

import logging

from fastapi import Request, APIRouter, Depends, HTTPException
from utils.i18n import http_error
from sqlalchemy import text

from database import get_db_connection
from routers.auth import get_current_user
from schemas.forecast import ForecastAdjustRequest, ForecastGenerateRequest
from services.demand_forecast_service import generate_demand_forecast, manual_adjust
from utils.permissions import require_permission

forecast_router = APIRouter(prefix="/forecast", tags=["Demand Forecasting"])
logger = logging.getLogger(__name__)


@forecast_router.post(
    "/generate",
    dependencies=[Depends(require_permission("inventory.forecast_generate"))],
)
def generate_forecast(
    body: ForecastGenerateRequest,
    current_user: dict = Depends(get_current_user),
):
    """Generate demand forecast for a product based on sales history."""
    db = get_db_connection(current_user.company_id)
    try:
        result = generate_demand_forecast(
            db,
            product_id=body.product_id,
            warehouse_id=body.warehouse_id,
            horizon_months=body.horizon_months,
            user_id=current_user.id,
        )
        return result
    except ValueError:
        logger.exception("Internal error")
        raise HTTPException(**http_error(400, "invalid_data"))
    finally:
        db.close()


@forecast_router.get(
    "",
    dependencies=[Depends(require_permission("inventory.forecast_view"))],
)
def list_forecasts(
    product_id: int | None = None,
    current_user: dict = Depends(get_current_user),
):
    """List saved demand forecasts, optionally filtered by product."""
    db = get_db_connection(current_user.company_id)
    try:
        where = ""
        params: dict = {}
        if product_id:
            where = "WHERE df.product_id = :pid"
            params["pid"] = product_id

        rows = db.execute(
            text(f"""
                SELECT df.id, df.product_id, df.warehouse_id, df.forecast_method,
                       df.generated_date, df.generated_by, df.history_months_used,
                       p.product_name
                FROM demand_forecasts df
                JOIN products p ON p.id = df.product_id
                {where}
                ORDER BY df.generated_date DESC
                LIMIT 100
            """),
            params,
        ).fetchall()

        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


@forecast_router.get(
    "/{forecast_id}",
    dependencies=[Depends(require_permission("inventory.forecast_view"))],
)
def get_forecast(request: Request, 
    forecast_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Get a forecast with all its periods."""
    db = get_db_connection(current_user.company_id)
    try:
        row = db.execute(
            text("""
                SELECT df.id, df.product_id, df.warehouse_id, df.forecast_method,
                       df.generated_date, df.generated_by, df.history_months_used,
                       p.product_name
                FROM demand_forecasts df
                JOIN products p ON p.id = df.product_id
                WHERE df.id = :fid
            """),
            {"fid": forecast_id},
        ).fetchone()
        if not row:
            raise HTTPException(**http_error(404, "forecast_not_found", request))

        forecast = dict(row._mapping)

        periods = db.execute(
            text("""
                SELECT id, forecast_id, period_start, period_end,
                       projected_quantity, confidence_lower, confidence_upper,
                       manual_adjustment, adjusted_quantity
                FROM demand_forecast_periods
                WHERE forecast_id = :fid
                ORDER BY period_start
            """),
            {"fid": forecast_id},
        ).fetchall()
        forecast["periods"] = [dict(p._mapping) for p in periods]

        return forecast
    finally:
        db.close()


@forecast_router.put(
    "/{forecast_id}/adjust",
    dependencies=[Depends(require_permission("inventory.forecast_manage"))],
)
def adjust_forecast(request: Request, 
    forecast_id: int,
    body: ForecastAdjustRequest,
    current_user: dict = Depends(get_current_user),
):
    """Apply manual adjustments to forecast periods."""
    db = get_db_connection(current_user.company_id)
    try:
        # Verify forecast exists
        exists = db.execute(
            text("SELECT 1 FROM demand_forecasts WHERE id = :fid"),
            {"fid": forecast_id},
        ).fetchone()
        if not exists:
            raise HTTPException(**http_error(404, "forecast_not_found", request))

        result = manual_adjust(
            db,
            forecast_id=forecast_id,
            adjustments=[
                {"period_id": a.period_id, "manual_adjustment": a.manual_adjustment}
                for a in body.adjustments
            ],
        )
        return result
    finally:
        db.close()
