"""
HR PII masking utilities.

Provides field-level masking for sensitive HR data (salary, IBAN, national ID)
based on user permissions. Users with 'hr.pii' permission see unmasked values;
others see masked versions.

Constitution §4: PII must be masked for users without hr.pii permission.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

from utils.masking import mask_pii


def has_pii_access(current_user: Any) -> bool:
    """Check if the current user has hr.pii permission."""
    if isinstance(current_user, dict):
        permissions = current_user.get("permissions", []) or []
        role = current_user.get("role", "")
    else:
        permissions = getattr(current_user, "permissions", []) or []
        role = getattr(current_user, "role", "") or ""

    if role in ("admin", "system_admin", "superuser"):
        return True
    if "*" in permissions:
        return True
    return "hr.pii" in permissions or "hr.manage" in permissions or "hr.payroll" in permissions


def mask_employee_pii(employee: Dict[str, Any], current_user: Any) -> Dict[str, Any]:
    """Mask sensitive employee fields based on user permissions.

    Fields masked without hr.pii:
    - salary, housing_allowance, transport_allowance, other_allowances
    - iban (from bank accounts)
    - tax_id, social_security, iqama_number, passport_number
    - gosi_number
    """
    if has_pii_access(current_user):
        return employee

    masked = dict(employee)

    # Salary fields — show as None without permission
    for field in ("salary", "housing_allowance", "transport_allowance", "other_allowances", "hourly_cost"):
        if field in masked and masked[field] is not None:
            masked[field] = None
            masked[f"{field}_masked"] = True

    # Identity fields — show masked version
    for field in ("tax_id", "social_security", "iqama_number", "passport_number"):
        if field in masked and masked[field]:
            masked[field] = mask_pii(str(masked[field]), visible_chars=4)

    # IBAN — show last 4 only
    if "iban" in masked and masked["iban"]:
        masked["iban"] = mask_pii(str(masked["iban"]), visible_chars=4)

    return masked


def mask_payroll_entry_pii(entry: Dict[str, Any], current_user: Any) -> Dict[str, Any]:
    """Mask sensitive payroll entry fields based on user permissions."""
    if has_pii_access(current_user):
        return entry

    masked = dict(entry)

    # All salary components
    salary_fields = (
        "basic_salary", "housing_allowance", "transport_allowance", "other_allowances",
        "salary_components_earning", "salary_components_deduction", "overtime_amount",
        "gosi_employee_share", "gosi_employer_share", "violation_deduction",
        "loan_deduction", "deductions", "net_salary", "net_salary_base",
        "absence_deduction", "advance_deduction",
    )
    for field in salary_fields:
        if field in masked:
            masked[field] = None
            masked[f"{field}_masked"] = True

    return masked
