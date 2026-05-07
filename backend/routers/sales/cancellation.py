"""Sales invoice cancellation endpoint.

Feature 023 — T039.  POST /sales/invoices/{id}/cancel
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from database import get_company_db
from routers.auth import get_current_user
from schemas import UserResponse

router = APIRouter()


class CancellationRequest(BaseModel):
    reason: Optional[str] = None
    restock_warehouse_id: Optional[int] = None


def get_db(current_user: UserResponse = Depends(get_current_user)):
    yield from get_company_db(current_user.company_id)


@router.post("/sales/invoices/{invoice_id}/cancel")
async def cancel_invoice(
    invoice_id: int,
    body: CancellationRequest,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from services.sales.sales_cancellation import cancel_invoice as do_cancel

    result = do_cancel(
        db,
        invoice_id=invoice_id,
        tenant_id=current_user.company_id,
        actor=current_user,
        reason=body.reason or "",
        restock_warehouse_id=body.restock_warehouse_id,
    )
    db.commit()
    return result
