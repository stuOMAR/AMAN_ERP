"""Returns unified endpoints.

Feature 023 — T042.  POST /returns, POST /returns/{id}/post,
POST /returns/{id}/cancel, GET /returns
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session
from typing import Optional

from database import get_company_db
from routers.auth import get_current_user
from schemas import UserResponse
from utils.i18n import http_error
from utils.permissions import check_permission, require_permission

router = APIRouter(prefix="/returns", tags=["returns"])


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


_SOURCE_PERMISSIONS = {
    "sales": {
        "view": "sales.view",
        "create": "sales.approve_return",
        "post": "sales.approve_return",
        "cancel": "sales.void",
    },
    "pos": {
        "view": "pos.view",
        "create": "pos.returns",
        "post": "pos.returns",
        "cancel": "pos.cancel",
    },
    "buying": {
        "view": "buying.view",
        "create": "buying.create",
        "post": "buying.create",
        "cancel": "buying.void",
    },
    "purchase": {
        "view": "buying.view",
        "create": "buying.create",
        "post": "buying.create",
        "cancel": "buying.void",
    },
    "purchases": {
        "view": "buying.view",
        "create": "buying.create",
        "post": "buying.create",
        "cancel": "buying.void",
    },
}


def _require_source_permission(current_user: UserResponse, source: Optional[str], action: str, request: Request):
    source_key = (source or "").strip().lower()
    required = _SOURCE_PERMISSIONS.get(source_key, {}).get(action)
    if not required:
        raise HTTPException(**http_error(400, "invalid_data", request))
    if not check_permission(current_user.permissions or [], required):
        raise HTTPException(**http_error(403, "permission_denied", request))


def _fetch_return_source(db: Session, return_id: int, tenant_id: int) -> Optional[str]:
    row = db.execute(
        text("SELECT source FROM returns_unified WHERE id = :id AND tenant_id = :tid AND deleted_at IS NULL"),
        {"id": return_id, "tid": tenant_id},
    ).fetchone()
    return row.source if row else None


class ReturnCreate(BaseModel):
    source: str
    original_invoice_id: Optional[int] = None
    original_pos_sale_id: Optional[int] = None
    restock_warehouse_id: Optional[int] = None
    lines: list[dict]
    reason: Optional[str] = None


@router.post("", dependencies=[Depends(require_permission(["sales.approve_return", "pos.returns", "buying.create"]))])
async def create_return(
    body: ReturnCreate,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from services.returns_unified_service import create_return
    _require_source_permission(current_user, body.source, "create", request)
    user = _actor(current_user)
    result = create_return(db, tenant_id=user.get("tenant_id", 0), actor=user, **body.model_dump())
    db.commit()
    return result


@router.post("/{return_id}/post", dependencies=[Depends(require_permission(["sales.approve_return", "pos.returns", "buying.create"]))])
async def post_return(
    return_id: int,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from services.returns_unified_service import post_return
    user = _actor(current_user)
    source = _fetch_return_source(db, return_id, user.get("tenant_id", 0))
    if source:
        _require_source_permission(current_user, source, "post", request)
    result = post_return(db, return_id=return_id, tenant_id=user.get("tenant_id", 0), actor=user)
    db.commit()
    return result


@router.post("/{return_id}/cancel", dependencies=[Depends(require_permission(["sales.void", "pos.cancel", "buying.void"]))])
async def cancel_return(
    return_id: int,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from services.returns_unified_service import cancel_return
    user = _actor(current_user)
    source = _fetch_return_source(db, return_id, user.get("tenant_id", 0))
    if source:
        _require_source_permission(current_user, source, "cancel", request)
    result = cancel_return(db, return_id=return_id, tenant_id=user.get("tenant_id", 0), actor=user)
    db.commit()
    return result


@router.get("", dependencies=[Depends(require_permission(["sales.view", "pos.view", "buying.view"]))])
async def list_returns(
    request: Request,
    source: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0),
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if source:
        _require_source_permission(current_user, source, "view", request)
    user = _actor(current_user)
    tid = user.get("tenant_id", 0)

    conditions = ["tenant_id = :tid", "deleted_at IS NULL"]
    params = {"tid": tid, "limit": limit, "offset": offset}

    if source:
        conditions.append("source = :source")
        params["source"] = source
    if state:
        conditions.append("state = :state")
        params["state"] = state

    where = " AND ".join(conditions)
    rows = db.execute(
        text(f"SELECT * FROM returns_unified WHERE {where} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
        params,
    ).fetchall()
    return [dict(r._mapping) for r in rows]
