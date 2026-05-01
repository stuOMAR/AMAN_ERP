"""projects sub-router — split from monolithic projects.py (T6.3).

Mounted under the parent router via projects/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request, File, UploadFile
from utils.i18n import http_error, i18n_message
import os
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import require_permission, validate_branch_access, require_module
from utils.accounting import (
    generate_sequential_number, get_mapped_account_id,
    get_base_currency, compute_line_amounts, compute_invoice_totals
)
from utils.audit import log_activity
from utils.fiscal_lock import check_fiscal_period_open
from sqlalchemy import text
from services.gl_service import create_journal_entry as gl_create_journal_entry
import logging

logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')
def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')

from schemas.projects import (
    ProjectCreate, ProjectUpdate, TaskCreate, TaskUpdate,
    ProjectExpenseCreate, ProjectRevenueCreate,
    TimesheetCreate, TimesheetUpdate, TimesheetApprove,
    ProjectInvoiceCreate, ChangeOrderCreate, ChangeOrderUpdate, ProjectCloseRequest,
    ProjectRiskCreate, ProjectRiskUpdate, TaskDependencyCreate
)
from schemas.timetracking import (
    TimesheetEntryCreate, TimesheetEntryUpdate,
    WeeklySubmitRequest, RejectRequest
)
from schemas.resource import AllocationCreate, AllocationUpdate

router = APIRouter()

from .core import _D2, _D4, _dec

@router.get("/reports/profitability", dependencies=[Depends(require_permission("projects.view"))], response_model=Dict[str, Any])
async def report_project_profitability(
    status_filter: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير ربحية المشاريع"""
    db = get_db_connection(current_user.company_id)
    try:
        where = "WHERE 1=1"
        params = {}
        if status_filter:
            where += " AND p.status = :status"
            params["status"] = status_filter

        rows = db.execute(text(f"""
            SELECT p.id, p.project_code, p.project_name, p.status,
                   p.planned_budget, p.progress_percentage,
                   p.start_date, p.end_date,
                   COALESCE(exp.total, 0) as total_expenses,
                   COALESCE(rev.total, 0) as total_revenues
            FROM projects p
            LEFT JOIN (
                SELECT project_id, SUM(amount) as total
                FROM project_expenses WHERE status != 'rejected'
                GROUP BY project_id
            ) exp ON exp.project_id = p.id
            LEFT JOIN (
                SELECT project_id, SUM(amount) as total
                FROM project_revenues WHERE status != 'rejected'
                GROUP BY project_id
            ) rev ON rev.project_id = p.id
            {where}
            ORDER BY (COALESCE(rev.total, 0) - COALESCE(exp.total, 0)) DESC
        """), params).fetchall()

        projects_list = []
        total_revenue_sum = Decimal('0')
        total_expense_sum = Decimal('0')
        for r in rows:
            m = r._mapping
            rev = _dec(m["total_revenues"] or 0)
            exp = _dec(m["total_expenses"] or 0)
            net = rev - exp
            margin = (net / rev * Decimal('100')) if rev > 0 else Decimal('0')
            budget = _dec(m["planned_budget"] or 0)
            budget_var = budget - exp

            projects_list.append({
                "project_id": m["id"],
                "project_code": m["project_code"],
                "project_name": m["project_name"],
                "status": m["status"],
                "planned_budget": float(budget.quantize(_D2)),
                "total_expenses": float(exp.quantize(_D2)),
                "total_revenues": float(rev.quantize(_D2)),
                "net_profit": float(net.quantize(_D2)),
                "margin_pct": float(margin.quantize(_D2)),
                "budget_variance": float(budget_var.quantize(_D2)),
                "progress": float(m["progress_percentage"] or 0),
            })
            total_revenue_sum += rev
            total_expense_sum += exp

        total_net = total_revenue_sum - total_expense_sum
        avg_margin = (total_net / total_revenue_sum * Decimal('100')) if total_revenue_sum > 0 else Decimal('0')

        return {
            "report_name": "تقرير ربحية المشاريع",
            "projects": projects_list,
            "totals": {
                "total_revenue": float(total_revenue_sum.quantize(_D2)),
                "total_expense": float(total_expense_sum.quantize(_D2)),
                "total_profit": float(total_net.quantize(_D2)),
                "avg_margin_pct": float(avg_margin.quantize(_D2)),
                "project_count": len(projects_list),
            }
        }
    finally:
        db.close()

@router.get("/reports/variance", dependencies=[Depends(require_permission("projects.view"))], response_model=Dict[str, Any])
async def report_project_variance(current_user: dict = Depends(get_current_user)):
    """تقرير انحراف المشاريع (Budget vs Actual)"""
    db = get_db_connection(current_user.company_id)
    try:
        rows = db.execute(text("""
            SELECT p.id, p.project_code, p.project_name, p.status,
                   p.planned_budget, p.progress_percentage,
                   p.start_date, p.end_date,
                   COALESCE(exp.total, 0) as actual_expenses,
                   COALESCE(ts.total_hours, 0) as actual_hours,
                   COALESCE(tk.planned_hours, 0) as planned_hours
            FROM projects p
            LEFT JOIN (
                SELECT project_id, SUM(amount) as total
                FROM project_expenses WHERE status != 'rejected'
                GROUP BY project_id
            ) exp ON exp.project_id = p.id
            LEFT JOIN (
                SELECT project_id, SUM(hours) as total_hours
                FROM project_timesheets WHERE status = 'approved'
                GROUP BY project_id
            ) ts ON ts.project_id = p.id
            LEFT JOIN (
                SELECT project_id, SUM(planned_hours) as planned_hours
                FROM project_tasks
                GROUP BY project_id
            ) tk ON tk.project_id = p.id
            WHERE p.status != 'cancelled'
            ORDER BY p.id
        """)).fetchall()

        projects_list = []
        for r in rows:
            m = r._mapping
            budget = _dec(m["planned_budget"] or 0)
            actual = _dec(m["actual_expenses"] or 0)
            cost_var = budget - actual
            cost_var_pct = (cost_var / budget * Decimal('100')) if budget > 0 else Decimal('0')

            planned_h = _dec(m["planned_hours"] or 0)
            actual_h = _dec(m["actual_hours"] or 0)
            hour_var = planned_h - actual_h

            schedule_var_days = None
            if m["end_date"] and m["status"] not in ["completed", "cancelled"]:
                schedule_var_days = (m["end_date"] - date.today()).days

            projects_list.append({
                "project_id": m["id"],
                "project_code": m["project_code"],
                "project_name": m["project_name"],
                "status": m["status"],
                "planned_budget": float(budget.quantize(_D2)),
                "actual_cost": float(actual.quantize(_D2)),
                "cost_variance": float(cost_var.quantize(_D2)),
                "cost_variance_pct": float(cost_var_pct.quantize(_D2)),
                "planned_hours": float(planned_h.quantize(_D2)),
                "actual_hours": float(actual_h.quantize(_D2)),
                "hours_variance": float(hour_var.quantize(_D2)),
                "progress": float(m["progress_percentage"] or 0),
                "schedule_days_remaining": schedule_var_days,
                "is_over_budget": actual > budget if budget > 0 else False,
                "is_behind_schedule": schedule_var_days is not None and schedule_var_days < 0,
            })

        overbudget = sum(1 for p in projects_list if p["is_over_budget"])
        behind = sum(1 for p in projects_list if p["is_behind_schedule"])

        return {
            "report_name": "تقرير انحراف المشاريع",
            "projects": projects_list,
            "summary": {
                "total_projects": len(projects_list),
                "over_budget_count": overbudget,
                "behind_schedule_count": behind,
                "on_track_count": len(projects_list) - overbudget - behind,
            }
        }
    finally:
        db.close()

@router.get("/reports/resource-utilization", dependencies=[Depends(require_permission("projects.view"))], response_model=Dict[str, Any])
async def report_resource_utilization(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير استخدام الموارد عبر المشاريع"""
    db = get_db_connection(current_user.company_id)
    try:
        date_filter = ""
        params = {}
        if start_date:
            date_filter += " AND ts.date >= :start"
            params["start"] = start_date
        if end_date:
            date_filter += " AND ts.date <= :end"
            params["end"] = end_date

        rows = db.execute(text(f"""
            SELECT u.id as user_id, u.full_name,
                   COUNT(DISTINCT ts.project_id) as projects_count,
                   SUM(ts.hours) as total_hours,
                   AVG(ts.hours) as avg_daily_hours,
                   COUNT(DISTINCT ts.date) as working_days
            FROM project_timesheets ts
            JOIN company_users u ON ts.employee_id = u.id
            WHERE ts.status = 'approved' {date_filter}
            GROUP BY u.id, u.full_name
            ORDER BY total_hours DESC
        """), params).fetchall()

        resources = []
        for r in rows:
            m = r._mapping
            total_h = _dec(m["total_hours"] or 0)
            working_days = int(m["working_days"] or 1)
            standard_hours = _dec(working_days * 8)
            utilization = (total_h / standard_hours * Decimal('100')) if standard_hours > 0 else Decimal('0')

            resources.append({
                "user_id": m["user_id"],
                "name": m["full_name"],
                "projects_count": m["projects_count"],
                "total_hours": float(total_h.quantize(_D2)),
                "avg_daily_hours": round(float(m["avg_daily_hours"] or 0), 2),
                "working_days": working_days,
                "utilization_pct": float(utilization.quantize(_D2)),
            })

        return {
            "report_name": "تقرير استخدام الموارد",
            "period": {
                "start": str(start_date) if start_date else "All",
                "end": str(end_date) if end_date else "All"
            },
            "resources": resources,
        }
    finally:
        db.close()

# ═══════════════════════════════════════════════════════════

@router.get("/alerts/overdue-tasks", dependencies=[Depends(require_permission("projects.view"))], response_model=Dict[str, Any])
async def get_overdue_tasks(current_user: dict = Depends(get_current_user)):
    """
    المهام المتأخرة: المهام التي تجاوزت تاريخ الانتهاء ولم تكتمل بعد.
    """
    db = get_db_connection(current_user.company_id)
    try:
        rows = db.execute(text("""
            SELECT t.id, t.task_name, t.end_date, t.status,
                   t.progress,
                   p.id as project_id, p.project_code, p.project_name,
                   COALESCE(u.full_name, '') as assigned_to_name,
                   (CURRENT_DATE - t.end_date) as days_overdue
            FROM project_tasks t
            JOIN projects p ON t.project_id = p.id
            LEFT JOIN company_users u ON t.assigned_to = u.id
            WHERE t.end_date < CURRENT_DATE
              AND t.status NOT IN ('completed', 'cancelled')
              AND p.status NOT IN ('completed', 'cancelled')
            ORDER BY days_overdue DESC
        """)).fetchall()

        tasks_list = [dict(r._mapping) for r in rows]

        return {
            "alert_type": "overdue_tasks",
            "count": len(tasks_list),
            "tasks": tasks_list,
            "message": i18n_message("overdue_tasks_attention_count", count=len(tasks_list)) if tasks_list else i18n_message("overdue_tasks_none"),
        }
    finally:
        db.close()

@router.get("/alerts/over-budget", dependencies=[Depends(require_permission("projects.view"))], response_model=Dict[str, Any])
async def get_over_budget_projects(current_user: dict = Depends(get_current_user)):
    """المشاريع التي تجاوزت ميزانيتها المخططة."""
    db = get_db_connection(current_user.company_id)
    try:
        rows = db.execute(text("""
            SELECT p.id, p.project_code, p.project_name, p.status,
                   p.planned_budget,
                   COALESCE(exp.total, 0) as actual_cost,
                   COALESCE(exp.total, 0) - p.planned_budget as overage,
                   CASE WHEN p.planned_budget > 0
                        THEN ROUND(((COALESCE(exp.total,0) - p.planned_budget) / p.planned_budget * 100)::numeric, 1)
                        ELSE 0 END as overage_pct,
                   p.progress_percentage
            FROM projects p
            LEFT JOIN (
                SELECT project_id, SUM(amount) as total
                FROM project_expenses WHERE status != 'rejected'
                GROUP BY project_id
            ) exp ON exp.project_id = p.id
            WHERE p.planned_budget > 0
              AND COALESCE(exp.total, 0) > p.planned_budget
              AND p.status NOT IN ('completed', 'cancelled')
            ORDER BY overage_pct DESC
        """)).fetchall()

        projects_list = [dict(r._mapping) for r in rows]

        return {
            "alert_type": "over_budget",
            "count": len(projects_list),
            "projects": projects_list,
            "message": i18n_message("over_budget_projects_count", count=len(projects_list)) if projects_list else i18n_message("over_budget_projects_none"),
        }
    finally:
        db.close()

@router.get("/alerts/dashboard", dependencies=[Depends(require_permission("projects.view"))], response_model=Dict[str, Any])
async def get_alerts_dashboard(current_user: dict = Depends(get_current_user)):
    """
    لوحة تنبيهات المشاريع الشاملة:
    - مهام متأخرة
    - مشاريع تجاوزت الميزانية
    - مشاريع قاربت على الموعد النهائي (<14 يوم)
    - مشاريع تجاوزت الموعد النهائي
    """
    db = get_db_connection(current_user.company_id)
    try:
        today = date.today()

        # Overdue tasks
        overdue_tasks_count = db.execute(text("""
            SELECT COUNT(*) FROM project_tasks t
            JOIN projects p ON t.project_id = p.id
            WHERE t.end_date < CURRENT_DATE
              AND t.status NOT IN ('completed', 'cancelled')
              AND p.status NOT IN ('completed', 'cancelled')
        """)).scalar()

        # Over-budget projects
        over_budget_count = db.execute(text("""
            SELECT COUNT(*) FROM projects p
            LEFT JOIN (
                SELECT project_id, SUM(amount) as total FROM project_expenses
                WHERE status != 'rejected' GROUP BY project_id
            ) exp ON exp.project_id = p.id
            WHERE p.planned_budget > 0
              AND COALESCE(exp.total,0) > p.planned_budget
              AND p.status NOT IN ('completed','cancelled')
        """)).scalar()

        # Projects ending within 14 days
        due_soon = db.execute(text("""
            SELECT id, project_code, project_name, end_date,
                   (end_date - CURRENT_DATE) as days_remaining,
                   progress_percentage
            FROM projects
            WHERE end_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '14 days'
              AND status NOT IN ('completed', 'cancelled')
            ORDER BY end_date
        """)).fetchall()

        # Projects past end_date
        overdue_projects = db.execute(text("""
            SELECT id, project_code, project_name, end_date,
                   (CURRENT_DATE - end_date) as days_overdue,
                   progress_percentage
            FROM projects
            WHERE end_date < CURRENT_DATE
              AND status NOT IN ('completed', 'cancelled')
            ORDER BY days_overdue DESC
        """)).fetchall()

        # Pending change orders
        pending_cos = db.execute(text("""
            SELECT COUNT(*) FROM project_change_orders
            WHERE status = 'pending'
        """)).scalar() or 0

        alerts = []
        if overdue_tasks_count:
            alerts.append({"type": "overdue_tasks", "severity": "high",
                           "message": i18n_message("overdue_tasks_count", count=overdue_tasks_count), "count": overdue_tasks_count})
        if over_budget_count:
            alerts.append({"type": "over_budget", "severity": "high",
                           "message": i18n_message("over_budget_count", count=over_budget_count), "count": over_budget_count})
        if overdue_projects:
            alerts.append({"type": "overdue_projects", "severity": "critical",
                           "message": i18n_message("overdue_projects_count", count=len(overdue_projects)), "count": len(overdue_projects)})
        if due_soon:
            alerts.append({"type": "due_soon", "severity": "medium",
                           "message": i18n_message("projects_due_soon_14_days_count", count=len(due_soon)), "count": len(due_soon)})
        if pending_cos:
            alerts.append({"type": "pending_change_orders", "severity": "low",
                           "message": i18n_message("pending_change_orders_count", count=pending_cos), "count": pending_cos})

        return {
            "total_alerts": len(alerts),
            "alerts": alerts,
            "details": {
                "overdue_tasks_count": int(overdue_tasks_count or 0),
                "over_budget_count": int(over_budget_count or 0),
                "overdue_projects": [dict(r._mapping) for r in overdue_projects],
                "due_soon_projects": [dict(r._mapping) for r in due_soon],
                "pending_change_orders": int(pending_cos),
            }
        }
    finally:
        db.close()


# ===================== B5: Project Risks =====================

