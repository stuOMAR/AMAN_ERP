"""
Inventory Module - Products CRUD + Cost Breakdown
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.audit import log_activity
from utils.permissions import require_permission
from utils.tx import transactional
from repositories import ProductRepository
from .schemas import ProductCreate, ProductResponse

products_router = APIRouter()
logger = logging.getLogger(__name__)


@products_router.get("/products/{product_id}/cost-breakdown", dependencies=[Depends(require_permission("stock.view_cost"))], response_model=Dict[str, Any])
def get_product_cost_breakdown(
    product_id: int,
    current_user: dict = Depends(get_current_user)
):
    """جلب تفاصيل التكلفة لكل مستودع (للنظام الهجين أو متعدد المستودعات)"""
    db = get_db_connection(current_user.company_id)
    try:
        # Check Policy
        policy = db.execute(text("SELECT policy_type FROM costing_policies WHERE is_active = TRUE")).scalar()

        # Determine global cost
        product = db.execute(text("SELECT cost_price FROM products WHERE id = :id"), {"id": product_id}).fetchone()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        global_cost = product.cost_price or 0

        # Get Warehouse Details
        breakdown = []
        rows = db.execute(text("""
            SELECT 
                w.id as warehouse_id,
                w.warehouse_name,
                i.quantity,
                i.average_cost,
                i.last_costing_update
            FROM inventory i
            JOIN warehouses w ON i.warehouse_id = w.id
            WHERE i.product_id = :pid AND i.quantity > 0
        """), {"pid": product_id}).fetchall()

        for row in rows:
            avg_cost = row.average_cost or 0
            qty = row.quantity or 0

            breakdown.append({
                "warehouse_id": row.warehouse_id,
                "warehouse_name": row.warehouse_name,
                "quantity": str(qty),
                "average_cost": str(avg_cost),
                "total_value": str(qty * avg_cost),
                "last_update": row.last_costing_update.isoformat() if row.last_costing_update else None
            })

        return {
            "policy_type": policy or 'global_wac',
            "global_cost": str(global_cost),
            "breakdown": breakdown
        }
    finally:
        db.close()


@products_router.get("/products", response_model=List[ProductResponse], dependencies=[Depends(require_permission("products.view"))])
def list_products(
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """عرض قائمة المنتجات"""
    from utils.permissions import validate_branch_access
    branch_id = validate_branch_access(current_user, branch_id)

    with transactional(current_user.company_id) as db:
        repo = ProductRepository(db)
        rows = repo.list(branch_id=branch_id, search=search, limit=limit, offset=skip)
        return [
            {
                "id": r["id"],
                "item_code": r.get("product_code"),
                "item_name": r.get("product_name"),
                "item_name_en": r.get("product_name_en"),
                "item_type": r.get("product_type"),
                "unit": r.get("unit_of_measure") or "قطعة",
                "selling_price": str(r.get("selling_price") or 0),
                "buying_price": str(r.get("cost_price") or 0),
                "last_buying_price": str(r.get("last_purchase_price") or 0),
                "tax_rate": str(r.get("tax_rate") or 0),
                "description": r.get("description"),
                "is_active": r.get("is_active", True),
                "current_stock": str(r.get("current_stock") or 0),
                "reserved_quantity": "0",
                "category_id": r.get("category_id"),
                "category_name": r.get("category_name"),
                "has_batch_tracking": r.get("has_batch_tracking") or False,
                "has_serial_tracking": r.get("has_serial_tracking") or False,
                "has_expiry_tracking": r.get("has_expiry_tracking") or False,
                "shelf_life_days": r.get("shelf_life_days") or 0,
                "expiry_alert_days": r.get("expiry_alert_days") or 30,
                "created_at": r.get("created_at"),
            }
            for r in rows
        ]


@products_router.get("/products/{product_id}/stock", response_model=float, dependencies=[Depends(require_permission("stock.view"))])
def get_product_stock(
    product_id: int,
    warehouse_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """جلب رصيد المنتج المتاح (في كل المستودعات أو مستودع محدد)"""
    db = get_db_connection(current_user.company_id)
    try:
        from utils.permissions import validate_branch_access
        # Check permissions - if user is restricted, filter warehouses
        allowed_branch = None
        try:
             allowed_branch = validate_branch_access(current_user, None)
        except Exception:
             # If validation fails (e.g. need to select branch), we might need to handle it or let it fail
             # For stock sum, ideally we return sum of allowed. 
             # For now let's leniently check if they have specific branch requirement
             pass
             
        # But wait, validate_branch_access logic is strict.
        # Let's check user allowed branches manually to filter the SUM
        if isinstance(current_user, dict):
            allowed_branches = current_user.get("allowed_branches", [])
            user_role = current_user.get("role")
            user_perms = current_user.get("permissions", [])
        else:
            allowed_branches = getattr(current_user, "allowed_branches", [])
            user_role = getattr(current_user, "role", None)
            user_perms = getattr(current_user, "permissions", [])

        is_admin = user_role in ['admin', 'system_admin', 'superuser'] or '*' in user_perms
        
        query = "SELECT COALESCE(SUM(quantity), 0) FROM inventory WHERE product_id = :pid"
        params = {"pid": product_id}

        if not is_admin and allowed_branches:
            # Filter by allowed branches
            query += " AND warehouse_id IN (SELECT id FROM warehouses WHERE branch_id = ANY(:allowed_branches))"
            params["allowed_branches"] = allowed_branches

        if warehouse_id:
            query += " AND warehouse_id = :wid"
            params["wid"] = warehouse_id

        total_qty = db.execute(text(query), params).scalar()

        return str(total_qty or 0)
    finally:
        db.close()


@products_router.post("/products", response_model=ProductResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("products.create"))])
def create_product(
    product: ProductCreate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """إنشاء منتج جديد"""
    db = get_db_connection(current_user.company_id)
    try:
        # Check if code exists
        exists = db.execute(
            text("SELECT 1 FROM products WHERE product_code = :code"),
            {"code": product.item_code}
        ).fetchone()

        if exists:
            raise HTTPException(status_code=400, detail="كود المنتج موجود بالفعل")

        # Resolve unit_id
        unit_id = db.execute(
            text("SELECT id FROM product_units WHERE unit_name = :unit OR unit_name_en = :unit LIMIT 1"),
            {"unit": product.unit}
        ).scalar()

        # If unit not found, use default or the first one
        if not unit_id:
            unit_id = db.execute(text("SELECT id FROM product_units LIMIT 1")).scalar()

        result = db.execute(text("""
            INSERT INTO products (
                product_code, product_name, product_name_en, product_type, unit_id, category_id,
                selling_price, cost_price, last_purchase_price, tax_rate, description, is_active,
                has_batch_tracking, has_serial_tracking, has_expiry_tracking, shelf_life_days, expiry_alert_days
            ) VALUES (
                :code, :name, :name_en, :type, :unit_id, :cat_id,
                :sell, :buy, :last_buy, :tax, :desc, :active,
                :hbt, :hst, :het, :sld, :ead
            ) RETURNING id, created_at
        """), {
            "code": product.item_code,
            "name": product.item_name,
            "name_en": product.item_name_en,
            "type": product.item_type,
            "unit_id": unit_id,
            "cat_id": product.category_id,
            "sell": product.selling_price,
            "buy": product.buying_price,
            "last_buy": product.last_buying_price,
            "tax": product.tax_rate,
            "desc": product.description,
            "active": product.is_active,
            "hbt": product.has_batch_tracking,
            "hst": product.has_serial_tracking,
            "het": product.has_expiry_tracking,
            "sld": product.shelf_life_days,
            "ead": product.expiry_alert_days
        }).fetchone()

        # Initialize inventory for default warehouse if product
        if product.item_type == 'product':
            # Get default warehouse
            wh_id = db.execute(text("SELECT id FROM warehouses WHERE is_default = TRUE LIMIT 1")).scalar()
            if wh_id:
                db.execute(text("""
                    INSERT INTO inventory (product_id, warehouse_id, quantity) 
                    VALUES (:pid, :whid, 0)
                """), {"pid": result.id, "whid": wh_id})

        db.commit()

        product_data = {
            **product.model_dump(),
            "id": result.id,
            "current_stock": 0.0,
            "created_at": result.created_at
        }

        # AUDIT LOG
        log_activity(
            db,
            user_id=current_user.id,
            username=current_user.username,
            action="product.create",
            resource_type="product",
            resource_id=str(result.id),
            details={"name": product.item_name, "code": product.item_code},
            request=request
        )

        return product_data
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating product: {str(e)}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@products_router.get("/products/{id}", response_model=ProductResponse, dependencies=[Depends(require_permission("products.view"))])
def get_product(id: int, current_user: dict = Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        product = db.execute(text("""
            SELECT 
                p.id,
                p.product_code as item_code,
                p.product_name as item_name,
                p.product_name_en as item_name_en,
                p.product_type as item_type,
                COALESCE(pu.unit_name, 'قطعة') as unit, 
                p.selling_price,
                p.cost_price as buying_price,
                p.last_purchase_price as last_buying_price,
                p.tax_rate,
                p.description,
                p.category_id,
                p.is_active,
                pc.category_name,
                p.has_batch_tracking, p.has_serial_tracking, p.has_expiry_tracking,
                p.shelf_life_days, p.expiry_alert_days,
                COALESCE((SELECT quantity FROM inventory WHERE product_id = p.id AND warehouse_id = (SELECT id FROM warehouses WHERE is_default = TRUE LIMIT 1)), 0) as current_stock,
                p.created_at
            FROM products p
            LEFT JOIN product_categories pc ON p.category_id = pc.id
            LEFT JOIN product_units pu ON p.unit_id = pu.id
            WHERE p.id = :id
        """), {"id": id}).fetchone()

        if not product:
            raise HTTPException(**http_error(404, "product_not_found"))

        return product
    finally:
        db.close()


@products_router.put("/products/{id}", response_model=ProductResponse, dependencies=[Depends(require_permission("products.edit"))])
def update_product(id: int, product: ProductCreate, request: Request, current_user: dict = Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        # Check existence
        existing = db.execute(text("SELECT id FROM products WHERE id = :id"), {"id": id}).fetchone()
        if not existing:
            raise HTTPException(**http_error(404, "product_not_found"))

        # Check code uniqueness if changed
        dup = db.execute(text("SELECT id FROM products WHERE product_code = :code AND id != :id"),
                         {"code": product.item_code, "id": id}).fetchone()
        if dup:
            raise HTTPException(status_code=400, detail="كود المنتج مستخدم بالفعل لمنتج آخر")

        # Resolve unit_id
        unit_id = db.execute(
            text("SELECT id FROM product_units WHERE unit_name = :unit OR unit_name_en = :unit LIMIT 1"),
            {"unit": product.unit}
        ).scalar()

        # If unit not found, use default or the first one
        if not unit_id:
            unit_id = db.execute(text("SELECT id FROM product_units LIMIT 1")).scalar()

        sql = """
            UPDATE products SET
                product_code = :code,
                product_name = :name,
                product_name_en = :name_en,
                product_type = :type,
                unit_id = :unit_id,
                selling_price = :sell,
                cost_price = :buy,
                last_purchase_price = :last,
                tax_rate = :tax,
                description = :desc,
                category_id = :cat,
                is_active = :active,
                has_batch_tracking = :hbt,
                has_serial_tracking = :hst,
                has_expiry_tracking = :het,
                shelf_life_days = :sld,
                expiry_alert_days = :ead,
                updated_at = NOW()
            WHERE id = :id
        """

        params = {
            "id": id,
            "code": product.item_code,
            "name": product.item_name,
            "name_en": product.item_name_en,
            "type": product.item_type,
            "unit_id": unit_id,
            "sell": product.selling_price,
            "buy": product.buying_price,
            "last": product.last_buying_price,
            "tax": product.tax_rate,
            "desc": product.description,
            "cat": product.category_id,
            "active": product.is_active,
            "hbt": product.has_batch_tracking,
            "hst": product.has_serial_tracking,
            "het": product.has_expiry_tracking,
            "sld": product.shelf_life_days,
            "ead": product.expiry_alert_days
        }

        db.execute(text(sql), params)
        db.commit()

        # Format response
        cat_name = db.execute(text("SELECT category_name FROM product_categories WHERE id=:id"), {"id": product.category_id}).scalar()

        # Get current stock
        stock = db.execute(text("""
            SELECT COALESCE(quantity, 0) FROM inventory 
            WHERE product_id = :id AND warehouse_id = (SELECT id FROM warehouses WHERE is_default = TRUE LIMIT 1)
        """), {"id": id}).scalar() or 0.0

        # AUDIT LOG
        log_activity(
            db,
            user_id=current_user.id,
            username=current_user.username,
            action="product.update",
            resource_type="product",
            resource_id=str(id),
            details={"name": product.item_name, "changes": product.model_dump()},
            request=request,
            branch_id=getattr(product, 'branch_id', None)
        )

        return {**product.model_dump(), "id": id, "category_name": cat_name, "current_stock": stock, "created_at": datetime.now()}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@products_router.delete("/products/{id}", dependencies=[Depends(require_permission("products.delete"))], response_model=Dict[str, Any])
def delete_product(
    id: int,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """حذف منتج"""
    db = get_db_connection(current_user.company_id)
    try:
        # Check existence
        product = db.execute(text("SELECT id, product_name FROM products WHERE id = :id"), {"id": id}).fetchone()
        if not product:
            raise HTTPException(**http_error(404, "product_not_found"))

        # Check if product has stock
        stock = db.execute(text("""
            SELECT COALESCE(SUM(quantity), 0) FROM inventory WHERE product_id = :id
        """), {"id": id}).scalar()

        if stock and stock > 0:
            raise HTTPException(status_code=400, detail="لا يمكن حذف منتج له رصيد في المخزون")

        # Check if product is used in any transactions
        usage = db.execute(text("""
            SELECT COUNT(*) FROM (
                SELECT 1 FROM invoice_lines WHERE product_id = :id
                UNION ALL
                SELECT 1 FROM purchase_order_lines WHERE product_id = :id
            ) AS usage
        """), {"id": id}).scalar()

        if usage and usage > 0:
            raise HTTPException(status_code=400, detail="لا يمكن حذف منتج مستخدم في معاملات سابقة")

        # Delete inventory records
        db.execute(text("DELETE FROM inventory WHERE product_id = :id"), {"id": id})

        # Delete product
        db.execute(text("DELETE FROM products WHERE id = :id"), {"id": id})
        db.commit()

        # AUDIT LOG
        log_activity(
            db,
            user_id=current_user.id,
            username=current_user.username,
            action="product.delete",
            resource_type="product",
            resource_id=str(id),
            details={"name": product.product_name},
            request=request,
            branch_id=None
        )

        return {"message": "تم حذف المنتج بنجاح"}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
