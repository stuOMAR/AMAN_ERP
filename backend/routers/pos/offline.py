"""POS offline batch endpoints.

Feature 023 — T050.  POST /pos/offline/batches, GET /pos/offline/batches,
POST /pos/offline/batches/{id}/retry
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from database import get_company_db
from routers.auth import get_current_user
from schemas import UserResponse

router = APIRouter()


def get_db(current_user: UserResponse = Depends(get_current_user)):
    yield from get_company_db(current_user.company_id)


class OfflineBatchSubmit(BaseModel):
    device_id: str
    client_uuid: str
    warehouse_id: int
    lines: list[dict]


@router.post("/pos/offline/batches")
async def submit_batch(body: OfflineBatchSubmit, request: Request,
                       current_user: UserResponse = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    from sqlalchemy import text
    import json

    result = db.execute(
        text("""
            INSERT INTO pos_offline_batches (device_id, client_uuid, payload, state, queued_at)
            VALUES (:device, :uuid, :payload, 'queued', clock_timestamp())
            ON CONFLICT (device_id, client_uuid) DO NOTHING
            RETURNING id
        """),
        {
            "device": body.device_id,
            "uuid": body.client_uuid,
            "payload": json.dumps({"lines": body.lines, "warehouse_id": body.warehouse_id}),
        },
    )
    row = result.fetchone()
    if row:
        db.commit()
        return {"id": row.id, "status": "queued"}
    else:
        return {"status": "duplicate", "message": "Batch already submitted"}


@router.get("/pos/offline/batches")
async def list_batches(
    request: Request,
    device_id: str = Query(...),
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from sqlalchemy import text

    rows = db.execute(
        text("""
            SELECT id, device_id, client_uuid, state, failure_reason_code, failure_detail,
                   pos_sale_id, queued_at, processed_at
            FROM pos_offline_batches
            WHERE device_id = :device
            ORDER BY queued_at DESC LIMIT 100
        """),
        {"device": device_id},
    ).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/pos/offline/batches/{batch_id}/retry")
async def retry_batch(batch_id: int, request: Request,
                      current_user: UserResponse = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    from sqlalchemy import text

    result = db.execute(
        text("""
            UPDATE pos_offline_batches
            SET state = 'queued', failure_reason_code = NULL, failure_detail = NULL,
                processed_at = NULL, updated_at = clock_timestamp()
            WHERE id = :id AND state IN ('manual_review', 'failed')
            RETURNING id
        """),
        {"id": batch_id},
    )
    if result.fetchone():
        db.commit()
        return {"status": "queued", "id": batch_id}
    raise HTTPException(status_code=404, detail="Batch not found or not in retryable state")
