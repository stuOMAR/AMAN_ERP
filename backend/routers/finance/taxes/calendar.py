"""taxes sub-router — split from monolithic taxes.py (T6.3).

Mounted under the parent router via taxes/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pydantic import BaseModel
import logging
from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import branch_scope_filter_from_scope, require_permission, resolve_branch_scope, validate_branch_access, require_module
from utils.audit import log_activity
from utils.fiscal_lock import check_fiscal_period_open
from utils.accounting import generate_sequential_number, get_mapped_account_id, get_base_currency
from schemas.taxes import TaxRateCreate, TaxRateUpdate, TaxGroupCreate, TaxReturnCreate, TaxPaymentCreate

logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')

def _dec(v) -> Decimal:
    return Decimal(str(v or 0))

router = APIRouter()

from .core import TaxCalendarCreate, TaxCalendarUpdate, _D2, _D4

@router.get("/calendar", response_model=List[Dict[str, Any]])
def list_tax_calendar(
    status: Optional[str] = None,
    tax_type: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user=Depends(require_permission(["taxes.view"]))
):
    """List tax calendar events with optional filters"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    with transactional(current_user.company_id) as db:
        try:
            conditions = ["is_active = TRUE"]
            params = {}
            branch_condition = branch_scope_filter_from_scope(branch_scope, "branch_id", params, prefix="").strip()
            if branch_condition:
                conditions.append(branch_condition)
            if status == "completed":
                conditions.append("is_completed = true")
            elif status == "pending":
                conditions.append("is_completed = false")
            elif status == "overdue":
                conditions.append("is_completed = false AND due_date < CURRENT_DATE")
            if tax_type:
                conditions.append("tax_type = :tax_type")
                params["tax_type"] = tax_type
    
            where = " AND ".join(conditions)
            rows = db.execute(text(  # noqa: sql-lint
                f"""
    
                SELECT *, 
                       CASE WHEN is_completed THEN 'completed'
                            WHEN due_date < CURRENT_DATE THEN 'overdue'
                            WHEN due_date <= CURRENT_DATE + INTERVAL '7 days' THEN 'upcoming'
                            ELSE 'pending' END as status
                FROM tax_calendar
                WHERE {where}
                ORDER BY due_date ASC
            """), params).fetchall()
            return [dict(r._mapping) for r in rows]
        except Exception as e:
            logger.error(f"Error listing tax calendar: {e}")
            return []


@router.get("/calendar/summary", response_model=Dict[str, Any])
def tax_calendar_summary(
    branch_id: Optional[int] = None,
    current_user=Depends(require_permission(["taxes.view"]))
):
    """Get tax calendar summary stats"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    with transactional(current_user.company_id) as db:
        try:
            params = {}
            branch_filter = branch_scope_filter_from_scope(branch_scope, "branch_id", params)
            row = db.execute(text(f""" # noqa: sql-lint
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE is_completed = false AND due_date >= CURRENT_DATE) as pending,
                    COUNT(*) FILTER (WHERE is_completed = false AND due_date < CURRENT_DATE) as overdue,
                    COUNT(*) FILTER (WHERE is_completed = true) as completed,
                    COUNT(*) FILTER (WHERE is_completed = false AND due_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '7 days') as upcoming_week,
                    MIN(due_date) FILTER (WHERE is_completed = false AND due_date >= CURRENT_DATE) as next_due
                FROM tax_calendar
                WHERE is_active = TRUE {branch_filter}
            """), params).fetchone()
            return dict(row._mapping) if row else {}
        except Exception as e:
            logger.error(f"Error fetching calendar summary: {e}")
            return {}


@router.get("/calendar/{item_id}", response_model=Dict[str, Any])
def get_tax_calendar_item(
    item_id: int,
    request: Request,
    current_user=Depends(require_permission(["taxes.view"]))
):
    """Get Tax Calendar Item."""
    with transactional(current_user.company_id) as db:
        try:
            row = db.execute(text("SELECT * FROM tax_calendar WHERE id = :id AND is_active = TRUE"), {"id": item_id}).fetchone()
            if not row:
                raise HTTPException(**http_error(404, "tax_calendar_item_not_found", request))
            if row.branch_id:
                validate_branch_access(current_user, row.branch_id)
            return dict(row._mapping)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/calendar", response_model=Dict[str, Any])
def create_tax_calendar_item(
    request: Request,
    data: TaxCalendarCreate,
    current_user=Depends(require_permission(["taxes.manage"]))
):
    """Create Tax Calendar Item."""
    with transactional(current_user.company_id) as db:
        try:
            import json
            branch_id = validate_branch_access(current_user, data.branch_id)
            row = db.execute(text("""
                INSERT INTO tax_calendar (title, tax_type, branch_id, due_date, reminder_days, is_recurring, recurrence_months, notes, created_by)
                VALUES (:title, :tax_type, :branch_id, :due_date, CAST(:reminder_days AS jsonb), :is_recurring, :recurrence_months, :notes, :user_id)
                RETURNING *
            """), {
                "title": data.title,
                "tax_type": data.tax_type,
                "branch_id": branch_id,
                "due_date": data.due_date,
                "reminder_days": json.dumps(data.reminder_days or [7, 3, 1]),
                "is_recurring": data.is_recurring,
                "recurrence_months": data.recurrence_months,
                "notes": data.notes,
                "user_id": current_user.id
            }).fetchone()
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="taxes.calendar.create", resource_type="tax_calendar",
                         resource_id=str(row.id), details={"title": data.title},
                         request=request)
            return dict(row._mapping)
        except Exception as e:
            pass
            logger.error(f"Error creating calendar item: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.put("/calendar/{item_id}", response_model=Dict[str, Any])
def update_tax_calendar_item(
    item_id: int,
    request: Request,
    data: TaxCalendarUpdate,
    current_user=Depends(require_permission(["taxes.manage"]))
):
    """Update Tax Calendar Item."""
    with transactional(current_user.company_id) as db:
        try:
            import json
            existing = db.execute(text(
                "SELECT branch_id FROM tax_calendar WHERE id = :id AND is_active = TRUE"
            ), {"id": item_id}).fetchone()
            if not existing:
                raise HTTPException(**http_error(404, "tax_calendar_item_not_found", request))
            if existing.branch_id:
                validate_branch_access(current_user, existing.branch_id)
            updates = []
            params = {"id": item_id}
            if data.branch_id is not None:
                updates.append("branch_id = :branch_id")
                params["branch_id"] = validate_branch_access(current_user, data.branch_id)
            for field in ["title", "tax_type", "due_date", "is_recurring", "recurrence_months", "is_completed", "notes"]:
                val = getattr(data, field, None)
                if val is not None:
                    updates.append(f"{field} = :{field}")
                    params[field] = val
            if data.reminder_days is not None:
                updates.append("reminder_days = CAST(:reminder_days AS jsonb)")
                params["reminder_days"] = json.dumps(data.reminder_days)
            if not updates:
                raise HTTPException(**http_error(400, "pos_no_fields", request))
    
            row = db.execute(text(  # noqa: sql-lint
                f"""
    
                UPDATE tax_calendar SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP WHERE id = :id RETURNING *
            """), params).fetchone()
            if not row:
                raise HTTPException(**http_error(404, "tax_calendar_item_not_found", request))
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="taxes.calendar.update", resource_type="tax_calendar",
                         resource_id=str(item_id), details={"fields": list(params.keys())},
                         request=request)
            return dict(row._mapping)
        except HTTPException:
            raise
        except Exception as e:
            pass
            logger.error(f"Error updating calendar item: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.delete("/calendar/{item_id}", response_model=Dict[str, Any])
def delete_tax_calendar_item(
    item_id: int,
    request: Request,
    current_user=Depends(require_permission(["taxes.manage"]))
):
    """Delete Tax Calendar Item."""
    with transactional(current_user.company_id) as db:
        try:
            existing = db.execute(text(
                "SELECT branch_id FROM tax_calendar WHERE id = :id AND is_active = TRUE"
            ), {"id": item_id}).fetchone()
            if not existing:
                raise HTTPException(**http_error(404, "tax_calendar_item_not_found", request))
            if existing.branch_id:
                validate_branch_access(current_user, existing.branch_id)
            result = db.execute(text("""
                UPDATE tax_calendar
                   SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP
                 WHERE id = :id AND is_active = TRUE
            """), {"id": item_id})
            if result.rowcount == 0:
                raise HTTPException(**http_error(404, "tax_calendar_item_not_found", request))
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="taxes.calendar.delete", resource_type="tax_calendar",
                         resource_id=str(item_id), details={},
                         request=request)
            return {"message": i18n_message("record_deleted", request), "soft_deleted": True}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.put("/calendar/{item_id}/complete", response_model=Dict[str, Any])
def complete_tax_calendar_item(
    item_id: int,
    request: Request,
    current_user=Depends(require_permission(["taxes.manage"]))
):
    """Mark a tax calendar item as completed, optionally creating next recurrence"""
    with transactional(current_user.company_id) as db:
        try:
            row = db.execute(text("SELECT * FROM tax_calendar WHERE id = :id AND is_active = TRUE FOR UPDATE"), {"id": item_id}).fetchone()
            if not row:
                raise HTTPException(**http_error(404, "tax_calendar_item_not_found", request))
            if row.branch_id:
                validate_branch_access(current_user, row.branch_id)
            item = dict(row._mapping)
    
            db.execute(text("""
                UPDATE tax_calendar
                   SET is_completed = true, completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                 WHERE id = :id
            """), {"id": item_id})
    
            # If recurring, create next occurrence
            new_id = None
            if item.get("is_recurring"):
                import json
                months = item.get("recurrence_months", 3)
                next_due = item["due_date"]
                from dateutil.relativedelta import relativedelta
                if hasattr(next_due, 'date'):
                    next_due = next_due
                next_due = next_due + relativedelta(months=months)
                next_row = db.execute(text("""
                    INSERT INTO tax_calendar (title, tax_type, branch_id, due_date, reminder_days, is_recurring, recurrence_months, notes, created_by)
                    VALUES (:title, :tax_type, :branch_id, :next_due, CAST(:reminder_days AS jsonb), true, :months, :notes, :user_id)
                    RETURNING id
                """), {
                    "title": item["title"],
                    "tax_type": item.get("tax_type"),
                    "branch_id": item.get("branch_id"),
                    "next_due": next_due,
                    "reminder_days": json.dumps(item.get("reminder_days", [7, 3, 1])),
                    "months": months,
                    "notes": item.get("notes"),
                    "user_id": current_user.id
                }).fetchone()
                new_id = next_row[0] if next_row else None
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="taxes.calendar.complete", resource_type="tax_calendar",
                         resource_id=str(item_id), details={"next_recurrence_id": new_id},
                         request=request)
            return {"message": i18n_message("record_completed", request), "next_recurrence_id": new_id}
        except HTTPException:
            raise
        except Exception as e:
            pass
            logger.error(f"Error completing calendar item: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
