"""Order → Invoice endpoint.

Feature 023 — T035.  POST /sales/orders/{order_id}/invoice
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session
from typing import Optional

from database import get_company_db
from routers.auth import get_current_user
from schemas import UserResponse

router = APIRouter()


def get_db(current_user: UserResponse = Depends(get_current_user)):
    yield from get_company_db(current_user.company_id)


@router.post("/sales/orders/{order_id}/invoice")
async def order_to_invoice(
    order_id: int,
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key", max_length=64),
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Convert a confirmed sales order to a posted invoice (idempotent)."""
    from services.sales.order_to_invoice import convert_order_to_invoice as do_convert
    import json

    body = {}
    try:
        if request.headers.get("content-type", "").startswith("application/json"):
            body = await request.json()
    except Exception:
        pass

    result = do_convert(
        db,
        order_id=order_id,
        company_id=current_user.company_id,
        actor=current_user,
        idempotency_key=idempotency_key,
        posting_date=body.get("posting_date"),
        memo=body.get("memo"),
    )
    db.commit()
    return result
