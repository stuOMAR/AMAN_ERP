"""FSM pricelists admin endpoints.

GET    /api/fsm/pricelists           — list pricelists
POST   /api/fsm/pricelists           — create/update pricelist entry
GET    /api/fsm/pricelists/resolve   — resolve price for an item
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from fastapi import Request, APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from typing import Optional

from database import get_db_connection
from services.fsm.pricelists import resolve_price, upsert_pricelist_entry
from utils.i18n import http_error, i18n_message

router = APIRouter(prefix="/api/fsm/pricelists", tags=["FSM Pricelists"])
logger = logging.getLogger(__name__)


class PricelistEntryCreate(BaseModel):
    scope: str  # customer, group, global
    scope_ref_id: Optional[int] = None
    item_id: int
    currency: str
    price: Decimal
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None


def _get_tenant_id(current_user) -> str:
    return str(
        current_user.get("company_id")
        if isinstance(current_user, dict)
        else getattr(current_user, "company_id", 0)
    )


@router.get("")
def list_pricelists(
    scope: Optional[str] = None,
    item_id: Optional[int] = None,
    current_user=None,
):
    """List pricelist entries."""
    tenant_id = _get_tenant_id(current_user)
    conn = get_db_connection(tenant_id)
    try:
        conditions = ["tenant_id = :tid"]
        params = {"tid": int(tenant_id)}

        if scope:
            conditions.append("scope = :scope")
            params["scope"] = scope
        if item_id:
            conditions.append("item_id = :iid")
            params["iid"] = item_id

        where = " AND ".join(conditions)
        query = f"""
                SELECT id, scope, scope_ref_id, item_id, currency, price,
                       valid_from, valid_to
                FROM service_pricelists
                WHERE {where}
                ORDER BY scope, item_id
            """
        rows = conn.execute(
            text(query),  # noqa: sql-lint
            params,
        ).fetchall()

        return [
            {
                "id": r[0], "scope": r[1], "scope_ref_id": r[2],
                "item_id": r[3], "currency": r[4], "price": str(r[5]),
                "valid_from": str(r[6]) if r[6] else None,
                "valid_to": str(r[7]) if r[7] else None,
            }
            for r in rows
        ]
    finally:
        conn.close()


@router.post("")
def create_pricelist_entry(
    request: Request,
    body: PricelistEntryCreate,
    current_user=None,
):
    """Create or update a pricelist entry."""
    tenant_id = _get_tenant_id(current_user)
    conn = get_db_connection(tenant_id)
    try:
        result = upsert_pricelist_entry(
            conn,
            tenant_id=int(tenant_id),
            scope=body.scope,
            scope_ref_id=body.scope_ref_id,
            item_id=body.item_id,
            currency=body.currency,
            price=body.price,
            valid_from=body.valid_from,
            valid_to=body.valid_to,
        )
        return result
    except Exception as e:
        logger.exception("Error creating pricelist entry")
        raise HTTPException(status_code=400, detail=i18n_message("internal_error", request) if request else "Internal error")
    finally:
        conn.close()


@router.get("/resolve")
def resolve_item_price(request: Request, 
    item_id: int,
    currency: str,
    customer_id: Optional[int] = None,
    customer_group_id: Optional[int] = None,
    current_user=None,
):
    """Resolve price for an item from the pricelist hierarchy."""
    tenant_id = _get_tenant_id(current_user)
    conn = get_db_connection(tenant_id)
    try:
        price, level = resolve_price(
            conn,
            tenant_id=int(tenant_id),
            item_id=item_id,
            currency=currency,
            customer_id=customer_id,
            customer_group_id=customer_group_id,
        )

        if price is None:
            raise HTTPException(**http_error(404, "pricelistno_price", request))

        return {"price": str(price), "level": level}
    finally:
        conn.close()
