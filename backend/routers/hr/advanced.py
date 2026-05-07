"""
Advanced HR Router - Phase 4
الموارد البشرية المتقدمة: هياكل الرواتب، مكونات الراتب، العمل الإضافي، GOSI، المستندات، تقييم الأداء، التدريب، المخالفات، العهد
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from database import get_db_connection
from routers.auth import get_current_user, UserResponse, get_current_user_company
from utils.tx import transactional
from utils.permissions import branch_scope_filter, require_permission, require_module
from utils.exports import generate_excel, generate_pdf, create_export_response
from utils.audit import log_activity
import logging
logger = logging.getLogger(__name__)

from schemas.hr_advanced import (
    SalaryStructureCreate, SalaryStructureUpdate, SalaryStructureResponse,
    SalaryComponentCreate, SalaryComponentUpdate, SalaryComponentResponse,
    EmployeeSalaryComponentCreate, OvertimeRequestCreate, OvertimeRequestUpdate, OvertimeRequestResponse,
    GOSISettingsCreate, GOSICalculationResponse,
    EmployeeDocumentCreate, EmployeeDocumentUpdate, EmployeeDocumentResponse,
    PerformanceReviewCreate, PerformanceReviewUpdate, PerformanceReviewResponse,
    TrainingProgramCreate, TrainingProgramUpdate, TrainingProgramResponse,
    TrainingParticipantCreate, TrainingParticipantUpdate, TrainingParticipantResponse,
    ViolationCreate, ViolationUpdate, ViolationResponse,
    CustodyCreate, CustodyUpdate, CustodyResponse,
)

_D2 = Decimal('0.01')

def _dec(v):
    return Decimal(str(v or 0))

router = APIRouter(prefix="/hr-advanced", tags=["HR Advanced - الموارد البشرية المتقدمة"], dependencies=[Depends(require_module("hr"))])


# =============================================
# هياكل الرواتب - Salary Structures
# =============================================

@router.get("/salary-structures", response_model=List[SalaryStructureResponse], dependencies=[Depends(require_permission("hr.view"))])
def list_salary_structures(company_id: str = Depends(get_current_user_company)):
    """List Salary Structures."""
    with transactional(company_id) as conn:
        rows = conn.execute(text("SELECT * FROM salary_structures ORDER BY created_at DESC")).fetchall()
        return [dict(r._mapping) for r in rows]


@router.post("/salary-structures", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def create_salary_structure(data: SalaryStructureCreate, request: Request, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Create Salary Structure."""
    with transactional(company_id) as conn:
        result = conn.execute(text("""
            INSERT INTO salary_structures (name, name_en, description, base_type)
            VALUES (:name, :name_en, :desc, :base_type) RETURNING id
        """), {"name": data.name, "name_en": data.name_en, "desc": data.description, "base_type": data.base_type})
        sid = result.scalar()
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.salary_structure.create", resource_type="salary_structure",
            resource_id=str(sid), details={"name": data.name}, request=request
        )
        return {"id": sid, "message": "تم إنشاء هيكل الراتب بنجاح"}


@router.put("/salary-structures/{structure_id}", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def update_salary_structure(structure_id: int, data: SalaryStructureUpdate, request: Request, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Update Salary Structure."""
    with transactional(company_id) as conn:
        fields, params = [], {"id": structure_id}
        for field in ["name", "name_en", "description", "base_type", "is_active"]:
            val = getattr(data, field, None)
            if val is not None:
                fields.append(f"{field} = :{field}")
                params[field] = val
        if not fields:
            raise HTTPException(**http_error(400, "no_changes"))
        fields.append("updated_at = CURRENT_TIMESTAMP")
        conn.execute(text(f"UPDATE salary_structures SET {', '.join(fields)} WHERE id = :id"), params)
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.salary_structure.update", resource_type="salary_structure",
            resource_id=str(structure_id), details={"fields": list(params.keys())}, request=request
        )
        return {"message": "تم التحديث بنجاح"}


@router.delete("/salary-structures/{structure_id}", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def delete_salary_structure(structure_id: int, request: Request, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Delete Salary Structure."""
    with transactional(company_id) as conn:
        conn.execute(text("DELETE FROM salary_structures WHERE id = :id"), {"id": structure_id})
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.salary_structure.delete", resource_type="salary_structure",
            resource_id=str(structure_id), details={}, request=request
        )
        return {"message": "تم الحذف بنجاح"}


# =============================================
# مكونات الراتب - Salary Components
# =============================================

@router.get("/salary-components", response_model=List[SalaryComponentResponse], dependencies=[Depends(require_permission("hr.view"))])
def list_salary_components(structure_id: Optional[int] = None, company_id: str = Depends(get_current_user_company)):
    """List Salary Components."""
    with transactional(company_id) as conn:
        query = "SELECT * FROM salary_components WHERE 1=1"
        params = {}
        if structure_id:
            query += " AND structure_id = :sid"
            params["sid"] = structure_id
        query += " ORDER BY sort_order, created_at"
        rows = conn.execute(text(query), params).fetchall()
        return [dict(r._mapping) for r in rows]


@router.post("/salary-components", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def create_salary_component(data: SalaryComponentCreate, request: Request, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Create Salary Component."""
    with transactional(company_id) as conn:
        result = conn.execute(text("""
            INSERT INTO salary_components (name, name_en, component_type, calculation_type, percentage_of, percentage_value, formula, is_taxable, is_gosi_applicable, sort_order, structure_id)
            VALUES (:name, :name_en, :type, :calc, :pof, :pval, :formula, :tax, :gosi, :sort, :sid)
            RETURNING id
        """), {
            "name": data.name, "name_en": data.name_en, "type": data.component_type,
            "calc": data.calculation_type, "pof": data.percentage_of, "pval": data.percentage_value,
            "formula": data.formula, "tax": data.is_taxable, "gosi": data.is_gosi_applicable,
            "sort": data.sort_order, "sid": data.structure_id
        })
        cid = result.scalar()
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.salary_component.create", resource_type="salary_component",
            resource_id=str(cid), details={"name": data.name}, request=request
        )
        return {"id": cid, "message": "تم إنشاء مكون الراتب بنجاح"}


@router.put("/salary-components/{component_id}", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def update_salary_component(component_id: int, data: SalaryComponentUpdate, request: Request, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Update Salary Component."""
    with transactional(company_id) as conn:
        fields, params = [], {"id": component_id}
        for field in ["name", "name_en", "component_type", "calculation_type", "percentage_of", "percentage_value", "formula", "is_taxable", "is_gosi_applicable", "is_active", "sort_order", "structure_id"]:
            val = getattr(data, field, None)
            if val is not None:
                fields.append(f"{field} = :{field}")
                params[field] = val
        if not fields:
            raise HTTPException(**http_error(400, "no_changes"))
        conn.execute(text(f"UPDATE salary_components SET {', '.join(fields)} WHERE id = :id"), params)
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.salary_component.update", resource_type="salary_component",
            resource_id=str(component_id), details={"fields": list(params.keys())}, request=request
        )
        return {"message": "تم التحديث بنجاح"}


# =============================================
# ربط مكونات الراتب بالموظفين
# =============================================

@router.get("/employee-salary-components/{employee_id}", dependencies=[Depends(require_permission("hr.view"))], response_model=List[Dict[str, Any]])
def get_employee_salary_components(employee_id: int, company_id: str = Depends(get_current_user_company)):
    """Get Employee Salary Components."""
    with transactional(company_id) as conn:
        rows = conn.execute(text("""
            SELECT esc.*, sc.name as component_name, sc.component_type
            FROM employee_salary_components esc
            JOIN salary_components sc ON esc.component_id = sc.id
            WHERE esc.employee_id = :eid AND esc.is_active = TRUE
            ORDER BY sc.sort_order
        """), {"eid": employee_id}).fetchall()
        return [dict(r._mapping) for r in rows]


@router.post("/employee-salary-components", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def assign_salary_component(data: EmployeeSalaryComponentCreate, request: Request, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Assign Salary Component."""
    with transactional(company_id) as conn:
        conn.execute(text("""
            INSERT INTO employee_salary_components (employee_id, component_id, amount, is_active, effective_date)
            VALUES (:eid, :cid, :amt, :active, :date)
            ON CONFLICT (employee_id, component_id) DO UPDATE SET amount = :amt, is_active = :active, effective_date = :date
        """), {"eid": data.employee_id, "cid": data.component_id, "amt": data.amount, "active": data.is_active, "date": data.effective_date})
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.employee_salary_component.assign", resource_type="employee_salary_component",
            resource_id=str(data.employee_id), details={"component_id": data.component_id, "amount": str(data.amount) if data.amount else "0"}, request=request
        )
        return {"message": "تم تعيين مكون الراتب بنجاح"}


# =============================================
# العمل الإضافي - Overtime
# =============================================

# T8.4: expose configurable overtime multipliers from `overtime_rates_config`
# (seeded by tenant_runner) so the frontend OvertimeRequests form no longer
# hard-codes 1.5/2.0 in its <select> dropdown.
@router.get("/overtime/rates", response_model=Dict[str, Any], dependencies=[Depends(require_permission("hr.view"))])
def get_overtime_rates(
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company),
):
    """Return active overtime rate multipliers configured for this tenant.

    Falls back to the default seed values (1.5x weekday, 2.0x weekend, 1.25x
    night) if the `overtime_rates_config` table doesn't exist yet (older
    tenants pre-2026 baseline).
    """
    defaults = [
        {"rate_key": "weekday_ot", "description": "Weekday overtime multiplier", "multiplier": 1.5},
        {"rate_key": "weekend_ot", "description": "Weekend / public holiday overtime", "multiplier": 2.0},
        {"rate_key": "night_shift", "description": "Night-shift premium", "multiplier": 1.25},
    ]
    with transactional(company_id) as conn:
        try:
            rows = conn.execute(
                text(
                    "SELECT rate_key, description, multiplier "
                    "FROM overtime_rates_config "
                    "WHERE coalesce(is_active, true) = true "
                    "ORDER BY id"
                )
            ).fetchall()
            items = [
                {"rate_key": r[0], "description": r[1], "multiplier": float(r[2])}
                for r in rows
            ]
            return {"items": items or defaults, "source": "overtime_rates_config" if items else "defaults"}
        except Exception as e:
            logger.warning(f"overtime/rates fallback to defaults: {e}")
            return {"items": defaults, "source": "defaults"}


@router.get("/overtime", response_model=List[OvertimeRequestResponse], dependencies=[Depends(require_permission("hr.view"))])
def list_overtime_requests(employee_id: Optional[int] = None, status: Optional[str] = None, branch_id: Optional[int] = None, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """List Overtime Requests."""
    with transactional(company_id) as conn:
        query = """
            SELECT o.*, e.first_name || ' ' || e.last_name as employee_name
            FROM overtime_requests o
            JOIN employees e ON o.employee_id = e.id
            WHERE 1=1
        """
        params = {}
        if employee_id:
            query += " AND o.employee_id = :eid"
            params["eid"] = employee_id
        if status:
            query += " AND o.status = :status"
            params["status"] = status
        query += " " + branch_scope_filter(current_user, branch_id, "e.branch_id", params, branch_param="bid")
        query += " ORDER BY o.created_at DESC"
        rows = conn.execute(text(query), params).fetchall()
        return [dict(r._mapping) for r in rows]


@router.post("/overtime", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def create_overtime_request(data: OvertimeRequestCreate, request: Request, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Create Overtime Request."""
    with transactional(company_id) as conn:
        # Calculate amount: (salary / 30 / 8) * hours * multiplier
        emp = conn.execute(text("SELECT salary FROM employees WHERE id = :eid"), {"eid": data.employee_id}).fetchone()
        if not emp:
            raise HTTPException(**http_error(404, "employee_not_found"))

        hourly_rate = (_dec(emp.salary) / Decimal('30') / Decimal('8'))
        multiplier = _dec(data.multiplier) if data.multiplier else (Decimal('1.5') if data.overtime_type == "normal" else Decimal('2'))
        amount = str((hourly_rate * _dec(data.hours) * multiplier).quantize(_D2, ROUND_HALF_UP))

        result = conn.execute(text("""
            INSERT INTO overtime_requests (employee_id, request_date, overtime_date, hours, overtime_type, multiplier, calculated_amount, reason, branch_id)
            VALUES (:eid, CURRENT_DATE, :odate, :hours, :otype, :mult, :amt, :reason, :bid)
            RETURNING id
        """), {
            "eid": data.employee_id, "odate": data.overtime_date, "hours": data.hours,
            "otype": data.overtime_type, "mult": str(multiplier), "amt": amount,
            "reason": data.reason, "bid": data.branch_id
        })
        ot_id = result.scalar()
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.overtime.create", resource_type="overtime_request",
            resource_id=str(ot_id), details={"employee_id": data.employee_id, "hours": data.hours}, request=request
        )
        return {"id": ot_id, "calculated_amount": amount, "message": "تم إنشاء طلب العمل الإضافي"}


@router.put("/overtime/{overtime_id}/approve", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def approve_overtime(overtime_id: int, data: OvertimeRequestUpdate, request: Request, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Approve Overtime."""
    with transactional(company_id) as conn:
        user_id = current_user.id if hasattr(current_user, 'id') else current_user.get("id")
        conn.execute(text("""
            UPDATE overtime_requests SET status = :status, approved_by = :uid, approved_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = :id
        """), {"status": data.status, "uid": user_id, "id": overtime_id})
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.overtime.approve", resource_type="overtime_request",
            resource_id=str(overtime_id), details={"status": data.status}, request=request
        )
        return {"message": "تم تحديث حالة الطلب"}


# =============================================
# GOSI - التأمينات الاجتماعية
# =============================================

@router.get("/gosi-settings", dependencies=[Depends(require_permission("hr.view"))], response_model=Dict[str, Any])
def get_gosi_settings(company_id: str = Depends(get_current_user_company)):
    """Get GOSI Settings."""
    with transactional(company_id) as conn:
        row = conn.execute(text("SELECT * FROM gosi_settings WHERE is_active = TRUE ORDER BY id DESC LIMIT 1")).fetchone()
        if not row:
            return {"employee_share_percentage": 9.75, "employer_share_percentage": 11.75, "occupational_hazard_percentage": 2.0, "max_contributable_salary": 45000, "is_active": True}
        return dict(row._mapping)


@router.post("/gosi-settings", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def save_gosi_settings(data: GOSISettingsCreate, request: Request, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Save GOSI Settings."""
    with transactional(company_id) as conn:
        # Deactivate old
        conn.execute(text("UPDATE gosi_settings SET is_active = FALSE"))
        result = conn.execute(text("""
            INSERT INTO gosi_settings (employee_share_percentage, employer_share_percentage, occupational_hazard_percentage, max_contributable_salary, effective_date)
            VALUES (:emp_pct, :empr_pct, :occ_pct, :max_sal, :eff_date) RETURNING id
        """), {
            "emp_pct": data.employee_share_percentage, "empr_pct": data.employer_share_percentage,
            "occ_pct": data.occupational_hazard_percentage, "max_sal": data.max_contributable_salary,
            "eff_date": data.effective_date or date.today()
        })
        gosi_id = result.scalar()
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.gosi_settings.save", resource_type="gosi_settings",
            resource_id=str(gosi_id), details={"employee_share": data.employee_share_percentage, "employer_share": data.employer_share_percentage}, request=request
        )
        return {"id": gosi_id, "message": "تم حفظ إعدادات GOSI"}


@router.get("/gosi-calculation", response_model=List[GOSICalculationResponse], dependencies=[Depends(require_permission("hr.view"))])
def calculate_gosi(branch_id: Optional[int] = None, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Calculate GOSI."""
    with transactional(company_id) as conn:
        # Get active settings (Saudi rates default per GOSI 2024:
        #   Saudi: 9.75% employee + 11.75% employer (12.00% from Jul-2025 if configured)
        #   Non-Saudi: 0% employee + 2% employer occupational hazard only)
        settings = conn.execute(text("SELECT * FROM gosi_settings WHERE is_active = TRUE ORDER BY id DESC LIMIT 1")).fetchone()
        emp_pct = _dec(settings.employee_share_percentage) if settings else Decimal('9.75')
        empr_pct = _dec(settings.employer_share_percentage) if settings else Decimal('11.75')
        occ_pct = _dec(settings.occupational_hazard_percentage) if settings else Decimal('2.0')
        max_sal = _dec(settings.max_contributable_salary) if settings else Decimal('45000')

        gosi_query = """
            SELECT id, first_name || ' ' || last_name as name, salary, housing_allowance,
                   COALESCE(nationality, 'SA') AS nationality
            FROM employees WHERE status = 'active'
        """
        gosi_params = {}
        gosi_query += " " + branch_scope_filter(current_user, branch_id, "branch_id", gosi_params, branch_param="bid")
        employees = conn.execute(text(gosi_query), gosi_params).fetchall()

        results = []
        for emp in employees:
            basic = _dec(emp.salary)
            housing = _dec(emp.housing_allowance)
            contributable = min(basic + housing, max_sal)
            is_saudi = (str(emp.nationality or 'SA').upper() in ('SA', 'SAU', 'SAUDI', 'SAUDIA'))
            if is_saudi:
                emp_share = (contributable * emp_pct / Decimal('100')).quantize(_D2, ROUND_HALF_UP)
                empr_share = (contributable * empr_pct / Decimal('100')).quantize(_D2, ROUND_HALF_UP)
                occ_hazard = Decimal('0').quantize(_D2)  # included in employer share
            else:
                # Non-Saudi: occupational-hazard branch only
                emp_share = Decimal('0').quantize(_D2)
                empr_share = Decimal('0').quantize(_D2)
                occ_hazard = (contributable * occ_pct / Decimal('100')).quantize(_D2, ROUND_HALF_UP)
            results.append({
                "employee_id": emp.id, "employee_name": emp.name,
                "basic_salary": str(basic), "housing_allowance": str(housing),
                "contributable_salary": str(contributable),
                "nationality": emp.nationality, "is_saudi": is_saudi,
                "employee_share": str(emp_share), "employer_share": str(empr_share),
                "occupational_hazard": str(occ_hazard),
                "total_contribution": str((emp_share + empr_share + occ_hazard).quantize(_D2, ROUND_HALF_UP))
            })
        return results


@router.get("/gosi-export", dependencies=[Depends(require_permission("hr.view"))], response_model=Dict[str, Any])
def export_gosi(
    format: str = "excel",
    month: Optional[int] = None,
    year: Optional[int] = None,
    branch_id: Optional[int] = None,
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company)
):
    """
    تصدير ملف GOSI (التأمينات الاجتماعية) بتنسيق Excel أو PDF
    Export GOSI contribution file for submission to Saudi GOSI system
    """
    with transactional(company_id) as conn:
        # Get active settings
        settings = conn.execute(text("SELECT * FROM gosi_settings WHERE is_active = TRUE ORDER BY id DESC LIMIT 1")).fetchone()
        emp_pct = _dec(settings.employee_share_percentage) if settings else Decimal('9.75')
        empr_pct = _dec(settings.employer_share_percentage) if settings else Decimal('11.75')
        occ_pct = _dec(settings.occupational_hazard_percentage) if settings else Decimal('2.0')
        max_sal = _dec(settings.max_contributable_salary) if settings else Decimal('45000')

        # Get employees with additional GOSI-relevant fields
        gosi_exp_query = """
            SELECT e.id, e.employee_code as employee_number, e.first_name || ' ' || e.last_name as name,
                   e.salary, e.housing_allowance, e.social_security as national_id, e.nationality,
                   e.birth_date as date_of_birth, e.hire_date, d.department_name as department
            FROM employees e
            LEFT JOIN departments d ON d.id = e.department_id
            WHERE e.status = 'active'
        """
        gosi_exp_params = {}
        gosi_exp_query += " " + branch_scope_filter(current_user, branch_id, "e.branch_id", gosi_exp_params, branch_param="bid")
        gosi_exp_query += " ORDER BY d.department_name, e.first_name"
        employees = conn.execute(text(gosi_exp_query), gosi_exp_params).fetchall()

        target_month = month or date.today().month
        target_year = year or date.today().year

        export_data = []
        total_emp_share = Decimal('0')
        total_empr_share = Decimal('0')
        total_occ_hazard = Decimal('0')
        total_all = Decimal('0')

        for emp in employees:
            basic = _dec(emp.salary)
            housing = _dec(emp.housing_allowance)
            contributable = min(basic + housing, max_sal)
            is_saudi = (str(getattr(emp, 'nationality', '') or 'SA').upper()
                        in ('SA', 'SAU', 'SAUDI', 'SAUDIA'))
            if is_saudi:
                emp_share = (contributable * emp_pct / Decimal('100')).quantize(_D2, ROUND_HALF_UP)
                empr_share = (contributable * empr_pct / Decimal('100')).quantize(_D2, ROUND_HALF_UP)
                occ_hazard = Decimal('0').quantize(_D2)
            else:
                emp_share = Decimal('0').quantize(_D2)
                empr_share = Decimal('0').quantize(_D2)
                occ_hazard = (contributable * occ_pct / Decimal('100')).quantize(_D2, ROUND_HALF_UP)
            total = (emp_share + empr_share + occ_hazard).quantize(_D2, ROUND_HALF_UP)

            total_emp_share += emp_share
            total_empr_share += empr_share
            total_occ_hazard += occ_hazard
            total_all += total

            export_data.append({
                "رقم الموظف / Emp #": getattr(emp, 'employee_number', '') or emp.id,
                "الاسم / Name": emp.name,
                "رقم الهوية / National ID": getattr(emp, 'national_id', '') or '',
                "الجنسية / Nationality": getattr(emp, 'nationality', '') or '',
                "القسم / Department": getattr(emp, 'department', '') or '',
                "الراتب الأساسي / Basic Salary": str(basic),
                "بدل السكن / Housing": str(housing),
                "الراتب الخاضع / Contributable": str(contributable),
                f"حصة الموظف {emp_pct}% / Employee Share": str(emp_share),
                f"حصة صاحب العمل {empr_pct}% / Employer Share": str(empr_share),
                f"أخطار مهنية {occ_pct}% / Occ. Hazard": str(occ_hazard),
                "الإجمالي / Total": str(total),
            })

        # Summary row
        export_data.append({
            "رقم الموظف / Emp #": "",
            "الاسم / Name": "الإجمالي / TOTAL",
            "رقم الهوية / National ID": "",
            "الجنسية / Nationality": "",
            "القسم / Department": "",
            "الراتب الأساسي / Basic Salary": "",
            "بدل السكن / Housing": "",
            "الراتب الخاضع / Contributable": "",
            f"حصة الموظف {emp_pct}% / Employee Share": str(total_emp_share.quantize(_D2, ROUND_HALF_UP)),
            f"حصة صاحب العمل {empr_pct}% / Employer Share": str(total_empr_share.quantize(_D2, ROUND_HALF_UP)),
            f"أخطار مهنية {occ_pct}% / Occ. Hazard": str(total_occ_hazard.quantize(_D2, ROUND_HALF_UP)),
            "الإجمالي / Total": str(total_all.quantize(_D2, ROUND_HALF_UP)),
        })

        columns = list(export_data[0].keys())
        period_str = f"{target_year}-{str(target_month).zfill(2)}"

        if format == "excel":
            buffer = generate_excel(export_data, columns, sheet_name=f"GOSI {period_str}")
            return create_export_response(buffer, f"gosi_report_{period_str}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        elif format == "csv":
            import csv
            import io
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=columns)
            writer.writeheader()
            writer.writerows(export_data)
            csv_bytes = io.BytesIO(output.getvalue().encode('utf-8-sig'))
            return create_export_response(csv_bytes, f"gosi_report_{period_str}.csv", "text/csv")
        else:
            pdf_data = [columns]
            for row in export_data:
                pdf_data.append([str(row.get(c, '')) for c in columns])
            buffer = generate_pdf(pdf_data, f"GOSI Report - تقرير التأمينات الاجتماعية ({period_str})")
            return create_export_response(buffer, f"gosi_report_{period_str}.pdf", "application/pdf")


# =============================================
# مستندات الموظفين - Employee Documents
# =============================================

@router.get("/documents", response_model=List[EmployeeDocumentResponse], dependencies=[Depends(require_permission("hr.view"))])
def list_documents(employee_id: Optional[int] = None, expiring_soon: Optional[bool] = None, branch_id: Optional[int] = None, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """List Documents."""
    with transactional(company_id) as conn:
        query = """
            SELECT d.*, e.first_name || ' ' || e.last_name as employee_name
            FROM employee_documents d
            JOIN employees e ON d.employee_id = e.id
            WHERE 1=1
        """
        params = {}
        if employee_id:
            query += " AND d.employee_id = :eid"
            params["eid"] = employee_id
        if expiring_soon:
            query += " AND d.expiry_date IS NOT NULL AND d.expiry_date <= CURRENT_DATE + d.alert_days * INTERVAL '1 day'"
        query += " " + branch_scope_filter(current_user, branch_id, "e.branch_id", params, branch_param="bid")
        query += " ORDER BY d.expiry_date ASC NULLS LAST"
        rows = conn.execute(text(query), params).fetchall()
        return [dict(r._mapping) for r in rows]


@router.post("/documents", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def create_document(data: EmployeeDocumentCreate, request: Request, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Create Document."""
    with transactional(company_id) as conn:
        # Determine status based on expiry
        doc_status = "valid"
        if data.expiry_date:
            if data.expiry_date < date.today():
                doc_status = "expired"
            elif (data.expiry_date - date.today()).days <= data.alert_days:
                doc_status = "expiring_soon"

        result = conn.execute(text("""
            INSERT INTO employee_documents (employee_id, document_type, document_number, issue_date, expiry_date, issuing_authority, file_url, notes, alert_days, status)
            VALUES (:eid, :dtype, :dnum, :issue, :expiry, :auth, :url, :notes, :alert, :status) RETURNING id
        """), {
            "eid": data.employee_id, "dtype": data.document_type, "dnum": data.document_number,
            "issue": data.issue_date, "expiry": data.expiry_date, "auth": data.issuing_authority,
            "url": data.file_url, "notes": data.notes, "alert": data.alert_days, "status": doc_status
        })
        doc_id = result.scalar()
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.document.create", resource_type="employee_document",
            resource_id=str(doc_id), details={"employee_id": data.employee_id, "type": data.document_type}, request=request
        )
        return {"id": doc_id, "message": "تم إضافة المستند"}


@router.put("/documents/{doc_id}", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def update_document(doc_id: int, data: EmployeeDocumentUpdate, request: Request, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Update Document."""
    with transactional(company_id) as conn:
        fields, params = [], {"id": doc_id}
        for field in ["document_number", "issue_date", "expiry_date", "issuing_authority", "file_url", "notes", "alert_days"]:
            val = getattr(data, field, None)
            if val is not None:
                fields.append(f"{field} = :{field}")
                params[field] = val
        if not fields:
            raise HTTPException(**http_error(400, "no_changes"))
        fields.append("updated_at = CURRENT_TIMESTAMP")
        conn.execute(text(f"UPDATE employee_documents SET {', '.join(fields)} WHERE id = :id"), params)
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.document.update", resource_type="employee_document",
            resource_id=str(doc_id), details={"fields": list(params.keys())}, request=request
        )
        return {"message": "تم التحديث"}


@router.delete("/documents/{doc_id}", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def delete_document(doc_id: int, request: Request, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Delete Document."""
    with transactional(company_id) as conn:
        conn.execute(text("DELETE FROM employee_documents WHERE id = :id"), {"id": doc_id})
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.document.delete", resource_type="employee_document",
            resource_id=str(doc_id), details={}, request=request
        )
        return {"message": "تم الحذف"}


# =============================================
# تقييم الأداء - Performance Reviews
# =============================================

@router.get("/performance-reviews", response_model=List[PerformanceReviewResponse], dependencies=[Depends(require_permission("hr.view"))])
def list_performance_reviews(employee_id: Optional[int] = None, branch_id: Optional[int] = None, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """List Performance Reviews."""
    with transactional(company_id) as conn:
        query = """
            SELECT pr.*, 
                e.first_name || ' ' || e.last_name as employee_name,
                r.first_name || ' ' || r.last_name as reviewer_name
            FROM performance_reviews pr
            JOIN employees e ON pr.employee_id = e.id
            LEFT JOIN employees r ON pr.reviewer_id = r.id
            WHERE 1=1
        """
        params = {}
        if employee_id:
            query += " AND pr.employee_id = :eid"
            params["eid"] = employee_id
        query += " " + branch_scope_filter(current_user, branch_id, "e.branch_id", params, branch_param="bid")
        query += " ORDER BY pr.review_date DESC"
        rows = conn.execute(text(query), params).fetchall()
        return [dict(r._mapping) for r in rows]


@router.post("/performance-reviews", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def create_performance_review(data: PerformanceReviewCreate, request: Request, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Create Performance Review."""
    with transactional(company_id) as conn:
        result = conn.execute(text("""
            INSERT INTO performance_reviews (employee_id, reviewer_id, review_period, review_date, review_type, overall_rating, strengths, weaknesses, goals)
            VALUES (:eid, :rid, :period, :rdate, :rtype, :rating, :strengths, :weaknesses, :goals) RETURNING id
        """), {
            "eid": data.employee_id, "rid": data.reviewer_id, "period": data.review_period,
            "rdate": data.review_date, "rtype": data.review_type, "rating": data.overall_rating,
            "strengths": data.strengths, "weaknesses": data.weaknesses, "goals": data.goals
        })
        pr_id = result.scalar()
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.performance_review.create", resource_type="performance_review",
            resource_id=str(pr_id), details={"employee_id": data.employee_id}, request=request
        )
        return {"id": pr_id, "message": "تم إنشاء التقييم"}


@router.put("/performance-reviews/{review_id}", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def update_performance_review(review_id: int, data: PerformanceReviewUpdate, request: Request, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Update Performance Review."""
    with transactional(company_id) as conn:
        fields, params = [], {"id": review_id}
        for field in ["overall_rating", "strengths", "weaknesses", "goals", "self_rating", "self_comments", "manager_comments", "status"]:
            val = getattr(data, field, None)
            if val is not None:
                fields.append(f"{field} = :{field}")
                params[field] = val
        if not fields:
            raise HTTPException(**http_error(400, "no_changes"))
        fields.append("updated_at = CURRENT_TIMESTAMP")
        conn.execute(text(f"UPDATE performance_reviews SET {', '.join(fields)} WHERE id = :id"), params)
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.performance_review.update", resource_type="performance_review",
            resource_id=str(review_id), details={"fields": list(params.keys())}, request=request
        )
        return {"message": "تم تحديث التقييم"}


# =============================================
# برامج التدريب - Training Programs
# =============================================

@router.get("/training", response_model=List[TrainingProgramResponse], dependencies=[Depends(require_permission("hr.view"))])
def list_training_programs(company_id: str = Depends(get_current_user_company)):
    """List Training Programs."""
    with transactional(company_id) as conn:
        rows = conn.execute(text("""
            SELECT t.*, COUNT(tp.id) as participant_count
            FROM training_programs t
            LEFT JOIN training_participants tp ON t.id = tp.training_id
            GROUP BY t.id
            ORDER BY t.start_date DESC NULLS LAST
        """)).fetchall()
        return [dict(r._mapping) for r in rows]


@router.post("/training", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def create_training_program(data: TrainingProgramCreate, request: Request, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Create Training Program."""
    with transactional(company_id) as conn:
        result = conn.execute(text("""
            INSERT INTO training_programs (name, name_en, description, trainer, location, start_date, end_date, max_participants, cost)
            VALUES (:name, :name_en, :desc, :trainer, :loc, :start, :end, :max, :cost) RETURNING id
        """), {
            "name": data.name, "name_en": data.name_en, "desc": data.description,
            "trainer": data.trainer, "loc": data.location, "start": data.start_date,
            "end": data.end_date, "max": data.max_participants, "cost": data.cost
        })
        tp_id = result.scalar()
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.training.create", resource_type="training_program",
            resource_id=str(tp_id), details={"name": data.name}, request=request
        )
        return {"id": tp_id, "message": "تم إنشاء البرنامج التدريبي"}


@router.put("/training/{training_id}", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def update_training_program(training_id: int, data: TrainingProgramUpdate, request: Request, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Update Training Program."""
    with transactional(company_id) as conn:
        fields, params = [], {"id": training_id}
        for field in ["name", "name_en", "description", "trainer", "location", "start_date", "end_date", "max_participants", "cost", "status"]:
            val = getattr(data, field, None)
            if val is not None:
                fields.append(f"{field} = :{field}")
                params[field] = val
        if not fields:
            raise HTTPException(**http_error(400, "no_changes"))
        conn.execute(text(f"UPDATE training_programs SET {', '.join(fields)} WHERE id = :id"), params)
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.training.update", resource_type="training_program",
            resource_id=str(training_id), details={"fields": list(params.keys())}, request=request
        )
        return {"message": "تم التحديث"}


@router.post("/training/{training_id}/participants", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def add_training_participant(training_id: int, data: TrainingParticipantCreate, request: Request, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Add Training Participant."""
    conn = get_db_connection(company_id)
    try:
        conn.execute(text("""
            INSERT INTO training_participants (training_id, employee_id)
            VALUES (:tid, :eid)
        """), {"tid": training_id, "eid": data.employee_id})
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.training.add_participant", resource_type="training_participant",
            resource_id=str(training_id), details={"employee_id": data.employee_id}, request=request
        )
        conn.commit()
        return {"message": "تم تسجيل المشارك"}
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(status_code=400, detail="المشارك مسجل مسبقاً")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        conn.close()


@router.get("/training/{training_id}/participants", response_model=List[TrainingParticipantResponse], dependencies=[Depends(require_permission("hr.view"))])
def list_training_participants(training_id: int, company_id: str = Depends(get_current_user_company)):
    """List Training Participants."""
    with transactional(company_id) as conn:
        rows = conn.execute(text("""
            SELECT tp.*, e.first_name || ' ' || e.last_name as employee_name
            FROM training_participants tp
            JOIN employees e ON tp.employee_id = e.id
            WHERE tp.training_id = :tid
            ORDER BY e.first_name
        """), {"tid": training_id}).fetchall()
        return [dict(r._mapping) for r in rows]


@router.put("/training/participants/{participant_id}", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def update_training_participant(participant_id: int, data: TrainingParticipantUpdate, request: Request, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Update Training Participant."""
    with transactional(company_id) as conn:
        fields, params = [], {"id": participant_id}
        for field in ["attendance_status", "certificate_issued", "score", "feedback"]:
            val = getattr(data, field, None)
            if val is not None:
                fields.append(f"{field} = :{field}")
                params[field] = val
        if not fields:
            raise HTTPException(**http_error(400, "no_changes"))
        conn.execute(text(f"UPDATE training_participants SET {', '.join(fields)} WHERE id = :id"), params)
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.training.update_participant", resource_type="training_participant",
            resource_id=str(participant_id), details={"fields": list(params.keys())}, request=request
        )
        return {"message": "تم التحديث"}


# =============================================
# المخالفات - Violations
# =============================================

@router.get("/violations", response_model=List[ViolationResponse], dependencies=[Depends(require_permission("hr.view"))])
def list_violations(employee_id: Optional[int] = None, branch_id: Optional[int] = None, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """List Violations."""
    with transactional(company_id) as conn:
        query = """
            SELECT v.*, e.first_name || ' ' || e.last_name as employee_name
            FROM employee_violations v
            JOIN employees e ON v.employee_id = e.id
            WHERE 1=1
        """
        params = {}
        if employee_id:
            query += " AND v.employee_id = :eid"
            params["eid"] = employee_id
        query += " " + branch_scope_filter(current_user, branch_id, "e.branch_id", params, branch_param="bid")
        query += " ORDER BY v.violation_date DESC"
        rows = conn.execute(text(query), params).fetchall()
        return [dict(r._mapping) for r in rows]


@router.post("/violations", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def create_violation(data: ViolationCreate, request: Request, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Create Violation."""
    with transactional(company_id) as conn:
        user_id = current_user.id if hasattr(current_user, 'id') else current_user.get("id")
        result = conn.execute(text("""
            INSERT INTO employee_violations (employee_id, violation_date, violation_type, severity, description, action_taken, penalty_amount, deduct_from_salary, reported_by)
            VALUES (:eid, :vdate, :vtype, :sev, :desc, :action, :penalty, :deduct, :reported) RETURNING id
        """), {
            "eid": data.employee_id, "vdate": data.violation_date, "vtype": data.violation_type,
            "sev": data.severity, "desc": data.description, "action": data.action_taken,
            "penalty": data.penalty_amount, "deduct": data.deduct_from_salary,
            "reported": data.reported_by or user_id
        })
        v_id = result.scalar()
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.violation.create", resource_type="employee_violation",
            resource_id=str(v_id), details={"employee_id": data.employee_id, "type": data.violation_type}, request=request
        )
        return {"id": v_id, "message": "تم تسجيل المخالفة"}


@router.put("/violations/{violation_id}", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def update_violation(violation_id: int, data: ViolationUpdate, request: Request, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Update Violation."""
    with transactional(company_id) as conn:
        fields, params = [], {"id": violation_id}
        for field in ["action_taken", "penalty_amount", "deduct_from_salary", "status"]:
            val = getattr(data, field, None)
            if val is not None:
                fields.append(f"{field} = :{field}")
                params[field] = val
        if not fields:
            raise HTTPException(**http_error(400, "no_changes"))
        fields.append("updated_at = CURRENT_TIMESTAMP")
        conn.execute(text(f"UPDATE employee_violations SET {', '.join(fields)} WHERE id = :id"), params)
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.violation.update", resource_type="employee_violation",
            resource_id=str(violation_id), details={"fields": list(params.keys())}, request=request
        )
        return {"message": "تم تحديث المخالفة"}


# =============================================
# العهد - Employee Custody
# =============================================

@router.get("/custody", response_model=List[CustodyResponse], dependencies=[Depends(require_permission("hr.view"))])
def list_custody(employee_id: Optional[int] = None, status_filter: Optional[str] = None, branch_id: Optional[int] = None, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """List Custody."""
    with transactional(company_id) as conn:
        query = """
            SELECT c.*, e.first_name || ' ' || e.last_name as employee_name
            FROM employee_custody c
            JOIN employees e ON c.employee_id = e.id
            WHERE 1=1
        """
        params = {}
        if employee_id:
            query += " AND c.employee_id = :eid"
            params["eid"] = employee_id
        if status_filter:
            query += " AND c.status = :status"
            params["status"] = status_filter
        query += " " + branch_scope_filter(current_user, branch_id, "e.branch_id", params, branch_param="bid")
        query += " ORDER BY c.assigned_date DESC"
        rows = conn.execute(text(query), params).fetchall()
        return [dict(r._mapping) for r in rows]


@router.post("/custody", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def create_custody(data: CustodyCreate, request: Request, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Create Custody."""
    with transactional(company_id) as conn:
        result = conn.execute(text("""
            INSERT INTO employee_custody (employee_id, item_name, item_type, serial_number, assigned_date, condition_on_assign, value, notes)
            VALUES (:eid, :item, :itype, :serial, :date, :condition, :value, :notes) RETURNING id
        """), {
            "eid": data.employee_id, "item": data.item_name, "itype": data.item_type,
            "serial": data.serial_number, "date": data.assigned_date,
            "condition": data.condition_on_assign, "value": data.value, "notes": data.notes
        })
        c_id = result.scalar()
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.custody.create", resource_type="employee_custody",
            resource_id=str(c_id), details={"employee_id": data.employee_id, "item": data.item_name}, request=request
        )
        return {"id": c_id, "message": "تم تسليم العهدة"}


@router.put("/custody/{custody_id}", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def update_custody(custody_id: int, data: CustodyUpdate, request: Request, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Update Custody."""
    with transactional(company_id) as conn:
        fields, params = [], {"id": custody_id}
        for field in ["return_date", "condition_on_return", "status", "notes"]:
            val = getattr(data, field, None)
            if val is not None:
                fields.append(f"{field} = :{field}")
                params[field] = val
        if not fields:
            raise HTTPException(**http_error(400, "no_changes"))
        fields.append("updated_at = CURRENT_TIMESTAMP")
        conn.execute(text(f"UPDATE employee_custody SET {', '.join(fields)} WHERE id = :id"), params)
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.custody.update", resource_type="employee_custody",
            resource_id=str(custody_id), details={"fields": list(params.keys())}, request=request
        )
        return {"message": "تم تحديث العهدة"}


@router.put("/custody/{custody_id}/return", dependencies=[Depends(require_permission("hr.manage"))], response_model=Dict[str, Any])
def return_custody(custody_id: int, data: CustodyUpdate, request: Request, current_user: UserResponse = Depends(get_current_user), company_id: str = Depends(get_current_user_company)):
    """Return Custody."""
    with transactional(company_id) as conn:
        conn.execute(text("""
            UPDATE employee_custody SET status = 'returned', return_date = CURRENT_DATE, 
            condition_on_return = :condition, notes = :notes, updated_at = CURRENT_TIMESTAMP
            WHERE id = :id
        """), {"condition": data.condition_on_return or "good", "notes": data.notes, "id": custody_id})
        log_activity(
            conn, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="hr.custody.return", resource_type="employee_custody",
            resource_id=str(custody_id), details={}, request=request
        )
        return {"message": "تم استلام العهدة"}
