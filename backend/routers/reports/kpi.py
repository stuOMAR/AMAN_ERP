"""Reports sub-router — split from monolithic reports.py (T6.3).

Mounted under the parent /reports prefix via reports/__init__.py.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from typing import Any, Dict
from decimal import Decimal, ROUND_HALF_UP
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.permissions import branch_scope_filter_from_scope, require_permission, resolve_branch_scope

logger = logging.getLogger(__name__)
router = APIRouter()
_D1 = Decimal("0.1")
_D2 = Decimal("0.01")


def _q_money(value) -> Decimal:
    return Decimal(str(value if value is not None else 0)).quantize(_D2, rounding=ROUND_HALF_UP)


def _money_str(value) -> str:
    return format(_q_money(value), "f")


def _ratio_str(value, places: Decimal = _D2) -> str:
    return format(Decimal(str(value if value is not None else 0)).quantize(places, rounding=ROUND_HALF_UP), "f")


def _pct_change(current: Decimal, previous: Decimal) -> str:
    if previous == 0:
        return "0.0"
    return _ratio_str(((current - previous) / previous.copy_abs()) * Decimal("100"), _D1)

@router.get("/kpi/dashboard", dependencies=[Depends(require_permission("reports.view"))], response_model=Dict[str, Any])
def get_kpi_dashboard(current_user=Depends(get_current_user)):
    """لوحة مؤشرات الأداء الرئيسية"""
    db = get_db_connection(current_user.company_id)
    try:
        branch_scope = resolve_branch_scope(current_user, None)
        revenue = Decimal("0")
        previous_revenue = Decimal("0")
        expenses = Decimal("0")
        accounts_receivable = Decimal("0")
        accounts_payable = Decimal("0")
        cash_balance = Decimal("0")
        inventory_value = Decimal("0")
        inventory_items = 0
        employee_count = 0
        total_employees = 0

        # Revenue KPI (with exchange_rate conversion)
        rev_params: Dict[str, Any] = {}
        rev_branch_filter = branch_scope_filter_from_scope(branch_scope, "branch_id", rev_params)
        last_rev_params: Dict[str, Any] = {}
        last_rev_branch_filter = branch_scope_filter_from_scope(
            branch_scope,
            "branch_id",
            last_rev_params,
            branch_param="last_branch_id",
            branches_param="last_allowed_branch_ids",
        )
        for key, value in last_rev_params.items():
            rev_params[key] = value
        rev = db.execute(text(f"""
            SELECT COALESCE(SUM(total * COALESCE(exchange_rate, 1)), 0) as current_month,
                   (SELECT COALESCE(SUM(total * COALESCE(exchange_rate, 1)), 0) FROM invoices
                    WHERE invoice_type = 'sales' AND status != 'cancelled'
                      AND invoice_date >= date_trunc('month', CURRENT_DATE - INTERVAL '1 month')
                      AND invoice_date < date_trunc('month', CURRENT_DATE)
                      {last_rev_branch_filter}) as last_month
            FROM invoices
            WHERE invoice_type = 'sales' AND status != 'cancelled'
              AND invoice_date >= date_trunc('month', CURRENT_DATE)
              {rev_branch_filter}
        """), rev_params).fetchone()
        if rev:
            r = dict(rev._mapping)
            revenue = _q_money(r.get("current_month", 0))
            previous_revenue = _q_money(r.get("last_month", 0))

        # Expenses KPI
        exp_params: Dict[str, Any] = {}
        exp_branch_filter = branch_scope_filter_from_scope(branch_scope, "branch_id", exp_params)
        exp = db.execute(text(f"""
            SELECT COALESCE(SUM(total_amount), 0) as current_month
            FROM expenses WHERE expense_date >= date_trunc('month', CURRENT_DATE)
            {exp_branch_filter}
        """), exp_params).fetchone()
        expenses = _q_money(dict(exp._mapping).get("current_month", 0)) if exp else Decimal("0")

        # Outstanding receivables (converted to base)
        ar_params: Dict[str, Any] = {}
        ar_branch_filter = branch_scope_filter_from_scope(branch_scope, "branch_id", ar_params)
        ar = db.execute(text(f"""
            SELECT COALESCE(SUM((total - COALESCE(paid_amount, 0)) * COALESCE(exchange_rate, 1)), 0) as total
            FROM invoices WHERE status IN ('unpaid', 'partial') AND invoice_type = 'sales'
            {ar_branch_filter}
        """), ar_params).fetchone()
        accounts_receivable = _q_money(dict(ar._mapping).get("total", 0)) if ar else Decimal("0")

        # Outstanding payables (converted to base)
        ap_params: Dict[str, Any] = {}
        ap_branch_filter = branch_scope_filter_from_scope(branch_scope, "branch_id", ap_params)
        ap = db.execute(text(f"""
            SELECT COALESCE(SUM((total - COALESCE(paid_amount, 0)) * COALESCE(exchange_rate, 1)), 0) as total
            FROM invoices WHERE status IN ('unpaid', 'partial') AND invoice_type = 'purchase'
            {ap_branch_filter}
        """), ap_params).fetchone()
        accounts_payable = _q_money(dict(ap._mapping).get("total", 0)) if ap else Decimal("0")

        # Cash balance — pulled from GL (journal_lines) using company_settings
        # acc_map_cash_main + acc_map_bank so the KPI always matches the TB.
        cash_params: Dict[str, Any] = {}
        cash_branch_filter = branch_scope_filter_from_scope(branch_scope, "je.branch_id", cash_params)
        cash = db.execute(text(f"""
            WITH cash_accs AS (
                SELECT CAST(setting_value AS INTEGER) AS account_id
                FROM company_settings
                WHERE setting_key IN ('acc_map_cash_main', 'acc_map_bank')
                  AND setting_value ~ '^[0-9]+$'
            )
            SELECT COALESCE(SUM(jl.debit - jl.credit), 0) AS balance
            FROM journal_lines jl
            JOIN journal_entries je ON je.id = jl.journal_entry_id
            WHERE jl.account_id IN (SELECT account_id FROM cash_accs)
              AND je.status = 'posted'
              {cash_branch_filter}
        """), cash_params).fetchone()
        cash_balance = _q_money(dict(cash._mapping).get("balance", 0)) if cash else Decimal("0")

        # Inventory value (using cost_price from products)
        inv = db.execute(text("""
            SELECT COALESCE(SUM(i.quantity * p.cost_price), 0) as total_value,
                   COUNT(DISTINCT p.id) as total_items
            FROM products p
            LEFT JOIN inventory i ON i.product_id = p.id
            WHERE p.is_active = TRUE
        """)).fetchone()
        if inv:
            d = dict(inv._mapping)
            inventory_value = _q_money(d.get("total_value", 0))
            inventory_items = int(d.get("total_items", 0))

        # HR headcount
        hr = db.execute(text("""
            SELECT COUNT(*) as total, COUNT(CASE WHEN status = 'active' THEN 1 END) as active
            FROM employees
        """)).fetchone()
        if hr:
            d = dict(hr._mapping)
            total_employees = int(d.get("total", 0))
            employee_count = int(d.get("active", 0))

        net_income = revenue - expenses
        current_assets = cash_balance + accounts_receivable + inventory_value
        profit_margin = (net_income / revenue * Decimal("100")) if revenue != 0 else Decimal("0")
        current_ratio = (current_assets / accounts_payable) if accounts_payable != 0 else Decimal("0")
        cash_ratio = (cash_balance / accounts_payable) if accounts_payable != 0 else Decimal("0")
        ar_turnover = (revenue / accounts_receivable) if accounts_receivable != 0 else Decimal("0")

        return {
            "revenue": _money_str(revenue),
            "revenue_previous": _money_str(previous_revenue),
            "revenue_change": _pct_change(revenue, previous_revenue),
            "expenses": _money_str(expenses),
            "accounts_receivable": _money_str(accounts_receivable),
            "accounts_payable": _money_str(accounts_payable),
            "cash_balance": _money_str(cash_balance),
            "inventory_value": _money_str(inventory_value),
            "inventory_items": inventory_items,
            "employee_count": employee_count,
            "employee_total": total_employees,
            "financial_ratios": {
                "net_income": _money_str(net_income),
                "profit_margin": _ratio_str(profit_margin, _D1),
                "current_ratio": _ratio_str(current_ratio),
                "cash_ratio": _ratio_str(cash_ratio),
                "ar_turnover": _ratio_str(ar_turnover, _D1),
            },
        }
    except Exception as e:
        logger.error(f"KPI Dashboard error: {e}")
        return {}
    finally:
        db.close()


# ============================================================
#   10 INDUSTRY-SPECIFIC REPORT ENDPOINTS
#   تقارير صناعية متخصصة ببيانات حقيقية من قاعدة البيانات
# ============================================================
