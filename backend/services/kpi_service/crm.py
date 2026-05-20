"""kpi_service.crm — split from monolithic kpi_service.py (T6.3)"""
from sqlalchemy import text
from datetime import date, timedelta
from typing import Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)
from .common import (
    build_branch_filter, kpi_item, ratio_status, _count_table
)
from utils.accounting import get_base_currency
from utils.currency_display import currency_amount_base_sql


def get_crm_kpis(db, start_date: date, end_date: date,
                 branch_id: Optional[int] = None) -> dict:
    """KPIs for CRM / Sales Rep."""
    opp_branch_sql, opp_bp = build_branch_filter(branch_id, table_alias="o")
    base_currency = get_base_currency(db) or "SAR"
    opp_currency_sql = "COALESCE(o.currency, (SELECT b.default_currency FROM branches b WHERE b.id = o.branch_id), :base_currency)"
    expected_base_sql = currency_amount_base_sql("o.expected_value", opp_currency_sql)

    # Opportunities
    open_opps = 0
    open_value = 0
    try:
        oo = db.execute(text(f"""
            SELECT COUNT(*), COALESCE(SUM({expected_base_sql}), 0)
            FROM sales_opportunities o WHERE o.stage IN ('open','qualified','proposal') {opp_branch_sql}
        """), {"base_currency": base_currency, **opp_bp}).fetchone()
        if oo:
            open_opps = int(oo[0] or 0)
            open_value = float(oo[1] or 0)
    except Exception:
        pass

    # Win Rate
    won_opps = _count_table(db, "sales_opportunities", date_col="updated_at",
                            start_date=start_date, end_date=end_date,
                            extra_where="stage = 'won'")
    lost_opps = _count_table(db, "sales_opportunities", date_col="updated_at",
                             start_date=start_date, end_date=end_date,
                             extra_where="stage = 'lost'")
    total_closed = won_opps + lost_opps
    win_rate = (won_opps / total_closed * 100) if total_closed > 0 else 0

    # Pipeline by Stage
    pipeline_stages = []
    try:
        stages = db.execute(text(f"""
            SELECT o.stage, COUNT(*), COALESCE(SUM({expected_base_sql}), 0)
            FROM sales_opportunities o WHERE o.stage NOT IN ('won','lost','cancelled') {opp_branch_sql}
            GROUP BY o.stage ORDER BY COUNT(*) DESC
        """), {"base_currency": base_currency, **opp_bp}).fetchall()
        pipeline_stages = [{"stage": r[0], "count": int(r[1]), "value": Decimal(str(r[2]))} for r in stages]
    except Exception:
        pass

    # Support Tickets
    open_tickets = _count_table(db, "support_tickets", extra_where="status IN ('open','in_progress')")
    overdue_tickets = 0
    try:
        ot = db.execute(text("""
            SELECT COUNT(*) FROM support_tickets
            WHERE status IN ('open','in_progress')
              AND due_date < CURRENT_DATE
        """)).scalar()
        overdue_tickets = int(ot or 0)
    except Exception:
        pass

    # Campaign ROI (marketing_campaigns has budget/spent, no actual_revenue)
    campaign_roi = 0
    try:
        cr = db.execute(text("""
            SELECT
                COALESCE(SUM(conversion_count), 0),
                COALESCE(SUM(budget), 0),
                COALESCE(SUM(spent), 0)
            FROM marketing_campaigns
            WHERE start_date BETWEEN :s AND :e
        """), {"s": start_date, "e": end_date}).fetchone()
        if cr and cr[2] > 0 and cr[1] > 0:
            # ROI based on spend efficiency: (budget - spent) / budget * 100
            campaign_roi = ((cr[1] - cr[2]) / cr[1]) * 100
    except Exception:
        pass

    kpis = [
        kpi_item("open_opportunities", "Open Opportunities", "الفرص المفتوحة", open_opps, ""),
        kpi_item("pipeline_value", "Pipeline Value", "قيمة الفرص", open_value, base_currency),
        kpi_item("win_rate", "Win Rate", "معدل الفوز", win_rate, "%",
                 benchmark=35.0, benchmark_source="Industry Avg",
                 status=ratio_status(win_rate, 35, 20)),
        kpi_item("open_tickets", "Open Tickets", "التذاكر المفتوحة", open_tickets, ""),
        kpi_item("overdue_tickets", "Overdue Tickets", "التذاكر المتأخرة", overdue_tickets, "",
                 status="danger" if overdue_tickets > 0 else "good"),
        kpi_item("campaign_roi", "Campaign ROI", "عائد الحملات", campaign_roi, "%",
                 benchmark=100.0, benchmark_source="Marketing Benchmark"),
    ]

    charts = [
        {"id": "pipeline_stages", "type": "funnel", "title": "Pipeline by Stage",
         "title_ar": "الفرص حسب المرحلة", "data": pipeline_stages},
    ]

    alerts = []
    if overdue_tickets > 0:
        alerts.append({"severity": "high", "code": "OVERDUE_TICKETS",
                        "message": i18n_message("kpi_overdue_tickets"),
                        "message_ar": f"{overdue_tickets} تذكرة دعم متأخرة",
                        "count": overdue_tickets, "link": "/crm/tickets?status=overdue"})

    return {"role": "crm", "kpis": kpis, "charts": charts, "alerts": alerts}


# ═══════════════════════════════════════════════════════════════════════════════
# Helper: Chart Builders
# ═══════════════════════════════════════════════════════════════════════════════

