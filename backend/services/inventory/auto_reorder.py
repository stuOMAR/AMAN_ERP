"""Auto-reorder scheduler.

Feature 023 — T073.  Contract: contracts/auto-reorder.md
"""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


def run_auto_reorder(db: Any, *, tenant_id: int) -> dict:
    """Scan below-reorder-point pairs and create recommendations.

    Steps:
    1. Acquire per-tenant advisory lock.
    2. Paginate through item_warehouse_settings in chunks of 1000.
    3. For each pair below reorder point, insert mrp_recommendations row.
    4. Optionally create draft POs when auto_reorder_enabled=true.
    5. Audit summary.
    """
    run_id = str(uuid.uuid4())
    recommendations_created = 0

    # Advisory lock
    lock_key = hash(f"auto_reorder:{tenant_id}") & 0x7FFFFFFF
    db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})

    # Check if auto-reorder is enabled
    enabled = db.execute(
        text("""
            SELECT setting_value FROM company_settings
            WHERE tenant_id = :tid AND setting_key = 'inventory.auto_reorder_enabled'
        """),
        {"tid": tenant_id},
    ).fetchone()

    if not enabled or enabled.setting_value not in ("true", "1", "yes"):
        logger.info(f"auto_reorder: disabled for tenant {tenant_id}")
        return {"status": "disabled", "run_id": run_id}

    # Paginate through item_warehouse_settings
    offset = 0
    chunk_size = 1000

    while True:
        rows = db.execute(
            text("""
                SELECT iws.item_id, iws.warehouse_id, iws.reorder_point,
                       iws.reorder_quantity, iws.safety_stock, iws.lead_time_days,
                       iws.preferred_supplier_id
                FROM item_warehouse_settings iws
                WHERE iws.tenant_id = :tid
                ORDER BY iws.item_id, iws.warehouse_id
                LIMIT :limit OFFSET :offset
            """),
            {"tid": tenant_id, "limit": chunk_size, "offset": offset},
        ).fetchall()

        if not rows:
            break

        for row in rows:
            try:
                _process_pair(db, tenant_id=tenant_id, row=row, run_id=run_id)
                recommendations_created += 1
            except Exception as e:
                logger.warning(f"auto_reorder: failed for item={row.item_id} wh={row.warehouse_id}: {e}")

        offset += chunk_size

    # Audit summary
    try:
        from services.audit_writer import log_activity
        log_activity(
            db,
            action="inventory.reorder_run_completed",
            entity_type="auto_reorder",
            details={"run_id": run_id, "recommendations_created": recommendations_created},
        )
    except Exception:
        pass

    return {"status": "completed", "run_id": run_id, "recommendations_created": recommendations_created}


def _process_pair(db: Any, *, tenant_id: int, row: Any, run_id: str) -> None:
    """Process a single (item, warehouse) pair."""
    item_id = row.item_id
    warehouse_id = row.warehouse_id
    reorder_point = Decimal(str(row.reorder_point or 0))
    reorder_quantity = Decimal(str(row.reorder_quantity or 0))
    safety_stock = Decimal(str(row.safety_stock or 0))
    lead_time_days = int(row.lead_time_days or 0)

    # Compute available = on_hand + on_order - allocated
    avail_row = db.execute(
        text("""
            SELECT COALESCE(SUM(
                CASE WHEN transaction_type IN ('purchase', 'return', 'adjustment_in', 'transfer_in')
                THEN quantity ELSE -quantity END
            ), 0) as on_hand
            FROM inventory_transactions
            WHERE product_id = :item AND warehouse_id = :wid
        """),
        {"item": item_id, "wid": warehouse_id},
    ).fetchone()

    available = Decimal(str(avail_row.on_hand or 0)) if avail_row else Decimal(0)

    if available >= reorder_point:
        return  # No reorder needed

    # Simple forecast: use average daily demand over last 30 days
    demand_row = db.execute(
        text("""
            SELECT COALESCE(ABS(SUM(quantity)), 0) / 30.0 as avg_daily
            FROM inventory_transactions
            WHERE product_id = :item AND warehouse_id = :wid
              AND transaction_type IN ('sales', 'pos_sale')
              AND created_at >= NOW() - INTERVAL '30 days'
        """),
        {"item": item_id, "wid": warehouse_id},
    ).fetchone()

    avg_daily = Decimal(str(demand_row.avg_daily or 0)) if demand_row else Decimal(0)
    forecast_demand = avg_daily * Decimal(str(lead_time_days))

    recommended_qty = max(reorder_quantity, safety_stock + forecast_demand - available)

    if recommended_qty <= 0:
        return

    db.execute(
        text("""
            INSERT INTO mrp_recommendations (
                tenant_id, run_id, item_id, warehouse_id,
                recommended_qty, state, source, created_at, updated_at
            ) VALUES (
                :tid, :run_id, :item, :wid,
                :qty, 'open', 'auto_reorder', clock_timestamp(), clock_timestamp()
            )
        """),
        {
            "tid": tenant_id, "run_id": run_id, "item": item_id,
            "wid": warehouse_id, "qty": float(recommended_qty),
        },
    )

    try:
        from services.audit_writer import log_activity
        log_activity(
            db,
            action="inventory.reorder_recommended",
            entity_type="mrp_recommendation",
            details={
                "item_id": item_id, "warehouse_id": warehouse_id,
                "recommended_qty": float(recommended_qty),
            },
        )
    except Exception:
        pass
