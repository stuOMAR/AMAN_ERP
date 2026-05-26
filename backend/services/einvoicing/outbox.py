"""ZATCA outbox — enqueue + worker loop.

Feature 023 — T061.  Contract: contracts/zatca-outbox.md
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

# State transitions: pending → processing → submitted/clearing → cleared/reported → (final)
# Or: pending → processing → failed → dead_letter (after max_attempts)


def enqueue(db: Any, invoice_id: int, tenant_id: int | str | None = None, idempotency_key: str | None = None) -> int | None:
    """Insert a row into zatca_outbox for the given invoice.

    Uses ON CONFLICT DO NOTHING for idempotency.
    Returns the outbox row id, or None if already enqueued.
    """
    try:
        tenant_id_value = int(tenant_id) if tenant_id is not None else None
    except (TypeError, ValueError):
        tenant_id_value = None

    result = db.execute(
        text("""
            INSERT INTO zatca_outbox (
                tenant_id, invoice_id, state, attempts, max_attempts,
                next_attempt_at, idempotency_key, created_at, updated_at
            ) VALUES (
                COALESCE(
                    :tid,
                    CASE
                        WHEN current_database() ~ '^aman_[0-9]+$'
                        THEN regexp_replace(current_database(), '^aman_', '')::BIGINT
                        ELSE 0
                    END
                ),
                :invoice_id, 'pending', 0, 5,
                clock_timestamp(), :idempotency_key, clock_timestamp(), clock_timestamp()
            )
            ON CONFLICT (tenant_id, invoice_id) DO NOTHING
            RETURNING id
        """),
        {"tid": tenant_id_value, "invoice_id": invoice_id, "idempotency_key": idempotency_key},
    )
    row = result.fetchone()
    return row.id if row else None


def start_worker() -> None:
    """Start the ZATCA outbox flush worker. Stub — actual loop runs in worker.py."""
    logger.info("worker.zatca_outbox started (interval=5s, batch=25)")


def process_batch(db: Any, batch_size: int = 25) -> int:
    """Process a batch of pending outbox rows. Returns count processed."""
    rows = db.execute(
        text("""
            SELECT * FROM zatca_outbox
            WHERE state IN ('pending', 'failed')
              AND next_attempt_at <= clock_timestamp()
            ORDER BY next_attempt_at
            LIMIT :batch_size
            FOR UPDATE SKIP LOCKED
        """),
        {"batch_size": batch_size},
    ).fetchall()

    processed = 0
    for row in rows:
        row = dict(row._mapping)
        try:
            _process_one(db, row)
            processed += 1
        except Exception:
            logger.warning("outbox: failed for invoice_id=%s", row.get("invoice_id"))
            _handle_failure(db, row, "zatca_outbox_processing_failed")

    return processed


def _process_one(db: Any, row: dict) -> None:
    """Process a single outbox row: build UBL, sign, submit."""
    outbox_id = row["id"]
    invoice_id = row["invoice_id"]
    tenant_id = row["tenant_id"]

    # Mark processing
    db.execute(
        text("""
            UPDATE zatca_outbox SET state = 'submitting', updated_at = clock_timestamp()
            WHERE id = :id
        """),
        {"id": outbox_id},
    )

    # Get invoice data
    invoice = db.execute(
        text("SELECT * FROM invoices WHERE id = :id"),
        {"id": invoice_id},
    ).fetchone()

    if not invoice:
        raise ValueError("invoice_not_found")

    invoice = dict(invoice._mapping)

    # Build UBL
    try:
        from services.einvoicing.ubl_builder import build_ubl
        xml = build_ubl(invoice)
    except Exception as exc:
        raise ValueError("ubl_build_failed") from exc

    # Sign
    try:
        from services.einvoicing.ubl_signer import sign_xml
        signed_xml = sign_xml(xml, tenant_id=tenant_id)
    except Exception as exc:
        raise ValueError("ubl_signing_failed") from exc

    # Submit to ZATCA (placeholder — real HTTP call would go here)
    # For now, mark as submitted
    db.execute(
        text("""
            UPDATE zatca_outbox
            SET state = 'submitted', attempts = attempts + 1,
                signed_xml = :xml, updated_at = clock_timestamp()
            WHERE id = :id
        """),
        {"id": outbox_id, "xml": signed_xml},
    )


def _handle_failure(db: Any, row: dict, error: str) -> None:
    """Handle a failed processing attempt with exponential backoff."""
    outbox_id = row["id"]
    attempts = row.get("attempts", 0) + 1
    max_attempts = row.get("max_attempts", 5)

    if attempts >= max_attempts:
        new_state = "dead_letter"
    else:
        new_state = "failed"

    # Exponential backoff: 5s, 25s, 125s, 625s, ...
    backoff = min(5 ** attempts, 3600)

    db.execute(
        text("""
            UPDATE zatca_outbox
            SET state = :state, attempts = :attempts,
                last_error = :error,
                next_attempt_at = clock_timestamp() + (:backoff || ' seconds')::INTERVAL,
                updated_at = clock_timestamp()
            WHERE id = :id
        """),
        {"id": outbox_id, "state": new_state, "attempts": attempts,
         "error": error[:500], "backoff": backoff},
    )
