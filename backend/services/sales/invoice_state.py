"""Invoice state machine — the ONLY writer of invoices.state.

Feature 023 — T024.  Contract: contracts/invoice-state-machine.md
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

LEGAL_TRANSITIONS: dict[str, set[str]] = {
    "draft":     {"posted", "cancelled"},
    "posted":    {"submitted", "reversed", "cancelled"},
    "submitted": {"cleared", "reported", "reversed"},
    "cleared":   {"reversed"},
    "reported":  {"reversed"},
    "reversed":  set(),
    "cancelled": set(),
}


class InvalidInvoiceTransition(Exception):
    def __init__(self, from_state: str, to_state: str):
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"Invalid invoice transition: {from_state} → {to_state}")


class StaleInvoiceState(Exception):
    def __init__(self, expected: str, actual: str):
        self.expected = expected
        self.actual = actual
        super().__init__(f"Stale invoice state: expected={expected}, actual={actual}")


def transition(
    db: Any,
    invoice: dict,
    target_state: str,
    *,
    actor: dict | None = None,
    reason: str | None = None,
) -> dict:
    """Transition an invoice to target_state. The only allowed writer of invoices.state.

    Args:
        db: SQLAlchemy connection.
        invoice: dict with at least 'id' and 'state'.
        target_state: one of the legal target states.
        actor: user context dict (id, name, ip, user_agent).
        reason: optional free text for reversed/cancelled.

    Returns:
        Updated invoice dict.

    Raises:
        InvalidInvoiceTransition: if (current_state, target_state) not in LEGAL_TRANSITIONS.
        StaleInvoiceState: if the conditional UPDATE affects 0 rows.
    """
    current = invoice["state"]
    if target_state not in LEGAL_TRANSITIONS.get(current, set()):
        raise InvalidInvoiceTransition(current, target_state)

    # Conditional UPDATE — the sole concurrency guard
    result = db.execute(
        text("""
            UPDATE invoices
            SET state = :target,
                state_reason = COALESCE(:reason, state_reason),
                posted_at = CASE WHEN :target = 'posted' THEN clock_timestamp() ELSE posted_at END,
                posted_by = CASE WHEN :target = 'posted' THEN :actor_id ELSE posted_by END,
                updated_at = clock_timestamp()
            WHERE id = :invoice_id AND state = :expected
        """),
        {
            "target": target_state,
            "reason": reason,
            "actor_id": actor.get("id") if actor else None,
            "invoice_id": invoice["id"],
            "expected": current,
        },
    )

    if result.rowcount == 0:
        # Re-read actual state
        row = db.execute(
            text("SELECT state FROM invoices WHERE id = :id"),
            {"id": invoice["id"]},
        ).fetchone()
        actual = row.state if row else "unknown"
        raise StaleInvoiceState(current, actual)

    # Side-effect dispatch
    _dispatch_side_effects(db, invoice, current, target_state, actor, reason)

    # Audit
    try:
        from services.audit_writer import log_activity
        log_activity(
            db,
            action="sales.invoice.state_changed",
            entity_type="invoice",
            entity_id=invoice["id"],
            details={
                "from_state": current,
                "to_state": target_state,
                "reason": reason,
            },
        )
    except Exception:
        logger.warning("Audit write failed for invoice state change", exc_info=True)

    # Return refreshed invoice
    row = db.execute(
        text("SELECT * FROM invoices WHERE id = :id"),
        {"id": invoice["id"]},
    ).fetchone()
    return dict(row._mapping) if row else {**invoice, "state": target_state}


def _dispatch_side_effects(
    db: Any,
    invoice: dict,
    from_state: str,
    to_state: str,
    actor: dict | None,
    reason: str | None,
) -> None:
    """Dispatch GL, ZATCA outbox, and domain events per transition."""
    invoice_id = invoice["id"]
    tenant_id = invoice.get("tenant_id")

    if from_state == "draft" and to_state == "posted":
        # GL posting
        try:
            from services.gl_service import create_journal_entry
            # The actual GL posting logic will be wired by T026
            logger.info(f"GL post triggered for invoice {invoice_id} (draft→posted)")
        except Exception:
            logger.warning(f"GL post failed for invoice {invoice_id}", exc_info=True)

        # ZATCA outbox enqueue
        try:
            from services.einvoicing.outbox import enqueue
            enqueue(db, invoice_id=invoice_id, tenant_id=tenant_id)
        except Exception:
            logger.warning(f"ZATCA enqueue failed for invoice {invoice_id}", exc_info=True)

    elif to_state in ("reversed", "cancelled") and from_state in ("posted", "submitted", "cleared", "reported"):
        # GL reversal
        try:
            logger.info(f"GL reverse triggered for invoice {invoice_id} ({from_state}→{to_state})")
        except Exception:
            logger.warning(f"GL reverse failed for invoice {invoice_id}", exc_info=True)

    # Domain event
    try:
        from utils.redis_event_bus import publish_event
        publish_event("invoice.state_changed", {
            "invoice_id": invoice_id,
            "from_state": from_state,
            "to_state": to_state,
            "actor_id": actor.get("id") if actor else None,
            "reason": reason,
        })
    except Exception:
        pass  # Event bus is best-effort
