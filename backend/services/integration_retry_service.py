"""
Phase 5 / T5.4 — Payment & SMS retry dispatchers.

Each dispatcher pulls due rows from its retry queue, attempts re-delivery
via the configured gateway, and either marks the row succeeded or schedules
the next retry with exponential backoff (60s → 300s → 1800s). After
``max_retries`` attempts the row is escalated to ``integration_dlq``.

Scheduler-job entry points (registered in :mod:`services.scheduler`):

  * :func:`process_payment_retries_all_tenants`
  * :func:`process_sms_retries_all_tenants`
"""

from __future__ import annotations

import json
import logging
from typing import Callable, Optional

from sqlalchemy import text

from services.audit_sanitizer import sanitize_for_audit

logger = logging.getLogger(__name__)

# Exponential backoff — same shape as `retry_failed_notifications` (T019).
_BACKOFF_SECONDS = {0: 60, 1: 300, 2: 1800}
_MAX_RETRIES_DEFAULT = 3


# ─── shared helpers ─────────────────────────────────────────────────────────

def _sanitize_external_payload(value):
    return sanitize_for_audit(value, context="integration_retry")


def _safe_error(exc: Exception) -> str:
    return f"{exc.__class__.__name__}"

def _next_backoff_clause(retry_count: int) -> str:
    """Return a SQL expression computing ``next_retry_at = NOW() + INTERVAL`` ."""
    seconds = _BACKOFF_SECONDS.get(retry_count, 1800)
    return f"CURRENT_TIMESTAMP + INTERVAL '{seconds} seconds'"


def _move_to_dlq(conn, *, queue_type: str, queue_item_id: int, provider: Optional[str],
                 reason: str, payload: dict, gateway_response: Optional[dict]) -> None:
    safe_payload = _sanitize_external_payload(payload or {})
    safe_gateway_response = _sanitize_external_payload(gateway_response or {})
    conn.execute(
        text("""
            INSERT INTO integration_dlq (
                queue_type, queue_item_id, provider, final_status, reason,
                payload, gateway_response
            ) VALUES (
                :qt, :qi, :pr, 'permanently_failed', :rs,
                CAST(:pl AS JSONB), CAST(:gr AS JSONB)
            )
        """),
        {
            "qt": queue_type, "qi": queue_item_id, "pr": provider,
            "rs": str(_sanitize_external_payload(reason or ""))[:1000],
            "pl": json.dumps(safe_payload, default=str),
            "gr": json.dumps(safe_gateway_response, default=str) if gateway_response else None,
        },
    )


# ─── Payments ───────────────────────────────────────────────────────────────

def enqueue_payment_retry(
    conn, *,
    payment_id: Optional[int],
    provider: str,
    amount,
    currency: str,
    request_payload: dict,
    error: str,
    idempotency_key: Optional[str] = None,
) -> int:
    """Insert a fresh row into ``payment_retry_queue`` (retry_count = 0)."""
    new_id = conn.execute(
        text("""
            INSERT INTO payment_retry_queue (
                payment_id, provider, amount, currency, idempotency_key,
                request_payload, retry_count, status, last_error,
                next_retry_at
            ) VALUES (
                :pid, :pr, :amt, :cur, :ik,
                CAST(:rp AS JSONB), 0, 'pending', :err,
                CURRENT_TIMESTAMP + INTERVAL '60 seconds'
            ) RETURNING id
        """),
        {
            "pid": payment_id, "pr": provider, "amt": amount, "cur": currency,
            "ik": idempotency_key,
            "rp": json.dumps(request_payload or {}, default=str),
            "err": (error or "")[:500],
        },
    ).scalar()
    return int(new_id)


def process_payment_retries(conn, attempt_callback: Callable[[dict], dict]) -> dict:
    """Process all due payment retries for one tenant connection.

    ``attempt_callback`` receives the row as a dict and must return a dict::

        {"status": "succeeded" | "failed", "gateway_response": {...},
         "error": "..." (optional)}

    Returns a stats dict.
    """
    stats = {"processed": 0, "succeeded": 0, "retried": 0, "dlq": 0}

    # Atomically claim rows so concurrent workers don't double-charge.
    rows = conn.execute(
        text("""
            UPDATE payment_retry_queue
               SET status = 'processing',
                   last_attempt_at = CURRENT_TIMESTAMP,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id IN (
                 SELECT id FROM payment_retry_queue
                  WHERE status = 'pending'
                    AND next_retry_at <= CURRENT_TIMESTAMP
                  ORDER BY next_retry_at
                  LIMIT 100
                  FOR UPDATE SKIP LOCKED
             )
            RETURNING id, payment_id, provider, amount, currency,
                      idempotency_key, request_payload, retry_count, max_retries
        """),
    ).fetchall()
    conn.commit() if hasattr(conn, "commit") else None

    for r in rows:
        row = {
            "id": r[0], "payment_id": r[1], "provider": r[2],
            "amount": r[3], "currency": r[4],
            "idempotency_key": r[5], "request_payload": r[6],
            "retry_count": r[7], "max_retries": r[8],
        }
        stats["processed"] += 1
        try:
            outcome = attempt_callback(row)
        except Exception as e:
            logger.exception("[payment-retry] gateway call raised for row %s", row["id"])
            outcome = {"status": "failed", "error": _safe_error(e), "gateway_response": None}

        new_retry_count = (row["retry_count"] or 0) + 1
        if outcome.get("status") == "succeeded":
            conn.execute(
                text("""
                    UPDATE payment_retry_queue
                       SET status = 'succeeded',
                           retry_count = :rc,
                           gateway_response = CAST(:gr AS JSONB),
                           updated_at = CURRENT_TIMESTAMP
                     WHERE id = :id
                """),
                {"id": row["id"], "rc": new_retry_count,
                 "gr": json.dumps(outcome.get("gateway_response"), default=str)
                 if outcome.get("gateway_response") else None},
            )
            stats["succeeded"] += 1
        elif new_retry_count >= (row["max_retries"] or _MAX_RETRIES_DEFAULT):
            _move_to_dlq(
                conn,
                queue_type="payment", queue_item_id=row["id"], provider=row["provider"],
                reason=outcome.get("error") or "max retries exceeded",
                payload=row["request_payload"] or {},
                gateway_response=outcome.get("gateway_response"),
            )
            conn.execute(
                text("""UPDATE payment_retry_queue
                           SET status = 'permanently_failed',
                               retry_count = :rc,
                               last_error = :err,
                               gateway_response = CAST(:gr AS JSONB),
                               updated_at = CURRENT_TIMESTAMP
                         WHERE id = :id"""),
                {"id": row["id"], "rc": new_retry_count,
                 "err": (outcome.get("error") or "")[:500],
                 "gr": json.dumps(outcome.get("gateway_response"), default=str)
                 if outcome.get("gateway_response") else None},
            )
            stats["dlq"] += 1
        else:
            conn.execute(
                text(f"""
                    UPDATE payment_retry_queue
                       SET status = 'pending',
                           retry_count = :rc,
                           last_error = :err,
                           gateway_response = CAST(:gr AS JSONB),
                           next_retry_at = {_next_backoff_clause(new_retry_count)},
                           updated_at = CURRENT_TIMESTAMP
                     WHERE id = :id
                """),
                {"id": row["id"], "rc": new_retry_count,
                 "err": (outcome.get("error") or "")[:500],
                 "gr": json.dumps(outcome.get("gateway_response"), default=str)
                 if outcome.get("gateway_response") else None},
            )
            stats["retried"] += 1

    return stats


# ─── SMS ────────────────────────────────────────────────────────────────────

def enqueue_sms_retry(
    conn, *,
    notification_id: Optional[int],
    provider: str,
    recipient_phone: str,
    message_text: str,
    sender_id: Optional[str],
    error: str,
) -> int:
    new_id = conn.execute(
        text("""
            INSERT INTO sms_retry_queue (
                notification_id, provider, recipient_phone, message_text, sender_id,
                retry_count, status, last_error, next_retry_at
            ) VALUES (
                :nid, :pr, :ph, :msg, :sid,
                0, 'pending', :err,
                CURRENT_TIMESTAMP + INTERVAL '60 seconds'
            ) RETURNING id
        """),
        {
            "nid": notification_id, "pr": provider,
            "ph": recipient_phone, "msg": message_text, "sid": sender_id,
            "err": (error or "")[:500],
        },
    ).scalar()
    return int(new_id)


def process_sms_retries(conn, send_callback: Callable[[dict], dict]) -> dict:
    """Process all due SMS retries for one tenant connection.

    ``send_callback(row) -> {"status": "sent"|"failed",
                             "gateway_response": {...},
                             "error": "..." (optional)}``
    """
    stats = {"processed": 0, "sent": 0, "retried": 0, "dlq": 0}

    rows = conn.execute(
        text("""
            UPDATE sms_retry_queue
               SET status = 'processing',
                   last_attempt_at = CURRENT_TIMESTAMP,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id IN (
                 SELECT id FROM sms_retry_queue
                  WHERE status = 'pending'
                    AND next_retry_at <= CURRENT_TIMESTAMP
                  ORDER BY next_retry_at
                  LIMIT 200
                  FOR UPDATE SKIP LOCKED
             )
            RETURNING id, notification_id, provider, recipient_phone,
                      message_text, sender_id, retry_count, max_retries
        """),
    ).fetchall()
    conn.commit() if hasattr(conn, "commit") else None

    for r in rows:
        row = {
            "id": r[0], "notification_id": r[1], "provider": r[2],
            "recipient_phone": r[3], "message_text": r[4],
            "sender_id": r[5], "retry_count": r[6], "max_retries": r[7],
        }
        stats["processed"] += 1
        try:
            outcome = send_callback(row)
        except Exception as e:
            logger.exception("[sms-retry] gateway call raised for row %s", row["id"])
            outcome = {"status": "failed", "error": _safe_error(e), "gateway_response": None}

        new_retry_count = (row["retry_count"] or 0) + 1
        if outcome.get("status") == "sent":
            conn.execute(
                text("""
                    UPDATE sms_retry_queue
                       SET status = 'sent', retry_count = :rc,
                           gateway_response = CAST(:gr AS JSONB),
                           updated_at = CURRENT_TIMESTAMP
                     WHERE id = :id
                """),
                {"id": row["id"], "rc": new_retry_count,
                 "gr": json.dumps(outcome.get("gateway_response"), default=str)
                 if outcome.get("gateway_response") else None},
            )
            stats["sent"] += 1
        elif new_retry_count >= (row["max_retries"] or _MAX_RETRIES_DEFAULT):
            _move_to_dlq(
                conn,
                queue_type="sms", queue_item_id=row["id"], provider=row["provider"],
                reason=outcome.get("error") or "max retries exceeded",
                payload={
                    "recipient_phone": row["recipient_phone"],
                    "sender_id": row["sender_id"],
                    "message_text_preview": (row["message_text"] or "")[:160],
                },
                gateway_response=outcome.get("gateway_response"),
            )
            conn.execute(
                text("""UPDATE sms_retry_queue
                           SET status = 'permanently_failed',
                               retry_count = :rc,
                               last_error = :err,
                               gateway_response = CAST(:gr AS JSONB),
                               updated_at = CURRENT_TIMESTAMP
                         WHERE id = :id"""),
                {"id": row["id"], "rc": new_retry_count,
                 "err": (outcome.get("error") or "")[:500],
                 "gr": json.dumps(outcome.get("gateway_response"), default=str)
                 if outcome.get("gateway_response") else None},
            )
            stats["dlq"] += 1
        else:
            conn.execute(
                text(f"""
                    UPDATE sms_retry_queue
                       SET status = 'pending',
                           retry_count = :rc,
                           last_error = :err,
                           gateway_response = CAST(:gr AS JSONB),
                           next_retry_at = {_next_backoff_clause(new_retry_count)},
                           updated_at = CURRENT_TIMESTAMP
                     WHERE id = :id
                """),
                {"id": row["id"], "rc": new_retry_count,
                 "err": (outcome.get("error") or "")[:500],
                 "gr": json.dumps(outcome.get("gateway_response"), default=str)
                 if outcome.get("gateway_response") else None},
            )
            stats["retried"] += 1

    return stats


# ─── Default gateway callbacks ──────────────────────────────────────────────

def default_payment_attempt(row: dict) -> dict:
    """Replay the original charge against the configured payment gateway.

    Pulls the live :class:`PaymentGateway` adapter for ``row['provider']``
    from :mod:`integrations.payments.registry` and invokes ``create_charge``.
    """
    try:
        from integrations.payments.registry import get_gateway as get_payment_gateway
    except Exception as e:
        return {"status": "failed", "error": f"payments registry unavailable: {_safe_error(e)}"}

    try:
        gateway = get_payment_gateway(row.get("provider"))
    except Exception as e:
        return {"status": "failed", "error": _safe_error(e)}

    payload = row.get("request_payload") or {}
    source = payload.get("source") or {}
    metadata = payload.get("metadata") or {}
    if row.get("idempotency_key"):
        metadata["idempotency_key"] = row["idempotency_key"]
    try:
        result = gateway.create_charge(
            amount=row["amount"], currency=row["currency"],
            source=source, metadata=metadata,
        )
    except Exception as e:
        return {"status": "failed", "error": _safe_error(e)}

    if result.status in ("captured", "authorised"):
        return {"status": "succeeded",
                "gateway_response": {"charge_id": result.charge_id, "status": result.status,
                                     **(result.gateway_response or {})}}
    return {"status": "failed",
            "error": str(_sanitize_external_payload(result.error_message or f"unexpected status {result.status}")),
            "gateway_response": {"charge_id": result.charge_id, "status": result.status,
                                 **(result.gateway_response or {})}}


def default_sms_send(row: dict) -> dict:
    try:
        from integrations.sms.registry import get_gateway as get_sms_gateway
    except Exception as e:
        return {"status": "failed", "error": f"sms registry unavailable: {_safe_error(e)}"}

    try:
        gateway = get_sms_gateway(row.get("provider"))
    except Exception as e:
        return {"status": "failed", "error": _safe_error(e)}

    try:
        result = gateway.send(
            to=row["recipient_phone"],
            message=row["message_text"],
            sender=row.get("sender_id"),
        )
    except Exception as e:
        return {"status": "failed", "error": _safe_error(e)}

    if result.status in ("sent", "delivered", "queued"):
        return {"status": "sent",
                "gateway_response": {"message_id": result.message_id, "segments": result.segments,
                                     **(result.gateway_response or {})}}
    return {"status": "failed",
            "error": str(_sanitize_external_payload(result.error_message or f"unexpected status {result.status}")),
            "gateway_response": {"message_id": result.message_id,
                                 **(result.gateway_response or {})}}


# ─── Cross-tenant scheduler entry points ────────────────────────────────────

def _iter_tenant_engines():
    from database import _get_all_company_db_names
    from services.scheduler import _get_company_engine_for_db
    for db_name in _get_all_company_db_names():
        try:
            yield db_name, _get_company_engine_for_db(db_name)
        except Exception:
            logger.exception("[retry] could not open engine for %s", db_name)


def process_payment_retries_all_tenants() -> None:
    """APScheduler entry point — iterate all tenants and process due payment retries."""
    for db_name, engine in _iter_tenant_engines():
        try:
            with engine.begin() as conn:
                # Skip tenants that don't yet have the queue table.
                exists = conn.execute(
                    text("SELECT to_regclass('payment_retry_queue')")
                ).scalar()
                if not exists:
                    continue
                stats = process_payment_retries(conn, default_payment_attempt)
                if stats["processed"]:
                    logger.info("[payment-retry][%s] %s", db_name, stats)
        except Exception:
            logger.exception("[payment-retry] tenant %s failed", db_name)


def process_sms_retries_all_tenants() -> None:
    for db_name, engine in _iter_tenant_engines():
        try:
            with engine.begin() as conn:
                exists = conn.execute(
                    text("SELECT to_regclass('sms_retry_queue')")
                ).scalar()
                if not exists:
                    continue
                stats = process_sms_retries(conn, default_sms_send)
                if stats["processed"]:
                    logger.info("[sms-retry][%s] %s", db_name, stats)
        except Exception:
            logger.exception("[sms-retry] tenant %s failed", db_name)


__all__ = [
    "enqueue_payment_retry", "enqueue_sms_retry",
    "process_payment_retries", "process_sms_retries",
    "process_payment_retries_all_tenants", "process_sms_retries_all_tenants",
    "default_payment_attempt", "default_sms_send",
]
