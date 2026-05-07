"""taxes sub-router — split from monolithic taxes.py (T6.3).

Mounted under the parent router via taxes/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pydantic import BaseModel
import logging
from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import branch_scope_filter_from_scope, require_permission, resolve_branch_scope, validate_branch_access, require_module
from utils.audit import log_activity
from utils.fiscal_lock import check_fiscal_period_open
from utils.accounting import generate_sequential_number, get_mapped_account_id, get_base_currency
from utils.currency_display import base_to_display_amount, display_currency_fields, document_amount_base_sql, resolve_display_currency
from schemas.taxes import TaxRateCreate, TaxRateUpdate, TaxGroupCreate, TaxReturnCreate, TaxPaymentCreate

logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')

def _dec(v) -> Decimal:
    return Decimal(str(v or 0))


def _display_dec(value: Any, display_meta: dict) -> Decimal:
    return _dec(base_to_display_amount(value, display_meta)).quantize(_D2, ROUND_HALF_UP)

router = APIRouter()

from .core import _D2, _D4, _dec

@router.get("/vat-report", response_model=Dict[str, Any], dependencies=[Depends(require_permission(["accounting.view", "taxes.view", "reports.view"]))])
def get_vat_report(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """جلب تقرير ضريبة القيمة المضافة للفترة المحددة"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    with transactional(current_user.company_id) as db:
        if not start_date:
            start_date = date.today().replace(day=1)
        if not end_date:
            end_date = date.today()

        display_meta = resolve_display_currency(db, branch_scope)
        params = {"start": start_date, "end": end_date, "base_currency": display_meta["base_currency"]}
        branch_filter = branch_scope_filter_from_scope(branch_scope, "i.branch_id", params)
        taxable_base_sql = document_amount_base_sql("(il.quantity * il.unit_price - COALESCE(il.discount, 0))", "i")
        vat_base_sql = document_amount_base_sql("((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * (il.tax_rate / 100))", "i")

        output_vat = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT COALESCE(SUM({taxable_base_sql}), 0) as taxable_amount,
                   COALESCE(SUM({vat_base_sql}), 0) as vat_amount
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'sales' AND i.status NOT IN ('draft', 'cancelled')
            AND i.invoice_date BETWEEN :start AND :end {branch_filter}
        """), params).fetchone()

        input_vat = db.execute(text(  # noqa: sql-lint
            f"""
             SELECT COALESCE(SUM({taxable_base_sql}), 0) as taxable_amount,
                 COALESCE(SUM({vat_base_sql}), 0) as vat_amount
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'purchase' AND i.status NOT IN ('draft', 'cancelled')
            AND i.invoice_date BETWEEN :start AND :end {branch_filter}
        """), params).fetchone()

        output_vat_returns = db.execute(text(  # noqa: sql-lint
            f"""
             SELECT COALESCE(SUM({taxable_base_sql}), 0) as taxable_amount,
                 COALESCE(SUM({vat_base_sql}), 0) as vat_amount
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'sales_return' AND i.status NOT IN ('draft', 'cancelled')
            AND i.invoice_date BETWEEN :start AND :end {branch_filter}
        """), params).fetchone()

        input_vat_returns = db.execute(text(  # noqa: sql-lint
            f"""
             SELECT COALESCE(SUM({taxable_base_sql}), 0) as taxable_amount,
                 COALESCE(SUM({vat_base_sql}), 0) as vat_amount
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'purchase_return' AND i.status NOT IN ('draft', 'cancelled')
            AND i.invoice_date BETWEEN :start AND :end {branch_filter}
        """), params).fetchone()

        net_output_taxable = (_dec(output_vat.taxable_amount) - _dec(output_vat_returns.taxable_amount)).quantize(_D2, ROUND_HALF_UP)
        net_output_vat = (_dec(output_vat.vat_amount) - _dec(output_vat_returns.vat_amount)).quantize(_D2, ROUND_HALF_UP)
        net_input_taxable = (_dec(input_vat.taxable_amount) - _dec(input_vat_returns.taxable_amount)).quantize(_D2, ROUND_HALF_UP)
        net_input_vat = (_dec(input_vat.vat_amount) - _dec(input_vat_returns.vat_amount)).quantize(_D2, ROUND_HALF_UP)
        net_vat_payable = (net_output_vat - net_input_vat).quantize(_D2, ROUND_HALF_UP)

        return {
            **display_currency_fields(display_meta),
            "period": {"start": start_date, "end": end_date},
            "output_vat": {"taxable": str(_display_dec(net_output_taxable, display_meta)), "vat": str(_display_dec(net_output_vat, display_meta))},
            "input_vat": {"taxable": str(_display_dec(net_input_taxable, display_meta)), "vat": str(_display_dec(net_input_vat, display_meta))},
            "net_vat_payable": str(_display_dec(net_vat_payable, display_meta))
        }


# ==================== TAX AUDIT ====================

@router.get("/audit-report", response_model=List[dict], dependencies=[Depends(require_permission(["accounting.view", "taxes.view", "reports.view"]))])
def get_tax_audit(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير تدقيق ضريبي مفصل لكل معاملة خاضعة للضريبة بالفترة"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    with transactional(current_user.company_id) as db:
        if not start_date:
            start_date = date.today().replace(day=1)
        if not end_date:
            end_date = date.today()

        params = {"start": start_date, "end": end_date}
        branch_filter = branch_scope_filter_from_scope(branch_scope, "i.branch_id", params)

        results = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT i.id, i.invoice_number, i.invoice_date, i.invoice_type,
                p.name as party_name, p.tax_number,
                SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate) as taxable_amount,
                SUM((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * i.exchange_rate * (il.tax_rate / 100)) as vat_amount
            FROM invoices i
            JOIN invoice_lines il ON i.id = il.invoice_id
            LEFT JOIN parties p ON i.party_id = p.id
            WHERE i.invoice_date BETWEEN :start AND :end
              AND il.tax_rate > 0 AND i.status != 'draft'
              {branch_filter}
            GROUP BY i.id, i.invoice_number, i.invoice_date, i.invoice_type, p.name, p.tax_number
            ORDER BY i.invoice_date DESC
        """), params).fetchall()

        return [
            {
                "id": r.id, "number": r.invoice_number, "date": r.invoice_date,
                "type": r.invoice_type, "party": r.party_name, "tax_number": r.tax_number,
                "taxable": str(_dec(r.taxable_amount or 0).quantize(_D2, ROUND_HALF_UP)), "vat": str(_dec(r.vat_amount or 0).quantize(_D2, ROUND_HALF_UP))
            }
            for r in results
        ]


# ==================== TAX SUMMARY ====================

@router.get("/summary", dependencies=[Depends(require_permission(["accounting.view", "taxes.view"]))], response_model=Dict[str, Any])
def get_tax_summary(
    branch_id: Optional[int] = None,
    year: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """ملخص وحدة الضرائب (لوحة تحكم) مع فلترة حسب الفرع"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    branch_id = branch_scope["branch_id"]
    with transactional(current_user.company_id) as db:
        display_meta = resolve_display_currency(db, branch_scope)
        # ── Branch/country aware rates count ──
        rate_where = "WHERE is_active = TRUE"
        rate_params = {}
        if branch_id:
            # Get branch country_code for filtering rates
            br = db.execute(text("SELECT country_code FROM branches WHERE id = :bid"), {"bid": branch_id}).fetchone()
            if br and br.country_code:
                rate_where += " AND (country_code = :cc OR country_code IS NULL)"
                rate_params["cc"] = br.country_code
        rates_count = db.execute(text(f"SELECT COUNT(*) FROM tax_rates {rate_where}"), rate_params).scalar() or 0  # noqa: sql-lint

        # ── Returns stats with branch filter ──
        ret_where = "WHERE status != 'cancelled'"
        ret_params = {}
        ret_where += " " + branch_scope_filter_from_scope(branch_scope, "branch_id", ret_params)
        if year:
            ret_where += " AND tax_period LIKE :yp"
            ret_params["yp"] = f"{year}%"

        returns_stats = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'draft') as draft,
                COUNT(*) FILTER (WHERE status = 'filed') as filed,
                COUNT(*) FILTER (WHERE status = 'paid') as paid,
                COALESCE(SUM(total_amount) FILTER (WHERE status = 'filed'), 0) as pending_amount,
                COALESCE(SUM(total_amount) FILTER (WHERE status = 'paid'), 0) as paid_amount
            FROM tax_returns {ret_where}
        """), ret_params).fetchone()

        today = date.today()
        first_of_month = today.replace(day=1)
        vat_params = {"start": first_of_month, "end": today, "base_currency": display_meta["base_currency"]}
        vat_branch_filter = branch_scope_filter_from_scope(branch_scope, "i.branch_id", vat_params)
        vat_base_sql = document_amount_base_sql("((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * (il.tax_rate / 100))", "i")

        current_vat = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT
                COALESCE(SUM(CASE WHEN i.invoice_type = 'sales' THEN {vat_base_sql} ELSE 0 END), 0) as output_vat,
                COALESCE(SUM(CASE WHEN i.invoice_type = 'purchase' THEN {vat_base_sql} ELSE 0 END), 0) as input_vat
            FROM invoice_lines il JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_date >= :start AND i.invoice_date <= :end
            AND i.status NOT IN ('draft', 'cancelled') AND il.tax_rate > 0
            {vat_branch_filter}
        """), vat_params).fetchone()

        overdue_where = "WHERE status = 'filed' AND due_date < CURRENT_DATE"
        overdue_params = {}
        overdue_where += " " + branch_scope_filter_from_scope(branch_scope, "branch_id", overdue_params)
        overdue = db.execute(text(f"SELECT COUNT(*) FROM tax_returns {overdue_where}"), overdue_params).scalar() or 0  # noqa: sql-lint

        # ── Employee tax summary (withholding from payroll) ──
        emp_tax = {"total_employees": 0, "total_salary_tax": 0, "total_gosi": 0}
        try:
            emp_where = ""
            emp_params = {}
            emp_where = branch_scope_filter_from_scope(branch_scope, "e.branch_id", emp_params)
            emp_row = db.execute(text(  # noqa: sql-lint
                f"""
                SELECT COUNT(DISTINCT pe.employee_id) as total_employees,
                       COALESCE(SUM(pe.gosi_employee_share), 0) as total_gosi,
                       COALESCE(SUM(pe.net_salary - pe.basic_salary), 0) as total_deductions
                FROM payroll_entries pe
                JOIN employees e ON pe.employee_id = e.id
                WHERE pe.status IN ('approved', 'paid') {emp_where}
            """), emp_params).fetchone()
            if emp_row:
                emp_tax["total_employees"] = emp_row.total_employees or 0
                emp_tax["total_gosi"] = float(emp_row.total_gosi or 0)
        except Exception:
            pass  # payroll tables may not exist yet

        return {
            **display_currency_fields(display_meta),
            "active_rates": rates_count,
            "returns": {
                "total": returns_stats.total or 0, "draft": returns_stats.draft or 0,
                "filed": returns_stats.filed or 0, "paid": returns_stats.paid or 0,
                "pending_amount": str(_display_dec(returns_stats.pending_amount or 0, display_meta)),
                "paid_amount": str(_display_dec(returns_stats.paid_amount or 0, display_meta))
            },
            "current_period": {
                "output_vat": str(_display_dec(current_vat.output_vat or 0, display_meta)),
                "input_vat": str(_display_dec(current_vat.input_vat or 0, display_meta)),
                "net_vat": str(_display_dec(_dec(current_vat.output_vat) - _dec(current_vat.input_vat), display_meta))
            },
            "overdue_returns": overdue,
            "employee_taxes": emp_tax,
            "branch_id": branch_id,
        }


# ==================== TAX SETTLEMENT ====================

@router.get("/branch-analysis", dependencies=[Depends(require_permission(["accounting.view", "taxes.view", "reports.view"]))], response_model=Dict[str, Any])
def get_branch_tax_analysis(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    تحليل ضريبي مفصل حسب الفرع — يعرض VAT مقسم لكل فرع
    يستخدم هذا التقرير لمعرفة حجم الالتزامات الضريبية لكل فرع
    """
    branch_scope = resolve_branch_scope(current_user, branch_id)
    with transactional(current_user.company_id) as db:
        display_meta = resolve_display_currency(db, branch_scope)
        if not start_date:
            start_date = date.today().replace(month=1, day=1)
        if not end_date:
            end_date = date.today()

        params = {"start": start_date, "end": end_date, "base_currency": display_meta["base_currency"]}
        branch_filter = branch_scope_filter_from_scope(branch_scope, "i.branch_id", params)
        taxable_base_sql = document_amount_base_sql("(il.quantity * il.unit_price - COALESCE(il.discount, 0))", "i")
        vat_base_sql = document_amount_base_sql("((il.quantity * il.unit_price - COALESCE(il.discount, 0)) * (il.tax_rate / 100))", "i")

        rows = db.execute(text(  # noqa: sql-lint
            f"""

            SELECT 
                b.id as branch_id, b.branch_name, b.branch_name_en,
                b.country_code as jurisdiction, COALESCE(b.default_currency, :base_currency) as branch_currency,
                COALESCE(SUM(CASE WHEN i.invoice_type = 'sales'
                    THEN {vat_base_sql} ELSE 0 END), 0) as output_vat,
                COALESCE(SUM(CASE WHEN i.invoice_type = 'purchase'
                    THEN {vat_base_sql} ELSE 0 END), 0) as input_vat,
                COALESCE(SUM(CASE WHEN i.invoice_type = 'sales'
                    THEN {taxable_base_sql} ELSE 0 END), 0) as taxable_sales,
                COALESCE(SUM(CASE WHEN i.invoice_type = 'purchase'
                    THEN {taxable_base_sql} ELSE 0 END), 0) as taxable_purchases,
                COUNT(DISTINCT i.id) as invoice_count
            FROM invoices i
            JOIN invoice_lines il ON i.id = il.invoice_id
            JOIN branches b ON i.branch_id = b.id
            WHERE i.invoice_date BETWEEN :start AND :end
              AND i.status NOT IN ('draft', 'cancelled')
              AND il.tax_rate > 0
              {branch_filter}
                        GROUP BY b.id, b.branch_name, b.branch_name_en, b.country_code, b.default_currency
            ORDER BY output_vat DESC
        """), params).fetchall()

        # Get return stats per branch
        ret_params = {"year_prefix": str(start_date.year) + "%"}
        ret_branch_filter = branch_scope_filter_from_scope(branch_scope, "tr.branch_id", ret_params)

        returns_by_branch = db.execute(text(  # noqa: sql-lint
            f"""

            SELECT tr.branch_id,
                   COUNT(*) as returns_count,
                   COUNT(*) FILTER (WHERE tr.status = 'filed') as filed,
                   COUNT(*) FILTER (WHERE tr.status = 'paid') as paid,
                   COUNT(*) FILTER (WHERE tr.status = 'draft') as draft,
                   COALESCE(SUM(tr.total_amount), 0) as total_tax
            FROM tax_returns tr
            WHERE tr.status != 'cancelled'
              AND tr.tax_period LIKE :year_prefix
              {ret_branch_filter}
            GROUP BY tr.branch_id
        """), ret_params).fetchall()

        ret_map = {r.branch_id: dict(r._mapping) for r in returns_by_branch}

        result = []
        grand_output = Decimal("0")
        grand_input = Decimal("0")

        for r in rows:
            out = _dec(r.output_vat).quantize(_D2, ROUND_HALF_UP)
            inp = _dec(r.input_vat).quantize(_D2, ROUND_HALF_UP)
            net = (out - inp).quantize(_D2, ROUND_HALF_UP)
            grand_output += out
            grand_input += inp
            ret_info = ret_map.get(r.branch_id, {})

            result.append({
                "branch_id": r.branch_id,
                "branch_name": r.branch_name,
                "branch_name_en": r.branch_name_en,
                "jurisdiction": r.jurisdiction or "SA",
                "currency": display_meta["currency"],
                "branch_currency": str(r.branch_currency or display_meta["base_currency"]).upper(),
                "output_vat": float(_display_dec(out, display_meta)),
                "input_vat": float(_display_dec(inp, display_meta)),
                "net_vat": float(_display_dec(net, display_meta)),
                "taxable_sales": float(_display_dec(r.taxable_sales or 0, display_meta)),
                "taxable_purchases": float(_display_dec(r.taxable_purchases or 0, display_meta)),
                "invoice_count": r.invoice_count,
                "returns_count": ret_info.get("returns_count", 0),
                "returns_filed": ret_info.get("filed", 0),
                "returns_paid": ret_info.get("paid", 0),
                "returns_draft": ret_info.get("draft", 0),
            })

        return {
            **display_currency_fields(display_meta),
            "period": {"start": start_date, "end": end_date},
            "branches": result,
            "totals": {
                "output_vat": float(_display_dec(grand_output, display_meta)),
                "input_vat": float(_display_dec(grand_input, display_meta)),
                "net_vat": float(_display_dec(grand_output - grand_input, display_meta)),
                "branch_count": len(result)
            }
        }


# ==================== EMPLOYEE TAX OBLIGATIONS ====================

@router.get("/employee-taxes", dependencies=[Depends(require_permission(["accounting.view", "taxes.view", "hr.view"]))], response_model=Dict[str, Any])
def get_employee_tax_obligations(
    branch_id: Optional[int] = None,
    department_id: Optional[int] = None,
    employee_id: Optional[int] = None,
    year: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    تقرير الالتزامات الضريبية للموظفين
    يشمل: ضريبة الدخل على الرواتب، التأمينات الاجتماعية (GOSI)، استقطاع ضريبي
    يمكن الفلترة حسب الفرع، القسم، الموظف، والسنة
    """
    branch_scope = resolve_branch_scope(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        if not year:
            year = date.today().year

        where_parts = ["pe.status IN ('approved', 'paid')"]
        params = {"year": year}
        branch_condition = branch_scope_filter_from_scope(branch_scope, "e.branch_id", params, prefix="").strip()
        if branch_condition:
            where_parts.append(branch_condition)
        if department_id:
            where_parts.append("e.department_id = :department_id")
            params["department_id"] = department_id
        if employee_id:
            where_parts.append("e.id = :employee_id")
            params["employee_id"] = employee_id

        where = " AND ".join(where_parts)

        employees = db.execute(text(  # noqa: sql-lint
            f"""

            SELECT 
                e.id as employee_id, e.employee_code,
                CONCAT(e.first_name, ' ', e.last_name) as employee_name,
                e.tax_id, e.social_security,
                e.branch_id, b.branch_name, b.country_code as jurisdiction,
                d.name as department_name,
                COUNT(pe.id) as payslip_count,
                COALESCE(SUM(pe.basic_salary), 0) as total_basic,
                COALESCE(SUM(pe.housing_allowance), 0) as total_housing,
                COALESCE(SUM(pe.transport_allowance), 0) as total_transport,
                COALESCE(SUM(pe.other_allowances), 0) as total_other_allowances,
                COALESCE(SUM(pe.gross_salary), 0) as total_gross,
                COALESCE(SUM(pe.gosi_employee_share), 0) as total_gosi_employee,
                COALESCE(SUM(pe.gosi_employer_share), 0) as total_gosi_employer,
                COALESCE(SUM(pe.net_salary), 0) as total_net,
                COALESCE(SUM(pe.gross_salary - pe.net_salary), 0) as total_deductions
            FROM employees e
            JOIN payroll_entries pe ON pe.employee_id = e.id
            LEFT JOIN branches b ON e.branch_id = b.id
            LEFT JOIN departments d ON e.department_id = d.id
            LEFT JOIN payroll_periods pp ON pe.period_id = pp.id
            WHERE {where}
              AND EXTRACT(YEAR FROM pp.start_date) = :year
            GROUP BY e.id, e.employee_code, e.first_name, e.last_name, e.tax_id,
                     e.social_security, e.branch_id, b.branch_name, b.country_code,
                     d.name
            ORDER BY total_gross DESC
        """), params).fetchall()

        # Get GOSI settings for computation
        gosi = db.execute(text(
            "SELECT employee_share_pct, employer_share_pct, max_contributable_salary FROM gosi_settings LIMIT 1"
        )).fetchone()

        employee_list = []
        total_gosi_emp = Decimal("0")
        total_gosi_empr = Decimal("0")
        total_gross_all = Decimal("0")

        for emp in employees:
            gosi_emp = _dec(emp.total_gosi_employee).quantize(_D2, ROUND_HALF_UP)
            gosi_empr = _dec(emp.total_gosi_employer).quantize(_D2, ROUND_HALF_UP)
            gross = _dec(emp.total_gross).quantize(_D2, ROUND_HALF_UP)
            total_gosi_emp += gosi_emp
            total_gosi_empr += gosi_empr
            total_gross_all += gross

            # Compute income tax for employee's jurisdiction
            jurisdiction = emp.jurisdiction or "SA"
            tax_due = Decimal("0")
            tax_rate_dec = Decimal("0")
            if jurisdiction != "SA":
                # SA doesn't have personal income tax; other countries do
                regime = db.execute(text(
                    "SELECT default_rate FROM tax_regimes WHERE country_code = :cc AND tax_type = 'salary_tax' AND is_active = TRUE LIMIT 1"
                ), {"cc": jurisdiction}).fetchone()
                if regime:
                    tax_rate_dec = _dec(regime.default_rate)
                    tax_due = (gross * (tax_rate_dec / Decimal("100"))).quantize(_D2, ROUND_HALF_UP)

            employee_list.append({
                "employee_id": emp.employee_id,
                "employee_code": emp.employee_code,
                "employee_name": emp.employee_name,
                "tax_id": emp.tax_id,
                "social_security": emp.social_security,
                "branch_id": emp.branch_id,
                "branch_name": emp.branch_name,
                "jurisdiction": jurisdiction,
                "department_name": emp.department_name,
                "payslip_count": emp.payslip_count,
                "total_gross": float(gross),
                "total_basic": float(emp.total_basic or 0),
                "total_allowances": float(emp.total_housing or 0) + float(emp.total_transport or 0) + float(emp.total_other_allowances or 0),
                "gosi_employee": float(gosi_emp),
                "gosi_employer": float(gosi_empr),
                "income_tax_rate": float(tax_rate_dec),
                "income_tax_due": float(tax_due),
                "total_deductions": float(emp.total_deductions or 0),
                "total_net": float(emp.total_net or 0),
            })

        return {
            "year": year,
            "branch_id": branch_scope["branch_id"],
            "employees": employee_list,
            "summary": {
                "total_employees": len(employee_list),
                "total_gross": float(total_gross_all.quantize(_D2, ROUND_HALF_UP)),
                "total_gosi_employee": float(total_gosi_emp.quantize(_D2, ROUND_HALF_UP)),
                "total_gosi_employer": float(total_gosi_empr.quantize(_D2, ROUND_HALF_UP)),
                "total_gosi_combined": float((total_gosi_emp + total_gosi_empr).quantize(_D2, ROUND_HALF_UP)),
            },
            "gosi_settings": {
                "employee_pct": float(gosi.employee_share_pct) if gosi else 0,
                "employer_pct": float(gosi.employer_share_pct) if gosi else 0,
                "max_salary": float(gosi.max_contributable_salary) if gosi else 0,
            } if gosi else None
        }
    except Exception as e:
        logger.error(f"Error fetching employee tax obligations: {e}")
        return {
            "year": year, "branch_id": branch_id,
            "employees": [], "summary": {"total_employees": 0, "total_gross": 0,
                "total_gosi_employee": 0, "total_gosi_employer": 0, "total_gosi_combined": 0},
            "gosi_settings": None
        }
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# ██  Tax Filing Calendar  (TAX-002)
# ═══════════════════════════════════════════════════════════════

