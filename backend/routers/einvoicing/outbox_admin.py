"""ZATCA outbox admin endpoints.

Feature 023 — T066.  GET /einvoicing/outbox,
POST /einvoicing/outbox/{id}/reprocess
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db

router = APIRouter(prefix="/einvoicing/outbox", tags=["einvoicing"])


@router.get("")
async def list_outbox(
    request: Request,
    state: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: Session = Depends(get_db),
):
    from utils.permissions import get_current_user
    from sqlalchemy import text

    user = get_current_user(request)
    tid = user.get("tenant_id", 0)

    conditions = ["tenant_id = :tid"]
    params: dict = {"tid": tid, "limit": limit, "offset": offset}

    if state:
        conditions.append("state = :state")
        params["state"] = state

    where = " AND ".join(conditions)
    rows = db.execute(
        text(f"""
            SELECT id, invoice_id, state, attempts, max_attempts,
                   last_error, next_attempt_at, created_at, updated_at
            FROM zatca_outbox WHERE {where}
            ORDER BY created_at DESC LIMIT :limit OFFSET :offset
        """),
        params,
    ).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/{outbox_id}/reprocess")
async def reprocess_outbox(
    outbox_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    from utils.permissions import get_current_user
    from sqlalchemy import text

    user = get_current_user(request)
    tid = user.get("tenant_id", 0)

    result = db.execute(
        text("""
            UPDATE zatca_outbox
            SET state = 'pending', attempts = 0, last_error = NULL,
                next_attempt_at = clock_timestamp(), updated_at = clock_timestamp()
            WHERE id = :id AND tenant_id = :tid AND state IN ('failed', 'dead_letter')
            RETURNING id, state
        """),
        {"id": outbox_id, "tid": tid},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Outbox row not found or not in reprocessable state")

    db.commit()
    return {"id": row.id, "state": row.state}
