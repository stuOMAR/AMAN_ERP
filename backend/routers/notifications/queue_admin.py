"""Notifications queue admin endpoints.

GET  /notifications/queue           — list queue entries
POST /notifications/queue/{id}/retry — retry a failed notification
GET  /notifications/dlq             — list dead-letter queue
POST /notifications/dlq/{id}/requeue — requeue from DLQ
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from database import get_db_connection
from services.permissions.sensitive import require_sensitive_permission

router = APIRouter(tags=["Notifications Admin"])


def _get_tenant_id(current_user) -> str:
    return str(
        current_user.get("company_id")
        if isinstance(current_user, dict)
        else getattr(current_user, "company_id", 0)
    )


@router.get("/queue")
def list_queue(
    state: str = None,
    channel: str = None,
    limit: int = 50,
    current_user=Depends(require_sensitive_permission("notifications.admin")),
):
    """List notification queue entries."""
    tenant_id = _get_tenant_id(current_user)
    conn = get_db_connection(tenant_id)
    try:
        conditions = ["tenant_id = :tnt"]
        params = {"tnt": int(tenant_id), "limit": limit}

        if state:
            conditions.append("state = :state")
            params["state"] = state
        if channel:
            conditions.append("channel = :channel")
            params["channel"] = channel

        where = " AND ".join(conditions)
        rows = conn.execute(
            text(f"""
                SELECT id, event_type, channel, recipient, state,
                       attempts, last_error, created_at, sent_at
                FROM notifications_queue
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT :limit
            """),
            params,
        ).fetchall()

        return [
            {
                "id": r[0], "event_type": r[1], "channel": r[2],
                "recipient": r[3], "state": r[4], "attempts": r[5],
                "last_error": r[6],
                "created_at": r[7].isoformat() if r[7] else None,
                "sent_at": r[8].isoformat() if r[8] else None,
            }
            for r in rows
        ]
    finally:
        conn.close()


@router.post("/queue/{notif_id}/retry")
def retry_notification(
    notif_id: int,
    current_user=Depends(require_sensitive_permission("notifications.admin")),
):
    """Retry a failed notification."""
    tenant_id = _get_tenant_id(current_user)
    conn = get_db_connection(tenant_id)
    try:
        result = conn.execute(
            text("""
                UPDATE notifications_queue
                SET state = 'pending', next_attempt_at = now(), last_error = NULL
                WHERE id = :nid AND tenant_id = :tnt AND state IN ('failed', 'dlq')
            """),
            {"nid": notif_id, "tnt": int(tenant_id)},
        )
        if result.rowcount == 0:
            raise HTTPException(**http_error(404, "notification_not_found_or_not_retryable", request))
        conn.commit()
        return {"retried": True, "id": notif_id}
    finally:
        conn.close()


@router.get("/dlq")
def list_dlq(
    limit: int = 50,
    current_user=Depends(require_sensitive_permission("notifications.admin")),
):
    """List dead-letter queue entries."""
    tenant_id = _get_tenant_id(current_user)
    conn = get_db_connection(tenant_id)
    try:
        rows = conn.execute(
            text("""
                SELECT id, event_type, channel, recipient, attempts,
                       last_error, dlq_at, created_at
                FROM notifications_queue
                WHERE tenant_id = :tnt AND state = 'dlq'
                ORDER BY dlq_at DESC
                LIMIT :limit
            """),
            {"tnt": int(tenant_id), "limit": limit},
        ).fetchall()

        return [
            {
                "id": r[0], "event_type": r[1], "channel": r[2],
                "recipient": r[3], "attempts": r[4], "last_error": r[5],
                "dlq_at": r[6].isoformat() if r[6] else None,
                "created_at": r[7].isoformat() if r[7] else None,
            }
            for r in rows
        ]
    finally:
        conn.close()


@router.post("/dlq/{notif_id}/requeue")
def requeue_from_dlq(
    notif_id: int,
    current_user=Depends(require_sensitive_permission("notifications.admin")),
):
    """Requeue a notification from the DLQ."""
    tenant_id = _get_tenant_id(current_user)
    conn = get_db_connection(tenant_id)
    try:
        result = conn.execute(
            text("""
                UPDATE notifications_queue
                SET state = 'pending', dlq_at = NULL, next_attempt_at = now(),
                    attempts = 0, last_error = NULL
                WHERE id = :nid AND tenant_id = :tnt AND state = 'dlq'
            """),
            {"nid": notif_id, "tnt": int(tenant_id)},
        )
        if result.rowcount == 0:
            raise HTTPException(**http_error(404, "notification_not_found_in_dlq", request))
        conn.commit()
        return {"requeued": True, "id": notif_id}
    finally:
        conn.close()
