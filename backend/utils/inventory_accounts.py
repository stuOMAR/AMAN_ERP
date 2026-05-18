"""Per-warehouse inventory GL account resolution (F-30/F-31).

Every code path that posts a journal entry which debits or credits inventory
funnels through :func:`resolve_warehouse_inventory_account` so that:

  * Movements within a single warehouse keep the ledger balanced against the
    same account (no change vs. legacy behaviour when the column is NULL).
  * Movements between warehouses produce a meaningful entry — Dr inventory
    of the destination warehouse / Cr inventory of the source warehouse —
    which is the foundation of cross-warehouse and cross-branch inventory
    valuation (F-31).
  * Cross-currency transfers can post in base currency against per-warehouse
    accounts while preserving the transactional currency on
    ``journal_lines.amount_currency``/``currency`` (F-30).

The helper falls back to the global ``acc_map_inventory`` mapping when:

  * ``warehouse_id`` is not provided (legacy callers).
  * The warehouse exists but has no ``gl_inventory_account_id`` configured.

Callers should use the explicit fallback path so the rollout is non-breaking.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import text


def resolve_warehouse_inventory_account(
    db,
    warehouse_id: Optional[int],
    *,
    fallback_to_global: bool = True,
) -> Optional[int]:
    """Return the inventory account id mapped for ``warehouse_id``.

    Resolution order:
      1. ``warehouses.gl_inventory_account_id`` for the supplied warehouse.
      2. (When ``fallback_to_global``) the tenant-level
         ``acc_map_inventory`` setting.

    Returns ``None`` when nothing resolves; the caller is expected to raise
    a 400 explaining that mapping is missing.
    """
    if warehouse_id is not None:
        try:
            row = db.execute(
                text(
                    """
                    SELECT gl_inventory_account_id
                    FROM warehouses
                    WHERE id = :wid
                    """
                ),
                {"wid": int(warehouse_id)},
            ).fetchone()
        except Exception:
            row = None
        if row and row[0]:
            return int(row[0])

    if not fallback_to_global:
        return None

    # Lazy import to avoid a circular dependency with utils.accounting.
    from utils.accounting import get_mapped_account_id

    acc = get_mapped_account_id(db, "acc_map_inventory")
    return int(acc) if acc else None


def require_warehouse_inventory_account(
    db,
    warehouse_id: Optional[int],
    request=None,
) -> int:
    """Like :func:`resolve_warehouse_inventory_account` but raises HTTP 400.

    Use this in code paths where a missing mapping is a hard error.
    """
    from fastapi import HTTPException
    from utils.i18n import http_error

    acc = resolve_warehouse_inventory_account(db, warehouse_id)
    if acc is None:
        raise HTTPException(**http_error(400, "inventory_account_not_configured", request))
    return acc
