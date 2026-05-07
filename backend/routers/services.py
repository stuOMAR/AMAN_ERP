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

TECHNICIAN_USER_FILTER = """
    u.is_active = true
    AND (
        u.role IN ('technician', 'service_technician', 'field_technician',
                   'maintenance', 'maintenance_technician', 'service_manager',
                   'admin', 'superuser', 'system_admin')
        OR u.permissions::text ILIKE '%services.edit%'
        OR u.permissions::text ILIKE '%services.*%'
        OR u.permissions::text ILIKE '%"*"%'
    )
"""


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
    """List Service Requests."""
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
    """Get Service Stats."""
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
    """Get Service Request."""
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


@router.get("/requests/{request_id}/state-history",
            dependencies=[Depends(require_permission("services.view"))],
            response_model=List[Dict[str, Any]])
def get_state_history(request_id: int,
                      current_user: UserResponse = Depends(get_current_user)):
    """T18 \u2014 timeline of status transitions for a service request."""
    with transactional(current_user.company_id) as db:
        try:
            rows = db.execute(text("""
                SELECT id, from_status, to_status, actor_user_id, actor_username,
                       comment, changed_at
                FROM service_request_state_history
                WHERE request_id = :id
                ORDER BY changed_at, id
            """), {"id": request_id}).fetchall()
            return [dict(r._mapping) for r in rows]
        except Exception:
            return []


@router.post("/requests", dependencies=[Depends(require_permission("services.create"))], response_model=Dict[str, Any])
def create_service_request(data: ServiceRequestCreate, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Create Service Request."""
    with transactional(current_user.company_id) as db:
        try:
            if data.branch_id:
                validate_branch_access(current_user, data.branch_id)
    
            req_id = db.execute(text("""
                INSERT INTO service_requests (
                    title, description, category, priority, status,
                    customer_id, asset_id, assigned_to, branch_id,
                    estimated_hours, hourly_rate, estimated_cost, scheduled_date,
                    location, notes, created_by
                ) VALUES (
                    :title, :description, :category, :priority, 'pending',
                    :customer_id, :asset_id, :assigned_to, :branch_id,
                    :estimated_hours, :hourly_rate, :estimated_cost, :scheduled_date,
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
                "hourly_rate": data.hourly_rate or None,
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
    """Update Service Request."""
    with transactional(current_user.company_id) as db:
        try:
            existing = db.execute(text("""
                SELECT id, status, branch_id, version,
                       COALESCE(actual_hours, 0) AS actual_hours,
                       COALESCE(actual_cost, 0) AS actual_cost
                FROM service_requests
                WHERE id = :id AND is_deleted = false
            """), {"id": request_id}).fetchone()
            if not existing:
                raise HTTPException(**http_error(404, "maintenance_request_not_found"))
    
            if existing.branch_id:
                validate_branch_access(current_user, existing.branch_id)
    
            # Validate status transition
            if data.status and data.status != existing.status:
                allowed = VALID_TRANSITIONS.get(existing.status, [])
                if data.status not in allowed:
                    raise HTTPException(**http_error(400, "invalid_status_transition"))
                if data.status == "completed":
                    proposed_hours = _dec(data.actual_hours) if data.actual_hours is not None else _dec(existing.actual_hours)
                    proposed_cost = _dec(data.actual_cost) if data.actual_cost is not None else _dec(existing.actual_cost)
                    if proposed_hours <= 0 and proposed_cost <= 0:
                        raise HTTPException(**http_error(400, "service_completion_requires_actuals"))
    
            fields = []
            params = {"id": request_id, "version": data.version}
            updatable = [
                "title", "description", "category", "priority", "status",
                "customer_id", "asset_id", "assigned_to",
                "estimated_hours", "actual_hours", "hourly_rate", "estimated_cost", "actual_cost",
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
            fields.append("version = version + 1")
            params["uid"] = current_user.id
    
            if fields:
                result = db.execute(
                    text(f"""
                        UPDATE service_requests
                        SET {', '.join(fields)}
                        WHERE id = :id AND version = :version
                    """),
                    params,
                )
                if result.rowcount == 0:
                    raise HTTPException(**http_error(409, "record_changed_reload"))
                db.commit()

            # T18 #77/#78/#79/#81 \u2014 FSM state history. Record every status
            # transition in service_request_state_history so we can answer
            # "who changed this and when?" without scraping audit_logs.
            if data.status and data.status != existing.status:
                try:
                    db.execute(text("""
                        INSERT INTO service_request_state_history
                            (request_id, from_status, to_status,
                             actor_user_id, actor_username, comment, changed_at)
                        VALUES (:rid, :fs, :ts, :uid, :uname, :cmt, NOW())
                    """), {
                        "rid": request_id,
                        "fs": existing.status,
                        "ts": data.status,
                        "uid": current_user.id,
                        "uname": getattr(current_user, "username", None),
                        "cmt": getattr(data, "notes", None),
                    })
                    db.commit()
                except Exception:
                    # Tenants without the history table (legacy) skip silently.
                    pass

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
    """Delete Service Request."""
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
            # T10.2 #170 — cascade soft-delete to attached documents so they
            # don't outlive the parent request and clutter DMS searches.
            # ``related_module='services'`` + ``related_id=request_id`` is
            # the convention established by the upload endpoint.
            db.execute(text(
                "UPDATE documents SET is_deleted = true, updated_at = NOW(), updated_by = :uid "
                "WHERE related_module = 'services' AND related_id = :id AND is_deleted = false"
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

            if data.assigned_to is not None:
                technician = db.execute(text(f"""
                    SELECT u.id FROM company_users u
                    WHERE u.id = :tech_id AND {TECHNICIAN_USER_FILTER}
                """), {"tech_id": data.assigned_to}).fetchone()
                if not technician:
                    raise HTTPException(status_code=400, detail="المستخدم المحدد لا يملك دور أو صلاحية فني خدمة")
    
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
    """Add a cost line to a service request.

    T10.1 P1 #76 — when ``cost_type == 'parts'`` and the caller supplies
    ``product_id`` + ``warehouse_id``, deduct the consumed quantity from
    inventory in the same transaction. Refuses to over-consume (negative
    on-hand) so the inventory book stays trustworthy.
    """
    with transactional(current_user.company_id) as db:
        try:
            existing = db.execute(text("SELECT id FROM service_requests WHERE id = :id AND is_deleted = false"), {"id": request_id}).fetchone()
            if not existing:
                raise HTTPException(**http_error(404, "maintenance_request_not_found"))
    
            qty = _dec(data.quantity if data.quantity is not None else 1)
            unit = _dec(data.unit_cost if data.unit_cost is not None else 0)
            markup_pct = _dec(data.markup_pct if data.markup_pct is not None else 0)
            if markup_pct < 0:
                raise HTTPException(status_code=400, detail="نسبة الهامش لا يمكن أن تكون سالبة")
            total = (qty * unit * (Decimal("1") + (markup_pct / Decimal("100")))).quantize(_D2, ROUND_HALF_UP)

            cost_type = (data.cost_type or "other").strip().lower()
            product_id = data.product_id
            warehouse_id = data.warehouse_id

            # P1 #76 — parts must deduct inventory. Allow product_id to be
            # omitted only for free-form 'parts' descriptions (legacy).
            if cost_type == "parts" and product_id is not None:
                if warehouse_id is None:
                    raise HTTPException(status_code=400, detail="warehouse_id مطلوب عند صرف قطع لخدمة")
                if qty <= 0:
                    raise HTTPException(status_code=400, detail="الكمية المصروفة يجب أن تكون أكبر من صفر")
                # Lock + check available stock before decrementing.
                row = db.execute(
                    text(
                        "SELECT quantity FROM inventory "
                        "WHERE product_id = :pid AND warehouse_id = :wid FOR UPDATE"
                    ),
                    {"pid": product_id, "wid": warehouse_id},
                ).fetchone()
                on_hand = _dec(row.quantity if row else 0)
                if on_hand < qty:
                    raise HTTPException(
                        status_code=400,
                        detail=f"المخزون غير كافٍ (المتوفر {on_hand}، المطلوب {qty})",
                    )
                db.execute(
                    text(
                        "UPDATE inventory SET quantity = quantity - :qty, updated_at = NOW() "
                        "WHERE product_id = :pid AND warehouse_id = :wid"
                    ),
                    {"qty": qty, "pid": product_id, "wid": warehouse_id},
                )
                db.execute(
                    text(
                        "INSERT INTO stock_movements (product_id, warehouse_id, movement_type, quantity, reference_type, reference_id, notes, created_by) "
                        "VALUES (:pid, :wid, 'service_consumption', :qty, 'service_request', :rid, :notes, :uid)"
                    ),
                    {
                        "pid": product_id,
                        "wid": warehouse_id,
                        "qty": qty,
                        "rid": request_id,
                        "notes": data.description or f"Service request #{request_id} parts consumption",
                        "uid": current_user.id,
                    },
                )

            db.execute(text("""
                INSERT INTO service_request_costs (service_request_id, cost_type, description, quantity, unit_cost, markup_pct, total_cost, product_id, warehouse_id)
                VALUES (:rid, :ctype, :desc, :qty, :ucost, :markup_pct, :total, :pid, :wid)
            """), {
                "rid": request_id,
                "ctype": cost_type,
                "desc": data.description or "",
                "qty": qty, "ucost": unit, "markup_pct": markup_pct, "total": total,
                "pid": product_id, "wid": warehouse_id,
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
    """Delete Service Cost."""
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
    """List Documents."""
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
        items = [dict(r._mapping) for r in rows]
        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": math.ceil(total / per_page) if total else 0
        }


@router.get("/documents/{doc_id}", dependencies=[Depends(require_permission("services.view"))], response_model=Dict[str, Any])
def get_document(doc_id: int, current_user: UserResponse = Depends(get_current_user)):
    """Get Document."""
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
    """Upload Document."""
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
def download_document(doc_id: int, request: Request, current_user: UserResponse = Depends(get_current_user)):
    """Download the latest version of a document.

    P1 #55 fix: validate that the resolved file path is rooted inside
    ``UPLOAD_DIR`` (path-traversal guard) and enforce ``access_level``
    (``admin_only`` requires ``services.admin`` / role ``admin``).
    The download is recorded in the audit trail (DMS #168).
    """
    from utils.sql_safety import validate_file_path_safety
    from utils.permissions import check_permission

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

        # P1 #55a — path traversal guard: refuse anything outside UPLOAD_DIR.
        if not validate_file_path_safety(doc.file_path, UPLOAD_DIR):
            logger.warning(
                "DMS path-traversal attempt: doc_id=%s path=%s user=%s",
                doc_id, doc.file_path, getattr(current_user, "id", None),
            )
            raise HTTPException(**http_error(403, "forbidden"))

        # P1 #55b — access_level enforcement.
        access_level = (doc.access_level or "").lower()
        if access_level == "admin_only":
            role = getattr(current_user, "role", None)
            if role not in ("admin", "system_admin") and not check_permission(current_user, "services.admin"):
                raise HTTPException(**http_error(403, "forbidden"))

        # P2 #168 — audit log on download (who/when).
        try:
            log_activity(
                db, user_id=current_user.id, username=current_user.username,
                action="document.download", resource_type="document",
                resource_id=doc_id,
                details={"file_name": doc.file_name, "access_level": access_level or "public"},
                request=request, branch_id=None,
            )
        except Exception:
            logger.exception("audit log_activity failed for document.download")

        return FileResponse(
            path=doc.file_path,
            filename=doc.file_name,
            media_type=doc.mime_type or "application/octet-stream"
        )


@router.delete("/documents/{doc_id}", dependencies=[Depends(require_permission("services.delete"))], response_model=Dict[str, Any])
def delete_document(doc_id: int, current_user: UserResponse = Depends(get_current_user)):
    """Delete Document."""
    with transactional(current_user.company_id) as db:
        try:
            doc = db.execute(text("SELECT id, file_path FROM documents WHERE id = :id AND is_deleted = false"), {"id": doc_id}).fetchone()
            if not doc:
                raise HTTPException(**http_error(404, "document_not_found"))
    
            db.execute(text(
                "UPDATE documents SET is_deleted = true, updated_at = NOW(), updated_by = :uid WHERE id = :id"
            ), {"id": doc_id, "uid": current_user.id})
            # T10.2 #170 — cascade soft-delete to document_versions. The
            # versions table has no is_deleted column, so we delete the
            # version rows outright (the actual files on disk are
            # cleaned up by the daily ``purge_soft_deleted_documents``
            # scheduler job).
            db.execute(text(
                "DELETE FROM document_versions WHERE document_id = :id"
            ), {"id": doc_id})
    
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
        users = db.execute(text(f"""
            SELECT u.id, u.full_name, u.email, u.role
            FROM company_users u
            WHERE {TECHNICIAN_USER_FILTER}
            ORDER BY u.full_name
        """)).fetchall()
        return [dict(u._mapping) for u in users]
