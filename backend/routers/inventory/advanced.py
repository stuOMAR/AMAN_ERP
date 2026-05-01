"""
Advanced Inventory Features Router - Phase 2
INV-106: Product Variants
INV-107: Bin Locations  
INV-108: Product Kits
INV-109: FIFO/LIFO Costing Policies
INV-110: Product Ledger
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from database import get_db_connection
from routers.auth import get_current_user
from utils.audit import log_activity
import logging
logger = logging.getLogger(__name__)

advanced_router = APIRouter(prefix="/advanced", tags=["Advanced Inventory Phase 2"])


# ==================== SCHEMAS ====================

# Product Variants (INV-106)
class VariantOptionCreate(BaseModel):
    attribute_name: str
    option_value: str

class ProductVariantCreate(BaseModel):
    product_id: int
    variant_sku: str
    variant_name: Optional[str] = None
    options: List[VariantOptionCreate]
    additional_cost: Optional[float] = 0
    additional_price: Optional[float] = 0

class ProductVariantUpdate(BaseModel):
    variant_sku: Optional[str] = None
    variant_name: Optional[str] = None
    additional_cost: Optional[float] = None
    additional_price: Optional[float] = None
    is_active: Optional[bool] = None


# Bin Locations (INV-107)
class BinLocationCreate(BaseModel):
    warehouse_id: int
    aisle: str
    rack: str
    shelf: str
    bin: str
    location_type: Optional[str] = 'storage'
    capacity: Optional[float] = None
    is_active: Optional[bool] = True

class BinLocationUpdate(BaseModel):
    aisle: Optional[str] = None
    rack: Optional[str] = None
    shelf: Optional[str] = None
    bin: Optional[str] = None
    location_type: Optional[str] = None
    capacity: Optional[float] = None
    is_active: Optional[bool] = None


# Product Kits (INV-108)
class KitComponentCreate(BaseModel):
    component_product_id: int
    quantity: float

class ProductKitCreate(BaseModel):
    kit_product_id: int
    components: List[KitComponentCreate]
    assembly_cost: Optional[float] = 0
    notes: Optional[str] = None

class ProductKitUpdate(BaseModel):
    assembly_cost: Optional[float] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


# ==================== PRODUCT VARIANTS (INV-106) ====================

@advanced_router.get("/variants", response_model=Dict[str, Any])
async def list_variants(
    product_id: Optional[int] = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
    current_user: dict = Depends(get_current_user)
):
    db = get_db_connection(current_user.company_id)
    try:
        conditions = []
        params = {}
        if product_id:
            conditions.append("pv.product_id = :product_id")
            params["product_id"] = product_id
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        
        query = text(f"""
            SELECT pv.*, p.product_name, p.product_code
            FROM product_variants pv
            JOIN products p ON p.id = pv.product_id
            {where}
            ORDER BY pv.id DESC
            LIMIT :limit OFFSET :offset
        """)
        params["limit"] = limit
        params["offset"] = offset
        result = db.execute(query, params)
        rows = [dict(r._mapping) for r in result]
        
        # Get attributes for each variant
        for row in rows:
            attrs_result = db.execute(text("""
                SELECT attribute_name, attribute_value
                FROM product_variant_attributes
                WHERE variant_id = :vid
            """), {"vid": row["id"]})
            row["attributes"] = [dict(r._mapping) for r in attrs_result]
        
        return {"data": rows, "total": len(rows)}
    except Exception as e:
        if "does not exist" in str(e):
            return {"data": [], "total": 0, "message": "Table not migrated yet"}
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@advanced_router.post("/variants", response_model=Dict[str, Any])
async def create_variant(data: ProductVariantCreate, request: Request, current_user: dict = Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        result = db.execute(text("""
            INSERT INTO product_variants (product_id, variant_sku, variant_name, additional_cost, additional_price, is_active)
            VALUES (:product_id, :variant_sku, :variant_name, :additional_cost, :additional_price, true)
            RETURNING id
        """), {
            "product_id": data.product_id, "variant_sku": data.variant_sku,
            "variant_name": data.variant_name, "additional_cost": data.additional_cost,
            "additional_price": data.additional_price
        })
        variant_id = result.fetchone()[0]
        
        for opt in data.options:
            db.execute(text("""
                INSERT INTO product_variant_attributes (variant_id, attribute_name, attribute_value)
                VALUES (:vid, :attr, :val)
            """), {"vid": variant_id, "attr": opt.attribute_name, "val": opt.option_value})
        
        db.commit()
        # INV-L03: Audit log
        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="variant.create", resource_type="product_variant",
                     resource_id=str(variant_id), details={"product_id": data.product_id, "sku": data.variant_sku}, request=request)
        return {"id": variant_id, "message": "Variant created successfully"}
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@advanced_router.put("/variants/{variant_id}", response_model=Dict[str, Any])
async def update_variant(variant_id: int, data: ProductVariantUpdate, request: Request, current_user: dict = Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        fields = []
        params = {"vid": variant_id}
        for field, value in data.dict(exclude_unset=True).items():
            fields.append(f"{field} = :{field}")
            params[field] = value
        if not fields:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        db.execute(text(f"UPDATE product_variants SET {', '.join(fields)} WHERE id = :vid"), params)
        db.commit()
        # INV-L03: Audit log
        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="variant.update", resource_type="product_variant",
                     resource_id=str(variant_id), details=data.dict(exclude_unset=True), request=request)
        return {"message": "Variant updated successfully"}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ==================== BIN LOCATIONS (INV-107) ====================

@advanced_router.get("/bins", response_model=Dict[str, Any])
async def list_bins(
    warehouse_id: Optional[int] = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
    current_user: dict = Depends(get_current_user)
):
    db = get_db_connection(current_user.company_id)
    try:
        conditions = []
        params = {}
        if warehouse_id:
            conditions.append("bl.warehouse_id = :warehouse_id")
            params["warehouse_id"] = warehouse_id
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        
        query = text(f"""
            SELECT bl.*, w.warehouse_name
            FROM bin_locations bl
            JOIN warehouses w ON w.id = bl.warehouse_id
            {where}
            ORDER BY bl.id DESC
            LIMIT :limit OFFSET :offset
        """)
        params["limit"] = limit
        params["offset"] = offset
        result = db.execute(query, params)
        rows = [dict(r._mapping) for r in result]
        return {"data": rows, "total": len(rows)}
    except Exception as e:
        if "does not exist" in str(e):
            return {"data": [], "total": 0, "message": "Table not migrated yet"}
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@advanced_router.post("/bins", response_model=Dict[str, Any])
async def create_bin(data: BinLocationCreate, request: Request, current_user: dict = Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        result = db.execute(text("""
            INSERT INTO bin_locations (warehouse_id, aisle, rack, shelf, bin, location_type, capacity, is_active)
            VALUES (:warehouse_id, :aisle, :rack, :shelf, :bin, :location_type, :capacity, :is_active)
            RETURNING id
        """), data.dict())
        bin_id = result.fetchone()[0]
        db.commit()
        # INV-L03: Audit log
        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="bin.create", resource_type="bin_location",
                     resource_id=str(bin_id), details={"warehouse_id": data.warehouse_id, "aisle": data.aisle, "rack": data.rack}, request=request)
        return {"id": bin_id, "message": "Bin location created successfully"}
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@advanced_router.put("/bins/{bin_id}", response_model=Dict[str, Any])
async def update_bin(bin_id: int, data: BinLocationUpdate, request: Request, current_user: dict = Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        fields = []
        params = {"bid": bin_id}
        for field, value in data.dict(exclude_unset=True).items():
            fields.append(f"{field} = :{field}")
            params[field] = value
        if not fields:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        db.execute(text(f"UPDATE bin_locations SET {', '.join(fields)} WHERE id = :bid"), params)
        db.commit()
        # INV-L03: Audit log
        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="bin.update", resource_type="bin_location",
                     resource_id=str(bin_id), details=data.dict(exclude_unset=True), request=request)
        return {"message": "Bin location updated successfully"}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ==================== PRODUCT KITS (INV-108) ====================

@advanced_router.get("/kits", response_model=Dict[str, Any])
async def list_kits(
    limit: int = Query(100, le=500),
    offset: int = 0,
    current_user: dict = Depends(get_current_user)
):
    db = get_db_connection(current_user.company_id)
    try:
        result = db.execute(text("""
            SELECT pk.*, p.product_name, p.product_code
            FROM product_kits pk
            JOIN products p ON p.id = pk.kit_product_id
            ORDER BY pk.id DESC
            LIMIT :limit OFFSET :offset
        """), {"limit": limit, "offset": offset})
        rows = [dict(r._mapping) for r in result]
        return {"data": rows, "total": len(rows)}
    except Exception as e:
        if "does not exist" in str(e):
            return {"data": [], "total": 0, "message": "Table not migrated yet"}
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@advanced_router.get("/kits/{kit_id}", response_model=Dict[str, Any])
async def get_kit(kit_id: int, current_user: dict = Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        result = db.execute(text("""
            SELECT pk.*, p.product_name, p.product_code
            FROM product_kits pk
            JOIN products p ON p.id = pk.kit_product_id
            WHERE pk.id = :kit_id
        """), {"kit_id": kit_id})
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Kit not found")
        
        kit = dict(row._mapping)
        items = db.execute(text("""
            SELECT pki.*, p.product_name, p.product_code
            FROM product_kit_items pki
            JOIN products p ON p.id = pki.component_product_id
            WHERE pki.kit_id = :kit_id
        """), {"kit_id": kit_id})
        kit["components"] = [dict(r._mapping) for r in items]
        return kit
    except HTTPException:
        raise
    except Exception as e:
        if "does not exist" in str(e):
            raise HTTPException(status_code=404, detail="Table not migrated yet")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@advanced_router.post("/kits", response_model=Dict[str, Any])
async def create_kit(data: ProductKitCreate, request: Request, current_user: dict = Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        result = db.execute(text("""
            INSERT INTO product_kits (kit_product_id, assembly_cost, notes, is_active)
            VALUES (:kit_product_id, :assembly_cost, :notes, true)
            RETURNING id
        """), {"kit_product_id": data.kit_product_id, "assembly_cost": data.assembly_cost, "notes": data.notes})
        kit_id = result.fetchone()[0]
        
        for comp in data.components:
            db.execute(text("""
                INSERT INTO product_kit_items (kit_id, component_product_id, quantity)
                VALUES (:kit_id, :cpid, :qty)
            """), {"kit_id": kit_id, "cpid": comp.component_product_id, "qty": comp.quantity})
        
        db.commit()
        # INV-L03: Audit log
        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="kit.create", resource_type="product_kit",
                     resource_id=str(kit_id), details={"kit_product_id": data.kit_product_id, "components": len(data.components)}, request=request)
        return {"id": kit_id, "message": "Kit created successfully"}
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@advanced_router.put("/kits/{kit_id}", response_model=Dict[str, Any])
async def update_kit(kit_id: int, data: ProductKitUpdate, request: Request, current_user: dict = Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        fields = []
        params = {"kid": kit_id}
        for field, value in data.dict(exclude_unset=True).items():
            fields.append(f"{field} = :{field}")
            params[field] = value
        if not fields:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        db.execute(text(f"UPDATE product_kits SET {', '.join(fields)} WHERE id = :kid"), params)
        db.commit()
        # INV-L03: Audit log
        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="kit.update", resource_type="product_kit",
                     resource_id=str(kit_id), details=data.dict(exclude_unset=True), request=request)
        return {"message": "Kit updated successfully"}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ==================== COSTING POLICIES (INV-109) ====================

@advanced_router.get("/costing-policies", response_model=Dict[str, Any])
async def list_costing_policies():
    """Get available costing policies"""
    return {
        "policies": [
            {"code": "WAC", "name": "Weighted Average Cost", "name_ar": "المتوسط المرجح", "description": "Default. Cost = total value / total qty"},
            {"code": "FIFO", "name": "First In First Out", "name_ar": "الوارد أولاً صادر أولاً", "description": "Oldest inventory sold first"},
            {"code": "LIFO", "name": "Last In First Out", "name_ar": "الوارد أخيراً صادر أولاً", "description": "Newest inventory sold first"},
            {"code": "SPECIFIC", "name": "Specific Identification", "name_ar": "التحديد العيني", "description": "Track cost of each individual item"},
        ]
    }


# ==================== PRODUCT LEDGER (INV-110) ====================

@advanced_router.get("/ledger", response_model=Dict[str, Any])
async def get_product_ledger(
    product_id: int = Query(...),
    warehouse_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
    current_user: dict = Depends(get_current_user)
):
    """Get product ledger (كشف حساب المنتج) with running balance"""
    db = get_db_connection(current_user.company_id)
    try:
        conditions = ["it.product_id = :product_id"]
        params = {"product_id": product_id, "limit": limit, "offset": offset}
        
        if warehouse_id:
            conditions.append("it.warehouse_id = :warehouse_id")
            params["warehouse_id"] = warehouse_id
        if start_date:
            conditions.append("it.created_at >= :start_date")
            params["start_date"] = start_date
        if end_date:
            conditions.append("it.created_at <= :end_date")
            params["end_date"] = end_date
        
        where = "WHERE " + " AND ".join(conditions)
        
        result = db.execute(text(f"""
            SELECT it.*, w.warehouse_name, p.product_name, p.product_code
            FROM inventory_transactions it
            JOIN warehouses w ON w.id = it.warehouse_id
            JOIN products p ON p.id = it.product_id
            {where}
            ORDER BY it.created_at ASC
            LIMIT :limit OFFSET :offset
        """), params)
        rows = [dict(r._mapping) for r in result]
        
        # Calculate running balance
        running_balance = 0
        for row in rows:
            qty = abs(float(row.get("quantity", 0)))
            tx_type = row.get("transaction_type", "")
            
            if tx_type in ("receipt", "initial", "adjustment_in", "return_in", "transfer_in", "stock_in", "production_in"):
                running_balance += qty
                row["qty_in"] = qty
                row["qty_out"] = 0
            else:
                running_balance -= qty
                row["qty_in"] = 0
                row["qty_out"] = qty
            
            row["running_balance"] = running_balance

        count_result = db.execute(text(f"SELECT COUNT(*) FROM inventory_transactions it {where}"), params)
        total = count_result.scalar()
        
        return {"data": rows, "total": total}
    except Exception:
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()