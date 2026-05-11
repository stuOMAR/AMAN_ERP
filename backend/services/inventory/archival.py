"""Inventory transactions archival.

Feature 023 — T098.  Contract: contracts/inventory-archival.md
"""
from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


def run_archival(db: Any, *, tenant_id: int) -> dict:
    """Move old inventory_transactions to archive.

    Steps:
    1. Acquire per-tenant advisory lock.
    2. Compute cutoff from inventory.retention_days setting.
    3. Loop batches of 5000, DELETE RETURNING → INSERT INTO archive.
    4. Audit summary.
    """
    # Advisory lock
    lock_key = hash(f"inventory_archival:{tenant_id}") & 0x7FFFFFFF
    db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})

    # Get retention_days setting
    retention = db.execute(
        text("""
            SELECT setting_value FROM company_settings
            WHERE tenant_id = :tid AND setting_key = 'inventory.retention_days'
        """),
        {"tid": tenant_id},
    ).fetchone()

    retention_days = int(retention.setting_value or 365) if retention else 365

    total_moved = 0
    batches = 0
    max_retries = 3
    batch_size = 5000

    while True:
        moved = 0
        for attempt in range(max_retries):
            try:
                result = db.execute(
                    text("""
                        WITH moved AS (
                            DELETE FROM inventory_transactions
                            WHERE created_at < NOW() - (:days || ' days')::INTERVAL
                            LIMIT :batch_size
                            RETURNING *
                        )
                        INSERT INTO inventory_transactions_archive
                        SELECT * FROM moved
                    """),
                    {"days": retention_days, "batch_size": batch_size},
                )
                moved = result.rowcount
                db.commit()
                break
            except Exception as e:
                logger.warning(f"archival: batch failed (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    logger.error(f"archival: batch failed after {max_retries} attempts")
                    return {"status": "error", "total_moved": total_moved, "batches": batches}

        if moved == 0:
            break

        total_moved += moved
        batches += 1
        time.sleep(0.1)  # Brief pause to keep WAL/IO calm

    # Audit summary
    try:
        from services.audit_writer import log_activity
        log_activity(
            db,
            action="inventory.archival.run_completed",
            entity_type="inventory_archival",
            details={"moved": total_moved, "batches": batches, "retention_days": retention_days},
        )
    except Exception:
        pass

    return {"status": "completed", "total_moved": total_moved, "batches": batches}
