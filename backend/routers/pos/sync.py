"""
T17 P1 #88 — POS sync conflict management endpoints.

The detection / queueing path lives in ``services.scheduler.process_pos_offline_inbox``,
which writes one row to ``pos_sync_conflicts`` per drift / stock /
duplicate event. This module provides the *resolution* surface a manager
uses to triage those conflicts:

  * ``GET  /pos/sync/conflicts``                — paginated list
  * ``GET  /pos/sync/conflicts/{id}``           — full detail
  * ``POST /pos/sync/conflicts/{id}/resolve``   — accept | reject | merge

"Accepting" a conflict simply marks it resolved (the inbox row was
already processed using server state). "Rejecting" rolls back any
ad-hoc changes the operator made and quarantines the inbox row.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from database import get_db_connection
from routers.auth import get_current_user
from utils.audit import log_activity
from utils.i18n import http_error
from utils.permissions import require_permission

router = APIRouter()


class ConflictResolve(BaseModel):
    resolution: str = Field(..., pattern="^(accepted|rejected|merged)$")
    note: Optional[str] = None


@router.get("/sync/conflicts", response_model=Dict[str, Any],
            dependencies=[Depends(require_permission("pos.manage"))])
def list_conflicts(resolution: Optional[str] = None,
                   session_id: Optional[int] = None,
                   limit: int = 50, offset: int = 0,
                   current_user=Depends(get_current_user)):
    limit = max(1, min(200, int(limit or 50)))
    offset = max(0, int(offset or 0))
    db = get_db_connection(current_user.company_id)
    try:
        clauses = ["1=1"]
        params: Dict[str, Any] = {"lim": limit, "off": offset}
        if resolution:
            clauses.append("resolution = :res")
            params["res"] = resolution
        if session_id:
            clauses.append("session_id = :sid")
            params["sid"] = session_id
        where = " AND ".join(clauses)
        rows = db.execute(text(f"""
            SELECT id, session_id, client_op_id, op_type, conflict_kind,
                   resolution, resolved_by, resolved_at, created_at
            FROM pos_sync_conflicts
            WHERE {where}
            ORDER BY id DESC
            LIMIT :lim OFFSET :off
        """), params).fetchall()
        total = db.execute(text(f"SELECT COUNT(*) FROM pos_sync_conflicts WHERE {where}"),
                           params).scalar() or 0
        return {
            "items": [dict(r._mapping) for r in rows],
            "total": int(total),
            "limit": limit,
            "offset": offset,
        }
    finally:
        db.close()


@router.get("/sync/conflicts/{conflict_id}", response_model=Dict[str, Any],
            dependencies=[Depends(require_permission("pos.manage"))])
def get_conflict(conflict_id: int, current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        row = db.execute(text(
            "SELECT * FROM pos_sync_conflicts WHERE id = :id"
        ), {"id": conflict_id}).fetchone()
        if not row:
            raise HTTPException(**http_error(404, ("pos_conflict_not_found", request)))
        return dict(row._mapping)
    finally:
        db.close()


@router.post("/sync/conflicts/{conflict_id}/resolve",
             response_model=Dict[str, Any],
             dependencies=[Depends(require_permission("pos.manage"))])
def resolve_conflict(conflict_id: int, payload: ConflictResolve,
                     request: Request,
                     current_user=Depends(get_current_user)):
    """Mark a POS sync conflict resolved.

    The actual data merge (if any) was performed by the inbox worker —
    this endpoint records the manager's decision for audit.
    """
    db = get_db_connection(current_user.company_id)
    try:
        row = db.execute(text(
            "SELECT id, resolution FROM pos_sync_conflicts WHERE id = :id FOR UPDATE"
        ), {"id": conflict_id}).fetchone()
        if not row:
            raise HTTPException(**http_error(404, ("pos_conflict_not_found", request)))
        if row.resolution and row.resolution != "pending":
            raise HTTPException(**http_error(400, "pos_conflict_already_resolved", request, status=row.resolution))

        db.execute(text("""
            UPDATE pos_sync_conflicts
            SET resolution = :res,
                resolved_by = :uid,
                resolved_at = NOW()
            WHERE id = :id
        """), {"res": payload.resolution, "uid": current_user.id, "id": conflict_id})
        db.commit()
        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="pos.sync.conflict_resolve",
                     resource_type="pos_sync_conflict",
                     resource_id=str(conflict_id),
                     details={"resolution": payload.resolution, "note": payload.note},
                     request=request)
        return {"id": conflict_id, "resolution": payload.resolution}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
