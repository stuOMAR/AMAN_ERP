"""kpi_service.projects — split from monolithic kpi_service.py (T6.3)"""
from sqlalchemy import text
from datetime import date
from typing import Optional
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)
from .common import (  # noqa: E402
    kpi_item, ratio_status, _count_table
)
from utils.accounting import get_base_currency  # noqa: E402
from utils.tax_precision import money_str, rate_str  # noqa: E402
from utils.i18n import i18n_message  # noqa: E402


def get_projects_kpis(db, start_date: date, end_date: date,
                      branch_id: Optional[int] = None) -> dict:
    """KPIs for Project Manager."""
    base_currency = get_base_currency(db) or "SAR"

    # Active projects
    active_projects = _count_table(db, "projects", extra_where="status = 'active'")
    _count_table(db, "projects", extra_where="status = 'completed'")

    # Budget utilization
    budget_util = Decimal("0")
    try:
        bu = db.execute(text("""
            SELECT
                COALESCE(SUM(actual_cost), 0),
                COALESCE(SUM(planned_budget), 0)
            FROM projects WHERE status IN ('active', 'completed')
        """)).fetchone()
        if bu and bu[1] > 0:
            budget_util = (bu[0] / bu[1]) * 100
    except Exception:
        pass

    # EVM: CPI and SPI (projects table has no earned_value/planned_value;
    # approximate CPI from actual_cost vs planned_budget)
    avg_cpi = Decimal("0")
    avg_spi = Decimal("0")
    try:
        evm = db.execute(text("""
            SELECT
                AVG(CASE WHEN actual_cost > 0 THEN (progress_percentage / 100.0 * planned_budget) / actual_cost ELSE 1 END),
                AVG(COALESCE(progress_percentage, 0) / 100.0)
            FROM projects WHERE status = 'active' AND planned_budget > 0
        """)).fetchone()
        if evm:
            avg_cpi = Decimal(str(evm[0] or 0))
            avg_spi = Decimal(str(evm[1] or 0))
    except Exception:
        pass

    # Change Orders
    change_orders_value = Decimal("0")
    try:
        co = db.execute(text("""
            SELECT COALESCE(SUM(cost_impact), 0) FROM project_change_orders
            WHERE created_at BETWEEN :s AND :e
        """), {"s": start_date, "e": end_date}).scalar()
        change_orders_value = Decimal(str(co or 0))
    except Exception:
        pass

    # Risk Distribution (project_risks has probability/impact, not risk_level)
    risks = {"high": 0, "medium": 0, "low": 0}
    try:
        risk_rows = db.execute(text("""
            SELECT impact, COUNT(*) FROM project_risks
            WHERE status = 'open'
            GROUP BY impact
        """)).fetchall()
        for r in risk_rows:
            level = str(r[0]).lower()
            if level in risks:
                risks[level] = int(r[1])
    except Exception:
        pass

    # Resource utilization (project_timesheets has single 'hours' column, no planned_hours)
    resource_hours = Decimal("0")
    Decimal("0")
    try:
        ru = db.execute(text("""
            SELECT COALESCE(SUM(hours), 0)
            FROM project_timesheets
            WHERE date BETWEEN :s AND :e
        """), {"s": start_date, "e": end_date}).scalar()
        resource_hours = Decimal(str(ru or 0))
    except Exception:
        pass

    kpis = [
        kpi_item("active_projects", "Active Projects", "مشاريع نشطة", active_projects, ""),
        kpi_item("budget_utilization", "Budget Utilization", "استخدام الميزانية", rate_str(budget_util), "%",
                 benchmark="100.0000", benchmark_source="PMI PMBOK"),
        kpi_item("cpi", "Cost Performance Index", "مؤشر أداء التكلفة", rate_str(avg_cpi), "x",
                 benchmark="1.0000", benchmark_source="PMI PMBOK",
                 status=ratio_status(avg_cpi, Decimal("1.0"), Decimal("0.8"))),
        kpi_item("spi", "Schedule Performance Index", "مؤشر أداء الجدول", rate_str(avg_spi), "x",
                 benchmark="1.0000", benchmark_source="PMI PMBOK",
                 status=ratio_status(avg_spi, Decimal("1.0"), Decimal("0.8"))),
        kpi_item("change_orders", "Change Orders Value", "قيمة أوامر التغيير", money_str(change_orders_value), base_currency),
        kpi_item("high_risks", "High Risks", "مخاطر عالية", risks["high"], "",
                 status="danger" if risks["high"] > 0 else "good"),
        kpi_item("resource_utilization", "Resource Hours", "ساعات الموارد", rate_str(resource_hours), "h",
                 benchmark="", benchmark_source="timesheets"),
    ]

    charts = [
        {"id": "risk_distribution", "type": "pie", "title": "Risk Distribution",
         "title_ar": "توزيع المخاطر", "data": risks},
    ]

    alerts = []
    if risks["high"] > 0:
        alerts.append({"severity": "high", "code": "HIGH_RISKS",
                        "message": i18n_message("kpi_high_risks"),
                        "message_ar": f"{risks['high']} مخاطر عالية تحتاج متابعة",
                        "count": risks["high"], "link": "/projects/risks"})

    return {"role": "projects", "kpis": kpis, "charts": charts, "alerts": alerts}


# ═══════════════════════════════════════════════════════════════════════════════
# POS Dashboard KPIs
# ═══════════════════════════════════════════════════════════════════════════════
