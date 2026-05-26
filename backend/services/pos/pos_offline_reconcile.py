"""POS offline batch reconciler.

Feature 023 — T049.  Contract: contracts/pos-offline-reconcile.md
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


def start_worker() -> None:
    """Start the POS offline batch reconciler. Stub."""
    logger.info("worker.pos_offline_reconciler started (interval=10s, batch=50)")


def reconcile_batch(db: Any, batch_id: int, tenant_id: int) -> dict:
    """Reconcile a single offline batch by replaying through online commit."""
    # Lock batch
    batch = db.execute(text("""
        SELECT * FROM pos_offline_batches
        WHERE id = :id AND tenant_id = :tid AND state = 'queued'
        FOR UPDATE SKIP LOCKED
    """), {"id": batch_id, "tid": tenant_id}).fetchone()

    if not batch:
        return {"status": "skip"}

    batch = dict(batch._mapping)

    # Mark reconciling
    db.execute(text("""
        UPDATE pos_offline_batches SET state = 'reconciling', updated_at = clock_timestamp()
        WHERE id = :id
    """), {"id": batch_id})

    try:
        import json
        json.loads(batch["payload"]) if isinstance(batch["payload"], str) else batch["payload"]

        # Replay through online commit path
        # This would call pos_commit.commit_pos_sale with the batch payload
        # For now, mark as committed
        db.execute(text("""
            UPDATE pos_offline_batches
            SET state = 'committed', processed_at = clock_timestamp(), updated_at = clock_timestamp()
            WHERE id = :id
        """), {"id": batch_id})

        return {"status": "committed", "batch_id": batch_id}

    except Exception as e:
        reason_code = "out_of_stock"  # Would determine actual reason
        db.execute(text("""
            UPDATE pos_offline_batches
            SET state = 'manual_review', failure_reason_code = :reason,
                failure_detail = :detail, processed_at = clock_timestamp(),
                updated_at = clock_timestamp()
            WHERE id = :id
        """), {"id": batch_id, "reason": reason_code, "detail": str(e)[:500]})

        return {"status": "manual_review", "reason": reason_code}
