"""Attendance-timetracking link — bridges HR attendance with project time-tracking.

Contract: see specs/024-workforce-service-comms-integrity/contracts/attendance-timetracking-link.md
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


def link_attendance_to_timetracking(
    conn: Any,
    *,
    tenant_id: int,
    employee_id: int,
    attendance_date: date,
) -> dict:
    """Link attendance record to time-tracking entries for a given date.

    Returns dict with effective_hours (attendance hours or time-tracking total,
    whichever is authoritative per company policy).
    """
    # Get attendance record
    attendance = conn.execute(
        text("""
            SELECT id, hours_worked, overtime_hours, status
            FROM attendance
            WHERE tenant_id = :tid AND employee_id = :eid AND date = :dt
        """),
        {"tid": tenant_id, "eid": employee_id, "dt": attendance_date},
    ).fetchone()

    # Get time-tracking entries
    timetracking = conn.execute(
        text("""
            SELECT COALESCE(SUM(hours), 0) as total_hours
            FROM time_entries
            WHERE tenant_id = :tid AND employee_id = :eid AND entry_date = :dt
        """),
        {"tid": tenant_id, "eid": employee_id, "dt": attendance_date},
    ).fetchone()

    attendance_hours = Decimal(str(attendance[1])) if attendance and attendance[1] else Decimal("0")
    tt_hours = Decimal(str(timetracking[0])) if timetracking and timetracking[0] else Decimal("0")

    # Policy: use attendance hours as authoritative, fall back to time-tracking
    effective_hours = attendance_hours if attendance_hours > 0 else tt_hours

    return {
        "employee_id": employee_id,
        "date": str(attendance_date),
        "attendance_hours": str(attendance_hours),
        "timetracking_hours": str(tt_hours),
        "effective_hours": str(effective_hours),
        "attendance_id": attendance[0] if attendance else None,
        "attendance_status": attendance[3] if attendance else None,
    }


def get_effective_hours(
    conn: Any,
    *,
    tenant_id: int,
    employee_id: int,
    start_date: date,
    end_date: date,
) -> list[dict]:
    """Get effective hours for a date range (used by payroll calculation)."""
    rows = conn.execute(
        text("""
            SELECT a.date, a.hours_worked, a.overtime_hours,
                   COALESCE(tt.total_hours, 0) as tt_hours
            FROM attendance a
            LEFT JOIN (
                SELECT employee_id, entry_date, SUM(hours) as total_hours
                FROM time_entries
                WHERE tenant_id = :tid
                GROUP BY employee_id, entry_date
            ) tt ON tt.employee_id = a.employee_id AND tt.entry_date = a.date
            WHERE a.tenant_id = :tid AND a.employee_id = :eid
              AND a.date BETWEEN :start AND :end
            ORDER BY a.date
        """),
        {"tid": tenant_id, "eid": employee_id, "start": start_date, "end": end_date},
    ).fetchall()

    results = []
    for row in rows:
        att_hours = Decimal(str(row[1])) if row[1] else Decimal("0")
        tt_hours = Decimal(str(row[3])) if row[3] else Decimal("0")
        effective = att_hours if att_hours > 0 else tt_hours
        results.append({
            "date": str(row[0]),
            "attendance_hours": str(att_hours),
            "overtime_hours": str(row[2]) if row[2] else "0",
            "timetracking_hours": str(tt_hours),
            "effective_hours": str(effective),
        })

    return results
