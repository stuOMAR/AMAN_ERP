"""MRP recommendations endpoints.

Feature 023 — T077.  GET /manufacturing/mrp/recommendations,
POST /manufacturing/mrp/recommendations/{id}/accept
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from typing import Optional

from database import get_company_db
from routers.auth import get_current_user
from schemas import UserResponse
from utils.i18n import http_error
from utils.permissions import require_module, require_permission

router = APIRouter(
    prefix="/manufacturing/mrp",
    tags=["manufacturing"],
    dependencies=[Depends(require_module("manufacturing"))],
)


def get_db(current_user: UserResponse = Depends(get_current_user)):
    yield from get_company_db(current_user.company_id)


def _actor(current_user: UserResponse) -> dict:
    return {
        "id": current_user.id,
        "user_id": current_user.id,
        "username": current_user.username,
        "role": current_user.role,
        "company_id": current_user.company_id,
        "tenant_id": current_user.company_id,
        "permissions": current_user.permissions or [],
    }


@router.get("/recommendations", dependencies=[Depends(require_permission("manufacturing.view"))])
async def list_recommendations(
    request: Request,
    run_id: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0),
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from sqlalchemy import text

    user = _actor(current_user)
    tid = user.get("tenant_id", 0)

    conditions = ["tenant_id = :tid"]
    params: dict = {"tid": tid, "limit": limit, "offset": offset}

    if run_id:
        conditions.append("run_id = :run_id")
        params["run_id"] = run_id
    if state:
        conditions.append("state = :state")
        params["state"] = state

    where = " AND ".join(conditions)
    rows = db.execute(
        text(f"SELECT * FROM mrp_recommendations WHERE {where} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
        params,
    ).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/recommendations/{rec_id}/accept", dependencies=[Depends(require_permission("manufacturing.manage"))])
async def accept_recommendation(
    rec_id: int,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from sqlalchemy import text

    user = _actor(current_user)
    tid = user.get("tenant_id", 0)

    result = db.execute(
        text("""
            UPDATE mrp_recommendations
            SET state = 'accepted', accepted_by = :uid, updated_at = clock_timestamp()
            WHERE id = :id AND tenant_id = :tid AND state = 'open'
            RETURNING id, item_id, warehouse_id, recommended_qty
        """),
        {"id": rec_id, "tid": tid, "uid": user.get("id")},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(**http_error(404, "mrp_recommendation_not_found", request))

    db.commit()
    return dict(row._mapping)
