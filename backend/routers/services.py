"""
Service Management Router — SVC-001 + SVC-002
- Service / Maintenance Requests (CRUD + assign + costs + stats)
- Document Management (upload + versions + search)
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, Request
from fastapi.responses import FileResponse
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from decimal import Decimal, ROUND_HALF_UP
import logging
import math
import os
import uuid

from database import get_db_connection
from routers.auth import get_current_user, UserResponse
from utils.tx import transactional
from utils.permissions import require_permission, require_module, validate_branch_access
from utils.audit import log_activity
from schemas.services import (
    ServiceRequestCreate, ServiceRequestUpdate, TechnicianAssignRequest,
    ServiceCostCreate, DocumentMetaUpdate
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/services", tags=["Services"], dependencies=[Depends(require_module("services"))])

_D2 = Decimal('0.01')
def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "uploads", "documents")
try:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
except PermissionError as e:
    logger.warning(f"⚠️  Cannot create upload dir {UPLOAD_DIR}: {e} — continuing without it")

# Status transition state machine
VALID_TRANSITIONS = {
    "pending": ["assigned", "cancelled"],
    "assigned": ["in_progress", "cancelled"],
    "in_progress": ["on_hold", "completed", "cancelled"],
    "on_hold": ["in_progress", "cancelled"],
}


# ─────────────────────────────────────────────
# SVC-001: Service / Maintenance Requests
# ─────────────────────────────────────────────

@router.get("/requests", dependencies=[Depends(require_permission("services.view"))], response_model=Dict[str, Any])
def list_service_requests(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    assigned_to: Optional[int] = None,
    customer_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    current_user: UserResponse = Depends(get_current_user)
):
    with transactional(current_user.company_id) as db:
        base_where = " WHERE sr.is_deleted = false"
        params = {}
        if status:
            base_where += " AND sr.status = :status"
            params["status"] = status
        if priority:
            base_where += " AND sr.priority = :priority"
            params["priority"] = priority
        if assigned_to:
            base_where += " AND sr.assigned_to = :assigned_to"
            params["assigned_to"] = assigned_to
        if customer_id:
            base_where += " AND sr.customer_id = :customer_id"
            params["customer_id"] = customer_id

        # Count total
        total = db.execute(text(f"SELECT COUNT(*) FROM service_requests sr{base_where}"), params).scalar()

        # Paginated query
        offset = (page - 1) * per_page
        query = f"""
            SELECT sr.*,
                   p.name as customer_name,
                   u.full_name as assigned_to_name,
                   cu.full_name as created_by_name
            FROM service_requests sr
            LEFT JOIN parties p ON sr.customer_id = p.id
            LEFT JOIN company_users u ON sr.assigned_to = u.id
            LEFT JOIN company_users cu ON sr.created_by = cu.id
            {base_where}
            ORDER BY sr.created_at DESC
            LIMIT :limit OFFSET :offset
        """
        params["limit"] = per_page
        params["offset"] = offset
        rows = db.execute(text(query), params).fetchall()
        return {
            "items": [dict(r._mapping) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": math.ceil(total / per_page) if total else 0
        }


@router.get("/requests/stats", dependencies=[Depends(require_permission("services.view"))], response_model=Dict[str, Any])
def get_service_stats(current_user: UserResponse = Depends(get_current_user)):
    with transactional(current_user.company_id) as db:
        stats = db.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'pending') as pending,
                COUNT(*) FILTER (WHERE status = 'assigned') as assigned,
                COUNT(*) FILTER (WHERE status = 'in_progress') as in_progress,
                COUNT(*) FILTER (WHERE status = 'on_hold') as on_hold,
                COUNT(*) FILTER (WHERE status = 'completed') as completed,
                COUNT(*) FILTER (WHERE status = 'cancelled') as cancelled,
                COUNT(*) FILTER (WHERE priority = 'critical' AND status NOT IN ('completed','cancelled')) as critical_open,
                COALESCE(AVG(actual_hours) FILTER (WHERE status = 'completed'), 0) as avg_hours,
                COALESCE(SUM(actual_cost) FILTER (WHERE status = 'completed'), 0) as total_cost
            FROM service_requests
            WHERE is_deleted = false
        """)).fetchone()
        return dict(stats._mapping) if stats else {}


@router.get("/requests/{request_id}", dependencies=[Depends(require_permission("services.view"))], response_model=Dict[str, Any])
def get_service_request(request_id: int, current_user: UserResponse = Depends(get_current_user)):
    with transactional(current_user.company_id) as db:
        req = db.execute(text("""
            SELECT sr.*,
                   p.name as customer_name,
                   u.full_name as assigned_to_name,
                   cu.full_name as created_by_name
            FROM service_requests sr
            LEFT JOIN parties p ON sr.customer_id = p.id
            LEFT JOIN company_users u ON sr.assigned_to = u.id
            LEFT JOIN company_users cu ON sr.created_by = cu.id
            WHERE sr.id = :id AND sr.is_deleted = false
        """), {"id": request_id}).fetchone()
        if not req:
            raise HTTPException(**http_error(404, "maintenance_request_not_found"))
        result = dict(req._mapping)
        # Fetch costs
        costs = db.execute(text(
            "SELECT * FROM service_request_costs WHERE service_request_id = :id AND is_deleted = false ORDER BY created_at"
        ), {"id": request_id}).fetchall()
        result["costs"] = [dict(c._mapping) for c in costs]
        return result


@router.post("/requests", dependencies=[Depends(require_permission("services.create"))], response_model=Dict[str, Any])
def create_service_request(data: ServiceRequestCreate, request: Request, current_user: UserResponse = Depends(get_current_user)):
    with transactional(current_user.company_id) as db:
        try:
            if data.branch_id:
                validate_branch_access(current_user, data.branch_id)
    
            req_id = db.execute(text("""
                INSERT INTO service_requests (
                    title, description, category, priority, status,
                    customer_id, asset_id, assigned_to, branch_id,
                    estimated_hours, estimated_cost, scheduled_date,
                    location, notes, created_by
                ) VALUES (
                    :title, :description, :category, :priority, 'pending',
                    :customer_id, :asset_id, :assigned_to, :branch_id,
                    :estimated_hours, :estimated_cost, :scheduled_date,
                    :location, :notes, :uid
                ) RETURNING id
            """), {
                "title": data.title or "",
                "description": data.description,
                "category": data.category or "maintenance",
                "priority": data.priority or "medium",
                "customer_id": data.customer_id or None,
                "asset_id": data.asset_id or None,
                "assigned_to": data.assigned_to or None,
                "branch_id": data.branch_id or None,
                "estimated_hours": data.estimated_hours or None,
                "estimated_cost": data.estimated_cost or 0,
                "scheduled_date": data.scheduled_date or None,
                "location": data.location,
                "notes": data.notes,
                "uid": current_user.id
            }).scalar()
    
            # If technician assigned immediately, update status
            if data.assigned_to:
                db.execute(text("""
                    UPDATE service_requests SET status = 'assigned', assigned_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                """), {"id": req_id})
    
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="service_request.create", resource_type="service_request",
                         resource_id=req_id, details={"title": data.title},
                         request=request, branch_id=data.branch_id)
    
            return get_service_request(req_id, current_user)
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.put("/requests/{request_id}", dependencies=[Depends(require_permission("services.edit"))], response_model=Dict[str, Any])
def update_service_request(request_id: int, data: ServiceRequestUpdate, request: Request, current_user: UserResponse = Depends(get_current_user)):
    with transactional(current_user.company_id) as db:
        try:
            existing = db.execute(text("SELECT id, status, branch_id FROM service_requests WHERE id = :id AND is_deleted = false"), {"id": request_id}).fetchone()
            if not existing:
                raise HTTPException(**http_error(404, "maintenance_request_not_found"))
    
            if existing.branch_id:
                validate_branch_access(current_user, existing.branch_id)
    
            # Validate status transition
            if data.status and data.status != existing.status:
                allowed = VALID_TRANSITIONS.get(existing.status, [])
                if data.status not in allowed:
                    raise HTTPException(**http_error(400, "invalid_status_transition"))
    
            fields = []
            params = {"id": request_id}
            updatable = [
                "title", "description", "category", "priority", "status",
                "customer_id", "asset_id", "assigned_to",
                "estimated_hours", "actual_hours", "estimated_cost", "actual_cost",
                "scheduled_date", "completion_date", "location", "notes"
            ]
            for f in updatable:
                val = getattr(data, f, None)
                if val is not None:
                    fields.append(f"{f} = :{f}")
                    params[f] = val if val != "" else None
    
            # Auto-set assigned_at
            if data.assigned_to:
                fields.append("assigned_at = CURRENT_TIMESTAMP")
            # Auto-set completion_date
            if data.status == "completed" and not data.completion_date:
                fields.append("completion_date = CURRENT_DATE")
    
            fields.append("updated_at = CURRENT_TIMESTAMP")
            fields.append("updated_by = :uid")
            params["uid"] = current_user.id
    
            if fields:
                db.execute(text(f"UPDATE service_requests SET {', '.join(fields)} WHERE id = :id"), params)
                db.commit()
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="service_request.update", resource_type="service_request",
                         resource_id=request_id, details={"status": data.status},
                         request=request, branch_id=existing.branch_id)
    
            return get_service_request(request_id, current_user)
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.delete("/requests/{request_id}", dependencies=[Depends(require_permission("services.delete"))], response_model=Dict[str, Any])
def delete_service_request(request_id: int, request: Request, current_user: UserResponse = Depends(get_current_user)):
    with transactional(current_user.company_id) as db:
        try:
            existing = db.execute(text("SELECT id, branch_id FROM service_requests WHERE id = :id AND is_deleted = false"), {"id": request_id}).fetchone()
            if not existing:
                raise HTTPException(**http_error(404, "maintenance_request_not_found"))
    
            if existing.branch_id:
                validate_branch_access(current_user, existing.branch_id)
    
            db.execute(text(
                "UPDATE service_requests SET is_deleted = true, updated_at = NOW(), updated_by = :uid WHERE id = :id"
            ), {"id": request_id, "uid": current_user.id})
            # Soft-delete associated costs
            db.execute(text(
                "UPDATE service_request_costs SET is_deleted = true, updated_at = NOW(), updated_by = :uid WHERE service_request_id = :id"
            ), {"id": request_id, "uid": current_user.id})
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="service_request.delete", resource_type="service_request",
                         resource_id=request_id, details={},
                         request=request, branch_id=existing.branch_id)
    
            return {"message": "تم حذف طلب الصيانة بنجاح"}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/requests/{request_id}/assign", dependencies=[Depends(require_permission("services.edit"))], response_model=Dict[str, Any])
def assign_technician(request_id: int, data: TechnicianAssignRequest, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Assign or reassign a technician to a service request."""
    with transactional(current_user.company_id) as db:
        try:
            existing = db.execute(text("SELECT id, branch_id FROM service_requests WHERE id = :id AND is_deleted = false"), {"id": request_id}).fetchone()
            if not existing:
                raise HTTPException(**http_error(404, "maintenance_request_not_found"))
    
            if existing.branch_id:
                validate_branch_access(current_user, existing.branch_id)
    
            db.execute(text("""
                UPDATE service_requests
                SET assigned_to = :tech_id, assigned_at = CURRENT_TIMESTAMP,
                    status = CASE WHEN status = 'pending' THEN 'assigned' ELSE status END,
                    updated_at = CURRENT_TIMESTAMP, updated_by = :uid
                WHERE id = :id
            """), {"id": request_id, "tech_id": data.assigned_to, "uid": current_user.id})
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="service_request.assign", resource_type="service_request",
                         resource_id=request_id, details={"assigned_to": data.assigned_to},
                         request=request, branch_id=existing.branch_id)
    
            return get_service_request(request_id, current_user)
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/requests/{request_id}/costs", dependencies=[Depends(require_permission("services.edit"))], response_model=Dict[str, Any])
def add_service_cost(request_id: int, data: ServiceCostCreate, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Add a cost line to a service request."""
    with transactional(current_user.company_id) as db:
        try:
            existing = db.execute(text("SELECT id FROM service_requests WHERE id = :id AND is_deleted = false"), {"id": request_id}).fetchone()
            if not existing:
                raise HTTPException(**http_error(404, "maintenance_request_not_found"))
    
            qty = _dec(data.quantity if data.quantity is not None else 1)
            unit = _dec(data.unit_cost if data.unit_cost is not None else 0)
            total = (qty * unit).quantize(_D2, ROUND_HALF_UP)
    
            db.execute(text("""
                INSERT INTO service_request_costs (service_request_id, cost_type, description, quantity, unit_cost, total_cost)
                VALUES (:rid, :ctype, :desc, :qty, :ucost, :total)
            """), {
                "rid": request_id,
                "ctype": data.cost_type or "other",
                "desc": data.description or "",
                "qty": qty, "ucost": unit, "total": total
            })
    
            # Update total actual cost on the request
            db.execute(text("""
                UPDATE service_requests
                SET actual_cost = COALESCE((SELECT SUM(total_cost) FROM service_request_costs WHERE service_request_id = :id AND is_deleted = false), 0),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """), {"id": request_id})
    
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="service_request.add_cost", resource_type="service_request",
                         resource_id=request_id, details={"cost_type": data.cost_type, "total": str(total)},
                         request=request, branch_id=None)
    
            return get_service_request(request_id, current_user)
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.delete("/requests/{request_id}/costs/{cost_id}", dependencies=[Depends(require_permission("services.edit"))], response_model=Dict[str, Any])
def delete_service_cost(request_id: int, cost_id: int, request: Request, current_user: UserResponse = Depends(get_current_user)):
    with transactional(current_user.company_id) as db:
        try:
            db.execute(text(
                "UPDATE service_request_costs SET is_deleted = true, updated_at = NOW(), updated_by = :uid WHERE id = :cid AND service_request_id = :rid"
            ), {"cid": cost_id, "rid": request_id, "uid": current_user.id})
            # Recalculate
            db.execute(text("""
                UPDATE service_requests
                SET actual_cost = COALESCE((SELECT SUM(total_cost) FROM service_request_costs WHERE service_request_id = :id AND is_deleted = false), 0),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """), {"id": request_id})
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="service_request.delete_cost", resource_type="service_request",
                         resource_id=request_id, details={"cost_id": cost_id},
                         request=request, branch_id=None)
    
            return {"message": "تم حذف التكلفة بنجاح"}
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ─────────────────────────────────────────────
# SVC-002: Document Management
# ─────────────────────────────────────────────

@router.get("/documents", dependencies=[Depends(require_permission("services.view"))], response_model=Dict[str, Any])
def list_documents(
    category: Optional[str] = None,
    search: Optional[str] = None,
    related_module: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    current_user: UserResponse = Depends(get_current_user)
):
    with transactional(current_user.company_id) as db:
        base_where = " WHERE d.is_deleted = false"
        params = {}
        if category:
            base_where += " AND d.category = :category"
            params["category"] = category
        if related_module:
            base_where += " AND d.related_module = :related_module"
            params["related_module"] = related_module
        if search:
            base_where += " AND (d.title ILIKE :search OR d.description ILIKE :search OR d.tags::text ILIKE :search)"
            params["search"] = f"%{search}%"

        # Count total
        total = db.execute(text(f"SELECT COUNT(*) FROM documents d{base_where}"), params).scalar()

        # Paginated query (exclude file_path from response)
        offset = (page - 1) * per_page
        query = f"""
            SELECT d.id, d.title, d.description, d.category, d.file_name,
                   d.file_size, d.mime_type, d.tags, d.access_level, d.related_module,
                   d.related_id, d.current_version, d.created_by, d.created_at,
                   d.updated_at, u.full_name as created_by_name
            FROM documents d
            LEFT JOIN company_users u ON d.created_by = u.id
            {base_where}
            ORDER BY d.created_at DESC
            LIMIT :limit OFFSET :offset
        """
        params["limit"] = per_page
        params["offset"] = offset
        rows = db.execute(text(query), params).fetchall()
        items = []
        for r in rows:
            row_dict = dict(r._mapping)
            row_dict["download_url"] = f"/services/documents/{row_dict['id']}/download"
            items.append(row_dict)
        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": math.ceil(total / per_page) if total else 0
        }


@router.get("/documents/{doc_id}", dependencies=[Depends(require_permission("services.view"))], response_model=Dict[str, Any])
def get_document(doc_id: int, current_user: UserResponse = Depends(get_current_user)):
    with transactional(current_user.company_id) as db:
        doc = db.execute(text("""
            SELECT d.id, d.title, d.description, d.category, d.file_name,
                   d.file_size, d.mime_type, d.tags, d.access_level, d.related_module,
                   d.related_id, d.current_version, d.created_by, d.created_at,
                   d.updated_at, u.full_name as created_by_name
            FROM documents d
            LEFT JOIN company_users u ON d.created_by = u.id
            WHERE d.id = :id AND d.is_deleted = false
        """), {"id": doc_id}).fetchone()
        if not doc:
            raise HTTPException(**http_error(404, "document_not_found"))
        result = dict(doc._mapping)
        result["download_url"] = f"/services/documents/{doc_id}/download"
        # Fetch versions (exclude file_path)
        versions = db.execute(text("""
            SELECT dv.id, dv.document_id, dv.version_number, dv.file_name, dv.file_size,
                   dv.change_notes, dv.uploaded_by, dv.created_at as uploaded_at,
                   u.full_name as uploaded_by_name
            FROM document_versions dv
            LEFT JOIN company_users u ON dv.uploaded_by = u.id
            WHERE dv.document_id = :id ORDER BY dv.version_number DESC
        """), {"id": doc_id}).fetchall()
        result["versions"] = [dict(v._mapping) for v in versions]
        return result


@router.post("/documents", dependencies=[Depends(require_permission("services.create"))], response_model=Dict[str, Any])
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(""),
    description: str = Form(""),
    category: str = Form("general"),
    tags: str = Form(""),
    access_level: str = Form("company"),
    related_module: str = Form(""),
    related_id: int = Form(0),
    current_user: UserResponse = Depends(get_current_user)
):
    with transactional(current_user.company_id) as db:
        try:
            # SEC-FIX-016/017: Validate file size and type
            from utils.sql_safety import (
                validate_file_size, validate_file_extension,
                validate_file_mime_and_signature,
                MAX_DOCUMENT_SIZE, ALLOWED_DOCUMENT_EXTENSIONS
            )
            validate_file_extension(file.filename, ALLOWED_DOCUMENT_EXTENSIONS, "المستند")
            
            # Save file
            ext = os.path.splitext(file.filename)[1] if file.filename else ""
            unique_name = f"{uuid.uuid4().hex}{ext}"
            company_dir = os.path.join(UPLOAD_DIR, current_user.company_id)
            os.makedirs(company_dir, exist_ok=True)
            file_path = os.path.join(company_dir, unique_name)
    
            content = await file.read()
            validate_file_size(content, MAX_DOCUMENT_SIZE, "المستند")
            validate_file_mime_and_signature(file.filename, file.content_type, content, "المستند")
            
            with open(file_path, "wb") as f:
                f.write(content)
            file_size = len(content)
    
            used_title = title if title else file.filename
    
            doc_id = db.execute(text("""
                INSERT INTO documents (title, description, category, file_name, file_path, file_size,
                                       mime_type, tags, access_level, related_module, related_id, created_by)
                VALUES (:title, :desc, :cat, :fname, :fpath, :fsize,
                        :mime, :tags, :access, :rmod, :rid, :uid)
                RETURNING id
            """), {
                "title": used_title,
                "desc": description,
                "cat": category,
                "fname": file.filename,
                "fpath": file_path,
                "fsize": file_size,
                "mime": file.content_type,
                "tags": tags,
                "access": access_level,
                "rmod": related_module or None,
                "rid": related_id if related_id else None,
                "uid": current_user.id
            }).scalar()
    
            # First version
            db.execute(text("""
                INSERT INTO document_versions (document_id, version_number, file_name, file_path, file_size, change_notes, uploaded_by)
                VALUES (:did, 1, :fname, :fpath, :fsize, 'الإصدار الأول', :uid)
            """), {
                "did": doc_id, "fname": file.filename,
                "fpath": file_path, "fsize": file_size, "uid": current_user.id
            })
    
            return get_document(doc_id, current_user)
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.put("/documents/{doc_id}", dependencies=[Depends(require_permission("services.edit"))], response_model=Dict[str, Any])
def update_document_meta(doc_id: int, data: DocumentMetaUpdate, current_user: UserResponse = Depends(get_current_user)):
    """Update document metadata (title, description, category, tags, access_level)."""
    with transactional(current_user.company_id) as db:
        try:
            existing = db.execute(text("SELECT id FROM documents WHERE id = :id AND is_deleted = false"), {"id": doc_id}).fetchone()
            if not existing:
                raise HTTPException(**http_error(404, "document_not_found"))
    
            fields = []
            params = {"id": doc_id}
            for f in ["title", "description", "category", "tags", "access_level"]:
                val = getattr(data, f, None)
                if val is not None:
                    fields.append(f"{f} = :{f}")
                    params[f] = val
            fields.append("updated_at = CURRENT_TIMESTAMP")
            db.execute(text(f"UPDATE documents SET {', '.join(fields)} WHERE id = :id"), params)
            return get_document(doc_id, current_user)
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/documents/{doc_id}/versions", dependencies=[Depends(require_permission("services.edit"))], response_model=Dict[str, Any])
async def upload_new_version(
    doc_id: int,
    file: UploadFile = File(...),
    change_notes: str = Form(""),
    current_user: UserResponse = Depends(get_current_user)
):
    """Upload a new version of an existing document."""
    with transactional(current_user.company_id) as db:
        try:
            doc = db.execute(text("SELECT id, current_version FROM documents WHERE id = :id AND is_deleted = false"), {"id": doc_id}).fetchone()
            if not doc:
                raise HTTPException(**http_error(404, "document_not_found"))
    
            new_version = doc.current_version + 1
    
            ext = os.path.splitext(file.filename)[1] if file.filename else ""
            unique_name = f"{uuid.uuid4().hex}{ext}"
            company_dir = os.path.join(UPLOAD_DIR, current_user.company_id)
            os.makedirs(company_dir, exist_ok=True)
            file_path = os.path.join(company_dir, unique_name)
    
            from utils.sql_safety import (
                validate_file_size,
                validate_file_extension,
                validate_file_mime_and_signature,
                MAX_DOCUMENT_SIZE,
                ALLOWED_DOCUMENT_EXTENSIONS,
            )
            content = await file.read()
            validate_file_extension(file.filename, ALLOWED_DOCUMENT_EXTENSIONS, "المستند")
            validate_file_size(content, MAX_DOCUMENT_SIZE, "المستند")
            validate_file_mime_and_signature(file.filename, file.content_type, content, "المستند")
    
            with open(file_path, "wb") as f:
                f.write(content)
            file_size = len(content)
    
            db.execute(text("""
                INSERT INTO document_versions (document_id, version_number, file_name, file_path, file_size, change_notes, uploaded_by)
                VALUES (:did, :ver, :fname, :fpath, :fsize, :notes, :uid)
            """), {
                "did": doc_id, "ver": new_version,
                "fname": file.filename, "fpath": file_path,
                "fsize": file_size, "notes": change_notes or f"الإصدار {new_version}",
                "uid": current_user.id
            })
    
            db.execute(text("""
                UPDATE documents SET current_version = :ver, file_name = :fname, file_path = :fpath,
                                     file_size = :fsize, mime_type = :mime, updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """), {
                "ver": new_version, "fname": file.filename,
                "fpath": file_path, "fsize": file_size,
                "mime": file.content_type, "id": doc_id
            })
    
            return get_document(doc_id, current_user)
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.get("/documents/{doc_id}/download", dependencies=[Depends(require_permission("services.view"))])
def download_document(doc_id: int, current_user: UserResponse = Depends(get_current_user)):
    """Download the latest version of a document."""
    with transactional(current_user.company_id) as db:
        doc = db.execute(text("""
            SELECT d.id, d.file_path, d.file_name, d.mime_type, d.access_level
            FROM documents d
            WHERE d.id = :id AND d.is_deleted = false
        """), {"id": doc_id}).fetchone()
        if not doc:
            raise HTTPException(**http_error(404, "document_not_found"))

        if not doc.file_path or not os.path.isfile(doc.file_path):
            raise HTTPException(**http_error(404, "file_not_found"))

        return FileResponse(
            path=doc.file_path,
            filename=doc.file_name,
            media_type=doc.mime_type or "application/octet-stream"
        )


@router.delete("/documents/{doc_id}", dependencies=[Depends(require_permission("services.delete"))], response_model=Dict[str, Any])
def delete_document(doc_id: int, current_user: UserResponse = Depends(get_current_user)):
    with transactional(current_user.company_id) as db:
        try:
            doc = db.execute(text("SELECT id, file_path FROM documents WHERE id = :id AND is_deleted = false"), {"id": doc_id}).fetchone()
            if not doc:
                raise HTTPException(**http_error(404, "document_not_found"))
    
            db.execute(text(
                "UPDATE documents SET is_deleted = true, updated_at = NOW(), updated_by = :uid WHERE id = :id"
            ), {"id": doc_id, "uid": current_user.id})
    
            return {"message": "تم حذف المستند بنجاح"}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.get("/technicians", dependencies=[Depends(require_permission("services.view"))], response_model=List[Dict[str, Any]])
def list_technicians(current_user: UserResponse = Depends(get_current_user)):
    """List users who can be assigned to service requests."""
    with transactional(current_user.company_id) as db:
        users = db.execute(text("""
            SELECT id, full_name, email FROM company_users WHERE is_active = true ORDER BY full_name
        """)).fetchall()
        return [dict(u._mapping) for u in users]
