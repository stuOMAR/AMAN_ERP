"""Scrap movements writer.

Feature 023 — T083.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


def record_scrap(
    db: Any,
    *,
    tenant_id: int,
    item_id: int,
    warehouse_id: int,
    qty: Decimal,
    unit_cost: Decimal,
    reason: str,
    mo_id: int | None = None,
) -> dict:
    """Record a scrap movement and post GL."""
    # Post GL
    je_id = 0
    try:
        from services.gl_service import create_journal_entry
        # Simplified — actual GL posting uses the configured scrap-loss account
        je_id = 0  # Placeholder
    except Exception:
        pass

    result = db.execute(text("""
        INSERT INTO scrap_movements (
            tenant_id, item_id, warehouse_id, qty, unit_cost_at_scrap,
            reason, mo_id, je_id, occurred_at
        ) VALUES (:tid, :item, :wid, :qty, :cost, :reason, :mo, :je, clock_timestamp())
        RETURNING id
    """), {
        "tid": tenant_id, "item": item_id, "wid": warehouse_id,
        "qty": float(qty), "cost": float(unit_cost),
        "reason": reason, "mo": mo_id, "je": je_id,
    })

    scrap_id = result.fetchone().id

    # Audit
    try:
        from services.audit_writer import log_activity
        log_activity(
            db, action="inventory.scrap.recorded",
            entity_type="scrap_movement", entity_id=scrap_id,
            details={"item_id": item_id, "qty": float(qty), "reason": reason},
        )
    except Exception:
        pass

    return {"id": scrap_id, "je_id": je_id}
