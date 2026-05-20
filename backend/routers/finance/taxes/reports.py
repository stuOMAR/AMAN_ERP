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
from utils.hr_pii import has_pii_access
from utils.masking import mask_pii
from utils.audit import log_activity
from utils.fiscal_lock import check_fiscal_period_open
from utils.accounting import generate_sequential_number, get_mapped_account_id, get_base_currency
from utils.currency_display import base_to_display_decimal, display_currency_fields, document_amount_base_sql, resolve_display_currency
from utils.tax_precision import display_money_str, money_str, rate_str
from schemas.taxes import TaxRateCreate, TaxRateUpdate, TaxGroupCreate, TaxReturnCreate, TaxPaymentCreate

logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')

def _dec(v) -> Decimal:
    return Decimal(str(v or 0))


def _display_dec(value: Any, display_meta: dict) -> Decimal:
    return _dec(base_to_display_decimal(value, display_meta)).quantize(_D2, ROUND_HALF_UP)

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

        # Aggregate at invoice level to respect header discounts and locked exchange rates
        def _invoice_vat_subquery(invoice_type: str) -> str:
            return f"""
                SELECT
                    COALESCE(SUM(inv.taxable_amount), 0) as taxable_amount,
                    COALESCE(SUM(inv.vat_amount), 0) as vat_amount
                FROM (
                    SELECT
                        i.id,
                        ((COALESCE(i.subtotal, 0) - COALESCE(i.discount, 0)) * COALESCE(i.exchange_rate, 1)) AS taxable_amount,
                        (COALESCE(i.tax_amount, 0) * COALESCE(i.exchange_rate, 1)) AS vat_amount
                    FROM invoices i
                    WHERE i.invoice_type = '{invoice_type}'
                      AND i.status NOT IN ('draft', 'cancelled')
                      AND COALESCE(i.zatca_clearance_status, 'not_required') NOT IN ('pending_clearance', 'rejected')
                      AND i.invoice_date BETWEEN :start AND :end
                      {branch_filter}
                ) inv
            """

        output_vat = db.execute(text(_invoice_vat_subquery("sales")), params).fetchone()

        input_vat = db.execute(text(_invoice_vat_subquery("purchase")), params).fetchone()

        output_vat_returns = db.execute(text(_invoice_vat_subquery("sales_return")), params).fetchone()

        input_vat_returns = db.execute(text(_invoice_vat_subquery("purchase_return")), params).fetchone()

        # T037: Include credit/debit notes in VAT calculation
        output_credit_notes = db.execute(text(_invoice_vat_subquery("sales_credit_note")), params).fetchone()
        output_debit_notes = db.execute(text(_invoice_vat_subquery("sales_debit_note")), params).fetchone()
        input_credit_notes = db.execute(text(_invoice_vat_subquery("purchase_credit_note")), params).fetchone()
        input_debit_notes = db.execute(text(_invoice_vat_subquery("purchase_debit_note")), params).fetchone()

        # Credit notes reduce output VAT; debit notes increase it.
        net_output_taxable = (
            _dec(output_vat.taxable_amount)
            - _dec(output_vat_returns.taxable_amount)
            - _dec(output_credit_notes.taxable_amount)
            + _dec(output_debit_notes.taxable_amount)
        ).quantize(_D2, ROUND_HALF_UP)
        net_output_vat = (
            _dec(output_vat.vat_amount)
            - _dec(output_vat_returns.vat_amount)
            - _dec(output_credit_notes.vat_amount)
            + _dec(output_debit_notes.vat_amount)
        ).quantize(_D2, ROUND_HALF_UP)
        # T037: Net input VAT includes credit notes (reduce) and debit notes (increase)
        net_input_taxable = (_dec(input_vat.taxable_amount) - _dec(input_vat_returns.taxable_amount) - _dec(input_credit_notes.taxable_amount) + _dec(input_debit_notes.taxable_amount)).quantize(_D2, ROUND_HALF_UP)
        net_input_vat = (_dec(input_vat.vat_amount) - _dec(input_vat_returns.vat_amount) - _dec(input_credit_notes.vat_amount) + _dec(input_debit_notes.vat_amount)).quantize(_D2, ROUND_HALF_UP)

        vat_out_account_id = get_mapped_account_id(db, "acc_map_vat_out") or get_mapped_account_id(db, "acc_map_vat_output")
        vat_in_account_id = get_mapped_account_id(db, "acc_map_vat_in") or get_mapped_account_id(db, "acc_map_vat_input")
        if vat_out_account_id or vat_in_account_id:
            gl_params = {"start": start_date, "end": end_date}
            gl_branch_filter = branch_scope_filter_from_scope(branch_scope, "je.branch_id", gl_params)
            if vat_out_account_id:
                gl_output = db.execute(text(f"""
                    SELECT COALESCE(SUM(jl.credit - jl.debit), 0) AS amount
                    FROM journal_lines jl
                    JOIN journal_entries je ON je.id = jl.journal_entry_id
                    WHERE jl.account_id = :account_id
                      AND je.status = 'posted'
                      AND je.entry_date BETWEEN :start AND :end
                      {gl_branch_filter}
                """), {**gl_params, "account_id": vat_out_account_id}).scalar()
                net_output_vat = _dec(gl_output).quantize(_D2, ROUND_HALF_UP)
            if vat_in_account_id:
                gl_input = db.execute(text(f"""
                    SELECT COALESCE(SUM(jl.debit - jl.credit), 0) AS amount
                    FROM journal_lines jl
                    JOIN journal_entries je ON je.id = jl.journal_entry_id
                    WHERE jl.account_id = :account_id
                      AND je.status = 'posted'
                      AND je.entry_date BETWEEN :start AND :end
                      {gl_branch_filter}
                """), {**gl_params, "account_id": vat_in_account_id}).scalar()
                net_input_vat = _dec(gl_input).quantize(_D2, ROUND_HALF_UP)
        net_vat_payable = (net_output_vat - net_input_vat).quantize(_D2, ROUND_HALF_UP)

        return {
            **display_currency_fields(display_meta),
            "period": {"start": start_date, "end": end_date},
            "output_vat": {"taxable": str(_display_dec(net_output_taxable, display_meta)), "vat": str(_display_dec(net_output_vat, display_meta))},
            "input_vat": {"taxable": str(_display_dec(net_input_taxable, display_meta)), "vat": str(_display_dec(net_input_vat, display_meta))},
            "net_vat_payable": str(_display_dec(net_vat_payable, display_meta))
        }


# ==================== TAX AUDIT ====================

@router.get("/audit-report", response_model=Dict[str, Any], dependencies=[Depends(require_permission(["accounting.view", "taxes.view", "reports.view"]))])
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

        display_meta = resolve_display_currency(db, branch_scope)
        params = {"start": start_date, "end": end_date, "base_currency": display_meta["base_currency"]}
        branch_filter = branch_scope_filter_from_scope(branch_scope, "i.branch_id", params)
        taxable_base_sql = document_amount_base_sql("(COALESCE(i.subtotal, 0) - COALESCE(i.discount, 0))", "i")
        vat_base_sql = document_amount_base_sql("COALESCE(i.tax_amount, 0)", "i")

        results = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT i.id, i.invoice_number, i.invoice_date, i.invoice_type,
                p.name as party_name, p.tax_number,
                {taxable_base_sql} as taxable_amount,
                {vat_base_sql} as vat_amount
            FROM invoices i
            LEFT JOIN parties p ON i.party_id = p.id
            WHERE i.invoice_date BETWEEN :start AND :end
              AND COALESCE(i.tax_amount, 0) <> 0
              AND i.status NOT IN ('draft', 'cancelled')
              AND COALESCE(i.zatca_clearance_status, 'not_required') NOT IN ('pending_clearance', 'rejected')
              {branch_filter}
            ORDER BY i.invoice_date DESC
        """), params).fetchall()

        return {
            **display_currency_fields(display_meta),
            "period": {"start": start_date, "end": end_date},
            "items": [
                {
                    "id": r.id, "number": r.invoice_number, "date": r.invoice_date,
                    "type": r.invoice_type, "party": r.party_name, "tax_number": r.tax_number,
                    "taxable": display_money_str(r.taxable_amount or 0, display_meta),
                    "vat": display_money_str(r.vat_amount or 0, display_meta),
                }
                for r in results
            ],
        }


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

        # Aggregate at invoice level to respect header discounts
        current_vat = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT
                COALESCE(SUM(CASE
                    WHEN inv.invoice_type IN ('sales', 'sales_debit_note') THEN inv.vat_amount
                    WHEN inv.invoice_type IN ('sales_return', 'sales_credit_note') THEN -inv.vat_amount
                    ELSE 0
                END), 0) as output_vat,
                COALESCE(SUM(CASE
                    WHEN inv.invoice_type IN ('purchase', 'purchase_debit_note') THEN inv.vat_amount
                    WHEN inv.invoice_type IN ('purchase_return', 'purchase_credit_note') THEN -inv.vat_amount
                    ELSE 0
                END), 0) as input_vat
            FROM (
                SELECT
                    i.id,
                    i.invoice_type,
                    (COALESCE(i.tax_amount, 0) * COALESCE(i.exchange_rate, 1)) AS vat_amount
                FROM invoices i
                WHERE i.invoice_date >= :start AND i.invoice_date <= :end
                  AND i.status NOT IN ('draft', 'cancelled')
                  AND COALESCE(i.zatca_clearance_status, 'not_required') NOT IN ('pending_clearance', 'rejected')
                  AND i.invoice_type IN (
                      'sales', 'sales_return', 'sales_credit_note', 'sales_debit_note',
                      'purchase', 'purchase_return', 'purchase_credit_note', 'purchase_debit_note'
                  )
                  {vat_branch_filter}
            ) inv
        """), vat_params).fetchone()

        overdue_where = "WHERE status = 'filed' AND due_date < CURRENT_DATE"
        overdue_params = {}
        overdue_where += " " + branch_scope_filter_from_scope(branch_scope, "branch_id", overdue_params)
        overdue = db.execute(text(f"SELECT COUNT(*) FROM tax_returns {overdue_where}"), overdue_params).scalar() or 0  # noqa: sql-lint

        # ── Employee tax summary (withholding from payroll) ──
        emp_tax = {"total_employees": 0, "total_salary_tax": "0.00", "total_gosi": "0.00"}
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
                emp_tax["total_gosi"] = display_money_str(emp_row.total_gosi or 0, display_meta)
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
        taxable_base_sql = document_amount_base_sql("(COALESCE(i.subtotal, 0) - COALESCE(i.discount, 0))", "i")
        vat_base_sql = document_amount_base_sql("COALESCE(i.tax_amount, 0)", "i")

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
            JOIN branches b ON i.branch_id = b.id
            WHERE i.invoice_date BETWEEN :start AND :end
              AND i.status NOT IN ('draft', 'cancelled')
              AND COALESCE(i.tax_amount, 0) <> 0
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
                "output_vat": display_money_str(out, display_meta),
                "input_vat": display_money_str(inp, display_meta),
                "net_vat": display_money_str(net, display_meta),
                "taxable_sales": display_money_str(r.taxable_sales or 0, display_meta),
                "taxable_purchases": display_money_str(r.taxable_purchases or 0, display_meta),
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
                "output_vat": display_money_str(grand_output, display_meta),
                "input_vat": display_money_str(grand_input, display_meta),
                "net_vat": display_money_str(grand_output - grand_input, display_meta),
                "branch_count": len(result)
            }
        }


# ==================== EMPLOYEE TAX OBLIGATIONS ====================

@router.get("/employee-taxes", dependencies=[Depends(require_permission(["accounting.view", "taxes.view", "hr.view"]))], response_model=Dict[str, Any])
def get_employee_tax_obligations(
    request: Request,
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

        display_meta = resolve_display_currency(db, branch_scope)
        can_view_pii = has_pii_access(current_user)
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

            tax_id = emp.tax_id
            social_security = emp.social_security
            if not can_view_pii:
                tax_id = mask_pii(tax_id, visible_chars=4)
                social_security = mask_pii(social_security, visible_chars=4)

            employee_list.append({
                "employee_id": emp.employee_id,
                "employee_code": emp.employee_code,
                "employee_name": emp.employee_name,
                "tax_id": tax_id,
                "social_security": social_security,
                "pii_masked": not can_view_pii,
                "branch_id": emp.branch_id,
                "branch_name": emp.branch_name,
                "jurisdiction": jurisdiction,
                "department_name": emp.department_name,
                "payslip_count": emp.payslip_count,
                "total_gross": display_money_str(gross, display_meta),
                "total_basic": display_money_str(emp.total_basic or 0, display_meta),
                "total_allowances": display_money_str(_dec(emp.total_housing) + _dec(emp.total_transport) + _dec(emp.total_other_allowances), display_meta),
                "gosi_employee": display_money_str(gosi_emp, display_meta),
                "gosi_employer": display_money_str(gosi_empr, display_meta),
                "income_tax_rate": rate_str(tax_rate_dec),
                "income_tax_due": display_money_str(tax_due, display_meta),
                "total_deductions": display_money_str(emp.total_deductions or 0, display_meta),
                "total_net": display_money_str(emp.total_net or 0, display_meta),
            })

        return {
            **display_currency_fields(display_meta),
            "year": year,
            "branch_id": branch_scope["branch_id"],
            "employees": employee_list,
            "summary": {
                "total_employees": len(employee_list),
                "total_gross": display_money_str(total_gross_all, display_meta),
                "total_gosi_employee": display_money_str(total_gosi_emp, display_meta),
                "total_gosi_employer": display_money_str(total_gosi_empr, display_meta),
                "total_gosi_combined": display_money_str(total_gosi_emp + total_gosi_empr, display_meta),
            },
            "gosi_settings": {
                "employee_pct": rate_str(gosi.employee_share_pct) if gosi else "0.0000",
                "employer_pct": rate_str(gosi.employer_share_pct) if gosi else "0.0000",
                "max_salary": display_money_str(gosi.max_contributable_salary, display_meta) if gosi else "0.00",
            } if gosi else None
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error fetching employee tax obligations")
        raise HTTPException(**http_error(500, "internal_error", request))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# ██  Tax Filing Calendar  (TAX-002)
# ═══════════════════════════════════════════════════════════════
