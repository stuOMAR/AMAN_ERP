"""T122: KPI evaluator job — runs every reports.kpi.evaluation_interval_minutes.

Supports metric_source ∈ {report_key, classifier_category}.
Idempotent on (kpi_id, evaluation_window_start) via idempotent_run.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


async def evaluate_kpis(tenant_id: str | None = None) -> dict[str, Any]:
    """Evaluate all active KPI definitions for the tenant.

    Returns dict with evaluation results.
    """
    from database import get_tenant_db
    from services.scheduler import idempotent_run
    from sqlalchemy import text

    results = {"evaluated": 0, "breached": 0, "skipped": 0}
    now = datetime.now(timezone.utc)

    try:
        with get_tenant_db(tenant_id) as db:
            # Get active KPI definitions
            kpis = db.execute(
                text("SELECT id, kpi_code, metric_source, metric_reference, threshold_value, comparison_op FROM kpi_definitions WHERE is_active = true")
            ).fetchall()

            for kpi in kpis:
                kpi_id, kpi_code, metric_source, metric_ref, threshold, comp_op = kpi
                job_id = f"kpi_eval_{kpi_id}"

                try:
                    with idempotent_run(job_id, scheduled_for=now, tenant_id=tenant_id):
                        # Compute metric value
                        value = _compute_metric(db, tenant_id, metric_source, metric_ref)
                        if value is None:
                            results["skipped"] += 1
                            continue

                        # Check threshold
                        breached = _check_threshold(float(value), float(threshold), comp_op)

                        # Insert evaluation
                        db.execute(
                            text("""
                                INSERT INTO kpi_evaluations
                                    (kpi_id, tenant_id, evaluation_window_start, evaluation_window_end, value, breached)
                                VALUES (:kpi_id, :tenant_id, :start, :end, :value, :breached)
                            """),
                            {"kpi_id": kpi_id, "tenant_id": tenant_id,
                             "start": now, "end": now, "value": float(value), "breached": breached},
                        )
                        db.commit()

                        results["evaluated"] += 1
                        if breached:
                            results["breached"] += 1
                            logger.warning("KPI %s breached: value=%s threshold=%s", kpi_code, value, threshold)

                except Exception as exc:
                    logger.error("KPI evaluation failed for %s: %s", kpi_code, exc)
                    results["skipped"] += 1

    except Exception as exc:
        logger.error("KPI evaluator job failed: %s", exc)

    return results


def _compute_metric(db: Any, tenant_id: str, metric_source: str, metric_ref: str) -> float | None:
    """Compute the metric value from the source."""
    from sqlalchemy import text

    if metric_source == "report_key":
        # Read from a cached report
        try:
            result = db.execute(
                text("SELECT setting_value FROM company_settings WHERE setting_key = :k"),
                {"k": f"report_cache:{metric_ref}"},
            )
            row = result.fetchone()
            return float(row[0]) if row else None
        except Exception:
            return None

    elif metric_source == "classifier_category":
        # Aggregate from mv_period_stats
        try:
            result = db.execute(
                text(f"""
                    SELECT COALESCE(SUM(CASE WHEN :cat = 'revenue' THEN revenue ELSE expense END), 0)
                    FROM mv_period_stats
                    WHERE tenant_id = :tid
                    ORDER BY period_end DESC LIMIT 1
                """),
                {"cat": metric_ref, "tid": tenant_id},
            )
            row = result.fetchone()
            return float(row[0]) if row else None
        except Exception:
            return None

    return None


def _check_threshold(value: float, threshold: float, comp_op: str) -> bool:
    """Check if value breaches the threshold."""
    ops = {
        "lt": lambda v, t: v < t,
        "lte": lambda v, t: v <= t,
        "gt": lambda v, t: v > t,
        "gte": lambda v, t: v >= t,
        "eq": lambda v, t: abs(v - t) < 0.001,
    }
    return ops.get(comp_op, lambda v, t: False)(value, threshold)
