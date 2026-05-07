"""
Price Sync API
==============
Automatically updates branch prices when exchange rates change.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from typing import Optional

from database import get_db_connection
from routers.auth import get_current_user
from utils.permissions import require_permission

router = APIRouter(prefix="/price-sync", tags=["Price Sync"])


@router.post("/sync-from-base", dependencies=[Depends(require_permission(["products.edit", "sales.edit"]))])
def sync_prices_from_base(
    current_user: dict = Depends(get_current_user)
):
    """تحديث أسعار جميع الفروع من السعر الأساسي بالريال"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    db = get_db_connection(company_id)
    try:
        base_cur = db.execute(text("SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1")).scalar() or "SAR"
        
        # Get all active branches with their currencies
        branches = db.execute(text("""
            SELECT id, branch_name, default_currency FROM branches WHERE is_active = TRUE
        """)).fetchall()
        
        # Get base price list (default for base currency)
        base_pl = db.execute(text("""
            SELECT id FROM customer_price_lists 
            WHERE currency = :cur AND is_default = TRUE AND status = 'active'
            LIMIT 1
        """), {"cur": base_cur}).fetchone()
        
        if not base_pl:
            return {"message": "لا توجد قائمة أسعار أساسية", "updated": 0}
        
        # Get base prices
        base_items = db.execute(text("""
            SELECT product_id, price FROM customer_price_list_items 
            WHERE price_list_id = :plid
        """), {"plid": base_pl.id}).fetchall()
        
        total_updated = 0
        
        for branch in branches:
            if branch.default_currency == base_cur:
                continue  # Skip base currency branch
            
            # Get exchange rate
            rate = db.execute(text("""
                SELECT current_rate FROM currencies WHERE code = :code
            """), {"code": branch.default_currency}).scalar()
            
            if not rate:
                continue
            
            # Get or create price list for this branch
            pl = db.execute(text("""
                SELECT id FROM customer_price_lists 
                WHERE branch_id = :bid AND status = 'active' AND is_default = TRUE
                LIMIT 1
            """), {"bid": branch.id}).fetchone()
            
            if not pl:
                # Create new price list
                db.execute(text("""
                    INSERT INTO customer_price_lists 
                    (price_list_code, price_list_name, price_list_name_en, currency, branch_id, is_default, status)
                    VALUES (:code, :name, :name_en, :cur, :bid, TRUE, 'active')
                """), {
                    "code": f"PL-{branch.branch_name[:3].upper()}",
                    "name": f"أسعار {branch.branch_name}",
                    "name_en": f"Prices - {branch.branch_name}",
                    "cur": branch.default_currency,
                    "bid": branch.id
                })
                pl_id = db.execute(text("SELECT LASTVAL() as id"), {}).fetchone().id
            else:
                pl_id = pl.id
            
            # Update prices
            for item in base_items:
                new_price = round(float(item.price) * float(rate), 2)
                db.execute(text("""
                    INSERT INTO customer_price_list_items (price_list_id, product_id, price)
                    VALUES (:lid, :pid, :price)
                    ON CONFLICT (price_list_id, product_id) DO UPDATE SET price = :price
                """), {"lid": pl_id, "pid": item.product_id, "price": new_price})
                total_updated += 1
        
        db.commit()
        return {"message": f"تم تحديث {total_updated} سعر", "updated": total_updated}
    finally:
        db.close()


@router.post("/sync-single/{list_id}", dependencies=[Depends(require_permission(["products.edit", "sales.edit"]))])
def sync_single_price_list(
    list_id: int,
    current_user: dict = Depends(get_current_user)
):
    """تحديث قائمة أسعار واحدة من القائمة الأساسية"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    db = get_db_connection(company_id)
    try:
        base_cur = db.execute(text("SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1")).scalar() or "SAR"
        
        # Get target price list
        target_pl = db.execute(text("""
            SELECT id, currency, branch_id FROM customer_price_lists WHERE id = :id
        """), {"id": list_id}).fetchone()
        
        if not target_pl:
            raise HTTPException(status_code=404, detail="قائمة الأسعار غير موجودة")
        
        if target_pl.currency == base_cur:
            return {"message": "هذه القائمة بالعملة الأساسية - لا حاجة للتحديث"}
        
        # Get exchange rate
        rate = db.execute(text("""
            SELECT current_rate FROM currencies WHERE code = :code
        """), {"code": target_pl.currency}).scalar()
        
        if not rate:
            raise HTTPException(status_code=400, detail=f"لا يوجد سعر صرف لعملة {target_pl.currency}")
        
        # Get base price list
        base_pl = db.execute(text("""
            SELECT id FROM customer_price_lists 
            WHERE currency = :cur AND is_default = TRUE AND status = 'active'
            LIMIT 1
        """), {"cur": base_cur}).fetchone()
        
        if not base_pl:
            raise HTTPException(status_code=400, detail="لا توجد قائمة أسعار أساسية")
        
        # Get base prices
        base_items = db.execute(text("""
            SELECT product_id, price FROM customer_price_list_items 
            WHERE price_list_id = :plid
        """), {"plid": base_pl.id}).fetchall()
        
        # Update prices
        updated = 0
        for item in base_items:
            new_price = round(float(item.price) * float(rate), 2)
            db.execute(text("""
                INSERT INTO customer_price_list_items (price_list_id, product_id, price)
                VALUES (:lid, :pid, :price)
                ON CONFLICT (price_list_id, product_id) DO UPDATE SET price = :price
            """), {"lid": list_id, "pid": item.product_id, "price": new_price})
            updated += 1
        
        db.commit()
        return {"message": f"تم تحديث {updated} سعر", "updated": updated}
    finally:
        db.close()
