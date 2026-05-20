"""Inventory archival admin endpoints.

Feature 023 — T100.  GET /inventory/archival/status,
POST /inventory/archival/run

INV-05 fix: replaced manual get_current_user() call with proper FastAPI
require_permission dependency (Constitution §4 [CRITICAL]).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from sqlalchemy import text

from database import get_db
from routers.auth import get_current_user
from utils.permissions import require_permission

router = APIRouter(prefix="/inventory/archival", tags=["inventory"])


@router.get("/status", dependencies=[Depends(require_permission("system.admin"))])
async def archival_status(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return live vs archived inventory transaction counts."""
    # tenant_id is resolved from the authenticated user's company_id
    company_id = (
        current_user.get("company_id")
        if isinstance(current_user, dict)
        else getattr(current_user, "company_id", 0)
    )

    live = db.execute(
        text("SELECT COUNT(*) as cnt FROM inventory_transactions"),
    ).fetchone()
    archived = db.execute(
        text("SELECT COUNT(*) as cnt FROM inventory_transactions_archive"),
    ).fetchone()

    return {
        "company_id": company_id,
        "live_count": live.cnt if live else 0,
        "archived_count": archived.cnt if archived else 0,
    }


@router.post("/run", dependencies=[Depends(require_permission("system.admin"))])
async def run_archival(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Trigger inventory transaction archival for the current tenant."""
    from services.inventory.archival import run_archival as _run_archival

    result = _run_archival(db)
    db.commit()
    return result
