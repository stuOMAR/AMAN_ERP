"""CRM sales velocity — deterministic formula from stage history.

Feature 023 — T055.  Contract: contracts/crm-velocity-funnel.md
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import text


def compute_velocity(
    db: Any,
    *,
    tenant_id: int,
    pipeline_id: int | None = None,
    window_days: int = 90,
) -> dict:
    """Compute sales velocity over a rolling window.

    velocity = (won_value * win_rate) / avg_cycle_days

    Returns dict with velocity, win_rate, avg_cycle_days, won_value, confidence.
    """
    params = {"tid": tenant_id, "days": window_days}
    pipeline_filter = "AND o.pipeline_id = :pid" if pipeline_id else ""
    if pipeline_id:
        params["pid"] = pipeline_id

    # Won opportunities in window
    won = db.execute(text(f"""
        SELECT COUNT(*) as cnt, COALESCE(SUM(o.expected_value), 0) as total_value
        FROM opportunities o
        JOIN opportunity_stage_history sh ON sh.opportunity_id = o.id AND sh.to_stage = 'won'
        WHERE o.tenant_id = :tid {pipeline_filter}
          AND sh.entered_at >= NOW() - INTERVAL ':days days'
    """), params).fetchone()

    won_count = int(won.cnt or 0)
    won_value = Decimal(str(won.total_value or 0))

    # Total opportunities that entered the pipeline
    total = db.execute(text(f"""
        SELECT COUNT(DISTINCT o.id) as cnt
        FROM opportunities o
        WHERE o.tenant_id = :tid {pipeline_filter}
          AND o.created_at >= NOW() - INTERVAL ':days days'
    """), params).fetchone()

    total_count = int(total.cnt or 0)

    # Average cycle days (created → won)
    avg_cycle = db.execute(text(f"""
        SELECT AVG(EXTRACT(EPOCH FROM (sh.entered_at - o.created_at)) / 86400) as avg_days
        FROM opportunities o
        JOIN opportunity_stage_history sh ON sh.opportunity_id = o.id AND sh.to_stage = 'won'
        WHERE o.tenant_id = :tid {pipeline_filter}
          AND sh.entered_at >= NOW() - INTERVAL ':days days'
    """), params).fetchone()

    avg_days = float(avg_cycle.avg_days or 0) if avg_cycle else 0

    if total_count == 0 or avg_days == 0:
        return {
            "velocity": 0, "win_rate": 0, "avg_cycle_days": 0,
            "won_value": 0, "won_count": 0, "total_count": 0,
            "confidence": "insufficient_data",
        }

    win_rate = won_count / total_count
    velocity = float(won_value) * win_rate / avg_days

    return {
        "velocity": round(velocity, 4),
        "win_rate": round(win_rate, 4),
        "avg_cycle_days": round(avg_days, 2),
        "won_value": float(won_value),
        "won_count": won_count,
        "total_count": total_count,
        "confidence": "sufficient",
    }
