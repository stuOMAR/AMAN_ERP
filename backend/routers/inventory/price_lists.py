"""
Inventory Module - Price Lists CRUD
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List
import logging

from database import get_db_connection, get_system_db
from routers.auth import get_current_user
from utils.audit import log_activity
from utils.permissions import require_permission
from .schemas import PriceListCreate, PriceListItemUpdate

price_lists_router = APIRouter()
logger = logging.getLogger(__name__)


@price_lists_router.get("/price-lists", response_model=List[dict], dependencies=[Depends(require_permission("stock.view"))])
def list_price_lists(current_user: dict = Depends(get_current_user)):
    """عرض قوائم الأسعار"""
    db = get_db_connection(current_user.company_id)
    try:
        result = db.execute(text("""
            SELECT id, price_list_name as name, currency, 
                   (status = 'active') as is_active, is_default 
            FROM customer_price_lists 
            ORDER BY id
        """)).fetchall()
        return [dict(row._mapping) for row in result]
    finally:
        db.close()


@price_lists_router.post("/price-lists", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("products.create"))], response_model=Dict[str, Any])
def create_price_list(data: PriceListCreate, current_user: dict = Depends(get_current_user)):
    """إنشاء قائمة أسعار جديدة"""

    # Fetch Company Currency
    sys_db = get_system_db()
    company_currency = None
    try:
        res = sys_db.execute(text("SELECT currency FROM system_companies WHERE id = :id"), {"id": current_user.company_id}).scalar()
        if res:
            company_currency = res
    except Exception as e:
        logger.warning(f"Could not fetch company currency: {e}")
    finally:
        sys_db.close()

    db = get_db_connection(current_user.company_id)
    try:
        if data.is_default:
            db.execute(text("UPDATE customer_price_lists SET is_default = FALSE"))

        import uuid
        code = f"PL-{str(uuid.uuid4())[:8]}"
        status_str = "active" if data.is_active else "inactive"

        result = db.execute(text("""
            INSERT INTO customer_price_lists (
                price_list_code, price_list_name, currency, status, is_default
            )
            VALUES (:code, :name, :curr, :status, :default)
            RETURNING id
        """), {
            "code": code, "name": data.name, "curr": company_currency,
            "status": status_str, "default": data.is_default
        }).fetchone()

        db.commit()
        return {"id": result[0], "message": "تم إنشاء القائمة بنجاح", "currency": company_currency}
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@price_lists_router.put("/price-lists/{id}", dependencies=[Depends(require_permission("products.edit"))], response_model=Dict[str, Any])
def update_price_list(
    id: int,
    data: PriceListCreate,
    current_user: dict = Depends(get_current_user)
):
    """تحديث قائمة أسعار"""
    db = get_db_connection(current_user.company_id)
    try:
        existing = db.execute(text("SELECT id FROM customer_price_lists WHERE id = :id"), {"id": id}).fetchone()
        if not existing:
            raise HTTPException(**http_error(404, "price_list_not_found"))

        if data.is_default:
            db.execute(text("UPDATE customer_price_lists SET is_default = FALSE WHERE id != :id"), {"id": id})

        status_str = "active" if data.is_active else "inactive"

        db.execute(text("""
            UPDATE customer_price_lists SET
                price_list_name = :name,
                status = :status,
                is_default = :default,
                updated_at = NOW()
            WHERE id = :id
        """), {
            "id": id,
            "name": data.name,
            "status": status_str,
            "default": data.is_default
        })

        db.commit()
        return {"id": id, "message": "تم تحديث القائمة بنجاح"}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@price_lists_router.delete("/price-lists/{id}", dependencies=[Depends(require_permission("products.delete"))], response_model=Dict[str, Any])
def delete_price_list(
    id: int,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """حذف قائمة أسعار"""
    db = get_db_connection(current_user.company_id)
    try:
        price_list = db.execute(text("SELECT id, price_list_name FROM customer_price_lists WHERE id = :id"), {"id": id}).fetchone()
        if not price_list:
            raise HTTPException(**http_error(404, "price_list_not_found"))

        # Check if it's used by any customers
        usage = db.execute(text("SELECT COUNT(*) FROM parties WHERE price_list_id = :id"), {"id": id}).scalar()
        if usage and usage > 0:
            raise HTTPException(status_code=400, detail="لا يمكن حذف قائمة أسعار مستخدمة من قبل عملاء")

        # Delete price list items first
        db.execute(text("DELETE FROM customer_price_list_items WHERE price_list_id = :id"), {"id": id})

        # Delete price list
        db.execute(text("DELETE FROM customer_price_lists WHERE id = :id"), {"id": id})
        db.commit()

        # AUDIT LOG
        log_activity(
            db,
            user_id=current_user.id,
            username=current_user.username,
            action="price_list.delete",
            resource_type="price_list",
            resource_id=str(id),
            details={"name": price_list.price_list_name},
            request=request,
            branch_id=None
        )

        return {"message": "تم حذف قائمة الأسعار بنجاح"}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@price_lists_router.get("/price-lists/{id}/items", response_model=List[dict], dependencies=[Depends(require_permission("stock.view"))])
def get_price_list_items(id: int, current_user: dict = Depends(get_current_user)):
    """جلب أسعار المنتجات في قائمة محددة"""
    db = get_db_connection(current_user.company_id)
    try:
        query = """
            SELECT p.id as product_id, p.product_name, p.product_code, 
                   COALESCE(pp.price, 0) as price
            FROM products p
            LEFT JOIN customer_price_list_items pp ON p.id = pp.product_id AND pp.price_list_id = :list_id
            WHERE p.is_active = TRUE
            ORDER BY p.product_name
        """
        result = db.execute(text(query), {"list_id": id}).fetchall()
        return [dict(row._mapping) for row in result]
    finally:
        db.close()


@price_lists_router.post("/price-lists/{id}/items", dependencies=[Depends(require_permission("stock.manage"))], response_model=Dict[str, Any])
def update_price_list_items(
    id: int,
    items: List[PriceListItemUpdate],
    current_user: dict = Depends(get_current_user)
):
    """تحديث أسعار المنتجات في القائمة"""
    db = get_db_connection(current_user.company_id)
    try:
        for item in items:
            exists = db.execute(text("""
                SELECT 1 FROM customer_price_list_items 
                WHERE price_list_id = :lid AND product_id = :pid
            """), {"lid": id, "pid": item.product_id}).scalar()

            if exists:
                db.execute(text("""
                    UPDATE customer_price_list_items SET price = :price 
                    WHERE price_list_id = :lid AND product_id = :pid
                """), {"lid": id, "pid": item.product_id, "price": item.price})
            else:
                db.execute(text("""
                    INSERT INTO customer_price_list_items (price_list_id, product_id, price)
                    VALUES (:lid, :pid, :price)
                """), {"lid": id, "pid": item.product_id, "price": item.price})

        db.commit()
        return {"message": "تم تحديث الأسعار بنجاح"}
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
