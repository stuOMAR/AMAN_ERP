"""crm sub-router — split from monolithic crm.py (T6.3).

Mounted under the parent router via crm/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel
from decimal import Decimal
import logging
from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import require_permission, require_module, validate_branch_access
from utils.accounting import generate_sequential_number
from utils.audit import log_activity
from utils.sql_builder import validate_update_keys
from services.notification_service import notification_service
from schemas.campaign import CampaignCreate, TrackingWebhookPayload

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/analytics/pipeline", dependencies=[Depends(require_permission("sales.view"))], response_model=Dict[str, Any])
def pipeline_analytics(current_user=Depends(get_current_user)):
    """تحليلات خط أنابيب المبيعات — معدلات التحويل وسرعة المبيعات"""
    db = get_db_connection(current_user.company_id)
    try:
        # Stage conversion funnel
        funnel = db.execute(text("""
            SELECT stage,
                   COUNT(*) as count,
                   COALESCE(SUM(expected_value), 0) as total_value,
                   COALESCE(AVG(expected_value), 0) as avg_deal_size
            FROM sales_opportunities
            GROUP BY stage
            ORDER BY CASE stage
                WHEN 'lead' THEN 1 WHEN 'qualified' THEN 2
                WHEN 'proposal' THEN 3 WHEN 'negotiation' THEN 4
                WHEN 'won' THEN 5 WHEN 'lost' THEN 6
            END
        """)).fetchall()

        # Win rate
        win_rate = db.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE stage = 'won') as won,
                COUNT(*) FILTER (WHERE stage = 'lost') as lost,
                COUNT(*) FILTER (WHERE stage IN ('won','lost')) as closed,
                CASE WHEN COUNT(*) FILTER (WHERE stage IN ('won','lost')) > 0
                     THEN ROUND(100.0 * COUNT(*) FILTER (WHERE stage = 'won') /
                          COUNT(*) FILTER (WHERE stage IN ('won','lost')), 1)
                     ELSE 0 END as win_rate_pct
            FROM sales_opportunities
        """)).fetchone()

        # Sales velocity: avg days to close won deals
        velocity = db.execute(text("""
            SELECT
                COALESCE(AVG(EXTRACT(DAY FROM (updated_at - created_at))), 0) as avg_days_to_close,
                COALESCE(AVG(expected_value), 0) as avg_deal_value,
                COUNT(*) as total_won
            FROM sales_opportunities WHERE stage = 'won'
        """)).fetchone()

        # Monthly trend (last 12 months)
        monthly = db.execute(text("""
            SELECT TO_CHAR(created_at, 'YYYY-MM') as month,
                   COUNT(*) as created,
                   COUNT(*) FILTER (WHERE stage = 'won') as won,
                   COUNT(*) FILTER (WHERE stage = 'lost') as lost,
                   COALESCE(SUM(expected_value) FILTER (WHERE stage = 'won'), 0) as won_value
            FROM sales_opportunities
            WHERE created_at >= NOW() - INTERVAL '12 months'
            GROUP BY TO_CHAR(created_at, 'YYYY-MM')
            ORDER BY month
        """)).fetchall()

        # Top performers
        top_reps = db.execute(text("""
            SELECT cu.username, cu.full_name,
                   COUNT(*) FILTER (WHERE o.stage = 'won') as wins,
                   COALESCE(SUM(o.expected_value) FILTER (WHERE o.stage = 'won'), 0) as total_value,
                   COUNT(*) as total_assigned
            FROM sales_opportunities o
            JOIN company_users cu ON o.assigned_to = cu.id
            GROUP BY cu.id, cu.username, cu.full_name
            ORDER BY total_value DESC
            LIMIT 10
        """)).fetchall()

        # Source analysis
        sources = db.execute(text("""
            SELECT COALESCE(source, 'غير محدد') as source,
                   COUNT(*) as total,
                   COUNT(*) FILTER (WHERE stage = 'won') as won,
                   COALESCE(SUM(expected_value) FILTER (WHERE stage = 'won'), 0) as won_value
            FROM sales_opportunities
            GROUP BY source
            ORDER BY won_value DESC
        """)).fetchall()

        return {
            "funnel": [dict(r._mapping) for r in funnel],
            "win_rate": dict(win_rate._mapping) if win_rate else {},
            "velocity": dict(velocity._mapping) if velocity else {},
            "monthly_trend": [dict(r._mapping) for r in monthly],
            "top_performers": [dict(r._mapping) for r in top_reps],
            "source_analysis": [dict(r._mapping) for r in sources]
        }
    finally:
        db.close()


@router.get("/analytics/forecast", dependencies=[Depends(require_permission("sales.view"))], response_model=Dict[str, Any])
def sales_forecast(current_user=Depends(get_current_user)):
    """توقعات المبيعات المبنية على خط الأنابيب"""
    db = get_db_connection(current_user.company_id)
    try:
        # Weighted pipeline value
        weighted = db.execute(text("""
            SELECT
                COALESCE(SUM(expected_value * probability / 100.0), 0) as weighted_value,
                COALESCE(SUM(expected_value), 0) as total_pipeline,
                COUNT(*) as active_deals
            FROM sales_opportunities
            WHERE stage NOT IN ('won', 'lost')
        """)).fetchone()

        # By expected close month
        by_month = db.execute(text("""
            SELECT TO_CHAR(expected_close_date, 'YYYY-MM') as month,
                   COUNT(*) as deals,
                   COALESCE(SUM(expected_value), 0) as total_value,
                   COALESCE(SUM(expected_value * probability / 100.0), 0) as weighted_value
            FROM sales_opportunities
            WHERE stage NOT IN ('won', 'lost') AND expected_close_date IS NOT NULL
            GROUP BY TO_CHAR(expected_close_date, 'YYYY-MM')
            ORDER BY month
        """)).fetchall()

        # Historical actuals for comparison
        actuals = db.execute(text("""
            SELECT TO_CHAR(updated_at, 'YYYY-MM') as month,
                   COALESCE(SUM(expected_value), 0) as actual_value,
                   COUNT(*) as deals_won
            FROM sales_opportunities
            WHERE stage = 'won' AND updated_at >= NOW() - INTERVAL '12 months'
            GROUP BY TO_CHAR(updated_at, 'YYYY-MM')
            ORDER BY month
        """)).fetchall()

        # Best/Worst/Most Likely scenarios
        scenarios = db.execute(text("""
            SELECT
                COALESCE(SUM(expected_value) FILTER (WHERE probability >= 75), 0) as commit_value,
                COALESCE(SUM(expected_value) FILTER (WHERE probability >= 50), 0) as best_case,
                COALESCE(SUM(expected_value * probability / 100.0), 0) as most_likely
            FROM sales_opportunities
            WHERE stage NOT IN ('won', 'lost')
        """)).fetchone()

        return {
            "weighted_pipeline": dict(weighted._mapping) if weighted else {},
            "by_month": [dict(r._mapping) for r in by_month],
            "historical_actuals": [dict(r._mapping) for r in actuals],
            "scenarios": dict(scenarios._mapping) if scenarios else {}
        }
    finally:
        db.close()


@router.get("/dashboard", dependencies=[Depends(require_permission("sales.view"))], response_model=Dict[str, Any])
def crm_dashboard(current_user=Depends(get_current_user)):
    """لوحة معلومات CRM الشاملة"""
    db = get_db_connection(current_user.company_id)
    try:
        # Summary KPIs
        kpis = db.execute(text("""
            SELECT
                COUNT(*) as total_opportunities,
                COUNT(*) FILTER (WHERE stage NOT IN ('won','lost')) as active_opps,
                COUNT(*) FILTER (WHERE stage = 'won') as won_opps,
                COUNT(*) FILTER (WHERE stage = 'lost') as lost_opps,
                COALESCE(SUM(expected_value) FILTER (WHERE stage = 'won'), 0) as total_won_value,
                COALESCE(SUM(expected_value) FILTER (WHERE stage NOT IN ('won','lost')), 0) as pipeline_value,
                COALESCE(AVG(expected_value) FILTER (WHERE stage = 'won'), 0) as avg_deal_size
            FROM sales_opportunities
        """)).fetchone()

        # Tickets summary
        tickets = db.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'open') as open_tickets,
                COUNT(*) FILTER (WHERE status = 'in_progress') as in_progress,
                COUNT(*) FILTER (WHERE priority IN ('critical','high') AND status NOT IN ('resolved','closed')) as urgent,
                COALESCE(AVG(EXTRACT(EPOCH FROM (COALESCE(resolved_at, NOW()) - created_at)) / 3600)
                    FILTER (WHERE resolved_at IS NOT NULL), 0) as avg_resolution_hrs
            FROM support_tickets
        """)).fetchone()

        # Campaigns summary
        campaigns = db.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'active') as active,
                COALESCE(SUM(budget), 0) as total_budget,
                COALESCE(SUM(total_responded), 0) as total_conversions
            FROM marketing_campaigns
        """)).fetchone()

        # Pipeline by stage
        pipeline_by_stage = db.execute(text("""
            SELECT stage,
                   COUNT(*) as count,
                   COALESCE(SUM(expected_value), 0) as total_value
            FROM sales_opportunities
            GROUP BY stage
            ORDER BY CASE stage
                WHEN 'lead' THEN 1 WHEN 'qualified' THEN 2
                WHEN 'proposal' THEN 3 WHEN 'negotiation' THEN 4
                WHEN 'won' THEN 5 WHEN 'lost' THEN 6 END
        """)).fetchall()

        # Win rate
        win_rate_row = db.execute(text("""
            SELECT CASE WHEN COUNT(*) FILTER (WHERE stage IN ('won','lost')) > 0
                        THEN ROUND(100.0 * COUNT(*) FILTER (WHERE stage = 'won') /
                             COUNT(*) FILTER (WHERE stage IN ('won','lost')), 1)
                        ELSE 0 END as win_rate
            FROM sales_opportunities
        """)).fetchone()

        # Recent activities
        recent = db.execute(text("""
            SELECT a.*, o.title as opportunity_title
            FROM opportunity_activities a
            JOIN sales_opportunities o ON a.opportunity_id = o.id
            ORDER BY a.created_at DESC LIMIT 10
        """)).fetchall()

        # Lead scores distribution
        scores_dist = db.execute(text("""
            SELECT grade, COUNT(*) as count
            FROM crm_lead_scores
            GROUP BY grade
            ORDER BY grade
        """)).fetchall()

        kpis_dict = dict(kpis._mapping) if kpis else {}
        kpis_dict['win_rate'] = Decimal(str(win_rate_row.win_rate)) if win_rate_row else Decimal('0')

        return {
            "kpis": kpis_dict,
            "tickets": dict(tickets._mapping) if tickets else {},
            "campaigns": dict(campaigns._mapping) if campaigns else {},
            "pipeline_by_stage": [dict(r._mapping) for r in pipeline_by_stage],
            "recent_activities": [dict(r._mapping) for r in recent],
            "lead_score_distribution": [dict(r._mapping) for r in scores_dist]
        }
    finally:
        db.close()


@router.get("/analytics/conversion", dependencies=[Depends(require_permission("sales.view"))], response_model=Dict[str, Any])
def conversion_analytics(current_user=Depends(get_current_user)):
    """تحليلات معدلات التحويل"""
    db = get_db_connection(current_user.company_id)
    try:
        # Win/Loss rate
        rates = db.execute(text("""
            SELECT
                COUNT(*) as total_closed,
                COUNT(*) FILTER (WHERE stage = 'won') as won,
                COUNT(*) FILTER (WHERE stage = 'lost') as lost,
                CASE WHEN COUNT(*) FILTER (WHERE stage IN ('won','lost')) > 0
                     THEN ROUND(100.0 * COUNT(*) FILTER (WHERE stage = 'won') /
                          COUNT(*) FILTER (WHERE stage IN ('won','lost')), 1) ELSE 0 END as win_rate,
                CASE WHEN COUNT(*) FILTER (WHERE stage IN ('won','lost')) > 0
                     THEN ROUND(100.0 * COUNT(*) FILTER (WHERE stage = 'lost') /
                          COUNT(*) FILTER (WHERE stage IN ('won','lost')), 1) ELSE 0 END as loss_rate,
                COALESCE(AVG(EXTRACT(DAY FROM (updated_at - created_at)))
                    FILTER (WHERE stage = 'won'), 0) as avg_days_to_close
            FROM sales_opportunities
        """)).fetchone()

        # Conversion by source
        by_source = db.execute(text("""
            SELECT COALESCE(source, 'غير محدد') as source,
                   COUNT(*) as total,
                   COUNT(*) FILTER (WHERE stage = 'won') as won,
                   CASE WHEN COUNT(*) > 0
                        THEN ROUND(100.0 * COUNT(*) FILTER (WHERE stage = 'won') / COUNT(*), 1)
                        ELSE 0 END as conversion_rate
            FROM sales_opportunities
            WHERE stage IN ('won', 'lost')
            GROUP BY source
            ORDER BY conversion_rate DESC
        """)).fetchall()

        # Stage-to-stage conversion
        stage_conv = db.execute(text("""
            SELECT stage,
                   COUNT(*) as count,
                   COALESCE(SUM(expected_value), 0) as value
            FROM sales_opportunities
            GROUP BY stage
            ORDER BY CASE stage
                WHEN 'lead' THEN 1 WHEN 'qualified' THEN 2
                WHEN 'proposal' THEN 3 WHEN 'negotiation' THEN 4
                WHEN 'won' THEN 5 WHEN 'lost' THEN 6 END
        """)).fetchall()

        return {
            "win_rate": Decimal(str(rates.win_rate)) if rates else Decimal('0'),
            "loss_rate": Decimal(str(rates.loss_rate)) if rates else Decimal('0'),
            "avg_days_to_close": Decimal(str(rates.avg_days_to_close)) if rates else Decimal('0'),
            "total_closed": rates.total_closed if rates else 0,
            "won": rates.won if rates else 0,
            "lost": rates.lost if rates else 0,
            "by_source": [dict(r._mapping) for r in by_source],
            "stage_distribution": [dict(r._mapping) for r in stage_conv]
        }
    finally:
        db.close()


@router.get("/analytics/campaign-roi", dependencies=[Depends(require_permission("sales.view"))], response_model=Dict[str, Any])
def campaign_roi_analytics(current_user=Depends(get_current_user)):
    """تحليل العائد على الاستثمار في الحملات"""
    db = get_db_connection(current_user.company_id)
    try:
        rows = db.execute(text("""
            SELECT id, name, campaign_type, status, budget,
                   COALESCE(total_sent, 0) as sent,
                   COALESCE(total_opened, 0) as opens,
                   COALESCE(total_clicked, 0) as clicks,
                   COALESCE(total_responded, 0) as conversions,
                   CASE WHEN COALESCE(total_sent, 0) > 0
                        THEN ROUND(100.0 * COALESCE(total_opened, 0) / total_sent, 1) ELSE 0 END as open_rate,
                   CASE WHEN COALESCE(total_opened, 0) > 0
                        THEN ROUND(100.0 * COALESCE(total_clicked, 0) / total_opened, 1) ELSE 0 END as click_rate,
                   CASE WHEN COALESCE(total_sent, 0) > 0
                        THEN ROUND(100.0 * COALESCE(total_responded, 0) / total_sent, 1) ELSE 0 END as conversion_rate,
                   CASE WHEN budget > 0 AND COALESCE(total_responded, 0) > 0
                        THEN ROUND(budget / total_responded, 2) ELSE 0 END as cost_per_conversion,
                   start_date, end_date
            FROM marketing_campaigns
            ORDER BY COALESCE(total_responded, 0) DESC
        """)).fetchall()

        # Summary
        summary = db.execute(text("""
            SELECT
                COALESCE(SUM(budget), 0) as total_investment,
                COALESCE(SUM(total_responded), 0) as total_conversions,
                CASE WHEN SUM(COALESCE(total_responded, 0)) > 0
                     THEN ROUND(SUM(budget) / SUM(total_responded), 2) ELSE 0 END as avg_cpc,
                CASE WHEN SUM(COALESCE(total_sent, 0)) > 0
                     THEN ROUND(100.0 * SUM(COALESCE(total_responded, 0)) / SUM(total_sent), 2)
                     ELSE 0 END as overall_conversion_rate
            FROM marketing_campaigns
        """)).fetchone()

        return {
            "campaigns": [dict(r._mapping) for r in rows],
            "summary": dict(summary._mapping) if summary else {}
        }
    finally:
        db.close()
