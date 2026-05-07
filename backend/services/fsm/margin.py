"""Service margin computation — calculates revenue, cost, and margin for service orders.

Contract: see specs/024-workforce-service-comms-integrity/contracts/service-margin.md
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


def compute_margin(
    conn: Any,
    *,
    tenant_id: int,
    service_order_id: int,
) -> dict:
    """Compute margin for a service order.

    Reads revenue from pricelist resolution and cost from WAC (via 023's
    wac_per_warehouse or BOM cost).
    """
    order = conn.execute(
        text("""
            SELECT id, revenue_total, cost_total, status, kind
            FROM service_orders
            WHERE id = :oid AND tenant_id = :tid
        """),
        {"oid": service_order_id, "tid": tenant_id},
    ).fetchone()

    if order is None:
        raise LookupError("Service order not found")

    revenue = Decimal(str(order[1])) if order[1] else Decimal("0")
    cost = Decimal(str(order[2])) if order[2] else Decimal("0")

    margin_amount = revenue - cost
    margin_pct = (margin_amount / revenue * 100) if revenue > 0 else Decimal("0")

    return {
        "service_order_id": service_order_id,
        "revenue": str(revenue),
        "cost": str(cost),
        "margin_amount": str(margin_amount.quantize(Decimal("0.01"))),
        "margin_pct": str(margin_pct.quantize(Decimal("0.01"))),
        "status": order[3],
        "kind": order[4],
    }


def update_order_margin(
    conn: Any,
    *,
    tenant_id: int,
    service_order_id: int,
    revenue: Optional[Decimal] = None,
    cost: Optional[Decimal] = None,
) -> dict:
    """Update revenue/cost and recompute margin for a service order."""
    updates = []
    params = {"oid": service_order_id, "tid": tenant_id}

    if revenue is not None:
        updates.append("revenue_total = :rev, revenue_resolved_at = now()")
        params["rev"] = revenue
    if cost is not None:
        updates.append("cost_total = :cost")
        params["cost"] = cost

    if not updates:
        return compute_margin(conn, tenant_id=tenant_id, service_order_id=service_order_id)

    conn.execute(
        text(f"""
            UPDATE service_orders
            SET {', '.join(updates)}, updated_at = now()
            WHERE id = :oid AND tenant_id = :tid
        """),
        params,
    )
    conn.commit()

    return compute_margin(conn, tenant_id=tenant_id, service_order_id=service_order_id)
