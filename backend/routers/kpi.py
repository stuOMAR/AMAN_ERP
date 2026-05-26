"""T121: KPI admin CRUD endpoints.

KPI reads are gated by dashboard.analytics_view; mutations by dashboard.analytics_manage.
"""

from __future__ import annotations

import logging
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from pydantic import BaseModel
from routers.auth import get_current_user
from utils.permissions import require_permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/kpi", tags=["kpi"])


class KPIDefinitionCreate(BaseModel):
    kpi_code: str
    metric_source: str  # report_key | classifier_category
    metric_reference: str
    threshold_value: float
    comparison_op: str  # lt | lte | gt | gte | eq
    channels: list[str]
    evaluation_interval_minutes: int = 15
    is_active: bool = True


class KPIDefinitionResponse(BaseModel):
    id: str
    kpi_code: str
    metric_source: str
    metric_reference: str
    threshold_value: float
    comparison_op: str
    channels: list[str]
    evaluation_interval_minutes: int
    is_active: bool


@router.post(
    "/definitions",
    response_model=KPIDefinitionResponse,
    dependencies=[Depends(require_permission("dashboard.analytics_manage"))],
)
async def create_kpi_definition(body: KPIDefinitionCreate, request: Request, current_user=Depends(get_current_user)):
    """Create a new KPI definition."""
    from database import get_tenant_db
    from sqlalchemy import text
    import uuid

    kpi_id = str(uuid.uuid4())

    # Validate
    if body.metric_source not in ("report_key", "classifier_category"):
        raise HTTPException(**http_error(400, "kpi_metric_source_invalid", request))
    if body.comparison_op not in ("lt", "lte", "gt", "gte", "eq"):
        raise HTTPException(**http_error(400, "kpi_comparison_op_invalid", request))
    if body.evaluation_interval_minutes < 5:
        raise HTTPException(**http_error(400, "kpi_interval_min", request))

    try:
        with get_tenant_db(current_user.company_id) as db:
            db.execute(
                text("""
                    INSERT INTO kpi_definitions
                        (id, tenant_id, kpi_code, metric_source, metric_reference,
                         threshold_value, comparison_op, channels, evaluation_interval_minutes, is_active)
                    VALUES (
                        :id,
                        CASE
                            WHEN current_database() ~ '^aman_[0-9]+$'
                            THEN regexp_replace(current_database(), '^aman_', '')::bigint
                            ELSE 0
                        END,
                        :code, :source, :ref, :threshold, :op,
                        CAST(:channels AS JSONB), :interval, :active
                    )
                """),
                {
                    "id": kpi_id, "code": body.kpi_code,
                    "source": body.metric_source, "ref": body.metric_reference,
                    "threshold": body.threshold_value, "op": body.comparison_op,
                    "channels": json.dumps(body.channels), "interval": body.evaluation_interval_minutes,
                    "active": body.is_active,
                },
            )
            db.commit()
    except Exception:
        raise HTTPException(**http_error(500, "kpi_create_failed", request))

    return KPIDefinitionResponse(id=kpi_id, **body.model_dump())


@router.get("/definitions", dependencies=[Depends(require_permission("dashboard.analytics_view"))])
async def list_kpi_definitions(current_user=Depends(get_current_user)):
    """List all KPI definitions."""
    from database import get_tenant_db
    from sqlalchemy import text

    with get_tenant_db(current_user.company_id) as db:
        result = db.execute(text("SELECT id, kpi_code, metric_source, metric_reference, threshold_value, comparison_op, channels, evaluation_interval_minutes, is_active FROM kpi_definitions ORDER BY kpi_code"))
        rows = result.fetchall()

    return [
        KPIDefinitionResponse(
            id=str(r[0]), kpi_code=r[1], metric_source=r[2], metric_reference=r[3],
            threshold_value=float(r[4]), comparison_op=r[5], channels=r[6],
            evaluation_interval_minutes=r[7], is_active=r[8],
        )
        for r in rows
    ]


@router.get("/evaluations", dependencies=[Depends(require_permission("dashboard.analytics_view"))])
async def list_kpi_evaluations(
    kpi_id: Optional[str] = None,
    limit: int = 20,
    current_user=Depends(get_current_user),
):
    """List KPI evaluations, optionally filtered by kpi_id."""
    from database import get_tenant_db
    from sqlalchemy import text

    query = "SELECT id, kpi_id, evaluation_window_start, value, breached, notified_at FROM kpi_evaluations"
    params: dict = {}
    if kpi_id:
        query += " WHERE kpi_id = :kpi_id"
        params["kpi_id"] = kpi_id
    query += " ORDER BY created_at DESC LIMIT :limit"
    params["limit"] = limit

    with get_tenant_db(current_user.company_id) as db:
        result = db.execute(text(query), params)
        rows = result.fetchall()

    return [
        {
            "id": str(r[0]), "kpi_id": str(r[1]),
            "evaluation_window_start": r[2].isoformat() if r[2] else None,
            "value": float(r[3]) if r[3] else 0,
            "breached": r[4],
            "notified_at": r[5].isoformat() if r[5] else None,
        }
        for r in rows
    ]
