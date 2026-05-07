"""T104: Period stats reader — reads from mv_period_stats with live-compute fallback.

For newly-created periods not yet in the MV, falls back to live computation
and triggers an async refresh.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def read_period_stats(db: Any, tenant_id: str, company_id: str,
                      period_id: str) -> dict[str, Any] | None:
    """Read period stats from the MV first, with live-compute fallback.

    Args:
        db: Database connection.
        tenant_id: Tenant identifier.
        company_id: Company identifier.
        period_id: Fiscal period identifier.

    Returns:
        Dict with period stats or None if not found.
    """
    from sqlalchemy import text

    # Try MV first
    try:
        result = db.execute(
            text("""
                SELECT tenant_id, company_id, period_id, period_start, period_end,
                       revenue, expense, gross_profit, operating_margin,
                       cash_in, cash_out, refreshed_at
                FROM mv_period_stats
                WHERE tenant_id = :tid AND company_id = :cid AND period_id = :pid
            """),
            {"tid": tenant_id, "cid": company_id, "pid": period_id},
        )
        row = result.fetchone()
        if row:
            return {
                "tenant_id": row[0],
                "company_id": row[1],
                "period_id": row[2],
                "period_start": row[3].isoformat() if row[3] else None,
                "period_end": row[4].isoformat() if row[4] else None,
                "revenue": float(row[5]) if row[5] else 0,
                "expense": float(row[6]) if row[6] else 0,
                "gross_profit": float(row[7]) if row[7] else 0,
                "operating_margin": float(row[8]) if row[8] else 0,
                "cash_in": float(row[9]) if row[9] else 0,
                "cash_out": float(row[10]) if row[10] else 0,
                "source": "mv",
            }
    except Exception as exc:
        logger.warning("MV read failed, falling back to live compute: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass

    # Live compute fallback for new periods
    logger.info("Period %s not in MV, computing live and triggering async refresh", period_id)
    result = _compute_period_stats_live(db, tenant_id, company_id, period_id)

    # Trigger async refresh
    _trigger_async_refresh(period_id)

    return result


def _compute_period_stats_live(db: Any, tenant_id: str, company_id: str,
                                period_id: str) -> dict[str, Any] | None:
    """Live computation of period stats from journal_lines."""
    from sqlalchemy import text

    try:
        result = db.execute(
            text("""
                SELECT
                    p.id AS period_id,
                    p.start_date,
                    p.end_date,
                                        COALESCE(SUM(CASE
                                                WHEN ac.statement_category IN ('revenue', 'contra_revenue')
                                                THEN jl.credit - jl.debit ELSE 0 END), 0) AS revenue,
                                        COALESCE(SUM(CASE
                                                WHEN ac.statement_category IN ('expense', 'contra_expense')
                                                THEN jl.debit - jl.credit ELSE 0 END), 0) AS expense
                FROM journal_lines jl
                JOIN journal_entries je ON je.id = jl.journal_entry_id
                                JOIN fiscal_periods p ON je.entry_date::date BETWEEN p.start_date AND p.end_date
                                LEFT JOIN account_classifications ac
                                    ON ac.account_id = jl.account_id
                                 AND ac.tenant_id = :tid
                                 AND ac.is_active = true
                                 AND ac.valid_from <= CURRENT_DATE
                                 AND (ac.valid_to IS NULL OR ac.valid_to >= CURRENT_DATE)
                                WHERE p.id::text = :pid
                GROUP BY p.id, p.start_date, p.end_date
            """),
            {"tid": tenant_id, "cid": company_id, "pid": period_id},
        )
        row = result.fetchone()
        if not row:
            return None

        revenue = float(row[3]) if row[3] else 0
        expense = float(row[4]) if row[4] else 0
        return {
            "tenant_id": tenant_id,
            "company_id": company_id,
            "period_id": row[0],
            "period_start": row[1].isoformat() if row[1] else None,
            "period_end": row[2].isoformat() if row[2] else None,
            "revenue": revenue,
            "expense": expense,
            "gross_profit": revenue - expense,
            "operating_margin": 0,
            "cash_in": 0,
            "cash_out": 0,
            "source": "live",
        }
    except Exception as exc:
        logger.error("Live period stats computation failed: %s", exc)
        return None


def _trigger_async_refresh(period_id: str) -> None:
    """Trigger an async MV refresh for the given period."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_async_refresh())
        else:
            loop.run_until_complete(_async_refresh())
    except Exception:
        pass


async def _async_refresh() -> None:
    """Async wrapper for MV refresh."""
    try:
        from services.reports.mv_refresh import refresh_report_mvs
        await refresh_report_mvs()
    except Exception as exc:
        logger.warning("Async MV refresh failed: %s", exc)
