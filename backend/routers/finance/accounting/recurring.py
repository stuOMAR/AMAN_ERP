"""accounting sub-router — split from monolithic accounting.py (T6.3).

Mounted under the parent router via accounting/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Body, Request
from utils.i18n import http_error, i18n_message
from typing import Any, Dict, List, Optional
from sqlalchemy import text
from routers.auth import get_current_user
from utils.tx import transactional
import logging
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from utils.permissions import branch_scope_filter, require_permission, validate_branch_access
from utils.audit import log_activity
from utils.accounting import get_base_currency
from utils.limiter import limiter

logger = logging.getLogger(__name__)
_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')

def _dec(v) -> Decimal:
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return Decimal("0")
    return Decimal(str(v)) if v is not None else Decimal('0')


def _money_str(v) -> str:
    return str(_dec(v).quantize(_D2, ROUND_HALF_UP))

router = APIRouter()

from .core import _D2, _D4, _dec, _create_entry_from_template  # noqa: E402

@router.get("/recurring-templates", dependencies=[Depends(require_permission("accounting.view"))], response_model=List[Dict[str, Any]])
@limiter.limit("200/minute")
def list_recurring_templates(
    request: Request,
    is_active: Optional[bool] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """قائمة قوالب القيود المتكررة"""
    with transactional(current_user.company_id) as db:
        query = """
            SELECT t.*,
                   u.full_name as created_by_name,
                   (SELECT COUNT(*) FROM recurring_journal_lines WHERE template_id = t.id) as line_count
            FROM recurring_journal_templates t
            LEFT JOIN company_users u ON t.created_by = u.id
        """
        params = {}
        conditions = []
        if is_active is not None:
            conditions.append("t.is_active = :active")
            params["active"] = is_active
        if branch_id is not None:
            conditions.append("t.branch_id = :branch_id")
            params["branch_id"] = branch_id
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY t.created_at DESC"
        rows = db.execute(text(query), params).fetchall()
        return [dict(r._mapping) for r in rows]
@router.get("/recurring-templates/{template_id}", dependencies=[Depends(require_permission("accounting.view"))], response_model=Dict[str, Any])
@limiter.limit("200/minute")
def get_recurring_template(request: Request, template_id: int, current_user: dict = Depends(get_current_user)):
    """تفاصيل قالب قيد متكرر مع بنوده"""
    with transactional(current_user.company_id) as db:
        tmpl = db.execute(text("""
            SELECT t.*, u.full_name as created_by_name
            FROM recurring_journal_templates t
            LEFT JOIN company_users u ON t.created_by = u.id
            WHERE t.id = :id
        """), {"id": template_id}).fetchone()
        if not tmpl:
            raise HTTPException(**http_error(404, "template_not_found"))
        validate_branch_access(current_user, tmpl.branch_id, request)

        lines = db.execute(text("""
            SELECT l.*, a.name as account_name, a.account_code as account_code
            FROM recurring_journal_lines l
            JOIN accounts a ON l.account_id = a.id
            WHERE l.template_id = :tid
            ORDER BY l.id
        """), {"tid": template_id}).fetchall()

        result = dict(tmpl._mapping)
        result["lines"] = [dict(line._mapping) for line in lines]
        result["total_debit"] = _money_str(sum((_dec(line.debit) for line in lines), Decimal("0")))
        result["total_credit"] = _money_str(sum((_dec(line.credit) for line in lines), Decimal("0")))
        return result


@router.post("/recurring-templates", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("accounting.edit"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
def create_recurring_template(request: Request, data: dict = Body(...), current_user: dict = Depends(get_current_user)):
    """إنشاء قالب قيد متكرر جديد"""
    with transactional(current_user.company_id) as db:
        try:
            lines = data.pop("lines", [])
            if not lines or len(lines) < 2:
                raise HTTPException(**http_error(400, "at_least_two_lines_required", request))
    
            total_debit = sum(_dec(line.get("debit", 0)) for line in lines)
            total_credit = sum(_dec(line.get("credit", 0)) for line in lines)
            if (total_debit - total_credit).copy_abs() > _D4:
                raise HTTPException(status_code=400, detail=i18n_message("journal_entry_unbalanced", request))
    
            result = db.execute(text("""
                INSERT INTO recurring_journal_templates
                    (name, description, reference, frequency, start_date, end_date,
                     next_run_date, is_active, auto_post, branch_id, currency,
                     exchange_rate, max_runs, created_by)
                VALUES
                    (:name, :description, :reference, :frequency, :start_date, :end_date,
                     :next_run_date, :is_active, :auto_post, :branch_id, :currency,
                     :exchange_rate, :max_runs, :created_by)
                RETURNING id
            """), {
                "name": data.get("name"),
                "description": data.get("description"),
                "reference": data.get("reference"),
                "frequency": data.get("frequency", "monthly"),
                "start_date": data.get("start_date"),
                "end_date": data.get("end_date"),
                "next_run_date": data.get("next_run_date") or data.get("start_date"),
                "is_active": data.get("is_active", True),
                "auto_post": data.get("auto_post", False),
                "branch_id": data.get("branch_id") or getattr(current_user, "branch_id", None),
                "currency": data.get("currency", get_base_currency(db)),
                "exchange_rate": _dec(data.get("exchange_rate", 1)),
                "max_runs": data.get("max_runs"),
                "created_by": current_user.id,
            })
            template_id = result.fetchone()[0]
    
            for line in lines:
                db.execute(text("""
                    INSERT INTO recurring_journal_lines
                        (template_id, account_id, debit, credit, description, cost_center_id)
                    VALUES (:tid, :account_id, :debit, :credit, :desc, :cc)
                """), {
                    "tid": template_id,
                    "account_id": line["account_id"],
                    "debit": _dec(line.get("debit", 0)),
                    "credit": _dec(line.get("credit", 0)),
                    "desc": line.get("description", ""),
                    "cc": line.get("cost_center_id"),
                })
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="accounting.recurring_template.create",
                         resource_type="recurring_template", resource_id=str(template_id),
                         details={"name": data.get('name')})
            return {"id": template_id, "message": i18n_message("recurring_template_created", request)}
        except HTTPException:
            raise
        except Exception:
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
@router.put("/recurring-templates/{template_id}", dependencies=[Depends(require_permission("accounting.edit"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
def update_recurring_template(request: Request, template_id: int, data: dict = Body(...), current_user: dict = Depends(get_current_user)):
    """تعديل قالب قيد متكرر"""
    with transactional(current_user.company_id) as db:
        try:
            existing = db.execute(text(
                "SELECT id, branch_id FROM recurring_journal_templates WHERE id = :id"
            ), {"id": template_id}).fetchone()
            if not existing:
                raise HTTPException(**http_error(404, "template_not_found"))
            validate_branch_access(current_user, existing.branch_id, request)
    
            lines = data.pop("lines", None)
    
            db.execute(text("""
                UPDATE recurring_journal_templates SET
                    name = COALESCE(:name, name),
                    description = COALESCE(:description, description),
                    reference = COALESCE(:reference, reference),
                    frequency = COALESCE(:frequency, frequency),
                    start_date = COALESCE(:start_date, start_date),
                    end_date = :end_date,
                    next_run_date = COALESCE(:next_run_date, next_run_date),
                    is_active = COALESCE(:is_active, is_active),
                    auto_post = COALESCE(:auto_post, auto_post),
                    currency = COALESCE(:currency, currency),
                    exchange_rate = COALESCE(:exchange_rate, exchange_rate),
                    max_runs = :max_runs,
                    updated_at = NOW()
                WHERE id = :id
            """), {
                "id": template_id,
                "name": data.get("name"),
                "description": data.get("description"),
                "reference": data.get("reference"),
                "frequency": data.get("frequency"),
                "start_date": data.get("start_date"),
                "end_date": data.get("end_date"),
                "next_run_date": data.get("next_run_date"),
                "is_active": data.get("is_active"),
                "auto_post": data.get("auto_post"),
                "currency": data.get("currency"),
                "exchange_rate": data.get("exchange_rate"),
                "max_runs": data.get("max_runs"),
            })
    
            if lines is not None:
                if len(lines) < 2:
                    raise HTTPException(**http_error(400, "at_least_two_lines_required", request))
                total_debit = sum(_dec(line.get("debit", 0)) for line in lines)
                total_credit = sum(_dec(line.get("credit", 0)) for line in lines)
                if (total_debit - total_credit).copy_abs() > _D4:
                    raise HTTPException(status_code=400, detail=i18n_message("journal_entry_unbalanced", request))
    
                db.execute(text("DELETE FROM recurring_journal_lines WHERE template_id = :tid"), {"tid": template_id})
                for line in lines:
                    db.execute(text("""
                        INSERT INTO recurring_journal_lines
                            (template_id, account_id, debit, credit, description, cost_center_id)
                        VALUES (:tid, :account_id, :debit, :credit, :desc, :cc)
                    """), {
                        "tid": template_id,
                        "account_id": line["account_id"],
                        "debit": _dec(line.get("debit", 0)),
                        "credit": _dec(line.get("credit", 0)),
                        "desc": line.get("description", ""),
                        "cc": line.get("cost_center_id"),
                    })
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="accounting.recurring_template.update",
                         resource_type="recurring_template", resource_id=str(template_id),
                         details={"template_id": template_id})
            return {"success": True, "message": i18n_message("recurring_template_updated", request)}
        except HTTPException:
            raise
        except Exception:
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
@router.delete("/recurring-templates/{template_id}", dependencies=[Depends(require_permission("accounting.manage"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
def delete_recurring_template(request: Request, template_id: int, current_user: dict = Depends(get_current_user)):
    """حذف قالب قيد متكرر"""
    with transactional(current_user.company_id) as db:
        try:
            existing = db.execute(text(
                "SELECT id, name, branch_id FROM recurring_journal_templates WHERE id = :id"
            ), {"id": template_id}).fetchone()
            if not existing:
                raise HTTPException(**http_error(404, "template_not_found"))
            validate_branch_access(current_user, existing.branch_id, request)
    
            db.execute(text("DELETE FROM recurring_journal_templates WHERE id = :id"), {"id": template_id})
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="accounting.recurring_template.delete",
                         resource_type="recurring_template", resource_id=str(template_id),
                         details={"name": existing.name})
            return {"success": True, "message": i18n_message("recurring_template_deleted", request)}
        except HTTPException:
            raise
        except Exception:
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
@router.post("/recurring-templates/{template_id}/generate", dependencies=[Depends(require_permission("accounting.edit"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
def generate_from_template(request: Request, template_id: int, current_user: dict = Depends(get_current_user)):
    """توليد قيد يومي من قالب متكرر يدوياً"""
    with transactional(current_user.company_id) as db:
        try:
            idempotency_key = request.headers.get("Idempotency-Key")
            if idempotency_key:
                from utils.idempotency import find_je_by_idempotency_key
                existing = find_je_by_idempotency_key(db, idempotency_key)
                if existing:
                    je_id, _ = existing
                    return {"success": True, "message": i18n_message("recurring_entry_generated", request), "entry_id": je_id}

            tmpl = db.execute(text(
                "SELECT * FROM recurring_journal_templates WHERE id = :id"
            ), {"id": template_id}).fetchone()
            if not tmpl:
                raise HTTPException(**http_error(404, "template_not_found"))
            validate_branch_access(current_user, tmpl.branch_id, request)
    
            lines = db.execute(text(
                "SELECT * FROM recurring_journal_lines WHERE template_id = :tid ORDER BY id"
            ), {"tid": template_id}).fetchall()
            if not lines:
                raise HTTPException(**http_error(400, "template_has_no_lines", request))
    
            entry_id = _create_entry_from_template(db, tmpl, lines, current_user, idempotency_key=idempotency_key)
    
            return {"success": True, "message": i18n_message("recurring_entry_generated", request), "entry_id": entry_id}
        except HTTPException:
            raise
        except Exception:
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
@router.post("/recurring-templates/generate-due", dependencies=[Depends(require_permission("accounting.manage"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
def generate_all_due_templates(request: Request, current_user: dict = Depends(get_current_user)):
    """توليد القيود المستحقة لجميع القوالب النشطة (يُستخدم بالجدولة)"""
    with transactional(current_user.company_id) as db:
        try:
            idempotency_key = request.headers.get("Idempotency-Key")
            if idempotency_key:
                prefix = f"due-{idempotency_key}-%"
                rows = db.execute(text("""
                    SELECT id, source_id FROM journal_entries
                    WHERE idempotency_key LIKE :k
                """), {"k": prefix}).fetchall()
                if rows:
                    generated = []
                    for r in rows:
                        name_row = db.execute(text("SELECT name FROM recurring_journal_templates WHERE id = :id"), {"id": r.source_id}).fetchone()
                        generated.append({
                            "template_id": r.source_id,
                            "template_name": name_row.name if name_row else f"Template #{r.source_id}",
                            "entry_id": r.id
                        })
                    return {
                        "success": True,
                        "generated_count": len(generated),
                        "error_count": 0,
                        "generated": generated,
                        "errors": [],
                    }

            today = date.today()
            params: Dict[str, Any] = {"today": today}
            branch_filter = branch_scope_filter(current_user, None, "branch_id", params)
            templates = db.execute(text(f"""
                SELECT * FROM recurring_journal_templates
                WHERE is_active = TRUE
                  AND next_run_date <= :today
                  AND (end_date IS NULL OR end_date >= :today)
                  AND (max_runs IS NULL OR run_count < max_runs)
                  {branch_filter}
                ORDER BY next_run_date
            """), params).fetchall()
    
            generated = []
            errors = []
            for tmpl in templates:
                try:
                    lines = db.execute(text(
                        "SELECT * FROM recurring_journal_lines WHERE template_id = :tid ORDER BY id"
                    ), {"tid": tmpl.id}).fetchall()
                    if not lines:
                        continue
    
                    tmpl_idem_key = f"due-{idempotency_key}-{tmpl.id}" if idempotency_key else None
                    entry_id = _create_entry_from_template(db, tmpl, lines, current_user, idempotency_key=tmpl_idem_key)
                    generated.append({"template_id": tmpl.id, "template_name": tmpl.name, "entry_id": entry_id})
                except Exception as ex:
                    errors.append({"template_id": tmpl.id, "template_name": tmpl.name, "error": str(ex)})
    
            return {
                "success": True,
                "generated_count": len(generated),
                "error_count": len(errors),
                "generated": generated,
                "errors": errors,
            }
        except Exception:
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
