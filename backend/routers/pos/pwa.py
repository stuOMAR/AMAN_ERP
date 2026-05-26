"""pos sub-router — split from monolithic pos.py (T6.3).

Mounted under the parent router via pos/__init__.py.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Any, Dict, Optional
from decimal import Decimal
import logging
from database import get_company_db
from routers.auth import get_current_user
from utils.permissions import branch_scope_filter_from_scope, resolve_branch_scope
from schemas import UserResponse

logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')
def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')

def get_db(current_user: UserResponse = Depends(get_current_user)):
    yield from get_company_db(current_user.company_id)

router = APIRouter()


@router.get("/pwa/manifest", response_model=Dict[str, Any])
def get_pwa_manifest(current_user: UserResponse = Depends(get_current_user)):
    """PWA manifest for POS offline support"""
    return {
        "name": "نقاط البيع - أمان ERP",
        "short_name": "POS",
        "description": "نظام نقاط البيع",
        "start_url": "/pos",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#1a73e8",
        "orientation": "any",
        "icons": [
            {"src": "/icons/pos-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icons/pos-512.png", "sizes": "512x512", "type": "image/png"}
        ],
        "categories": ["business", "finance"],
        "lang": "ar",
        "dir": "rtl"
    }


@router.get("/pwa/config", response_model=Dict[str, Any])
def get_pwa_config(
    branch_id: Optional[int] = None,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """PWA offline config - cached products and settings"""
    try:
        branch_scope = resolve_branch_scope(current_user, branch_id)
        product_params = {}
        product_branch_filter = branch_scope_filter_from_scope(branch_scope, "w.branch_id", product_params)
        product_scope_clause = ""
        if product_branch_filter:
            product_scope_clause = f"""
                AND EXISTS (
                    SELECT 1
                    FROM inventory i
                    JOIN warehouses w ON w.id = i.warehouse_id
                    WHERE i.product_id = products.id
                    {product_branch_filter}
                )
            """
        products = db.execute(text(f"""
            SELECT id, product_name as name, product_code as sku, selling_price as sale_price, tax_rate, category_id, barcode
            FROM products WHERE is_active = TRUE
            {product_scope_clause}
            ORDER BY product_name LIMIT 5000
        """), product_params).fetchall()
        tax_rates = db.execute(text("SELECT * FROM tax_rates WHERE is_active = TRUE")).fetchall()
        payment_methods = []
        try:
            payment_methods = db.execute(text(
                "SELECT * FROM pos_payment_methods WHERE is_active = TRUE ORDER BY sort_order"
            )).fetchall()
        except Exception:
            pass  # pos_payment_methods table may not exist
        return {
            "products": [dict(r._mapping) for r in products],
            "tax_rates": [dict(r._mapping) for r in tax_rates],
            "payment_methods": [dict(r._mapping) for r in payment_methods],
            "cache_version": __import__('time').time()
        }
    except Exception as e:
        logger.error(f"Error loading PWA config: {e}")
        return {"products": [], "tax_rates": [], "payment_methods": [], "error": "Failed to load configuration"}
