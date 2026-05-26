"""T103: APScheduler job for materialized view refresh.

Runs ``REFRESH MATERIALIZED VIEW CONCURRENTLY`` for all report MVs.
Wraps with ``idempotent_run`` for safety.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

ANALYTICS_MVS = {
    "mv_revenue_summary",
    "mv_expense_summary",
    "mv_cash_position",
    "mv_top_customers",
    "mv_ar_aging",
    "mv_ap_aging",
    "mv_inventory_turnover",
    "mv_sales_pipeline",
}

REPORT_MVS = [
    "mv_daily_financial_chart",
    "mv_period_stats",
    *sorted(ANALYTICS_MVS),
]


async def refresh_report_mvs(tenant_id: str | None = None) -> dict[str, bool]:
    """Refresh all report materialized views concurrently.

    Returns dict of {mv_name: success}.
    """
    from database import get_tenant_db
    from services.scheduler import idempotent_run
    from sqlalchemy import text

    results = {}
    now = datetime.now(timezone.utc)

    for mv_name in REPORT_MVS:
        job_id = f"reports_mv_refresh_{mv_name}"
        try:
            with idempotent_run(job_id, scheduled_for=now, tenant_id=tenant_id):
                with get_tenant_db(tenant_id) as db:
                    exists = db.execute(
                        text("SELECT EXISTS (SELECT 1 FROM pg_matviews WHERE matviewname = :name)"),
                        {"name": mv_name},
                    ).scalar()
                    if not exists:
                        results[mv_name] = False
                        logger.warning("Report MV does not exist: %s", mv_name)
                        continue
                    started = time.monotonic()
                    db.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {mv_name}"))
                    if mv_name in ANALYTICS_MVS:
                        db.execute(text("""
                            CREATE TABLE IF NOT EXISTS analytics_mv_freshness (
                                mv_name VARCHAR(128) PRIMARY KEY,
                                last_refreshed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                                refresh_duration_ms INTEGER
                            )
                        """))
                        db.execute(text("""
                            INSERT INTO analytics_mv_freshness (mv_name, last_refreshed_at, refresh_duration_ms)
                            VALUES (:mv_name, NOW(), :duration_ms)
                            ON CONFLICT (mv_name) DO UPDATE
                              SET last_refreshed_at = EXCLUDED.last_refreshed_at,
                                  refresh_duration_ms = EXCLUDED.refresh_duration_ms
                        """), {
                            "mv_name": mv_name,
                            "duration_ms": int((time.monotonic() - started) * 1000),
                        })
                    db.commit()
                results[mv_name] = True
                logger.info("Refreshed MV: %s", mv_name)
        except Exception as exc:
            results[mv_name] = False
            logger.error("Failed to refresh MV %s: %s", mv_name, exc)

    return results
