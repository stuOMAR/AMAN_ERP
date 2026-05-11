"""
AMAN ERP - Industry KPI Service
خدمة حساب مؤشرات الأداء حسب القطاع

Provides industry-specific KPIs for 7 sectors:
1. Retail (تجزئة)
2. F&B (مطاعم وأغذية)
3. Manufacturing (تصنيع)
4. Construction (مقاولات)
5. Services (خدمات)
6. Wholesale (جملة)
7. General (عام)

Standards: NRF, NRA/USALI, APICS/ISO 9001, PMI PMBOK, AICPA, DSCSA, IFRS/IAS
"""

from sqlalchemy import text
from datetime import date
from typing import Optional
import logging

from services.kpi_service import (
    kpi_item, calc_trend, ratio_status,
    build_branch_filter, get_previous_period,
    _gl_sum, _gl_balance, _gl_balance_by_classification, _count_table, _sum_column
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Industry Router — detects company industry and returns appropriate KPIs
# ═══════════════════════════════════════════════════════════════════════════════

def get_industry_kpis(db, company_id: str, start_date: date, end_date: date,
                      branch_id: Optional[int] = None) -> dict:
    """Route to the correct industry KPI function based on company settings."""
    industry = _detect_industry(db, company_id)

    dispatchers = {
        "retail": get_retail_kpis,
        "food_and_beverage": get_fnb_kpis,
        "f&b": get_fnb_kpis,
        "restaurant": get_fnb_kpis,
        "manufacturing": get_manufacturing_industry_kpis,
        "construction": get_construction_kpis,
        "services": get_services_kpis,
        "wholesale": get_wholesale_kpis,
        "pharmacy": get_retail_kpis,       # Pharmacy uses retail KPIs + stock turnover
        "workshop": get_services_kpis,     # Workshop uses services KPIs
        "ecommerce": get_retail_kpis,      # E-commerce uses retail KPIs
        "logistics": get_wholesale_kpis,   # Logistics uses wholesale KPIs (CCC, DSO, DPO)
        "agriculture": get_general_kpis,   # Agriculture uses general KPIs
        "general": get_general_kpis,
    }

    handler = dispatchers.get(industry.lower(), get_general_kpis)
    result = handler(db, start_date, end_date, branch_id)
    result["industry"] = industry
    return result


def _detect_industry(db, company_id: str) -> str:
    """Detect industry type from company_settings or system_companies."""
    try:
        # Try company_settings first
        r = db.execute(text("""
            SELECT setting_value FROM company_settings
            WHERE setting_key = 'industry_type'
        """)).scalar()
        if r:
            return str(r).strip().lower()
    except Exception:
        pass

    try:
        # Fallback to system db — industry_templates
        from database import engine
        with engine.connect() as sys_db:
            r = sys_db.execute(text("""
                SELECT it.industry_key FROM system_companies sc
                LEFT JOIN industry_templates it ON sc.template_id = it.id
                WHERE sc.company_id = :cid
            """), {"cid": company_id}).scalar()
            if r:
                return str(r).strip().lower()
    except Exception:
        pass

    return "general"


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Retail — التجزئة
# ═══════════════════════════════════════════════════════════════════════════════

def get_retail_kpis(db, start_date: date, end_date: date,
                    branch_id: Optional[int] = None) -> dict:
    """Retail-specific KPIs. Reference: NRF + IFRS 15."""
    prev_start, prev_end = get_previous_period(start_date, end_date)
    branch_sql, bp = build_branch_filter(branch_id)

    # Total Sales (period)
    sales = _sum_column(db, "invoices", "total", branch_id, "invoice_date", start_date, end_date,
                        extra_where="invoice_type = 'sales' AND status != 'cancelled'")
    prev_sales = _sum_column(db, "invoices", "total", branch_id, "invoice_date", prev_start, prev_end,
                              extra_where="invoice_type = 'sales' AND status != 'cancelled'")
    sales_growth_trend = calc_trend(sales, prev_sales)

    # Transactions
    tx_count = _count_table(db, "invoices", branch_id, "invoice_date", start_date, end_date,
                            extra_where="invoice_type = 'sales' AND status != 'cancelled'")
    # Also include POS
    pos_sales = _sum_column(db, "pos_orders", "total_amount", branch_id, "order_date", start_date, end_date,
                            extra_where="status = 'paid'")
    pos_count = _count_table(db, "pos_orders", branch_id, "order_date", start_date, end_date,
                             extra_where="status = 'paid'")
    total_sales = sales + pos_sales
    total_tx = tx_count + pos_count

    # ATV (Average Transaction Value)
    atv = total_sales / total_tx if total_tx > 0 else 0

    # Inventory Valuation
    inv_valuation = 0
    try:
        iv = db.execute(text("""
            SELECT COALESCE(SUM(i.quantity * COALESCE(p.cost_price, 0)), 0)
            FROM inventory i JOIN products p ON i.product_id = p.id
        """)).scalar()
        inv_valuation = float(iv or 0)
    except Exception:
        pass

    # COGS
    cogs = 0
    try:
        cr = db.execute(text("""
            SELECT COALESCE(SUM(jl.debit - jl.credit), 0)
            FROM journal_lines jl JOIN journal_entries je ON jl.journal_entry_id = je.id
            JOIN accounts a ON jl.account_id = a.id
            WHERE (a.account_type = 'expense' AND a.account_code LIKE '5%')
              AND je.entry_date BETWEEN :s AND :e AND je.status = 'posted'
        """), {"s": start_date, "e": end_date}).scalar()
        cogs = float(cr or 0)
    except Exception:
        pass

    # GMROI = Gross Margin / Avg Inventory Cost
    gross_margin_value = total_sales - cogs
    gmroi = gross_margin_value / inv_valuation if inv_valuation > 0 else 0

    # Sell-Through Rate = Units Sold / (Units On Hand + Units Sold) × 100
    units_sold = 0
    units_on_hand = 0
    try:
        us = db.execute(text("""
            SELECT COALESCE(SUM(quantity), 0) FROM invoice_lines il
            JOIN invoices i ON il.invoice_id = i.id
            WHERE i.invoice_type = 'sales' AND i.invoice_date BETWEEN :s AND :e AND i.status != 'cancelled'
        """), {"s": start_date, "e": end_date}).scalar()
        units_sold = float(us or 0)
    except Exception:
        pass
    try:
        oh = db.execute(text("SELECT COALESCE(SUM(quantity), 0) FROM inventory")).scalar()
        units_on_hand = float(oh or 0)
    except Exception:
        pass
    sell_through = (units_sold / (units_on_hand + units_sold) * 100) if (units_on_hand + units_sold) > 0 else 0

    # Out-of-Stock Rate
    total_active_skus = _count_table(db, "products", extra_where="is_active = true AND product_type != 'service'")
    oos_skus = 0
    try:
        oos = db.execute(text("""
            SELECT COUNT(DISTINCT p.id) FROM products p
            LEFT JOIN inventory i ON p.id = i.product_id
            WHERE p.is_active = true AND p.product_type != 'service'
              AND (i.quantity IS NULL OR i.quantity <= 0)
        """)).scalar()
        oos_skus = int(oos or 0)
    except Exception:
        pass
    oos_rate = (oos_skus / total_active_skus * 100) if total_active_skus > 0 else 0

    # Customer Return Rate (repeat customers)
    repeat_customers = 0
    total_customers = 0
    try:
        rc = db.execute(text("""
            SELECT
                COUNT(DISTINCT CASE WHEN order_count > 1 THEN customer_id END),
                COUNT(DISTINCT customer_id)
            FROM (
                SELECT customer_id, COUNT(*) as order_count
                FROM invoices
                WHERE invoice_type = 'sales' AND invoice_date BETWEEN :s AND :e AND status != 'cancelled'
                GROUP BY customer_id
            ) sub
        """), {"s": start_date, "e": end_date}).fetchone()
        if rc:
            repeat_customers = int(rc[0] or 0)
            total_customers = int(rc[1] or 0)
    except Exception:
        pass
    customer_return_rate = (repeat_customers / total_customers * 100) if total_customers > 0 else 0

    kpis = [
        kpi_item("total_sales", "Total Sales", "إجمالي المبيعات", total_sales, "SAR",
                 sales_growth_trend[0], sales_growth_trend[1], sales_growth_trend[2]),
        kpi_item("sssg", "Sales Growth", "نمو المبيعات", float(sales_growth_trend[0].rstrip('%')) if '%' in sales_growth_trend[0] else 0, "%",
                 benchmark=3.0, benchmark_source="NRF"),
        kpi_item("atv", "Avg Transaction Value", "متوسط قيمة العملية", atv, "SAR"),
        kpi_item("gmroi", "GMROI", "العائد الإجمالي على الاستثمار في المخزون", gmroi, "x",
                 benchmark=3.0, benchmark_source="NRF",
                 status=ratio_status(gmroi, 3.0, 1.5)),
        kpi_item("sell_through", "Sell-Through Rate", "معدل البيع", sell_through, "%",
                 benchmark=80.0, benchmark_source="Retail Benchmark",
                 status=ratio_status(sell_through, 80, 50)),
        kpi_item("oos_rate", "Out-of-Stock Rate", "نسبة نفاد المخزون", oos_rate, "%",
                 benchmark=3.0, benchmark_source="NRF",
                 status=ratio_status(oos_rate, 3, 8, higher_is_better=False)),
        kpi_item("customer_return_rate", "Repeat Customer Rate", "معدل العملاء المتكررين", customer_return_rate, "%",
                 benchmark=30.0, benchmark_source="Retail Benchmark",
                 status=ratio_status(customer_return_rate, 30, 15)),
        kpi_item("total_transactions", "Transactions", "عدد العمليات", total_tx, ""),
    ]

    charts = []
    alerts = []
    if oos_rate > 5:
        alerts.append({"severity": "high", "code": "HIGH_OOS",
                        "message": i18n_message("kpi_out_of_stock_rate", request),
                        "message_ar": f"نسبة نفاد المخزون {oos_rate:.1f}% — {oos_skus} صنف",
                        "link": "/stock/products?filter=out_of_stock"})

    return {"industry": "retail", "kpis": kpis, "charts": charts, "alerts": alerts}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Food & Beverage — مطاعم وأغذية
# ═══════════════════════════════════════════════════════════════════════════════

def get_fnb_kpis(db, start_date: date, end_date: date,
                 branch_id: Optional[int] = None) -> dict:
    """F&B KPIs. Reference: NRA + USALI Standards."""
    branch_sql, bp = build_branch_filter(branch_id)

    # Total Revenue (POS + Invoices)
    pos_revenue = _sum_column(db, "pos_orders", "total_amount", branch_id, "order_date",
                              start_date, end_date, extra_where="status = 'paid'")
    invoice_revenue = _sum_column(db, "invoices", "total", branch_id, "invoice_date",
                                   start_date, end_date, extra_where="invoice_type = 'sales' AND status != 'cancelled'")
    total_revenue = pos_revenue + invoice_revenue

    # Food Cost
    food_cost = 0
    try:
        fc = db.execute(text("""
            SELECT COALESCE(SUM(jl.debit - jl.credit), 0)
            FROM journal_lines jl JOIN journal_entries je ON jl.journal_entry_id = je.id
            JOIN accounts a ON jl.account_id = a.id
            WHERE (a.account_type = 'expense' AND a.account_code LIKE '5%')
              AND je.entry_date BETWEEN :s AND :e AND je.status = 'posted'
        """), {"s": start_date, "e": end_date}).scalar()
        food_cost = float(fc or 0)
    except Exception:
        pass
    food_cost_pct = (food_cost / total_revenue * 100) if total_revenue > 0 else 0

    # Labor Cost (join payroll_entries via period_id to payroll_periods)
    labor_cost = 0
    try:
        lc = db.execute(text("""
            SELECT COALESCE(SUM(pe.net_salary), 0)
            FROM payroll_entries pe
            JOIN payroll_periods pp ON pe.period_id = pp.id
            WHERE pp.start_date >= :s AND pp.end_date <= :e
        """), {"s": start_date, "e": end_date}).scalar()
        labor_cost = float(lc or 0)
    except Exception:
        pass
    labor_cost_pct = (labor_cost / total_revenue * 100) if total_revenue > 0 else 0

    # Prime Cost
    prime_cost_pct = food_cost_pct + labor_cost_pct

    # POS Transactions (covers)
    covers = _count_table(db, "pos_orders", branch_id, "order_date", start_date, end_date,
                          extra_where="status = 'paid'")

    # Average Check per Cover
    avg_check = total_revenue / covers if covers > 0 else 0

    # Table Turnover Rate
    total_tables = 0
    try:
        tt = db.execute(text("SELECT COUNT(*) FROM pos_tables WHERE is_active = true")).scalar()
        total_tables = int(tt or 0)
    except Exception:
        pass
    days_in_period = max((end_date - start_date).days + 1, 1)
    table_turnover = covers / (total_tables * days_in_period) if total_tables > 0 else 0

    # Kitchen Order Time (avg)
    kot_avg = 0
    try:
        kot = db.execute(text("""
            SELECT AVG(EXTRACT(EPOCH FROM (completed_at - created_at)) / 60)
            FROM pos_orders
            WHERE status = 'paid' AND completed_at IS NOT NULL
              AND order_date BETWEEN :s AND :e
        """), {"s": start_date, "e": end_date}).scalar()
        kot_avg = float(kot or 0)
    except Exception:
        pass

    kpis = [
        kpi_item("total_revenue", "Total Revenue", "إجمالي الإيرادات", total_revenue, "SAR"),
        kpi_item("food_cost_pct", "Food Cost %", "نسبة تكلفة الطعام", food_cost_pct, "%",
                 benchmark=32.0, benchmark_source="NRA",
                 status=ratio_status(food_cost_pct, 28, 38, higher_is_better=False)),
        kpi_item("labor_cost_pct", "Labor Cost %", "نسبة تكلفة العمالة", labor_cost_pct, "%",
                 benchmark=30.0, benchmark_source="NRA",
                 status=ratio_status(labor_cost_pct, 25, 38, higher_is_better=False)),
        kpi_item("prime_cost_pct", "Prime Cost %", "نسبة التكلفة الأساسية", prime_cost_pct, "%",
                 benchmark=65.0, benchmark_source="NRA",
                 status=ratio_status(prime_cost_pct, 60, 70, higher_is_better=False)),
        kpi_item("avg_check", "Average Check", "متوسط الفاتورة", avg_check, "SAR"),
        kpi_item("covers", "Covers Served", "عدد الضيوف", covers, ""),
        kpi_item("table_turnover", "Table Turnover", "معدل دوران الطاولات", table_turnover, "x/day",
                 benchmark=2.5, benchmark_source="F&B Benchmark",
                 status=ratio_status(table_turnover, 2.5, 1.5)),
        kpi_item("kot", "Avg Kitchen Time", "متوسط وقت المطبخ", kot_avg, "min",
                 benchmark=15.0, benchmark_source="F&B Benchmark",
                 status=ratio_status(kot_avg, 15, 25, higher_is_better=False)),
    ]

    charts = []
    alerts = []
    if prime_cost_pct > 70:
        alerts.append({"severity": "high", "code": "HIGH_PRIME_COST",
                        "message": i18n_message("kpi_prime_cost_high", request),
                        "message_ar": f"التكلفة الأساسية {prime_cost_pct:.1f}% — تتجاوز حد 70%",
                        "link": "/reports/income-statement"})

    return {"industry": "food_and_beverage", "kpis": kpis, "charts": charts, "alerts": alerts}


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Manufacturing — تصنيع
# ═══════════════════════════════════════════════════════════════════════════════

def get_manufacturing_industry_kpis(db, start_date: date, end_date: date,
                                    branch_id: Optional[int] = None) -> dict:
    """Manufacturing industry KPIs. Reference: APICS + ISO 9001 + IAS 2."""

    # OEE — approximate from capacity_plans if available
    oee = 0
    availability = 100
    performance = 100
    quality = 100
    try:
        cp = db.execute(text("""
            SELECT AVG(efficiency_pct)
            FROM capacity_plans
            WHERE date BETWEEN :s AND :e
        """), {"s": start_date, "e": end_date}).scalar()
        if cp:
            performance = float(cp or 85)
    except Exception:
        performance = 85
    oee = (availability * performance * quality) / 10000

    # Production Yield
    yield_rate = 0
    total_produced = 0
    total_planned = 0
    try:
        yr = db.execute(text("""
            SELECT COALESCE(SUM(produced_quantity), 0), COALESCE(SUM(quantity), 0)
            FROM production_orders
            WHERE status = 'completed' AND start_date BETWEEN :s AND :e
        """), {"s": start_date, "e": end_date}).fetchone()
        if yr:
            total_produced = float(yr[0] or 0)
            total_planned = float(yr[1] or 0)
            yield_rate = (total_produced / total_planned * 100) if total_planned > 0 else 0
    except Exception:
        pass

    # Cost Per Unit (production_orders has no actual_cost column)
    cost_per_unit = 0
    planned_vs_actual = (total_produced / total_planned * 100) if total_planned > 0 else 0

    # Material Variance (no estimated_cost/actual_cost on production_orders)
    material_variance = 0

    # Machine Downtime % (use capacity_plans if available)
    downtime_pct = 0
    try:
        dt = db.execute(text("""
            SELECT
                COALESCE(SUM(planned_hours - actual_hours), 0),
                COALESCE(SUM(available_hours), 0)
            FROM capacity_plans
            WHERE date BETWEEN :s AND :e
        """), {"s": start_date, "e": end_date}).fetchone()
        if dt and dt[1] > 0:
            downtime_pct = (dt[0] / dt[1]) * 100
    except Exception:
        pass

    # Scrap Rate
    scrap_rate = 0
    try:
        sr = db.execute(text("""
            SELECT COALESCE(SUM(scrapped_quantity), 0), COALESCE(SUM(quantity), 0)
            FROM production_orders
            WHERE status = 'completed' AND start_date BETWEEN :s AND :e
        """), {"s": start_date, "e": end_date}).fetchone()
        if sr and sr[1] > 0:
            scrap_rate = (sr[0] / sr[1]) * 100
    except Exception:
        pass

    # On-Time Delivery (approximate — no actual_end_date/planned_end_date on production_orders)
    on_time = 0
    total_orders = 0
    try:
        otd = db.execute(text("""
            SELECT
                COUNT(CASE WHEN updated_at <= due_date THEN 1 END),
                COUNT(*)
            FROM production_orders
            WHERE status = 'completed' AND start_date BETWEEN :s AND :e
        """), {"s": start_date, "e": end_date}).fetchone()
        if otd:
            on_time = int(otd[0] or 0)
            total_orders = int(otd[1] or 0)
    except Exception:
        pass
    otd_pct = (on_time / total_orders * 100) if total_orders > 0 else 0

    kpis = [
        kpi_item("oee", "OEE", "الفعالية الكلية للمعدات", oee, "%",
                 benchmark=85.0, benchmark_source="World Class (APICS)",
                 status=ratio_status(oee, 85, 60)),
        kpi_item("yield_rate", "Production Yield", "معدل الإنتاجية", yield_rate, "%",
                 benchmark=95.0, benchmark_source="ISO 9001",
                 status=ratio_status(yield_rate, 95, 85)),
        kpi_item("cost_per_unit", "Cost Per Unit", "التكلفة لكل وحدة", cost_per_unit, "SAR"),
        kpi_item("planned_vs_actual", "Planned vs Actual", "المخطط مقابل الفعلي", planned_vs_actual, "%",
                 benchmark=95.0, benchmark_source="APICS"),
        kpi_item("material_variance", "Material Variance", "انحراف المواد", material_variance, "%",
                 benchmark=5.0, benchmark_source="Internal",
                 status=ratio_status(abs(material_variance), 5, 15, higher_is_better=False)),
        kpi_item("downtime_pct", "Machine Downtime", "توقف المعدات", downtime_pct, "%",
                 benchmark=5.0, benchmark_source="Industry Avg",
                 status=ratio_status(downtime_pct, 5, 15, higher_is_better=False)),
        kpi_item("scrap_rate", "Scrap Rate", "نسبة الهالك", scrap_rate, "%",
                 benchmark=2.0, benchmark_source="ISO 9001",
                 status=ratio_status(scrap_rate, 2, 5, higher_is_better=False)),
        kpi_item("otd", "On-Time Delivery", "التسليم في الموعد", otd_pct, "%",
                 benchmark=95.0, benchmark_source="APICS",
                 status=ratio_status(otd_pct, 95, 85)),
    ]

    charts = []
    alerts = []
    if oee > 0 and oee < 60:
        alerts.append({"severity": "high", "code": "LOW_OEE",
                        "message": i18n_message("kpi_oee_low", request),
                        "message_ar": f"الفعالية الكلية {oee:.1f}% — أقل بكثير من المعيار العالمي 85%",
                        "link": "/manufacturing/work-centers"})

    return {"industry": "manufacturing", "kpis": kpis, "charts": charts, "alerts": alerts}


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Construction — مقاولات
# ═══════════════════════════════════════════════════════════════════════════════

def get_construction_kpis(db, start_date: date, end_date: date,
                          branch_id: Optional[int] = None) -> dict:
    """Construction KPIs. Reference: PMI PMBOK + IFRS 15."""

    # Active Projects
    active = _count_table(db, "projects", extra_where="status = 'active'")

    # EVM: SPI & CPI (projects has no earned_value/planned_value;
    # approximate from progress_percentage and planned_budget)
    avg_spi = 0
    avg_cpi = 0
    try:
        evm = db.execute(text("""
            SELECT
                AVG(COALESCE(progress_percentage, 0) / 100.0),
                AVG(CASE WHEN actual_cost > 0 THEN (progress_percentage / 100.0 * planned_budget) / actual_cost ELSE 1 END)
            FROM projects WHERE status = 'active' AND planned_budget > 0
        """)).fetchone()
        if evm:
            avg_spi = float(evm[0] or 0)
            avg_cpi = float(evm[1] or 0)
    except Exception:
        pass

    # Budget Variance per project (average)
    budget_variance = 0
    try:
        bv = db.execute(text("""
            SELECT AVG(CASE WHEN planned_budget > 0 THEN (actual_cost - planned_budget) / planned_budget * 100 ELSE 0 END)
            FROM projects WHERE status IN ('active','completed')
        """)).scalar()
        budget_variance = float(bv or 0)
    except Exception:
        pass

    # Change Orders %
    change_order_pct = 0
    try:
        co = db.execute(text("""
            SELECT
                COALESCE(SUM(pco.cost_impact), 0),
                COALESCE(SUM(p.planned_budget), 0)
            FROM projects p
            LEFT JOIN project_change_orders pco ON pco.project_id = p.id
            WHERE p.status IN ('active', 'completed')
        """)).fetchone()
        if co and co[1] > 0:
            change_order_pct = (co[0] / co[1]) * 100
    except Exception:
        pass

    # Contract Backlog
    backlog = 0
    try:
        bl = db.execute(text("""
            SELECT COALESCE(SUM(planned_budget - COALESCE(actual_cost, 0)), 0)
            FROM projects WHERE status = 'active'
        """)).scalar()
        backlog = float(bl or 0)
    except Exception:
        pass

    # EAC = BAC / CPI
    eac = 0
    try:
        bac = db.execute(text("""
            SELECT COALESCE(SUM(planned_budget), 0) FROM projects WHERE status = 'active'
        """)).scalar()
        bac = float(bac or 0)
        eac = bac / avg_cpi if avg_cpi > 0 else bac
    except Exception:
        pass

    # Risk count
    high_risks = _count_table(db, "project_risks", extra_where="status = 'open' AND impact = 'high'")

    kpis = [
        kpi_item("active_projects", "Active Projects", "مشاريع نشطة", active, ""),
        kpi_item("spi", "Schedule Performance (SPI)", "مؤشر أداء الجدول", avg_spi, "x",
                 benchmark=1.0, benchmark_source="PMI PMBOK",
                 status=ratio_status(avg_spi, 1.0, 0.8)),
        kpi_item("cpi", "Cost Performance (CPI)", "مؤشر أداء التكلفة", avg_cpi, "x",
                 benchmark=1.0, benchmark_source="PMI PMBOK",
                 status=ratio_status(avg_cpi, 1.0, 0.8)),
        kpi_item("budget_variance", "Budget Variance", "انحراف الميزانية", budget_variance, "%",
                 benchmark=5.0, benchmark_source="PMI PMBOK",
                 status=ratio_status(abs(budget_variance), 5, 15, higher_is_better=False)),
        kpi_item("change_order_pct", "Change Orders %", "نسبة أوامر التغيير", change_order_pct, "%",
                 benchmark=10.0, benchmark_source="Construction Benchmark",
                 status=ratio_status(change_order_pct, 10, 20, higher_is_better=False)),
        kpi_item("eac", "Estimate at Completion", "التقدير عند الإنجاز", eac, "SAR"),
        kpi_item("backlog", "Contract Backlog", "الأعمال المتبقية", backlog, "SAR"),
        kpi_item("high_risks", "High Risks", "مخاطر عالية", high_risks, "",
                 status="danger" if high_risks > 0 else "good"),
    ]

    charts = []
    alerts = []
    if avg_cpi > 0 and avg_cpi < 0.9:
        alerts.append({"severity": "high", "code": "COST_OVERRUN",
                        "message": i18n_message("kpi_cpi_over_budget", request),
                        "message_ar": f"مؤشر التكلفة {avg_cpi:.2f} — المشاريع تتجاوز الميزانية",
                        "link": "/projects"})

    return {"industry": "construction", "kpis": kpis, "charts": charts, "alerts": alerts}


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Services — خدمات
# ═══════════════════════════════════════════════════════════════════════════════

def get_services_kpis(db, start_date: date, end_date: date,
                      branch_id: Optional[int] = None) -> dict:
    """Services KPIs. Reference: AICPA Service Business Benchmarks."""

    # Headcount
    headcount = _count_table(db, "employees", extra_where="status = 'active'")

    # Revenue
    revenue = _gl_sum(db, "revenue", start_date, end_date, branch_id, debit_minus_credit=False)

    # Revenue per Employee
    rev_per_emp = revenue / headcount if headcount > 0 else 0

    # Billable Utilization (from project_timesheets — no billable/planned_hours columns)
    billable_hours = 0
    total_hours = 0
    try:
        ts = db.execute(text("""
            SELECT COALESCE(SUM(hours), 0)
            FROM project_timesheets
            WHERE date BETWEEN :s AND :e
        """), {"s": start_date, "e": end_date}).scalar()
        total_hours = float(ts or 0)
        billable_hours = total_hours  # All logged hours assumed billable
    except Exception:
        pass
    # Without separate billable flag, estimate utilization from hours logged vs capacity
    work_days = max((end_date - start_date).days + 1, 1) * 5 / 7  # approx work days
    headcount_capacity = headcount * work_days * 8 if headcount > 0 else 1
    billable_util = (total_hours / headcount_capacity * 100) if headcount_capacity > 0 else 0
    billable_util = min(billable_util, 100)  # cap at 100%

    # Project Profitability (projects has actual_cost but no actual_revenue;
    # use planned_budget as revenue proxy)
    project_profit = 0
    try:
        pp = db.execute(text("""
            SELECT
                COALESCE(SUM(planned_budget), 0),
                COALESCE(SUM(actual_cost), 0)
            FROM projects WHERE status IN ('active','completed')
        """)).fetchone()
        if pp and pp[0] > 0:
            project_profit = ((pp[0] - pp[1]) / pp[0]) * 100
    except Exception:
        pass

    # Client count
    active_clients = 0
    try:
        ac = db.execute(text("""
            SELECT COUNT(DISTINCT party_id) FROM invoices
            WHERE invoice_type = 'sales' AND invoice_date BETWEEN :s AND :e AND status != 'cancelled'
        """), {"s": start_date, "e": end_date}).scalar()
        active_clients = int(ac or 0)
    except Exception:
        pass

    # ARPC
    arpc = revenue / active_clients if active_clients > 0 else 0

    # Ticket Resolution Time
    avg_resolution = 0
    try:
        rt = db.execute(text("""
            SELECT AVG(EXTRACT(EPOCH FROM (resolved_at - created_at)) / 3600)
            FROM support_tickets WHERE status = 'resolved'
              AND resolved_at BETWEEN :s AND :e
        """), {"s": start_date, "e": end_date}).scalar()
        avg_resolution = float(rt or 0)
    except Exception:
        pass

    # Proposal Win Rate
    win_rate = 0
    try:
        wr = db.execute(text("""
            SELECT
                COUNT(CASE WHEN status = 'converted' THEN 1 END),
                COUNT(*)
            FROM sales_quotations
            WHERE quotation_date BETWEEN :s AND :e
        """), {"s": start_date, "e": end_date}).fetchone()
        if wr and wr[1] > 0:
            win_rate = (wr[0] / wr[1]) * 100
    except Exception:
        pass

    kpis = [
        kpi_item("billable_util", "Billable Utilization", "نسبة الساعات المدفوعة", billable_util, "%",
                 benchmark=75.0, benchmark_source="AICPA",
                 status=ratio_status(billable_util, 75, 55)),
        kpi_item("rev_per_employee", "Revenue per Employee", "الإيرادات لكل موظف", rev_per_emp, "SAR",
                 benchmark_source="AICPA"),
        kpi_item("project_profitability", "Project Profitability", "ربحية المشاريع", project_profit, "%",
                 benchmark=30.0, benchmark_source="AICPA",
                 status=ratio_status(project_profit, 30, 15)),
        kpi_item("arpc", "Avg Revenue per Client", "متوسط الإيرادات لكل عميل", arpc, "SAR"),
        kpi_item("active_clients", "Active Clients", "العملاء النشطون", active_clients, ""),
        kpi_item("avg_resolution", "Avg Ticket Resolution", "متوسط وقت حل التذكرة", avg_resolution, "hrs",
                 benchmark=24.0, benchmark_source="SLA Standard",
                 status=ratio_status(avg_resolution, 24, 48, higher_is_better=False)),
        kpi_item("win_rate", "Proposal Win Rate", "معدل الفوز بالعروض", win_rate, "%",
                 benchmark=35.0, benchmark_source="Industry Avg",
                 status=ratio_status(win_rate, 35, 20)),
    ]

    charts = []
    alerts = []
    return {"industry": "services", "kpis": kpis, "charts": charts, "alerts": alerts}


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Wholesale — جملة
# ═══════════════════════════════════════════════════════════════════════════════

def get_wholesale_kpis(db, start_date: date, end_date: date,
                       branch_id: Optional[int] = None) -> dict:
    """Wholesale/Distribution KPIs. Reference: DSCSA + IAS 2."""
    branch_sql, bp = build_branch_filter(branch_id)

    # Revenue & COGS
    revenue = _gl_sum(db, "revenue", start_date, end_date, branch_id, debit_minus_credit=False)
    cogs = 0
    try:
        cr = db.execute(text("""
            SELECT COALESCE(SUM(jl.debit - jl.credit), 0)
            FROM journal_lines jl JOIN journal_entries je ON jl.journal_entry_id = je.id
            JOIN accounts a ON jl.account_id = a.id
            WHERE (a.account_type = 'expense' AND a.account_code LIKE '5%')
              AND je.entry_date BETWEEN :s AND :e AND je.status = 'posted'
        """), {"s": start_date, "e": end_date}).scalar()
        cogs = float(cr or 0)
    except Exception:
        pass
    gross_margin = ((revenue - cogs) / revenue * 100) if revenue > 0 else 0

    # Order Count & AOV
    order_count = _count_table(db, "sales_orders", branch_id, "order_date", start_date, end_date)
    order_value = _sum_column(db, "sales_orders", "total", branch_id, "order_date", start_date, end_date)
    aov = order_value / order_count if order_count > 0 else 0

    # Cash Conversion Cycle = DIO + DSO - DPO
    inv_valuation = 0
    try:
        iv = db.execute(text("""
            SELECT COALESCE(SUM(i.quantity * COALESCE(p.cost_price, 0)), 0)
            FROM inventory i JOIN products p ON i.product_id = p.id
        """)).scalar()
        inv_valuation = float(iv or 0)
    except Exception:
        pass

    ar_balance = _gl_balance(db, "receivable", end_date, branch_id)
    ap_balance = _gl_balance(db, "payable", end_date, branch_id, debit_minus_credit=False)

    days_in_period = max((end_date - start_date).days, 1)
    daily_revenue = revenue / days_in_period if days_in_period > 0 else 0
    daily_cogs = cogs / days_in_period if days_in_period > 0 else 0

    dso = ar_balance / daily_revenue if daily_revenue > 0 else 0
    dpo = ap_balance / daily_cogs if daily_cogs > 0 else 0
    stock_turnover = cogs / inv_valuation if inv_valuation > 0 else 0
    dio = 365 / stock_turnover if stock_turnover > 0 else 0
    ccc = dio + dso - dpo

    # Customer Concentration
    top_customer_rev = 0
    try:
        tcr = db.execute(text(f"""
            SELECT COALESCE(SUM(total), 0) FROM invoices
            WHERE invoice_type = 'sales' AND invoice_date BETWEEN :s AND :e AND status != 'cancelled' {branch_sql}
            AND party_id = (
                SELECT party_id FROM invoices
                WHERE invoice_type = 'sales' AND invoice_date BETWEEN :s AND :e AND status != 'cancelled'
                GROUP BY party_id ORDER BY SUM(total) DESC LIMIT 1
            )
        """), {"s": start_date, "e": end_date, **bp}).scalar()
        top_customer_rev = float(tcr or 0)
    except Exception:
        pass
    concentration = (top_customer_rev / revenue * 100) if revenue > 0 else 0

    # Return Rate
    return_value = _sum_column(db, "sales_returns", "total", branch_id, "return_date", start_date, end_date)
    return_rate = (return_value / revenue * 100) if revenue > 0 else 0

    kpis = [
        kpi_item("gross_margin", "Gross Margin", "هامش الربح الإجمالي", gross_margin, "%",
                 benchmark=20.0, benchmark_source="Wholesale Benchmark",
                 status=ratio_status(gross_margin, 20, 10)),
        kpi_item("aov", "Average Order Value", "متوسط قيمة الطلب", aov, "SAR"),
        kpi_item("ccc", "Cash Conversion Cycle", "دورة التحويل النقدي", ccc, "days",
                 benchmark=45, benchmark_source="Industry Avg",
                 status=ratio_status(ccc, 45, 90, higher_is_better=False)),
        kpi_item("dso", "DSO", "أيام تحصيل المبيعات", dso, "days"),
        kpi_item("dpo", "DPO", "أيام سداد المشتريات", dpo, "days"),
        kpi_item("dio", "DIO", "أيام دوران المخزون", dio, "days"),
        kpi_item("concentration", "Top Customer %", "تركز أكبر عميل", concentration, "%",
                 benchmark=20.0, benchmark_source="Risk Benchmark",
                 status=ratio_status(concentration, 20, 40, higher_is_better=False)),
        kpi_item("return_rate", "Return Rate", "معدل المرتجعات", return_rate, "%",
                 benchmark=2.0, benchmark_source="Wholesale Benchmark",
                 status=ratio_status(return_rate, 2, 5, higher_is_better=False)),
    ]

    charts = []
    alerts = []
    if concentration > 30:
        alerts.append({"severity": "medium", "code": "CUSTOMER_CONCENTRATION",
                        "message": i18n_message("kpi_customer_concentration", request),
                        "message_ar": f"أكبر عميل يمثل {concentration:.0f}% من الإيرادات — خطر التركز",
                        "link": "/sales/customers"})

    return {"industry": "wholesale", "kpis": kpis, "charts": charts, "alerts": alerts}


# ═══════════════════════════════════════════════════════════════════════════════
# 7. General — عام
# ═══════════════════════════════════════════════════════════════════════════════

def get_general_kpis(db, start_date: date, end_date: date,
                     branch_id: Optional[int] = None) -> dict:
    """General industry KPIs. Covers fundamental financial metrics for any business."""
    prev_start, prev_end = get_previous_period(start_date, end_date)

    revenue = _gl_sum(db, "revenue", start_date, end_date, branch_id, debit_minus_credit=False)
    prev_revenue = _gl_sum(db, "revenue", prev_start, prev_end, branch_id, debit_minus_credit=False)
    rev_growth_trend = calc_trend(revenue, prev_revenue)

    expenses = _gl_sum(db, "expense", start_date, end_date, branch_id)
    cogs = 0
    try:
        cr = db.execute(text("""
            SELECT COALESCE(SUM(jl.debit - jl.credit), 0)
            FROM journal_lines jl JOIN journal_entries je ON jl.journal_entry_id = je.id
            JOIN accounts a ON jl.account_id = a.id
            WHERE (a.account_type = 'expense' AND a.account_code LIKE '5%')
              AND je.entry_date BETWEEN :s AND :e AND je.status = 'posted'
        """), {"s": start_date, "e": end_date}).scalar()
        cogs = float(cr or 0)
    except Exception:
        pass

    net_income = revenue - cogs - expenses
    gross_margin = ((revenue - cogs) / revenue * 100) if revenue > 0 else 0
    net_margin = (net_income / revenue * 100) if revenue > 0 else 0
    ebitda_margin = (net_income / revenue * 100) if revenue > 0 else 0  # simplified

    # Balance Sheet items
    total_assets = _gl_balance(db, "asset", end_date, branch_id)
    total_equity = _gl_balance(db, "equity", end_date, branch_id, debit_minus_credit=False)
    total_liabilities = _gl_balance(db, "liability", end_date, branch_id, debit_minus_credit=False)
    current_assets = _gl_balance_by_classification(db, "current_asset", end_date, branch_id)
    if current_assets == 0:
        current_assets = total_assets  # fallback
    current_liabilities = abs(_gl_balance_by_classification(db, "current_liability", end_date, branch_id))
    if current_liabilities == 0:
        current_liabilities = abs(total_liabilities)

    current_ratio = current_assets / current_liabilities if current_liabilities > 0 else 0
    quick_ratio = current_ratio  # simplified
    debt_to_equity = abs(total_liabilities) / total_equity if total_equity > 0 else 0
    roa = (net_income / total_assets * 100) if total_assets > 0 else 0
    roe = (net_income / total_equity * 100) if total_equity > 0 else 0

    # AR / AP Turnover
    ar_balance = _gl_balance(db, "receivable", end_date, branch_id)
    ap_balance = _gl_balance(db, "payable", end_date, branch_id, debit_minus_credit=False)
    ar_turnover = revenue / ar_balance if ar_balance > 0 else 0
    ap_turnover = cogs / ap_balance if ap_balance > 0 else 0

    kpis = [
        kpi_item("revenue_growth", "Revenue Growth", "نمو الإيرادات",
                 float(rev_growth_trend[0].rstrip('%')) if '%' in rev_growth_trend[0] else 0, "%",
                 rev_growth_trend[0], rev_growth_trend[1], rev_growth_trend[2],
                 benchmark_source="IFRS 15"),
        kpi_item("gross_margin", "Gross Profit Margin", "هامش الربح الإجمالي", gross_margin, "%",
                 benchmark=30.0, benchmark_source="IAS 1"),
        kpi_item("net_margin", "Net Profit Margin", "صافي هامش الربح", net_margin, "%",
                 benchmark=15.0, benchmark_source="IAS 1"),
        kpi_item("ebitda_margin", "EBITDA Margin", "هامش الأرباح قبل الفوائد والضرائب", ebitda_margin, "%"),
        kpi_item("current_ratio", "Current Ratio", "نسبة التداول", current_ratio, "x",
                 benchmark=2.0, benchmark_source="IAS 1",
                 status=ratio_status(current_ratio, 2.0, 1.0)),
        kpi_item("debt_to_equity", "Debt-to-Equity", "نسبة الدين للملكية", debt_to_equity, "x",
                 benchmark=1.5, benchmark_source="IAS 32",
                 status=ratio_status(debt_to_equity, 1.0, 2.0, higher_is_better=False)),
        kpi_item("roa", "Return on Assets", "العائد على الأصول", roa, "%",
                 benchmark=5.0, benchmark_source="Financial Benchmark"),
        kpi_item("roe", "Return on Equity", "العائد على حقوق الملكية", roe, "%",
                 benchmark=15.0, benchmark_source="Financial Benchmark"),
        kpi_item("ar_turnover", "AR Turnover", "معدل دوران الذمم المدينة", ar_turnover, "x"),
        kpi_item("ap_turnover", "AP Turnover", "معدل دوران الذمم الدائنة", ap_turnover, "x"),
    ]

    charts = []
    alerts = []
    return {"industry": "general", "kpis": kpis, "charts": charts, "alerts": alerts}
