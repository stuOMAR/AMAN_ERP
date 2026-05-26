"""kpi_service.executive — split from monolithic kpi_service.py (T6.3)"""
from sqlalchemy import text
from datetime import date
from typing import Optional
import logging

logger = logging.getLogger(__name__)
from .common import (  # noqa: E402
    get_previous_period, build_branch_filter, kpi_item, calc_trend, calc_trend_inverse, ratio_status, _gl_sum, _gl_balance, _count_table
)
from .charts import (  # noqa: E402
    _build_revenue_expense_chart, _build_executive_alerts
)
from utils.accounting import get_base_currency  # noqa: E402


def get_executive_kpis(db, start_date: date, end_date: date,
                       branch_id: Optional[int] = None) -> dict:
    """KPIs for CEO / Executive role."""
    prev_start, prev_end = get_previous_period(start_date, end_date)
    base_currency = get_base_currency(db) or "SAR"

    # Revenue (credit - debit for revenue accounts)
    revenue = _gl_sum(db, "revenue", start_date, end_date, branch_id, debit_minus_credit=False)
    prev_revenue = _gl_sum(db, "revenue", prev_start, prev_end, branch_id, debit_minus_credit=False)

    # Expenses (debit - credit for expense accounts)
    expenses = _gl_sum(db, "expense", start_date, end_date, branch_id)
    prev_expenses = _gl_sum(db, "expense", prev_start, prev_end, branch_id)

    # COGS (expense accounts with code starting with 5)
    cogs = 0
    try:
        cogs_branch_sql, cogs_bp = build_branch_filter(branch_id)
        cogs_result = db.execute(text("""
            SELECT COALESCE(SUM(jl.debit - jl.credit), 0)
            FROM journal_lines jl
            JOIN journal_entries je ON jl.journal_entry_id = je.id
            JOIN accounts a ON jl.account_id = a.id
            WHERE a.account_type = 'expense' AND a.account_code LIKE '5%'
              AND je.entry_date BETWEEN :s AND :e AND je.status = 'posted'
              {cogs_branch_sql}
        """.format(cogs_branch_sql=cogs_branch_sql)), {"s": start_date, "e": end_date, **cogs_bp}).scalar()
        cogs = float(cogs_result or 0)
    except Exception:
        pass

    net_income = revenue - expenses - cogs
    prev_net = prev_revenue - prev_expenses
    profit_margin = (net_income / revenue * 100) if revenue > 0 else 0

    # EBITDA (Net Income + Interest + Tax + Depreciation + Amortization)
    # Simplified: Revenue - Operating Expenses (exclude interest, tax, depreciation)
    ebitda = net_income  # Simplified — full version would exclude specific accounts

    # Operating Expense Ratio
    opex_ratio = (expenses / revenue * 100) if revenue > 0 else 0

    # Cash & Bank Balance (converted to base currency)
    cash_balance = 0
    try:
        cash_branch_sql, cash_bp = build_branch_filter(branch_id, table_alias="ta")
        cash_result = db.execute(text(f"""
            SELECT COALESCE(SUM(ta.current_balance * COALESCE(c.current_rate, 1)), 0)
            FROM treasury_accounts ta
            LEFT JOIN currencies c ON ta.currency = c.code
            WHERE ta.is_active = true {cash_branch_sql}
        """), cash_bp).scalar()
        cash_balance = float(cash_result or 0)
    except Exception:
        pass

    # DSO (Days Sales Outstanding) = AR / (Revenue / days_in_period)
    ar_balance = _gl_balance(db, "receivable", end_date, branch_id)
    days_in_period = max((end_date - start_date).days, 1)
    daily_revenue = revenue / days_in_period if days_in_period > 0 else 0
    dso = ar_balance / daily_revenue if daily_revenue > 0 else 0

    # DPO (Days Payable Outstanding) = AP / (COGS / days_in_period)
    ap_balance = _gl_balance(db, "payable", end_date, branch_id, debit_minus_credit=False)
    daily_cogs = cogs / days_in_period if days_in_period > 0 else 0
    dpo = ap_balance / daily_cogs if daily_cogs > 0 else 0

    # Headcount
    headcount = _count_table(db, "employees", extra_where="status = 'active'")

    # Revenue trend
    rev_trend = calc_trend(revenue, prev_revenue)
    exp_trend = calc_trend_inverse(expenses, prev_expenses)
    profit_trend = calc_trend(net_income, prev_net)

    kpis = [
        kpi_item("revenue", "Revenue", "الإيرادات", revenue, base_currency,
                 rev_trend[0], rev_trend[1], rev_trend[2]),
        kpi_item("revenue_growth", "Revenue Growth", "نمو الإيرادات", rev_trend[0].rstrip('%'), "%",
                 rev_trend[0], rev_trend[1], rev_trend[2], benchmark=5.0, benchmark_source="Industry Avg"),
        kpi_item("net_profit_margin", "Net Profit Margin", "هامش صافي الربح", profit_margin, "%",
                 profit_trend[0], profit_trend[1], profit_trend[2],
                 benchmark=15.0, benchmark_source="IAS 1",
                 status=ratio_status(profit_margin, 15, 5)),
        kpi_item("ebitda", "EBITDA", "الأرباح قبل الفوائد والضرائب والإهلاك", ebitda, base_currency),
        kpi_item("opex_ratio", "Operating Expense Ratio", "نسبة المصاريف التشغيلية", opex_ratio, "%",
                 exp_trend[0], exp_trend[1], not exp_trend[2],
                 benchmark=70.0, benchmark_source="Industry Avg",
                 status=ratio_status(opex_ratio, 60, 80, higher_is_better=False)),
        kpi_item("cash_balance", "Cash & Bank Balance", "الرصيد النقدي والبنكي", cash_balance, base_currency),
        kpi_item("dso", "Days Sales Outstanding", "أيام تحصيل المبيعات", dso, "days",
                 status=ratio_status(dso, 30, 60, higher_is_better=False),
                 benchmark=30, benchmark_source="Best Practice"),
        kpi_item("dpo", "Days Payable Outstanding", "أيام سداد المشتريات", dpo, "days",
                 benchmark=45, benchmark_source="Best Practice"),
        kpi_item("headcount", "Headcount", "عدد الموظفين", headcount, ""),
    ]

    # Charts
    charts = _build_revenue_expense_chart(db, start_date, end_date, branch_id)

    # Alerts
    alerts = _build_executive_alerts(db, branch_id)

    return {"role": "executive", "kpis": kpis, "charts": charts, "alerts": alerts}


# ═══════════════════════════════════════════════════════════════════════════════
# Financial Dashboard KPIs (CFO / Accountant)
# ═══════════════════════════════════════════════════════════════════════════════

