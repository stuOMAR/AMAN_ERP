"""kpi_service.financial — split from monolithic kpi_service.py (T6.3)"""
from sqlalchemy import text
from datetime import date, timedelta
from typing import Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)
from .common import (
    get_previous_period, build_branch_filter, kpi_item, ratio_status, _gl_sum, _gl_balance, _gl_balance_by_classification
)
from .charts import (
    _build_ar_aging, _build_ap_aging, _build_financial_alerts
)


def get_financial_kpis(db, start_date: date, end_date: date,
                       branch_id: Optional[int] = None) -> dict:
    """KPIs for CFO / Accountant role."""
    prev_start, prev_end = get_previous_period(start_date, end_date)

    # Current Assets & Liabilities (balance as of end_date)
    current_assets = _gl_balance_by_classification(db, "current_asset", end_date, branch_id)
    if current_assets == 0:
        # Fallback: sum asset accounts with codes 1xxx
        current_assets = _gl_balance(db, "asset", end_date, branch_id)

    current_liabilities = abs(_gl_balance_by_classification(db, "current_liability", end_date, branch_id))
    if current_liabilities == 0:
        current_liabilities = abs(_gl_balance(db, "liability", end_date, branch_id, debit_minus_credit=False))

    # Inventory balance
    inventory_balance = 0
    try:
        inv_result = db.execute(text("""
            SELECT COALESCE(SUM(jl.debit - jl.credit), 0)
            FROM journal_lines jl
            JOIN journal_entries je ON jl.journal_entry_id = je.id
            JOIN accounts a ON jl.account_id = a.id
            WHERE (a.account_code LIKE '14%' OR a.name ILIKE '%inventory%' OR a.name ILIKE '%مخزون%')
              AND je.entry_date <= :end_dt AND je.status = 'posted'
        """), {"end_dt": end_date}).scalar()
        inventory_balance = float(inv_result or 0)
    except Exception:
        pass

    # Ratios
    current_ratio = current_assets / current_liabilities if current_liabilities > 0 else 0
    quick_ratio = (current_assets - inventory_balance) / current_liabilities if current_liabilities > 0 else 0

    # Total Debt & Equity
    total_debt = current_liabilities  # Simplified — should include long-term too
    equity = _gl_balance(db, "equity", end_date, branch_id, debit_minus_credit=False)
    debt_to_equity = total_debt / equity if equity > 0 else 0

    # Revenue & Margins
    revenue = _gl_sum(db, "revenue", start_date, end_date, branch_id, debit_minus_credit=False)
    cogs = 0
    try:
        cogs_r = db.execute(text("""
            SELECT COALESCE(SUM(jl.debit - jl.credit), 0)
            FROM journal_lines jl JOIN journal_entries je ON jl.journal_entry_id = je.id
            JOIN accounts a ON jl.account_id = a.id
            WHERE a.account_type = 'expense' AND a.account_code LIKE '5%'
              AND je.entry_date BETWEEN :s AND :e AND je.status = 'posted'
        """), {"s": start_date, "e": end_date}).scalar()
        cogs = float(cogs_r or 0)
    except Exception:
        pass

    expenses = _gl_sum(db, "expense", start_date, end_date, branch_id)
    gross_margin = ((revenue - cogs) / revenue * 100) if revenue > 0 else 0
    net_margin = ((revenue - cogs - expenses) / revenue * 100) if revenue > 0 else 0

    # Budget vs Actual
    budget_variance = 0
    try:
        bv = db.execute(text("""
            SELECT
                COALESCE(SUM(bi.planned_amount), 0) as budgeted,
                COALESCE(SUM(bi.actual_amount), 0) as actual
            FROM budget_items bi
            JOIN budgets b ON bi.budget_id = b.id
            WHERE b.status = 'active'
        """)).fetchone()
        if bv and bv[0] > 0:
            budget_variance = ((bv[1] - bv[0]) / bv[0]) * 100
    except Exception:
        pass

    # AR Aging
    ar_aging = _build_ar_aging(db, end_date, branch_id)

    # AP Aging
    ap_aging = _build_ap_aging(db, end_date, branch_id)

    # VAT Position
    vat_output = 0
    vat_input = 0
    try:
        vat_r = db.execute(text("""
            SELECT
                COALESCE(SUM(CASE WHEN jl.credit > 0 AND a.account_code LIKE '22%' THEN jl.credit ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN jl.debit > 0 AND a.account_code LIKE '15%' THEN jl.debit ELSE 0 END), 0)
            FROM journal_lines jl
            JOIN journal_entries je ON jl.journal_entry_id = je.id
            JOIN accounts a ON jl.account_id = a.id
            WHERE je.entry_date BETWEEN :s AND :e AND je.status = 'posted'
        """), {"s": start_date, "e": end_date}).fetchone()
        if vat_r:
            vat_output = float(vat_r[0] or 0)
            vat_input = float(vat_r[1] or 0)
    except Exception:
        pass
    vat_position = vat_output - vat_input

    # Zakat estimate (ZATCA method: equity minus fixed assets and intangibles × 2.5%)
    zakat_estimate = 0
    try:
        try:
            db.rollback()
        except Exception:
            pass
        branch_sql_z, bp_z = build_branch_filter(branch_id)
        # Fixed assets (property/plant/equipment — non-zakatable)
        fa_bal = db.execute(text(f"""
            SELECT COALESCE(SUM(jl.debit - jl.credit), 0)
            FROM journal_lines jl
            JOIN journal_entries je ON jl.journal_entry_id = je.id
            JOIN accounts a ON jl.account_id = a.id
            WHERE a.account_type = 'asset'
              AND (
                a.account_code LIKE '12%%' OR a.account_code LIKE '15%%' OR a.account_code LIKE '16%%'
                OR a.name LIKE '%%أصول ثابتة%%' OR a.name LIKE '%%معدات%%' OR a.name LIKE '%%آلات%%'
                OR a.name LIKE '%%مباني%%' OR a.name LIKE '%%سيارات%%' OR a.name LIKE '%%أثاث%%'
                OR a.name_en ILIKE '%%fixed asset%%' OR a.name_en ILIKE '%%equipment%%'
                OR a.name_en ILIKE '%%building%%' OR a.name_en ILIKE '%%vehicle%%'
                OR a.name_en ILIKE '%%furniture%%' OR a.name_en ILIKE '%%depreciation%%'
              )
              AND je.entry_date <= :end_dt AND je.status = 'posted'
              {branch_sql_z}
        """), {"end_dt": end_date, **bp_z}).scalar()
        fixed_assets_bal = float(fa_bal or 0)

        # Intangible assets (goodwill/IP — non-zakatable)
        intang_bal = db.execute(text(f"""
            SELECT COALESCE(SUM(jl.debit - jl.credit), 0)
            FROM journal_lines jl
            JOIN journal_entries je ON jl.journal_entry_id = je.id
            JOIN accounts a ON jl.account_id = a.id
            WHERE a.account_type = 'asset'
              AND (
                a.account_code LIKE '18%%'
                OR a.name LIKE '%%شهرة%%' OR a.name LIKE '%%براءة%%'
                OR a.name LIKE '%%رخصة%%' OR a.name LIKE '%%غير ملموس%%'
                OR a.name_en ILIKE '%%goodwill%%' OR a.name_en ILIKE '%%intangible%%'
                OR a.name_en ILIKE '%%patent%%' OR a.name_en ILIKE '%%trademark%%'
              )
              AND je.entry_date <= :end_dt AND je.status = 'posted'
              {branch_sql_z}
        """), {"end_dt": end_date, **bp_z}).scalar()
        intangibles_bal = float(intang_bal or 0)

        zakat_base = max(0.0, equity - fixed_assets_bal - intangibles_bal)
        zakat_estimate = zakat_base * 0.025
    except Exception:
        pass

    prev_current_ratio = 0  # Would need prev period balance — simplified

    kpis = [
        kpi_item("current_ratio", "Current Ratio", "نسبة التداول", current_ratio, "x",
                 benchmark=2.0, benchmark_source="IAS 1",
                 status=ratio_status(current_ratio, 2.0, 1.0)),
        kpi_item("quick_ratio", "Quick Ratio", "نسبة السيولة السريعة", quick_ratio, "x",
                 benchmark=1.0, benchmark_source="IAS 1",
                 status=ratio_status(quick_ratio, 1.0, 0.5)),
        kpi_item("debt_to_equity", "Debt-to-Equity", "نسبة الدين إلى حقوق الملكية", debt_to_equity, "x",
                 benchmark=1.5, benchmark_source="IAS 32",
                 status=ratio_status(debt_to_equity, 1.0, 2.0, higher_is_better=False)),
        kpi_item("gross_margin", "Gross Margin", "هامش الربح الإجمالي", gross_margin, "%",
                 benchmark=30.0, benchmark_source="Industry Avg",
                 status=ratio_status(gross_margin, 30, 15)),
        kpi_item("net_margin", "Net Margin", "صافي هامش الربح", net_margin, "%",
                 benchmark=15.0, benchmark_source="IAS 1",
                 status=ratio_status(net_margin, 15, 5)),
        kpi_item("budget_variance", "Budget vs Actual", "الانحراف عن الميزانية", budget_variance, "%",
                 benchmark=0, benchmark_source="Internal",
                 status=ratio_status(abs(budget_variance), 5, 15, higher_is_better=False)),
        kpi_item("vat_position", "VAT Position", "موقف ضريبة القيمة المضافة", vat_position, "SAR"),
        kpi_item("zakat_estimate", "Zakat Estimate", "تقدير الزكاة", zakat_estimate, "SAR",
                 benchmark_source="GAZT"),
    ]

    charts = [
        {"id": "ar_aging", "type": "bar", "title": "AR Aging", "title_ar": "أعمار الذمم المدينة", "data": ar_aging},
        {"id": "ap_aging", "type": "bar", "title": "AP Aging", "title_ar": "أعمار الذمم الدائنة", "data": ap_aging},
    ]

    alerts = _build_financial_alerts(db, current_ratio, quick_ratio, budget_variance, branch_id)

    return {"role": "financial", "kpis": kpis, "charts": charts, "alerts": alerts}


# ═══════════════════════════════════════════════════════════════════════════════
# Sales Dashboard KPIs
# ═══════════════════════════════════════════════════════════════════════════════

