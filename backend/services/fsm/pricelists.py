"""Service pricelist resolver — resolves prices for FSM service orders.

Contract: see specs/024-workforce-service-comms-integrity/contracts/service-pricelist-resolver.md

Resolution hierarchy:
  1. Customer-specific pricelist
  2. Customer group pricelist
  3. Global pricelist (scope='global')
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any, Optional, Tuple

from sqlalchemy import text

logger = logging.getLogger(__name__)


def resolve_price(
    conn: Any,
    *,
    tenant_id: int,
    item_id: int,
    currency: str,
    customer_id: Optional[int] = None,
    customer_group_id: Optional[int] = None,
    as_of_date: date = None,
) -> Tuple[Optional[Decimal], Optional[str]]:
    """Resolve the price for an item from the pricelist hierarchy.

    Returns (price, level) where level is 'customer', 'group', or 'global'.
    Returns (None, None) if no price found.
    """
    if as_of_date is None:
        as_of_date = date.today()

    # 1. Customer-specific pricelist
    if customer_id:
        row = conn.execute(
            text("""
                SELECT price FROM service_pricelists
                WHERE tenant_id = :tid AND scope = 'customer'
                  AND scope_ref_id = :cid AND item_id = :iid
                  AND currency = :cur
                  AND (valid_from IS NULL OR valid_from <= :today)
                  AND (valid_to IS NULL OR valid_to >= :today)
                ORDER BY valid_from DESC NULLS LAST
                LIMIT 1
            """),
            {
                "tid": tenant_id, "cid": customer_id,
                "iid": item_id, "cur": currency, "today": as_of_date,
            },
        ).fetchone()
        if row:
            return Decimal(str(row[0])), "customer"

    # 2. Customer group pricelist
    if customer_group_id:
        row = conn.execute(
            text("""
                SELECT price FROM service_pricelists
                WHERE tenant_id = :tid AND scope = 'group'
                  AND scope_ref_id = :gid AND item_id = :iid
                  AND currency = :cur
                  AND (valid_from IS NULL OR valid_from <= :today)
                  AND (valid_to IS NULL OR valid_to >= :today)
                ORDER BY valid_from DESC NULLS LAST
                LIMIT 1
            """),
            {
                "tid": tenant_id, "gid": customer_group_id,
                "iid": item_id, "cur": currency, "today": as_of_date,
            },
        ).fetchone()
        if row:
            return Decimal(str(row[0])), "group"

    # 3. Global pricelist
    row = conn.execute(
        text("""
            SELECT price FROM service_pricelists
            WHERE tenant_id = :tid AND scope = 'global'
              AND item_id = :iid AND currency = :cur
              AND (valid_from IS NULL OR valid_from <= :today)
              AND (valid_to IS NULL OR valid_to >= :today)
            ORDER BY valid_from DESC NULLS LAST
            LIMIT 1
        """),
        {"tid": tenant_id, "iid": item_id, "cur": currency, "today": as_of_date},
    ).fetchone()

    if row:
        return Decimal(str(row[0])), "global"

    return None, None


def upsert_pricelist_entry(
    conn: Any,
    *,
    tenant_id: int,
    scope: str,
    scope_ref_id: Optional[int],
    item_id: int,
    currency: str,
    price: Decimal,
    valid_from: Optional[date] = None,
    valid_to: Optional[date] = None,
) -> dict:
    """Create or update a pricelist entry."""
    row = conn.execute(
        text("""
            INSERT INTO service_pricelists
                (tenant_id, scope, scope_ref_id, item_id, currency, price,
                 valid_from, valid_to, created_at)
            VALUES
                (:tid, :scope, :ref, :item, :cur, :price,
                 :vf, :vt, now())
            ON CONFLICT (tenant_id, scope, scope_ref_id, item_id, currency,
                         COALESCE(valid_from, '1900-01-01'), COALESCE(valid_to, '9999-12-31'))
            DO UPDATE SET price = :price, updated_at = now()
            RETURNING id, scope, item_id, currency, price
        """),
        {
            "tid": tenant_id, "scope": scope, "ref": scope_ref_id,
            "item": item_id, "cur": currency, "price": price,
            "vf": valid_from, "vt": valid_to,
        },
    ).fetchone()
    conn.commit()

    return {
        "id": row[0],
        "scope": row[1],
        "item_id": row[2],
        "currency": row[3],
        "price": str(row[4]),
    }
