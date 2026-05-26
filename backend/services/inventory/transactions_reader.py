"""Inventory transactions reader — UNION ALL across live and archive.

Feature 023 — T099.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


def read_inventory_transactions(
    db: Any,
    *,
    tenant_id: int,
    item_id: int | None = None,
    warehouse_id: int | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 10000,
    offset: int = 0,
) -> list[dict]:
    """Read inventory transactions from both live and archive tables.

    Used by valuation and historical balance reports that may span the archival cutoff.
    """
    conditions_live = ["1=1"]
    conditions_archive = ["1=1"]
    params: dict = {"limit": limit, "offset": offset}

    if item_id:
        conditions_live.append("product_id = :item_id")
        conditions_archive.append("product_id = :item_id")
        params["item_id"] = item_id

    if warehouse_id:
        conditions_live.append("warehouse_id = :wid")
        conditions_archive.append("warehouse_id = :wid")
        params["wid"] = warehouse_id

    if since:
        conditions_live.append("created_at >= :since")
        conditions_archive.append("created_at >= :since")
        params["since"] = since

    if until:
        conditions_live.append("created_at <= :until")
        conditions_archive.append("created_at <= :until")
        params["until"] = until

    where_live = " AND ".join(conditions_live)
    where_archive = " AND ".join(conditions_archive)

    rows = db.execute(
        text(f"""
            SELECT * FROM inventory_transactions WHERE {where_live}
            UNION ALL
            SELECT * FROM inventory_transactions_archive WHERE {where_archive}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    ).fetchall()

    return [dict(r._mapping) for r in rows]
