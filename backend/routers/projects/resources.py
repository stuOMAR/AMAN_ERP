"""projects sub-router — split from monolithic projects.py (T6.3).

Mounted under the parent router via projects/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from utils.i18n import http_error, i18n_message
from typing import Any, Dict, List, Optional
from datetime import date, datetime, timedelta
from decimal import Decimal
from database import get_db_connection
from routers.auth import get_current_user
from utils.permissions import require_permission
from utils.audit import log_activity
from utils.permissions import validate_branch_access
from utils.tax_precision import qty_str, rate_str, require_idempotency_key
from sqlalchemy import text
import logging

logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')
def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')

from schemas.resource import AllocationCreate, AllocationUpdate  # noqa: E402

router = APIRouter()

from .core import _dec, _fetch_allocation, _compute_total_allocation  # noqa: E402

def _load_status(hours: Decimal) -> str:
    if hours <= 0:
        return "none"
    if hours <= Decimal("6"):
        return "light"
    if hours <= Decimal("8"):
        return "optimal"
    if hours <= Decimal("10"):
        return "heavy"
    return "overload"

@router.get("/resources/allocation", dependencies=[Depends(require_permission("projects.view"))], response_model=List[Dict[str, Any]])
async def get_resource_allocation(
    start_date: date,
    end_date: date,
    current_user: dict = Depends(get_current_user)
):
    """
    تقرير تخصيص الموارد (Resource Allocation)
    يحسب ساعات العمل المخططة لكل موظف يومياً بناءً على المهام المسندة.
    """
    db = get_db_connection(current_user.company_id)
    try:
        # Fetch tasks that overlap with the requested period
        tasks = db.execute(text("""
            SELECT pt.id, pt.task_name, pt.start_date, pt.end_date, pt.planned_hours,
                   pt.assigned_to, CONCAT(e.first_name, ' ', e.last_name) as employee_name,
                   p.project_name
            FROM project_tasks pt
            JOIN projects p ON pt.project_id = p.id
            JOIN employees e ON pt.assigned_to = e.id
            WHERE pt.start_date <= :end AND pt.end_date >= :start
            AND pt.assigned_to IS NOT NULL
            AND p.status IN ('in_progress', 'planning')
        """), {"start": start_date, "end": end_date}).fetchall()

        # Fetch actual timesheets for verification (Optional, maybe for a different view)
        # For allocation, we mainly care about "Planned" load to avoid overloading.

        allocation: Dict[int, Dict[str, Any]] = {}

        # Helper to generate date range
        from datetime import timedelta
        def daterange(start_date, end_date):
            for n in range(int((end_date - start_date).days) + 1):
                yield start_date + timedelta(n)

        req_start = start_date
        req_end = end_date

        for task in tasks:
            emp_id = task.assigned_to
            emp_name = task.employee_name
            
            if emp_id not in allocation:
                allocation[emp_id] = {"id": emp_id, "name": emp_name, "projects": set(), "daily_load": {}}

            allocation[emp_id]["projects"].add(task.project_name)

            # Calculate daily load for this task
            # Intersection of Task Duration and Requested Period
            t_start = max(task.start_date.date() if isinstance(task.start_date, datetime) else task.start_date, req_start)
            t_end = min(task.end_date.date() if isinstance(task.end_date, datetime) else task.end_date, req_end)
            
            if t_start > t_end:
                 continue

            days_count = (task.end_date - task.start_date).days + 1
            if days_count <= 0:
                days_count = 1
            
            # Simple linear distribution: hours / days
            daily_hours = _dec(task.planned_hours or 0) / _dec(days_count)

            for single_date in daterange(t_start, t_end):
                d_str = single_date.isoformat()
                allocation[emp_id]["daily_load"][d_str] = allocation[emp_id]["daily_load"].get(d_str, Decimal('0')) + daily_hours

        # Format for frontend
        result = []
        for emp_id, data in allocation.items():
            weekly_total = sum((_dec(h) for h in data["daily_load"].values()), Decimal("0"))
            result.append({
                "id": data["id"],
                "name": data["name"],
                "projects": list(data["projects"]),
                "weekly_total_load": qty_str(weekly_total),
                "weekly_load_status": _load_status(weekly_total),
                "daily_load": [
                    {
                        "date": d,
                        "hours": qty_str(h),
                        "load_status": _load_status(_dec(h)),
                    }
                    for d, h in data["daily_load"].items()
                ],
            })

        return result

    except Exception as e:
        logger.error(f"Error fetching resource allocation: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()

@router.get("/resources/availability",
            dependencies=[Depends(require_permission("projects.resource_view"))], response_model=Dict[str, Any])
async def get_team_availability(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    current_user: dict = Depends(get_current_user)
):
    """عرض تقويم توفر الفريق مع نسب التخصيص"""
    db = get_db_connection(current_user.company_id)
    try:
        if not date_from:
            date_from = date.today()
        if not date_to:
            date_to = date_from + timedelta(days=90)

        try:
            employees = db.execute(text("""
                SELECT DISTINCT ra.employee_id, e.full_name AS employee_name
                FROM   resource_allocations ra
                JOIN   employees e ON e.id = ra.employee_id
                WHERE  ra.start_date <= :ed AND ra.end_date >= :sd
                ORDER  BY e.full_name
            """), {"sd": date_from, "ed": date_to}).fetchall()
        except Exception as e:
            db.rollback()
            if "does not exist" in str(e):
                return {"employees": []}
            raise

        result = []
        for emp in employees:
            allocs = db.execute(text("""
                SELECT ra.*,
                       p.project_name
                FROM   resource_allocations ra
                LEFT JOIN projects p ON p.id = ra.project_id
                WHERE  ra.employee_id = :eid
                  AND  ra.start_date <= :ed
                  AND  ra.end_date   >= :sd
                ORDER  BY ra.start_date
            """), {"eid": emp.employee_id, "sd": date_from, "ed": date_to}).fetchall()

            total_alloc = sum((_dec(a.allocation_percent) for a in allocs), Decimal("0"))
            result.append({
                "employee_id": emp.employee_id,
                "employee_name": emp.employee_name,
                "total_allocation": rate_str(total_alloc),
                "is_over_allocated": total_alloc > Decimal("100"),
                "allocations": [dict(a._mapping) for a in allocs],
            })
        return {"employees": result}
    finally:
        db.close()


@router.post("/resources/allocate", status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("projects.resource_manage"))], response_model=Dict[str, Any])
async def allocate_resource(
    alloc: AllocationCreate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """تخصيص مورد لمشروع مع تحذير عند التخصيص الزائد"""
    db = get_db_connection(current_user.company_id)
    try:
        idempotency_key = require_idempotency_key(request, operation="resource allocation")
        replay = db.execute(text("""
            SELECT id FROM resource_allocations WHERE idempotency_key = :key LIMIT 1
        """), {"key": idempotency_key}).fetchone()
        if replay:
            data = _fetch_allocation(db, replay.id)
            if data and data.get("allocation_percent") is not None:
                data["allocation_percent"] = rate_str(data["allocation_percent"])
            data["idempotency_replayed"] = True
            return data
        project = db.execute(text(
            "SELECT branch_id FROM projects WHERE id = :id"
        ), {"id": alloc.project_id}).fetchone()
        if not project:
            raise HTTPException(**http_error(status.HTTP_404_NOT_FOUND, "project_not_found"))
        validate_branch_access(current_user, project.branch_id)

        existing_total = _compute_total_allocation(
            db, alloc.employee_id, alloc.start_date, alloc.end_date
        )
        new_total = existing_total + _dec(alloc.allocation_percent)
        over_allocated = new_total > Decimal("100")
        if over_allocated:
            raise HTTPException(status_code=400, detail=i18n_message("employee_overallocated_warning", total=rate_str(new_total)))

        result = db.execute(text("""
            INSERT INTO resource_allocations
                (employee_id, project_id, role, allocation_percent,
                 start_date, end_date, created_by, idempotency_key)
            VALUES
                (:employee_id, :project_id, :role, :allocation_percent,
                 :start_date, :end_date, :created_by, :idempotency_key)
            ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL
            DO NOTHING
            RETURNING id
        """), {
            "employee_id":      alloc.employee_id,
            "project_id":       alloc.project_id,
            "role":             alloc.role,
            "allocation_percent": alloc.allocation_percent,
            "start_date":       alloc.start_date,
            "end_date":         alloc.end_date,
            "created_by":       current_user.id,
            "idempotency_key":   idempotency_key,
        })
        inserted = result.fetchone()
        if not inserted:
            replay = db.execute(text("""
                SELECT id FROM resource_allocations WHERE idempotency_key = :key LIMIT 1
            """), {"key": idempotency_key}).fetchone()
            if replay:
                data = _fetch_allocation(db, replay.id)
                data["allocation_percent"] = rate_str(data["allocation_percent"])
                data["idempotency_replayed"] = True
                return data
            raise HTTPException(**http_error(status.HTTP_409_CONFLICT, "duplicate_idempotency_key"))
        alloc_id = inserted[0]
        db.commit()

        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="project.resource_allocate", resource_type="resource_allocation",
            resource_id=str(alloc_id),
            details={"project_id": alloc.project_id, "employee_id": alloc.employee_id, "percent": rate_str(alloc.allocation_percent)},
            request=request
        )

        data = _fetch_allocation(db, alloc_id)
        data["allocation_percent"] = rate_str(data["allocation_percent"])
        data["total_allocation"] = rate_str(new_total)
        data["over_allocation_warning"] = over_allocated
        return data
    except Exception as e:
        db.rollback()
        logger.error(f"Error allocating resource: {e}")
        raise HTTPException(**http_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error"))
    finally:
        db.close()


@router.put("/resources/allocate/{alloc_id}",
            dependencies=[Depends(require_permission("projects.resource_manage"))], response_model=Dict[str, Any])
async def update_allocation(
    alloc_id: int,
    alloc: AllocationUpdate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """تحديث تخصيص مورد"""
    require_idempotency_key(request, operation="resource allocation update")
    db = get_db_connection(current_user.company_id)
    try:
        existing = _fetch_allocation(db, alloc_id)
        if not existing:
            raise HTTPException(**http_error(status.HTTP_404_NOT_FOUND, "allocation_not_found"))
        project = db.execute(text(
            "SELECT branch_id FROM projects WHERE id = :id"
        ), {"id": existing["project_id"]}).fetchone()
        if project:
            validate_branch_access(current_user, project.branch_id)

        updates, params = [], {"id": alloc_id}
        if alloc.role is not None:
            updates.append("role = :role")
            params["role"] = alloc.role
        if alloc.allocation_percent is not None:
            updates.append("allocation_percent = :pct")
            params["pct"] = alloc.allocation_percent
        if alloc.start_date is not None:
            updates.append("start_date = :sd")
            params["sd"] = alloc.start_date
        if alloc.end_date is not None:
            updates.append("end_date = :ed")
            params["ed"] = alloc.end_date
        if not updates:
            return existing

        new_sd = alloc.start_date or existing["start_date"]
        new_ed = alloc.end_date or existing["end_date"]
        new_pct = _dec(alloc.allocation_percent) if alloc.allocation_percent is not None else _dec(existing["allocation_percent"])
        total_without_existing = _compute_total_allocation(
            db, existing["employee_id"], new_sd, new_ed, exclude_id=alloc_id
        )
        projected_total = total_without_existing + new_pct
        if projected_total > Decimal("100"):
            raise HTTPException(status_code=400, detail=i18n_message("employee_overallocated_warning", total=rate_str(projected_total)))

        updates.append("updated_at = now()")
        db.execute(text(
            f"UPDATE resource_allocations SET {', '.join(updates)} WHERE id = :id"
        ), params)
        db.commit()

        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="project.resource_update", resource_type="resource_allocation",
            resource_id=str(alloc_id),
            details={"alloc_id": alloc_id},
            request=request
        )

        updated = _fetch_allocation(db, alloc_id)
        updated["allocation_percent"] = rate_str(updated["allocation_percent"])
        updated["total_allocation"] = rate_str(projected_total)
        updated["over_allocation_warning"] = False
        return updated
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating allocation: {e}")
        raise HTTPException(**http_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error"))
    finally:
        db.close()


@router.delete("/resources/allocate/{alloc_id}",
               dependencies=[Depends(require_permission("projects.resource_manage"))], response_model=Dict[str, Any])
async def delete_allocation(
    alloc_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """حذف تخصيص مورد"""
    db = get_db_connection(current_user.company_id)
    try:
        existing = _fetch_allocation(db, alloc_id)
        if not existing:
            raise HTTPException(**http_error(status.HTTP_404_NOT_FOUND, "allocation_not_found"))
        project = db.execute(text(
            "SELECT branch_id FROM projects WHERE id = :id"
        ), {"id": existing["project_id"]}).fetchone()
        if project:
            validate_branch_access(current_user, project.branch_id)
        db.execute(text("DELETE FROM resource_allocations WHERE id = :id"),
                   {"id": alloc_id})
        db.commit()
        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="project.resource_delete", resource_type="resource_allocation",
            resource_id=str(alloc_id),
            details={"alloc_id": alloc_id},
            request=request
        )
        return {"message": i18n_message("allocation_removed"), "id": alloc_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting allocation: {e}")
        raise HTTPException(**http_error(status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error"))
    finally:
        db.close()


@router.get("/resources/project/{project_id}",
            dependencies=[Depends(require_permission("projects.resource_view"))], response_model=List[Dict[str, Any]])
async def get_project_resources(
    project_id: int,
    current_user: dict = Depends(get_current_user)
):
    """عرض تخصيصات الموارد لمشروع معين"""
    db = get_db_connection(current_user.company_id)
    try:
        project = db.execute(text(
            "SELECT branch_id FROM projects WHERE id = :id"
        ), {"id": project_id}).fetchone()
        if not project:
            raise HTTPException(**http_error(status.HTTP_404_NOT_FOUND, "project_not_found"))
        validate_branch_access(current_user, project.branch_id)
        rows = db.execute(text("""
            SELECT ra.*,
                   e.full_name  AS employee_name,
                   p.project_name
            FROM   resource_allocations ra
            LEFT JOIN employees e ON e.id = ra.employee_id
            LEFT JOIN projects  p ON p.id = ra.project_id
            WHERE  ra.project_id = :pid
            ORDER  BY ra.start_date, e.full_name
        """), {"pid": project_id}).fetchall()
        result = []
        for row in rows:
            data = dict(row._mapping)
            if data.get("allocation_percent") is not None:
                data["allocation_percent"] = rate_str(data["allocation_percent"])
            result.append(data)
        return result
    finally:
        db.close()
