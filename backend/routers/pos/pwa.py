"""pos sub-router — split from monolithic pos.py (T6.3).

Mounted under the parent router via pos/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import logging
from database import get_company_db
from routers.auth import get_current_user
from utils.permissions import require_permission, validate_branch_access, require_module
from utils.fiscal_lock import check_fiscal_period_open
from utils.audit import log_activity
from schemas import UserResponse
from schemas.pos import SessionCreate, SessionClose, SessionResponse, POSProductResponse, OrderCreate, OrderResponse, ReturnCreate
from services.gl_service import create_journal_entry as gl_create_journal_entry

logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')
def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')

def get_db(current_user: UserResponse = Depends(get_current_user)):
    yield from get_company_db(current_user.company_id)

router = APIRouter()

from .core import _D2, _D4

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
def get_pwa_config(current_user: UserResponse = Depends(get_current_user)):
    """PWA offline config - cached products and settings"""
    db = get_company_db(current_user.company_id)
    try:
        products = db.execute(text("""
            SELECT id, name, name_ar, sku, sale_price, tax_rate, category_id, unit_id, barcode
            FROM products WHERE is_active = TRUE
            ORDER BY name LIMIT 5000
        """)).fetchall()
        tax_rates = db.execute(text("SELECT * FROM tax_rates WHERE is_active = TRUE")).fetchall()
        payment_methods = db.execute(text(
            "SELECT * FROM pos_payment_methods WHERE is_active = TRUE ORDER BY sort_order"
        )).fetchall()
        return {
            "products": [dict(r._mapping) for r in products],
            "tax_rates": [dict(r._mapping) for r in tax_rates],
            "payment_methods": [dict(r._mapping) for r in payment_methods],
            "cache_version": __import__('time').time()
        }
    except Exception as e:
        logger.error(f"Error loading PWA config: {e}")
        return {"products": [], "tax_rates": [], "payment_methods": [], "error": "Failed to load configuration"}
    finally:
        db.close()
