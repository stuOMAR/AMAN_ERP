"""CRM cash-flow forecast feed.

Feature 023 — T057.  Contract: contracts/crm-cashflow-feed.md
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from utils.tax_precision import money_str


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
    params = {"horizon": horizon_days}
    conditions = [
        "COALESCE(is_deleted, FALSE) = FALSE",
        "stage NOT IN ('won', 'lost', 'cancelled')",
        "expected_close_date IS NOT NULL",
        "expected_close_date <= CURRENT_DATE + (CAST(:horizon AS INTEGER) * INTERVAL '1 day')",
    ]
    if window_start:
        conditions.append("expected_close_date >= :window_start")
        params["window_start"] = window_start
    if window_end:
        conditions.append("expected_close_date <= :window_end")
        params["window_end"] = window_end
    where_clause = " AND ".join(conditions)

    rows = db.execute(text(f"""
        SELECT
            DATE_TRUNC('month', expected_close_date) as bucket,
            COUNT(*) as opportunity_count,
            COALESCE(SUM(expected_value * probability / 100), 0) as weighted_value,
            COALESCE(SUM(expected_value), 0) as total_pipeline
        FROM sales_opportunities
        WHERE {where_clause}
        GROUP BY DATE_TRUNC('month', expected_close_date)
        ORDER BY bucket
    """), params).fetchall()

    return [
        {
            "bucket": str(r.bucket.date()) if r.bucket else None,
            "opportunity_count": int(r.opportunity_count),
            "weighted_value": money_str(r.weighted_value),
            "total_pipeline": money_str(r.total_pipeline),
            "currency": currency,
        }
        for r in rows
    ]
