"""CRM cash-flow forecast feed.

Feature 023 — T057.  Contract: contracts/crm-cashflow-feed.md
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import text


def forecast_by_date(
    db: Any,
    *,
    tenant_id: int,
    window_start: str | None = None,
    window_end: str | None = None,
    currency: str = "SAR",
    horizon_days: int = 180,
) -> list[dict]:
    """Probability-weighted bucketed cash-flow forecast from open opportunities.

    Each open opportunity contributes expected_value * probability to the
    bucket keyed by expected_close_date.
    """
    params = {"tid": tenant_id, "horizon": horizon_days}

    rows = db.execute(text("""
        SELECT
            DATE_TRUNC('month', expected_close_date) as bucket,
            COUNT(*) as opportunity_count,
            SUM(expected_value * probability / 100.0) as weighted_value,
            SUM(expected_value) as total_pipeline
        FROM opportunities
        WHERE tenant_id = :tid
          AND stage NOT IN ('won', 'lost', 'cancelled')
          AND expected_close_date IS NOT NULL
          AND expected_close_date <= CURRENT_DATE + INTERVAL ':horizon days'
        GROUP BY DATE_TRUNC('month', expected_close_date)
        ORDER BY bucket
    """), params).fetchall()

    return [
        {
            "bucket": str(r.bucket.date()) if r.bucket else None,
            "opportunity_count": int(r.opportunity_count),
            "weighted_value": float(Decimal(str(r.weighted_value or 0))),
            "total_pipeline": float(Decimal(str(r.total_pipeline or 0))),
            "currency": currency,
        }
        for r in rows
    ]
