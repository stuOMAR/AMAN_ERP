"""Unified maintenance writer — canonical path for creating maintenance work orders.

Contract: see specs/024-workforce-service-comms-integrity/contracts/unified-maintenance-writer.md
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


def create_work_order(
    conn: Any,
    *,
    tenant_id: int,
    source: str,
    title: str,
    description: Optional[str] = None,
    asset_id: Optional[int] = None,
    contract_id: Optional[int] = None,
    assigned_technician_id: Optional[int] = None,
    priority: str = "normal",
    due_date: Optional[str] = None,
    actor_id: int = 0,
) -> dict:
    """Create a maintenance work order.

    Source can be: 'preventive', 'corrective', 'asset', 'shopfloor'.
    All maintenance orders are service_orders with kind='maintenance'.
    """
    row = conn.execute(
        text("""
            INSERT INTO service_orders
                (tenant_id, kind, source, title, description,
                 asset_id, contract_id, assigned_technician_id,
                 priority, due_date, status, created_by, created_at)
            VALUES
                (:tnt, 'maintenance', :source, :title, :desc,
                 :asset, :contract, :tech, :priority, :due, 'open', :actor, now())
            RETURNING id
        """),
        {
            "tnt": tenant_id, "source": source, "title": title,
            "desc": description, "asset": asset_id, "contract": contract_id,
            "tech": assigned_technician_id, "priority": priority,
            "due": due_date, "actor": actor_id,
        },
    ).fetchone()
    conn.commit()

    return {"id": row[0], "kind": "maintenance", "source": source, "status": "open"}
