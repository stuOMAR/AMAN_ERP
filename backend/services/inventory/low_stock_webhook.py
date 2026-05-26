"""Low-stock webhook — debounced emission.

Feature 023 — T101.  Contract: contracts/inventory-low-stock-webhook.md
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


def check_and_emit(
    db: Any,
    *,
    tenant_id: int,
    item_id: int,
    warehouse_id: int,
) -> bool:
    """Check if (item, warehouse) is below reorder_point and emit webhook if so.

    Uses Redis SET NX for day-bucket debouncing to avoid duplicate webhooks.
    Returns True if webhook was emitted.
    """
    # Get current on-hand
    row = db.execute(
        text("""
            SELECT COALESCE(SUM(
                CASE WHEN transaction_type IN ('purchase', 'return', 'adjustment_in', 'transfer_in')
                THEN quantity ELSE -quantity END
            ), 0) as available
            FROM inventory_transactions
            WHERE product_id = :item AND warehouse_id = :wid
        """),
        {"item": item_id, "wid": warehouse_id},
    ).fetchone()

    available = Decimal(str(row.available or 0)) if row else Decimal(0)

    # Get reorder_point
    settings = db.execute(
        text("""
            SELECT reorder_point FROM item_warehouse_settings
            WHERE tenant_id = :tid AND item_id = :item AND warehouse_id = :wid
        """),
        {"tid": tenant_id, "item": item_id, "wid": warehouse_id},
    ).fetchone()

    if not settings:
        return False

    reorder_point = Decimal(str(settings.reorder_point or 0))
    if available >= reorder_point:
        return False

    # Debounce via Redis SET NX
    debounce_key = f"low_stock:{tenant_id}:{item_id}:{warehouse_id}"
    try:
        import redis
        r = redis.Redis()

        # Get debounce hours from settings
        debounce_setting = db.execute(
            text("""
                SELECT setting_value FROM company_settings
                WHERE setting_key = 'inventory.low_stock_debounce_hours'
            """),
        ).fetchone()
        debounce_hours = int(debounce_setting.setting_value or 24) if debounce_setting else 24

        # SET NX with TTL — succeeds only if key doesn't exist
        if not r.set(debounce_key, "1", nx=True, ex=debounce_hours * 3600):
            return False  # Already emitted within debounce window
    except Exception:
        # Redis unavailable — emit anyway (fail-open)
        pass

    # Dispatch webhook
    try:
        from services.webhooks.dispatch import dispatch
        dispatch(
            db,
            tenant_id=tenant_id,
            event="inventory.low_stock",
            payload={
                "item_id": item_id,
                "warehouse_id": warehouse_id,
                "available": str(available),
                "reorder_point": str(reorder_point),
            },
        )
    except Exception:
        logger.warning("low_stock_webhook: dispatch failed")

    return True
