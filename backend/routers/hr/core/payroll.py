"""core sub-router — split from monolithic core.py (T6.3).

Mounted under the parent router via core/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from routers.roles import DEFAULT_ROLES
from pydantic import BaseModel
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
import logging
from database import get_db_connection, hash_password
from routers.auth import get_current_user, UserResponse, get_current_user_company
from utils.tx import transactional
from repositories import EmployeeRepository
from utils.permissions import branch_scope_filter, require_permission, require_sensitive_permission, validate_branch_access, check_permission, require_module
from utils.permissions import has_pii_access, mask_pii, mask_pii_list, EMPLOYEE_PII_FIELDS, PAYROLL_PII_FIELDS
from utils.accounting import get_mapped_account_id, get_base_currency
import calendar as cal_module
from utils.fiscal_lock import check_fiscal_period_open
from utils.audit import log_activity
from schemas.hr import LoanCreate, LoanResponse, EmployeeCreate, EmployeeUpdate, DepartmentCreate, DepartmentResponse, PositionCreate, PositionResponse, PayrollPeriodCreate, PayrollEntryResponse, PayrollPeriodResponse, AttendanceResponse, LeaveRequestCreate, LeaveRequestResponse, EndOfServiceRequest
from services.gl_service import create_journal_entry as gl_create_journal_entry

logger = logging.getLogger(__name__)
_D2 = Decimal('0.01')

def _dec(v: Any) -> Decimal:
    return Decimal(str(v or 0))


# T13 — Default Saudi work week (Sun..Thu, ISO weekdays 7,1,2,3,4) used when
# no work_policy is attached to an employee.
_DEFAULT_WORK_DAYS_ISO = {7, 1, 2, 3, 4}
_DEFAULT_DAILY_HOURS   = Decimal('8')
_DEFAULT_WEEKLY_HOURS  = Decimal('40')


def _expected_working_days(start, end, work_days_iso: set) -> int:
    """Return the count of days in ``[start, end]`` whose ISO weekday is in
    ``work_days_iso``. Both endpoints inclusive. Pure stdlib so it can be
    unit-tested without a DB."""
    from datetime import timedelta as _td
    if not start or not end or end < start:
        return 0
    total = 0
    cur = start
    while cur <= end:
        if cur.isoweekday() in work_days_iso:
            total += 1
        cur = cur + _td(days=1)
    return total


router = APIRouter()

from .core import PayslipGenerateRequest, _D2, _dec

@router.get("/payroll-periods", response_model=List[PayrollPeriodResponse], dependencies=[Depends(require_permission(["hr.view", "hr.payroll.view"]))])
def list_payroll_periods(branch_id: Optional[int] = None, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """List Payroll Periods."""
    with transactional(company_id) as conn:
        query = """
            SELECT p.id, p.name, p.start_date, p.end_date, p.status, p.created_at,
                   COALESCE(SUM(e.net_salary), 0) as total_net
            FROM payroll_periods p
            LEFT JOIN payroll_entries e ON p.id = e.period_id
            LEFT JOIN employees emp ON e.employee_id = emp.id
            WHERE 1=1
        """
        params = {}
        query += " " + branch_scope_filter(current_user, branch_id, "emp.branch_id", params, branch_param="bid")
        query += """
            GROUP BY p.id
            ORDER BY p.start_date DESC
        """
        result = conn.execute(text(query), params).fetchall()
        
        periods = []
        for row in result:
            periods.append({
                "id": row.id,
                "name": row.name,
                "start_date": row.start_date,
                "end_date": row.end_date,
                "status": row.status,
                "total_net": row.total_net,
                "created_at": row.created_at,
            })
        return periods

@router.get("/payroll-periods/{period_id}", response_model=PayrollPeriodResponse, dependencies=[Depends(require_permission(["hr.view", "hr.payroll.view"]))])
def get_payroll_period(period_id: int, company_id: str = Depends(get_current_user_company)):
    """Get Payroll Period."""
    with transactional(company_id) as conn:
        query = """
            SELECT p.id, p.name, p.start_date, p.end_date, p.status, p.created_at,
                   COALESCE(SUM(e.net_salary), 0) as total_net
            FROM payroll_periods p
            LEFT JOIN payroll_entries e ON p.id = e.period_id
            WHERE p.id = :id
            GROUP BY p.id
        """
        row = conn.execute(text(query), {"id": period_id}).fetchone()
        
        if not row:
            raise HTTPException(**http_error(404, ("payroll_period_not_found", request)))
            
        return {
            "id": row.id,
            "name": row.name,
            "start_date": row.start_date,
            "end_date": row.end_date,
            "status": row.status,
            "total_net": row.total_net,
            "created_at": row.created_at
        }

@router.post("/payroll-periods", dependencies=[Depends(require_permission(["hr.manage", "hr.payroll.manage"]))], response_model=Dict[str, Any])
def create_payroll_period(period: PayrollPeriodCreate, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Create Payroll Period."""
    with transactional(company_id) as conn:
        # Check overlap? For now skip complex validation
        
        conn.execute(text("""
            INSERT INTO payroll_periods (name, start_date, end_date, payment_date, status)
            VALUES (:name, :start, :end, :pay, 'draft')
        """), {
            "name": period.name,
            "start": period.start_date,
            "end": period.end_date,
            "pay": period.payment_date
        })
        user_id = current_user.get("id") if isinstance(current_user, dict) else current_user.id
        username = current_user.get("username", "") if isinstance(current_user, dict) else getattr(current_user, "username", "")
        log_activity(conn, user_id=user_id, username=username, action="payroll_period.create",
                     resource_type="payroll_period", resource_id=0, details={"name": period.name})
        return {"message": i18n_message(("payroll_created_success", request))}

@router.get("/payroll-periods/{period_id}/entries", response_model=List[PayrollEntryResponse], dependencies=[Depends(require_permission(["hr.view", "hr.payroll.view"]))])
def get_payroll_entries(period_id: int, branch_id: Optional[int] = None, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Get Payroll Entries."""
    with transactional(company_id) as conn:
        query = """
            SELECT pe.id, 
                   e.first_name || ' ' || e.last_name as employee_name,
                   p.position_name as position,
                   pe.basic_salary, pe.housing_allowance, pe.transport_allowance, pe.other_allowances, 
                   pe.deductions, pe.net_salary,
                   pe.currency, pe.exchange_rate, pe.net_salary_base,
                   pe.gosi_employee_share, pe.gosi_employer_share,
                   pe.overtime_amount, pe.violation_deduction, pe.loan_deduction,
                   pe.salary_components_earning, pe.salary_components_deduction
            FROM payroll_entries pe
            JOIN employees e ON pe.employee_id = e.id
            LEFT JOIN employee_positions p ON e.position_id = p.id
            WHERE pe.period_id = :pid
        """
        params = {"pid": period_id}
        query += " " + branch_scope_filter(current_user, branch_id, "e.branch_id", params, branch_param="bid")
            
        query += " ORDER BY e.first_name"
        
        result = conn.execute(text(query), params).fetchall()
        
        entries = []
        for row in result:
            entries.append({
                "id": row.id,
                "employee_name": row.employee_name,
                "position": row.position,
                "basic_salary": row.basic_salary or 0,
                "housing_allowance": row.housing_allowance or 0,
                "transport_allowance": row.transport_allowance or 0,
                "other_allowances": row.other_allowances or 0,
                "deductions": row.deductions or 0,
                "net_salary": row.net_salary or 0,
                "currency": row.currency,
                "exchange_rate": str(row.exchange_rate) if row.exchange_rate else "1",
                "net_salary_base": str(row.net_salary_base) if row.net_salary_base else None,
                "gosi_employee_share": str(row.gosi_employee_share or 0),
                "gosi_employer_share": str(row.gosi_employer_share or 0),
                "overtime_amount": str(row.overtime_amount or 0),
                "violation_deduction": str(row.violation_deduction or 0),
                "loan_deduction": str(row.loan_deduction or 0),
                "salary_components_earning": str(row.salary_components_earning or 0),
                "salary_components_deduction": str(row.salary_components_deduction or 0)
            })
        return entries

# --- LOAN ENDPOINTS ---

@router.post("/loans", response_model=LoanResponse, dependencies=[Depends(require_permission("hr.loans.manage"))])
def create_loan_request(loan: LoanCreate, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Create Loan Request."""
    with transactional(company_id) as conn:
        try:
            monthly_installment = str((_dec(loan.amount) / Decimal(str(loan.total_installments))).quantize(_D2, ROUND_HALF_UP))
            
            # Check if employee exists
            emp = conn.execute(text("SELECT id FROM employees WHERE id=:id"), {"id": loan.employee_id}).fetchone()
            if not emp:
                 raise HTTPException(**http_error(404, ("employee_not_found", request)))
    
            result = conn.execute(text("""
                INSERT INTO employee_loans (employee_id, amount, total_installments, monthly_installment, start_date, reason, status, branch_id)
                VALUES (:eid, :amt, :inst, :month_inst, :start, :reason, 'pending', :bid)
                RETURNING id, created_at, monthly_installment, paid_amount, status
            """), {
                "eid": loan.employee_id, "amt": loan.amount, "inst": loan.total_installments,
                "month_inst": monthly_installment, "start": loan.start_date, "reason": loan.reason,
                "bid": current_user.get("branch_id") if isinstance(current_user, dict) else (current_user.allowed_branches[0] if current_user.allowed_branches else None)
            }).fetchone()
            
            user_id = current_user.get("id") if isinstance(current_user, dict) else current_user.id
            username = current_user.get("username", "") if isinstance(current_user, dict) else getattr(current_user, "username", "")
            log_activity(conn, user_id=user_id, username=username, action="loan.create",
                         resource_type="employee_loan", resource_id=result.id,
                         details={"employee_id": loan.employee_id, "amount": loan.amount})
            return {**loan.model_dump(), "id": result.id, "monthly_installment": result.monthly_installment, 
                    "paid_amount": result.paid_amount, "status": result.status, "created_at": result.created_at}
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))

@router.get("/loans", dependencies=[Depends(require_permission("hr.loans.view"))], response_model=List[Dict[str, Any]])
def list_loans(branch_id: Optional[int] = None, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """List Loans."""
    with transactional(company_id) as conn:
        try:
            query = """
                SELECT l.*, e.first_name || ' ' || e.last_name as employee_name 
                FROM employee_loans l
                JOIN employees e ON l.employee_id = e.id
                WHERE 1=1
            """
            params = {}
            query += " " + branch_scope_filter(current_user, branch_id, "l.branch_id", params, branch_param="bid")
    
            query += " ORDER BY l.created_at DESC"
            
            loans = conn.execute(text(query), params).fetchall()
            return [dict(row._mapping) for row in loans]
        except Exception as e:
            logger.error("list_loans error: %s", e)
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))

@router.put("/loans/{loan_id}/approve", dependencies=[Depends(require_permission("hr.loans.manage"))], response_model=Dict[str, Any])
def approve_loan(loan_id: int, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Approve Loan."""
    conn = get_db_connection(company_id)
    trans = conn.begin()
    try:
        loan = conn.execute(text("SELECT * FROM employee_loans WHERE id=:id FOR UPDATE"), {"id": loan_id}).fetchone()
        if not loan or loan.status != 'pending':
            raise HTTPException(**http_error(400, ("invalid_loan_status", request)))

        # Enforce fiscal period lock before any GL posting on approval
        check_fiscal_period_open(conn, datetime.now().date())

        # Update Status
        conn.execute(text("UPDATE employee_loans SET status='active', approved_by=:uid WHERE id=:id"), 
                     {"uid": current_user.get("id") if isinstance(current_user, dict) else current_user.id, "id": loan_id})
        
        # Create Journal Entry for Loan Disbursement (Automated)
        acc_loan = get_mapped_account_id(conn, "acc_map_loans_adv")
        acc_cash = get_mapped_account_id(conn, "acc_map_cash_main")
        
        if acc_loan and acc_cash:
            from utils.accounting import generate_sequential_number
            je_num = generate_sequential_number(conn, f"LOAN-{datetime.now().year}", "journal_entries", "entry_number")
            base_currency = get_base_currency(conn)
            user_id = current_user.get("id") if isinstance(current_user, dict) else current_user.id
            
            gl_create_journal_entry(
                db=conn,
                company_id=company_id,
                date=datetime.now().date(),
                reference=f"LOAN-{loan_id}",
                description=f"صرف سلفة لموظف - رقم {loan_id}",
                status="posted",
                currency=base_currency,
                exchange_rate=1.0,
                lines=[
                    {
                        "account_id": acc_loan, "debit": loan.amount, "credit": 0,
                        "description": "مدين سلفة موظف"
                    },
                    {
                        "account_id": acc_cash, "debit": 0, "credit": loan.amount,
                        "description": "دائن نقدية/صرف سلفة"
                    }
                ],
                user_id=user_id
            )
        
        trans.commit()
        user_id_val = current_user.get("id") if isinstance(current_user, dict) else current_user.id
        username_val = current_user.get("username", "") if isinstance(current_user, dict) else getattr(current_user, "username", "")
        log_activity(conn, user_id=user_id_val, username=username_val, action="loan.approve",
                     resource_type="employee_loan", resource_id=loan_id,
                     details={"amount": str(loan.amount), "employee_id": loan.employee_id})
        return {"status": "active"}
    except Exception:
        trans.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        conn.close()

@router.post("/payroll-periods/{period_id}/generate", dependencies=[Depends(require_sensitive_permission(["hr.manage", "hr.payroll.manage"], critical=True))], response_model=Dict[str, Any])
def generate_payroll(period_id: int, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Generate Payroll."""
    conn = get_db_connection(company_id)
    trans = conn.begin()
    try:
        # Check status
        period = conn.execute(text("SELECT * FROM payroll_periods WHERE id = :id"), {"id": period_id}).fetchone()
        if not period:
            raise HTTPException(**http_error(404, ("period_not_found", request)))
        if period.status != 'draft':
             raise HTTPException(**http_error(400, ("cannot_generate_non_draft", request)))

        # Clear existing
        conn.execute(text("DELETE FROM payroll_entries WHERE period_id = :id"), {"id": period_id})
        
        # Fetch Active Employees (include currency & branch & work policy)
        employees = conn.execute(text("""
            SELECT e.id, e.salary, e.housing_allowance, e.transport_allowance, e.other_allowances,
                   e.currency, e.branch_id, COALESCE(b.default_currency, 'SAR') as branch_currency,
                   e.work_policy_id,
                   wp.daily_hours          AS wp_daily_hours,
                   wp.weekly_hours         AS wp_weekly_hours,
                   wp.work_days            AS wp_work_days,
                   wp.absence_deduction_method AS wp_method
            FROM employees e
            LEFT JOIN branches b      ON e.branch_id = b.id
            LEFT JOIN work_policies wp ON e.work_policy_id = wp.id AND wp.is_active = TRUE
            WHERE e.status = 'active'
        """)).fetchall()

        # Fetch GOSI settings (active)
        gosi = conn.execute(text("SELECT * FROM gosi_settings WHERE is_active = TRUE ORDER BY id DESC LIMIT 1")).fetchone()
        gosi_emp_pct = _dec(gosi.employee_share_percentage) if gosi and gosi.employee_share_percentage is not None else Decimal('9.75')
        gosi_empr_pct = _dec(gosi.employer_share_percentage) if gosi and gosi.employer_share_percentage is not None else Decimal('11.75')
        gosi_occ_raw = getattr(gosi, "occupational_hazard_percentage", None) if gosi else None
        gosi_occ_pct = _dec(gosi_occ_raw) if gosi_occ_raw is not None else Decimal('2.00')
        gosi_max_sal = _dec(gosi.max_contributable_salary) if gosi and gosi.max_contributable_salary is not None else Decimal('45000')

        base_currency = get_base_currency(conn)

        # T7.5: batch-prefetch all per-employee data to avoid 5×N queries
        # inside the loop. For 500 employees this drops 2500+ round-trips
        # to ~6 queries total.
        emp_ids = [e.id for e in employees]
        comps_by_emp: Dict[int, list] = {}
        ot_by_emp: Dict[int, Decimal] = {}
        viol_by_emp: Dict[int, Decimal] = {}
        loan_by_emp: Dict[int, Any] = {}
        rate_by_currency: Dict[str, Decimal] = {}

        if emp_ids:
            try:
                rows = conn.execute(text("""
                    SELECT esc.employee_id,
                           esc.amount, sc.component_type, sc.calculation_type,
                           sc.percentage_of, sc.percentage_value
                    FROM employee_salary_components esc
                    JOIN salary_components sc ON esc.component_id = sc.id
                    WHERE esc.is_active = TRUE AND sc.is_active = TRUE
                      AND esc.employee_id = ANY(:eids)
                """), {"eids": emp_ids}).fetchall()
                for r in rows:
                    comps_by_emp.setdefault(r.employee_id, []).append(r)
            except Exception as exc:
                logger.warning("employee_salary_components skipped for company %s: %s", company_id, exc)

            try:
                # T10.2 #183 \u2014 previously aggregated ALL approved
                # overtime regardless of date, so a request approved in
                # March could be paid again in May. Filter by overtime_date
                # within the payroll period and exclude already-processed.
                rows = conn.execute(text("""
                    SELECT employee_id, COALESCE(SUM(calculated_amount), 0) AS total
                    FROM overtime_requests
                    WHERE status = 'approved'
                      AND employee_id = ANY(:eids)
                      AND overtime_date >= :s
                      AND overtime_date <= :e
                    GROUP BY employee_id
                """), {"eids": emp_ids, "s": period.start_date, "e": period.end_date}).fetchall()
                for r in rows:
                    ot_by_emp[r.employee_id] = _dec(r.total)
            except Exception:
                pass

            try:
                rows = conn.execute(text("""
                    SELECT employee_id, COALESCE(SUM(penalty_amount), 0) AS total
                    FROM employee_violations
                    WHERE deduct_from_salary = TRUE AND status = 'open'
                      AND payroll_period_id IS NULL
                      AND employee_id = ANY(:eids)
                    GROUP BY employee_id
                """), {"eids": emp_ids}).fetchall()
                for r in rows:
                    viol_by_emp[r.employee_id] = _dec(r.total)
            except Exception:
                pass

            try:
                rows = conn.execute(text("""
                    SELECT * FROM employee_loans
                    WHERE status = 'active' AND paid_amount < amount
                      AND employee_id = ANY(:eids)
                """), {"eids": emp_ids}).fetchall()
                for r in rows:
                    # First active loan per employee (mirrors prior fetchone)
                    loan_by_emp.setdefault(r.employee_id, r)
            except Exception:
                pass

            # T15 #71/#104 — Salary advances awaiting recovery. We only pull
            # advances in status 'paid' or 'recovering' (the cash has left
            # the treasury so it MUST be recouped) and where any balance
            # remains (recovered_amount < amount).
            advance_by_emp: Dict[int, Any] = {}
            try:
                rows = conn.execute(text("""
                    SELECT id, employee_id, amount, recovered_amount, installments
                    FROM salary_advances
                    WHERE status IN ('paid', 'recovering')
                      AND recovered_amount < amount
                      AND employee_id = ANY(:eids)
                    ORDER BY id
                """), {"eids": emp_ids}).fetchall()
                for r in rows:
                    advance_by_emp.setdefault(r.employee_id, r)
            except Exception:
                pass

            currencies = sorted({
                (getattr(e, 'currency', None) or getattr(e, 'branch_currency', None) or base_currency)
                for e in employees
            })
            non_base = [c for c in currencies if c and c != base_currency]
            if non_base:
                try:
                    rows = conn.execute(text("""
                        SELECT code, current_rate FROM currencies
                        WHERE is_active = TRUE AND code = ANY(:codes)
                    """), {"codes": non_base}).fetchall()
                    for r in rows:
                        rate_by_currency[r.code] = _dec(r.current_rate) if r.current_rate else Decimal('1')
                except Exception:
                    pass

        # T13 #64/#65 — Attendance & work-policy driven absence deduction.
        # We compute *expected working days* in [start_date, end_date] from
        # ``work_policy.work_days`` (ISO weekday list) and subtract days where
        # the employee has an attendance row with status='present' (or any
        # row at all, since absence is the missing-row case). Result drives a
        # per-day or per-hour deduction depending on the policy method.
        attendance_present_by_emp: Dict[int, int] = {}
        try:
            period_start = period.start_date
            period_end   = period.end_date
        except Exception:
            period_start = period_end = None

        if emp_ids and period_start and period_end:
            try:
                rows = conn.execute(text("""
                    SELECT employee_id, COUNT(*) AS present_days
                    FROM attendance
                    WHERE employee_id = ANY(:eids)
                      AND date BETWEEN :s AND :e
                      AND COALESCE(status, 'present') IN ('present', 'late')
                    GROUP BY employee_id
                """), {"eids": emp_ids, "s": period_start, "e": period_end}).fetchall()
                for r in rows:
                    attendance_present_by_emp[r.employee_id] = int(r.present_days or 0)
            except Exception:
                pass

        insert_rows: List[Dict[str, Any]] = []
        count = 0
        for emp in employees:
            basic: Decimal = _dec(emp.salary)
            housing: Decimal = _dec(emp.housing_allowance)
            transport: Decimal = _dec(emp.transport_allowance)
            other: Decimal = _dec(emp.other_allowances)

            # === 1. Salary Components (earnings & deductions) ===
            comp_earning = Decimal('0')
            comp_deduction = Decimal('0')
            for comp in comps_by_emp.get(emp.id, []):
                if comp.calculation_type == 'percentage':
                    base_val = basic if (comp.percentage_of or 'basic') == 'basic' else (basic + housing)
                    amt = (_dec(comp.percentage_value) / Decimal('100') * base_val).quantize(_D2, ROUND_HALF_UP)
                else:
                    amt = _dec(comp.amount)
                if comp.component_type == 'earning':
                    comp_earning += amt
                else:
                    comp_deduction += amt

            # === 2. Approved Overtime (not yet processed) ===
            overtime_amount = ot_by_emp.get(emp.id, Decimal('0'))

            # === 3. GOSI Deductions ===
            contributable = min(basic + housing, gosi_max_sal)
            gosi_emp_share = (contributable * gosi_emp_pct / Decimal('100')).quantize(_D2, ROUND_HALF_UP)
            gosi_empr_share = (contributable * (gosi_empr_pct + gosi_occ_pct) / Decimal('100')).quantize(_D2, ROUND_HALF_UP)

            # === 4. Violation Deductions (open, deduct_from_salary, not yet deducted) ===
            violation_deduction = viol_by_emp.get(emp.id, Decimal('0'))

            # === 5. Loan Deductions ===
            active_loan = loan_by_emp.get(emp.id)
            loan_deduction = Decimal('0')
            if active_loan:
                loan_deduction = min(_dec(active_loan.monthly_installment), _dec(active_loan.amount) - _dec(active_loan.paid_amount))

            # === 5b. Salary Advance Recovery (T15 #71/#104) ===
            # Spread the unpaid balance across remaining installments. We
            # never deduct more than what's still outstanding.
            active_advance = advance_by_emp.get(emp.id)
            advance_deduction = Decimal('0')
            if active_advance:
                outstanding = _dec(active_advance.amount) - _dec(active_advance.recovered_amount)
                inst = max(1, int(active_advance.installments or 1))
                per_run = (_dec(active_advance.amount) / Decimal(inst)).quantize(_D2, ROUND_HALF_UP)
                advance_deduction = min(per_run, outstanding)

            # === 6. Absence Deductions (T13 #64/#65) ===
            # Pull the ISO-weekday work-day list from the employee's policy
            # (falls back to Saudi default Sun..Thu). For the period window we
            # compute expected days, then subtract present/late attendance
            # rows. Anything left is treated as unpaid absence.
            absence_deduction = Decimal('0')
            absent_days = 0
            if period_start and period_end:
                wd_raw = getattr(emp, 'wp_work_days', None)
                if isinstance(wd_raw, (list, tuple)):
                    work_days_iso = {int(x) for x in wd_raw if x is not None}
                elif isinstance(wd_raw, str) and wd_raw.strip().startswith('['):
                    try:
                        import json as _json
                        work_days_iso = {int(x) for x in _json.loads(wd_raw)}
                    except Exception:
                        work_days_iso = set(_DEFAULT_WORK_DAYS_ISO)
                else:
                    work_days_iso = set(_DEFAULT_WORK_DAYS_ISO)
                expected = _expected_working_days(period_start, period_end, work_days_iso)
                present  = attendance_present_by_emp.get(emp.id, expected)  # no rows ⇒ assume present (legacy)
                absent_days = max(0, expected - present)
                if absent_days > 0 and expected > 0:
                    method = (getattr(emp, 'wp_method', None) or 'daily_rate').lower()
                    daily_h  = _dec(getattr(emp, 'wp_daily_hours',  None)) or _DEFAULT_DAILY_HOURS
                    weekly_h = _dec(getattr(emp, 'wp_weekly_hours', None)) or _DEFAULT_WEEKLY_HOURS
                    if method == 'hourly' and weekly_h > 0:
                        # Approx monthly hours = weekly_hours * 4.33
                        monthly_hours = weekly_h * Decimal('4.33')
                        if monthly_hours > 0:
                            absence_deduction = ((basic + housing) / monthly_hours) * (daily_h * Decimal(absent_days))
                    else:
                        # daily_rate (default): salary / expected_working_days
                        daily_rate = (basic + housing) / Decimal(expected)
                        absence_deduction = daily_rate * Decimal(absent_days)
                    absence_deduction = absence_deduction.quantize(_D2, ROUND_HALF_UP)

            # === Calculate totals ===
            total_earnings = basic + housing + transport + other + comp_earning + overtime_amount
            total_deductions = comp_deduction + gosi_emp_share + violation_deduction + loan_deduction + absence_deduction + advance_deduction
            net = (total_earnings - total_deductions).quantize(_D2, ROUND_HALF_UP)

            # === Currency & Exchange Rate ===
            emp_currency = getattr(emp, 'currency', None) or getattr(emp, 'branch_currency', None) or base_currency
            if emp_currency and emp_currency != base_currency:
                exchange_rate = rate_by_currency.get(emp_currency, Decimal('1'))
            else:
                exchange_rate = Decimal('1')

            net_base = (net * exchange_rate).quantize(_D2, ROUND_HALF_UP)

            insert_rows.append({
                "pid": period_id, "eid": emp.id,
                "basic": str(basic), "housing": str(housing), "transport": str(transport), "other": str(other),
                "comp_earn": str(comp_earning), "comp_ded": str(comp_deduction),
                "overtime": str(overtime_amount), "gosi_emp": str(gosi_emp_share), "gosi_empr": str(gosi_empr_share),
                "viol_ded": str(violation_deduction), "loan_ded": str(loan_deduction),
                "abs_ded": str(absence_deduction), "abs_days": absent_days,
                "adv_ded": str(advance_deduction),
                "total_ded": str(total_deductions), "net": str(net),
                "currency": emp_currency, "exchange_rate": str(exchange_rate), "net_base": str(net_base),
            })
            count += 1

        if insert_rows:
            # T7.5: single executemany call instead of N separate INSERTs.
            conn.execute(text("""
                INSERT INTO payroll_entries (
                    period_id, employee_id, basic_salary, housing_allowance, transport_allowance,
                    other_allowances, salary_components_earning, salary_components_deduction,
                    overtime_amount, gosi_employee_share, gosi_employer_share,
                    violation_deduction, loan_deduction, absence_deduction, absent_days,
                    advance_deduction,
                    deductions, net_salary,
                    currency, exchange_rate, net_salary_base
                )
                VALUES (:pid, :eid, :basic, :housing, :transport, :other, :comp_earn, :comp_ded,
                        :overtime, :gosi_emp, :gosi_empr, :viol_ded, :loan_ded, :abs_ded, :abs_days,
                        :adv_ded,
                        :total_ded, :net,
                        :currency, :exchange_rate, :net_base)
            """), insert_rows)
            
        trans.commit()
        user_id = current_user.get("id") if isinstance(current_user, dict) else current_user.id
        username = current_user.get("username", "") if isinstance(current_user, dict) else getattr(current_user, "username", "")
        log_activity(conn, user_id=user_id, username=username, action="payroll.generate",
                     resource_type="payroll_period", resource_id=period_id,
                     details={"employee_count": count})
        return {"message": i18n_message("payroll_generated_success", request)}
    except Exception:
        trans.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        conn.close()

@router.post("/payroll-periods/{period_id}/post", dependencies=[Depends(require_sensitive_permission(["hr.manage", "hr.payroll.manage"], critical=True))], response_model=Dict[str, Any])
def post_payroll(period_id: int, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Post Payroll."""
    conn = get_db_connection(company_id)
    trans = conn.begin()
    try:
        # 1. Check Status
        period = conn.execute(text("SELECT * FROM payroll_periods WHERE id = :id"), {"id": period_id}).fetchone()
        if not period or period.status != 'draft':
            raise HTTPException(**http_error(400, ("invalid_period_status", request)))

        # FISCAL-LOCK: Prevent posting payroll into a closed accounting period
        check_fiscal_period_open(conn, period.end_date)

        base_currency = get_base_currency(conn)

        # 2. Calculate Totals in BASE currency (convert foreign currency amounts)
        totals = conn.execute(text("""
            SELECT 
                SUM(COALESCE(net_salary_base, net_salary * COALESCE(exchange_rate, 1))) as total_net_base,
                SUM((basic_salary + housing_allowance + transport_allowance + other_allowances + salary_components_earning + overtime_amount) * COALESCE(exchange_rate, 1)) as total_gross_base,
                SUM(gosi_employee_share * COALESCE(exchange_rate, 1)) as total_gosi_emp_base,
                SUM(gosi_employer_share * COALESCE(exchange_rate, 1)) as total_gosi_empr_base,
                SUM(overtime_amount * COALESCE(exchange_rate, 1)) as total_overtime_base,
                SUM(violation_deduction * COALESCE(exchange_rate, 1)) as total_violations_base,
                SUM(loan_deduction * COALESCE(exchange_rate, 1)) as total_loans_base,
                SUM(salary_components_deduction * COALESCE(exchange_rate, 1)) as total_comp_ded_base
            FROM payroll_entries WHERE period_id = :id
        """), {"id": period_id}).fetchone()
        
        total_net = _dec(totals.total_net_base)
        totals_gross = _dec(totals.total_gross_base)
        total_gosi_emp = _dec(totals.total_gosi_emp_base)
        total_gosi_empr = _dec(totals.total_gosi_empr_base)
        total_violations = _dec(totals.total_violations_base)
        total_loans = _dec(totals.total_loans_base)
        total_comp_ded = _dec(totals.total_comp_ded_base)
        
        # Get net salary grouped by currency for bank payout lines
        net_by_currency = conn.execute(text("""
            SELECT COALESCE(currency, :base) as pay_currency,
                   SUM(net_salary) as total_net_local,
                   SUM(COALESCE(net_salary_base, net_salary * COALESCE(exchange_rate, 1))) as total_net_base,
                   MAX(COALESCE(exchange_rate, 1)) as rate
            FROM payroll_entries WHERE period_id = :id
            GROUP BY COALESCE(currency, :base)
        """), {"id": period_id, "base": base_currency}).fetchall()
        
        if total_net == Decimal('0'):
            raise HTTPException(**http_error(400, ("no_payroll_to_post", request)))

        # 3. Handle Loan Deductions & Balances
        if total_loans > 0:
            entries_with_loans = conn.execute(text("SELECT employee_id, loan_deduction FROM payroll_entries WHERE period_id = :id AND loan_deduction > 0"), {"id": period_id}).fetchall()
            # T7.5: batch-fetch all active loans in one query.
            loan_eids = [e.employee_id for e in entries_with_loans]
            loans_map: Dict[int, Any] = {}
            if loan_eids:
                loan_rows = conn.execute(
                    text(
                        "SELECT * FROM employee_loans "
                        "WHERE employee_id = ANY(:eids) "
                        "  AND status='active' AND paid_amount < amount"
                    ),
                    {"eids": loan_eids},
                ).fetchall()
                for r in loan_rows:
                    loans_map.setdefault(r.employee_id, r)
            loan_updates: List[Dict[str, Any]] = []
            for entry in entries_with_loans:
                loan = loans_map.get(entry.employee_id)
                if loan:
                    new_paid = _dec(loan.paid_amount) + _dec(entry.loan_deduction)
                    new_status = 'completed' if new_paid >= _dec(loan.amount) else 'active'
                    loan_updates.append({
                        "paid": str(new_paid.quantize(_D2, ROUND_HALF_UP)),
                        "status": new_status,
                        "id": loan.id,
                    })
            if loan_updates:
                conn.execute(
                    text("UPDATE employee_loans SET paid_amount = :paid, status = :status WHERE id=:id"),
                    loan_updates,
                )

        # 3b. Handle Salary Advance Recovery (T15 #71/#104) — mirror loan
        # bookkeeping: bump recovered_amount, flip to 'recovering' or
        # 'recovered' as appropriate.
        try:
            entries_with_adv = conn.execute(text(
                "SELECT employee_id, advance_deduction FROM payroll_entries "
                "WHERE period_id = :id AND advance_deduction > 0"
            ), {"id": period_id}).fetchall()
            if entries_with_adv:
                adv_eids = [e.employee_id for e in entries_with_adv]
                adv_rows = conn.execute(text(
                    "SELECT id, employee_id, amount, recovered_amount FROM salary_advances "
                    "WHERE employee_id = ANY(:eids) "
                    "  AND status IN ('paid', 'recovering') "
                    "  AND recovered_amount < amount"
                ), {"eids": adv_eids}).fetchall()
                adv_map: Dict[int, Any] = {}
                for r in adv_rows:
                    adv_map.setdefault(r.employee_id, r)
                adv_updates: List[Dict[str, Any]] = []
                for entry in entries_with_adv:
                    adv = adv_map.get(entry.employee_id)
                    if not adv:
                        continue
                    new_rec = _dec(adv.recovered_amount) + _dec(entry.advance_deduction)
                    new_status = 'recovered' if new_rec >= _dec(adv.amount) else 'recovering'
                    adv_updates.append({
                        "rec": str(new_rec.quantize(_D2, ROUND_HALF_UP)),
                        "status": new_status,
                        "id": adv.id,
                    })
                if adv_updates:
                    conn.execute(text(
                        "UPDATE salary_advances SET recovered_amount = :rec, "
                        "status = :status, updated_at = NOW() WHERE id = :id"
                    ), adv_updates)
        except Exception:
            # Tenants without the salary_advances table (legacy) just skip.
            pass

        # 4. Mark processed overtime requests (so they're not counted again)
        try:
            # T7.5: single UPDATE instead of one per employee.
            conn.execute(
                text(
                    "UPDATE overtime_requests SET status = 'processed' "
                    "WHERE status = 'approved' AND employee_id IN ("
                    "  SELECT employee_id FROM payroll_entries "
                    "  WHERE period_id = :pid AND overtime_amount > 0)"
                ),
                {"pid": period_id},
            )
        except Exception:
            pass  # 'processed' status may not exist, safe to skip

        # 5. Mark violations as deducted (link to payroll period)
        try:
            # T7.5: single UPDATE instead of one per employee.
            conn.execute(
                text(
                    "UPDATE employee_violations SET payroll_period_id = :pid, status = 'resolved' "
                    "WHERE deduct_from_salary = TRUE AND status = 'open' "
                    "  AND payroll_period_id IS NULL "
                    "  AND employee_id IN ("
                    "    SELECT employee_id FROM payroll_entries "
                    "    WHERE period_id = :pid AND violation_deduction > 0)"
                ),
                {"pid": period_id},
            )
        except Exception:
            pass

        # 6. Create Journal Entry
        # Dr Salaries & Wages Expense (Gross: basic + housing + transport + other + components + overtime)
        # Dr GOSI Employer Expense (employer's share)
        #   Cr GOSI Payable (employee share + employer share)
        #   Cr Employee Loans (loan deductions)
        #   Cr Bank/Cash (net salary payout)
        
        from utils.accounting import generate_sequential_number
        je_num = generate_sequential_number(conn, f"PAY-{datetime.now().year}", "journal_entries", "entry_number")
        user_id = current_user.get("id") if isinstance(current_user, dict) else current_user.id
        branch_id = current_user.get("branch_id") if isinstance(current_user, dict) else (current_user.allowed_branches[0] if current_user.allowed_branches else None)
        
        lines = []

        # Line 1: Dr Salaries Expense (Gross)
        acc_salaries_exp = get_mapped_account_id(conn, "acc_map_salaries_exp")
        if acc_salaries_exp:
            lines.append({
                "account_id": acc_salaries_exp, "debit": totals_gross, "credit": 0,
                "description": 'مصروف رواتب وأجور - Salaries Expense',
                "currency": base_currency, "exchange_rate": 1.0
            })

        # Line 2: Dr GOSI Employer Expense
        if total_gosi_empr > Decimal('0'):
            acc_gosi_exp = get_mapped_account_id(conn, "acc_map_gosi_expense")
            if acc_gosi_exp:
                lines.append({
                    "account_id": acc_gosi_exp, "debit": total_gosi_empr, "credit": 0,
                    "description": 'مصروف تأمينات اجتماعية (حصة صاحب العمل) - GOSI Employer',
                    "currency": base_currency, "exchange_rate": 1.0
                })

        # Line 3: Cr GOSI Payable (employee + employer shares)
        total_gosi = total_gosi_emp + total_gosi_empr
        if total_gosi > Decimal('0'):
            acc_gosi_payable = get_mapped_account_id(conn, "acc_map_gosi_payable")
            if acc_gosi_payable:
                lines.append({
                    "account_id": acc_gosi_payable, "debit": 0, "credit": total_gosi,
                    "description": 'التأمينات المستحقة (حصة موظف + صاحب عمل) - GOSI Payable',
                    "currency": base_currency, "exchange_rate": 1.0
                })

        # Line 4: Cr Employee Loans (Deductions)
        if total_loans > Decimal('0'):
            acc_loans_adv = get_mapped_account_id(conn, "acc_map_loans_adv")
            if acc_loans_adv:
                lines.append({
                    "account_id": acc_loans_adv, "debit": 0, "credit": total_loans,
                    "description": 'استقطاع سلف موظفين - Loan Repayment',
                    "currency": base_currency, "exchange_rate": 1.0
                })

        # Line 5: Cr Violation Deductions
        if total_violations > Decimal('0'):
            acc_violations = get_mapped_account_id(conn, "acc_map_violations") or get_mapped_account_id(conn, "acc_map_other_payable")
            if acc_violations:
                lines.append({
                    "account_id": acc_violations, "debit": 0, "credit": total_violations,
                    "description": 'استقطاع مخالفات موظفين - Violation Deductions',
                    "currency": base_currency, "exchange_rate": 1.0
                })

        # Line 6: Cr Salary Component Deductions (other deductions)
        if total_comp_ded > Decimal('0'):
            acc_comp_ded = get_mapped_account_id(conn, "acc_map_other_deductions") or get_mapped_account_id(conn, "acc_map_other_payable")
            if acc_comp_ded:
                lines.append({
                    "account_id": acc_comp_ded, "debit": 0, "credit": total_comp_ded,
                    "description": 'استقطاعات عناصر الراتب - Salary Component Deductions',
                    "currency": base_currency, "exchange_rate": 1.0
                })

        # Line 7: Cr Bank (Net Payout) — one line per currency for proper tracking
        total_net_all = Decimal('0')
        acc_bank = get_mapped_account_id(conn, "acc_map_bank")
        if acc_bank:
            for cur_row in net_by_currency:
                pay_currency = cur_row.pay_currency
                local_amount = _dec(cur_row.total_net_local)
                base_amount = _dec(cur_row.total_net_base)
                rate = _dec(cur_row.rate)

                if pay_currency == base_currency:
                    desc_text = f'صافي الرواتب المحولة - Net Salary Payment ({pay_currency})'
                else:
                    desc_text = f'صافي الرواتب المحولة - Net Salary Payment ({str(local_amount)} {pay_currency} × {str(rate)})'

                lines.append({
                    "account_id": acc_bank, "debit": 0, "credit": base_amount,
                    "description": desc_text,
                    "currency": pay_currency, "exchange_rate": rate
                })
                total_net_all += base_amount

        if lines:
            gl_create_journal_entry(
                db=conn,
                company_id=company_id,
                date=datetime.now().date(),
                description=f"Payroll for period {period.name}",
                status="posted",
                currency=base_currency,
                exchange_rate=1.0,
                branch_id=branch_id,
                source="payroll",
                source_id=period_id,
                lines=lines,
                user_id=user_id
            )

        # 7a. Update Treasury (bank) balance to keep treasury in sync with GL
        if total_net_all > Decimal('0'):
            try:
                # Find treasury account linked to the GL bank account
                treasury = conn.execute(text("""
                    SELECT id FROM treasury_accounts
                    WHERE gl_account_id = :gl_id AND is_active = TRUE
                    LIMIT 1
                """), {"gl_id": acc_bank}).fetchone() if acc_bank else None
                if treasury:
                    conn.execute(text("""
                        UPDATE treasury_accounts
                        SET current_balance = current_balance - :amt, updated_at = CURRENT_TIMESTAMP
                        WHERE id = :tid
                    """), {"amt": str(total_net_all), "tid": treasury.id})
            except Exception as tres_err:
                logger.warning(f"Treasury balance update for payroll skipped: {tres_err}")

        # 7. Update Period Status
        conn.execute(text("UPDATE payroll_periods SET status='posted' WHERE id=:id"), {"id": period_id})

        # 8. Notify HR admins about payroll posting
        try:
            emp_count = conn.execute(text("SELECT COUNT(*) FROM payroll_entries WHERE period_id = :id"), {"id": period_id}).scalar() or 0
            conn.execute(text("""
                INSERT INTO notifications (user_id, type, title, message, link, is_read, created_at)
                SELECT DISTINCT u.id, 'payroll', :title, :message, :link, FALSE, NOW()
                FROM company_users u
                WHERE u.is_active = TRUE
                AND u.role IN ('admin', 'superuser')
            """), {
                "title": i18n_message("notif_payroll_posted", request),
                "message": i18n_message("payroll_posted_details", request),
                "link": "/hr/payroll"
            })
        except Exception:
            pass  # Non-blocking

        trans.commit()
        log_activity(conn, user_id=user_id, username=current_user.get("username", "") if isinstance(current_user, dict) else getattr(current_user, "username", ""),
                     action="payroll.post", resource_type="payroll_period", resource_id=period_id,
                     details={"journal_entry": je_num, "total_net": str(total_net)})
        return {"message": i18n_message("payroll_posted_success", request), "journal_entry": je_num}

    except Exception:
        trans.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        conn.close()

# --- Departments ---
@router.get("/payslips", dependencies=[Depends(require_permission("hr.view"))], response_model=List[Dict[str, Any]])
def list_all_payslips(branch_id: Optional[int] = None, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """List All Payslips.

    P1 #110a fix: previously this endpoint returned `basic_salary`,
    allowances, deductions and `net_pay` for *every* employee whenever
    the caller had `hr.view` — bypassing the per-employee PII gate at
    `/employees/{id}/payslips`. Now we mask payroll PII fields unless
    the caller has `hr.pii` (or is the salary owner — handled in the
    per-employee endpoint). Callers without `hr.pii` see only ids,
    employee_name, period and status.
    """
    with transactional(company_id) as conn:
        q = """
            SELECT pe.id, pe.employee_id, pe.period_id,
                   e.first_name || ' ' || e.last_name as employee_name,
                   pe.basic_salary,
                   COALESCE(pe.housing_allowance,0)+COALESCE(pe.transport_allowance,0)+COALESCE(pe.other_allowances,0)+COALESCE(pe.salary_components_earning,0)+COALESCE(pe.overtime_amount,0) as total_allowances,
                   COALESCE(pe.deductions,0) as total_deductions,
                   pe.net_salary as net_pay,
                   pp.status,
                   EXTRACT(MONTH FROM pp.start_date)::int as month,
                   EXTRACT(YEAR FROM pp.start_date)::int as year
            FROM payroll_entries pe
            JOIN employees e ON pe.employee_id = e.id
            JOIN payroll_periods pp ON pe.period_id = pp.id
            WHERE 1=1
        """
        params = {}
        q += " " + branch_scope_filter(current_user, branch_id, "e.branch_id", params, branch_param="bid")
        q += " ORDER BY pp.start_date DESC, e.first_name"
        result = conn.execute(text(q), params).fetchall()
        rows = [dict(row._mapping) for row in result]
        # P1 #110a — mask payroll PII when the caller lacks hr.pii.
        if not has_pii_access(current_user):
            rows = mask_pii_list(rows, PAYROLL_PII_FIELDS)
        return rows


@router.get("/payslips/{entry_id}", dependencies=[Depends(require_permission("hr.view"))], response_model=Dict[str, Any])
def get_payslip_detail(
    entry_id: int,
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company),
):
    """Get Payslip Detail."""
    with transactional(company_id) as conn:
        row = conn.execute(text("""
            SELECT pe.*, e.first_name || ' ' || e.last_name as employee_name,
                   pp.status, pp.name as period_name,
                   EXTRACT(MONTH FROM pp.start_date)::int as month,
                   EXTRACT(YEAR FROM pp.start_date)::int as year,
                   e.user_id as _employee_user_id
            FROM payroll_entries pe
            JOIN employees e ON pe.employee_id = e.id
            JOIN payroll_periods pp ON pe.period_id = pp.id
            WHERE pe.id = :id
        """), {"id": entry_id}).fetchone()
        if not row:
            raise HTTPException(**http_error(404, ("payslip_not_found", request)))
        data = dict(row._mapping)
        owner_user_id = data.pop("_employee_user_id", None)
        # T2.4: mask unless caller has hr.pii or is the employee themselves
        if not has_pii_access(current_user):
            uid = current_user.get("id") if isinstance(current_user, dict) else current_user.id
            if owner_user_id != uid:
                data = mask_pii(data, PAYROLL_PII_FIELDS)
        return data


@router.post("/payslips/generate", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def generate_single_payslip(data: PayslipGenerateRequest, company_id: str = Depends(get_current_user_company)):
    """Generate Single Payslip."""
    with transactional(company_id) as conn:
        last_day = cal_module.monthrange(data.year, data.month)[1]
        start_date = f"{data.year}-{data.month:02d}-01"
        end_date = f"{data.year}-{data.month:02d}-{last_day}"
        period_name = f"Payroll {data.month}/{data.year}"

        period = conn.execute(text("""
            SELECT id FROM payroll_periods
            WHERE EXTRACT(MONTH FROM start_date)=:m AND EXTRACT(YEAR FROM start_date)=:y
        """), {"m": data.month, "y": data.year}).fetchone()

        if not period:
            res = conn.execute(text("""
                INSERT INTO payroll_periods (name,start_date,end_date,payment_date,status)
                VALUES (:name,:start,:end,:end,'draft') RETURNING id
            """), {"name": period_name, "start": start_date, "end": end_date})
            period_id = res.fetchone()[0]
        else:
            period_id = period.id

        emp = conn.execute(text("""
            SELECT e.id, e.salary,
                   COALESCE(ss.basic_salary, e.salary, 0) as basic_salary,
                   COALESCE(ss.housing_allowance, 0) as housing_allowance,
                   COALESCE(ss.transport_allowance, 0) as transport_allowance,
                   COALESCE(ss.other_allowances, 0) as other_allowances
            FROM employees e
            LEFT JOIN salary_structures ss ON e.salary_structure_id = ss.id
            WHERE e.id = :id
        """), {"id": data.employee_id}).fetchone()

        if not emp:
            raise HTTPException(**http_error(404, ("employee_not_found", request)))

        existing = conn.execute(text(
            "SELECT id FROM payroll_entries WHERE period_id=:pid AND employee_id=:eid"
        ), {"pid": period_id, "eid": data.employee_id}).fetchone()

        if existing:
            raise HTTPException(**http_error(400, ("payslip_already_exists", request)))

        basic = _dec(emp.basic_salary)
        housing = _dec(emp.housing_allowance)
        transport = _dec(emp.transport_allowance)
        other = _dec(emp.other_allowances)
        gross = basic + housing + transport + other

        # Calculate GOSI deductions
        # T10.2 #185: must use *active* settings and the actual column names
        # (`employee_share_percentage` / `employer_share_percentage`) to match
        # `generate_payroll` and the gosi_settings schema. Employer share
        # excludes occupational hazard, which is added separately below.
        gosi_settings = conn.execute(text(
            "SELECT * FROM gosi_settings WHERE is_active = TRUE ORDER BY id DESC LIMIT 1"
        )).fetchone()
        gosi_emp = Decimal('0')
        gosi_empr = Decimal('0')
        if gosi_settings:
            gosi_max_sal = _dec(gosi_settings.max_contributable_salary) if gosi_settings.max_contributable_salary else Decimal('45000')
            emp_rate = _dec(gosi_settings.employee_share_percentage) if gosi_settings.employee_share_percentage else Decimal('9.75')
            empr_rate = _dec(gosi_settings.employer_share_percentage) if gosi_settings.employer_share_percentage else Decimal('11.75')
            occ_rate = _dec(getattr(gosi_settings, "occupational_hazard_percentage", None)) if getattr(gosi_settings, "occupational_hazard_percentage", None) else Decimal('2.00')
            contributable = min(basic + housing, gosi_max_sal)
            gosi_emp = (contributable * emp_rate / Decimal('100')).quantize(_D2, ROUND_HALF_UP)
            gosi_empr = (contributable * (empr_rate + occ_rate) / Decimal('100')).quantize(_D2, ROUND_HALF_UP)

        # Calculate violation deductions for the month
        violation_total = conn.execute(text("""
            SELECT COALESCE(SUM(deduction_amount), 0) FROM employee_violations
            WHERE employee_id = :eid AND violation_date BETWEEN :start AND :end AND status = 'approved'
        """), {"eid": data.employee_id, "start": start_date, "end": end_date}).scalar() or 0
        violation_deduction = _dec(violation_total)

        # Calculate loan deductions
        loan_deduction = Decimal('0')
        active_loan = conn.execute(text("""
            SELECT monthly_deduction FROM employee_loans
            WHERE employee_id = :eid AND status = 'active' AND paid_amount < amount
            LIMIT 1
        """), {"eid": data.employee_id}).fetchone()
        if active_loan:
            loan_deduction = _dec(active_loan.monthly_deduction)

        # Calculate salary component earnings/deductions
        comp_earning = Decimal('0')
        comp_deduction = Decimal('0')
        components = conn.execute(text("""
            SELECT sc.amount, sc.component_type
            FROM salary_components sc
            WHERE sc.employee_id = :eid AND sc.is_active = TRUE
        """), {"eid": data.employee_id}).fetchall()
        for comp in components:
            if comp.component_type == 'earning':
                comp_earning += _dec(comp.amount)  # pyre-ignore
            elif comp.component_type == 'deduction':
                comp_deduction += _dec(comp.amount)  # pyre-ignore

        total_deductions = gosi_emp + violation_deduction + loan_deduction + comp_deduction  # pyre-ignore
        net = gross + comp_earning - total_deductions  # pyre-ignore

        conn.execute(text("""
            INSERT INTO payroll_entries
            (period_id,employee_id,basic_salary,housing_allowance,transport_allowance,other_allowances,
             salary_components_earning,salary_components_deduction,overtime_amount,
             gosi_employee_share,gosi_employer_share,violation_deduction,loan_deduction,deductions,net_salary)
            VALUES (:pid,:eid,:basic,:housing,:transport,:other,:comp_earn,:comp_ded,0,:gosi_emp,:gosi_empr,:violation,:loan,:deductions,:net)
        """), {"pid": period_id, "eid": data.employee_id, "basic": str(basic),
               "housing": str(housing), "transport": str(transport), "other": str(other),
               "comp_earn": str(comp_earning), "comp_ded": str(comp_deduction),
               "gosi_emp": str(gosi_emp), "gosi_empr": str(gosi_empr),
               "violation": str(violation_deduction), "loan": str(loan_deduction),
               "deductions": str(total_deductions), "net": str(net)})
        return {"message": i18n_message(("payslip_generated_success", request))}


# --- Recruitment ---

