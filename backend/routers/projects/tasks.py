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

from .core import _D2, _D4

@router.get("/{project_id}/tasks", dependencies=[Depends(require_permission("projects.view"))], response_model=List[Dict[str, Any]])
async def get_project_tasks(project_id: int, current_user: dict = Depends(get_current_user)):
    """جلب مهام المشروع"""
    db = get_db_connection(current_user.company_id)
    try:
        tasks = db.execute(text("""
            SELECT pt.*,
                CONCAT(e.first_name, ' ', e.last_name) as assigned_to_name
            FROM project_tasks pt
            LEFT JOIN employees e ON pt.assigned_to = e.id
            WHERE pt.project_id = :pid
            ORDER BY pt.id
        """), {"pid": project_id}).fetchall()
        return [dict(t._mapping) for t in tasks]
    finally:
        db.close()


@router.post("/{project_id}/tasks", status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("projects.edit"))], response_model=Dict[str, Any])
async def create_task(project_id: int, task: TaskCreate, request: Request, current_user: dict = Depends(get_current_user)):
    """إضافة مهمة للمشروع"""
    db = get_db_connection(current_user.company_id)
    try:
        project = db.execute(text("SELECT id FROM projects WHERE id = :id"), {"id": project_id}).fetchone()
        if not project:
            raise HTTPException(**http_error(404, "project_not_found"))

        result = db.execute(text("""
            INSERT INTO project_tasks (
                project_id, task_name, task_name_en, description,
                parent_task_id, assigned_to, start_date, end_date,
                planned_hours, status
            ) VALUES (
                :pid, :name, :name_en, :desc,
                :parent, :assigned, :start, :end,
                :hours, :status
            ) RETURNING id
        """), {
            "pid": project_id,
            "name": task.task_name, "name_en": task.task_name_en,
            "desc": task.description, "parent": task.parent_task_id,
            "assigned": task.assigned_to,
            "start": task.start_date, "end": task.end_date,
            "hours": task.planned_hours, "status": task.status
        })
        task_id = result.scalar()
        db.commit()

        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="project.task.create", resource_type="project_task",
            resource_id=str(task_id),
            details={"project_id": project_id, "task_name": task.task_name},
            request=request
        )

        return {"success": True, "id": task_id, "message": i18n_message("task_created_success")}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating task: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.put("/{project_id}/tasks/{task_id}", dependencies=[Depends(require_permission("projects.edit"))], response_model=Dict[str, Any])
async def update_task(project_id: int, task_id: int, data: TaskUpdate, request: Request, current_user: dict = Depends(get_current_user)):
    """تحديث مهمة"""
    db = get_db_connection(current_user.company_id)
    try:
        existing = db.execute(
            text("SELECT id FROM project_tasks WHERE id = :tid AND project_id = :pid"),
            {"tid": task_id, "pid": project_id}
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail=i18n_message("task_not_found"))

        updates = []
        params = {"tid": task_id}

        fields = {
            "task_name": "name", "description": "desc",
            "assigned_to": "assigned", "start_date": "start",
            "end_date": "end", "planned_hours": "ph",
            "actual_hours": "ah", "progress": "prog", "status": "st"
        }
        for field, param in fields.items():
            value = getattr(data, field, None)
            if value is not None:
                updates.append(f"{field} = :{param}")
                params[param] = value

        if not updates:
            raise HTTPException(**http_error(400, "no_data_to_update"))

        query = f"UPDATE project_tasks SET {', '.join(updates)} WHERE id = :tid"
        db.execute(text(query), params)

        # Auto-update project progress
        db.execute(text("""
            UPDATE projects SET progress_percentage = (
                SELECT COALESCE(AVG(progress), 0) FROM project_tasks WHERE project_id = :pid
            ), updated_at = NOW()
            WHERE id = :pid
        """), {"pid": project_id})

        db.commit()

        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="project.task.update", resource_type="project_task",
            resource_id=str(task_id),
            details={"project_id": project_id},
            request=request
        )

        return {"success": True, "message": i18n_message("task_updated_success")}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating task: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.delete("/{project_id}/tasks/{task_id}", dependencies=[Depends(require_permission("projects.edit"))], response_model=Dict[str, Any])
async def delete_task(project_id: int, task_id: int, request: Request, current_user: dict = Depends(get_current_user)):
    """حذف مهمة"""
    db = get_db_connection(current_user.company_id)
    try:
        db.execute(
            text("DELETE FROM project_tasks WHERE id = :tid AND project_id = :pid"),
            {"tid": task_id, "pid": project_id}
        )
        db.commit()

        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="project.task.delete", resource_type="project_task",
            resource_id=str(task_id),
            details={"project_id": project_id},
            request=request
        )

        return {"success": True, "message": i18n_message("task_deleted_success")}
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# Project Expenses (مع ربط محاسبي)
# ═══════════════════════════════════════════════════════════

@router.get("/{project_id}/task-dependencies", dependencies=[Depends(require_permission("projects.view"))], response_model=List[Dict[str, Any]])
def list_task_dependencies(project_id: int, current_user=Depends(get_current_user)):
    """تبعيات المهام"""
    db = get_db_connection(current_user.company_id)
    try:
        rows = db.execute(text("""
            SELECT td.*, t1.task_name as task_name, t2.task_name as depends_on_name
            FROM task_dependencies td
            LEFT JOIN project_tasks t1 ON t1.id = td.task_id
            LEFT JOIN project_tasks t2 ON t2.id = td.depends_on_task_id
            WHERE td.project_id = :pid
            ORDER BY td.task_id
        """), {"pid": project_id}).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


@router.post("/{project_id}/task-dependencies", dependencies=[Depends(require_permission("projects.edit"))], response_model=Dict[str, Any])
def create_task_dependency(project_id: int, dep: TaskDependencyCreate, request: Request, current_user=Depends(get_current_user)):
    """إنشاء تبعية مهمة"""
    db = get_db_connection(current_user.company_id)
    try:
        # T034: Validate no self-dependency
        if dep.task_id == dep.depends_on_task_id:
            raise HTTPException(**http_error(400, "task_cannot_depend_on_itself"))

        result = db.execute(text("""
            INSERT INTO task_dependencies (project_id, task_id, depends_on_task_id,
                dependency_type, lag_days)
            VALUES (:pid, :tid, :did, :dt, :ld)
            RETURNING id
        """), {
            "pid": project_id, "tid": dep.task_id, "did": dep.depends_on_task_id,
            "dt": dep.dependency_type, "ld": dep.lag_days
        })
        dep_id = result.fetchone()[0]
        db.commit()
        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="project.dependency_create", resource_type="task_dependency",
            resource_id=str(dep_id),
            details={"project_id": project_id, "task_id": dep.task_id, "depends_on": dep.depends_on_task_id},
            request=request
        )
        return {"id": dep_id, "message": i18n_message("dependency_created_success")}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating task dependency: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.delete("/task-dependencies/{dep_id}", dependencies=[Depends(require_permission("projects.edit"))], response_model=Dict[str, Any])
def delete_task_dependency(dep_id: int, request: Request, current_user=Depends(get_current_user)):
    """حذف تبعية"""
    db = get_db_connection(current_user.company_id)
    try:
        db.execute(text("DELETE FROM task_dependencies WHERE id = :id"), {"id": dep_id})
        db.commit()
        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="project.dependency_delete", resource_type="task_dependency",
            resource_id=str(dep_id),
            details={"dep_id": dep_id},
            request=request
        )
        return {"message": i18n_message("dependency_deleted_success")}
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting task dependency: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# US17 — Time Tracking  (/projects/timetracking/...)
# ═══════════════════════════════════════════════════════════

from schemas.timetracking import (
    TimesheetEntryCreate, TimesheetEntryUpdate,
    WeeklySubmitRequest, RejectRequest
)


