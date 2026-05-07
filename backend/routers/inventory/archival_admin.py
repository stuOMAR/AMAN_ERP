"""Inventory archival admin endpoints.

Feature 023 — T100.  GET /inventory/archival/status,
POST /inventory/archival/run
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/inventory/archival", tags=["inventory"])


@router.get("/status")
async def archival_status(request: Request, db: Session = Depends(get_db)):
    from utils.permissions import get_current_user
    from sqlalchemy import text

    user = get_current_user(request)
    tid = user.get("tenant_id", 0)

    live = db.execute(
        text("SELECT COUNT(*) as cnt FROM inventory_transactions WHERE tenant_id = :tid"),
        {"tid": tid},
    ).fetchone()
    archived = db.execute(
        text("SELECT COUNT(*) as cnt FROM inventory_transactions_archive WHERE tenant_id = :tid"),
        {"tid": tid},
    ).fetchone()

    return {
        "live_count": live.cnt if live else 0,
        "archived_count": archived.cnt if archived else 0,
    }


@router.post("/run")
async def run_archival(request: Request, db: Session = Depends(get_db)):
    from services.inventory.archival import run_archival
    from utils.permissions import get_current_user

    user = get_current_user(request)
    result = run_archival(db, tenant_id=user.get("tenant_id", 0))
    db.commit()
    return result
