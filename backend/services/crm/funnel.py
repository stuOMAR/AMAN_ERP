"""CRM funnel conversion — deterministic from stage history.

Feature 023 — T056.  Contract: contracts/crm-velocity-funnel.md
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text


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
    pipeline_filter = "AND o.pipeline_id = :pid" if pipeline_id else ""
    if pipeline_id:
        params["pid"] = pipeline_id

    # Get stage transitions in window
    rows = db.execute(text(f"""
        SELECT sh.from_stage, sh.to_stage, COUNT(*) as transition_count
        FROM opportunity_stage_history sh
        JOIN opportunities o ON o.id = sh.opportunity_id
        WHERE o.tenant_id = :tid {pipeline_filter}
          AND sh.entered_at >= NOW() - INTERVAL ':days days'
          AND sh.from_stage IS NOT NULL
        GROUP BY sh.from_stage, sh.to_stage
        ORDER BY sh.from_stage, sh.to_stage
    """), params).fetchall()

    # Count entries per stage
    entries = db.execute(text(f"""
        SELECT sh.to_stage, COUNT(DISTINCT sh.opportunity_id) as entry_count
        FROM opportunity_stage_history sh
        JOIN opportunities o ON o.id = sh.opportunity_id
        WHERE o.tenant_id = :tid {pipeline_filter}
          AND sh.entered_at >= NOW() - INTERVAL ':days days'
        GROUP BY sh.to_stage
    """), params).fetchall()

    entry_map = {r.to_stage: int(r.entry_count) for r in entries}

    result = []
    for row in rows:
        from_stage = row.from_stage
        to_stage = row.to_stage
        count = int(row.transition_count)
        denominator = entry_map.get(from_stage, 0)
        conversion_rate = round(count / denominator, 4) if denominator > 0 else 0

        result.append({
            "from_stage": from_stage,
            "to_stage": to_stage,
            "transition_count": count,
            "entry_count": denominator,
            "conversion_rate": conversion_rate,
        })

    return result
