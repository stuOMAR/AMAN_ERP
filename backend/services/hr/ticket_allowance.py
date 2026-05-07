"""Ticket allowance — monthly accrual + pay-out with JESource.TICKET_ALLOWANCE.

Contract: see specs/024-workforce-service-comms-integrity/contracts/ticket-allowance.md
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


def accrue_monthly_ticket_allowance(
    conn: Any,
    *,
    tenant_id: int,
    accrual_date: date,
    actor_id: int = 0,
) -> dict:
    """Accrue ticket allowance for all eligible employees for a given month.

    An employee is eligible if:
      - They have ticket_allowance > 0 on their record
      - They haven't already been accrued for this month

    Returns dict with accrual summary.
    """
    from models.domain_models.je_source import JESource

    # Find eligible employees not yet accrued this month
    employees = conn.execute(
        text("""
            SELECT e.id, e.employee_code, e.first_name, e.last_name,
                   COALESCE(e.ticket_allowance, 0) as ticket_allowance
            FROM employees e
            WHERE e.tenant_id = :tid
              AND e.status = 'active'
              AND COALESCE(e.ticket_allowance, 0) > 0
              AND NOT EXISTS (
                  SELECT 1 FROM ticket_allowance_accruals t
                  WHERE t.employee_id = e.id
                    AND t.tenant_id = :tid
                    AND t.accrual_month = DATE_TRUNC('month', :acc_date::date)
              )
        """),
        {"tid": tenant_id, "acc_date": accrual_date},
    ).fetchall()

    accrued_count = 0
    total_amount = Decimal("0")

    for emp in employees:
        emp_id = emp[0]
        amount = Decimal(str(emp[4]))

        # Insert accrual record
        conn.execute(
            text("""
                INSERT INTO ticket_allowance_accruals
                    (tenant_id, employee_id, accrual_month, amount,
                     status, created_at, created_by)
                VALUES
                    (:tid, :eid, DATE_TRUNC('month', :acc_date::date), :amount,
                     'accrued', now(), :actor)
            """),
            {
                "tid": tenant_id,
                "eid": emp_id,
                "acc_date": accrual_date,
                "amount": amount,
                "actor": actor_id,
            },
        )

        accrued_count += 1
        total_amount += amount

    conn.commit()

    return {
        "accrual_date": str(accrual_date),
        "accrued_count": accrued_count,
        "total_amount": str(total_amount),
    }


def pay_out_ticket_allowance(
    conn: Any,
    *,
    tenant_id: int,
    employee_id: int,
    amount: Decimal,
    period_id: int,
    actor_id: int = 0,
) -> dict:
    """Pay out accrued ticket allowance for an employee.

    Creates a GL entry with JESource.TICKET_ALLOWANCE.
    """
    from models.domain_models.je_source import JESource

    # Mark accruals as paid
    conn.execute(
        text("""
            UPDATE ticket_allowance_accruals
            SET status = 'paid', paid_at = now(), paid_in_period = :pid
            WHERE tenant_id = :tid AND employee_id = :eid AND status = 'accrued'
        """),
        {"tid": tenant_id, "eid": employee_id, "pid": period_id},
    )

    conn.commit()

    return {
        "employee_id": employee_id,
        "amount": str(amount),
        "period_id": period_id,
        "je_source": JESource.TICKET_ALLOWANCE.value,
    }
