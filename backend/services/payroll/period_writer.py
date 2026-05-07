"""Payroll period writer — canonical path for period state transitions.

Contract: see specs/024-workforce-service-comms-integrity/contracts/payroll-period-overlap.md

This is the ONLY module that writes to payroll_periods.state. The database
exclusion constraint prevents overlapping non-reversed periods.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


def create_period(
    conn: Any,
    *,
    tenant_id: int,
    name: str,
    start_date: date,
    end_date: date,
    payment_date: Optional[date] = None,
) -> dict:
    """Create a new payroll period in 'draft' state.

    Raises 409 if the period overlaps with an existing non-reversed period.
    Raises 422 if end_date < start_date.
    """
    if end_date < start_date:
        raise ValueError("payroll.invalid_range")

    try:
        row = conn.execute(
            text("""
                INSERT INTO payroll_periods
                    (tenant_id, name, start_date, end_date, payment_date, state)
                VALUES
                    (:tid, :name, :start, :end, :pay_date, 'draft')
                RETURNING id, name, start_date, end_date, state, created_at
            """),
            {
                "tid": tenant_id,
                "name": name,
                "start": start_date,
                "end": end_date,
                "pay_date": payment_date,
            },
        ).fetchone()
        conn.commit()
    except Exception as e:
        err_text = str(e)
        if "exclusion" in err_text.lower() or "overlap" in err_text.lower():
            # Find the conflicting period
            conflict = conn.execute(
                text("""
                    SELECT id, start_date, end_date
                    FROM payroll_periods
                    WHERE tenant_id = :tid
                      AND state <> 'reversed'
                      AND tstzrange(start_date::timestamptz, end_date::timestamptz, '[]')
                          && tstzrange(:start::timestamptz, :end::timestamptz, '[]')
                    LIMIT 1
                """),
                {"tid": tenant_id, "start": start_date, "end": end_date},
            ).fetchone()
            conn.rollback()
            detail = {
                "conflicting_period_id": conflict[0] if conflict else None,
                "conflicting_range": f"{conflict[1]}..{conflict[2]}" if conflict else None,
            }
            raise PeriodOverlapError(detail) from e
        raise

    return {
        "id": row[0],
        "name": row[1],
        "start_date": str(row[2]),
        "end_date": str(row[3]),
        "state": row[4],
        "created_at": row[5].isoformat() if row[5] else None,
    }


def transition_state(
    conn: Any,
    *,
    tenant_id: int,
    period_id: int,
    from_state: str,
    to_state: str,
) -> dict:
    """Transition a payroll period from one state to another.

    Valid transitions:
      draft → calculated → locked
      locked → reversed (via period_reversal.py)

    Returns the updated period row.
    """
    _VALID_TRANSITIONS = {
        ("draft", "calculated"),
        ("calculated", "locked"),
        ("locked", "reversed"),
    }

    if (from_state, to_state) not in _VALID_TRANSITIONS:
        raise ValueError(f"Invalid state transition: {from_state} → {to_state}")

    row = conn.execute(
        text("""
            UPDATE payroll_periods
            SET state = :to_state, updated_at = now()
            WHERE id = :pid AND tenant_id = :tid AND state = :from_state
            RETURNING id, name, start_date, end_date, state
        """),
        {"to_state": to_state, "pid": period_id, "tid": tenant_id, "from_state": from_state},
    ).fetchone()

    if row is None:
        raise LookupError("payroll.period_not_found_or_wrong_state")

    conn.commit()
    return {
        "id": row[0],
        "name": row[1],
        "start_date": str(row[2]),
        "end_date": str(row[3]),
        "state": row[4],
    }


class PeriodOverlapError(Exception):
    """Raised when a payroll period overlaps with an existing one."""

    def __init__(self, detail: dict):
        self.detail = detail
        super().__init__(f"Payroll period overlaps: {detail}")
