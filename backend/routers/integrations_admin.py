"""
Phase 5 / T5.3 — Admin endpoints for integration keys + circuit breakers.

Endpoints (all gated by ``admin`` permission):

  GET    /api/integrations/keys
  POST   /api/integrations/keys                  — create or rotate
  POST   /api/integrations/keys/{id}/revoke
  GET    /api/integrations/circuit-breakers      — current breaker state
  POST   /api/integrations/circuit-breakers/{id}/reset
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from database import get_db_connection
from routers.auth import get_current_user
from services import integration_keys_service as ks
from utils.i18n import http_error
from utils.permissions import require_permission
from utils.tx import transactional
from integrations.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/integrations", tags=["integrations-admin"])


class IntegrationKeyCreate(BaseModel):
    integration_type: str = Field(..., max_length=40)
    provider: str = Field(..., max_length=60)
    key_name: str = Field(..., max_length=80)
    plaintext_value: str = Field(..., min_length=1)
    valid_to: Optional[datetime] = None
    branch_id: Optional[int] = None
    activate: bool = True


@router.get(
    "/keys",
    dependencies=[Depends(require_permission("admin"))],
)
def list_integration_keys(
    integration_type: Optional[str] = None,
    provider: Optional[str] = None,
    include_revoked: bool = False,
    current_user=Depends(get_current_user),
):
    """List Integration Keys."""
    company_id = current_user.company_id
    with transactional(company_id) as db:
        return ks.list_keys(
            db,
            integration_type=integration_type,
            provider=provider,
            include_revoked=include_revoked,
        )


@router.post(
    "/keys",
    dependencies=[Depends(require_permission("admin"))],
)
def create_or_rotate_key(
    body: IntegrationKeyCreate,
    request: Request,
    current_user=Depends(get_current_user),
):
    """Create Or Rotate Key."""
    company_id = current_user.company_id
    try:
        with transactional(company_id) as db:
            new_id = ks.insert_key(
                db,
                integration_type=body.integration_type,
                provider=body.provider,
                key_name=body.key_name,
                plaintext_value=body.plaintext_value,
                tenant_id=company_id,
                valid_to=body.valid_to,
                branch_id=body.branch_id,
                created_by=current_user.id,
                activate=body.activate,
            )
        return {"id": new_id, "status": "active" if body.activate else "pending"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("integration key create failed")
        raise HTTPException(**http_error(500, "integration_key_store_failed", request))


@router.post(
    "/keys/{key_id}/revoke",
    dependencies=[Depends(require_permission("admin"))],
)
def revoke_integration_key(key_id: int, request: Request, current_user=Depends(get_current_user)):
    """Revoke Integration Key."""
    company_id = current_user.company_id
    try:
        with transactional(company_id) as db:
            ks.revoke_key(db, key_id)
        return {"id": key_id, "status": "revoked"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(**http_error(500, "integration_key_revoke_failed", request))


@router.get(
    "/circuit-breakers",
    dependencies=[Depends(require_permission("admin"))],
)
def list_circuit_breakers(current_user=Depends(get_current_user)):
    """Return the in-memory state of every registered breaker plus DB-persisted
    state for breakers that aren't currently loaded in this worker."""
    company_id = current_user.company_id
    in_memory = [b.snapshot() for b in CircuitBreaker._registry.values()]
    with transactional(company_id) as db:
        rows = db.execute(
            text("""SELECT id, integration_type, provider, state, failure_count,
                           opened_at, opens_until, last_error, updated_at
                      FROM integration_circuit_state
                     ORDER BY integration_type, provider""")
        ).fetchall()
    persisted = [
        {
            "id": r[0],
            "integration_type": r[1],
            "provider": r[2],
            "state": r[3],
            "failure_count": r[4],
            "opened_at": r[5].isoformat() if r[5] else None,
            "opens_until": r[6].isoformat() if r[6] else None,
            "last_error": r[7],
            "updated_at": r[8].isoformat() if r[8] else None,
        }
        for r in rows
    ]
    return {"in_memory": in_memory, "persisted": persisted}


@router.post(
    "/circuit-breakers/{breaker_id}/reset",
    dependencies=[Depends(require_permission("admin"))],
)
def reset_circuit_breaker(breaker_id: int, request: Request, current_user=Depends(get_current_user)):
    """Force a breaker back to ``closed`` (operator override)."""
    company_id = current_user.company_id
    try:
        with transactional(company_id) as db:
            row = db.execute(
                text("""SELECT integration_type, provider FROM integration_circuit_state
                         WHERE id = :id"""),
                {"id": breaker_id},
            ).fetchone()
            if not row:
                raise HTTPException(**http_error(404, "circuit_breaker_not_found", request))
            db.execute(
                text("""UPDATE integration_circuit_state
                           SET state = 'closed', failure_count = 0,
                               opened_at = NULL, opens_until = NULL,
                               last_error = NULL, updated_at = CURRENT_TIMESTAMP
                         WHERE id = :id"""),
                {"id": breaker_id},
            )
        # Also reset in-memory if instance exists in this worker.
        cb = CircuitBreaker._registry.get((row[0], row[1]))
        if cb:
            cb.record_success()
        return {"id": breaker_id, "state": "closed"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(**http_error(500, "circuit_breaker_reset_failed", request))


# ─── T5.4 — Retry Queues & DLQ viewer ─────────────────────────────────────────

@router.get(
    "/payment-retry-queue",
    dependencies=[Depends(require_permission("admin"))],
)
def list_payment_retry_queue(
    status: Optional[str] = None,
    limit: int = 100,
    current_user=Depends(get_current_user),
):
    """List rows from the payment retry queue (most recent first)."""
    company_id = current_user.company_id
    limit = min(max(int(limit or 100), 1), 500)
    with transactional(company_id) as db:
        q = """
            SELECT id, payment_id, provider, amount, currency, idempotency_key,
                   retry_count, max_retries, status, last_attempt_at,
                   next_retry_at, last_error, created_at, updated_at
              FROM payment_retry_queue
        """
        params: dict = {}
        if status:
            q += " WHERE status = :st"
            params["st"] = status
        q += " ORDER BY id DESC LIMIT :lim"
        params["lim"] = limit
        rows = db.execute(text(q), params).fetchall()
        return [
            {
                "id": r[0], "payment_id": r[1], "provider": r[2],
                "amount": float(r[3]) if r[3] is not None else None,
                "currency": r[4], "idempotency_key": r[5],
                "retry_count": r[6], "max_retries": r[7], "status": r[8],
                "last_attempt_at": r[9].isoformat() if r[9] else None,
                "next_retry_at": r[10].isoformat() if r[10] else None,
                "last_error": r[11],
                "created_at": r[12].isoformat() if r[12] else None,
                "updated_at": r[13].isoformat() if r[13] else None,
            }
            for r in rows
        ]


@router.get(
    "/sms-retry-queue",
    dependencies=[Depends(require_permission("admin"))],
)
def list_sms_retry_queue(
    status: Optional[str] = None,
    limit: int = 100,
    current_user=Depends(get_current_user),
):
    """List SMS Retry Queue."""
    company_id = current_user.company_id
    limit = min(max(int(limit or 100), 1), 500)
    with transactional(company_id) as db:
        q = """
            SELECT id, notification_id, provider, recipient_phone, sender_id,
                   retry_count, max_retries, status, last_attempt_at,
                   next_retry_at, last_error, created_at, updated_at
              FROM sms_retry_queue
        """
        params: dict = {}
        if status:
            q += " WHERE status = :st"
            params["st"] = status
        q += " ORDER BY id DESC LIMIT :lim"
        params["lim"] = limit
        rows = db.execute(text(q), params).fetchall()
        return [
            {
                "id": r[0], "notification_id": r[1], "provider": r[2],
                "recipient_phone": r[3], "sender_id": r[4],
                "retry_count": r[5], "max_retries": r[6], "status": r[7],
                "last_attempt_at": r[8].isoformat() if r[8] else None,
                "next_retry_at": r[9].isoformat() if r[9] else None,
                "last_error": r[10],
                "created_at": r[11].isoformat() if r[11] else None,
                "updated_at": r[12].isoformat() if r[12] else None,
            }
            for r in rows
        ]


@router.get(
    "/dlq",
    dependencies=[Depends(require_permission("admin"))],
)
def list_dlq(
    queue_type: Optional[str] = None,
    archived: bool = False,
    limit: int = 100,
    current_user=Depends(get_current_user),
):
    """List Dead-Letter Queue items. By default only unresolved (not archived)."""
    company_id = current_user.company_id
    limit = min(max(int(limit or 100), 1), 500)
    with transactional(company_id) as db:
        q = """
            SELECT id, queue_type, queue_item_id, provider, final_status,
                   reason, archived_at, created_at
              FROM integration_dlq
             WHERE 1=1
        """
        params: dict = {}
        if queue_type:
            q += " AND queue_type = :qt"
            params["qt"] = queue_type
        if not archived:
            q += " AND archived_at IS NULL"
        q += " ORDER BY id DESC LIMIT :lim"
        params["lim"] = limit
        rows = db.execute(text(q), params).fetchall()
        return [
            {
                "id": r[0], "queue_type": r[1], "queue_item_id": r[2],
                "provider": r[3], "final_status": r[4], "reason": r[5],
                "archived_at": r[6].isoformat() if r[6] else None,
                "created_at": r[7].isoformat() if r[7] else None,
            }
            for r in rows
        ]


@router.get(
    "/dlq/{dlq_id}",
    dependencies=[Depends(require_permission("admin"))],
)
def get_dlq_item(dlq_id: int, request: Request, current_user=Depends(get_current_user)):
    """Return a DLQ row with full payload + gateway response."""
    company_id = current_user.company_id
    with transactional(company_id) as db:
        row = db.execute(
            text("""
                SELECT id, queue_type, queue_item_id, provider, final_status,
                       reason, payload, gateway_response, archived_at, created_at
                  FROM integration_dlq WHERE id = :id
            """),
            {"id": dlq_id},
        ).fetchone()
    if not row:
        raise HTTPException(**http_error(404, "dlq_item_not_found", request))
    return {
        "id": row[0], "queue_type": row[1], "queue_item_id": row[2],
        "provider": row[3], "final_status": row[4], "reason": row[5],
        "payload": row[6], "gateway_response": row[7],
        "archived_at": row[8].isoformat() if row[8] else None,
        "created_at": row[9].isoformat() if row[9] else None,
    }


@router.post(
    "/dlq/{dlq_id}/replay",
    dependencies=[Depends(require_permission("admin"))],
)
def replay_dlq_item(dlq_id: int, request: Request, current_user=Depends(get_current_user)):
    """Re-enqueue a DLQ item back into its source queue (resets retry_count=0)
    and archives the DLQ row."""
    company_id = current_user.company_id
    with transactional(company_id) as db:
        row = db.execute(
            text("""SELECT id, queue_type, queue_item_id, archived_at
                      FROM integration_dlq WHERE id = :id"""),
            {"id": dlq_id},
        ).fetchone()
        if not row:
            raise HTTPException(**http_error(404, "dlq_item_not_found", request))
        if row[3] is not None:
            raise HTTPException(**http_error(400, "dlq_item_already_archived", request))

        queue_type, queue_item_id = row[1], row[2]
        if queue_type == "payment":
            updated = db.execute(
                text("""UPDATE payment_retry_queue
                           SET status='pending', retry_count=0,
                               next_retry_at=CURRENT_TIMESTAMP,
                               last_error=NULL,
                               updated_at=CURRENT_TIMESTAMP
                         WHERE id = :id RETURNING id"""),
                {"id": queue_item_id},
            ).fetchone()
        elif queue_type == "sms":
            updated = db.execute(
                text("""UPDATE sms_retry_queue
                           SET status='pending', retry_count=0,
                               next_retry_at=CURRENT_TIMESTAMP,
                               last_error=NULL,
                               updated_at=CURRENT_TIMESTAMP
                         WHERE id = :id RETURNING id"""),
                {"id": queue_item_id},
            ).fetchone()
        else:
            raise HTTPException(**http_error(400, "dlq_unknown_queue_type", request, queue_type=queue_type))

        if not updated:
            raise HTTPException(**http_error(404, "dlq_source_item_not_found", request))

        db.execute(
            text("""UPDATE integration_dlq
                       SET archived_at = CURRENT_TIMESTAMP
                     WHERE id = :id"""),
            {"id": dlq_id},
        )
    return {"id": dlq_id, "replayed": True, "queue_type": queue_type}


@router.post(
    "/dlq/{dlq_id}/archive",
    dependencies=[Depends(require_permission("admin"))],
)
def archive_dlq_item(dlq_id: int, request: Request, current_user=Depends(get_current_user)):
    """Mark a DLQ item as resolved (no replay)."""
    company_id = current_user.company_id
    with transactional(company_id) as db:
        row = db.execute(
            text("SELECT id, archived_at FROM integration_dlq WHERE id = :id"),
            {"id": dlq_id},
        ).fetchone()
        if not row:
            raise HTTPException(**http_error(404, "dlq_item_not_found", request))
        if row[1] is not None:
            return {"id": dlq_id, "archived": True}
        db.execute(
            text("UPDATE integration_dlq SET archived_at = CURRENT_TIMESTAMP WHERE id = :id"),
            {"id": dlq_id},
        )
    return {"id": dlq_id, "archived": True}
