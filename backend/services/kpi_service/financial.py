"""kpi_service.financial — split from monolithic kpi_service.py (T6.3)"""
from sqlalchemy import text
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional
import logging

logger = logging.getLogger(__name__)
from .common import (  # noqa: E402
    get_previous_period, build_branch_filter, kpi_item, ratio_status, _gl_sum, _gl_balance, _gl_balance_by_classification
)
from utils.accounting import get_base_currency  # noqa: E402
from .charts import (  # noqa: E402
    _build_ar_aging, _build_ap_aging, _build_financial_alerts
)


_D0 = Decimal("0")
_D2 = Decimal("0.01")
_D1 = Decimal("0.1")
_D100 = Decimal("100")


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0))
    except (InvalidOperation, TypeError, ValueError):
        return _D0


def _q(value: Any, places: Decimal = _D2) -> Decimal:
    return _dec(value).quantize(places, rounding=ROUND_HALF_UP)


def _decimal_text(value: Any, places: Decimal = _D2) -> str:
    return format(_q(value, places), "f")


def _ratio(numerator: Any, denominator: Any, places: Decimal = _D2) -> Decimal:
    denominator_dec = _dec(denominator)
    if denominator_dec <= 0:
        return _D0
    return _q(_dec(numerator) / denominator_dec, places)


def _percent(numerator: Any, denominator: Any) -> Decimal:
    denominator_dec = _dec(denominator)
    if denominator_dec <= 0:
        return _D0
    return _q((_dec(numerator) / denominator_dec) * _D100, _D1)


def get_financial_kpis(db, start_date: date, end_date: date,
                       branch_id: Optional[int] = None) -> dict:
    """KPIs for CFO / Accountant role."""
    prev_start, prev_end = get_previous_period(start_date, end_date)
    base_currency = get_base_currency(db) or "SAR"

    # Current Assets & Liabilities (balance as of end_date)
    current_assets = _dec(_gl_balance_by_classification(db, "current_asset", end_date, branch_id))
    if current_assets == 0:
        # Fallback: sum asset accounts with codes 1xxx
        current_assets = _dec(_gl_balance(db, "asset", end_date, branch_id))

    current_liabilities = abs(_dec(_gl_balance_by_classification(db, "current_liability", end_date, branch_id)))
    if current_liabilities == 0:
        current_liabilities = abs(_dec(_gl_balance(db, "liability", end_date, branch_id, debit_minus_credit=False)))

    # Inventory balance
    inventory_balance = _D0
    try:
        inv_branch_sql, inv_bp = build_branch_filter(branch_id)
        inv_result = db.execute(text("""
            SELECT COALESCE(SUM(jl.debit - jl.credit), 0)
            FROM journal_lines jl
            JOIN journal_entries je ON jl.journal_entry_id = je.id
            JOIN accounts a ON jl.account_id = a.id
            WHERE (a.account_code LIKE '14%' OR a.name ILIKE '%inventory%' OR a.name ILIKE '%مخزون%')
              AND je.entry_date <= :end_dt AND je.status = 'posted'
              {inv_branch_sql}
        """.format(inv_branch_sql=inv_branch_sql)), {"end_dt": end_date, **inv_bp}).scalar()
        inventory_balance = _dec(inv_result)
    except Exception:
        pass

    # Ratios
    current_ratio = _ratio(current_assets, current_liabilities)
    quick_ratio = _ratio(current_assets - inventory_balance, current_liabilities)

    # Total Debt & Equity
    total_debt = current_liabilities  # Simplified — should include long-term too
    equity = _dec(_gl_balance(db, "equity", end_date, branch_id, debit_minus_credit=False))
    debt_to_equity = _ratio(total_debt, equity)

    # Revenue & Margins
    revenue = _dec(_gl_sum(db, "revenue", start_date, end_date, branch_id, debit_minus_credit=False))
    cogs = _D0
    try:
        cogs_branch_sql, cogs_bp = build_branch_filter(branch_id)
        cogs_r = db.execute(text("""
            SELECT COALESCE(SUM(jl.debit - jl.credit), 0)
            FROM journal_lines jl JOIN journal_entries je ON jl.journal_entry_id = je.id
            JOIN accounts a ON jl.account_id = a.id
            WHERE a.account_type = 'expense' AND a.account_code LIKE '5%'
              AND je.entry_date BETWEEN :s AND :e AND je.status = 'posted'
              {cogs_branch_sql}
        """.format(cogs_branch_sql=cogs_branch_sql)), {"s": start_date, "e": end_date, **cogs_bp}).scalar()
        cogs = _dec(cogs_r)
    except Exception:
        pass

    expenses = _dec(_gl_sum(db, "expense", start_date, end_date, branch_id))
    gross_margin = _percent(revenue - cogs, revenue)
    net_margin = _percent(revenue - cogs - expenses, revenue)

    # Budget vs Actual
    budget_variance = _D0
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
            budget_variance = _percent(_dec(bv[1]) - _dec(bv[0]), bv[0])
    except Exception:
        pass

    # AR Aging
    ar_aging = _build_ar_aging(db, end_date, branch_id)

    # AP Aging
    ap_aging = _build_ap_aging(db, end_date, branch_id)

    # VAT Position
    vat_output = _D0
    vat_input = _D0
    try:
        vat_branch_sql, vat_bp = build_branch_filter(branch_id)
        vat_r = db.execute(text("""
            SELECT
                COALESCE(SUM(CASE WHEN jl.credit > 0 AND a.account_code LIKE '22%' THEN jl.credit ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN jl.debit > 0 AND a.account_code LIKE '15%' THEN jl.debit ELSE 0 END), 0)
            FROM journal_lines jl
            JOIN journal_entries je ON jl.journal_entry_id = je.id
            JOIN accounts a ON jl.account_id = a.id
            WHERE je.entry_date BETWEEN :s AND :e AND je.status = 'posted'
              {vat_branch_sql}
        """.format(vat_branch_sql=vat_branch_sql)), {"s": start_date, "e": end_date, **vat_bp}).fetchone()
        if vat_r:
            vat_output = _dec(vat_r[0])
            vat_input = _dec(vat_r[1])
    except Exception:
        pass
    vat_position = vat_output - vat_input

    # Zakat estimate (ZATCA method: equity minus fixed assets and intangibles × 2.5%)
    zakat_estimate = _D0
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
        fixed_assets_bal = _dec(fa_bal)

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
        intangibles_bal = _dec(intang_bal)

        zakat_base = max(_D0, equity - fixed_assets_bal - intangibles_bal)
        zakat_estimate = _q(zakat_base * Decimal("0.025"))
    except Exception:
        pass


    kpis = [
        kpi_item("current_ratio", "Current Ratio", "نسبة التداول", _decimal_text(current_ratio), "x",
                 benchmark="2.0", benchmark_source="IAS 1",
                 status=ratio_status(current_ratio, Decimal("2.0"), Decimal("1.0"))),
        kpi_item("quick_ratio", "Quick Ratio", "نسبة السيولة السريعة", _decimal_text(quick_ratio), "x",
                 benchmark="1.0", benchmark_source="IAS 1",
                 status=ratio_status(quick_ratio, Decimal("1.0"), Decimal("0.5"))),
        kpi_item("debt_to_equity", "Debt-to-Equity", "نسبة الدين إلى حقوق الملكية", _decimal_text(debt_to_equity), "x",
                 benchmark="1.5", benchmark_source="IAS 32",
                 status=ratio_status(debt_to_equity, Decimal("1.0"), Decimal("2.0"), higher_is_better=False)),
        kpi_item("gross_margin", "Gross Margin", "هامش الربح الإجمالي", _decimal_text(gross_margin, _D1), "%",
                 benchmark="30.0", benchmark_source="Industry Avg",
                 status=ratio_status(gross_margin, Decimal("30"), Decimal("15"))),
        kpi_item("net_margin", "Net Margin", "صافي هامش الربح", _decimal_text(net_margin, _D1), "%",
                 benchmark="15.0", benchmark_source="IAS 1",
                 status=ratio_status(net_margin, Decimal("15"), Decimal("5"))),
        kpi_item("budget_variance", "Budget vs Actual", "الانحراف عن الميزانية", _decimal_text(budget_variance, _D1), "%",
                 benchmark="0", benchmark_source="Internal",
                 status=ratio_status(abs(budget_variance), Decimal("5"), Decimal("15"), higher_is_better=False)),
        kpi_item("vat_position", "VAT Position", "موقف ضريبة القيمة المضافة", vat_position, base_currency),
        kpi_item("zakat_estimate", "Zakat Estimate", "تقدير الزكاة", zakat_estimate, base_currency,
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
