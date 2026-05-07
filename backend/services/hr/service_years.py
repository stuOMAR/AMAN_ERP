"""Service years computation — honors company service_years_policy setting.

Contract: see specs/024-workforce-service-comms-integrity/contracts/service-years-policy.md
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


def compute_service_years(
    conn: Any,
    *,
    tenant_id: int,
    employee_id: int,
    as_of_date: date = None,
) -> dict:
    """Compute service years for an employee based on company policy.

    Policies (from company_settings 'hr.service_years_policy'):
      - 'months_precise' (default): months / 12, rounded to 2 decimals
      - 'years_integer': completed years only (floor)
      - 'years_half': years rounded to nearest 0.5

    Returns dict with hire_date, service_years, service_months, policy.
    """
    if as_of_date is None:
        as_of_date = date.today()

    # Get employee hire date
    emp = conn.execute(
        text("""
            SELECT hire_date FROM employees
            WHERE id = :eid AND tenant_id = :tid
        """),
        {"eid": employee_id, "tid": tenant_id},
    ).fetchone()

    if emp is None:
        raise LookupError("salary.invalid_employee")
    if emp[0] is None:
        raise ValueError("service_years.future_hire")

    hire_date = emp[0]
    if isinstance(hire_date, str):
        from datetime import datetime as dt
        hire_date = dt.strptime(hire_date, "%Y-%m-%d").date()

    if hire_date > as_of_date:
        raise ValueError("service_years.future_hire")

    # Compute months difference
    months = (as_of_date.year - hire_date.year) * 12 + (as_of_date.month - hire_date.month)
    if as_of_date.day < hire_date.day:
        months -= 1

    # Get policy
    policy_row = conn.execute(
        text("""
            SELECT setting_value FROM company_settings
            WHERE setting_key = 'hr.service_years_policy'
        """),
    ).fetchone()
    policy = policy_row[0] if policy_row else "months_precise"

    # Apply policy
    if policy == "years_integer":
        service_years = Decimal(months // 12)
    elif policy == "years_half":
        exact_years = Decimal(months) / Decimal(12)
        service_years = (exact_years * 2).quantize(Decimal("1")) / 2
    else:  # months_precise
        service_years = (Decimal(months) / Decimal(12)).quantize(Decimal("0.01"))

    return {
        "employee_id": employee_id,
        "hire_date": str(hire_date),
        "as_of_date": str(as_of_date),
        "service_months": months,
        "service_years": str(service_years),
        "policy": policy,
    }
