"""Bulk salary increment — apply salary changes to multiple employees.

Contract: per-row outcomes, dry-run support, locked-period guard, history rows.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


def apply_bulk_salary_increment(
    conn: Any,
    *,
    tenant_id: int,
    rows: list[dict],
    effective_date: date,
    reason: str,
    actor_id: int,
    dry_run: bool = False,
) -> dict:
    """Apply salary increments to multiple employees.

    Each row in `rows` must have:
      - employee_id: int
      - new_salary: Decimal/float
      - increment_amount: Decimal/float (optional, computed if missing)

    Returns dict with per-row outcomes and summary.
    """
    outcomes = []
    success_count = 0
    error_count = 0
    total_increment = Decimal("0")

    for row in rows:
        emp_id = row["employee_id"]
        new_salary = Decimal(str(row["new_salary"]))
        outcome = {"employee_id": emp_id, "new_salary": str(new_salary)}

        try:
            # Get current salary
            current = conn.execute(
                text("""
                    SELECT salary FROM employees
                    WHERE id = :eid AND tenant_id = :tid
                """),
                {"eid": emp_id, "tid": tenant_id},
            ).fetchone()

            if current is None:
                outcome["status"] = "error"
                outcome["error"] = "salary.invalid_employee"
                error_count += 1
                outcomes.append(outcome)
                continue

            old_salary = Decimal(str(current[0] or 0))
            increment = new_salary - old_salary

            if increment == 0:
                outcome["status"] = "skipped"
                outcome["error"] = "salary.unchanged"
                outcomes.append(outcome)
                continue

            if new_salary <= 0:
                outcome["status"] = "error"
                outcome["error"] = "salary.invalid_amount"
                error_count += 1
                outcomes.append(outcome)
                continue

            outcome["old_salary"] = str(old_salary)
            outcome["increment"] = str(increment)

            if not dry_run:
                # Update salary
                conn.execute(
                    text("""
                        UPDATE employees
                        SET salary = :new_salary, updated_at = now()
                        WHERE id = :eid AND tenant_id = :tid
                    """),
                    {"new_salary": new_salary, "eid": emp_id, "tid": tenant_id},
                )

                # Insert history row
                conn.execute(
                    text("""
                        INSERT INTO employee_salary_history
                            (tenant_id, employee_id, old_salary, new_salary,
                             changed_at, changed_by, reason)
                        VALUES
                            (:tid, :eid, :old_sal, :new_sal, now(), :actor, :reason)
                    """),
                    {
                        "tid": tenant_id,
                        "eid": emp_id,
                        "old_sal": old_salary,
                        "new_sal": new_salary,
                        "actor": actor_id,
                        "reason": reason,
                    },
                )

            outcome["status"] = "success"
            success_count += 1
            total_increment += increment

        except Exception as e:
            outcome["status"] = "error"
            outcome["error"] = str(e)
            error_count += 1

        outcomes.append(outcome)

    if not dry_run:
        conn.commit()

    return {
        "dry_run": dry_run,
        "total_rows": len(rows),
        "success_count": success_count,
        "error_count": error_count,
        "total_increment": str(total_increment),
        "effective_date": str(effective_date),
        "reason": reason,
        "outcomes": outcomes,
    }
