"""
Excel Price Import API
=====================
Allows branch managers to import prices from Excel files.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import text
from typing import Optional
import pandas as pd
import io

from database import get_db_connection
from routers.auth import get_current_user
from utils.permissions import require_permission

router = APIRouter(prefix="/price-lists", tags=["Price Lists"])


@router.get("", dependencies=[Depends(require_permission(["products.view", "sales.view"]))])
def list_price_lists(
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """جلب قوائم الأسعار مع فلتر الفرع"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    db = get_db_connection(company_id)
    try:
        query = """
            SELECT cpl.id, cpl.price_list_code, cpl.price_list_name, cpl.price_list_name_en,
                   cpl.currency, cpl.is_default, cpl.status, cpl.branch_id,
                   b.branch_name,
                   COUNT(cpli.id) as items_count
            FROM customer_price_lists cpl
            LEFT JOIN branches b ON cpl.branch_id = b.id
            LEFT JOIN customer_price_list_items cpli ON cpli.price_list_id = cpl.id
            WHERE cpl.status = 'active'
        """
        params = {}
        
        if branch_id:
            query += " AND (cpl.branch_id = :bid OR cpl.branch_id IS NULL)"
            params["bid"] = branch_id
        
        query += " GROUP BY cpl.id, cpl.price_list_code, cpl.price_list_name, cpl.price_list_name_en, cpl.currency, cpl.is_default, cpl.status, cpl.branch_id, b.branch_name"
        query += " ORDER BY cpl.is_default DESC, cpl.price_list_name"
        
        rows = db.execute(text(query), params).fetchall()
        return [dict(row._mapping) for row in rows]
    finally:
        db.close()


@router.get("/{list_id}", dependencies=[Depends(require_permission(["products.view", "sales.view"]))])
def get_price_list(
    list_id: int,
    current_user: dict = Depends(get_current_user)
):
    """جلب تفاصيل قائمة الأسعار مع المنتجات"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    db = get_db_connection(company_id)
    try:
        # Get price list
        pl = db.execute(text("""
            SELECT cpl.*, b.branch_name
            FROM customer_price_lists cpl
            LEFT JOIN branches b ON cpl.branch_id = b.id
            WHERE cpl.id = :id
        """), {"id": list_id}).fetchone()
        
        if not pl:
            raise HTTPException(**http_error(404, "price_list_not_found", request))
        
        # Get items
        items = db.execute(text("""
            SELECT cpli.id, cpli.product_id, cpli.price,
                   p.product_code, p.product_name, p.selling_price as default_price
            FROM customer_price_list_items cpli
            JOIN products p ON cpli.product_id = p.id
            WHERE cpli.price_list_id = :id
            ORDER BY p.product_name
        """), {"id": list_id}).fetchall()
        
        return {
            "id": pl.id,
            "code": pl.price_list_code,
            "name": pl.price_list_name,
            "name_en": pl.price_list_name_en,
            "currency": pl.currency,
            "branch_id": pl.branch_id,
            "branch_name": pl.branch_name,
            "is_default": pl.is_default,
            "status": pl.status,
            "items": [dict(row._mapping) for row in items]
        }
    finally:
        db.close()


@router.post("/{list_id}/items", dependencies=[Depends(require_permission(["products.edit", "sales.edit"]))])
def update_price_list_item(
    list_id: int,
    data: dict,
    current_user: dict = Depends(get_current_user)
):
    """تحديث سعر منتج في قائمة الأسعار"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    db = get_db_connection(company_id)
    try:
        product_id = data.get("product_id")
        price = data.get("price")
        
        if not product_id or price is None:
            raise HTTPException(**http_error(400, "product_id_و_price_مطلوبان", request))
        
        db.execute(text("""
            INSERT INTO customer_price_list_items (price_list_id, product_id, price)
            VALUES (:lid, :pid, :price)
            ON CONFLICT (price_list_id, product_id) DO UPDATE SET price = :price
        """), {"lid": list_id, "pid": product_id, "price": price})
        
        db.commit()
        return {"message": i18n_message(("price_updated_success", request))}
    finally:
        db.close()


@router.post("/{list_id}/import", dependencies=[Depends(require_permission(["products.edit", "sales.edit"]))])
async def import_prices_from_excel(
    list_id: int,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    """استيراد الأسعار من ملف Excel"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    db = get_db_connection(company_id)
    try:
        # Verify price list exists
        pl = db.execute(text("SELECT id, currency FROM customer_price_lists WHERE id = :id"), {"id": list_id}).fetchone()
        if not pl:
            raise HTTPException(**http_error(404, "price_list_not_found", request))
        
        # Read Excel file
        content = await file.read()
        df = pd.read_excel(io.BytesIO(content))
        
        # Expected columns: product_code, price
        required_cols = ['product_code', 'price']
        if not all(col in df.columns for col in required_cols):
            raise HTTPException(status_code=400, detail=i18n_message("file_must_contain_columns", request))
        
        updated = 0
        errors = []
        
        for _, row in df.iterrows():
            product_code = str(row['product_code']).strip()
            price = float(row['price'])
            
            # Get product ID
            product = db.execute(text("SELECT id FROM products WHERE product_code = :code"), {"code": product_code}).fetchone()
            if not product:
                errors.append(f"المنتج {product_code} غير موجود")
                continue
            
            # Update price
            db.execute(text("""
                INSERT INTO customer_price_list_items (price_list_id, product_id, price)
                VALUES (:lid, :pid, :price)
                ON CONFLICT (price_list_id, product_id) DO UPDATE SET price = :price
            """), {"lid": list_id, "pid": product.id, "price": price})
            updated += 1
        
        db.commit()
        return {"message": i18n_message("prices_bulk_updated", request), "errors": errors}
    finally:
        db.close()
