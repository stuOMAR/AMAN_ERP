"""T103: APScheduler job for materialized view refresh.

Runs ``REFRESH MATERIALIZED VIEW CONCURRENTLY`` for all report MVs.
Wraps with ``idempotent_run`` for safety.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def refresh_report_mvs(tenant_id: str | None = None) -> dict[str, bool]:
    """Refresh all report materialized views concurrently.

    Returns dict of {mv_name: success}.
    """
    from database import get_tenant_db
    from services.scheduler import idempotent_run
    from sqlalchemy import text

    results = {}
    now = datetime.now(timezone.utc)

    mvs = ["mv_daily_financial_chart", "mv_period_stats"]

    for mv_name in mvs:
        job_id = f"reports_mv_refresh_{mv_name}"
        try:
            with idempotent_run(job_id, scheduled_for=now, tenant_id=tenant_id):
                with get_tenant_db(tenant_id) as db:
                    db.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {mv_name}"))
                    db.commit()
                results[mv_name] = True
                logger.info("Refreshed MV: %s", mv_name)
        except Exception as exc:
            results[mv_name] = False
            logger.error("Failed to refresh MV %s: %s", mv_name, exc)

    return results
