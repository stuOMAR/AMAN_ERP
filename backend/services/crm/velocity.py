"""CRM sales velocity — deterministic formula from stage history.

Feature 023 — T055.  Contract: contracts/crm-velocity-funnel.md
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import text

from utils.tax_precision import money_str, rate_str

_D2 = Decimal("0.01")


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
    pipeline_filter = ""

    # Won opportunities in window
    won = db.execute(text(f"""
        SELECT COUNT(*) as cnt, COALESCE(SUM(o.expected_value), 0) as total_value
        FROM sales_opportunities o
        JOIN opportunity_stage_history sh ON sh.opportunity_id = o.id AND sh.to_stage = 'won'
        WHERE sh.tenant_id = :tid {pipeline_filter}
          AND COALESCE(o.is_deleted, FALSE) = FALSE
          AND sh.entered_at >= NOW() - (CAST(:days AS INTEGER) * INTERVAL '1 day')
    """), params).fetchone()

    won_count = int(won.cnt or 0)
    won_value = Decimal(str(won.total_value or 0))

    # Total opportunities that entered the pipeline
    total = db.execute(text(f"""
        SELECT COUNT(DISTINCT o.id) as cnt
        FROM sales_opportunities o
        WHERE COALESCE(o.is_deleted, FALSE) = FALSE {pipeline_filter}
          AND o.created_at >= NOW() - (CAST(:days AS INTEGER) * INTERVAL '1 day')
    """), params).fetchone()

    total_count = int(total.cnt or 0)

    # Average cycle days (created → won)
    avg_cycle = db.execute(text(f"""
        SELECT AVG(EXTRACT(EPOCH FROM (sh.entered_at - o.created_at)) / 86400) as avg_days
        FROM sales_opportunities o
        JOIN opportunity_stage_history sh ON sh.opportunity_id = o.id AND sh.to_stage = 'won'
        WHERE sh.tenant_id = :tid {pipeline_filter}
          AND COALESCE(o.is_deleted, FALSE) = FALSE
          AND sh.entered_at >= NOW() - (CAST(:days AS INTEGER) * INTERVAL '1 day')
    """), params).fetchone()

    avg_days = Decimal(str(avg_cycle.avg_days or 0)) if avg_cycle else Decimal("0")

    if total_count == 0 or avg_days == 0:
        return {
            "velocity": money_str(0), "win_rate": rate_str(0), "avg_cycle_days": "0.00",
            "won_value": money_str(0), "won_count": 0, "total_count": 0,
            "confidence": "insufficient_data",
        }

    win_rate = Decimal(won_count) / Decimal(total_count)
    velocity = won_value * win_rate / avg_days

    return {
        "velocity": money_str(velocity),
        "win_rate": rate_str(win_rate),
        "avg_cycle_days": str(avg_days.quantize(_D2, rounding=ROUND_HALF_UP)),
        "won_value": money_str(won_value),
        "won_count": won_count,
        "total_count": total_count,
        "confidence": "sufficient",
    }
