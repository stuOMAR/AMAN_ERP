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
from utils.permissions import branch_scope_filter, require_permission, validate_branch_access, require_module
from utils.accounting import (
    generate_sequential_number, get_mapped_account_id,
    get_base_currency, compute_line_amounts, compute_invoice_totals
)
from utils.audit import log_activity
from utils.fiscal_lock import check_fiscal_period_open
from sqlalchemy import text
from services.gl_service import create_journal_entry as gl_create_journal_entry
from services.tax_engine import resolve_line_tax
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

def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')

router = APIRouter()
from schemas.projects import (
    ProjectCreate, ProjectUpdate, TaskCreate, TaskUpdate,
    ProjectExpenseCreate, ProjectRevenueCreate,
    TimesheetCreate, TimesheetUpdate, TimesheetApprove,
    ProjectInvoiceCreate, ChangeOrderCreate, ChangeOrderUpdate, ProjectCloseRequest,
    ProjectRiskCreate, ProjectRiskUpdate, TaskDependencyCreate
)


# ═══════════════════════════════════════════════════════════
# Projects CRUD
# ═══════════════════════════════════════════════════════════

@router.get("/", dependencies=[Depends(require_permission("projects.view"))], response_model=List[Dict[str, Any]])
async def get_projects(
    status_filter: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """جلب قائمة المشاريع مع ملخص مالي"""
    db = get_db_connection(current_user.company_id)
    try:
        params = {}
        filters = ["1=1"]

        if status_filter:
            filters.append("p.status = :status")
            params["status"] = status_filter

        branch_clause = branch_scope_filter(current_user, branch_id, "p.branch_id", params)
        if branch_clause:
            filters.append(branch_clause[4:].strip() if branch_clause.startswith("AND ") else branch_clause.strip())

        where = " AND ".join(filters)

        result = db.execute(text(f"""
            SELECT p.*,
                c.name as customer_name,
                CONCAT(e.first_name, ' ', e.last_name) as manager_name,
                COALESCE(exp.total_expenses, 0) as total_expenses,
                COALESCE(rev.total_revenues, 0) as total_revenues,
                COALESCE(tasks.total_tasks, 0) as total_tasks,
                COALESCE(tasks.completed_tasks, 0) as completed_tasks
            FROM projects p
            LEFT JOIN parties c ON p.customer_id = c.id
            LEFT JOIN employees e ON p.manager_id = e.id
            LEFT JOIN (
                SELECT project_id, SUM(amount) as total_expenses
                FROM project_expenses WHERE status != 'rejected'
                GROUP BY project_id
            ) exp ON exp.project_id = p.id
            LEFT JOIN (
                SELECT project_id, SUM(amount) as total_revenues
                FROM project_revenues WHERE status != 'rejected'
                GROUP BY project_id
            ) rev ON rev.project_id = p.id
            LEFT JOIN (
                SELECT project_id,
                       COUNT(*) as total_tasks,
                       COUNT(*) FILTER (WHERE status = 'completed') as completed_tasks
                FROM project_tasks
                GROUP BY project_id
            ) tasks ON tasks.project_id = p.id
            WHERE {where}
            ORDER BY p.created_at DESC
        """), params).fetchall()

        return [dict(r._mapping) for r in result]
    except Exception as e:
        logger.error(f"Error fetching projects: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.get("/summary", dependencies=[Depends(require_permission("projects.view"))], response_model=Dict[str, Any])
async def get_projects_summary(current_user: dict = Depends(get_current_user)):
    """ملخص إحصائي للمشاريع"""
    db = get_db_connection(current_user.company_id)
    try:
        stats = db.execute(text("""
            SELECT
                COUNT(*) as total_projects,
                COUNT(*) FILTER (WHERE status = 'planning') as planning,
                COUNT(*) FILTER (WHERE status = 'in_progress') as in_progress,
                COUNT(*) FILTER (WHERE status = 'completed') as completed,
                COUNT(*) FILTER (WHERE status = 'on_hold') as on_hold,
                COUNT(*) FILTER (WHERE status = 'cancelled') as cancelled,
                COALESCE(SUM(planned_budget), 0) as total_budget,
                COALESCE(SUM(actual_cost), 0) as total_actual_cost
            FROM projects
        """)).fetchone()

        return dict(stats._mapping)
    except Exception as e:
        logger.error(f"Error fetching project summary: {e}")
        return {
            "total_projects": 0, "planning": 0, "in_progress": 0,
            "completed": 0, "on_hold": 0, "cancelled": 0,
            "total_budget": 0, "total_actual_cost": 0
        }
    finally:
        db.close()


# NOTE: /timetracking must be defined BEFORE /{project_id} to avoid route shadowing
@router.get("/{project_id}", dependencies=[Depends(require_permission("projects.view"))], response_model=Dict[str, Any])
async def get_project(project_id: int, current_user: dict = Depends(get_current_user)):
    """جلب تفاصيل مشروع مع المهام والمصاريف والإيرادات"""
    db = get_db_connection(current_user.company_id)
    try:
        project = db.execute(text("""
            SELECT p.*,
                c.name as customer_name, c.party_code as customer_code,
                CONCAT(e.first_name, ' ', e.last_name) as manager_name
            FROM projects p
            LEFT JOIN parties c ON p.customer_id = c.id
            LEFT JOIN employees e ON p.manager_id = e.id
            WHERE p.id = :id
        """), {"id": project_id}).fetchone()

        if not project:
            raise HTTPException(**http_error(404, "project_not_found"))

        project_data: Dict[str, Any] = dict(project._mapping)

        # Tasks
        tasks = db.execute(text("""
            SELECT pt.*,
                CONCAT(e.first_name, ' ', e.last_name) as assigned_to_name
            FROM project_tasks pt
            LEFT JOIN employees e ON pt.assigned_to = e.id
            WHERE pt.project_id = :id
            ORDER BY pt.id
        """), {"id": project_id}).fetchall()
        project_data["tasks"] = [dict(t._mapping) for t in tasks]

        # Expenses
        expenses = db.execute(text("""
            SELECT pe.*,
                COALESCE(u.full_name, '') as created_by_name
            FROM project_expenses pe
            LEFT JOIN company_users u ON pe.created_by = u.id
            WHERE pe.project_id = :id
            ORDER BY pe.expense_date DESC
        """), {"id": project_id}).fetchall()
        project_data["expenses"] = [dict(ex._mapping) for ex in expenses]

        # Revenues
        revenues = db.execute(text("""
            SELECT pr.*,
                COALESCE(u.full_name, '') as created_by_name
            FROM project_revenues pr
            LEFT JOIN company_users u ON pr.created_by = u.id
            WHERE pr.project_id = :id
            ORDER BY pr.revenue_date DESC
        """), {"id": project_id}).fetchall()
        project_data["revenues"] = [dict(rv._mapping) for rv in revenues]

        # Financial summary
        total_exp = sum(_dec(ex.get("amount", 0)) for ex in project_data["expenses"] if ex.get("status") != "rejected")
        total_rev = sum(_dec(rv.get("amount", 0)) for rv in project_data["revenues"] if rv.get("status") != "rejected")
        planned = _dec(project_data.get("planned_budget") or 0)
        budget_consumed_pct = ((total_exp / planned) * Decimal('100')).quantize(_D2, ROUND_HALF_UP) if planned > 0 else Decimal('0')

        project_data["financial_summary"] = {
            "planned_budget": float(planned),
            "total_expenses": float(total_exp),
            "total_revenues": float(total_rev),
            "profit_loss": float(total_rev - total_exp),
            "budget_consumed_pct": float(budget_consumed_pct),
        }

        return project_data
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching project {project_id}: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.post("/", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("projects.create"))], response_model=Dict[str, Any])
async def create_project(
    request: Request,
    project: ProjectCreate,
    current_user: dict = Depends(get_current_user)
):
    """إنشاء مشروع جديد"""
    db = get_db_connection(current_user.company_id)
    try:
        # T034: Validate start_date <= end_date
        if project.start_date and project.end_date and project.end_date < project.start_date:
            raise HTTPException(**http_error(400, "project_end_before_start"))

        code = project.project_code
        if not code:
            code = generate_sequential_number(db, f"PRJ-{datetime.now().year}", "projects", "project_code")

        result = db.execute(text("""
            INSERT INTO projects (
                project_code, project_name, project_name_en, description,
                project_type, customer_id, manager_id,
                start_date, end_date, planned_budget, status, created_by,
                branch_id, contract_type
            ) VALUES (
                :code, :name, :name_en, :desc,
                :type, :cid, :mid,
                :start, :end, :budget, :status, :uid,
                :branch_id, :contract_type
            ) RETURNING id
        """), {
            "code": code, "name": project.project_name,
            "name_en": project.project_name_en, "desc": project.description,
            "type": project.project_type, "cid": project.customer_id,
            "mid": project.manager_id,
            "start": project.start_date, "end": project.end_date,
            "budget": project.planned_budget, "status": project.status,
            "uid": current_user.id,
            "branch_id": project.branch_id, "contract_type": project.contract_type
        })
        project_id = result.scalar()
        db.commit()

        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="project.create", resource_type="project",
            resource_id=str(project_id),
            details={"project_name": project.project_name, "budget": project.planned_budget},
            request=request, branch_id=project.branch_id
        )

        return {"success": True, "id": project_id, "project_code": code, "message": i18n_message("project_created_success")}
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating project: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.put("/{project_id}", dependencies=[Depends(require_permission("projects.edit"))], response_model=Dict[str, Any])
async def update_project(
    project_id: int,
    data: ProjectUpdate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """تحديث بيانات مشروع"""
    db = get_db_connection(current_user.company_id)
    try:
        existing = db.execute(text("SELECT * FROM projects WHERE id = :id"), {"id": project_id}).fetchone()
        if not existing:
            raise HTTPException(**http_error(404, "project_not_found"))

        updates = []
        params = {"id": project_id}

        field_map = {
            "project_name": "name", "project_name_en": "name_en",
            "description": "desc", "project_type": "type",
            "customer_id": "cid", "manager_id": "mid",
            "start_date": "start", "end_date": "end",
            "planned_budget": "budget", "status": "status",
            "progress_percentage": "pct"
        }

        for field, param in field_map.items():
            value = getattr(data, field, None)
            if value is not None:
                if field == "status":
                    valid = ['planning', 'in_progress', 'on_hold', 'completed', 'cancelled']
                    if value not in valid:
                        raise HTTPException(status_code=400, detail=i18n_message("invalid_status_available", valid=', '.join(valid)))
                if field == "progress_percentage" and (value < 0 or value > 100):
                    raise HTTPException(status_code=400, detail=i18n_message("project_progress_between_0_100"))
                updates.append(f"{field} = :{param}")
                params[param] = value

        if not updates:
            raise HTTPException(**http_error(400, "no_data_to_update"))

        updates.append("updated_at = NOW()")
        query = f"UPDATE projects SET {', '.join(updates)} WHERE id = :id"
        db.execute(text(query), params)
        db.commit()

        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="project.update", resource_type="project",
            resource_id=str(project_id), details={}, request=request
        )

        return {"success": True, "message": i18n_message("project_updated_success")}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating project: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.delete("/{project_id}", dependencies=[Depends(require_permission("projects.delete"))], response_model=Dict[str, Any])
async def delete_project(project_id: int, request: Request, current_user: dict = Depends(get_current_user)):
    """حذف مشروع (فقط إذا لم يكن له مصاريف أو إيرادات مرحّلة)"""
    db = get_db_connection(current_user.company_id)
    try:
        existing = db.execute(text("SELECT id FROM projects WHERE id = :id"), {"id": project_id}).fetchone()
        if not existing:
            raise HTTPException(**http_error(404, "project_not_found"))

        has_posted = db.execute(text("""
            SELECT COUNT(*) FROM (
                SELECT id FROM project_expenses WHERE project_id = :id AND status = 'approved'
                UNION ALL
                SELECT id FROM project_revenues WHERE project_id = :id AND status = 'approved'
            ) x
        """), {"id": project_id}).scalar()

        if has_posted > 0:
            raise HTTPException(
                status_code=400,
                detail=i18n_message("project_delete_blocked_has_posted_financials")
            )

        db.execute(text("DELETE FROM project_revenues WHERE project_id = :id"), {"id": project_id})
        db.execute(text("DELETE FROM project_expenses WHERE project_id = :id"), {"id": project_id})
        db.execute(text("DELETE FROM project_budgets WHERE project_id = :id"), {"id": project_id})
        db.execute(text("DELETE FROM project_tasks WHERE project_id = :id"), {"id": project_id})
        db.execute(text("DELETE FROM projects WHERE id = :id"), {"id": project_id})
        db.commit()

        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="project.delete", resource_type="project",
            resource_id=str(project_id), details={}, request=request
        )

        return {"success": True, "message": i18n_message("project_deleted_success")}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting project: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# Project Tasks
# ═══════════════════════════════════════════════════════════

@router.get("/{project_id}/financials", dependencies=[Depends(require_permission("projects.view"))], response_model=Dict[str, Any])
async def get_project_financials(project_id: int, current_user: dict = Depends(get_current_user)):
    """تقرير مالي شامل للمشروع"""
    db = get_db_connection(current_user.company_id)
    try:
        project = db.execute(text("SELECT * FROM projects WHERE id = :id"), {"id": project_id}).fetchone()
        if not project:
            raise HTTPException(**http_error(404, "project_not_found"))

        p = project._mapping

        expenses_by_type = db.execute(text("""
            SELECT expense_type, COUNT(*) as count, SUM(amount) as total
            FROM project_expenses
            WHERE project_id = :pid AND status != 'rejected'
            GROUP BY expense_type
        """), {"pid": project_id}).fetchall()

        revenues_by_type = db.execute(text("""
            SELECT revenue_type, COUNT(*) as count, SUM(amount) as total
            FROM project_revenues
            WHERE project_id = :pid AND status != 'rejected'
            GROUP BY revenue_type
        """), {"pid": project_id}).fetchall()

        monthly = db.execute(text("""
            SELECT
                TO_CHAR(d.month, 'YYYY-MM') as period,
                COALESCE(e.total, 0) as expenses,
                COALESCE(r.total, 0) as revenues
            FROM (
                SELECT DISTINCT DATE_TRUNC('month', expense_date) as month FROM project_expenses WHERE project_id = :pid
                UNION
                SELECT DISTINCT DATE_TRUNC('month', revenue_date) FROM project_revenues WHERE project_id = :pid
            ) d
            LEFT JOIN (
                SELECT DATE_TRUNC('month', expense_date) as month, SUM(amount) as total
                FROM project_expenses WHERE project_id = :pid AND status != 'rejected'
                GROUP BY DATE_TRUNC('month', expense_date)
            ) e ON e.month = d.month
            LEFT JOIN (
                SELECT DATE_TRUNC('month', revenue_date) as month, SUM(amount) as total
                FROM project_revenues WHERE project_id = :pid AND status != 'rejected'
                GROUP BY DATE_TRUNC('month', revenue_date)
            ) r ON r.month = d.month
            ORDER BY d.month
        """), {"pid": project_id}).fetchall()

        total_exp = sum((_dec(e._mapping["total"]) for e in expenses_by_type), Decimal('0'))
        total_rev = sum((_dec(r._mapping["total"]) for r in revenues_by_type), Decimal('0'))
        planned = _dec(p.get("planned_budget") or 0)
        
        # Calculate Indirect Costs (Overhead) - For now, assume a fixed 15% of Labor if not explicitly recorded
        # In a real scenario, this might come from a specific 'overhead' expense type
        labor_cost = next((_dec(e._mapping["total"]) for e in expenses_by_type if e._mapping["expense_type"] == 'labor'), Decimal('0'))
        direct_materials = next((_dec(e._mapping["total"]) for e in expenses_by_type if e._mapping["expense_type"] == 'materials'), Decimal('0'))
        
        # If no explicit 'overhead' expense type exists, we can estimate or just list what's there.
        # Let's just categorize existing expenses into Direct (Labor, Materials) and Indirect (Others)
        direct_types = ['labor', 'materials']
        indirect_cost = sum((_dec(e._mapping["total"]) for e in expenses_by_type if e._mapping["expense_type"] not in direct_types), Decimal('0'))

        net_profit = total_rev - total_exp
        margin = (net_profit / total_rev * Decimal('100')) if total_rev > 0 else Decimal('0')

        return {
            "project_id": project_id,
            "project_name": p["project_name"],
            "planned_budget": float(planned.quantize(_D2)),
            "total_expenses": float(total_exp.quantize(_D2)),
            "total_revenues": float(total_rev.quantize(_D2)),
            "net_profit": float(net_profit.quantize(_D2)),
            "margin_pct": float(margin.quantize(_D2)),
            "budget_remaining": float((planned - total_exp).quantize(_D2)),
            "budget_consumed_pct": float(((total_exp / planned) * Decimal('100')).quantize(_D2)) if planned > 0 else 0,
            "cost_breakdown": {
                "labor": float(labor_cost.quantize(_D2)),
                "materials": float(direct_materials.quantize(_D2)),
                "indirect_overhead": float(indirect_cost.quantize(_D2)),
                "details": [dict(e._mapping) for e in expenses_by_type]
            },
            "revenues_by_type": [dict(r._mapping) for r in revenues_by_type],
            "monthly_breakdown": [dict(m._mapping) for m in monthly],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching financials: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# Timesheets (PRJ-002)
# ═══════════════════════════════════════════════════════════

@router.post("/{project_id}/documents", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("projects.edit"))], response_model=Dict[str, Any])
async def create_project_document(
    project_id: int,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    """رفع مستند للمشروع"""
    global uploads_dir # Assuming it's available or we find path relative to main
    # But main.py defined it. We should use absolute path or config.
    # We will use 'uploads/projects' relative to backend root or where we are running.
    
    upload_folder = "uploads/projects"
    os.makedirs(upload_folder, exist_ok=True)
    
    from utils.sql_safety import (
        validate_file_extension,
        validate_file_size,
        validate_file_mime_and_signature,
        MAX_DOCUMENT_SIZE,
        ALLOWED_DOCUMENT_EXTENSIONS,
    )

    content = await file.read()
    validate_file_extension(file.filename, ALLOWED_DOCUMENT_EXTENSIONS, "المستند")
    validate_file_size(content, MAX_DOCUMENT_SIZE, "المستند")
    file_ext = validate_file_mime_and_signature(file.filename, file.content_type, content, "المستند")

    unique_filename = f"{project_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}{file_ext}"
    file_path = os.path.join(upload_folder, unique_filename)
    
    with open(file_path, "wb") as buffer:
        buffer.write(content)
        
    file_url = f"/uploads/projects/{unique_filename}"
    
    db = get_db_connection(current_user.company_id)
    try:
        doc_id = db.execute(text("""
            INSERT INTO project_documents (
                project_id, file_name, file_url, file_type, uploaded_by
            ) VALUES (:pid, :name, :url, :type, :uid)
            RETURNING id
        """), {
            "pid": project_id,
            "name": file.filename,
            "url": file_url,
            "type": file.content_type,
            "uid": current_user.id
        }).scalar()
        
        db.commit()
        return {"success": True, "id": doc_id, "file_url": file_url, "message": i18n_message("project_document_uploaded_success")}
    except Exception as e:
        db.rollback()
        logger.error(f"Error uploading document: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()

@router.get("/{project_id}/documents", dependencies=[Depends(require_permission("projects.view"))], response_model=Dict[str, Any])
async def get_project_documents(project_id: int, current_user: dict = Depends(get_current_user)):
    """جلب مستندات المشروع"""
    from utils.signed_urls import sign_upload_path  # T2.6: time-limited download links
    db = get_db_connection(current_user.company_id)
    try:
        docs = db.execute(text("""
            SELECT pd.*, u.full_name as uploaded_by_name
            FROM project_documents pd
            LEFT JOIN company_users u ON pd.uploaded_by = u.id
            WHERE pd.project_id = :pid
            ORDER BY pd.created_at DESC
        """), {"pid": project_id}).fetchall()
        out = []
        for d in docs:
            row = dict(d._mapping)
            # Caller already passed the projects.view permission check above;
            # we hand back a signed URL valid for 10 minutes.
            if row.get("file_url"):
                row["file_url"] = sign_upload_path(row["file_url"])
            out.append(row)
        return out
    finally:
        db.close()

@router.delete("/{project_id}/documents/{doc_id}", dependencies=[Depends(require_permission("projects.edit"))], response_model=Dict[str, Any])
async def delete_project_document(project_id: int, doc_id: int, current_user: dict = Depends(get_current_user)):
    """حذف مستند"""
    db = get_db_connection(current_user.company_id)
    try:
        # Get file path to delete from disk
        doc = db.execute(text("SELECT file_url FROM project_documents WHERE id = :id AND project_id = :pid"),
                         {"id": doc_id, "pid": project_id}).fetchone()
        
        if doc and doc.file_url:
            # Construct absolute path. stored as /uploads/...
            # We assume running from backend root, so remove leading /
            rel_path = doc.file_url.lstrip("/")
            # T046: Path traversal validation — ensure path stays within uploads/
            safe_base = os.path.abspath("uploads")
            abs_path = os.path.abspath(rel_path)
            if not abs_path.startswith(safe_base):
                raise HTTPException(**http_error(400, "invalid_file_path", request))
            if os.path.exists(abs_path):
                os.remove(abs_path)
                
        db.execute(text("DELETE FROM project_documents WHERE id = :id"), {"id": doc_id})
        db.commit()
        return {"success": True, "message": i18n_message("project_document_deleted_success")}
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting document: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# Project Invoicing
# ═══════════════════════════════════════════════════════════

@router.post("/{project_id}/create-invoice", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("projects.edit"))], response_model=Dict[str, Any])
async def create_project_invoice(
    project_id: int,
    invoice_data: ProjectInvoiceCreate,
    current_user: dict = Depends(get_current_user)
):
    """إنشاء فاتورة مبيعات من المشروع"""
    db = get_db_connection(current_user.company_id)
    try:
        # Enforce fiscal period lock before invoice JE
        check_fiscal_period_open(db, invoice_data.invoice_date)

        # Verify Project
        project = db.execute(text("SELECT * FROM projects WHERE id = :id"), {"id": project_id}).fetchone()
        if not project:
            raise HTTPException(**http_error(404, "project_not_found"))
            
        # 1. Generate Invoice Number
        inv_num = generate_sequential_number(db, f"INV-{datetime.now().year}", "invoices", "invoice_number", branch_id=project.branch_id)
        
        # 2. Calculate Totals (centralized — no inline float math)
        line_dicts = []
        line_items_data = []
        for item in invoice_data.items:
            if item.product_id and project.branch_id:
                tax_info = resolve_line_tax(project.branch_id, item.product_id, db, invoice_data.invoice_date, customer_id=invoice_data.customer_id)
                effective_tax_rate = tax_info["tax_rate"]
            else:
                effective_tax_rate = _dec(item.tax_rate or 0)
            la = compute_line_amounts(
                item.quantity,
                item.unit_price,
                effective_tax_rate,
                item.discount,
                discount_is_percent=False,
            )
            line_dicts.append({"quantity": item.quantity, "unit_price": item.unit_price,
                               "tax_rate": effective_tax_rate, "discount": item.discount})
            line_items_data.append({
                "pid": item.product_id,
                "desc": item.description,
                "qty": item.quantity,
                "price": item.unit_price,
                "tax": effective_tax_rate,
                "disc": item.discount,
                "total": la["line_total"]
            })
        totals = compute_invoice_totals(line_dicts, discount_is_percent=False)
        subtotal = totals["subtotal"]
        total_tax = totals["total_tax"]
        total_discount = totals["total_discount"]
        grand_total = totals["grand_total"]
        
        # 3. Create Invoice Header
        inv_currency = invoice_data.currency or get_base_currency(db)
        exchange_rate = invoice_data.exchange_rate or Decimal("1")
        
        inv_id = db.execute(text("""
            INSERT INTO invoices (
                invoice_number, party_id, invoice_type, invoice_date, due_date,
                subtotal, tax_amount, discount, total, paid_amount, status, notes,
                payment_method, created_by, branch_id, warehouse_id,
                currency, exchange_rate
            ) VALUES (
                :num, :cust, 'sales', :inv_date, :due_date,
                :sub, :tax, :disc, :total, 0, 'unpaid', :notes,
                :pay_method, :user, :branch, :wh,
                :currency, :rate
            ) RETURNING id
        """), {
            "num": inv_num, "cust": invoice_data.customer_id,
            "inv_date": invoice_data.invoice_date, "due_date": invoice_data.due_date,
            "sub": subtotal, "tax": total_tax, "disc": total_discount, "total": grand_total,
            "notes": invoice_data.notes or f"Project Invoice: {project.project_name}",
            "pay_method": invoice_data.payment_method, "user": current_user.id,
            "branch": project.branch_id, "wh": invoice_data.warehouse_id,
            "currency": inv_currency, "rate": exchange_rate
        }).scalar()
        
        # 4. Create Invoice Lines
        for item in line_items_data:
            db.execute(text("""
                INSERT INTO invoice_lines (
                    invoice_id, product_id, description, quantity, unit_price, tax_rate, discount, total
                ) VALUES (
                    :inv_id, :pid, :desc, :qty, :price, :tax, :disc, :total
                )
            """), {
                "inv_id": inv_id, **item
            })
            
            # NOTE: Logic to deduct inventory is skipped here for simplicity as we assume service/milestone invoice often. 
            # If product_id is provided, we should ideally deduct stock, but recreating full sales logic here is risky.
            # Best practice: Call the Internal create_invoice service.
            
        # 5. Link to Project Revenues (Shadow Record)
        # We manually insert into project_revenues to show it in project financials
        # WE DO NOT CREATE GL ENTRIES HERE because the INVOICE will eventually create GL entries when posted/paid or if we implemented full logic.
        # Actually, since we just inserted 'unpaid' invoice above without GL logic, NO GL exists yet.
        # The user will go to Sales -> Invoices to Post/Pay it.
        # So we just link it.
        
        db.execute(text("""
            INSERT INTO project_revenues (
                project_id, revenue_type, revenue_date, amount,
                description, invoice_id, status, created_by
            ) VALUES (
                :pid, 'invoice', :date, :amt, :desc, :inv_id, 'approved', :uid
            )
        """), {
            "pid": project_id,
            "date": invoice_data.invoice_date,
            "amt": grand_total,
            "desc": f"Invoice #{inv_num}",
            "inv_id": inv_id,
            "uid": current_user.id
        })
        
        # 6. Create GL Journal Entry (PRJ-103)
        # Dr: Accounts Receivable (acc_map_ar)
        # Cr: Sales Revenue (acc_map_sales_rev) — subtotal
        # Cr: VAT Output (acc_map_vat_out) — tax_amount (if any)
        je_id = None
        ar_acc = get_mapped_account_id(db, "acc_map_ar")
        rev_acc = get_mapped_account_id(db, "acc_map_sales_rev") or get_mapped_account_id(db, "acc_map_project_revenue")
        base_currency = get_base_currency(db)
        
        if ar_acc and rev_acc and grand_total > 0:
            lines = []
            cost_center_id = db.execute(text(
                "SELECT id FROM cost_centers WHERE center_name ILIKE :name LIMIT 1"
            ), {"name": f"%{project.project_name}%"}).scalar()

            # Dr: Accounts Receivable = grand_total
            lines.append({
                "account_id": ar_acc,
                "debit": grand_total,
                "credit": 0,
                "description": f"ذمم مدينة — فاتورة مشروع {inv_num}",
                "cost_center_id": cost_center_id
            })
            
            # Cr: Revenue = subtotal (before tax)
            net_revenue = subtotal - total_discount
            if net_revenue > 0:
                lines.append({
                    "account_id": rev_acc,
                    "debit": 0,
                    "credit": net_revenue,
                    "description": f"إيراد مشروع {project.project_name}",
                    "cost_center_id": cost_center_id
                })
            
            # Cr: VAT Output = tax_amount (if applicable)
            if total_tax > 0:
                vat_acc = get_mapped_account_id(db, "acc_map_vat_out") or get_mapped_account_id(db, "acc_map_tax_payable")
                if vat_acc:
                    lines.append({
                        "account_id": vat_acc,
                        "debit": 0,
                        "credit": total_tax,
                        "description": f"ضريبة القيمة المضافة — فاتورة مشروع {inv_num}",
                        "cost_center_id": cost_center_id
                    })

            je_id, entry_num = gl_create_journal_entry(
                db=db,
                company_id=current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id,
                date=invoice_data.invoice_date,
                description=f"فاتورة مشروع: {project.project_name} — {inv_num}",
                status="posted",
                currency=inv_currency,
                exchange_rate=exchange_rate,
                lines=lines,
                user_id=current_user.get("id") if isinstance(current_user, dict) else current_user.id,
                source="project_invoice",
                source_id=inv_id
            )
            
            # Update invoice with journal entry reference
            db.execute(text("UPDATE invoices SET notes = notes || ' | JE: ' || :je_num WHERE id = :id"),
                       {"je_num": entry_num, "id": inv_id})
        
        db.commit()
        return {
            "success": True, "invoice_id": inv_id, "invoice_number": inv_num,
            "journal_entry_id": je_id,
            "message": i18n_message("project_invoice_and_je_created_success") if je_id else i18n_message("project_invoice_created_without_je")
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating project invoice: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# Project Change Orders (أوامر التغيير)
# ═══════════════════════════════════════════════════════════

@router.post("/{project_id}/close", dependencies=[Depends(require_permission("projects.edit"))], response_model=Dict[str, Any])
async def close_project(
    project_id: int,
    close_data: ProjectCloseRequest,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """
    إغلاق المشروع مع قيد محاسبي لربح/خسارة المشروع.
    يقارن إجمالي الإيرادات بإجمالي المصاريف ويسجل قيد إقفال.
    """
    db = get_db_connection(current_user.company_id)
    try:
        project = db.execute(text("SELECT * FROM projects WHERE id = :id"), {"id": project_id}).fetchone()
        if not project:
            raise HTTPException(**http_error(404, "project_not_found"))

        p = project._mapping
        if p["status"] == "completed":
            raise HTTPException(status_code=400, detail=i18n_message("project_already_closed"))

        total_expenses = _dec(db.execute(text(
            "SELECT COALESCE(SUM(amount), 0) FROM project_expenses WHERE project_id = :pid AND status != 'rejected'"
        ), {"pid": project_id}).scalar())

        total_revenues = _dec(db.execute(text(
            "SELECT COALESCE(SUM(amount), 0) FROM project_revenues WHERE project_id = :pid AND status != 'rejected'"
        ), {"pid": project_id}).scalar())

        net_profit_loss = total_revenues - total_expenses
        base_currency = get_base_currency(db)
        close_date = close_data.close_date or date.today()

        # Fiscal period check before GL entry
        check_fiscal_period_open(db, close_date)

        je_id = None
        if abs(net_profit_loss) > Decimal('0.01'):
            pl_acc = get_mapped_account_id(db, "acc_map_project_pl")
            if not pl_acc:
                pl_acc = db.execute(text(
                    "SELECT id FROM accounts WHERE account_number = '3300' OR account_number = '33' LIMIT 1"
                )).scalar()

            if pl_acc:
                lines = []
                cost_center_id = db.execute(text(
                    "SELECT id FROM cost_centers WHERE center_name ILIKE :name LIMIT 1"
                ), {"name": f"%{p['project_name']}%"}).scalar()

                if net_profit_loss > 0:
                    rev_acc = get_mapped_account_id(db, "acc_map_sales_rev")
                    if rev_acc:
                        lines.append({
                            "account_id": rev_acc, "debit": net_profit_loss, "credit": 0,
                            "description": f"إقفال إيرادات مشروع {p['project_name']}", "cost_center_id": cost_center_id
                        })
                        lines.append({
                            "account_id": pl_acc, "debit": 0, "credit": net_profit_loss,
                            "description": f"ربح مشروع {p['project_name']}", "cost_center_id": cost_center_id
                        })
                else:
                    loss_amount = abs(net_profit_loss)
                    exp_acc = db.execute(text(
                        "SELECT id FROM accounts WHERE account_number = '5200' OR account_number = '52' LIMIT 1"
                    )).scalar()
                    if exp_acc:
                        lines.append({
                            "account_id": pl_acc, "debit": loss_amount, "credit": 0,
                            "description": f"خسارة مشروع {p['project_name']}", "cost_center_id": cost_center_id
                        })
                        lines.append({
                            "account_id": exp_acc, "debit": 0, "credit": loss_amount,
                            "description": f"إقفال مصاريف مشروع {p['project_name']}", "cost_center_id": cost_center_id
                        })
                
                if lines:
                    je_id, entry_num = gl_create_journal_entry(
                        db=db,
                        company_id=current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id,
                        date=close_date,
                        description=f"إقفال مشروع: {p['project_name']} — صافي {'ربح' if net_profit_loss > 0 else 'خسارة'}: {abs(net_profit_loss):.2f}",
                        status="posted",
                        currency=base_currency,
                        exchange_rate=Decimal("1"),
                        lines=lines,
                        user_id=current_user.get("id") if isinstance(current_user, dict) else current_user.id,
                        source="project_closure",
                        source_id=project_id
                    )

        db.execute(text("""
            UPDATE projects
            SET status = 'completed', progress_percentage = 100,
                actual_cost = :cost, end_date = :date, updated_at = NOW()
            WHERE id = :id
        """), {"cost": total_expenses, "date": close_date, "id": project_id})

        db.commit()

        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="project.close", resource_type="project",
            resource_id=str(project_id),
            details={"net_profit_loss": float(net_profit_loss.quantize(_D2)),
                     "total_expenses": float(total_expenses.quantize(_D2)),
                     "total_revenues": float(total_revenues.quantize(_D2))},
            request=request
        )

        return {
            "success": True,
            "message": i18n_message("project_closed_success"),
            "summary": {
                "total_expenses": float(total_expenses.quantize(_D2)),
                "total_revenues": float(total_revenues.quantize(_D2)),
                "net_profit_loss": float(net_profit_loss.quantize(_D2)),
                "journal_entry_id": je_id,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error closing project: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# PRJ-107: Retainer Auto-Billing (فوترة دورية تلقائية)
# ═══════════════════════════════════════════════════════════

class RetainerSetup(BaseModel):
    retainer_amount: float
    billing_cycle: str = "monthly"  # monthly, quarterly, yearly
    next_billing_date: Optional[date] = None

@router.put("/{project_id}/retainer-setup", dependencies=[Depends(require_permission("projects.edit"))], response_model=Dict[str, Any])
async def setup_retainer(
    project_id: int,
    data: RetainerSetup,
    current_user: dict = Depends(get_current_user)
):
    """إعداد الفوترة الدورية لعقد Retainer"""
    db = get_db_connection(current_user.company_id)
    try:
        project = db.execute(text("SELECT * FROM projects WHERE id = :id"), {"id": project_id}).fetchone()
        if not project:
            raise HTTPException(**http_error(404, "project_not_found"))
        
        next_date = data.next_billing_date or date.today()
        db.execute(text("""
            UPDATE projects SET 
                contract_type = 'retainer',
                retainer_amount = :amt,
                billing_cycle = :cycle,
                next_billing_date = :next_date,
                updated_at = NOW()
            WHERE id = :id
        """), {
            "amt": data.retainer_amount, "cycle": data.billing_cycle,
            "next_date": next_date, "id": project_id
        })
        db.commit()
        return {"success": True, "message": i18n_message("recurring_billing_configured_success")}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error setting up retainer: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# Earned Value Management (EVM)
# ═══════════════════════════════════════════════════════════

@router.get("/{project_id}/evm", dependencies=[Depends(require_permission("projects.view"))], response_model=Dict[str, Any])
async def get_earned_value_metrics(project_id: int, current_user: dict = Depends(get_current_user)):
    """
    حساب مقاييس القيمة المكتسبة (EVM):
    PV (Planned Value), EV (Earned Value), AC (Actual Cost)
    SPI, CPI, EAC, ETC, VAC, TCPI
    """
    db = get_db_connection(current_user.company_id)
    try:
        project = db.execute(text("SELECT * FROM projects WHERE id = :id"), {"id": project_id}).fetchone()
        if not project:
            raise HTTPException(**http_error(404, "project_not_found"))

        p = project._mapping
        bac = _dec(p.get("planned_budget") or 0)
        progress = _dec(p.get("progress_percentage") or 0) / Decimal('100')

        start_dt = p.get("start_date")
        end_dt = p.get("end_date")
        today = date.today()

        schedule_progress = Decimal('0')
        if start_dt and end_dt and end_dt > start_dt:
            total_days = (end_dt - start_dt).days
            elapsed_days = min((today - start_dt).days, total_days)
            schedule_progress = (
                max(Decimal('0'), _dec(elapsed_days) / _dec(total_days)) if total_days > 0 else Decimal('0')
            )

        pv = bac * schedule_progress          # Planned Value
        ev = bac * progress                    # Earned Value
        ac = _dec(db.execute(text(
            "SELECT COALESCE(SUM(amount), 0) FROM project_expenses WHERE project_id = :pid AND status != 'rejected'"
        ), {"pid": project_id}).scalar())

        spi = ev / pv if pv > 0 else Decimal('0')
        cpi = ev / ac if ac > 0 else Decimal('0')
        sv = ev - pv
        cv = ev - ac
        eac = bac / cpi if cpi > 0 else bac * Decimal('2')
        etc = max(Decimal('0'), eac - ac)
        vac = bac - eac

        remaining_work = bac - ev
        remaining_budget = bac - ac
        tcpi = remaining_work / remaining_budget if remaining_budget > 0 else None

        return {
            "project_id": project_id,
            "project_name": p["project_name"],
            "metrics": {
                "BAC": float(bac.quantize(_D2)),
                "PV": float(pv.quantize(_D2)),
                "EV": float(ev.quantize(_D2)),
                "AC": float(ac.quantize(_D2)),
                "SV": float(sv.quantize(_D2)),
                "CV": float(cv.quantize(_D2)),
                "SPI": float(spi.quantize(_D4)),
                "CPI": float(cpi.quantize(_D4)),
                "EAC": float(eac.quantize(_D2)),
                "ETC": float(etc.quantize(_D2)),
                "VAC": float(vac.quantize(_D2)),
                "TCPI": float(tcpi.quantize(_D4)) if tcpi is not None else None,
            },
            "interpretation": {
                "schedule": "ahead" if spi > 1 else ("on_track" if spi == 1 else "behind"),
                "cost": "under_budget" if cpi > 1 else ("on_budget" if cpi == 1 else "over_budget"),
                "schedule_progress_pct": float((schedule_progress * Decimal('100')).quantize(_D2)),
                "completion_pct": float((progress * Decimal('100')).quantize(_D2)),
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error calculating EVM: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# Project Reports
# ═══════════════════════════════════════════════════════════
# PRJ-108: Schedule & Budget Alerts Dashboard
def _fetch_timesheet_entry(db, entry_id: int) -> dict:
    row = db.execute(text("""
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
        WHERE  te.id = :id
    """), {"id": entry_id}).fetchone()
    return dict(row._mapping) if row else None


def _fetch_allocation(db, alloc_id: int) -> dict:
    row = db.execute(text("""
        SELECT ra.*,
               e.full_name  AS employee_name,
               p.project_name
        FROM   resource_allocations ra
        LEFT JOIN employees e ON e.id = ra.employee_id
        LEFT JOIN projects  p ON p.id = ra.project_id
        WHERE  ra.id = :id
    """), {"id": alloc_id}).fetchone()
    return dict(row._mapping) if row else None


def _compute_total_allocation(db, employee_id: int, start_date, end_date, exclude_id=None):
    """Sum allocation_percent for overlapping date ranges."""
    params = {"eid": employee_id, "sd": start_date, "ed": end_date}
    exclude_clause = ""
    if exclude_id:
        exclude_clause = "AND ra.id != :exclude_id"
        params["exclude_id"] = exclude_id
    row = db.execute(text( # noqa: sql-lint
                f"""
        SELECT COALESCE(SUM(ra.allocation_percent), 0) AS total_pct
        FROM   resource_allocations ra
        WHERE  ra.employee_id = :eid
          AND  ra.start_date <= :ed
          AND  ra.end_date   >= :sd
          {exclude_clause}
    """), params).fetchone()
    return float(row.total_pct)
