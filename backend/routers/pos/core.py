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

def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')

def get_db(current_user: UserResponse = Depends(get_current_user)):
    yield from get_company_db(current_user.company_id)

router = APIRouter(prefix="/pos", tags=["Point of Sale"], dependencies=[Depends(require_module("pos"))])

# --- Endpoints ---

def _get_populated_session(db: Session, session_id: int, current_user_id: int):
    query = text("""
        SELECT s.*, w.warehouse_name, u.full_name as cashier_name
        FROM pos_sessions s
        LEFT JOIN warehouses w ON s.warehouse_id = w.id
        LEFT JOIN company_users u ON s.user_id = u.id
        WHERE s.id = :sid
    """)
    session_row = db.execute(query, {"sid": session_id}).fetchone()
    
    if not session_row:
        return None
        
    session_data = dict(session_row._mapping)
    
    # Calculate totals from orders and payments
    # Total Sales (Paid orders)
    sales = db.execute(text("""
        SELECT COALESCE(SUM(total_amount), 0) 
        FROM pos_orders 
        WHERE session_id = :sid AND status = 'paid'
    """), {"sid": session_id}).scalar() or 0
    
    # Total Cash Payments
    cash = db.execute(text("""
        SELECT COALESCE(SUM(amount), 0) 
        FROM pos_payments 
        WHERE session_id = :sid AND payment_method = 'cash'
    """), {"sid": session_id}).scalar() or 0
    
    # Total Bank/Other Payments
    bank = db.execute(text("""
        SELECT COALESCE(SUM(amount), 0) 
        FROM pos_payments 
        WHERE session_id = :sid AND payment_method != 'cash'
    """), {"sid": session_id}).scalar() or 0
    
    # Total Returns (processed during this session)
    try:
        returns = db.execute(text("""
            SELECT COALESCE(SUM(refund_amount), 0) 
            FROM pos_returns 
            WHERE session_id = :sid
        """), {"sid": session_id}).scalar() or 0
    except Exception:
        db.rollback()
        returns = 0
    
    # Total Cash Returns (processed during this session)
    try:
        returns_cash = db.execute(text("""
            SELECT COALESCE(SUM(refund_amount), 0) 
            FROM pos_returns 
            WHERE session_id = :sid AND refund_method = 'cash'
        """), {"sid": session_id}).scalar() or 0
    except Exception:
        db.rollback()
        returns_cash = 0
    
    # Order count in this session
    order_count = db.execute(text("""
        SELECT COUNT(*) FROM pos_orders WHERE session_id = :sid
    """), {"sid": session_id}).scalar() or 0
    
    session_data['total_sales'] = str(_dec(sales).quantize(_D2, ROUND_HALF_UP))
    session_data['total_cash'] = str(_dec(cash).quantize(_D2, ROUND_HALF_UP))
    session_data['total_bank'] = str(_dec(bank).quantize(_D2, ROUND_HALF_UP))
    session_data['total_returns'] = str(_dec(returns).quantize(_D2, ROUND_HALF_UP))
    session_data['total_returns_cash'] = str(_dec(returns_cash).quantize(_D2, ROUND_HALF_UP))
    session_data['order_count'] = int(order_count)
    
    return session_data

@router.get("/warehouses", dependencies=[Depends(require_permission("pos.view"))], response_model=List[Dict[str, Any]])
def get_pos_warehouses(
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get warehouses for POS - no special permissions needed"""
    try:
        stmt = """
            SELECT w.id, w.warehouse_name as name, w.warehouse_code as code,
                   w.branch_id, COALESCE(b.branch_name, '') as branch_name
            FROM warehouses w
            LEFT JOIN branches b ON w.branch_id = b.id
            WHERE w.is_active = TRUE
        """
        params = {}
        
        # Filter by allowed branches if not admin
        if current_user.role != 'admin' and current_user.allowed_branches:
            stmt += " AND w.branch_id = ANY(:branches)"
            params["branches"] = current_user.allowed_branches
            
        stmt += " ORDER BY w.id"
        
        result = db.execute(text(stmt), params).fetchall()
        return [{"id": r.id, "name": r.name, "code": r.code, "branch_id": r.branch_id, "branch_name": r.branch_name} for r in result]
    except Exception:
        raise HTTPException(**http_error(500, "internal_error"))


@router.get("/products", response_model=List[POSProductResponse], dependencies=[Depends(require_permission("pos.view"))])

def get_pos_products(
    warehouse_id: Optional[int] = None,
    category_id: Optional[int] = None,
    search: Optional[str] = None,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # 1. Validate warehouse if provided
    if warehouse_id:
        wh_branch = db.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": warehouse_id}).scalar()
        if wh_branch:
            validate_branch_access(current_user, wh_branch)
            
    params = {}
    where_clauses = ["p.is_active = TRUE"]
    
    # 2. If no warehouse provided, filter products by allowed branches if restricted
    branch_filter = ""
    if not warehouse_id and current_user.role != 'admin' and current_user.allowed_branches:
        branch_filter = " AND i.warehouse_id IN (SELECT id FROM warehouses WHERE branch_id = ANY(:branches))"
        params["branches"] = current_user.allowed_branches

    query = f"""
        SELECT 
            p.id, p.product_name as name, p.product_code as code, p.barcode,
            p.selling_price as price, p.image_url, p.category_id,
            p.tax_rate,
            COALESCE(i.quantity, 0) as stock_quantity
        FROM products p
        LEFT JOIN inventory i ON p.id = i.product_id {branch_filter}
    """
    
    if warehouse_id:
        where_clauses.append("i.warehouse_id = :wh")
        params["wh"] = warehouse_id
        
    if category_id:
        where_clauses.append("p.category_id = :cat")
        params["cat"] = category_id
        
    if search:
        where_clauses.append("(p.product_name ILIKE :search OR p.barcode ILIKE :search OR p.product_code ILIKE :search)")
        params["search"] = f"%{search}%"
    
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)
        
    # Limit results for performance if no specific search
    if not search:
        query += " LIMIT 200"
        
    results = db.execute(text(query), params).fetchall()
    return [dict(row._mapping) for row in results]

