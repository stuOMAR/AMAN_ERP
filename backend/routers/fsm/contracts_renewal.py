"""Contract renewal endpoint.

POST /api/fsm/service-contracts/{id}/renew — renew a service contract.
"""
from __future__ import annotations

import logging
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from database import get_db_connection
from services.fsm.contract_renew import renew_contract
from services.permissions.sensitive import require_sensitive_permission
from utils.i18n import i18n_message
from utils.tax_precision import require_idempotency_key

router = APIRouter(prefix="/fsm/service-contracts", tags=["FSM Contracts"])
logger = logging.getLogger(__name__)


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
    request: Request,
    current_user=Depends(require_sensitive_permission("contract.renew")),
):
    """Renew a service contract."""
    require_idempotency_key(request, operation="FSM service contract renewal")
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
    except LookupError:
        logger.exception("Contract not found for renewal")
        raise HTTPException(status_code=404, detail=i18n_message("not_found", request) if request else "Not found")
    except ValueError:
        logger.exception("Validation error in contract renewal")
        raise HTTPException(status_code=422, detail=i18n_message("validation_error", request) if request else "Validation error")
    finally:
        conn.close()
