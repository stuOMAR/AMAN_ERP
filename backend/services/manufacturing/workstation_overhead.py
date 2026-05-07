"""Workstation overhead rate service.

Feature 023 — T095.  Contract: contracts/workstation-overhead.md
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import text


class ConflictingOverheadRanges(Exception):
    pass


def get_rate(db: Any, *, workstation_id: int, as_of: str | None = None, tenant_id: int | None = None) -> Decimal:
    """Get the overhead rate for a workstation on a given date.

    Falls back to manufacturing.global_overhead_rate when no effective range matches.
    """
    params = {"wid": workstation_id, "as_of": as_of or "CURRENT_DATE"}

    row = db.execute(text("""
        SELECT overhead_rate FROM workstations
        WHERE id = :wid
          AND (effective_from IS NULL OR effective_from <= :as_of::date)
          AND (effective_to IS NULL OR effective_to >= :as_of::date)
          AND overhead_rate IS NOT NULL
        LIMIT 1
    """), params).fetchone()

    if row and row.overhead_rate:
        return Decimal(str(row.overhead_rate))

    # Fallback to global setting
    fallback = db.execute(text("""
        SELECT setting_value FROM company_settings
        WHERE setting_key = 'manufacturing.global_overhead_rate'
    """)).fetchone()

    return Decimal(str(fallback.setting_value or 0)) if fallback else Decimal(0)
