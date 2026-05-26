"""
Ghost-employee detection — scheduled job.

Scans payroll snapshots per tenant and flags anomalies:

  1. Zero attendance + paid salary
  2. IBAN duplicated across employees
  3. Terminated employee with active payroll entry
  4. Employee missing a manager assignment

Findings are written to ``audit_logs`` with ``critical = True``.
"""

from __future__ import annotations

import logging
from typing import List

from sqlalchemy import text

logger = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _iter_tenant_engines():
    from database import _get_all_company_db_names
    from services.scheduler import _get_company_engine_for_db

    for db_name in _get_all_company_db_names():
        try:
            yield db_name, _get_company_engine_for_db(db_name)
        except Exception:
            logger.exception("[ghost-emp] could not open engine for %s", db_name)


def _table_exists(conn, name: str) -> bool:
    return conn.execute(
        text("SELECT to_regclass(:t)"), {"t": name}
    ).scalar() is not None


# ── rule implementations ─────────────────────────────────────────────────────

def _check_zero_attendance_paid(conn, tenant_id) -> list[dict]:
    """Employees with zero attendance in the pay period but a non-zero net salary."""
    findings: list[dict] = []
    if not _table_exists(conn, "payroll_snapshots") or not _table_exists(conn, "attendance"):
        return findings

    rows = conn.execute(text("""
        SELECT ps.employee_id, e.full_name, ps.period_start, ps.period_end, ps.net_salary
          FROM payroll_snapshots ps
          JOIN employees e ON e.id = ps.employee_id
         WHERE ps.net_salary > 0
           AND NOT EXISTS (
               SELECT 1 FROM attendance a
                WHERE a.employee_id = ps.employee_id
                  AND a.attendance_date BETWEEN ps.period_start AND ps.period_end
                  AND a.status = 'present'
           )
         ORDER BY ps.employee_id
         LIMIT 200
    """)).fetchall()

    for r in rows:
        findings.append({
            "rule": "zero_attendance_paid_salary",
            "employee_id": r.employee_id,
            "employee_name": r.full_name,
            "period": f"{r.period_start} → {r.period_end}",
            "net_salary": str(r.net_salary),
        })
    return findings


def _check_duplicate_iban(conn, tenant_id) -> list[dict]:
    """Multiple active employees sharing the same IBAN."""
    findings: list[dict] = []
    if not _table_exists(conn, "employees"):
        return findings

    rows = conn.execute(text("""
        SELECT bank_iban, array_agg(id) AS emp_ids, array_agg(full_name) AS names
          FROM employees
         WHERE bank_iban IS NOT NULL
           AND bank_iban != ''
           AND employment_status = 'active'
         GROUP BY bank_iban
        HAVING count(*) > 1
         LIMIT 100
    """)).fetchall()

    for r in rows:
        for eid, ename in zip(r.emp_ids, r.names):
            findings.append({
                "rule": "duplicate_iban",
                "iban": r.bank_iban,
                "employee_id": eid,
                "employee_name": ename,
                "all_employee_ids": r.emp_ids,
            })
    return findings


def _check_terminated_active_payroll(conn, tenant_id) -> list[dict]:
    """Terminated employee appearing in a recent payroll run."""
    findings: list[dict] = []
    if not _table_exists(conn, "payroll_snapshots") or not _table_exists(conn, "employees"):
        return findings

    rows = conn.execute(text("""
        SELECT ps.employee_id, e.full_name, e.termination_date, ps.period_start
          FROM payroll_snapshots ps
          JOIN employees e ON e.id = ps.employee_id
         WHERE e.employment_status = 'terminated'
           AND ps.period_start >= e.termination_date
           AND ps.net_salary > 0
         ORDER BY ps.employee_id
         LIMIT 200
    """)).fetchall()

    for r in rows:
        findings.append({
            "rule": "terminated_with_active_payroll",
            "employee_id": r.employee_id,
            "employee_name": r.full_name,
            "termination_date": str(r.termination_date),
            "payroll_period_start": str(r.period_start),
        })
    return findings


def _check_missing_manager(conn, tenant_id) -> list[dict]:
    """Active employees with no manager assigned."""
    findings: list[dict] = []
    if not _table_exists(conn, "employees"):
        return findings

    rows = conn.execute(text("""
        SELECT id, full_name, department
          FROM employees
         WHERE employment_status = 'active'
           AND (manager_id IS NULL OR manager_id = 0)
         ORDER BY id
         LIMIT 500
    """)).fetchall()

    for r in rows:
        findings.append({
            "rule": "missing_manager",
            "employee_id": r.id,
            "employee_name": r.full_name,
            "department": r.department,
        })
    return findings


# ── per-tenant orchestrator ──────────────────────────────────────────────────

def _run_for_tenant(conn, tenant_id) -> List[dict]:
    all_findings: list[dict] = []
    all_findings.extend(_check_zero_attendance_paid(conn, tenant_id))
    all_findings.extend(_check_duplicate_iban(conn, tenant_id))
    all_findings.extend(_check_terminated_active_payroll(conn, tenant_id))
    all_findings.extend(_check_missing_manager(conn, tenant_id))
    return all_findings


# ── public entry point ───────────────────────────────────────────────────────

def run_ghost_employee_check() -> dict:
    """Run the ghost-employee detection across all tenants.

    Returns a summary dict ``{tenant_id: [finding, …], …}``.
    """
    from services.audit_writer import log_activity

    summary: dict[str, list[dict]] = {}

    for db_name, engine in _iter_tenant_engines():
        company_id = db_name.replace("aman_", "", 1)
        try:
            with engine.begin() as conn:
                findings = _run_for_tenant(conn, company_id)

                if findings:
                    summary[company_id] = findings
                    log_activity(
                        conn,
                        action="ghost_employee_detected",
                        entity_type="payroll",
                        actor_id=None,
                        details={
                            "tenant": company_id,
                            "finding_count": len(findings),
                            "findings": findings[:50],
                        },
                        critical=True,
                    )
                    logger.warning(
                        "[ghost-emp][%s] %d finding(s)", company_id, len(findings)
                    )
        except Exception:
            logger.exception("[ghost-emp] tenant %s failed", company_id)

    return summary


__all__ = ["run_ghost_employee_check"]
