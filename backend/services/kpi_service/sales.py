"""kpi_service.sales — split from monolithic kpi_service.py (T6.3)"""
from sqlalchemy import text
from datetime import date, timedelta
from typing import Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)
from .common import (
    get_previous_period, build_branch_filter, kpi_item, calc_trend, ratio_status, _gl_sum, _gl_balance, _count_table, _sum_column
)
from .charts import (
    _build_sales_trend_chart
)


def get_sales_kpis(db, start_date: date, end_date: date,
                   branch_id: Optional[int] = None) -> dict:
    """KPIs for Sales Manager."""
    prev_start, prev_end = get_previous_period(start_date, end_date)
    branch_sql, bp = build_branch_filter(branch_id)

    # Total Revenue
    revenue = _gl_sum(db, "revenue", start_date, end_date, branch_id, debit_minus_credit=False)
    prev_revenue = _gl_sum(db, "revenue", prev_start, prev_end, branch_id, debit_minus_credit=False)
    rev_trend = calc_trend(revenue, prev_revenue)

    # Quotation Conversion Rate
    total_quotations = _count_table(db, "sales_quotations", branch_id, "quotation_date", start_date, end_date)
    converted_quotations = _count_table(db, "sales_quotations", branch_id, "quotation_date", start_date, end_date,
                                        extra_where="status = 'converted'")
    conversion_rate = (converted_quotations / total_quotations * 100) if total_quotations > 0 else 0

    # Average Deal Size
    total_orders = _count_table(db, "sales_orders", branch_id, "order_date", start_date, end_date)
    total_order_value = _sum_column(db, "sales_orders", "total", branch_id, "order_date", start_date, end_date)
    avg_deal = total_order_value / total_orders if total_orders > 0 else 0

    # Top 10 Customers
    top_customers = []
    try:
        rows = db.execute(text(f"""
            SELECT p.name, COALESCE(SUM(i.total), 0) as total
            FROM invoices i
            JOIN parties p ON i.party_id = p.id
            WHERE i.invoice_type = 'sales' AND i.invoice_date BETWEEN :s AND :e {branch_sql}
            GROUP BY p.name ORDER BY total DESC LIMIT 10
        """), {"s": start_date, "e": end_date, **bp}).fetchall()
        top_customers = [{"name": r[0], "value": float(r[1])} for r in rows]
    except Exception:
        pass

    # Overdue Invoices
    overdue_count = 0
    overdue_value = 0
    try:
        ov = db.execute(text(f"""
            SELECT COUNT(*), COALESCE(SUM(total - COALESCE(paid_amount, 0)), 0)
            FROM invoices
            WHERE invoice_type = 'sales' AND status IN ('sent','partially_paid')
              AND due_date < CURRENT_DATE {branch_sql.replace('je.', '')}
        """), bp).fetchone()
        if ov:
            overdue_count = int(ov[0] or 0)
            overdue_value = float(ov[1] or 0)
    except Exception:
        pass

    # DSO
    ar_balance = _gl_balance(db, "receivable", end_date, branch_id)
    days_in_period = max((end_date - start_date).days, 1)
    daily_rev = revenue / days_in_period if days_in_period > 0 else 0
    dso = ar_balance / daily_rev if daily_rev > 0 else 0

    # Pipeline Value (CRM)
    pipeline_value = 0
    try:
        pv = db.execute(text("""
            SELECT COALESCE(SUM(expected_value), 0) FROM sales_opportunities
            WHERE stage IN ('open', 'qualified', 'proposal')
        """)).scalar()
        pipeline_value = float(pv or 0)
    except Exception:
        pass

    kpis = [
        kpi_item("revenue", "Total Revenue", "إجمالي الإيرادات", revenue, "SAR",
                 rev_trend[0], rev_trend[1], rev_trend[2]),
        kpi_item("conversion_rate", "Quotation Conversion Rate", "معدل تحويل عروض الأسعار",
                 conversion_rate, "%", benchmark=25.0, benchmark_source="Industry Avg",
                 status=ratio_status(conversion_rate, 25, 10)),
        kpi_item("avg_deal_size", "Average Deal Size", "متوسط حجم الصفقة", avg_deal, "SAR"),
        kpi_item("total_orders", "Sales Orders", "أوامر البيع", total_orders, ""),
        kpi_item("overdue_invoices", "Overdue Invoices", "الفواتير المتأخرة", overdue_count, "",
                 status="danger" if overdue_count > 0 else "good"),
        kpi_item("overdue_value", "Overdue Value", "قيمة المتأخرات", overdue_value, "SAR",
                 status="danger" if overdue_value > 0 else "good"),
        kpi_item("dso", "Days Sales Outstanding", "أيام تحصيل المبيعات", dso, "days",
                 benchmark=30, benchmark_source="Best Practice",
                 status=ratio_status(dso, 30, 60, higher_is_better=False)),
        kpi_item("pipeline_value", "Pipeline Value", "قيمة الفرص المتوقعة", pipeline_value, "SAR"),
    ]

    charts = [
        {"id": "top_customers", "type": "bar", "title": "Top 10 Customers",
         "title_ar": "أعلى 10 عملاء", "data": top_customers},
    ]
    charts.extend(_build_sales_trend_chart(db, start_date, end_date, branch_id))

    alerts = []
    if overdue_count > 0:
        alerts.append({"severity": "high", "code": "OVERDUE_INVOICES",
                        "message": f"{overdue_count} invoices overdue totaling {overdue_value:,.0f} SAR",
                        "message_ar": f"{overdue_count} فاتورة متأخرة بإجمالي {overdue_value:,.0f} ر.س",
                        "count": overdue_count, "link": "/sales/invoices?status=overdue"})

    return {"role": "sales", "kpis": kpis, "charts": charts, "alerts": alerts}


# ═══════════════════════════════════════════════════════════════════════════════
# Procurement Dashboard KPIs
# ═══════════════════════════════════════════════════════════════════════════════

