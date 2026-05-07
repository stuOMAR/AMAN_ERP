"""Contract renewal endpoint.

POST /api/fsm/service-contracts/{id}/renew — renew a service contract.
"""
from __future__ import annotations

from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from database import get_db_connection
from services.fsm.contract_renew import renew_contract
from services.permissions.sensitive import require_sensitive_permission

router = APIRouter(prefix="/api/fsm/service-contracts", tags=["FSM Contracts"])


class RenewRequest(BaseModel):
    new_start_date: date
    new_end_date: date
    generate_invoice: bool = False


def _get_tenant_id(current_user) -> str:
    return str(
        current_user.get("company_id")
        if isinstance(current_user, dict)
        else getattr(current_user, "company_id", 0)
    )


def _get_user_id(current_user) -> int:
    return (
        current_user.get("id")
        if isinstance(current_user, dict)
        else getattr(current_user, "id", 0)
    )


@router.post("/{contract_id}/renew")
def renew(
    contract_id: int,
    body: RenewRequest,
    current_user=Depends(require_sensitive_permission("contract.renew")),
):
    """Renew a service contract."""
    tenant_id = _get_tenant_id(current_user)
    conn = get_db_connection(tenant_id)
    try:
        result = renew_contract(
            conn,
            tenant_id=int(tenant_id),
            contract_id=contract_id,
            new_start_date=body.new_start_date,
            new_end_date=body.new_end_date,
            generate_invoice=body.generate_invoice,
            actor_id=_get_user_id(current_user),
        )
        return result
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    finally:
        conn.close()
