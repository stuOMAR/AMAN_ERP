"""
Scheduled Reports & Report Sharing Router
RPT-106: مشاركة التقارير بين المستخدمين
RPT-106b: جدولة التقارير التلقائية (Scheduled Reports)
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from pydantic import BaseModel
import logging
import json

from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import branch_scope_filter_from_scope, require_permission, resolve_branch_scope, validate_branch_access
from utils.audit import log_activity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["Scheduled & Shared Reports"])

# ─── Report Types Registry ────────────────────────────────────────────────

REPORT_TYPES = {
    "profit_loss": {"label": "Profit & Loss / قائمة الدخل", "category": "accounting"},
    "balance_sheet": {"label": "Balance Sheet / الميزانية العمومية", "category": "accounting"},
    "trial_balance": {"label": "Trial Balance / ميزان المراجعة", "category": "accounting"},
    "general_ledger": {"label": "General Ledger / دفتر الأستاذ", "category": "accounting"},
    "cashflow": {"label": "Cash Flow / التدفقات النقدية", "category": "accounting"},
    "sales_summary": {"label": "Sales Summary / ملخص المبيعات", "category": "sales"},
    "sales_aging": {"label": "Aging Report / تقرير أعمار الديون", "category": "sales"},
    "detailed_pl": {"label": "Detailed P&L / أرباح وخسائر تفصيلي", "category": "accounting"},
    "commissions": {"label": "Commissions / تقرير العمولات", "category": "sales"},
    "inventory_valuation": {"label": "Inventory Valuation / تقييم المخزون", "category": "inventory"},
    "payroll_trend": {"label": "Payroll Trend / اتجاه الرواتب", "category": "hr"},
}


# ─── Schemas ──────────────────────────────────────────────────────────────

class ScheduledReportCreate(BaseModel):
    report_name: Optional[str] = None
    report_type: str
    report_config: Optional[dict] = None
    frequency: str  # daily, weekly, monthly
    recipients: List[str]  # list of email addresses (stored as JSONB)
    format: str = "pdf"
    branch_id: Optional[int] = None


class ShareReportRequest(BaseModel):
    report_type: str  # "custom" or "scheduled"
    report_id: int
    shared_with: int  # user_id
    permission: str = "view"
    message: Optional[str] = None


# ═══════════════════════════════════════════════════════════
# Scheduled Reports CRUD
# ═══════════════════════════════════════════════════════════

@router.get("/scheduled/types", response_model=Dict[str, Any])
def list_report_types():
    """List available report types for scheduling."""
    return REPORT_TYPES


@router.get("/scheduled/", dependencies=[Depends(require_permission(["reports.view"]))], response_model=Dict[str, Any])
def list_scheduled_reports(
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """List all scheduled reports."""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    with transactional(current_user.company_id) as db:
        params = {"uid": current_user.id}
        branch_filter = branch_scope_filter_from_scope(branch_scope, "sr.branch_id", params)

        query = f"""
            SELECT sr.*, b.branch_name, u.full_name as created_by_name
            FROM scheduled_reports sr
            LEFT JOIN branches b ON sr.branch_id = b.id
            LEFT JOIN company_users u ON sr.created_by = u.id
            WHERE (sr.created_by = :uid
                   OR sr.id IN (SELECT report_id FROM shared_reports WHERE shared_with = :uid AND report_type = 'scheduled'))
            {branch_filter}
            ORDER BY sr.created_at DESC
        """

        reports = [dict(row._mapping) for row in db.execute(text(query), params).fetchall()]
        return reports


@router.post("/scheduled/", dependencies=[Depends(require_permission(["reports.create"]))], response_model=Dict[str, Any])
def create_scheduled_report(
    data: ScheduledReportCreate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """Create a new scheduled report."""
    if data.report_type not in REPORT_TYPES:
        raise HTTPException(status_code=400, detail=i18n_message("invalid_report_type", request))
    if data.frequency not in ("daily", "weekly", "monthly"):
        raise HTTPException(**http_error(400, "frequency_must_be", request))

    with transactional(current_user.company_id) as db:
        try:
            if data.branch_id:
                validate_branch_access(current_user, data.branch_id)
    
            next_run = _calculate_next_run(data.frequency)
            report_name = data.report_name or REPORT_TYPES[data.report_type]["label"]
    
            result = db.execute(text("""
                INSERT INTO scheduled_reports
                (report_name, report_type, report_config, frequency, recipients, format, branch_id, created_by, next_run_at)
                VALUES (:name, :type, :config, :freq, :recipients, :fmt, :branch, :uid, :next_run)
                RETURNING id, report_name, report_type, frequency, format, next_run_at, is_active, created_at
            """), {
                "name": report_name,
                "type": data.report_type,
                "config": json.dumps(data.report_config or {}),
                "freq": data.frequency,
                "recipients": json.dumps(data.recipients),
                "fmt": data.format,
                "branch": data.branch_id,
                "uid": current_user.id,
                "next_run": next_run,
            })
            row = result.fetchone()
            log_activity(
                db, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
                action="reports.scheduled.create", resource_type="scheduled_report",
                resource_id=str(dict(row._mapping).get("id", "")),
                details={"report_type": data.report_type, "frequency": data.frequency},
                request=request
            )
            return dict(row._mapping)
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(400, "invalid_data"))


@router.put("/scheduled/{report_id}", dependencies=[Depends(require_permission(["reports.edit"]))], response_model=Dict[str, Any])
def update_scheduled_report(
    report_id: int,
    data: ScheduledReportCreate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """Update a scheduled report."""
    with transactional(current_user.company_id) as db:
        next_run = _calculate_next_run(data.frequency)
        report_name = data.report_name or REPORT_TYPES.get(data.report_type, {}).get("label", data.report_type)

        result = db.execute(text("""
            UPDATE scheduled_reports SET
                report_name = :name, report_type = :type, report_config = :config,
                frequency = :freq, recipients = :recipients, format = :fmt,
                branch_id = :branch, next_run_at = :next_run, updated_at = NOW()
            WHERE id = :id AND created_by = :uid
        """), {
            "name": report_name,
            "type": data.report_type,
            "config": json.dumps(data.report_config or {}),
            "freq": data.frequency,
            "recipients": json.dumps(data.recipients),
            "fmt": data.format,
            "branch": data.branch_id,
            "next_run": next_run,
            "id": report_id,
            "uid": current_user.id,
        })
        if result.rowcount == 0:
            raise HTTPException(**http_error(404, "report_not_found_unauthorized", request))
        log_activity(
            db, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="reports.scheduled.update", resource_type="scheduled_report",
            resource_id=str(report_id),
            details={"report_type": data.report_type, "frequency": data.frequency},
            request=request
        )
        return {"message": i18n_message("scheduled_report_updated", request)}


@router.delete("/scheduled/{report_id}", dependencies=[Depends(require_permission(["reports.delete"]))], response_model=Dict[str, Any])
def delete_scheduled_report(
    report_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """Delete a scheduled report."""
    with transactional(current_user.company_id) as db:
        db.execute(text("DELETE FROM shared_reports WHERE report_type='scheduled' AND report_id=:id"), {"id": report_id})
        result = db.execute(text("DELETE FROM scheduled_reports WHERE id = :id AND created_by = :uid"),
                            {"id": report_id, "uid": current_user.id})
        if result.rowcount == 0:
            raise HTTPException(**http_error(404, "report_not_found_unauthorized", request))
        log_activity(
            db, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="reports.scheduled.delete", resource_type="scheduled_report",
            resource_id=str(report_id), details={},
            request=request
        )
        return {"message": i18n_message("scheduled_report_deleted", request)}


@router.put("/scheduled/{report_id}/toggle", dependencies=[Depends(require_permission(["reports.edit"]))], response_model=Dict[str, Any])
def toggle_scheduled_report(
    report_id: int,
    active: bool,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """Activate/Deactivate a scheduled report."""
    with transactional(current_user.company_id) as db:
        result = db.execute(
            text("UPDATE scheduled_reports SET is_active = :active, updated_at = NOW() WHERE id = :id"),
            {"active": active, "id": report_id}
        )
        if result.rowcount == 0:
            raise HTTPException(**http_error(404, "report_not_found", request))
        log_activity(
            db, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="reports.scheduled.toggle", resource_type="scheduled_report",
            resource_id=str(report_id), details={"is_active": active},
            request=request
        )
        return {"message": i18n_message("report_activated_status", request)}


@router.post("/scheduled/{report_id}/run", dependencies=[Depends(require_permission(["reports.create"]))], response_model=Dict[str, Any])
def run_scheduled_report_now(
    report_id: int,
    background_tasks: BackgroundTasks,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """Manually trigger a scheduled report immediately."""
    with transactional(current_user.company_id) as db:
        report = db.execute(text("SELECT * FROM scheduled_reports WHERE id=:id"), {"id": report_id}).fetchone()
        if not report:
            raise HTTPException(**http_error(404, "report_not_found", request))

        background_tasks.add_task(_execute_scheduled_report, current_user.company_id, dict(report._mapping))
        log_activity(
            db, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="reports.scheduled.run_now", resource_type="scheduled_report",
            resource_id=str(report_id), details={},
            request=request
        )
        return {"message": i18n_message("report_execution_started", request)}


# ═══════════════════════════════════════════════════════════
# RPT-106: Report Sharing
# ═══════════════════════════════════════════════════════════

@router.post("/share", dependencies=[Depends(require_permission(["reports.view"]))], response_model=Dict[str, Any])
def share_report(
    data: ShareReportRequest,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """Share a report with another user."""
    if data.report_type not in ("custom", "scheduled"):
        raise HTTPException(**http_error(400, "report_type_must_be", request))

    with transactional(current_user.company_id) as db:
        try:
            # Verify user exists
            user = db.execute(text("SELECT id, full_name FROM company_users WHERE id=:id"), {"id": data.shared_with}).fetchone()
            if not user:
                raise HTTPException(**http_error(404, "user_not_found", request))
    
            # Verify report exists — SEC-003: table is from controlled whitelist, not user input
            _ALLOWED_TABLES = {"custom_reports", "scheduled_reports"}
            table = "custom_reports" if data.report_type == "custom" else "scheduled_reports"
            assert table in _ALLOWED_TABLES
            report = db.execute(text(f"SELECT id FROM {table} WHERE id=:id"), {"id": data.report_id}).fetchone()
            if not report:
                raise HTTPException(**http_error(404, "report_not_found", request))
    
            db.execute(text("""
                INSERT INTO shared_reports (report_type, report_id, shared_by, shared_with, permission, message)
                VALUES (:rt, :rid, :by, :with, :perm, :msg)
                ON CONFLICT (report_type, report_id, shared_with)
                DO UPDATE SET permission = EXCLUDED.permission, message = EXCLUDED.message
            """), {
                "rt": data.report_type, "rid": data.report_id,
                "by": current_user.id, "with": data.shared_with,
                "perm": data.permission, "msg": data.message,
            })
            log_activity(
                db, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
                action="reports.share.create", resource_type="shared_report",
                resource_id=str(data.report_id),
                details={"report_type": data.report_type, "shared_with": data.shared_with},
                request=request
            )
            return {"message": i18n_message("report_shared_success", request)}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(400, "invalid_data"))


@router.delete("/share/{share_id}", dependencies=[Depends(require_permission(["reports.view"]))], response_model=Dict[str, Any])
def unshare_report(share_id: int, request: Request, current_user: dict = Depends(get_current_user)):
    """Remove report sharing."""
    with transactional(current_user.company_id) as db:
        result = db.execute(text("DELETE FROM shared_reports WHERE id=:id AND shared_by=:uid"),
                            {"id": share_id, "uid": current_user.id})
        if result.rowcount == 0:
            raise HTTPException(**http_error(404, "share_not_found_unauthorized", request))
        log_activity(
            db, user_id=current_user.id, username=getattr(current_user, "username", "unknown"),
            action="reports.share.delete", resource_type="shared_report",
            resource_id=str(share_id), details={},
            request=request
        )
        return {"message": i18n_message("share_removed", request)}


@router.get("/shared/", dependencies=[Depends(require_permission(["reports.view"]))], response_model=List[Dict[str, Any]])
def list_shared_reports(current_user: dict = Depends(get_current_user)):
    """List reports shared with the current user."""
    with transactional(current_user.company_id) as db:
        result = db.execute(text("""
            SELECT sr.*, u.full_name as shared_by_name,
                   CASE sr.report_type
                       WHEN 'custom' THEN (SELECT report_name FROM custom_reports WHERE id = sr.report_id)
                       WHEN 'scheduled' THEN (SELECT COALESCE(report_name, report_type) FROM scheduled_reports WHERE id = sr.report_id)
                   END as report_name
            FROM shared_reports sr
            JOIN company_users u ON sr.shared_by = u.id
            WHERE sr.shared_with = :uid
            ORDER BY sr.created_at DESC
        """), {"uid": current_user.id}).fetchall()
        return [dict(row._mapping) for row in result]


@router.get("/shared/by-report/{report_type}/{report_id}", dependencies=[Depends(require_permission(["reports.view"]))], response_model=List[Dict[str, Any]])
def list_report_shares(report_type: str, report_id: int, current_user: dict = Depends(get_current_user)):
    """List users a report is shared with."""
    with transactional(current_user.company_id) as db:
        result = db.execute(text("""
            SELECT sr.*, u.full_name as shared_with_name, u.email as shared_with_email
            FROM shared_reports sr
            JOIN company_users u ON sr.shared_with = u.id
            WHERE sr.report_type = :rt AND sr.report_id = :rid
            ORDER BY sr.created_at DESC
        """), {"rt": report_type, "rid": report_id}).fetchall()
        return [dict(row._mapping) for row in result]


@router.get("/users/", dependencies=[Depends(require_permission(["reports.view"]))], response_model=List[Dict[str, Any]])
def list_users_for_sharing(current_user: dict = Depends(get_current_user)):
    """List users that reports can be shared with."""
    with transactional(current_user.company_id) as db:
        result = db.execute(text("""
            SELECT id, full_name, email, role FROM company_users
            WHERE id != :uid AND is_active = true
            ORDER BY full_name
        """), {"uid": current_user.id}).fetchall()
        return [dict(row._mapping) for row in result]


# ─── Helpers ──────────────────────────────────────────────────────────────

def _calculate_next_run(frequency: str) -> datetime:
    """Calculate next run time based on frequency."""
    now = datetime.now()
    if frequency == "daily":
        next_run = (now + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
    elif frequency == "weekly":
        days_ahead = 7 - now.weekday()
        if days_ahead == 0:
            days_ahead = 7
        next_run = (now + timedelta(days=days_ahead)).replace(hour=6, minute=0, second=0, microsecond=0)
    elif frequency == "monthly":
        if now.month == 12:
            next_run = now.replace(year=now.year + 1, month=1, day=1, hour=6, minute=0, second=0, microsecond=0)
        else:
            next_run = now.replace(month=now.month + 1, day=1, hour=6, minute=0, second=0, microsecond=0)
    else:
        next_run = now + timedelta(days=1)
    return next_run


def _execute_scheduled_report(company_id: str, report_config: dict):
    """Execute a scheduled report in the background (generate + log status)."""
    db = get_db_connection(company_id)
    report_id = report_config.get("id")
    try:
        report_type = report_config["report_type"]
        logger.info(f"Executing scheduled report #{report_id} ({report_type}) for company {company_id}")

        db.execute(text("UPDATE scheduled_reports SET last_status = 'running', updated_at = NOW() WHERE id = :id"),
                   {"id": report_id})
        db.commit()

        # Parse report_config for parameters
        config = report_config.get("report_config") or {}
        if isinstance(config, str):
            config = json.loads(config)

        # Default date range: last 30 days
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        if config:
            start_date = config.get('start_date', start_date)
            end_date = config.get('end_date', end_date)

        branch_id = config.get('branch_id') or report_config.get('branch_id')
        account_id = config.get('account_id')

        # Import report helpers
        from routers.reports import (
            _get_profit_loss_data,
            _get_balance_sheet_data,
            _get_trial_balance_data,
            _get_cashflow_data,
            _get_general_ledger_data,
        )

        # Dispatcher mapping report_type to helper
        REPORT_DISPATCHERS = {
            'profit_loss': lambda: _get_profit_loss_data(db, start_date, end_date, branch_id),
            'balance_sheet': lambda: _get_balance_sheet_data(db, end_date, branch_id),
            'trial_balance': lambda: _get_trial_balance_data(db, start_date, end_date, branch_id),
            'cashflow': lambda: _get_cashflow_data(db, start_date, end_date, branch_id),
            'general_ledger': lambda: _get_general_ledger_data(db, account_id, start_date, end_date, branch_id),
        }

        dispatcher = REPORT_DISPATCHERS.get(report_type)
        if not dispatcher:
            db.execute(text("""
                UPDATE scheduled_reports
                SET last_status = 'failed', last_run_at = NOW(), updated_at = NOW()
                WHERE id = :id
            """), {"id": report_id})
            db.commit()
            logger.warning(f"Unsupported report type '{report_type}' for scheduled report #{report_id}")
            return

        result_data = dispatcher()

        # Store result in scheduled_report_results
        db.execute(text("""
            INSERT INTO scheduled_report_results
            (scheduled_report_id, report_data, generated_at, status)
            VALUES (:report_id, :data, NOW(), 'completed')
        """), {
            "report_id": report_id,
            "data": json.dumps(result_data, default=str),
        })

        # Update scheduled_reports metadata
        frequency = report_config["frequency"]
        next_run = _calculate_next_run(frequency)

        db.execute(text("""
            UPDATE scheduled_reports SET
                last_run_at = NOW(), last_status = 'completed',
                next_run_at = :next_run, updated_at = NOW()
            WHERE id = :id
        """), {"id": report_id, "next_run": next_run})
        db.commit()
        logger.info(f"Scheduled report #{report_id} completed. Next run: {next_run}")
    except Exception as e:
        logger.error(f"Scheduled report #{report_id} failed: {e}")
        try:
            db.rollback()
            db.execute(text("UPDATE scheduled_reports SET last_status = 'failed', last_run_at = NOW(), updated_at = NOW() WHERE id = :id"),
                       {"id": report_id})
            db.commit()
        except Exception:
            pass
    finally:
        db.close()


# ─── Background Scheduler Bootstrap ─────────────────────────────────────

def start_report_scheduler(app):
    """
    Start APScheduler to run scheduled reports.
    Call this from main.py on startup.

    TASK-028: gated by settings.SCHEDULER_MODE — web processes skip starting
    this when the mode is not `in_process`, so the dedicated worker is the
    single authority for job firings in multi-replica deployments.
    """
    try:
        from config import settings
        mode = (getattr(settings, "SCHEDULER_MODE", "in_process") or "in_process").lower()
        if mode != "in_process":
            logger.info("start_report_scheduler skipped (SCHEDULER_MODE=%s)", mode)
            return

        from apscheduler.schedulers.background import BackgroundScheduler

        scheduler = BackgroundScheduler()

        def check_and_run_reports():
            """Check for reports due and execute them."""
            from database import get_all_company_ids
            try:
                company_ids = get_all_company_ids()
                for company_id in company_ids:
                    with transactional(company_id) as db:
                        due_reports = db.execute(text("""
                            SELECT * FROM scheduled_reports
                            WHERE is_active = true AND next_run_at <= NOW()
                            ORDER BY next_run_at
                            LIMIT 10
                        """)).fetchall()
                        for report in due_reports:
                            _execute_scheduled_report(company_id, dict(report._mapping))
            except Exception as e:
                logger.error(f"Scheduler check failed: {e}")

        scheduler.add_job(check_and_run_reports, 'interval', minutes=15, id='report_scheduler')
        scheduler.start()
        logger.info("Report scheduler started (checks every 15 min)")

        import atexit
        atexit.register(scheduler.shutdown)

    except ImportError:
        logger.warning("APScheduler not installed — scheduled reports will not auto-run")
    except Exception as e:
        logger.error(f"Failed to start report scheduler: {e}")
