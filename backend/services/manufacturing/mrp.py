"""MRP net requirements + multi-level BOM.

Feature 023 — T076.  Contract: contracts/mrp-net-requirements.md
"""
from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


class BomCycleError(Exception):
    def __init__(self, path: list[int]):
        self.path = path
        super().__init__(f"BOM cycle detected: {' → '.join(map(str, path))}")


def run_mrp(db: Any, *, tenant_id: int, actor: dict | None = None, horizon_days: int | None = None) -> dict:
    """Run MRP net requirements computation.

    Steps:
    1. Acquire per-tenant advisory lock.
    2. Build dependency graph from bom_lines; run Tarjan SCC for cycle detection.
    3. For each demand item, compute net = gross_demand - on_hand - on_order + safety_stock.
    4. Explode net through BOM levels with yield/scrap %.
    5. Aggregate per (item_id, warehouse_id) and persist to mrp_recommendations.
    """
    run_id = str(uuid.uuid4())
    lock_key = hash(f"mrp:{tenant_id}") & 0x7FFFFFFF
    db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})

    # Get horizon from settings if not provided
    if horizon_days is None:
        setting = db.execute(
            text("""
                SELECT setting_value FROM company_settings
                WHERE tenant_id = :tid AND setting_key = 'mrp.horizon_days'
            """),
            {"tid": tenant_id},
        ).fetchone()
        horizon_days = int(setting.setting_value or 30) if setting else 30

    # 1. Build BOM dependency graph
    bom_lines = db.execute(
        text("""
            SELECT bl.parent_item_id, bl.component_item_id, bl.qty_per,
                   COALESCE(bl.yield_pct, 100) as yield_pct,
                   COALESCE(bl.scrap_pct, 0) as scrap_pct
            FROM bom_lines bl
            JOIN bill_of_materials bom ON bom.id = bl.bom_id
            WHERE bom.tenant_id = :tid AND bom.is_active = true
        """),
        {"tid": tenant_id},
    ).fetchall()

    # Build adjacency list
    graph: dict[int, set[int]] = defaultdict(set)
    bom_data: dict[tuple[int, int], dict] = {}
    for line in bom_lines:
        parent = line.parent_item_id
        child = line.component_item_id
        graph[parent].add(child)
        bom_data[(parent, child)] = {
            "qty_per": Decimal(str(line.qty_per)),
            "yield_pct": Decimal(str(line.yield_pct)) / 100,
            "scrap_pct": Decimal(str(line.scrap_pct)) / 100,
        }

    # 2. Tarjan SCC cycle detection
    _check_cycles(graph)

    # 3. Get demand sources
    demand = _get_demand(db, tenant_id=tenant_id, horizon_days=horizon_days)

    # 4. Get current on-hand and on-order
    on_hand = _get_on_hand(db, tenant_id=tenant_id)
    on_order = _get_on_order(db, tenant_id=tenant_id)

    # 5. Get safety stock from item_warehouse_settings
    safety_stocks = _get_safety_stocks(db, tenant_id=tenant_id)

    # 6. Explode BOM and compute net requirements
    requirements: dict[tuple[int, int], Decimal] = defaultdict(lambda: Decimal(0))

    for item_id, gross_demand in demand.items():
        net = gross_demand - on_hand.get(item_id, Decimal(0)) - on_order.get(item_id, Decimal(0))
        net += safety_stocks.get((item_id, 0), Decimal(0))  # Default warehouse

        if net > 0:
            requirements[(item_id, 0)] += net

        # Explode through BOM levels
        _explode_bom(
            item_id, net, graph, bom_data, requirements,
            on_hand, on_order, safety_stocks, visited=set(),
        )

    # 7. Persist recommendations
    recommendations_created = 0
    for (item_id, warehouse_id), qty in requirements.items():
        if qty <= 0:
            continue

        db.execute(
            text("""
                INSERT INTO mrp_recommendations (
                    tenant_id, run_id, item_id, warehouse_id,
                    recommended_qty, state, source, created_at, updated_at
                ) VALUES (
                    :tid, :run_id, :item, :wid,
                    :qty, 'open', 'mrp', clock_timestamp(), clock_timestamp()
                )
            """),
            {
                "tid": tenant_id, "run_id": run_id, "item": item_id,
                "wid": warehouse_id, "qty": Decimal(str(qty)),
            },
        )
        recommendations_created += 1

    # Audit
    try:
        from services.audit_writer import log_activity
        log_activity(
            db,
            action="mfg.mrp.run_completed",
            entity_type="mrp_run",
            details={"run_id": run_id, "recommendations": recommendations_created},
        )
    except Exception:
        pass

    return {
        "run_id": run_id,
        "recommendations_created": recommendations_created,
    }


def _check_cycles(graph: dict[int, set[int]]) -> None:
    """Tarjan SCC cycle detection. Raises BomCycleError if cycle found."""
    index_counter = [0]
    stack: list[int] = []
    on_stack: set[int] = set()
    indices: dict[int, int] = {}
    lowlinks: dict[int, int] = {}

    def strongconnect(node: int) -> None:
        indices[node] = index_counter[0]
        lowlinks[node] = index_counter[0]
        index_counter[0] += 1
        stack.append(node)
        on_stack.add(node)

        for neighbor in graph.get(node, set()):
            if neighbor not in indices:
                strongconnect(neighbor)
                lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
            elif neighbor in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[neighbor])

        if lowlinks[node] == indices[node]:
            component = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                component.append(w)
                if w == node:
                    break
            if len(component) > 1:
                raise BomCycleError(component)

    for node in graph:
        if node not in indices:
            strongconnect(node)


def _get_demand(db: Any, *, tenant_id: int, horizon_days: int) -> dict[int, Decimal]:
    """Get gross demand from open sales orders within horizon."""
    rows = db.execute(
        text("""
            SELECT sol.product_id, SUM(sol.quantity) as total_qty
            FROM sales_order_lines sol
            JOIN sales_orders so ON so.id = sol.order_id
            WHERE so.tenant_id = :tid
              AND so.state IN ('confirmed', 'open')
              AND so.order_date <= CURRENT_DATE + (:days || ' days')::INTERVAL
            GROUP BY sol.product_id
        """),
        {"tid": tenant_id, "days": horizon_days},
    ).fetchall()

    return {r.product_id: Decimal(str(r.total_qty)) for r in rows}


def _get_on_hand(db: Any, *, tenant_id: int) -> dict[int, Decimal]:
    """Get current on-hand quantities."""
    rows = db.execute(
        text("""
            SELECT product_id,
                   COALESCE(SUM(
                       CASE WHEN transaction_type IN ('purchase', 'return', 'adjustment_in', 'transfer_in')
                       THEN quantity ELSE -quantity END
                   ), 0) as on_hand
            FROM inventory_transactions
            WHERE tenant_id = :tid
            GROUP BY product_id
        """),
        {"tid": tenant_id},
    ).fetchall()

    return {r.product_id: Decimal(str(r.on_hand)) for r in rows}


def _get_on_order(db: Any, *, tenant_id: int) -> dict[int, Decimal]:
    """Get quantities on open purchase orders."""
    rows = db.execute(
        text("""
            SELECT pol.product_id, SUM(pol.quantity) as total_qty
            FROM purchase_order_lines pol
            JOIN purchase_orders po ON po.id = pol.order_id
            WHERE po.tenant_id = :tid AND po.state IN ('confirmed', 'open')
            GROUP BY pol.product_id
        """),
        {"tid": tenant_id},
    ).fetchall()

    return {r.product_id: Decimal(str(r.total_qty)) for r in rows}


def _get_safety_stocks(db: Any, *, tenant_id: int) -> dict[tuple[int, int], Decimal]:
    """Get safety stock from item_warehouse_settings."""
    rows = db.execute(
        text("""
            SELECT item_id, warehouse_id, safety_stock
            FROM item_warehouse_settings
            WHERE tenant_id = :tid AND safety_stock > 0
        """),
        {"tid": tenant_id},
    ).fetchall()

    return {(r.item_id, r.warehouse_id): Decimal(str(r.safety_stock)) for r in rows}


def _explode_bom(
    item_id: int,
    net_qty: Decimal,
    graph: dict[int, set[int]],
    bom_data: dict[tuple[int, int], dict],
    requirements: dict[tuple[int, int], Decimal],
    on_hand: dict[int, Decimal],
    on_order: dict[int, Decimal],
    safety_stocks: dict[tuple[int, int], Decimal],
    visited: set[int],
) -> None:
    """Recursively explode BOM to compute component requirements."""
    if item_id in visited or net_qty <= 0:
        return
    visited.add(item_id)

    for child_id in graph.get(item_id, set()):
        key = (item_id, child_id)
        if key not in bom_data:
            continue

        data = bom_data[key]
        qty_per = data["qty_per"]
        yield_pct = data["yield_pct"]

        # Component qty = parent_net * qty_per / yield_pct
        component_qty = (net_qty * qty_per) / yield_pct if yield_pct > 0 else net_qty * qty_per

        # Net for component
        child_net = component_qty - on_hand.get(child_id, Decimal(0)) - on_order.get(child_id, Decimal(0))
        child_net += safety_stocks.get((child_id, 0), Decimal(0))

        if child_net > 0:
            requirements[(child_id, 0)] += child_net

        # Recurse
        _explode_bom(
            child_id, child_net, graph, bom_data, requirements,
            on_hand, on_order, safety_stocks, visited,
        )
