"""Technician admin endpoints.

GET  /api/fsm/technicians            — list technicians
POST /api/fsm/technicians            — create/update profile
POST /api/fsm/technicians/match      — find matching technicians
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from typing import List, Optional

from database import get_db_connection
from services.fsm.technicians import (
    upsert_technician,
    technician_assignment_matcher,
)
from utils.i18n import i18n_message
from utils.permissions import require_module, require_permission

router = APIRouter(
    prefix="/fsm/technicians",
    tags=["FSM Technicians"],
    dependencies=[Depends(require_module("services"))],
)
logger = logging.getLogger(__name__)


class TechnicianProfileCreate(BaseModel):
    employee_id: int
    skills: List[str]
    zones: List[str] = []
    certifications: List[str] = []
    availability: Optional[dict] = None


class MatchRequest(BaseModel):
    required_skills: List[str]
    zone: Optional[str] = None


def _get_tenant_id(current_user) -> str:
    return str(
        current_user.get("company_id")
        if isinstance(current_user, dict)
        else getattr(current_user, "company_id", 0)
    )


@router.get("")
def list_technicians(current_user=Depends(require_permission("services.view"))):
    """List all active technicians."""
    tenant_id = _get_tenant_id(current_user)
    conn = get_db_connection(tenant_id)
    try:
        rows = conn.execute(
            text("""
                SELECT id, employee_id, skills, zones, certifications, is_active
                FROM technicians
                WHERE tenant_id = :tnt AND is_active = true
                ORDER BY id
            """),
            {"tnt": int(tenant_id)},
        ).fetchall()

        return [
            {
                "id": r[0], "employee_id": r[1],
                "skills": json.loads(r[2]) if r[2] else [],
                "zones": json.loads(r[3]) if r[3] else [],
                "certifications": json.loads(r[4]) if r[4] else [],
                "is_active": r[5],
            }
            for r in rows
        ]
    finally:
        conn.close()


@router.post("")
def create_technician(
    request: Request,
    body: TechnicianProfileCreate,
    current_user=Depends(require_permission("services.edit")),
):
    """Create or update a technician profile."""
    tenant_id = _get_tenant_id(current_user)
    conn = get_db_connection(tenant_id)
    try:
        result = upsert_technician(
            conn,
            tenant_id=int(tenant_id),
            employee_id=body.employee_id,
            skills=body.skills,
            zones=body.zones,
            certifications=body.certifications,
            availability=body.availability,
        )
        return result
    except Exception:
        logger.exception("Error creating technician profile")
        raise HTTPException(status_code=400, detail=i18n_message("internal_error", request) if request else "Internal error")
    finally:
        conn.close()


@router.post("/match")
def match_technicians(
    body: MatchRequest,
    current_user=Depends(require_permission("services.view")),
):
    """Find technicians matching required skills."""
    tenant_id = _get_tenant_id(current_user)
    conn = get_db_connection(tenant_id)
    try:
        candidates = technician_assignment_matcher(
            conn,
            tenant_id=int(tenant_id),
            required_skills=body.required_skills,
            zone=body.zone,
        )
        return {"candidates": candidates}
    finally:
        conn.close()
