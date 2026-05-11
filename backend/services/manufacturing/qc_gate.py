"""QC gate — pass/fail for completed production.

Feature 023 — T092.  Contract: contracts/qc-gate.md
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from fastapi import HTTPException

logger = logging.getLogger(__name__)


def qc_pass(db: Any, *, mo_id: int, completion_ids: list[int], tenant_id: int) -> dict:
    """Pass QC for completions → move to completed state."""
    for cid in completion_ids:
        db.execute(text("""
            UPDATE production_completions
            SET qc_state = 'passed'
            WHERE id = :id AND mo_id = :mo AND tenant_id = :tid AND qc_state = 'pending'
        """), {"id": cid, "mo": mo_id, "tid": tenant_id})

    # Check if all completions passed
    pending = db.execute(text("""
        SELECT COUNT(*) as cnt FROM production_completions
        WHERE mo_id = :mo AND tenant_id = :tid AND qc_state = 'pending'
    """), {"mo": mo_id, "tid": tenant_id}).fetchone()

    if pending.cnt == 0:
        db.execute(text("""
            UPDATE manufacturing_orders SET state = 'completed', updated_at = clock_timestamp()
            WHERE id = :id AND tenant_id = :tid
        """), {"id": mo_id, "tid": tenant_id})

    return {"mo_id": mo_id, "status": "passed", "remaining_pending": pending.cnt}


def qc_fail(
    db: Any,
    *,
    mo_id: int,
    completion_ids: list[int],
    tenant_id: int,
    disposition: str,
    reason: str | None = None,
) -> dict:
    """Fail QC — route to scrap or rework."""
    if disposition not in ("scrap", "rework"):
        raise HTTPException(status_code=422, detail={
            "code": "mfg.qc.invalid_disposition",
            "message": i18n_message("disposition_scrap_or_rework"),
        })

    for cid in completion_ids:
        db.execute(text("""
            UPDATE production_completions
            SET qc_state = 'failed'
            WHERE id = :id AND mo_id = :mo AND tenant_id = :tid AND qc_state = 'pending'
        """), {"id": cid, "mo": mo_id, "tid": tenant_id})

    if disposition == "rework":
        db.execute(text("""
            UPDATE manufacturing_orders SET state = 'in_progress', updated_at = clock_timestamp()
            WHERE id = :id AND tenant_id = :tid
        """), {"id": mo_id, "tid": tenant_id})
    else:
        db.execute(text("""
            UPDATE manufacturing_orders SET state = 'completed', updated_at = clock_timestamp()
            WHERE id = :id AND tenant_id = :tid
        """), {"id": mo_id, "tid": tenant_id})

    return {"mo_id": mo_id, "status": "failed", "disposition": disposition}
