"""MRP run endpoint.

Feature 023 — T077.  POST /manufacturing/mrp/run
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/manufacturing/mrp", tags=["manufacturing"])


@router.post("/run")
async def run_mrp(request: Request, db: Session = Depends(get_db)):
    from services.manufacturing.mrp import run_mrp
    from utils.permissions import get_current_user

    user = get_current_user(request)
    result = run_mrp(db, tenant_id=user.get("tenant_id", 0), actor=user)
    db.commit()
    return result
