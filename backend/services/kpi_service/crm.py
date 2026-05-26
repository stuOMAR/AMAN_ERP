"""kpi_service.crm — split from monolithic kpi_service.py (T6.3)"""
from sqlalchemy import text
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional
import logging

logger = logging.getLogger(__name__)
from .common import (  # noqa: E402
    build_branch_filter, kpi_item, ratio_status, _count_table
)
from utils.i18n import i18n_message  # noqa: E402
from utils.accounting import get_base_currency  # noqa: E402
from utils.currency_display import currency_amount_base_sql  # noqa: E402
from utils.tax_precision import rate_str  # noqa: E402

_D4 = Decimal("0.0001")


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _pct(numerator: Any, denominator: Any) -> Decimal:
    denom = _dec(denominator)
    if denom == 0:
        return Decimal("0")
    return (_dec(numerator) * Decimal("100") / denom).quantize(_D4, rounding=ROUND_HALF_UP)


def get_crm_kpis(db, start_date: date, end_date: date,
                 branch_id: Optional[int] = None) -> dict:
    """KPIs for CRM / Sales Rep."""
    opp_branch_sql, opp_bp = build_branch_filter(branch_id, table_alias="o")
    base_currency = get_base_currency(db) or "SAR"
    opp_currency_sql = "COALESCE(o.currency, (SELECT b.default_currency FROM branches b WHERE b.id = o.branch_id), :base_currency)"
    expected_base_sql = currency_amount_base_sql("o.expected_value", opp_currency_sql)

    # Opportunities
    open_opps = 0
    open_value = Decimal("0")
    try:
        oo = db.execute(text(f"""
            SELECT COUNT(*), COALESCE(SUM({expected_base_sql}), 0)
            FROM sales_opportunities o
            WHERE o.stage NOT IN ('won','lost','cancelled')
              AND COALESCE(o.is_deleted, FALSE) = FALSE
              {opp_branch_sql}
        """), {"base_currency": base_currency, **opp_bp}).fetchone()
        if oo:
            open_opps = int(oo[0] or 0)
            open_value = _dec(oo[1])
    except Exception:
        pass

    # Win Rate
    won_opps = _count_table(db, "sales_opportunities", branch_id=branch_id, date_col="updated_at",
                            start_date=start_date, end_date=end_date,
                            extra_where="stage = 'won' AND COALESCE(is_deleted, FALSE) = FALSE")
    lost_opps = _count_table(db, "sales_opportunities", branch_id=branch_id, date_col="updated_at",
                             start_date=start_date, end_date=end_date,
                             extra_where="stage = 'lost' AND COALESCE(is_deleted, FALSE) = FALSE")
    total_closed = won_opps + lost_opps
    win_rate = _pct(won_opps, total_closed)

    # Pipeline by Stage
    pipeline_stages = []
    try:
        stages = db.execute(text(f"""
            SELECT o.stage, COUNT(*), COALESCE(SUM({expected_base_sql}), 0)
            FROM sales_opportunities o
            WHERE o.stage NOT IN ('won','lost','cancelled')
              AND COALESCE(o.is_deleted, FALSE) = FALSE
              {opp_branch_sql}
            GROUP BY o.stage ORDER BY COUNT(*) DESC
        """), {"base_currency": base_currency, **opp_bp}).fetchall()
        pipeline_stages = [{"stage": r[0], "count": int(r[1]), "value": _dec(r[2])} for r in stages]
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
    campaign_roi = Decimal("0")
    try:
        campaign_branch_sql, campaign_bp = build_branch_filter(branch_id, table_alias="mc")
        cr = db.execute(text(f"""
            SELECT
                COALESCE(SUM(total_responded), 0) as conversions,
                COALESCE(SUM(budget), 0) as budget,
                COALESCE(SUM(spent), 0) as spent
            FROM marketing_campaigns mc
            WHERE mc.start_date BETWEEN :s AND :e {campaign_branch_sql}
        """), {"s": start_date, "e": end_date, **campaign_bp}).fetchone()
        if cr and _dec(cr.spent) > 0 and _dec(cr.budget) > 0:
            # ROI based on spend efficiency: (budget - spent) / budget * 100
            campaign_roi = ((_dec(cr.budget) - _dec(cr.spent)) * Decimal("100") / _dec(cr.budget)).quantize(_D4, rounding=ROUND_HALF_UP)
    except Exception:
        pass

    kpis = [
        kpi_item("open_opportunities", "Open Opportunities", "الفرص المفتوحة", open_opps, ""),
        kpi_item("pipeline_value", "Pipeline Value", "قيمة الفرص", open_value, base_currency),
        kpi_item("win_rate", "Win Rate", "معدل الفوز", rate_str(win_rate), "%",
                 benchmark=rate_str(35), benchmark_source="Industry Avg",
                 status=ratio_status(win_rate, Decimal("35"), Decimal("20"))),
        kpi_item("open_tickets", "Open Tickets", "التذاكر المفتوحة", open_tickets, ""),
        kpi_item("overdue_tickets", "Overdue Tickets", "التذاكر المتأخرة", overdue_tickets, "",
                 status="danger" if overdue_tickets > 0 else "good"),
        kpi_item("campaign_roi", "Campaign ROI", "عائد الحملات", rate_str(campaign_roi), "%",
                 benchmark=rate_str(100), benchmark_source="Marketing Benchmark"),
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
