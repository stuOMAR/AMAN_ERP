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
from utils.permissions import require_permission, require_sensitive_permission, validate_branch_access, check_permission, require_module
from utils.permissions import has_pii_access, mask_pii, mask_pii_list, EMPLOYEE_PII_FIELDS, PAYROLL_PII_FIELDS
from utils.accounting import get_mapped_account_id, get_base_currency
from utils.fiscal_lock import check_fiscal_period_open
from utils.audit import log_activity
from schemas.hr import LoanCreate, LoanResponse, EmployeeCreate, EmployeeUpdate, DepartmentCreate, DepartmentResponse, PositionCreate, PositionResponse, PayrollPeriodCreate, PayrollEntryResponse, PayrollPeriodResponse, AttendanceResponse, LeaveRequestCreate, LeaveRequestResponse, EndOfServiceRequest
from services.gl_service import create_journal_entry as gl_create_journal_entry

logger = logging.getLogger(__name__)
_D2 = Decimal('0.01')

def _dec(v: Any) -> Decimal:
    return Decimal(str(v or 0))

router = APIRouter()

from .core import _D2, _dec

@router.get("/employees", dependencies=[Depends(require_permission("hr.view"))], response_model=List[Dict[str, Any]])
def get_employees(
    branch_id: Optional[int] = None, 
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company)
):
    """Get Employees."""
    with transactional(company_id) as conn:
        query = """
            SELECT 
                e.id, 
                e.employee_code,
                e.first_name, 
                e.last_name, 
                e.email,
                e.phone,
                e.status,
                p.position_name as position,
                d.department_name as department,
                e.user_id,
                e.account_id,
                e.branch_id,
                e.salary,
                e.housing_allowance,
                e.transport_allowance,
                e.other_allowances,
                e.hourly_cost,
                e.currency,
                e.nationality,
                u.role,
                array_agg(ub.branch_id) filter (where ub.branch_id is not null) as allowed_branches
            FROM employees e
            LEFT JOIN employee_positions p ON e.position_id = p.id
            LEFT JOIN departments d ON e.department_id = d.id
            LEFT JOIN company_users u ON e.user_id = u.id
            LEFT JOIN user_branches ub ON e.user_id = ub.user_id
            WHERE 1=1
        """
        params = {}
        role = (getattr(current_user, "role", None) or "").strip().lower()
        user_permissions = getattr(current_user, "permissions", []) or []
        is_privileged_user = (
            role in {"admin", "system_admin", "superuser", "manager", "gm"}
            or check_permission(user_permissions, "admin.branches")
            or check_permission(user_permissions, "branches.manage")
        )

        raw_allowed = getattr(current_user, "allowed_branches", None) or []
        normalized_allowed_branches = set()
        for b in raw_allowed:
            try:
                normalized_allowed_branches.add(int(b))
            except Exception:
                continue
        
        # Access Control Logic
        if not is_privileged_user:
            # For regular users, restrict to allowed branches
            if not normalized_allowed_branches:
                # If no branches assigned, they see nothing (or maybe just themselves? strict for now)
                return []
            
            if branch_id is not None:
                # If requesting specific branch, verify access
                if int(branch_id) not in normalized_allowed_branches:
                    raise HTTPException(status_code=403, detail="Unauthorized access to this branch")
                query += " AND (e.branch_id = :bid OR ub.branch_id = :bid)"
                params["bid"] = branch_id
            else:
                # If no specific branch, show employees in ALL allowed branches
                # safe string formatting for int list
                branches_str = ",".join(map(str, sorted(normalized_allowed_branches)))
                query += f" AND (e.branch_id IN ({branches_str}) OR ub.branch_id IN ({branches_str}))"
        else:
            # Admins/Managers can see all or filter by any branch
            if branch_id is not None:
                query += " AND (e.branch_id = :bid OR ub.branch_id = :bid)"
                params["bid"] = branch_id

        query += """
            GROUP BY e.id, e.employee_code, e.first_name, e.last_name, e.email, e.phone, e.status, e.user_id, e.account_id, e.created_at, p.position_name, d.department_name, e.branch_id, e.salary, e.housing_allowance, e.transport_allowance, e.other_allowances, e.hourly_cost, e.currency, e.nationality, u.role
            ORDER BY e.created_at DESC
        """
        
        result = conn.execute(text(query), params).fetchall()
        
        employees = []
        for row in result:
            employees.append({
                "id": row.id,
                "employee_code": row.employee_code,
                "first_name": row.first_name,
                "last_name": row.last_name,
                "email": row.email,
                "phone": row.phone,
                "status": row.status,
                "position": row.position or "غير محدد",
                "department": row.department or "غير محدد",
                "user_id": row.user_id,
                "account_id": row.account_id,
                "branch_id": row.branch_id,
                "salary": row.salary or 0,
                "housing_allowance": row.housing_allowance or 0,
                "transport_allowance": row.transport_allowance or 0,
                "other_allowances": row.other_allowances or 0,
                "hourly_cost": row.hourly_cost or 0,
                "currency": row.currency,
                "nationality": row.nationality,
                "allowed_branches": row.allowed_branches or [],
                "role": row.role or 'user'
            })
            
        # T2.4: mask financial PII unless caller has hr.pii
        if not has_pii_access(current_user):
            employees = mask_pii_list(employees, EMPLOYEE_PII_FIELDS)
        return employees

@router.post("/employees", dependencies=[Depends(require_sensitive_permission("hr.manage", critical=True))], response_model=Dict[str, Any])
def create_employee(request: Request, employee: EmployeeCreate, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Create Employee."""
    conn = get_db_connection(company_id)
    trans = conn.begin()
    try:
        # 1. Handle Department & Position (Simple Implementation: Get first or create dummy)
        # For simplicity in this iteration, we might check if they exist or just insert
        dept_id = None
        if employee.department_name:
            # Try find
            res = conn.execute(text("SELECT id FROM departments WHERE department_name = :n"), {"n": employee.department_name}).fetchone()
            if res:
                dept_id = res[0]
            else:
                # Create
                res = conn.execute(text("INSERT INTO departments (department_name) VALUES (:n) RETURNING id"), {"n": employee.department_name}).fetchone()
                dept_id = res[0]

        pos_id = None
        if employee.position_title:
             res = conn.execute(text("SELECT id FROM employee_positions WHERE position_name = :n"), {"n": employee.position_title}).fetchone()
             if res:
                 pos_id = res[0]
             else:
                 res = conn.execute(text("INSERT INTO employee_positions (position_name, department_id) VALUES (:n, :d) RETURNING id"), {"n": employee.position_title, "d": dept_id}).fetchone()
                 pos_id = res[0]


        # 2. Create User (Optional)
        new_user_id = None
        if employee.create_user and employee.username and employee.password:
            # Check if username exists
            exists = conn.execute(text("SELECT 1 FROM company_users WHERE username = :u"), {"u": employee.username}).fetchone()
            if exists:
                raise HTTPException(status_code=400, detail="Username already exists")
            
            hashed = hash_password(employee.password)
            role_key = (employee.role or 'employee').strip().lower()

            # SEC-C2: Whitelist role against DEFAULT_ROLES. Block privileged
            # roles (admin / system_admin / superuser) — those can only be
            # granted from /api/roles (admin.roles) with rank check.
            if role_key not in DEFAULT_ROLES:
                raise HTTPException(
                    status_code=400,
                    detail=f"الدور '{role_key}' غير معروف — استخدم دوراً معرَّفاً في DEFAULT_ROLES",
                )
            privileged = {"admin", "system_admin", "superuser"}
            if role_key in privileged:
                raise HTTPException(
                    status_code=403,
                    detail=(
                        "لا يمكن إسناد دور إداري من واجهة الموارد البشرية — "
                        "استخدم /api/roles المحمي بصلاحية admin.roles."
                    ),
                )

            # Get default permissions for the role
            import json
            perms_def = DEFAULT_ROLES.get(role_key, {})
            perms = perms_def.get("permissions", []) if isinstance(perms_def, dict) else perms_def
            perms_json = json.dumps(perms)
            
            res = conn.execute(text("""
                INSERT INTO company_users (username, password, email, full_name, role, permissions)
                VALUES (:u, :p, :e, :f, :r, :perms) RETURNING id
            """), {
                "u": employee.username,
                "p": hashed,
                "e": employee.email if employee.email else None,
                "f": f"{employee.first_name} {employee.last_name}",
                "r": role_key,
                "perms": perms_json
            }).fetchone()
            new_user_id = res[0]

            # DB-015: Update central user index for fast login
            try:
                from database import get_system_db
                sys_db = get_system_db()
                sys_db.execute(text("""
                    INSERT INTO system_user_index (username, company_id, is_active)
                    VALUES (:username, :company_id, true)
                    ON CONFLICT (username, company_id) DO UPDATE SET is_active = true, updated_at = CURRENT_TIMESTAMP
                """), {"username": employee.username, "company_id": company_id})
                sys_db.commit()
                sys_db.close()
            except Exception:
                pass  # Non-critical

        # 3. Create Ledger Account (Optional)
        new_account_id = None
        if employee.create_ledger:
            # Find "Salaries Payable" or "Employee Payables" parent.
            # For now, we put it under "Current Liabilities" (21) -> Accounts Payable (2101) or create new parent
            # Let's put under "Accounts Payable" (2101) for simplicity or look for a better parent.
            # Better: Create specific parent "Employee Payables" if not exists.
            
            # 1. Find or create parent "Employee Payables" under 21 (Current Liabilities)
            parent_acc = conn.execute(text("SELECT id FROM accounts WHERE name = 'ذمم الموظفين'")).fetchone()
            if not parent_acc:
                # Find ID of 21
                liab_root = conn.execute(text("SELECT id FROM accounts WHERE account_number = '21'")).fetchone()
                if liab_root:
                    parent_acc_res = conn.execute(text("""
                        INSERT INTO accounts (account_number, name, name_en, account_type, parent_id)
                        VALUES ('2105', 'ذمم الموظفين', 'Employees Payable', 'liability', :pid) RETURNING id
                    """), {"pid": liab_root[0]}).fetchone()
                    parent_acc_id = parent_acc_res[0]
                else:
                    parent_acc_id = None # Fallback?
            else:
                parent_acc_id = parent_acc[0]

            if parent_acc_id:
                # Generate unique number
                count = conn.execute(text("SELECT COUNT(*) FROM accounts WHERE parent_id = :pid"), {"pid": parent_acc_id}).scalar()
                acc_num = f"2105{str(count+1).zfill(3)}"
                
                acc_name = f"{employee.first_name} {employee.last_name}"
                res = conn.execute(text("""
                    INSERT INTO accounts (account_number, name, name_en, account_type, parent_id)
                    VALUES (:num, :name, :name, 'liability', :pid) RETURNING id
                """), {
                    "num": acc_num,
                    "name": acc_name,
                    "pid": parent_acc_id
                }).fetchone()
                new_account_id = res[0]

        # 4. Auto-detect currency from branch if not provided
        emp_currency = employee.currency
        if not emp_currency and employee.branch_id:
            branch_row = conn.execute(text("SELECT default_currency FROM branches WHERE id = :bid"), {"bid": employee.branch_id}).fetchone()
            if branch_row and branch_row.default_currency:
                emp_currency = branch_row.default_currency
        if not emp_currency:
            emp_currency = get_base_currency(conn)

        # 5. Create Employee Record
        conn.execute(text("""
            INSERT INTO employees (
                employee_code, first_name, last_name, first_name_en, last_name_en,
                email, phone, department_id, position_id, 
                salary, housing_allowance, transport_allowance, other_allowances, hourly_cost,
                hire_date, user_id, account_id, branch_id, currency, nationality
            ) VALUES (
                :code, :fn, :ln, :fne, :lne,
                :email, :phone, :did, :pid,
                :salary, :housing, :transport, :other, :hc,
                :hire, :uid, :aid, :bid, :currency, :nationality
            )
        """), {
            "code": employee.employee_code if employee.employee_code else None,
            "fn": employee.first_name,
            "ln": employee.last_name,
            "fne": employee.first_name_en,
            "lne": employee.last_name_en,
            "email": employee.email,
            "phone": employee.phone,
            "did": dept_id,
            "pid": pos_id,
            "salary": employee.salary,
            "housing": employee.housing_allowance,
            "transport": employee.transport_allowance,
            "other": employee.other_allowances,
            "hc": employee.hourly_cost,
            "hire": employee.hire_date or date.today(),
            "uid": new_user_id,
            "aid": new_account_id,
            "bid": employee.branch_id,
            "currency": emp_currency,
            "nationality": employee.nationality
        })
        
        # 5. Assign Branches
        if new_user_id and employee.allowed_branch_ids:
             for bid in employee.allowed_branch_ids:
                 conn.execute(text("INSERT INTO user_branches (user_id, branch_id) VALUES (:uid, :bid)"), {"uid": new_user_id, "bid": bid})
        
        trans.commit()

        # AUDIT LOG
        log_activity(
            conn,
            user_id=current_user.get("id") if isinstance(current_user, dict) else current_user.id,
            username=current_user.get("username") if isinstance(current_user, dict) else current_user.username,
            action="hr.employee.create",
            resource_type="employee",
            resource_id=f"{employee.first_name} {employee.last_name}",
            details={"position": employee.position_title, "branch_id": employee.branch_id},
            request=request,
            branch_id=employee.branch_id
        )

        # Notify HR admins about new employee
        try:
            conn.execute(text("""
                INSERT INTO notifications (user_id, type, title, message, link, is_read, created_at)
                SELECT DISTINCT u.id, 'employee', :title, :message, :link, FALSE, NOW()
                FROM company_users u
                WHERE u.is_active = TRUE AND u.role IN ('admin', 'superuser')
                AND u.id != :current_uid
            """), {
                "title": "👤 موظف جديد",
                "message": f"تم إضافة الموظف {employee.first_name} {employee.last_name} — {employee.position_title or ''}",
                "link": "/hr/employees",
                "current_uid": current_user.get('id') if isinstance(current_user, dict) else current_user.id
            })
            conn.commit()
        except Exception:
            pass

        return {"message": "Success"}
        
    except Exception as e:
        trans.rollback()
        logger.exception("Internal error")
        raise HTTPException(status_code=400, detail=f"Invalid data: {str(e)}")
    finally:
        conn.close()

@router.put("/employees/{employee_id}", dependencies=[Depends(require_sensitive_permission("hr.manage", critical=True))], response_model=Dict[str, Any])
def update_employee(
    request: Request,
    employee_id: int, 
    employee: EmployeeUpdate, 
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company)
):
    """Update Employee."""
    conn = get_db_connection(company_id)
    trans = conn.begin()
    try:
        # Check existence
        existing = conn.execute(text("SELECT user_id FROM employees WHERE id = :id"), {"id": employee_id}).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Employee not found")
        
        user_id = existing[0]

        # Update basic info
        update_fields = []
        params = {"id": employee_id}
        
        if employee.employee_code is not None:
            update_fields.append("employee_code = :code")
            params["code"] = employee.employee_code if employee.employee_code else None
        if employee.first_name:
            update_fields.append("first_name = :fn")
            params["fn"] = employee.first_name
        if employee.last_name:
            update_fields.append("last_name = :ln")
            params["ln"] = employee.last_name
        if employee.email:
            update_fields.append("email = :email")
            params["email"] = employee.email
        if employee.phone:
            update_fields.append("phone = :phone")
            params["phone"] = employee.phone
        if employee.salary:
            update_fields.append("salary = :salary")
            params["salary"] = employee.salary
        if employee.branch_id:
            update_fields.append("branch_id = :bid")
            params["bid"] = employee.branch_id

        # Allowances
        if employee.housing_allowance is not None:
             update_fields.append("housing_allowance = :housing")
             params["housing"] = employee.housing_allowance
        if employee.transport_allowance is not None:
             update_fields.append("transport_allowance = :transport")
             params["transport"] = employee.transport_allowance
        if employee.other_allowances is not None:
             update_fields.append("other_allowances = :other")
             params["other"] = employee.other_allowances
        if employee.hourly_cost is not None:
             update_fields.append("hourly_cost = :hc")
             params["hc"] = employee.hourly_cost

        if employee.currency is not None:
             update_fields.append("currency = :currency")
             params["currency"] = employee.currency
        if employee.nationality is not None:
             update_fields.append("nationality = :nationality")
             params["nationality"] = employee.nationality

        # Update Dept/Pos if changed
        if employee.department_name:
             # Find or create
             res = conn.execute(text("SELECT id FROM departments WHERE department_name = :n"), {"n": employee.department_name}).fetchone()
             if res:
                 dept_id = res[0]
             else:
                 res = conn.execute(text("INSERT INTO departments (department_name) VALUES (:n) RETURNING id"), {"n": employee.department_name}).fetchone()
                 dept_id = res[0]
             update_fields.append("department_id = :did")
             params["did"] = dept_id

        if employee.position_title:
             # We need dept_id (either updated or existing)
             # Simplification: if position exists, use it. If not, create (needs dept).
             # Fetch current dept if not updated
             if "did" not in params:
                 curr_dept = conn.execute(text("SELECT department_id FROM employees WHERE id = :id"), {"id": employee_id}).scalar()
                 dept = curr_dept
             else:
                 dept = params["did"]
                 
             res = conn.execute(text("SELECT id FROM employee_positions WHERE position_name = :n"), {"n": employee.position_title}).fetchone()
             if res:
                 pos_id = res[0]
             else:
                 res = conn.execute(text("INSERT INTO employee_positions (position_name, department_id) VALUES (:n, :d) RETURNING id"), {"n": employee.position_title, "d": dept}).fetchone()
                 pos_id = res[0]
             update_fields.append("position_id = :pid")
             params["pid"] = pos_id

        if update_fields:
            stmt = f"UPDATE employees SET {', '.join(update_fields)} WHERE id = :id"
            conn.execute(text(stmt), params)

        # Update Branches if provided and user exists
        if user_id and employee.allowed_branch_ids is not None:
            # Clear existing
            conn.execute(text("DELETE FROM user_branches WHERE user_id = :uid"), {"uid": user_id})
            # Add new
            for bid in employee.allowed_branch_ids:
                 conn.execute(text("INSERT INTO user_branches (user_id, branch_id) VALUES (:uid, :bid)"), {"uid": user_id, "bid": bid})

        # SEC-C2: Role writes are forbidden from the HR endpoint.
        # Role management lives under /api/roles and is gated by the
        # `admin.roles` permission with a rank check. Any attempt to send
        # `role` via the HR employee update is rejected hard.
        if user_id and getattr(employee, "role", None):
            raise HTTPException(
                status_code=403,
                detail=(
                    "لا يمكن تعديل الدور من خلال واجهة الموارد البشرية — "
                    "استخدم /api/roles المحمي بصلاحية admin.roles."
                ),
            )

        trans.commit()

        # AUDIT LOG
        log_activity(
            conn,
            user_id=current_user.get("id") if isinstance(current_user, dict) else current_user.id,
            username=current_user.get("username") if isinstance(current_user, dict) else current_user.username,
            action="hr.employee.update",
            resource_type="employee",
            resource_id=str(employee_id),
            details={"fields_updated": update_fields},
            request=request,
            branch_id=employee.branch_id
        )

        return {"message": "Updated successfully"}
    except Exception:
        trans.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(400, "invalid_data"))
    finally:
        conn.close()

# --- Payroll Endpoints ---

@router.post("/end-of-service/calculate", dependencies=[Depends(require_sensitive_permission("hr.manage", critical=True))], response_model=Dict[str, Any])
def calculate_end_of_service(
    data: EndOfServiceRequest,
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company)
):
    """حساب مكافأة نهاية الخدمة وفقاً لنظام العمل السعودي"""
    with transactional(company_id) as conn:
        try:
            # Get employee details
            emp = conn.execute(text("""
                SELECT id, CONCAT(first_name, ' ', last_name) as employee_name, 
                       hire_date, salary as basic_salary, 
                       COALESCE(housing_allowance, 0) as housing_allowance,
                       COALESCE(transport_allowance, 0) as transport_allowance
                FROM employees WHERE id = :eid
            """), {"eid": data.employee_id}).fetchone()
            
            if not emp:
                raise HTTPException(**http_error(404, "employee_not_found"))
            
            termination_date = data.termination_date or date.today()
            join_date = emp.hire_date
            
            if not join_date:
                raise HTTPException(status_code=400, detail="تاريخ التعيين غير محدد للموظف")
            
            # Calculate service years
            from dateutil.relativedelta import relativedelta
            delta = relativedelta(termination_date, join_date)
            total_years = _dec(delta.years) + (_dec(delta.months) / Decimal('12')) + (_dec(delta.days) / Decimal('365.25'))
            
            if total_years < Decimal('0'):
                raise HTTPException(status_code=400, detail="تاريخ الإنهاء قبل تاريخ التعيين")
            
            # Total salary (basic + housing + transport) used as base
            base_salary = _dec(emp.basic_salary)
            total_salary = base_salary + _dec(emp.housing_allowance) + _dec(emp.transport_allowance)
            
            # Calculate unpaid leave deduction days (if any) — used by the helper
            unpaid_days = conn.execute(text("""
                SELECT COALESCE(SUM(
                    CASE WHEN leave_type = 'unpaid' AND status = 'approved'
                    THEN (end_date - start_date + 1) ELSE 0 END
                ), 0) FROM leave_requests WHERE employee_id = :eid
            """), {"eid": data.employee_id}).scalar() or 0
    
            # Calculate EOS using shared helper (Saudi Labor Law Art. 84/85)
            from utils.hr_helpers import calculate_eos_gratuity
            eos = calculate_eos_gratuity(
                total_salary, total_years, data.termination_reason,
                unpaid_leave_days=int(unpaid_days),
            )
    
            gratuity = eos["full_gratuity"]
            resignation_factor = eos["resignation_factor"]
            unpaid_deduction = eos["unpaid_leave_deduction"]
            final_gratuity = eos["final_gratuity"]
    
            return {
                "employee_id": data.employee_id,
                "employee_name": emp.employee_name,
                "join_date": str(join_date),
                "termination_date": str(termination_date),
                "termination_reason": data.termination_reason,
                "service_years": str(total_years.quantize(_D2, ROUND_HALF_UP)),
                "service_years_display": f"{delta.years} سنة و {delta.months} شهر و {delta.days} يوم",
                "base_salary": str(base_salary),
                "total_salary_used": str(total_salary),
                "full_gratuity": str(gratuity),
                "resignation_factor": str(resignation_factor),
                "unpaid_leave_days": int(unpaid_days),
                "unpaid_leave_deduction": str(unpaid_deduction),
                "final_gratuity": str(final_gratuity),
                "notes": "الحساب وفقاً لنظام العمل السعودي - المادة 84 و 85 (مع خصم الإجازات بدون راتب)"
            }
        except HTTPException:
            raise
        except Exception:
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# =====================================================
# 8.15 HR IMPROVEMENTS
# =====================================================

# ---------- HR-005: Payslip View / Print ----------
# NOTE: Payslip endpoints consolidated below in "Phase 8.15" section


# ============================================================
# Phase 8.15 - Payslips, Recruitment, Leave Balance
# ============================================================
import calendar as cal_module

# --- Payslips ---

@router.get("/employees/{emp_id}/payslips", dependencies=[Depends(require_permission("hr.view"))], response_model=Dict[str, Any])
def get_employee_payslips_route(
    emp_id: int,
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company),
):
    """Get Employee Payslips Route."""
    with transactional(company_id) as conn:
        result = conn.execute(text("""
            SELECT pe.id, pe.employee_id,
                   e.first_name || ' ' || e.last_name as employee_name,
                   pe.basic_salary,
                   COALESCE(pe.housing_allowance,0)+COALESCE(pe.transport_allowance,0)+COALESCE(pe.other_allowances,0) as total_allowances,
                   COALESCE(pe.deductions,0) as total_deductions,
                   pe.net_salary as net_pay,
                   pp.status,
                   EXTRACT(MONTH FROM pp.start_date)::int as month,
                   EXTRACT(YEAR FROM pp.start_date)::int as year
            FROM payroll_entries pe
            JOIN employees e ON pe.employee_id = e.id
            JOIN payroll_periods pp ON pe.period_id = pp.id
            WHERE pe.employee_id = :eid
            ORDER BY pp.start_date DESC
        """), {"eid": emp_id}).fetchall()
        rows = [dict(row._mapping) for row in result]
        # T2.4: Allow employee to see their own payslips even without hr.pii;
        # otherwise require hr.pii to expose financial figures.
        if not has_pii_access(current_user):
            uid = current_user.get("id") if isinstance(current_user, dict) else current_user.id
            owner = conn.execute(
                text("SELECT user_id FROM employees WHERE id = :eid"),
                {"eid": emp_id},
            ).scalar()
            if owner != uid:
                rows = mask_pii_list(rows, PAYROLL_PII_FIELDS)
        return rows


