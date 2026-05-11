"""
Inventory Module - Batch & Serial Number Management
INV-101: Batch Numbers
INV-102: Serial Numbers  
INV-103: Expiry Date tracking
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pydantic import BaseModel, Field
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.audit import log_activity
from utils.permissions import require_permission

batches_router = APIRouter()
logger = logging.getLogger(__name__)


# ============ SCHEMAS ============

class BatchCreate(BaseModel):
    product_id: int
    warehouse_id: int
    batch_number: str
    manufacturing_date: Optional[str] = None
    expiry_date: Optional[str] = None
    quantity: float = Field(default=0, ge=0)
    unit_cost: float = 0
    supplier_id: Optional[int] = None
    notes: Optional[str] = None


class BatchUpdate(BaseModel):
    manufacturing_date: Optional[str] = None
    expiry_date: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None


class SerialCreate(BaseModel):
    product_id: int
    warehouse_id: int
    serial_number: str
    batch_id: Optional[int] = None
    purchase_price: float = 0
    warranty_start: Optional[str] = None
    warranty_end: Optional[str] = None
    notes: Optional[str] = None


class SerialBulkCreate(BaseModel):
    product_id: int
    warehouse_id: int
    batch_id: Optional[int] = None
    prefix: str = ""
    start_number: int = 1
    count: int = 1
    purchase_price: float = 0
    notes: Optional[str] = None


class SerialUpdate(BaseModel):
    status: Optional[str] = None
    warranty_start: Optional[str] = None
    warranty_end: Optional[str] = None
    notes: Optional[str] = None


# ============ BATCH ENDPOINTS ============

@batches_router.get("/batches", dependencies=[Depends(require_permission("stock.view"))], response_model=Dict[str, Any])
def list_batches(
    product_id: Optional[int] = None,
    warehouse_id: Optional[int] = None,
    status: Optional[str] = None,
    expiring_within_days: Optional[int] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(get_current_user)
):
    """قائمة الدفعات مع إمكانية الفلترة"""
    with transactional(current_user.company_id) as db:
        query = """
            SELECT b.*, 
                   p.product_name, p.product_code,
                   w.warehouse_name,
                   s.name as supplier_name
            FROM product_batches b
            JOIN products p ON b.product_id = p.id
            JOIN warehouses w ON b.warehouse_id = w.id
            LEFT JOIN parties s ON b.supplier_id = s.id
            WHERE 1=1
        """
        params = {"limit": limit, "skip": skip}

        if product_id:
            query += " AND b.product_id = :pid"
            params["pid"] = product_id
        if warehouse_id:
            query += " AND b.warehouse_id = :wid"
            params["wid"] = warehouse_id
        if status:
            query += " AND b.status = :status"
            params["status"] = status
        if expiring_within_days:
            query += " AND b.expiry_date IS NOT NULL AND b.expiry_date <= CURRENT_DATE + :days * INTERVAL '1 day' AND b.expiry_date >= CURRENT_DATE"
            params["days"] = expiring_within_days
        if search:
            query += " AND (b.batch_number ILIKE :search OR p.product_name ILIKE :search)"
            params["search"] = f"%{search}%"

        query += " ORDER BY b.created_at DESC LIMIT :limit OFFSET :skip"

        rows = db.execute(text(query), params).fetchall()
        
        # Count
        count_query = """
            SELECT COUNT(*) FROM product_batches b
            JOIN products p ON b.product_id = p.id
            WHERE 1=1
        """
        count_params = {}
        if product_id:
            count_query += " AND b.product_id = :pid"
            count_params["pid"] = product_id
        if warehouse_id:
            count_query += " AND b.warehouse_id = :wid"
            count_params["wid"] = warehouse_id
        if status:
            count_query += " AND b.status = :status"
            count_params["status"] = status

        total = db.execute(text(count_query), count_params).scalar() or 0

        return {
            "items": [dict(r._mapping) for r in rows],
            "total": total
        }


@batches_router.get("/batches/expiry-alerts", dependencies=[Depends(require_permission("stock.view"))], response_model=Dict[str, Any])
def get_expiry_alerts(
    days: int = Query(default=30, description="عدد الأيام للتنبيه"),
    warehouse_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تنبيهات المنتجات قريبة الانتهاء والمنتهية"""
    with transactional(current_user.company_id) as db:
        query = """
            SELECT b.*, 
                   p.product_name, p.product_code,
                   w.warehouse_name,
                   CASE 
                       WHEN b.expiry_date < CURRENT_DATE THEN 'expired'
                       WHEN b.expiry_date <= CURRENT_DATE + :days * INTERVAL '1 day' THEN 'expiring_soon'
                       ELSE 'ok'
                   END as alert_status,
                   b.expiry_date - CURRENT_DATE as days_remaining
            FROM product_batches b
            JOIN products p ON b.product_id = p.id
            JOIN warehouses w ON b.warehouse_id = w.id
            WHERE b.expiry_date IS NOT NULL 
              AND b.status = 'active'
              AND b.quantity > 0
              AND b.expiry_date <= CURRENT_DATE + :days * INTERVAL '1 day'
        """
        params = {"days": days}

        if warehouse_id:
            query += " AND b.warehouse_id = :wid"
            params["wid"] = warehouse_id

        query += " ORDER BY b.expiry_date ASC"

        rows = db.execute(text(query), params).fetchall()

        expired = []
        expiring_soon = []
        for r in rows:
            item = dict(r._mapping)
            if item.get("days_remaining") is not None:
                item["days_remaining"] = int(item["days_remaining"].days) if hasattr(item["days_remaining"], 'days') else int(item["days_remaining"])
            if item["alert_status"] == "expired":
                expired.append(item)
            else:
                expiring_soon.append(item)

        return {
            "expired": expired,
            "expired_count": len(expired),
            "expiring_soon": expiring_soon,
            "expiring_soon_count": len(expiring_soon),
            "total_alerts": len(expired) + len(expiring_soon)
        }


@batches_router.get("/batches/{batch_id}", dependencies=[Depends(require_permission("stock.view"))], response_model=Dict[str, Any])
def get_batch(batch_id: int, current_user: dict = Depends(get_current_user)):
    """تفاصيل دفعة محددة"""
    with transactional(current_user.company_id) as db:
        batch = db.execute(text("""
            SELECT b.*, 
                   p.product_name, p.product_code,
                   w.warehouse_name,
                   s.name as supplier_name
            FROM product_batches b
            JOIN products p ON b.product_id = p.id
            JOIN warehouses w ON b.warehouse_id = w.id
            LEFT JOIN parties s ON b.supplier_id = s.id
            WHERE b.id = :id
        """), {"id": batch_id}).fetchone()

        if not batch:
            raise HTTPException(**http_error(404, "batch_not_found"))

        result = dict(batch._mapping)

        # Get movements for this batch
        movements = db.execute(text("""
            SELECT bsm.*, cu.full_name as user_name
            FROM batch_serial_movements bsm
            LEFT JOIN company_users cu ON bsm.created_by = cu.id
            WHERE bsm.batch_id = :bid
            ORDER BY bsm.created_at DESC
        """), {"bid": batch_id}).fetchall()

        result["movements"] = [dict(m._mapping) for m in movements]

        # Get serials in this batch
        serials = db.execute(text("""
            SELECT id, serial_number, status, created_at
            FROM product_serials
            WHERE batch_id = :bid
            ORDER BY serial_number
        """), {"bid": batch_id}).fetchall()

        result["serials"] = [dict(s._mapping) for s in serials]

        return result


@batches_router.post("/batches", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("stock.manage"))], response_model=Dict[str, Any])
def create_batch(
    batch: BatchCreate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """إنشاء دفعة جديدة"""
    with transactional(current_user.company_id) as db:
        try:
            # Check product exists and has batch tracking
            product = db.execute(text("""
                SELECT id, product_name, has_batch_tracking FROM products WHERE id = :id
            """), {"id": batch.product_id}).fetchone()
    
            if not product:
                raise HTTPException(**http_error(404, "product_not_found"))
    
            # Check duplicate batch number
            exists = db.execute(text("""
                SELECT 1 FROM product_batches 
                WHERE product_id = :pid AND warehouse_id = :wid AND batch_number = :bn
            """), {"pid": batch.product_id, "wid": batch.warehouse_id, "bn": batch.batch_number}).fetchone()
    
            if exists:
                raise HTTPException(**http_error(400, "batch_number_duplicate", request))
    
            result = db.execute(text("""
                INSERT INTO product_batches (
                    product_id, warehouse_id, batch_number, manufacturing_date, expiry_date,
                    quantity, available_quantity, unit_cost, supplier_id, notes, 
                    created_by, status
                ) VALUES (
                    :pid, :wid, :bn, :mdate, :edate,
                    :qty, :qty, :cost, :sid, :notes,
                    :uid, 'active'
                ) RETURNING id, created_at
            """), {
                "pid": batch.product_id,
                "wid": batch.warehouse_id,
                "bn": batch.batch_number,
                "mdate": batch.manufacturing_date,
                "edate": batch.expiry_date,
                "qty": batch.quantity,
                "cost": batch.unit_cost,
                "sid": batch.supplier_id,
                "notes": batch.notes,
                "uid": current_user.id
            }).fetchone()
    
            # If quantity > 0, update inventory and log movement
            if batch.quantity > 0:
                from services.costing_service import CostingService
                unit_cost = Decimal(str(batch.unit_cost or 0))
                CostingService.update_cost(
                    db,
                    product_id=batch.product_id,
                    warehouse_id=batch.warehouse_id,
                    new_qty=float(batch.quantity),
                    new_price=float(unit_cost),
                )
                costing_method = CostingService._get_product_costing_method(db, batch.product_id, batch.warehouse_id)
                if costing_method in ("fifo", "lifo"):
                    CostingService.create_cost_layer(
                        db,
                        product_id=batch.product_id,
                        warehouse_id=batch.warehouse_id,
                        quantity=float(batch.quantity),
                        unit_cost=float(unit_cost),
                        source_document_type="batch",
                        source_document_id=result.id,
                        costing_method=costing_method,
                    )

                # Upsert inventory
                db.execute(text("""
                    INSERT INTO inventory (product_id, warehouse_id, quantity, average_cost, updated_at)
                    VALUES (:pid, :wid, :qty, :cost, NOW())
                    ON CONFLICT (product_id, warehouse_id)
                    DO UPDATE SET quantity = inventory.quantity + EXCLUDED.quantity,
                                  updated_at = NOW()
                """), {
                    "pid": batch.product_id,
                    "wid": batch.warehouse_id,
                    "qty": batch.quantity,
                    "cost": float(unit_cost),
                })
    
                # Log inventory transaction
                db.execute(text("""
                    INSERT INTO inventory_transactions (
                        product_id, warehouse_id, transaction_type, reference_type,
                        reference_id, quantity, unit_cost, total_cost, notes, created_by
                    ) VALUES (
                        :pid, :wid, 'batch_in', 'batch',
                        :bid, :qty, :cost, :total, :notes, :uid
                    )
                """), {
                    "pid": batch.product_id,
                    "wid": batch.warehouse_id,
                    "bid": result.id,
                    "qty": batch.quantity,
                    "cost": batch.unit_cost,
                    "total": batch.quantity * batch.unit_cost,
                    "notes": f"إضافة دفعة {batch.batch_number}",
                    "uid": current_user.id
                })
    
                # Log batch movement
                db.execute(text("""
                    INSERT INTO batch_serial_movements (
                        product_id, batch_id, warehouse_id, movement_type,
                        reference_type, quantity, notes, created_by
                    ) VALUES (
                        :pid, :bid, :wid, 'batch_create',
                        'batch', :qty, :notes, :uid
                    )
                """), {
                    "pid": batch.product_id,
                    "bid": result.id,
                    "wid": batch.warehouse_id,
                    "qty": batch.quantity,
                    "notes": f"إنشاء دفعة {batch.batch_number}",
                    "uid": current_user.id
                })
    
            # Enable batch tracking on product if not already
            db.execute(text("""
                UPDATE products SET has_batch_tracking = TRUE WHERE id = :pid AND has_batch_tracking = FALSE
            """), {"pid": batch.product_id})
    
    
            # INV-L01: Audit log for batch creation
            log_activity(
                db, user_id=current_user.id, username=current_user.username,
                action="batch.create", resource_type="product_batch",
                resource_id=str(result.id),
                details={"batch_number": batch.batch_number, "product_id": batch.product_id, "warehouse_id": batch.warehouse_id, "quantity": batch.quantity},
                request=request
            )
    
            return {
                "id": result.id,
                "batch_number": batch.batch_number,
                "message": i18n_message("batch_created_success", request)
            }
        except HTTPException:
            raise
        except Exception as e:
            pass
            logger.error(f"Error creating batch: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@batches_router.put("/batches/{batch_id}", dependencies=[Depends(require_permission("stock.manage"))], response_model=Dict[str, Any])
def update_batch(request: Request, 
    batch_id: int,
    data: BatchUpdate,
    current_user: dict = Depends(get_current_user)
):
    """تحديث بيانات دفعة"""
    with transactional(current_user.company_id) as db:
        try:
            batch = db.execute(text("SELECT id FROM product_batches WHERE id = :id"), {"id": batch_id}).fetchone()
            if not batch:
                raise HTTPException(**http_error(404, "batch_not_found"))
    
            updates = []
            params = {"id": batch_id}
    
            if data.manufacturing_date is not None:
                updates.append("manufacturing_date = :mdate")
                params["mdate"] = data.manufacturing_date
            if data.expiry_date is not None:
                updates.append("expiry_date = :edate")
                params["edate"] = data.expiry_date
            if data.notes is not None:
                updates.append("notes = :notes")
                params["notes"] = data.notes
            if data.status is not None:
                updates.append("status = :status")
                params["status"] = data.status
    
            if updates:
                updates.append("updated_at = NOW()")
                db.execute(text(f"UPDATE product_batches SET {', '.join(updates)} WHERE id = :id"), params) # noqa: sql-lint
                db.commit()
    
            return {"message": i18n_message("batch_updated_success", request)}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@batches_router.get("/batches/product/{product_id}", dependencies=[Depends(require_permission("stock.view"))], response_model=List[Dict[str, Any]])
def get_product_batches(
    product_id: int,
    warehouse_id: Optional[int] = None,
    active_only: bool = True,
    current_user: dict = Depends(get_current_user)
):
    """جلب دفعات منتج محدد (FEFO: الأقرب انتهاءً أولاً)"""
    with transactional(current_user.company_id) as db:
        query = """
            SELECT b.*, w.warehouse_name
            FROM product_batches b
            JOIN warehouses w ON b.warehouse_id = w.id
            WHERE b.product_id = :pid
        """
        params = {"pid": product_id}

        if warehouse_id:
            query += " AND b.warehouse_id = :wid"
            params["wid"] = warehouse_id
        if active_only:
            query += " AND b.status = 'active' AND b.quantity > 0"

        # FEFO: First Expired First Out
        query += " ORDER BY COALESCE(b.expiry_date, '9999-12-31') ASC, b.created_at ASC"

        rows = db.execute(text(query), params).fetchall()
        return [dict(r._mapping) for r in rows]


# ============ SERIAL NUMBER ENDPOINTS ============

@batches_router.get("/serials", dependencies=[Depends(require_permission("stock.view"))], response_model=Dict[str, Any])
def list_serials(
    product_id: Optional[int] = None,
    warehouse_id: Optional[int] = None,
    batch_id: Optional[int] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(get_current_user)
):
    """قائمة الأرقام التسلسلية"""
    with transactional(current_user.company_id) as db:
        query = """
            SELECT s.*, 
                   p.product_name, p.product_code,
                   w.warehouse_name,
                   b.batch_number
            FROM product_serials s
            JOIN products p ON s.product_id = p.id
            LEFT JOIN warehouses w ON s.warehouse_id = w.id
            LEFT JOIN product_batches b ON s.batch_id = b.id
            WHERE 1=1
        """
        params = {"limit": limit, "skip": skip}

        if product_id:
            query += " AND s.product_id = :pid"
            params["pid"] = product_id
        if warehouse_id:
            query += " AND s.warehouse_id = :wid"
            params["wid"] = warehouse_id
        if batch_id:
            query += " AND s.batch_id = :bid"
            params["bid"] = batch_id
        if status:
            query += " AND s.status = :status"
            params["status"] = status
        if search:
            query += " AND (s.serial_number ILIKE :search OR p.product_name ILIKE :search)"
            params["search"] = f"%{search}%"

        query += " ORDER BY s.created_at DESC LIMIT :limit OFFSET :skip"
        rows = db.execute(text(query), params).fetchall()

        # Count
        count_query = "SELECT COUNT(*) FROM product_serials s WHERE 1=1"
        count_params = {}
        if product_id:
            count_query += " AND s.product_id = :pid"
            count_params["pid"] = product_id
        if status:
            count_query += " AND s.status = :status"
            count_params["status"] = status

        total = db.execute(text(count_query), count_params).scalar() or 0

        return {
            "items": [dict(r._mapping) for r in rows],
            "total": total
        }


@batches_router.get("/serials/{serial_id}", dependencies=[Depends(require_permission("stock.view"))], response_model=Dict[str, Any])
def get_serial(serial_id: int, current_user: dict = Depends(get_current_user)):
    """تفاصيل رقم تسلسلي محدد"""
    with transactional(current_user.company_id) as db:
        serial = db.execute(text("""
            SELECT s.*, 
                   p.product_name, p.product_code,
                   w.warehouse_name,
                   b.batch_number,
                   c.name as customer_name
            FROM product_serials s
            JOIN products p ON s.product_id = p.id
            LEFT JOIN warehouses w ON s.warehouse_id = w.id
            LEFT JOIN product_batches b ON s.batch_id = b.id
            LEFT JOIN parties c ON s.customer_id = c.id
            WHERE s.id = :id
        """), {"id": serial_id}).fetchone()

        if not serial:
            raise HTTPException(**http_error(404, "serial_number_not_found"))

        result = dict(serial._mapping)

        # Get movement history
        movements = db.execute(text("""
            SELECT bsm.*, cu.full_name as user_name
            FROM batch_serial_movements bsm
            LEFT JOIN company_users cu ON bsm.created_by = cu.id
            WHERE bsm.serial_id = :sid
            ORDER BY bsm.created_at DESC
        """), {"sid": serial_id}).fetchall()

        result["movements"] = [dict(m._mapping) for m in movements]

        return result


@batches_router.get("/serials/lookup/{serial_number}", dependencies=[Depends(require_permission("stock.view"))], response_model=Dict[str, Any])
def lookup_serial(serial_number: str, current_user: dict = Depends(get_current_user)):
    """البحث عن رقم تسلسلي بالرقم"""
    with transactional(current_user.company_id) as db:
        serial = db.execute(text("""
            SELECT s.*, 
                   p.product_name, p.product_code,
                   w.warehouse_name,
                   b.batch_number,
                   c.name as customer_name
            FROM product_serials s
            JOIN products p ON s.product_id = p.id
            LEFT JOIN warehouses w ON s.warehouse_id = w.id
            LEFT JOIN product_batches b ON s.batch_id = b.id
            LEFT JOIN parties c ON s.customer_id = c.id
            WHERE s.serial_number = :sn
        """), {"sn": serial_number}).fetchone()

        if not serial:
            raise HTTPException(**http_error(404, "serial_number_not_found"))

        result = dict(serial._mapping)

        # Get movement history
        movements = db.execute(text("""
            SELECT bsm.*, cu.full_name as user_name
            FROM batch_serial_movements bsm
            LEFT JOIN company_users cu ON bsm.created_by = cu.id
            WHERE bsm.serial_id = :sid
            ORDER BY bsm.created_at DESC
        """), {"sid": serial.id}).fetchall()

        result["movements"] = [dict(m._mapping) for m in movements]

        return result


@batches_router.post("/serials", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("stock.manage"))], response_model=Dict[str, Any])
def create_serial(
    serial: SerialCreate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """إنشاء رقم تسلسلي واحد"""
    with transactional(current_user.company_id) as db:
        try:
            # Validate product
            product = db.execute(text("SELECT id, product_name FROM products WHERE id = :id"), {"id": serial.product_id}).fetchone()
            if not product:
                raise HTTPException(**http_error(404, "product_not_found"))
    
            # Check duplicate
            exists = db.execute(text("""
                SELECT 1 FROM product_serials WHERE product_id = :pid AND serial_number = :sn
            """), {"pid": serial.product_id, "sn": serial.serial_number}).fetchone()
    
            if exists:
                raise HTTPException(**http_error(400, "serial_number_duplicate", request))
    
            result = db.execute(text("""
                INSERT INTO product_serials (
                    product_id, warehouse_id, serial_number, batch_id,
                    purchase_price, warranty_start, warranty_end,
                    status, notes, created_by
                ) VALUES (
                    :pid, :wid, :sn, :bid,
                    :price, :ws, :we,
                    'available', :notes, :uid
                ) RETURNING id, created_at
            """), {
                "pid": serial.product_id,
                "wid": serial.warehouse_id,
                "sn": serial.serial_number,
                "bid": serial.batch_id,
                "price": serial.purchase_price,
                "ws": serial.warranty_start,
                "we": serial.warranty_end,
                "notes": serial.notes,
                "uid": current_user.id
            }).fetchone()
    
            # Log movement
            db.execute(text("""
                INSERT INTO batch_serial_movements (
                    product_id, serial_id, warehouse_id, movement_type,
                    reference_type, quantity, notes, created_by
                ) VALUES (
                    :pid, :sid, :wid, 'serial_create',
                    'serial', 1, :notes, :uid
                )
            """), {
                "pid": serial.product_id,
                "sid": result.id,
                "wid": serial.warehouse_id,
                "notes": f"إنشاء رقم تسلسلي {serial.serial_number}",
                "uid": current_user.id
            })
    
            # Enable serial tracking
            db.execute(text("UPDATE products SET has_serial_tracking = TRUE WHERE id = :pid"), {"pid": serial.product_id})
    
            # INV-L01: Audit log for serial creation
            log_activity(
                db, user_id=current_user.id, username=current_user.username,
                action="serial.create", resource_type="product_serial",
                resource_id=str(result.id),
                details={"serial_number": serial.serial_number, "product_id": serial.product_id, "warehouse_id": serial.warehouse_id},
                request=request
            )
            return {"id": result.id, "serial_number": serial.serial_number, "message": i18n_message("serial_created_success", request)}
        except HTTPException:
            raise
        except Exception as e:
            pass
            logger.error(f"Error creating serial: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@batches_router.post("/serials/bulk", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("stock.manage"))], response_model=Dict[str, Any])
def create_serials_bulk(request: Request, 
    data: SerialBulkCreate,
    current_user: dict = Depends(get_current_user)
):
    """إنشاء أرقام تسلسلية دفعة واحدة"""
    with transactional(current_user.company_id) as db:
        try:
            if data.count > 1000:
                raise HTTPException(**http_error(400, "max_serials_exceeded", request))
    
            product = db.execute(text("SELECT id FROM products WHERE id = :id"), {"id": data.product_id}).fetchone()
            if not product:
                raise HTTPException(**http_error(404, "product_not_found"))
    
            created = []
            failed = []
    
            for i in range(data.count):
                num = data.start_number + i
                serial_number = f"{data.prefix}{str(num).zfill(len(str(data.start_number + data.count)))}"
    
                try:
                    result = db.execute(text("""
                        INSERT INTO product_serials (
                            product_id, warehouse_id, serial_number, batch_id,
                            purchase_price, status, notes, created_by
                        ) VALUES (
                            :pid, :wid, :sn, :bid,
                            :price, 'available', :notes, :uid
                        ) RETURNING id
                    """), {
                        "pid": data.product_id,
                        "wid": data.warehouse_id,
                        "sn": serial_number,
                        "bid": data.batch_id,
                        "price": data.purchase_price,
                        "notes": data.notes,
                        "uid": current_user.id
                    }).fetchone()
    
                    # Log movement
                    db.execute(text("""
                        INSERT INTO batch_serial_movements (
                            product_id, serial_id, warehouse_id, movement_type,
                            reference_type, quantity, notes, created_by
                        ) VALUES (:pid, :sid, :wid, 'serial_create', 'serial', 1, :notes, :uid)
                    """), {
                        "pid": data.product_id, "sid": result.id, "wid": data.warehouse_id,
                        "notes": f"إنشاء رقم تسلسلي {serial_number}", "uid": current_user.id
                    })
    
                    created.append(serial_number)
                except Exception as e:
                    failed.append({"serial": serial_number, "error": str(e)})
                    db.rollback()
                    continue
    
            # Enable serial tracking
            db.execute(text("UPDATE products SET has_serial_tracking = TRUE WHERE id = :pid"), {"pid": data.product_id})
    
            return {
                "message": i18n_message("serials_created_count", request),
                "created_count": len(created),
                "failed_count": len(failed),
                "created": created[:20],  # Return first 20 only
                "failed": failed
            }
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@batches_router.put("/serials/{serial_id}", dependencies=[Depends(require_permission("stock.manage"))], response_model=Dict[str, Any])
def update_serial(request: Request, 
    serial_id: int,
    data: SerialUpdate,
    current_user: dict = Depends(get_current_user)
):
    """تحديث بيانات رقم تسلسلي"""
    with transactional(current_user.company_id) as db:
        try:
            serial = db.execute(text("SELECT id, serial_number FROM product_serials WHERE id = :id"), {"id": serial_id}).fetchone()
            if not serial:
                raise HTTPException(**http_error(404, "serial_number_not_found"))
    
            updates = []
            params = {"id": serial_id}
    
            if data.status is not None:
                updates.append("status = :status")
                params["status"] = data.status
            if data.warranty_start is not None:
                updates.append("warranty_start = :ws")
                params["ws"] = data.warranty_start
            if data.warranty_end is not None:
                updates.append("warranty_end = :we")
                params["we"] = data.warranty_end
            if data.notes is not None:
                updates.append("notes = :notes")
                params["notes"] = data.notes
    
            if updates:
                updates.append("updated_at = NOW()")
                db.execute(text(f"UPDATE product_serials SET {', '.join(updates)} WHERE id = :id"), params) # noqa: sql-lint
                db.commit()
    
            return {"message": i18n_message("serial_number_updated", request)}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ============ PRODUCT TRACKING CONFIG ============

@batches_router.put("/products/{product_id}/tracking", dependencies=[Depends(require_permission("products.edit"))], response_model=Dict[str, Any])
def update_product_tracking(request: Request, 
    product_id: int,
    has_batch_tracking: Optional[bool] = None,
    has_serial_tracking: Optional[bool] = None,
    has_expiry_tracking: Optional[bool] = None,
    shelf_life_days: Optional[int] = None,
    expiry_alert_days: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تحديث إعدادات تتبع المنتج"""
    with transactional(current_user.company_id) as db:
        try:
            product = db.execute(text("SELECT id FROM products WHERE id = :id"), {"id": product_id}).fetchone()
            if not product:
                raise HTTPException(**http_error(404, "product_not_found"))
    
            updates = []
            params = {"id": product_id}
    
            if has_batch_tracking is not None:
                updates.append("has_batch_tracking = :hbt")
                params["hbt"] = has_batch_tracking
            if has_serial_tracking is not None:
                updates.append("has_serial_tracking = :hst")
                params["hst"] = has_serial_tracking
            if has_expiry_tracking is not None:
                updates.append("has_expiry_tracking = :het")
                params["het"] = has_expiry_tracking
            if shelf_life_days is not None:
                updates.append("shelf_life_days = :sld")
                params["sld"] = shelf_life_days
            if expiry_alert_days is not None:
                updates.append("expiry_alert_days = :ead")
                params["ead"] = expiry_alert_days
    
            if updates:
                db.execute(text(f"UPDATE products SET {', '.join(updates)}, updated_at = NOW() WHERE id = :id"), params) # noqa: sql-lint
                db.commit()
    
            return {"message": i18n_message("tracking_settings_updated", request)}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ============ QUALITY CONTROL ============

@batches_router.get("/quality-inspections", dependencies=[Depends(require_permission("stock.view"))], response_model=Dict[str, Any])
def list_quality_inspections(
    product_id: Optional[int] = None,
    status: Optional[str] = None,
    inspection_type: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    current_user: dict = Depends(get_current_user)
):
    """قائمة فحوصات الجودة"""
    with transactional(current_user.company_id) as db:
        query = """
            SELECT qi.*, 
                   p.product_name, p.product_code,
                   w.warehouse_name,
                   b.batch_number,
                   ins.full_name as inspector_name
            FROM quality_inspections qi
            JOIN products p ON qi.product_id = p.id
            LEFT JOIN warehouses w ON qi.warehouse_id = w.id
            LEFT JOIN product_batches b ON qi.batch_id = b.id
            LEFT JOIN company_users ins ON qi.inspector_id = ins.id
            WHERE 1=1
        """
        params = {"limit": limit, "skip": skip}

        if product_id:
            query += " AND qi.product_id = :pid"
            params["pid"] = product_id
        if status:
            query += " AND qi.status = :status"
            params["status"] = status
        if inspection_type:
            query += " AND qi.inspection_type = :itype"
            params["itype"] = inspection_type

        query += " ORDER BY qi.created_at DESC LIMIT :limit OFFSET :skip"
        rows = db.execute(text(query), params).fetchall()

        total = db.execute(text("SELECT COUNT(*) FROM quality_inspections"), {}).scalar() or 0

        return {"items": [dict(r._mapping) for r in rows], "total": total}


@batches_router.get("/quality-inspections/{inspection_id}", dependencies=[Depends(require_permission("stock.view"))], response_model=Dict[str, Any])
def get_quality_inspection(inspection_id: int, current_user: dict = Depends(get_current_user)):
    """تفاصيل فحص جودة"""
    with transactional(current_user.company_id) as db:
        qi = db.execute(text("""
            SELECT qi.*, p.product_name, p.product_code, w.warehouse_name,
                   b.batch_number, ins.full_name as inspector_name
            FROM quality_inspections qi
            JOIN products p ON qi.product_id = p.id
            LEFT JOIN warehouses w ON qi.warehouse_id = w.id
            LEFT JOIN product_batches b ON qi.batch_id = b.id
            LEFT JOIN company_users ins ON qi.inspector_id = ins.id
            WHERE qi.id = :id
        """), {"id": inspection_id}).fetchone()

        if not qi:
            raise HTTPException(**http_error(404, "quality_check_not_found"))

        result = dict(qi._mapping)

        # Get criteria
        criteria = db.execute(text("""
            SELECT * FROM quality_inspection_criteria WHERE inspection_id = :iid ORDER BY id
        """), {"iid": inspection_id}).fetchall()

        result["criteria"] = [dict(c._mapping) for c in criteria]
        return result


class QualityInspectionCreate(BaseModel):
    inspection_type: str  # incoming, outgoing, in_process, periodic
    product_id: int
    warehouse_id: Optional[int] = None
    batch_id: Optional[int] = None
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None
    inspected_quantity: float = 0
    criteria: Optional[list] = []
    notes: Optional[str] = None


class QualityInspectionComplete(BaseModel):
    accepted_quantity: float = 0
    rejected_quantity: float = 0
    status: str  # passed, failed, partial
    result_notes: Optional[str] = None
    rejection_reason: Optional[str] = None
    criteria: Optional[list] = []


@batches_router.post("/quality-inspections", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("stock.manage"))], response_model=Dict[str, Any])
def create_quality_inspection(request: Request, 
    data: QualityInspectionCreate,
    current_user: dict = Depends(get_current_user)
):
    """إنشاء فحص جودة جديد"""
    with transactional(current_user.company_id) as db:
        try:
            # Generate inspection number
            count = db.execute(text("SELECT COUNT(*) FROM quality_inspections")).scalar() or 0
            inspection_number = f"QI-{datetime.now().year}-{str(count + 1).zfill(5)}"
    
            result = db.execute(text("""
                INSERT INTO quality_inspections (
                    inspection_number, inspection_type, product_id, warehouse_id,
                    batch_id, reference_type, reference_id, inspected_quantity,
                    status, created_by
                ) VALUES (
                    :num, :type, :pid, :wid, :bid, :rtype, :rid, :qty,
                    'pending', :uid
                ) RETURNING id
            """), {
                "num": inspection_number,
                "type": data.inspection_type,
                "pid": data.product_id,
                "wid": data.warehouse_id,
                "bid": data.batch_id,
                "rtype": data.reference_type,
                "rid": data.reference_id,
                "qty": data.inspected_quantity,
                "uid": current_user.id
            }).fetchone()
    
            # Add criteria
            for criterion in (data.criteria or []):
                db.execute(text("""
                    INSERT INTO quality_inspection_criteria (
                        inspection_id, criteria_name, expected_value
                    ) VALUES (:iid, :name, :expected)
                """), {
                    "iid": result.id,
                    "name": criterion.get("name", ""),
                    "expected": criterion.get("expected_value", "")
                })
    
            return {"id": result.id, "inspection_number": inspection_number, "message": i18n_message("quality_inspection_created", request)}
        except HTTPException:
            raise
        except Exception as e:
            pass
            logger.error(f"Error creating QI: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@batches_router.put("/quality-inspections/{inspection_id}/complete", dependencies=[Depends(require_permission("stock.manage"))], response_model=Dict[str, Any])
def complete_quality_inspection(request: Request, 
    inspection_id: int,
    data: QualityInspectionComplete,
    current_user: dict = Depends(get_current_user)
):
    """إكمال فحص الجودة وتسجيل النتيجة"""
    with transactional(current_user.company_id) as db:
        try:
            qi = db.execute(text("SELECT * FROM quality_inspections WHERE id = :id"), {"id": inspection_id}).fetchone()
            if not qi:
                raise HTTPException(**http_error(404, "quality_check_not_found"))
    
            db.execute(text("""
                UPDATE quality_inspections SET
                    accepted_quantity = :accepted,
                    rejected_quantity = :rejected,
                    status = :status,
                    result_notes = :notes,
                    rejection_reason = :reason,
                    inspector_id = :uid,
                    completed_date = NOW(),
                    updated_at = NOW()
                WHERE id = :id
            """), {
                "accepted": data.accepted_quantity,
                "rejected": data.rejected_quantity,
                "status": data.status,
                "notes": data.result_notes,
                "reason": data.rejection_reason,
                "uid": current_user.id,
                "id": inspection_id
            })
    
            # Update criteria
            for criterion in (data.criteria or []):
                if criterion.get("id"):
                    db.execute(text("""
                        UPDATE quality_inspection_criteria SET
                            actual_value = :actual,
                            is_passed = :passed,
                            notes = :notes
                        WHERE id = :id
                    """), {
                        "actual": criterion.get("actual_value", ""),
                        "passed": criterion.get("is_passed", False),
                        "notes": criterion.get("notes", ""),
                        "id": criterion["id"]
                    })
    
            return {"message": i18n_message("quality_inspection_completed", request)}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ============ CYCLE COUNTS ============

class CycleCountCreate(BaseModel):
    warehouse_id: int
    count_type: str = "full"  # full, partial, category
    scheduled_date: Optional[str] = None
    product_ids: Optional[list] = None  # For partial count
    notes: Optional[str] = None


class CycleCountItemUpdate(BaseModel):
    id: int
    counted_quantity: float
    notes: Optional[str] = None


class CycleCountComplete(BaseModel):
    items: List[CycleCountItemUpdate]
    auto_adjust: bool = False


@batches_router.get("/cycle-counts", dependencies=[Depends(require_permission("stock.view"))], response_model=Dict[str, Any])
def list_cycle_counts(
    warehouse_id: Optional[int] = None,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    current_user: dict = Depends(get_current_user)
):
    """قائمة الجرد الدوري"""
    with transactional(current_user.company_id) as db:
        query = """
            SELECT cc.*, w.warehouse_name, cu.full_name as created_by_name
            FROM cycle_counts cc
            JOIN warehouses w ON cc.warehouse_id = w.id
            LEFT JOIN company_users cu ON cc.created_by = cu.id
            WHERE 1=1
        """
        params = {"limit": limit, "skip": skip}

        if warehouse_id:
            query += " AND cc.warehouse_id = :wid"
            params["wid"] = warehouse_id
        if status:
            query += " AND cc.status = :status"
            params["status"] = status

        query += " ORDER BY cc.created_at DESC LIMIT :limit OFFSET :skip"
        rows = db.execute(text(query), params).fetchall()

        total = db.execute(text("SELECT COUNT(*) FROM cycle_counts"), {}).scalar() or 0

        return {"items": [dict(r._mapping) for r in rows], "total": total}


@batches_router.get("/cycle-counts/{count_id}", dependencies=[Depends(require_permission("stock.view"))], response_model=Dict[str, Any])
def get_cycle_count(count_id: int, current_user: dict = Depends(get_current_user)):
    """تفاصيل الجرد الدوري"""
    with transactional(current_user.company_id) as db:
        cc = db.execute(text("""
            SELECT cc.*, w.warehouse_name, cu.full_name as created_by_name
            FROM cycle_counts cc
            JOIN warehouses w ON cc.warehouse_id = w.id
            LEFT JOIN company_users cu ON cc.created_by = cu.id
            WHERE cc.id = :id
        """), {"id": count_id}).fetchone()

        if not cc:
            raise HTTPException(**http_error(404, "inventory_not_found"))

        result = dict(cc._mapping)

        # Get items
        items = db.execute(text("""
            SELECT cci.*, p.product_name, p.product_code,
                   cu.full_name as counted_by_name
            FROM cycle_count_items cci
            JOIN products p ON cci.product_id = p.id
            LEFT JOIN company_users cu ON cci.counted_by = cu.id
            WHERE cci.cycle_count_id = :ccid
            ORDER BY p.product_name
        """), {"ccid": count_id}).fetchall()

        result["items"] = [dict(i._mapping) for i in items]
        return result


@batches_router.post("/cycle-counts", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("stock.manage"))], response_model=Dict[str, Any])
def create_cycle_count(request: Request, 
    data: CycleCountCreate,
    current_user: dict = Depends(get_current_user)
):
    """إنشاء جرد دوري جديد"""
    with transactional(current_user.company_id) as db:
        try:
            # Generate count number
            count = db.execute(text("SELECT COUNT(*) FROM cycle_counts")).scalar() or 0
            count_number = f"CC-{datetime.now().year}-{str(count + 1).zfill(5)}"
    
            # Get products to count
            if data.count_type == "full":
                # All products in warehouse
                products = db.execute(text("""
                    SELECT i.product_id, i.quantity, COALESCE(p.cost_price, 0) as cost
                    FROM inventory i
                    JOIN products p ON i.product_id = p.id
                    WHERE i.warehouse_id = :wid AND p.product_type = 'product'
                """), {"wid": data.warehouse_id}).fetchall()
            elif data.product_ids:
                products = db.execute(text("""
                    SELECT i.product_id, i.quantity, COALESCE(p.cost_price, 0) as cost
                    FROM inventory i
                    JOIN products p ON i.product_id = p.id
                    WHERE i.warehouse_id = :wid AND i.product_id = ANY(:pids)
                """), {"wid": data.warehouse_id, "pids": data.product_ids}).fetchall()
            else:
                products = []
    
            result = db.execute(text("""
                INSERT INTO cycle_counts (
                    count_number, warehouse_id, count_type, status,
                    scheduled_date, total_items, notes, created_by
                ) VALUES (
                    :num, :wid, :type, 'draft',
                    :sdate, :total, :notes, :uid
                ) RETURNING id
            """), {
                "num": count_number,
                "wid": data.warehouse_id,
                "type": data.count_type,
                "sdate": data.scheduled_date,
                "total": len(products),
                "notes": data.notes,
                "uid": current_user.id
            }).fetchone()
    
            # Create count items
            for prod in products:
                db.execute(text("""
                    INSERT INTO cycle_count_items (
                        cycle_count_id, product_id, system_quantity, unit_cost, status
                    ) VALUES (:ccid, :pid, :qty, :cost, 'pending')
                """), {
                    "ccid": result.id,
                    "pid": prod.product_id,
                    "qty": str(prod.quantity),
                    "cost": str(prod.cost)
                })
    
            return {
                "id": result.id,
                "count_number": count_number,
                "total_items": len(products),
                "message": i18n_message("cycle_count_created_success", request)
            }
        except HTTPException:
            raise
        except Exception as e:
            pass
            logger.error(f"Error creating cycle count: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@batches_router.put("/cycle-counts/{count_id}/start", dependencies=[Depends(require_permission("stock.manage"))], response_model=Dict[str, Any])
def start_cycle_count(request: Request, count_id: int, current_user: dict = Depends(get_current_user)):
    """بدء الجرد الدوري"""
    with transactional(current_user.company_id) as db:
        try:
            cc = db.execute(text("SELECT status FROM cycle_counts WHERE id = :id"), {"id": count_id}).fetchone()
            if not cc:
                raise HTTPException(**http_error(404, "inventory_not_found"))
            if cc.status != 'draft':
                raise HTTPException(**http_error(400, "cycle_count_not_draft", request))
    
            db.execute(text("""
                UPDATE cycle_counts SET status = 'in_progress', start_date = NOW(), updated_at = NOW()
                WHERE id = :id
            """), {"id": count_id})
            return {"message": i18n_message("cycle_count_started", request)}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@batches_router.put("/cycle-counts/{count_id}/complete", dependencies=[Depends(require_permission("stock.manage"))], response_model=Dict[str, Any])
def complete_cycle_count(request: Request, 
    count_id: int,
    data: CycleCountComplete,
    current_user: dict = Depends(get_current_user)
):
    """إكمال الجرد الدوري وحساب الفروقات"""
    with transactional(current_user.company_id) as db:
        try:
            cc = db.execute(text("SELECT * FROM cycle_counts WHERE id = :id"), {"id": count_id}).fetchone()
            if not cc:
                raise HTTPException(**http_error(404, "inventory_not_found"))
    
            variance_count = 0
            counted_count = 0
    
            for item in data.items:
                # Get count item
                cci = db.execute(text("""
                    SELECT * FROM cycle_count_items WHERE id = :id AND cycle_count_id = :ccid
                """), {"id": item.id, "ccid": count_id}).fetchone()
    
                if not cci:
                    continue
    
                variance = item.counted_quantity - (cci.system_quantity or 0)
                variance_value = variance * (cci.unit_cost or 0)
    
                db.execute(text("""
                    UPDATE cycle_count_items SET
                        counted_quantity = :qty,
                        variance = :var,
                        variance_value = :vval,
                        status = 'counted',
                        counted_by = :uid,
                        counted_at = NOW(),
                        notes = :notes
                    WHERE id = :id
                """), {
                    "qty": item.counted_quantity,
                    "var": variance,
                    "vval": variance_value,
                    "uid": current_user.id,
                    "notes": item.notes,
                    "id": item.id
                })
    
                counted_count += 1
                if variance != 0:
                    variance_count += 1
    
                    # Auto adjust inventory if requested
                    if data.auto_adjust:
                        # T024: Hard-block negative stock — check reserved qty
                        inv_row = db.execute(text("""
                            SELECT reserved_quantity, quantity - COALESCE(reserved_quantity, 0) as available
                            FROM inventory
                            WHERE product_id = :pid AND warehouse_id = :wid
                            FOR UPDATE
                        """), {"pid": cci.product_id, "wid": cc.warehouse_id}).fetchone()
                        reserved = (inv_row.reserved_quantity if inv_row else 0) or 0
                        new_available = item.counted_quantity - reserved
                        if new_available < 0:
                            prod_name = db.execute(text("SELECT product_name FROM products WHERE id = :pid"), {"pid": cci.product_id}).scalar() or cci.product_id
                            raise HTTPException(
                                status_code=400,
                                detail=f"لا يمكن تعديل المخزون للمنتج {prod_name}: الكمية المحجوزة ({reserved}) أكبر من الكمية المحسوبة ({item.counted_quantity})"
                            )

                        from services.costing_service import CostingService
                        movement_unit_cost = Decimal(str(cci.unit_cost or 0))
                        variance_dec = Decimal(str(variance))
                        movement_total_abs = (abs(variance_dec) * movement_unit_cost).quantize(Decimal("0.01"), ROUND_HALF_UP)
                        costing_method = CostingService._get_product_costing_method(db, cci.product_id, cc.warehouse_id)
                        if variance_dec > 0:
                            CostingService.update_cost(
                                db,
                                product_id=cci.product_id,
                                warehouse_id=cc.warehouse_id,
                                new_qty=float(variance_dec),
                                new_price=float(movement_unit_cost),
                            )
                            if costing_method in ("fifo", "lifo"):
                                CostingService.create_cost_layer(
                                    db,
                                    product_id=cci.product_id,
                                    warehouse_id=cc.warehouse_id,
                                    quantity=float(variance_dec),
                                    unit_cost=float(movement_unit_cost),
                                    source_document_type="cycle_count",
                                    source_document_id=count_id,
                                    costing_method=costing_method,
                                )
                        elif variance_dec < 0 and costing_method in ("fifo", "lifo"):
                            try:
                                consumed_value = CostingService.consume_layers(
                                    db,
                                    product_id=cci.product_id,
                                    warehouse_id=cc.warehouse_id,
                                    quantity=float(abs(variance_dec)),
                                    sale_document_type="cycle_count",
                                    sale_document_id=count_id,
                                    costing_method=costing_method,
                                )
                            except ValueError as exc:
                                raise HTTPException(status_code=400, detail=str(exc))
                            movement_total_abs = Decimal(str(consumed_value)).quantize(Decimal("0.01"), ROUND_HALF_UP)
                            movement_unit_cost = (movement_total_abs / abs(variance_dec)).quantize(Decimal("0.0001"), ROUND_HALF_UP)

                        variance_value = movement_total_abs if variance_dec > 0 else -movement_total_abs
                        db.execute(text("""
                            UPDATE cycle_count_items
                            SET unit_cost = :uc, variance_value = :vv
                            WHERE id = :id
                        """), {
                            "uc": float(movement_unit_cost),
                            "vv": float(variance_value),
                            "id": item.id,
                        })

                        db.execute(text("""
                            UPDATE inventory SET quantity = :qty, updated_at = NOW()
                            WHERE product_id = :pid AND warehouse_id = :wid
                        """), {
                            "qty": item.counted_quantity,
                            "pid": cci.product_id,
                            "wid": cc.warehouse_id
                        })

                        # Log adjustment
                        adj_type = 'adjustment_in' if variance_dec > 0 else 'adjustment_out'
                        db.execute(text("""
                            INSERT INTO inventory_transactions (
                                product_id, warehouse_id, transaction_type, reference_type,
                                reference_id, quantity, unit_cost, total_cost, notes, created_by
                            ) VALUES (
                                :pid, :wid, :type, 'cycle_count', :ccid, :qty,
                                :uc, :tc, :notes, :uid
                            )
                        """), {
                            "pid": cci.product_id,
                            "wid": cc.warehouse_id,
                            "type": adj_type,
                            "ccid": count_id,
                            "qty": variance,
                            "uc": float(movement_unit_cost),
                            "tc": float(movement_total_abs),
                            "notes": f"تسوية جرد دوري {cc.count_number}",
                            "uid": current_user.id
                        })
    
            # T023: Post GL journal entries for cycle count variances
            if data.auto_adjust and variance_count > 0:
                from utils.accounting import get_mapped_account_id, get_base_currency
                from utils.fiscal_lock import check_fiscal_period_open
                from services.gl_service import create_journal_entry as gl_create_journal_entry
    
                acc_inventory = get_mapped_account_id(db, "acc_map_inventory")
                acc_variance = get_mapped_account_id(db, "acc_map_inventory_adjustment")
                base_currency = get_base_currency(db)
    
                if acc_inventory and acc_variance:
                    check_fiscal_period_open(db, datetime.now().date())
    
                    branch_id = db.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": cc.warehouse_id}).scalar()
    
                    # Gather all variance items for GL posting
                    variance_items = db.execute(text("""
                        SELECT cci.product_id, cci.variance, cci.variance_value, cci.unit_cost
                        FROM cycle_count_items cci
                        WHERE cci.cycle_count_id = :ccid AND cci.variance != 0
                    """), {"ccid": count_id}).fetchall()
    
                    for vi in variance_items:
                        abs_value = abs(float(vi.variance_value or 0))
                        if abs_value < 0.01:
                            continue
    
                        if vi.variance > 0:
                            # Surplus: Dr. Inventory Asset / Cr. Inventory Variance
                            lines = [
                                {"account_id": acc_inventory, "debit": abs_value, "credit": 0, "description": f"Cycle Count Surplus - {cc.count_number}"},
                                {"account_id": acc_variance, "debit": 0, "credit": abs_value, "description": f"Inventory Variance - {cc.count_number}"},
                            ]
                        else:
                            # Shortage: Dr. Inventory Variance / Cr. Inventory Asset
                            lines = [
                                {"account_id": acc_variance, "debit": abs_value, "credit": 0, "description": f"Inventory Variance - {cc.count_number}"},
                                {"account_id": acc_inventory, "debit": 0, "credit": abs_value, "description": f"Cycle Count Shortage - {cc.count_number}"},
                            ]
    
                        gl_create_journal_entry(
                            db,
                            company_id=current_user.company_id,
                            date=datetime.now().strftime("%Y-%m-%d"),
                            description=f"Cycle Count Variance - {cc.count_number}",
                            lines=lines,
                            user_id=current_user.id,
                            branch_id=branch_id,
                            reference=cc.count_number,
                            currency=base_currency,
                        )
    
            # Update cycle count
            db.execute(text("""
                UPDATE cycle_counts SET
                    status = 'completed',
                    end_date = NOW(),
                    counted_items = :counted,
                    variance_items = :variance,
                    updated_at = NOW()
                WHERE id = :id
            """), {"counted": counted_count, "variance": variance_count, "id": count_id})
    
            return {
                "message": i18n_message("cycle_count_completed_success", request),
                "counted_items": counted_count,
                "variance_items": variance_count,
                "auto_adjusted": data.auto_adjust
            }
        except HTTPException:
            raise
        except Exception as e:
            pass
            logger.error(f"Error completing cycle count: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
