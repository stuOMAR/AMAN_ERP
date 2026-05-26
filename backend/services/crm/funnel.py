"""CRM funnel conversion — deterministic from stage history.

Feature 023 — T056.  Contract: contracts/crm-velocity-funnel.md
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import text

from utils.tax_precision import rate_str

_D4 = Decimal("0.0001")


def compute_funnel(
    db: Any,
    *,
    tenant_id: int,
    pipeline_id: int | None = None,
    window_days: int = 90,
) -> list[dict]:
    """Compute funnel conversion rates per stage transition.

    conversion(stage_i → stage_j) = count(transitions i→j) / count(opps that entered i)
    """
    params = {"tid": tenant_id, "days": window_days}
    pipeline_filter = ""

    # Get stage transitions in window
    rows = db.execute(text(f"""
        SELECT sh.from_stage, sh.to_stage, COUNT(*) as transition_count
        FROM opportunity_stage_history sh
        JOIN sales_opportunities o ON o.id = sh.opportunity_id
        WHERE sh.tenant_id = :tid {pipeline_filter}
          AND COALESCE(o.is_deleted, FALSE) = FALSE
          AND sh.entered_at >= NOW() - (CAST(:days AS INTEGER) * INTERVAL '1 day')
          AND sh.from_stage IS NOT NULL
        GROUP BY sh.from_stage, sh.to_stage
        ORDER BY sh.from_stage, sh.to_stage
    """), params).fetchall()

    # Count entries per stage
    entries = db.execute(text(f"""
        SELECT sh.to_stage, COUNT(DISTINCT sh.opportunity_id) as entry_count
        FROM opportunity_stage_history sh
        JOIN sales_opportunities o ON o.id = sh.opportunity_id
        WHERE sh.tenant_id = :tid {pipeline_filter}
          AND COALESCE(o.is_deleted, FALSE) = FALSE
          AND sh.entered_at >= NOW() - (CAST(:days AS INTEGER) * INTERVAL '1 day')
        GROUP BY sh.to_stage
    """), params).fetchall()

    entry_map = {r.to_stage: int(r.entry_count) for r in entries}

    result = []
    for row in rows:
        from_stage = row.from_stage
        to_stage = row.to_stage
        count = int(row.transition_count)
        denominator = entry_map.get(from_stage, 0)
        conversion_rate = (
            (Decimal(count) / Decimal(denominator)).quantize(_D4, rounding=ROUND_HALF_UP)
            if denominator > 0
            else Decimal("0")
        )

        result.append({
            "from_stage": from_stage,
            "to_stage": to_stage,
            "transition_count": count,
            "entry_count": denominator,
            "conversion_rate": rate_str(conversion_rate),
        })

    return result
