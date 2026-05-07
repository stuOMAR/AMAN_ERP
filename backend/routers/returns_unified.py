"""Returns unified endpoints.

Feature 023 — T042.  POST /returns, POST /returns/{id}/post,
POST /returns/{id}/cancel, GET /returns
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db

router = APIRouter(prefix="/returns", tags=["returns"])


class ReturnCreate(BaseModel):
    source: str
    original_invoice_id: Optional[int] = None
    original_pos_sale_id: Optional[int] = None
    restock_warehouse_id: Optional[int] = None
    lines: list[dict]
    reason: Optional[str] = None


@router.post("")
async def create_return(body: ReturnCreate, request: Request, db: Session = Depends(get_db)):
    from services.returns_unified_service import create_return
    from utils.permissions import get_current_user
    user = get_current_user(request)
    result = create_return(db, tenant_id=user.get("tenant_id", 0), actor=user, **body.model_dump())
    db.commit()
    return result


@router.post("/{return_id}/post")
async def post_return(return_id: int, request: Request, db: Session = Depends(get_db)):
    from services.returns_unified_service import post_return
    from utils.permissions import get_current_user
    user = get_current_user(request)
    result = post_return(db, return_id=return_id, tenant_id=user.get("tenant_id", 0), actor=user)
    db.commit()
    return result


@router.post("/{return_id}/cancel")
async def cancel_return(return_id: int, request: Request, db: Session = Depends(get_db)):
    from services.returns_unified_service import cancel_return
    from utils.permissions import get_current_user
    user = get_current_user(request)
    result = cancel_return(db, return_id=return_id, tenant_id=user.get("tenant_id", 0), actor=user)
    db.commit()
    return result


@router.get("")
async def list_returns(
    request: Request,
    source: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: Session = Depends(get_db),
):
    from utils.permissions import get_current_user
    from sqlalchemy import text
    user = get_current_user(request)
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
