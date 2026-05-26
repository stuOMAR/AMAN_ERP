"""projects sub-router — split from monolithic projects.py (T6.3).

Mounted under the parent router via projects/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from utils.i18n import http_error, i18n_message
from typing import Any, Dict, List, Optional
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from database import get_db_connection
from routers.auth import get_current_user
from utils.permissions import require_permission
from utils.accounting import (
    get_mapped_account_id,
    get_base_currency
)
from utils.audit import log_activity
from utils.fiscal_lock import check_fiscal_period_open
from sqlalchemy import text
from services.gl_service import create_journal_entry as gl_create_journal_entry
from utils.permissions import validate_branch_access
from utils.tax_precision import money_str, qty_str, rate_str, require_idempotency_key
import logging

logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')
def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')

from schemas.projects import (  # noqa: E402
    TimesheetCreate, TimesheetUpdate, TimesheetApprove
)
from schemas.timetracking import (  # noqa: E402
    TimesheetEntryCreate, TimesheetEntryUpdate,
    WeeklySubmitRequest, RejectRequest
)

router = APIRouter()

from .core import _D2, _dec, _fetch_timesheet_entry  # noqa: E402

def _current_employee_id(db, current_user: dict) -> int:
    employee_id = db.execute(text(
        "SELECT id FROM employees WHERE user_id = :uid LIMIT 1"
    ), {"uid": current_user.id}).scalar()
    if not employee_id:
        raise HTTPException(status_code=400, detail=i18n_message("employee_profile_required"))
    return employee_id

def _serialize_time_entry(row_or_dict: Any) -> Dict[str, Any]:
    data = dict(row_or_dict._mapping) if hasattr(row_or_dict, "_mapping") else dict(row_or_dict)
    if data.get("hours") is not None:
        data["hours"] = qty_str(data["hours"])
    if data.get("billing_rate") is not None:
        data["billing_rate"] = money_str(data["billing_rate"])
    return data

@router.get("/timetracking", dependencies=[Depends(require_permission("projects.time_view"))], response_model=List[Dict[str, Any]])
async def list_own_time_entries(
    project_id: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    entry_status: Optional[str] = None,
    page: int = 1,
    page_size: int = 25,
    current_user: dict = Depends(get_current_user)
):
    """جلب سجلات الوقت الخاصة بالمستخدم (قابلة للفلترة)"""
    db = get_db_connection(current_user.company_id)
    try:
        page = max(page, 1)
        page_size = min(max(page_size, 1), 100)
        filters = ["te.employee_id = :employee_id"]
        params: dict = {
            "employee_id": _current_employee_id(db, current_user),
            "limit": page_size,
            "offset": (page - 1) * page_size,
        }
        if project_id:
            filters.append("te.project_id = :project_id")
            params["project_id"] = project_id
        if date_from:
            filters.append("te.date >= :date_from")
            params["date_from"] = date_from
        if date_to:
            filters.append("te.date <= :date_to")
            params["date_to"] = date_to
        if entry_status:
            filters.append("te.status = :entry_status")
            params["entry_status"] = entry_status
        where = " AND ".join(filters)
        try:
            rows = db.execute(text(f"""
                SELECT te.*,
                       e.full_name  AS employee_name,
                       p.project_name,
                       pt.task_name,
                       ae.full_name AS approver_name
                FROM   timesheet_entries te
                LEFT JOIN employees e  ON e.id  = te.employee_id
                LEFT JOIN projects  p  ON p.id  = te.project_id
                LEFT JOIN project_tasks pt ON pt.id = te.task_id
                LEFT JOIN employees ae ON ae.id = te.approved_by
                WHERE  {where}
                ORDER BY te.date DESC
                LIMIT :limit OFFSET :offset
            """), params).fetchall()
        except Exception as e:
            db.rollback()
            if "does not exist" in str(e):
                return []
            raise
        return [_serialize_time_entry(r) for r in rows]
    finally:
        db.close()


@router.get("/timetracking/week-summary", dependencies=[Depends(require_permission("projects.time_view"))], response_model=Dict[str, Any])
async def get_own_week_summary(
    date_from: date,
    date_to: date,
    project_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """Backend-owned weekly time totals for the current employee."""
    db = get_db_connection(current_user.company_id)
    try:
        filters = [
            "te.employee_id = :employee_id",
            "te.date >= :date_from",
            "te.date <= :date_to",
        ]
        params: dict = {
            "employee_id": _current_employee_id(db, current_user),
            "date_from": date_from,
            "date_to": date_to,
        }
        if project_id:
            filters.append("te.project_id = :project_id")
            params["project_id"] = project_id
        where = " AND ".join(filters)
        daily_rows = db.execute(text(f"""
            SELECT te.date,
                   COALESCE(SUM(te.hours), 0) AS total_hours,
                   COALESCE(SUM(CASE WHEN te.is_billable THEN te.hours ELSE 0 END), 0) AS billable_hours,
                   COALESCE(SUM(CASE WHEN NOT te.is_billable THEN te.hours ELSE 0 END), 0) AS non_billable_hours
            FROM timesheet_entries te
            WHERE {where}
            GROUP BY te.date
            ORDER BY te.date
        """), params).fetchall()
        totals = db.execute(text(f"""
            SELECT COALESCE(SUM(te.hours), 0) AS grand_total_hours,
                   COALESCE(SUM(CASE WHEN te.is_billable THEN te.hours ELSE 0 END), 0) AS billable_total_hours,
                   COALESCE(SUM(CASE WHEN NOT te.is_billable THEN te.hours ELSE 0 END), 0) AS non_billable_total_hours
            FROM timesheet_entries te
            WHERE {where}
        """), params).fetchone()
        return {
            "date_from": str(date_from),
            "date_to": str(date_to),
            "daily_totals": [
                {
                    "date": str(row.date),
                    "total_hours": qty_str(row.total_hours),
                    "billable_hours": qty_str(row.billable_hours),
                    "non_billable_hours": qty_str(row.non_billable_hours),
                }
                for row in daily_rows
            ],
            "grand_total_hours": qty_str(totals.grand_total_hours if totals else 0),
            "billable_total_hours": qty_str(totals.billable_total_hours if totals else 0),
            "non_billable_total_hours": qty_str(totals.non_billable_total_hours if totals else 0),
        }
    finally:
        db.close()


@router.get("/{project_id}/timesheets", dependencies=[Depends(require_permission("projects.view"))], response_model=List[Dict[str, Any]])
async def list_project_timesheets(project_id: int, current_user: dict = Depends(get_current_user)):
    """جلب سجلات الوقت لمشروع"""
    db = get_db_connection(current_user.company_id)
    try:
        project = db.execute(text("SELECT branch_id FROM projects WHERE id = :id"), {"id": project_id}).fetchone()
        if not project:
            raise HTTPException(**http_error(404, "project_not_found"))
        validate_branch_access(current_user, project.branch_id)

        timesheets = db.execute(text("""
            SELECT ts.*,
                CONCAT(u.first_name, ' ', u.last_name) as employee_name,
                pt.task_name
            FROM project_timesheets ts
            LEFT JOIN employees u ON ts.employee_id = u.id
            LEFT JOIN project_tasks pt ON ts.task_id = pt.id
            WHERE ts.project_id = :pid
            ORDER BY ts.date DESC, ts.created_at DESC
        """), {"pid": project_id}).fetchall()
        return [dict(t._mapping) for t in timesheets]
    finally:
        db.close()


@router.post("/{project_id}/timesheets", status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("projects.edit"))], response_model=Dict[str, Any])
async def create_timesheet(
    project_id: int,
    entry: TimesheetCreate,
    current_user: dict = Depends(get_current_user)
):
    """تسجيل وقت عمل"""
    db = get_db_connection(current_user.company_id)
    try:
        # Check if project exists
        project = db.execute(text("SELECT id FROM projects WHERE id = :id"), {"id": project_id}).fetchone()
        if not project:
            raise HTTPException(**http_error(404, "project_not_found"))

        ts_id = db.execute(text("""
            INSERT INTO project_timesheets (
                employee_id, project_id, task_id, date, hours, description, status
            ) VALUES (
                :uid, :pid, :tid, :date, :hours, :desc, :status
            ) RETURNING id
        """), {
            "uid": current_user.id,
            "pid": project_id,
            "tid": entry.task_id,
            "date": entry.date,
            "hours": entry.hours,
            "desc": entry.description,
            "status": entry.status
        }).scalar()

        # Update task actual hours if task_id is present
        if entry.task_id:
            db.execute(text("""
                UPDATE project_tasks
                SET actual_hours = COALESCE(actual_hours, 0) + :hours,
                    updated_at = NOW()
                WHERE id = :tid
            """), {"hours": entry.hours, "tid": entry.task_id})

        db.commit()
        return {"success": True, "id": ts_id, "message": i18n_message("timesheet_created_success")}
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating timesheet: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.put("/timesheets/{timesheet_id}", dependencies=[Depends(require_permission("projects.edit"))], response_model=Dict[str, Any])
async def update_timesheet(
    timesheet_id: int,
    entry: TimesheetUpdate,
    current_user: dict = Depends(get_current_user)
):
    """تحديث سجل وقت"""
    db = get_db_connection(current_user.company_id)
    try:
        # Get existing
        existing = db.execute(text("SELECT * FROM project_timesheets WHERE id = :id"), {"id": timesheet_id}).fetchone()
        if not existing:
            raise HTTPException(**http_error(404, "record_not_found"))
        
        # Check permission (only owner or admin)
        # Note: existing.employee_id refers to company_users.id (based on my schema design)
        # so comparison with current_user.id is correct.
        if existing.employee_id != current_user.id and current_user.role != 'admin':
             raise HTTPException(status_code=403, detail=i18n_message("not_allowed_edit_record"))

        # Calculate difference in hours if updating hours/task
        old_hours = _dec(existing.hours)
        new_hours = _dec(entry.hours) if entry.hours is not None else old_hours
        diff = new_hours - old_hours
        
        old_task = existing.task_id
        new_task = entry.task_id if entry.task_id is not None else old_task

        # Prepare updates
        updates = []
        params = {"id": timesheet_id}
        fields = {"task_id": "tid", "date": "date", "hours": "hrs", "description": "desc", "status": "st"}
        
        for field, param in fields.items():
            val = getattr(entry, field, None)
            if val is not None:
                updates.append(f"{field} = :{param}")
                params[param] = val
        
        if updates:
            updates.append("updated_at = NOW()")
            db.execute(text(f"UPDATE project_timesheets SET {', '.join(updates)} WHERE id = :id"), params)

            # Update actual hours on task(s)
            if old_task == new_task and diff != 0 and old_task:
                db.execute(text("UPDATE project_tasks SET actual_hours = actual_hours + :diff WHERE id = :tid"), 
                           {"diff": diff, "tid": old_task})
            elif old_task != new_task:
                if old_task:
                    db.execute(text("UPDATE project_tasks SET actual_hours = actual_hours - :hrs WHERE id = :tid"),
                               {"hrs": old_hours, "tid": old_task})
                if new_task:
                    db.execute(text("UPDATE project_tasks SET actual_hours = COALESCE(actual_hours, 0) + :hrs WHERE id = :tid"),
                               {"hrs": new_hours, "tid": new_task})

        db.commit()
        return {"success": True, "message": i18n_message("record_updated_success")}
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating timesheet: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.delete("/timesheets/{timesheet_id}", dependencies=[Depends(require_permission("projects.edit"))], response_model=Dict[str, Any])
async def delete_timesheet(timesheet_id: int, current_user: dict = Depends(get_current_user)):
    """حذف سجل وقت"""
    db = get_db_connection(current_user.company_id)
    try:
        existing = db.execute(text("SELECT * FROM project_timesheets WHERE id = :id"), {"id": timesheet_id}).fetchone()
        if not existing:
            raise HTTPException(**http_error(404, "record_not_found"))

        if existing.employee_id != current_user.id and current_user.role != 'admin':
             raise HTTPException(status_code=403, detail=i18n_message("not_allowed_delete_record"))

        # Revert task hours
        if existing.task_id:
            db.execute(text("UPDATE project_tasks SET actual_hours = actual_hours - :hrs WHERE id = :tid"),
                       {"hrs": existing.hours, "tid": existing.task_id})

        db.execute(text("DELETE FROM project_timesheets WHERE id = :id"), {"id": timesheet_id})
        db.commit()
        return {"success": True, "message": i18n_message("record_deleted_success")}
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting timesheet: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.post("/{project_id}/timesheets/approve", dependencies=[Depends(require_permission("projects.edit"))], response_model=Dict[str, Any])
async def approve_timesheets(
    project_id: int,
    approval: TimesheetApprove,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """اعتماد سجلات الوقت وتوليد القيود المحاسبية"""
    idempotency_key = require_idempotency_key(request, operation="project timesheet approval")
    db = get_db_connection(current_user.company_id)
    trans = db.begin()
    try:
        # 1. Fetch mapping accounts
        acc_labor_exp = get_mapped_account_id(db, "acc_map_salaries_exp")
        acc_payable = get_mapped_account_id(db, "acc_map_accrued_salaries")
        base_curr = get_base_currency(db)

        if not acc_labor_exp or not acc_payable:
            raise HTTPException(status_code=400, detail=i18n_message("labor_cost_accounts_not_configured"))

        # 2. Fetch Project Info
        project = db.execute(text("SELECT project_name, branch_id FROM projects WHERE id = :id"), {"id": project_id}).fetchone()
        if not project:
            raise HTTPException(**http_error(404, "project_not_found"))

        results = []
        for ts_id in approval.timesheet_ids:
            # Fetch timesheet with employee rates
            ts = db.execute(text("""
                SELECT ts.*, e.hourly_cost, e.salary, e.first_name || ' ' || e.last_name as emp_name
                FROM project_timesheets ts
                JOIN employees e ON ts.employee_id = e.user_id
                WHERE ts.id = :tid AND ts.project_id = :pid AND ts.status = 'draft'
            """), {"tid": ts_id, "pid": project_id}).fetchone()

            if not ts:
                continue

            # Enforce fiscal period lock before posting labor cost JE
            check_fiscal_period_open(db, ts.date)

            # Calculate Rate
            rate = _dec(ts.hourly_cost or 0)
            if rate == 0:
                # Fallback: Monthly Salary / 176 hours
                rate = _dec(ts.salary or 0) / Decimal('176')
            
            total_cost = (rate * _dec(ts.hours)).quantize(_D2, ROUND_HALF_UP)

            if total_cost > 0:
                # A. Create Project Expense Record
                db.execute(text("""
                    INSERT INTO project_expenses (
                        project_id, expense_type, expense_date, amount,
                        description, status, created_by
                    ) VALUES (:pid, 'labor', :date, :amt, :desc, 'approved', :uid)
                    RETURNING id
                """), {
                    "pid": project_id,
                    "date": ts.date,
                    "amt": total_cost,
                    "desc": f"تكلفة عمالة: {ts.emp_name} - {ts.description or ts.date}",
                    "uid": current_user.id
                }).scalar()

                # B. Create Journal Entry
                cost_center_id = db.execute(text(
                    "SELECT id FROM cost_centers WHERE center_name ILIKE :name LIMIT 1"
                ), {"name": f"%{project.project_name}%"}).scalar()

                je_id, _ = gl_create_journal_entry(
                    db=db,
                    company_id=current_user.company_id,
                    date=ts.date.isoformat() if hasattr(ts.date, 'isoformat') else str(ts.date),
                    description=f"قيد تكلفة عمالة مشروع: {project.project_name} - {ts.emp_name}",
                    reference=None,
                    status="posted",
                    currency=base_curr,
                    exchange_rate=Decimal("1"),
                    lines=[
                        {
                            "account_id": acc_labor_exp,
                            "debit": total_cost,
                            "credit": 0,
                            "description": f"تكلفة عمالة مشروع {project.project_name}",
                            "cost_center_id": cost_center_id
                        },
                        {
                            "account_id": acc_payable,
                            "debit": 0,
                            "credit": total_cost,
                            "description": f"استحقاق رواتب - مشروع {project.project_name}",
                            "cost_center_id": cost_center_id
                        }
                    ],
                    user_id=current_user.id,
                    branch_id=project.branch_id,
                    source="project_timesheet",
                    source_id=ts_id,
                    idempotency_key=f"project-timesheet:{idempotency_key}:{ts_id}:je",
                )

            # D. Update Timesheet Status
            db.execute(text("UPDATE project_timesheets SET status = 'approved' WHERE id = :id"), {"id": ts_id})
            results.append(ts_id)

        trans.commit()
        log_activity(db, user_id=current_user.id, username=current_user.username, action="approve_timesheets", resource_type="project_timesheet", resource_id=str(results), details={"approved_count": len(results), "project_id": project_id})
        return {"success": True, "approved_count": len(results), "message": i18n_message("timesheets_approved_count_success", count=len(results))}
    except Exception as e:
        trans.rollback()
        logger.error(f"Error approving timesheets: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()

# ═══════════════════════════════════════════════════════════
# Project Documents
# ═══════════════════════════════════════════════════════════

@router.post("/timetracking", status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("projects.time_log"))], response_model=Dict[str, Any])
async def log_time_entry(
    entry: TimesheetEntryCreate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """تسجيل ساعات العمل على مشروع (US17)"""
    db = get_db_connection(current_user.company_id)
    try:
        idempotency_key = require_idempotency_key(request, operation="time entry create")
        replay = db.execute(text("""
            SELECT id FROM timesheet_entries WHERE idempotency_key = :key LIMIT 1
        """), {"key": idempotency_key}).fetchone()
        if replay:
            return _serialize_time_entry(_fetch_timesheet_entry(db, replay.id))
        project = db.execute(text(
            "SELECT branch_id FROM projects WHERE id = :id"
        ), {"id": entry.project_id}).fetchone()
        if not project:
            raise HTTPException(**http_error(status.HTTP_404_NOT_FOUND, "project_not_found"))
        validate_branch_access(current_user, project.branch_id)
        employee_id = _current_employee_id(db, current_user)
        if entry.employee_id is not None and entry.employee_id != employee_id and current_user.role != "admin":
            raise HTTPException(status_code=403, detail=i18n_message("not_allowed_log_time_for_employee"))
        result = db.execute(text("""
            INSERT INTO timesheet_entries
                (employee_id, project_id, task_id, date, hours,
                 is_billable, billing_rate, description, status, created_by, idempotency_key)
            VALUES
                (:employee_id, :project_id, :task_id, :date, :hours,
                 :is_billable, :billing_rate, :description, 'draft', :created_by, :idempotency_key)
            ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL
            DO NOTHING
            RETURNING id
        """), {
            "employee_id": entry.employee_id if current_user.role == "admin" and entry.employee_id is not None else employee_id,
            "project_id":  entry.project_id,
            "task_id":     entry.task_id,
            "date":        entry.date,
            "hours":       entry.hours,
            "is_billable": entry.is_billable,
            "billing_rate": entry.billing_rate,
            "description": entry.description,
            "created_by":  current_user.id,
            "idempotency_key": idempotency_key,
        })
        inserted = result.fetchone()
        if not inserted:
            replay = db.execute(text("""
                SELECT id FROM timesheet_entries WHERE idempotency_key = :key LIMIT 1
            """), {"key": idempotency_key}).fetchone()
            if replay:
                return _serialize_time_entry(_fetch_timesheet_entry(db, replay.id))
            raise HTTPException(**http_error(status.HTTP_409_CONFLICT, "duplicate_idempotency_key"))
        entry_id = inserted[0]
        db.commit()
        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="project.time_log", resource_type="timesheet_entry",
            resource_id=str(entry_id),
            details={"project_id": entry.project_id, "hours": qty_str(entry.hours)},
            request=request
        )
        return _serialize_time_entry(_fetch_timesheet_entry(db, entry_id))
    except Exception as e:
        db.rollback()
        logger.error(f"Error logging time entry: {e}")
        raise HTTPException(**http_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error"))
    finally:
        db.close()


@router.put("/timetracking/{entry_id}",
            dependencies=[Depends(require_permission("projects.time_log"))], response_model=Dict[str, Any])
async def update_time_entry(
    entry_id: int,
    entry: TimesheetEntryUpdate,
    current_user: dict = Depends(get_current_user)
):
    """تعديل سجل وقت (draft فقط)"""
    db = get_db_connection(current_user.company_id)
    try:
        existing = _fetch_timesheet_entry(db, entry_id)
        if not existing:
            raise HTTPException(**http_error(status.HTTP_404_NOT_FOUND, "entry_not_found"))
        project = db.execute(text(
            "SELECT branch_id FROM projects WHERE id = :id"
        ), {"id": existing["project_id"]}).fetchone()
        if project:
            validate_branch_access(current_user, project.branch_id)
        if existing["status"] != "draft":
            raise HTTPException(**http_error(status.HTTP_400_BAD_REQUEST, "only_draft_entries_editable"))
        if existing.get("created_by") != current_user.id and current_user.role != "admin":
            raise HTTPException(status_code=403, detail=i18n_message("not_allowed_edit_record"))
        updates, params = [], {"id": entry_id}
        if entry.task_id is not None:
            updates.append("task_id = :task_id")
            params["task_id"] = entry.task_id
        if entry.date is not None:
            updates.append("date = :date")
            params["date"] = entry.date
        if entry.hours is not None:
            updates.append("hours = :hours")
            params["hours"] = entry.hours
        if entry.is_billable is not None:
            updates.append("is_billable = :is_billable")
            params["is_billable"] = entry.is_billable
        if entry.billing_rate is not None:
            updates.append("billing_rate = :billing_rate")
            params["billing_rate"] = entry.billing_rate
        if entry.description is not None:
            updates.append("description = :description")
            params["description"] = entry.description
        if not updates:
            return _serialize_time_entry(existing)
        updates.append("updated_at = now()")
        db.execute(text(f"UPDATE timesheet_entries SET {', '.join(updates)} WHERE id = :id"), params)
        db.commit()
        return _serialize_time_entry(_fetch_timesheet_entry(db, entry_id))
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating time entry: {e}")
        raise HTTPException(**http_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error"))
    finally:
        db.close()


@router.post("/timetracking/submit-week",
             dependencies=[Depends(require_permission("projects.time_log"))], response_model=Dict[str, Any])
async def submit_weekly_timesheet(
    req: WeeklySubmitRequest,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """رفع الجدول الزمني الأسبوعي للموافقة"""
    require_idempotency_key(request, operation="weekly timesheet submit")
    db = get_db_connection(current_user.company_id)
    try:
        employee_id = _current_employee_id(db, current_user)
        if req.employee_id is not None and req.employee_id != employee_id and current_user.role != "admin":
            raise HTTPException(status_code=403, detail=i18n_message("not_allowed_submit_timesheet"))
        target_employee_id = req.employee_id if current_user.role == "admin" and req.employee_id is not None else employee_id
        week_end = req.week_start + timedelta(days=6)
        result = db.execute(text("""
            UPDATE timesheet_entries
               SET status = 'submitted', updated_at = now()
             WHERE employee_id = :emp_id
               AND date BETWEEN :ws AND :we
               AND status = 'draft'
            RETURNING id
        """), {"emp_id": target_employee_id, "ws": req.week_start, "we": week_end})
        updated_ids = [r[0] for r in result.fetchall()]
        db.commit()
        return {"submitted_count": len(updated_ids), "entry_ids": updated_ids}
    except Exception as e:
        db.rollback()
        logger.error(f"Error submitting weekly timesheet: {e}")
        raise HTTPException(**http_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error"))
    finally:
        db.close()


@router.get("/timetracking/team",
            dependencies=[Depends(require_permission("projects.time_approve"))], response_model=List[Dict[str, Any]])
async def list_team_time_entries(
    project_id: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    entry_status: Optional[str] = None,
    page: int = 1,
    page_size: int = 25,
    current_user: dict = Depends(get_current_user)
):
    """جلب سجلات وقت الفريق (للمدير)"""
    db = get_db_connection(current_user.company_id)
    try:
        page = max(page, 1)
        page_size = min(max(page_size, 1), 100)
        filters = ["1=1"]
        params: dict = {"limit": page_size, "offset": (page - 1) * page_size}
        if project_id:
            filters.append("te.project_id = :project_id")
            params["project_id"] = project_id
            project = db.execute(text(
                "SELECT branch_id FROM projects WHERE id = :id"
            ), {"id": project_id}).fetchone()
            if project:
                validate_branch_access(current_user, project.branch_id)
        if date_from:
            filters.append("te.date >= :date_from")
            params["date_from"] = date_from
        if date_to:
            filters.append("te.date <= :date_to")
            params["date_to"] = date_to
        if entry_status:
            filters.append("te.status = :entry_status")
            params["entry_status"] = entry_status
        where = " AND ".join(filters)
        rows = db.execute(text(f"""
            SELECT te.*,
                   e.full_name  AS employee_name,
                   p.project_name,
                   pt.task_name,
                   ae.full_name AS approver_name
            FROM   timesheet_entries te
            LEFT JOIN employees e  ON e.id  = te.employee_id
            LEFT JOIN projects  p  ON p.id  = te.project_id
            LEFT JOIN project_tasks pt ON pt.id = te.task_id
            LEFT JOIN employees ae ON ae.id = te.approved_by
            WHERE  {where}
            ORDER BY te.date DESC, e.full_name
            LIMIT :limit OFFSET :offset
        """), params).fetchall()
        return [_serialize_time_entry(r) for r in rows]
    finally:
        db.close()


@router.post("/timetracking/{entry_id}/approve",
             dependencies=[Depends(require_permission("projects.time_approve"))], response_model=Dict[str, Any])
async def approve_time_entry(
    entry_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """الموافقة على سجل وقت"""
    require_idempotency_key(request, operation="time entry approval")
    db = get_db_connection(current_user.company_id)
    try:
        existing = _fetch_timesheet_entry(db, entry_id)
        if not existing:
            raise HTTPException(**http_error(status.HTTP_404_NOT_FOUND, "entry_not_found"))
        project = db.execute(text(
            "SELECT branch_id FROM projects WHERE id = :id"
        ), {"id": existing["project_id"]}).fetchone()
        if project:
            validate_branch_access(current_user, project.branch_id)
        if existing["status"] != "submitted":
            raise HTTPException(**http_error(status.HTTP_400_BAD_REQUEST, "only_submitted_entries_approvable"))
        approver_emp = db.execute(text(
            "SELECT id FROM employees WHERE user_id = :uid LIMIT 1"
        ), {"uid": current_user.id}).fetchone()
        approver_id = approver_emp[0] if approver_emp else None
        db.execute(text("""
            UPDATE timesheet_entries
               SET status = 'approved', approved_by = :approver, updated_at = now()
             WHERE id = :id
        """), {"approver": approver_id, "id": entry_id})
        db.commit()
        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="project.time_approve", resource_type="timesheet_entry",
            resource_id=str(entry_id),
            details={"entry_id": entry_id},
            request=request
        )
        return _serialize_time_entry(_fetch_timesheet_entry(db, entry_id))
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error approving time entry: {e}")
        raise HTTPException(**http_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error"))
    finally:
        db.close()


@router.post("/timetracking/{entry_id}/reject",
             dependencies=[Depends(require_permission("projects.time_approve"))], response_model=Dict[str, Any])
async def reject_time_entry(
    entry_id: int,
    req: RejectRequest,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """رفض سجل وقت مع سبب"""
    require_idempotency_key(request, operation="time entry rejection")
    db = get_db_connection(current_user.company_id)
    try:
        existing = _fetch_timesheet_entry(db, entry_id)
        if not existing:
            raise HTTPException(**http_error(status.HTTP_404_NOT_FOUND, "entry_not_found"))
        project = db.execute(text(
            "SELECT branch_id FROM projects WHERE id = :id"
        ), {"id": existing["project_id"]}).fetchone()
        if project:
            validate_branch_access(current_user, project.branch_id)
        if existing["status"] != "submitted":
            raise HTTPException(**http_error(status.HTTP_400_BAD_REQUEST, "only_submitted_entries_rejectable"))
        db.execute(text("""
            UPDATE timesheet_entries
               SET status = 'rejected',
                   rejection_reason = :reason,
                   updated_at = now()
             WHERE id = :id
        """), {"reason": req.rejection_reason, "id": entry_id})
        db.commit()
        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="project.time_reject", resource_type="timesheet_entry",
            resource_id=str(entry_id),
            details={"entry_id": entry_id, "reason": req.rejection_reason},
            request=request
        )
        return _serialize_time_entry(_fetch_timesheet_entry(db, entry_id))
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error rejecting time entry: {e}")
        raise HTTPException(**http_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error"))
    finally:
        db.close()


@router.get("/timetracking/profitability/{project_id}",
            dependencies=[Depends(require_permission("projects.time_view"))], response_model=Dict[str, Any])
async def get_project_profitability(
    project_id: int,
    current_user: dict = Depends(get_current_user)
):
    """تقرير ربحية المشروع: ساعات قابلة للفوترة × السعر مقابل الميزانية"""
    db = get_db_connection(current_user.company_id)
    try:
        project = db.execute(text("""
            SELECT id, project_name, planned_budget, actual_cost, branch_id
            FROM   projects WHERE id = :pid
        """), {"pid": project_id}).fetchone()
        if not project:
            raise HTTPException(**http_error(status.HTTP_404_NOT_FOUND, "project_not_found"))
        validate_branch_access(current_user, project.branch_id)

        ts = db.execute(text("""
            SELECT
                COALESCE(SUM(hours), 0)                                         AS total_hours,
                COALESCE(SUM(CASE WHEN is_billable THEN hours ELSE 0 END), 0)   AS billable_hours,
                COALESCE(SUM(CASE WHEN NOT is_billable THEN hours ELSE 0 END),0) AS non_billable_hours,
                COALESCE(SUM(CASE WHEN is_billable
                             THEN hours * COALESCE(billing_rate, 0)
                             ELSE 0 END), 0)                                    AS billable_revenue
            FROM timesheet_entries
            WHERE project_id = :pid AND status = 'approved'
        """), {"pid": project_id}).fetchone()

        expenses = db.execute(text("""
            SELECT COALESCE(SUM(amount), 0) AS total_expenses
            FROM (
                SELECT amount FROM project_expenses WHERE project_id = :pid
                UNION ALL
                SELECT amount FROM expenses WHERE project_id = :pid AND approval_status = 'approved' AND is_deleted = false
            ) combined
        """), {"pid": project_id}).fetchone()

        billable_revenue = _dec(ts.billable_revenue)
        total_expenses = _dec(expenses.total_expenses)
        total_cost = total_expenses + _dec(project.actual_cost or 0)
        profit = billable_revenue - total_cost
        planned_budget = _dec(project.planned_budget or 0)
        margin_pct = (profit / billable_revenue * Decimal("100")) if billable_revenue else Decimal("0")
        revenue_bar_pct = Decimal("100")
        cost_bar_pct = Decimal("0")
        max_bar = max(billable_revenue, total_cost, Decimal("1"))
        revenue_bar_pct = (billable_revenue / max_bar * Decimal("100")).quantize(_D2, ROUND_HALF_UP)
        cost_bar_pct = (total_cost / max_bar * Decimal("100")).quantize(_D2, ROUND_HALF_UP)

        return {
            "project_id":        project_id,
            "project_name":      project.project_name,
            "planned_budget":    money_str(planned_budget),
            "total_hours":       qty_str(ts.total_hours),
            "billable_hours":    qty_str(ts.billable_hours),
            "non_billable_hours": qty_str(ts.non_billable_hours),
            "billable_revenue":  money_str(billable_revenue),
            "total_expenses":    money_str(total_expenses),
            "total_cost":        money_str(total_cost),
            "profit":            money_str(profit),
            "margin_pct":        rate_str(margin_pct),
            "profit_status":     "profitable" if profit >= 0 else "loss",
            "budget_status":     "over_budget" if billable_revenue > planned_budget and planned_budget > 0 else "within_budget",
            "revenue_bar_pct":   rate_str(revenue_bar_pct),
            "cost_bar_pct":      rate_str(cost_bar_pct),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error calculating profitability: {e}")
        raise HTTPException(**http_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error"))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# US18 — Resource Planning  (/projects/resources/...)
# ═══════════════════════════════════════════════════════════
