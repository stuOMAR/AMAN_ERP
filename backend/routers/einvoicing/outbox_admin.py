"""ZATCA outbox admin endpoints.

Feature 023 — T066. GET /einvoicing/outbox, POST /einvoicing/outbox/{id}/reprocess

Audit fixes (F-NEW-007 / F-NEW-008 / F-NEW-026 / F-NEW-027):
  * Bind every handler to the per-tenant DB via ``transactional(company_id)``
    (the prior version used the global ``get_db`` Session).
  * Gate both routes with ``require_permission`` so a low-privilege account
    cannot list or replay ZATCA submissions.
  * F-NEW-027 (R-MISSING-IDEMPOTENCY): the reprocess endpoint accepts an
    ``Idempotency-Key`` header and persists it on
    ``zatca_outbox.last_idempotency_key`` (column added in audit batch 10,
    migration 0030). Two concurrent retry clicks with the same key collapse
    to a single state transition; the second call returns the recorded
    result rather than re-flipping the row.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text

from utils.permissions import (
    get_current_user,
    require_permission,
    require_sensitive_permission,
)
from utils.tax_precision import require_idempotency_key
from utils.tx import transactional
from utils.i18n import http_error

router = APIRouter(prefix="/einvoicing/outbox", tags=["einvoicing"])


@router.get(
    "",
    dependencies=[Depends(require_permission(["taxes.manage", "settings.view"]))],
)
async def list_outbox(
    request: Request,
    state: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    current_user=Depends(get_current_user),
):
    """List ZATCA outbox rows for the caller's tenant DB.

    PR16-fix: ``zatca_outbox.tenant_id`` is a BIGINT but ``company_id``
    on the ORM session is the tenant identifier string used to choose
    the per-tenant DB engine — feeding it as ``tenant_id`` into the
    WHERE clause yielded zero rows on PostgreSQL. The per-tenant DB
    binding (``transactional(company_id)`` opens the company's own
    schema) already provides isolation, so we drop the redundant
    ``tenant_id`` filter rather than coerce one identifier into the
    type of the other.
    """
    with transactional(current_user.company_id) as db:
        conditions: list[str] = []
        params: dict = {"limit": limit, "offset": offset}
        if state:
            conditions.append("state = :state")
            params["state"] = state

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        rows = db.execute(
            text(
                f"""
                SELECT id, invoice_id, state, attempts, max_attempts,
                       last_error, next_attempt_at, created_at, updated_at
                FROM zatca_outbox{where}
                ORDER BY created_at DESC LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).fetchall()
        return [dict(r._mapping) for r in rows]


@router.post(
    "/{outbox_id}/reprocess",
    dependencies=[
        Depends(
            require_sensitive_permission(
                ["taxes.manage", "einvoicing.manage"], critical=True
            )
        )
    ],
)
async def reprocess_outbox(
    outbox_id: int,
    request: Request,
    current_user=Depends(get_current_user),
):
    """Re-queue a failed/dead-letter row for the caller's tenant.

    F-NEW-027 (R-MISSING-IDEMPOTENCY): callers must supply an
    ``Idempotency-Key`` header. Replays of the same key on the same
    outbox row collapse to a no-op and return the already-recorded
    state, so two concurrent retry clicks cannot double-submit the
    invoice to ZATCA. The key is persisted on
    ``zatca_outbox.last_idempotency_key``.
    """
    idempotency_key = require_idempotency_key(request, operation="ZATCA outbox reprocess")

    with transactional(current_user.company_id) as db:
        # PR16-fix: per-tenant DB binding via transactional() already
        # isolates rows; the prior ``tenant_id = :tid`` filter coerced
        # ``company_id`` (string) into a BIGINT column, which silently
        # matched no rows on PostgreSQL.

        # Idempotency probe: if the same row was already processed with
        # this key, return the prior outcome without re-flipping state.
        prior = db.execute(
            text(
                """
                SELECT id, state, last_idempotency_key
                FROM zatca_outbox
                WHERE id = :id
                """
            ),
            {"id": outbox_id},
        ).fetchone()
        if prior is None:
            raise HTTPException(
                **http_error(
                    404,
                    "outbox_row_not_found_or_not_in_reprocessable_state",
                    request,
                )
            )
        if prior.last_idempotency_key == idempotency_key:
            return {"id": prior.id, "state": prior.state, "idempotent": True}

        result = db.execute(
            text(
                """
                UPDATE zatca_outbox
                SET state = 'pending', attempts = 0, last_error = NULL,
                    next_attempt_at = clock_timestamp(),
                    updated_at = clock_timestamp(),
                    last_idempotency_key = :idem_key
                WHERE id = :id
                  AND state IN ('failed', 'dead_letter')
                RETURNING id, state
                """
            ),
            {
                "id": outbox_id,
                "idem_key": idempotency_key,
            },
        )
        row = result.fetchone()
        if not row:
            raise HTTPException(
                **http_error(
                    404,
                    "outbox_row_not_found_or_not_in_reprocessable_state",
                    request,
                )
            )
        return {"id": row.id, "state": row.state}
