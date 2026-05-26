"""
Audit writer — outbox-backed, transaction-safe.

Every audit/log path MUST call ``log_activity()`` from this module.
It inserts into ``audit_outbox`` on the caller's session so the row
commits/rolls back atomically with the business transaction.

A background worker (``services/audit_outbox_worker.py``) flushes
committed rows to ``audit_logs``.

Contract: see specs/022-audit-security-finance-integrity/contracts/audit-writer.md
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from services.audit_sanitizer import sanitize_for_audit

logger = logging.getLogger(__name__)


# ── Custom error ──────────────────────────────────────────────────────────────
class AuditWriteError(Exception):
    """Raised when sanitization or outbox insert fails."""


# ── AuditDetails normalisation ────────────────────────────────────────────────
class AuditDetails:
    """Base class for typed audit detail payloads.

    Subclass this for action-specific schemas.  The writer boundary
    accepts both ``AuditDetails`` instances and plain ``dict`` s.
    """

    def to_dict(self) -> dict:
        raise NotImplementedError


def _normalize_details(details: dict | AuditDetails | None) -> dict:
    """Return a JSON-safe dict, wrapping legacy dicts with a schema tag."""
    if details is None:
        return {}
    if isinstance(details, AuditDetails):
        payload = details.to_dict()
        payload["_details_schema_version"] = 2
        return payload
    if isinstance(details, dict):
        # Legacy dict — wrap and tag.
        return {"legacy": details, "_details_schema_version": 1}
    # Fallback: repr wrapper.
    return {"legacy": {"repr": repr(details)}, "_details_schema_version": 0}


class _DecimalEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, Decimal):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)


def _to_jsonb(value: dict) -> str:
    return json.dumps(value, cls=_DecimalEncoder, default=str, sort_keys=True)


# ── Public API ────────────────────────────────────────────────────────────────
def log_activity(
    conn,
    *,
    action: str,
    entity_type: str | None = None,
    entity_id: str | int | None = None,
    actor_id: int | None = None,
    details: dict | AuditDetails | None = None,
    critical: bool = False,
) -> None:
    """Insert one row into ``audit_outbox`` on the caller's session.

    * **Never** commits or rolls back — the caller owns the transaction.
    * Sanitises *details* before persistence.
    * Raises ``AuditWriteError`` on failure.
    """
    try:
        normalized = _normalize_details(details)
        sanitized = sanitize_for_audit(normalized, context=action)
        payload_json = _to_jsonb(sanitized)
        statement = text(
            """
            INSERT INTO audit_outbox
                (tenant_id, actor_id, action, entity_type, entity_id,
                 payload, critical, enqueued_at)
            VALUES
                (
                 COALESCE(
                    NULLIF(current_setting('app.tenant_id', true), ''),
                    NULLIF(regexp_replace(current_database(), '^aman_', ''), ''),
                    'unknown'
                 ),
                 :actor_id, :action, :entity_type, :entity_id,
                 CAST(:payload AS JSONB), :critical, clock_timestamp())
            """
        )

        params = {
            "actor_id": actor_id,
            "action": action,
            "entity_type": entity_type,
            "entity_id": str(entity_id) if entity_id is not None else None,
            "payload": payload_json,
            "critical": critical,
        }

        owns_transaction = False
        try:
            in_transaction = conn.in_transaction()
        except Exception:
            in_transaction = True

        if not in_transaction:
            owns_transaction = True
        else:
            try:
                owns_transaction = conn.execute(
                    text("SELECT txid_current_if_assigned()")
                ).scalar() is None
            except Exception:
                owns_transaction = False

        def _enqueue() -> None:
            conn.execute(statement, params)

        if critical or owns_transaction:
            _enqueue()
            if owns_transaction:
                conn.commit()
        else:
            with conn.begin_nested():
                _enqueue()
        logger.debug("audit_outbox: enqueued %s", action)
    except AuditWriteError:
        raise
    except Exception as exc:
        logger.error("audit_outbox: failed to enqueue %s", action)
        raise AuditWriteError(f"Failed to enqueue audit row for {action}") from exc
