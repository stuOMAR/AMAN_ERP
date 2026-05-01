"""
Inventory Module - Categories CRUD
"""

from fastapi import APIRouter, Depends, HTTPException, status
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.audit import log_activity
from utils.permissions import require_permission
from schemas import CategoryCreate, CategoryResponse
from fastapi import Request

categories_router = APIRouter()
logger = logging.getLogger(__name__)


@categories_router.get("/categories", response_model=List[CategoryResponse], dependencies=[Depends(require_permission("products.view"))])
def list_categories(
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    db = get_db_connection(current_user.company_id)
    try:
        query = "SELECT id, category_name as name, category_code as code, branch_id FROM product_categories WHERE 1=1"
        params = {}
        if branch_id:
            query += " AND (branch_id = :bid OR branch_id IS NULL)"
            params["bid"] = branch_id
        else:
            # INV-011: Enforce allowed_branches when no branch_id specified
            allowed = getattr(current_user, 'allowed_branches', []) or []
            if allowed and "*" not in getattr(current_user, 'permissions', []):
                query += " AND (branch_id IN :branches OR branch_id IS NULL)"
                params["branches"] = tuple(allowed)

        query += " ORDER BY id"
        result = db.execute(text(query), params).fetchall()
        return [{"id": r.id, "name": r.name, "code": r.code, "branch_id": r.branch_id} for r in result]
    finally:
        db.close()


@categories_router.get("/categories/next-code", dependencies=[Depends(require_permission("products.create"))], response_model=Dict[str, Any])
def get_next_category_code(current_user: dict = Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        result = db.execute(text("SELECT category_code FROM product_categories WHERE category_code LIKE 'CAT%' ORDER BY category_code DESC LIMIT 1")).scalar()

        if result:
            try:
                last_num = int(result.replace("CAT", ""))
                next_num = last_num + 1
            except ValueError:
                next_num = 1
        else:
            next_num = 1

        return {"next_code": f"CAT{next_num:03d}"}
    finally:
        db.close()


@categories_router.post("/categories", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("products.create"))])
def create_category(
    category: CategoryCreate, 
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    db = get_db_connection(current_user.company_id)
    try:
        # Check duplicate code
        exists = db.execute(text("SELECT 1 FROM product_categories WHERE category_code = :code"), {"code": category.code}).scalar()
        if exists:
            raise HTTPException(status_code=400, detail="كود الفئة موجود مسبقاً")

        result = db.execute(text("""
            INSERT INTO product_categories (category_name, category_code, branch_id) 
            VALUES (:name, :code, :branch_id) RETURNING id
        """), {
            "name": category.name,
            "code": category.code,
            "branch_id": category.branch_id
        }).fetchone()
        db.commit()

        log_activity(
            db,
            user_id=current_user.id,
            username=current_user.username,
            action="inventory.category.create",
            resource_type="category",
            resource_id=str(result[0]),
            details={"name": category.name, "code": category.code},
            request=request
        )

        return {**category.model_dump(), "id": result[0]}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@categories_router.put("/categories/{id}", response_model=CategoryResponse, dependencies=[Depends(require_permission("products.edit"))])
def update_category(
    id: int, 
    category: CategoryCreate, 
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    db = get_db_connection(current_user.company_id)
    try:
        exists = db.execute(text("SELECT id FROM product_categories WHERE id = :id"), {"id": id}).scalar()
        if not exists:
            raise HTTPException(**http_error(404, "category_not_found"))

        db.execute(text("""
            UPDATE product_categories SET category_name = :name, category_code = :code
            WHERE id = :id
        """), {"name": category.name, "code": category.code, "id": id})
        db.commit()

        log_activity(
            db,
            user_id=current_user.id,
            username=current_user.username,
            action="inventory.category.update",
            resource_type="category",
            resource_id=str(id),
            details={"name": category.name, "code": category.code},
            request=request
        )

        return {**category.model_dump(), "id": id}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@categories_router.delete("/categories/{id}", dependencies=[Depends(require_permission("products.delete"))], response_model=Dict[str, Any])
def delete_category(
    id: int, 
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    db = get_db_connection(current_user.company_id)
    try:
        # INV-008: Check existence
        cat = db.execute(text("SELECT id FROM product_categories WHERE id = :id"), {"id": id}).fetchone()
        if not cat:
            raise HTTPException(**http_error(404, "category_not_found"))

        # INV-008: Check for linked products before deletion
        product_count = db.execute(text("SELECT COUNT(*) FROM products WHERE category_id = :id"), {"id": id}).scalar()
        if product_count and product_count > 0:
            raise HTTPException(status_code=400, detail=f"لا يمكن حذف الفئة لأنها مرتبطة بـ {product_count} منتج")

        db.execute(text("DELETE FROM product_categories WHERE id = :id"), {"id": id})
        db.commit()

        log_activity(
            db,
            user_id=current_user.id,
            username=current_user.username,
            action="inventory.category.delete",
            resource_type="category",
            resource_id=str(id),
            details=None,
            request=request
        )

        return {"message": "top deleted"}
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
