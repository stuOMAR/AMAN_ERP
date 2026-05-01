
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


from database import get_company_db
from routers.auth import get_current_user
from utils.permissions import require_permission, validate_branch_access, require_module
from utils.fiscal_lock import check_fiscal_period_open
from utils.audit import log_activity

from schemas import UserResponse
from schemas.pos import SessionCreate, SessionClose, SessionResponse, POSProductResponse, OrderCreate, OrderResponse, ReturnCreate
from services.gl_service import create_journal_entry as gl_create_journal_entry
from decimal import Decimal, ROUND_HALF_UP

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')
def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')

def get_db(current_user: UserResponse = Depends(get_current_user)):
    yield from get_company_db(current_user.company_id)

router = APIRouter(prefix="/pos", tags=["Point of Sale"], dependencies=[Depends(require_module("pos"))])

# --- Endpoints ---

@router.post("/sessions/open", response_model=SessionResponse, dependencies=[Depends(require_permission("pos.sessions"))])
def open_session(
    session_in: SessionCreate,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user_id = current_user.id
    
    # Validate branch access
    validate_branch_access(current_user, session_in.branch_id)
    
    # CONC-FIX: Use INSERT ... ON CONFLICT to prevent TOCTOU race condition.
    # A UNIQUE INDEX on (user_id) WHERE status='opened' must exist.
    # Fallback: check-then-insert inside a serialized read for environments without the index.
    existing_session = db.execute(
        text("SELECT id FROM pos_sessions WHERE user_id = :uid AND status = 'opened' FOR UPDATE SKIP LOCKED"),
        {"uid": user_id}
    ).fetchone()
    
    if existing_session:
        raise HTTPException(status_code=400, detail="User already has an open session")
    
    # Create new session
    # Generate session code
    import uuid
    session_code = f"SESS-{uuid.uuid4().hex[:8].upper()}"
    
    sql = text("""
        INSERT INTO pos_sessions (session_code, user_id, warehouse_id, opening_balance, status, branch_id, notes, treasury_account_id)
        VALUES (:code, :uid, :wh, :bal, 'opened', :branch, :notes, :tid)
        RETURNING id, session_code, user_id, warehouse_id, status, opened_at, opening_balance, closing_balance, total_sales, difference, treasury_account_id
    """)
    
    result = db.execute(sql, {
        "code": session_code,
        "uid": user_id,
        "wh": session_in.warehouse_id,
        "bal": session_in.opening_balance,
        "branch": session_in.branch_id,
        "notes": session_in.notes,
        "tid": session_in.treasury_account_id
    }).fetchone()
    
    db.commit()
    
    if not result:
        raise HTTPException(status_code=500, detail="Failed to create POS session")
    
    session_id = result._mapping["id"]

    log_activity(
        db, user_id=current_user.id, username=current_user.username,
        action="open_pos_session", resource_type="pos_session",
        resource_id=str(session_id),
        details={"branch_id": session_in.branch_id, "warehouse_id": session_in.warehouse_id, "opening_balance": str(session_in.opening_balance)},
        request=request, branch_id=session_in.branch_id
    )

    populated = _get_populated_session(db, session_id, user_id)
    if populated:
        return populated
    
    # Fallback: return basic data from INSERT result
    return dict(result._mapping)

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

@router.post("/sessions/{session_id}/close", response_model=SessionResponse, dependencies=[Depends(require_permission("pos.sessions"))])
def close_session(
    session_id: int,
    close_in: SessionClose,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    from utils.accounting import get_base_currency
    base_currency = get_base_currency(db)
    sess = db.execute(text("SELECT * FROM pos_sessions WHERE id = :id"), {"id": session_id}).fetchone()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
        
    # Validate branch access
    validate_branch_access(current_user, sess.branch_id)
    
    if sess.status != 'opened':
        raise HTTPException(status_code=400, detail="Session is not open")
        
    # Recalculate difference using actual data with safety for None values
    opening_bal = _dec(sess.opening_balance)
    sales_cash = db.execute(text("SELECT COALESCE(SUM(amount), 0) FROM pos_payments WHERE session_id = :id AND payment_method = 'cash'"), {"id": session_id}).scalar() or 0
    try:
        returns_cash = db.execute(text("SELECT COALESCE(SUM(refund_amount), 0) FROM pos_returns WHERE session_id = :id AND refund_method = 'cash'"), {"id": session_id}).scalar() or 0
    except Exception:
        db.rollback()
        returns_cash = 0
        # Re-fetch session after rollback
        sess = db.execute(text("SELECT * FROM pos_sessions WHERE id = :id"), {"id": session_id}).fetchone()

    # Expected cash should come from the close request, while cash_register_balance is actual count.
    # Keep computed cash flow available for future diagnostics.
    _ = (opening_bal + _dec(sales_cash) - _dec(returns_cash)).quantize(_D2, ROUND_HALF_UP)
    expected_cash = _dec(close_in.closing_balance).quantize(_D2, ROUND_HALF_UP)
    difference = (_dec(close_in.cash_register_balance) - expected_cash).quantize(_D2, ROUND_HALF_UP)
    
    # Build total_returns subquery safely (pos_returns may not exist)
    total_returns_sql = "0"
    try:
        db.execute(text("SELECT 1 FROM pos_returns LIMIT 0"))
        total_returns_sql = "(SELECT COALESCE(SUM(refund_amount), 0) FROM pos_returns WHERE session_id = :id)"
    except Exception:
        db.rollback()
    
    db.execute(text(f"""
        UPDATE pos_sessions
        SET status = 'closed',
            closed_at = CURRENT_TIMESTAMP,
            closing_balance = :close_bal,
            cash_register_balance = :reg_bal,
            difference = :diff,
            notes = :notes,
            total_sales = (SELECT COALESCE(SUM(total_amount), 0) FROM pos_orders WHERE session_id = :id AND status = 'paid'),
            total_returns = {total_returns_sql}
        WHERE id = :id
    """), {
        "close_bal": _dec(close_in.closing_balance).quantize(_D2, ROUND_HALF_UP),
        "reg_bal": _dec(close_in.cash_register_balance).quantize(_D2, ROUND_HALF_UP),
        "diff": difference,
        "notes": close_in.notes or "",
        "id": session_id
    })
    
    # FISCAL-LOCK: Reject if accounting period is closed
    check_fiscal_period_open(db, datetime.now().date())

    # Create Cash Over/Short GL Entry if there's a difference
    if abs(difference) > _D2:
        from utils.accounting import get_mapped_account_id
        acc_cash = get_mapped_account_id(db, "acc_map_cash_main")
        acc_over_short = get_mapped_account_id(db, "acc_map_cash_over_short") or get_mapped_account_id(db, "acc_map_expense_other")
        
        if acc_cash and acc_over_short:
            import random
            je_num = f"JE-POS-CLOSE-{session_id}-{random.randint(100,999)}"
            branch_id = db.execute(text("""
                SELECT w.branch_id FROM pos_sessions s 
                JOIN warehouses w ON s.warehouse_id = w.id 
                WHERE s.id = :id
            """), {"id": session_id}).scalar()
            
            diff_abs = abs(difference).quantize(_D2, ROUND_HALF_UP)
            lines_data = []
            if difference > 0:
                lines_data.append({"account_id": acc_cash, "debit": diff_abs, "credit": 0, "description": 'فائض صندوق'})
                lines_data.append({"account_id": acc_over_short, "debit": 0, "credit": diff_abs, "description": 'فائض صندوق POS'})
            else:
                lines_data.append({"account_id": acc_over_short, "debit": diff_abs, "credit": 0, "description": 'عجز صندوق POS'})
                lines_data.append({"account_id": acc_cash, "debit": 0, "credit": diff_abs, "description": 'عجز صندوق'})
            
            gl_create_journal_entry(
                db=db,
                company_id=current_user.company_id,
                date=datetime.now().date(),
                description=f"فرق إغلاق جلسة POS رقم {session_id}",
                lines=lines_data,
                user_id=current_user.id,
                branch_id=branch_id,
                reference=f"POS-SESSION-{session_id}",
                currency=base_currency,
                source="POS-Close",
                source_id=session_id
            )
    
    db.commit()

    log_activity(
        db, user_id=current_user.id, username=current_user.username,
        action="close_pos_session", resource_type="pos_session",
        resource_id=str(session_id),
        details={"closing_balance": str(close_in.closing_balance), "difference": str(difference)},
        request=request, branch_id=branch_id
    )

    return _get_populated_session(db, session_id, current_user.id)


@router.get("/sessions/active", response_model=Optional[SessionResponse], dependencies=[Depends(require_permission("pos.sessions"))])
def get_active_session(
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = text("""
        SELECT s.*, w.warehouse_name, u.full_name as cashier_name
        FROM pos_sessions s
        LEFT JOIN warehouses w ON s.warehouse_id = w.id
        LEFT JOIN company_users u ON s.user_id = u.id
        WHERE s.user_id = :uid AND s.status = 'opened'
        LIMIT 1
    """)
    session_row = db.execute(query, {"uid": current_user.id}).fetchone()
    if session_row:
        return _get_populated_session(db, session_row.id, current_user.id)
    return None


@router.get("/warehouses", dependencies=[Depends(require_permission("pos.view"))])
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

@router.post("/orders", response_model=OrderResponse, dependencies=[Depends(require_permission("pos.create"))])
def create_order(
    order_in: OrderCreate,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Get base currency
    from utils.accounting import get_base_currency
    base_currency = get_base_currency(db)
    
    # UOM Validation: Discrete units must have integer quantities
    from utils.quantity_validation import validate_quantity_for_product
    for item in order_in.items:
        validate_quantity_for_product(db, item.product_id, item.quantity)

    # TASK-027: unified VAT via compute_invoice_totals
    from utils.accounting import compute_invoice_totals, compute_line_amounts
    _totals = compute_invoice_totals([
        {
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "tax_rate": item.tax_rate,
            "discount": item.discount_amount,
        }
        for item in order_in.items
    ])
    subtotal = _totals["subtotal"] - _totals["total_discount"]  # net taxable base, matches prior semantics
    tax_total = _totals["total_tax"]

    # FISCAL-LOCK: Reject if accounting period is closed
    check_fiscal_period_open(db, datetime.now().date())
    
    # Apply global discount if any (POS-specific: reduces grand total post-tax)
    total = (subtotal + tax_total - _dec(order_in.discount_amount)).quantize(_D2, ROUND_HALF_UP)
    
    # Validate branch and warehouse access
    if order_in.branch_id:
        validate_branch_access(current_user, order_in.branch_id)
    
    if order_in.warehouse_id:
        wh_branch = db.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": order_in.warehouse_id}).scalar()
        if wh_branch:
             validate_branch_access(current_user, wh_branch)

    # Validate payments cover total for paid orders
    if order_in.status == 'paid':
        total_payments = sum(_dec(p.amount) for p in order_in.payments)
        if total_payments < total:
            if len(order_in.payments) == 1 and abs(total_payments - total) < _D2:
                # Auto-adjust only for rounding differences
                order_in.payments[0].amount = total
            elif total_payments < total:
                raise HTTPException(status_code=400, detail=f"المبلغ المدفوع ({total_payments:.2f}) أقل من إجمالي الطلب ({total:.2f})")

    # Fetch session info for branch_id if not provided
    pos_session = db.execute(text("SELECT branch_id, warehouse_id, treasury_account_id FROM pos_sessions WHERE id = :id"), {"id": order_in.session_id}).fetchone()
    branch_id = order_in.branch_id or (pos_session.branch_id if pos_session else None)
    warehouse_id = order_in.warehouse_id or (pos_session.warehouse_id if pos_session else None)
    treasury_id = pos_session.treasury_account_id if pos_session else None

    import uuid
    order_number = f"POS-{uuid.uuid4().hex[:8].upper()}"
    
    # 1. Create Order
    total_cogs = Decimal('0')
    result = db.execute(text("""
        INSERT INTO pos_orders (
            order_number, session_id, customer_id, walk_in_customer_name, 
            warehouse_id, branch_id, status, subtotal, tax_amount, 
            discount_amount, total_amount, paid_amount, note, created_by
        ) VALUES (
            :num, :sess, :cust, :walkin, :wh, :branch, :status, :subtotal, :tax,
            :disc, :total, :paid, :note, :uid
        ) RETURNING id
    """), {
        "num": order_number,
        "sess": order_in.session_id,
        "cust": order_in.customer_id,
        "walkin": order_in.walk_in_customer_name,
        "wh": warehouse_id,
        "branch": branch_id,
        "status": order_in.status,
        "subtotal": subtotal,
        "tax": tax_total,
        "disc": _dec(order_in.discount_amount).quantize(_D2, ROUND_HALF_UP),
        "total": total,
        "paid": _dec(order_in.paid_amount).quantize(_D2, ROUND_HALF_UP),
        "note": order_in.note,
        "uid": current_user.id
    }).fetchone()
    
    order_id = result.id
    
    # 2. Create Items
    for item in order_in.items:
        # Fetch product details for the record
        prod_info = db.execute(text("SELECT product_name, product_code, barcode FROM products WHERE id = :id"), {"id": item.product_id}).fetchone()
        
        item_subtotal = (_dec(item.quantity) * _dec(item.unit_price)).quantize(_D2, ROUND_HALF_UP)
        _la = compute_line_amounts(item.quantity, item.unit_price, item.tax_rate, item.discount_amount)
        tax_amount = _la["tax_amount"]
        item_total = _la["line_total"]

        db.execute(text("""
            INSERT INTO pos_order_lines (
                order_id, product_id, description,
                quantity, original_price, unit_price,
                tax_rate, tax_amount, subtotal, total,
                warehouse_id
            ) VALUES (
                :oid, :pid, :desc,
                :qty, :orig, :price,
                :tax_r, :tax_a, :sub, :tot,
                :wh
            )
        """), {
            "oid": order_id,
            "pid": item.product_id,
            "desc": f"{prod_info[0]} ({prod_info[1]})" if prod_info else "Unknown",
            "qty": item.quantity,
            "orig": _dec(item.unit_price).quantize(_D2, ROUND_HALF_UP),
            "price": _dec(item.unit_price).quantize(_D2, ROUND_HALF_UP),
            "tax_r": _dec(item.tax_rate),
            "tax_a": tax_amount,
            "sub": item_subtotal,
            "tot": item_total,
            "wh": warehouse_id
        })
        
        # 3. Update Inventory if Paid
        if order_in.status == 'paid':
            # CONC-FIX: Lock inventory row to prevent overselling under concurrent POS load
            current_stock = db.execute(text("""
                SELECT COALESCE(quantity, 0) as qty FROM inventory
                WHERE product_id = :pid AND warehouse_id = :wh
                FOR UPDATE
            """), {"pid": item.product_id, "wh": warehouse_id}).fetchone()
            avail_qty = _dec(current_stock.qty) if current_stock else Decimal('0')
            if avail_qty < _dec(item.quantity):
                prod_name = prod_info[0] if prod_info else str(item.product_id)
                raise HTTPException(status_code=400, detail=f"المخزون غير كافٍ للمنتج {prod_name}. المتوفر: {avail_qty:.0f}, المطلوب: {item.quantity}")

            # Fetch cost price for COGS (FIFO/LIFO or WAC)
            try:
                from services.costing_service import CostingService
                method = CostingService._get_product_costing_method(db, item.product_id, warehouse_id)
                if method in ("fifo", "lifo"):
                    item_cogs = CostingService.consume_layers(
                        db,
                        product_id=item.product_id,
                        warehouse_id=warehouse_id,
                        quantity=item.quantity,
                        sale_document_type="pos_order",
                        sale_document_id=order_id,
                        costing_method=method,
                    )
                    cost_price = (item_cogs / _dec(item.quantity)).quantize(_D4, ROUND_HALF_UP) if item.quantity else _dec(0)
                    total_cogs += _dec(item_cogs).quantize(_D2, ROUND_HALF_UP)
                else:
                    cost_price = _dec(db.execute(text("SELECT cost_price FROM products WHERE id = :id"), {"id": item.product_id}).scalar() or 0)
                    total_cogs += (cost_price * _dec(item.quantity)).quantize(_D2, ROUND_HALF_UP)
            except Exception:
                cost_price = _dec(db.execute(text("SELECT cost_price FROM products WHERE id = :id"), {"id": item.product_id}).scalar() or 0)
                total_cogs += (cost_price * _dec(item.quantity)).quantize(_D2, ROUND_HALF_UP)

            db.execute(text("""
                UPDATE inventory 
                SET quantity = quantity - :qty 
                WHERE product_id = :pid AND warehouse_id = :wh
            """), {
                "qty": item.quantity,
                "pid": item.product_id,
                "wh": warehouse_id
            })

            # Log Inventory Transaction
            db.execute(text("""
                INSERT INTO inventory_transactions (
                    product_id, warehouse_id, transaction_type, 
                    reference_type, reference_id, reference_document,
                    quantity, unit_cost, total_cost, created_by
                ) VALUES (
                    :pid, :wh, 'sales', 'pos_order', :order_id, :order_num,
                    :qty, :cost, :total_cost, :user
                )
            """), {
                "pid": item.product_id,
                "wh": warehouse_id,
                "order_id": order_id,
                "order_num": order_number,
                "qty": -item.quantity,
                "cost": cost_price,
                "total_cost": (cost_price * _dec(item.quantity)).quantize(_D2, ROUND_HALF_UP),
                "user": current_user.id
            })
            
    # 4. Create Payments
    for payment in order_in.payments:
        db.execute(text("""
            INSERT INTO pos_payments (order_id, session_id, payment_method, amount, reference_number)
            VALUES (:oid, :sess, :meth, :amt, :ref)
        """), {
            "oid": order_id,
            "sess": order_in.session_id,
            "meth": payment.method,
            "amt": payment.amount,
            "ref": payment.reference
        })
        
    # 5. Update Session Totals & Accounting
    if order_in.status == 'paid':
        # Update gross sales
        db.execute(text("""
            UPDATE pos_sessions
            SET total_sales = total_sales + :amount
            WHERE id = :id
        """), {
            "amount": total,
            "id": order_in.session_id
        })

        # --- Automated Accounting (GL Entries) ---
        # GL-FIX: Use configured account mappings with fallback to account_code lookup
        from utils.accounting import get_mapped_account_id

        def get_acc_id(code):
             return db.execute(text("SELECT id FROM accounts WHERE account_code = :code"), {"code": code}).scalar()

        acc_sales = get_mapped_account_id(db, "acc_map_sales") or get_acc_id("SALE-G")
        acc_vat_out = get_mapped_account_id(db, "acc_map_vat_output") or get_acc_id("VAT-OUT")

        # DYNAMIC TREASURY MAPPING
        acc_cash = None
        if treasury_id:
             acc_cash = db.execute(text("SELECT gl_account_id FROM treasury_accounts WHERE id = :id"), {"id": treasury_id}).scalar()
        if not acc_cash:
             acc_cash = get_mapped_account_id(db, "acc_map_cash_main") or get_acc_id("BOX")

        acc_bank = get_mapped_account_id(db, "acc_map_bank_main") or get_acc_id("BNK")
        acc_cogs = get_mapped_account_id(db, "acc_map_cogs") or get_acc_id("CGS")
        acc_inventory = get_mapped_account_id(db, "acc_map_inventory") or get_acc_id("INV")

        je_lines = []
        # A. Debit: Payments (Cash/Bank)
        for pmt in order_in.payments:
            acc_id = acc_cash if pmt.method == 'cash' else acc_bank
            if acc_id:
                je_lines.append({
                    "account_id": acc_id,
                    "debit": _dec(pmt.amount).quantize(_D2, ROUND_HALF_UP),
                    "credit": 0,
                    "description": f"POS Payment ({pmt.method}) - {order_number}"
                })

        # B. Credit: Sales Revenue (Gross Subtotal) & Debit: Sales Discount (if any)
        discount_dec = _dec(order_in.discount_amount).quantize(_D2, ROUND_HALF_UP)
        if acc_sales and subtotal > 0:
            je_lines.append({
                "account_id": acc_sales,
                "debit": 0,
                "credit": subtotal,
                "description": f"POS Gross Sales - {order_number}"
            })

        # Sales Discount (separate account for proper reporting)
        if discount_dec > 0:
            acc_discount = get_acc_id("DISC-SALE") or get_acc_id("SALE-DISC")
            if acc_discount:
                je_lines.append({
                    "account_id": acc_discount,
                    "debit": discount_dec,
                    "credit": 0,
                    "description": f"POS Discount - {order_number}"
                })
            else:
                # Fallback: If no discount account, net into sales (legacy behavior)
                # Adjust the sales credit we just added
                if je_lines and je_lines[-1]["account_id"] == acc_sales:
                    je_lines[-1]["credit"] = (subtotal - discount_dec).quantize(_D2, ROUND_HALF_UP)

        # C. Credit: VAT
        if acc_vat_out and tax_total > 0:
            je_lines.append({
                "account_id": acc_vat_out,
                "debit": 0,
                "credit": tax_total,
                "description": f"POS Tax - {order_number}"
            })

        # D. Perpetual Inventory: COGS & Inventory Reduction
        if total_cogs > 0:
            total_cogs_q = total_cogs.quantize(_D2, ROUND_HALF_UP)
            if acc_cogs:
                je_lines.append({
                    "account_id": acc_cogs,
                    "debit": total_cogs_q,
                    "credit": 0,
                    "description": f"POS COGS - {order_number}"
                })
            if acc_inventory:
                je_lines.append({
                    "account_id": acc_inventory,
                    "debit": 0,
                    "credit": total_cogs_q,
                    "description": f"POS Inventory Deduct - {order_number}"
                })

        # Create Journal Entry if accounts are mapped
        if je_lines:
            # Validate JE lines (balance, None accounts, negatives)
            from utils.accounting import prepare_je_lines
            try:
                je_lines = prepare_je_lines(je_lines, source=f"POS-{order_number}")
            except Exception as e:
                logger.error(f"POS JE validation failed for {order_number}: {e}")
                raise

            import uuid
            je_num = f"JE-POS-{order_number}"
            # Get treasury currency
            treasury_info = db.execute(text("SELECT currency FROM treasury_accounts WHERE id = :id"), {"id": treasury_id}).fetchone() if treasury_id else None
            pos_currency = treasury_info[0] if treasury_info else base_currency

            gl_create_journal_entry(
                db=db,
                company_id=current_user.company_id,
                date=datetime.now().date(),
                description=f"POS Order {order_number} ({pos_currency})",
                lines=je_lines,
                user_id=current_user.id,
                branch_id=branch_id,
                reference=order_number,
                currency=pos_currency,
                source="POS-Order",
                source_id=order_id
            )
        
        # Update individual payment method totals if you have columns for them
        # For now, we assume total_sales covers it all, but you might want 
        # specifically to log cash_sales and bank_sales for reconciliation.
        
        # 6. Update Treasury Balance — T1.3a idempotent recompute
        if treasury_id:
            from utils.treasury_balance import recalc_treasury_from_gl
            recalc_treasury_from_gl(db, treasury_id)

        # 7. Update Customer Balance (if customer-linked POS sale)
        if order_in.customer_id and order_in.status == 'paid':
            try:
                credit_payments = sum(_dec(p.amount) for p in order_in.payments if p.method in ('credit', 'on_account'))
                if credit_payments > 0:
                    db.execute(text("""
                        UPDATE parties
                        SET current_balance = current_balance + :amt, updated_at = CURRENT_TIMESTAMP
                        WHERE id = :pid
                    """), {"amt": credit_payments.quantize(_D2, ROUND_HALF_UP), "pid": order_in.customer_id})
            except Exception:
                # SEC-T2.11: silently dropping a credit-balance UPDATE leaves the
                # customer ledger out of sync with the GL. Surface the failure
                # and let the outer transaction roll back instead of swallowing.
                logger.exception("POS: failed to update party balance for credit sale")
                db.rollback()
                raise HTTPException(
                    status_code=500,
                    detail="تعذّر تحديث رصيد العميل لطلب البيع الآجل",
                )

    db.commit()

    log_activity(
        db, user_id=current_user.id, username=current_user.username,
        action="create_pos_order", resource_type="pos_order",
        resource_id=str(order_id),
        details={"order_number": order_number, "total": str(total), "status": order_in.status, "branch_id": branch_id},
        request=request, branch_id=branch_id
    )

    return OrderResponse(
        id=order_id,
        order_number=order_number,
        total_amount=total,
        status=order_in.status,
        created_at=datetime.now()
    )


# --- Hold Orders ---

@router.get("/orders/held", response_model=List[dict], dependencies=[Depends(require_permission("pos.view"))])
def get_held_orders(
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all held orders for current session"""
    try:
        allowed_branches = current_user.allowed_branches or []
        if current_user.role == "admin" or not allowed_branches:
            result = db.execute(text("""
                SELECT po.id, po.order_number, po.total_amount, po.status, po.created_at,
                       COALESCE(c.name, po.walk_in_customer_name, 'عميل نقدي') as customer_name,
                       (SELECT COUNT(*) FROM pos_order_lines WHERE order_id = po.id) as items_count
                FROM pos_orders po
                LEFT JOIN parties c ON po.customer_id = c.id
                WHERE po.status = 'hold'
                ORDER BY po.created_at DESC
            """)).fetchall()
        else:
            result = db.execute(text("""
                SELECT po.id, po.order_number, po.total_amount, po.status, po.created_at,
                       COALESCE(c.name, po.walk_in_customer_name, 'عميل نقدي') as customer_name,
                       (SELECT COUNT(*) FROM pos_order_lines WHERE order_id = po.id) as items_count
                FROM pos_orders po
                LEFT JOIN parties c ON po.customer_id = c.id
                WHERE po.status = 'hold' AND po.branch_id = ANY(:branches)
                ORDER BY po.created_at DESC
            """), {"branches": allowed_branches}).fetchall()
        
        return [dict(r._mapping) for r in result]
    except Exception as e:
        logger.error(f"Error fetching held orders: {str(e)}")
        return []


@router.post("/orders/{order_id}/resume", dependencies=[Depends(require_permission("pos.manage"))])
def resume_held_order(
    order_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Resume a held order - returns full order details"""
    order = db.execute(text("""
        SELECT po.*, 
               COALESCE(c.name, po.walk_in_customer_name) as customer_name
        FROM pos_orders po
        LEFT JOIN parties c ON po.customer_id = c.id
        WHERE po.id = :id AND po.status = 'hold'
    """), {"id": order_id}).fetchone()
    
    if not order:
        raise HTTPException(status_code=404, detail="Held order not found")

    if order.branch_id:
        validate_branch_access(current_user, order.branch_id)

    # Get order items
    items = db.execute(text("""
        SELECT poi.*, p.product_name as name, p.product_code as code, p.barcode
        FROM pos_order_lines poi
        JOIN products p ON poi.product_id = p.id
        WHERE poi.order_id = :id
    """), {"id": order_id}).fetchall()
    
    return {
        "order": dict(order._mapping),
        "items": [dict(i._mapping) for i in items]
    }


@router.delete("/orders/{order_id}/cancel-held", dependencies=[Depends(require_permission("pos.manage"))])
def cancel_held_order(
    order_id: int,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Cancel a held order"""
    order = db.execute(text("""
        SELECT id, branch_id, order_number FROM pos_orders 
        WHERE id = :id AND status = 'hold'
    """), {"id": order_id}).fetchone()
    
    if not order:
        raise HTTPException(status_code=404, detail="Held order not found")

    if order.branch_id:
        validate_branch_access(current_user, order.branch_id)

    # Delete related records from all possible tables to avoid foreign key issues
    db.execute(text("DELETE FROM pos_order_lines WHERE order_id = :id"), {"id": order_id})
    db.execute(text("DELETE FROM pos_payments WHERE order_id = :id"), {"id": order_id})
    db.execute(text("DELETE FROM pos_orders WHERE id = :id"), {"id": order_id})
    db.commit()

    log_activity(
        db, user_id=current_user.id, username=current_user.username,
        action="cancel_held_order", resource_type="pos_order",
        resource_id=str(order_id),
        details={"order_number": getattr(order, "order_number", None)},
        request=request, branch_id=getattr(order, "branch_id", None)
    )

    return {"message": "Order cancelled successfully"}


# --- Returns ---

@router.post("/orders/{order_id}/return", dependencies=[Depends(require_permission("pos.returns"))])
def create_return(
    order_id: int,
    return_in: ReturnCreate,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Process a return for a paid order"""
    # Get base currency
    from utils.accounting import get_base_currency
    base_currency = get_base_currency(db)
    # Verify original order exists and is paid
    order = db.execute(text("""
        SELECT o.id, o.order_number, o.session_id, o.warehouse_id, s.branch_id
        FROM pos_orders o
        JOIN pos_sessions s ON o.session_id = s.id
        WHERE o.id = :id AND o.status = 'paid'
    """), {"id": order_id}).fetchone()
    
    if not order:
        raise HTTPException(status_code=404, detail="Original order not found or not paid")
        
    # Validate branch access
    if order.branch_id:
        validate_branch_access(current_user, order.branch_id)
    
    total_refund = Decimal('0')

    # Pre-calculate total refund to check cash sufficiency
    for item in return_in.items:
        orig_item_pre = db.execute(text("""
            SELECT product_id, unit_price, quantity
            FROM pos_order_lines WHERE id = :id AND order_id = :order_id
        """), {"id": item.item_id, "order_id": order_id}).fetchone()
        if orig_item_pre:
            total_refund += (_dec(item.quantity) * _dec(orig_item_pre.unit_price)).quantize(_D2, ROUND_HALF_UP)

    # Check cash sufficiency for cash refunds
    if return_in.refund_method == 'cash' and total_refund > 0:
        session_info = db.execute(text("""
            SELECT s.treasury_account_id, COALESCE(ta.current_balance, 0) as cash_balance
            FROM pos_sessions s
            LEFT JOIN treasury_accounts ta ON s.treasury_account_id = ta.id
            WHERE s.id = :sid
        """), {"sid": order.session_id}).fetchone()
        if session_info and _dec(session_info.cash_balance) < total_refund:
            raise HTTPException(status_code=400, detail=f"رصيد الصندوق غير كافٍ للمرتجع. الرصيد الحالي: {_dec(session_info.cash_balance):.2f}, المطلوب: {total_refund:.2f}")

    total_refund = Decimal('0')  # Reset for actual calculation
    total_refund_tax = Decimal('0')  # Track VAT on returns
    
    for item in return_in.items:
        # Get original item details
        orig_item = db.execute(text("""
            SELECT product_id, unit_price, quantity, tax_rate 
            FROM pos_order_lines WHERE id = :id AND order_id = :order_id
        """), {"id": item.item_id, "order_id": order_id}).fetchone()
        
        if not orig_item:
            raise HTTPException(status_code=404, detail=f"Item {item.item_id} not found in order")
        
        if item.quantity > orig_item.quantity:
            raise HTTPException(status_code=400, detail="Return quantity exceeds original quantity")
        
        refund_amount = (_dec(item.quantity) * _dec(orig_item.unit_price)).quantize(_D2, ROUND_HALF_UP)
        refund_tax = (refund_amount * (_dec(orig_item.tax_rate) / Decimal('100'))).quantize(_D2, ROUND_HALF_UP)
        total_refund += refund_amount
        total_refund_tax += refund_tax
        
        # Update stock (add back) - use 'inventory' table (not warehouse_stock)
        if order.warehouse_id:
            db.execute(text("""
                UPDATE inventory 
                SET quantity = quantity + :qty 
                WHERE product_id = :pid AND warehouse_id = :wid
            """), {
                "qty": item.quantity,
                "pid": orig_item.product_id,
                "wid": order.warehouse_id
            })
            
            # Log inventory transaction for return
            cost_price = _dec(db.execute(text("SELECT cost_price FROM products WHERE id = :id"), {"id": orig_item.product_id}).scalar() or 0)
            db.execute(text("""
                INSERT INTO inventory_transactions (
                    product_id, warehouse_id, transaction_type,
                    reference_type, reference_id,
                    quantity, unit_cost, total_cost, created_by
                ) VALUES (
                    :pid, :wid, 'return_in',
                    'pos_return', :order_id,
                    :qty, :cost, :total_cost, :uid
                )
            """), {
                "pid": orig_item.product_id,
                "wid": order.warehouse_id,
                "qty": item.quantity,
                "order_id": order_id,
                "cost": cost_price,
                "total_cost": (cost_price * _dec(item.quantity)).quantize(_D2, ROUND_HALF_UP),
                "uid": current_user.id
            })
    
    # Find active session to link this return to current cash count
    active_session = db.execute(text("SELECT id FROM pos_sessions WHERE user_id = :uid AND status = 'opened'"), {"uid": current_user.id}).fetchone()
    curr_session_id = active_session.id if active_session else None

    # Create return record
    return_id = db.execute(text("""
        INSERT INTO pos_returns (
            original_order_id, user_id, session_id, refund_amount, refund_method, notes, created_at
        ) VALUES (:order_id, :user_id, :sess_id, :amount, :method, :notes, CURRENT_TIMESTAMP)
        RETURNING id
    """), {
        "order_id": order_id,
        "user_id": current_user.id,
        "sess_id": curr_session_id,
        "amount": total_refund,
        "method": return_in.refund_method,
        "notes": return_in.notes
    }).scalar()
    
    # Insert return items
    for item in return_in.items:
        db.execute(text("""
            INSERT INTO pos_return_items (return_id, original_item_id, quantity, reason)
            VALUES (:rid, :iid, :qty, :reason)
        """), {
            "rid": return_id,
            "iid": item.item_id,
            "qty": item.quantity,
            "reason": item.reason
        })
    
    # Update session totals (subtract refund)
    db.execute(text("""
        UPDATE pos_sessions 
        SET total_returns = COALESCE(total_returns, 0) + :amount 
        WHERE id = :id
    """), {"amount": total_refund, "id": order.session_id})
    
    # FISCAL-LOCK: Reject if accounting period is closed
    check_fiscal_period_open(db, datetime.now().date())

    # --- Create GL Journal Entries for Return ---
    # GL-FIX: Use configured account mappings with fallback to account_code lookup
    from utils.accounting import get_mapped_account_id

    def get_acc_id(code):
        return db.execute(text("SELECT id FROM accounts WHERE account_code = :code"), {"code": code}).scalar()

    acc_sales = get_mapped_account_id(db, "acc_map_sales") or get_acc_id("SALE-G")
    acc_cash = get_mapped_account_id(db, "acc_map_cash_main") or get_acc_id("BOX")
    acc_cogs = get_mapped_account_id(db, "acc_map_cogs") or get_acc_id("CGS")
    acc_inventory = get_mapped_account_id(db, "acc_map_inventory") or get_acc_id("INV")
    acc_vat_out = get_mapped_account_id(db, "acc_map_vat_output") or get_acc_id("VAT-OUT")
    
    # Get treasury for session
    session_treasury = db.execute(text("SELECT treasury_account_id FROM pos_sessions WHERE id = :id"), {"id": order.session_id}).fetchone()
    if session_treasury and session_treasury.treasury_account_id:
        acc_cash = db.execute(text("SELECT gl_account_id FROM treasury_accounts WHERE id = :id"), {"id": session_treasury.treasury_account_id}).scalar() or acc_cash
    
    total_refund_with_tax = (total_refund + total_refund_tax).quantize(_D2, ROUND_HALF_UP)

    if acc_sales and acc_cash:
        je_lines = []
        # Reverse: Debit Sales Revenue (net subtotal)
        je_lines.append({
            "account_id": acc_sales, "debit": total_refund, "credit": 0, "description": "POS Return Revenue Reversal"
        })
        # Reverse: Debit VAT Output (tax portion)
        if total_refund_tax > 0 and acc_vat_out:
            je_lines.append({
                "account_id": acc_vat_out, "debit": total_refund_tax, "credit": 0, "description": "POS Return VAT Reversal"
            })
        # Credit: Cash/Bank (total including tax)
        je_lines.append({
            "account_id": acc_cash, "debit": 0, "credit": total_refund_with_tax, "description": "POS Return Cash Refund"
        })

        # Reverse COGS if applicable
        total_cogs_return = Decimal('0')
        for item in return_in.items:
            orig_item = db.execute(text("SELECT product_id FROM pos_order_lines WHERE id = :id"), {"id": item.item_id}).fetchone()
            if orig_item:
                cost_price = _dec(db.execute(text("SELECT cost_price FROM products WHERE id = :id"), {"id": orig_item.product_id}).scalar() or 0)
                total_cogs_return += (cost_price * _dec(item.quantity)).quantize(_D2, ROUND_HALF_UP)

        if total_cogs_return > 0 and acc_cogs and acc_inventory:
            total_cogs_ret_q = total_cogs_return.quantize(_D2, ROUND_HALF_UP)
            je_lines.append({
                "account_id": acc_inventory, "debit": total_cogs_ret_q, "credit": 0, "description": "POS Return Inventory Restore"
            })
            je_lines.append({
                "account_id": acc_cogs, "debit": 0, "credit": total_cogs_ret_q, "description": "POS Return COGS Reversal"
            })

        gl_create_journal_entry(
            db=db,
            company_id=current_user.company_id,
            date=datetime.now().date(),
            description=f"POS Return for Order {order.order_number}",
            lines=je_lines,
            user_id=current_user.id,
            branch_id=None,
            reference=f"RTN-{order.order_number}",
            currency=base_currency,
            source="POS-Return",
            source_id=return_id
        )

        # Update treasury balance only for cash refunds — T1.3a idempotent recompute
        if return_in.refund_method == 'cash' and session_treasury and session_treasury.treasury_account_id:
            from utils.treasury_balance import recalc_treasury_from_gl
            recalc_treasury_from_gl(db, session_treasury.treasury_account_id)
    
    db.commit()

    log_activity(
        db, user_id=current_user.id, username=current_user.username,
        action="create_pos_return", resource_type="pos_return",
        resource_id=str(return_id),
        details={"order_id": order_id, "order_number": order.order_number, "refund_amount": str(total_refund), "refund_method": return_in.refund_method},
        request=request, branch_id=order.branch_id
    )

    return {
        "return_id": return_id,
        "refund_amount": str(total_refund),
        "message": "Return processed successfully"
    }


@router.get("/orders/{order_id}/details", dependencies=[Depends(require_permission("pos.view"))])
def get_order_details(
    order_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get full order details for returns"""
    order = db.execute(text("""
        SELECT po.*, 
               COALESCE(c.name, po.walk_in_customer_name, 'عميل نقدي') as customer_name
        FROM pos_orders po
        LEFT JOIN parties c ON po.customer_id = c.id
        WHERE po.id = :id
    """), {"id": order_id}).fetchone()
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if hasattr(order, 'branch_id') and order.branch_id:
        validate_branch_access(current_user, order.branch_id)

    items = db.execute(text("""
        SELECT poi.*, p.product_name as name
        FROM pos_order_lines poi
        JOIN products p ON poi.product_id = p.id
        WHERE poi.order_id = :id
    """), {"id": order_id}).fetchall()
    
    return {
        "order": dict(order._mapping),
        "items": [dict(i._mapping) for i in items]
    }


# =====================================================
# 8.10 POS IMPROVEMENTS
# =====================================================

# ---------- POS-003: Promotions & Discounts ----------

@router.get("/promotions", dependencies=[Depends(require_permission("pos.view"))])
def list_promotions(
    active_only: bool = True,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    q = "SELECT * FROM pos_promotions WHERE 1=1"
    params = {}
    if active_only:
        q += " AND is_active = true AND (end_date IS NULL OR end_date > NOW())"
    q += " ORDER BY created_at DESC"
    rows = db.execute(text(q), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/promotions", dependencies=[Depends(require_permission("pos.manage"))])
def create_promotion(
    data: dict,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    branch_id = data.get("branch_id")
    if branch_id:
        validate_branch_access(current_user, branch_id)

    result = db.execute(text("""
        INSERT INTO pos_promotions (name, promotion_type, value, buy_qty, get_qty, coupon_code,
            applicable_products, applicable_categories, min_order_amount, start_date, end_date,
            is_active, branch_id, created_by)
        VALUES (:name, :type, :value, :buy, :get, :coupon,
            :products, :categories, :min_amt, :start, :end,
            :active, :branch, :uid)
        RETURNING *
    """), {
        "name": data.get("name"),
        "type": data.get("promotion_type", "percentage"),
        "value": data.get("value", 0),
        "buy": data.get("buy_qty"),
        "get": data.get("get_qty"),
        "coupon": data.get("coupon_code"),
        "products": data.get("applicable_products"),
        "categories": data.get("applicable_categories"),
        "min_amt": data.get("min_order_amount", 0),
        "start": data.get("start_date"),
        "end": data.get("end_date"),
        "active": data.get("is_active", True),
        "branch": branch_id,
        "uid": current_user.id,
    })
    db.commit()
    row = dict(result.fetchone()._mapping)

    log_activity(
        db, user_id=current_user.id, username=current_user.username,
        action="create_promotion", resource_type="pos_promotion",
        resource_id=str(row.get("id")),
        details={"name": data.get("name"), "type": data.get("promotion_type")},
        request=request, branch_id=branch_id
    )

    return row


@router.put("/promotions/{promo_id}", dependencies=[Depends(require_permission("pos.manage"))])
def update_promotion(
    promo_id: int,
    data: dict,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    sets = []
    params = {"id": promo_id}
    for field in ["name", "promotion_type", "value", "buy_qty", "get_qty", "coupon_code",
                  "applicable_products", "applicable_categories", "min_order_amount",
                  "start_date", "end_date", "is_active"]:
        if field in data:
            sets.append(f"{field} = :{field}")
            params[field] = data[field]
    if not sets:
        raise HTTPException(status_code=400, detail="No fields to update")
    sets.append("updated_at = NOW()")
    sql = f"UPDATE pos_promotions SET {', '.join(sets)} WHERE id = :id RETURNING *"
    row = db.execute(text(sql), params).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Promotion not found")
    db.commit()

    log_activity(
        db, user_id=current_user.id, username=current_user.username,
        action="update_promotion", resource_type="pos_promotion",
        resource_id=str(promo_id),
        details={"updated_fields": list(data.keys())},
        request=request
    )

    return dict(row._mapping)


@router.delete("/promotions/{promo_id}", dependencies=[Depends(require_permission("pos.manage"))])
def delete_promotion(promo_id: int, request: Request, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM pos_promotions WHERE id = :id"), {"id": promo_id})
    db.commit()

    log_activity(
        db, user_id=current_user.id, username=current_user.username,
        action="delete_promotion", resource_type="pos_promotion",
        resource_id=str(promo_id), request=request
    )

    return {"message": "Deleted"}


@router.post("/promotions/validate", dependencies=[Depends(require_permission("pos.view"))])
def validate_coupon(
    data: dict,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Validate a coupon code and return applicable promotion."""
    code = data.get("coupon_code", "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="Coupon code required")
    promo = db.execute(text("""
        SELECT * FROM pos_promotions
        WHERE coupon_code = :code AND is_active = true
          AND (start_date IS NULL OR start_date <= NOW())
          AND (end_date IS NULL OR end_date > NOW())
    """), {"code": code}).fetchone()
    if not promo:
        raise HTTPException(status_code=404, detail="Invalid or expired coupon")
    return dict(promo._mapping)


# ---------- POS-004: Loyalty Program ----------

@router.get("/loyalty/programs", dependencies=[Depends(require_permission("pos.view"))])
def list_loyalty_programs(current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(text("SELECT * FROM pos_loyalty_programs WHERE is_active = true ORDER BY id")).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/loyalty/programs", dependencies=[Depends(require_permission("pos.manage"))])
def create_loyalty_program(data: dict, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    import json
    result = db.execute(text("""
        INSERT INTO pos_loyalty_programs (name, points_per_unit, currency_per_point, min_points_redeem, tier_rules, is_active, branch_id)
        VALUES (:name, :ppu, :cpp, :min, :tiers::jsonb, :active, :branch)
        RETURNING *
    """), {
        "name": data["name"],
        "ppu": data.get("points_per_unit", 1),
        "cpp": data.get("currency_per_point", 0.01),
        "min": data.get("min_points_redeem", 100),
        "tiers": json.dumps(data.get("tier_rules", [])),
        "active": data.get("is_active", True),
        "branch": data.get("branch_id"),
    })
    db.commit()
    return dict(result.fetchone()._mapping)


@router.get("/loyalty/customer/{party_id}", dependencies=[Depends(require_permission("pos.view"))])
def get_customer_loyalty(party_id: int, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.execute(text("""
        SELECT lp.*, prg.name as program_name, prg.currency_per_point
        FROM pos_loyalty_points lp
        JOIN pos_loyalty_programs prg ON lp.program_id = prg.id
        WHERE lp.party_id = :pid
    """), {"pid": party_id}).fetchone()
    if not row:
        return {"party_id": party_id, "balance": 0, "tier": "standard", "enrolled": False}
    return {**dict(row._mapping), "enrolled": True}


@router.post("/loyalty/enroll", dependencies=[Depends(require_permission("pos.manage"))])
def enroll_customer(data: dict, request: Request, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    existing = db.execute(text(
        "SELECT id FROM pos_loyalty_points WHERE party_id = :pid AND program_id = :prog"
    ), {"pid": data["party_id"], "prog": data["program_id"]}).fetchone()
    if existing:
        raise HTTPException(status_code=400, detail="Customer already enrolled")
    result = db.execute(text("""
        INSERT INTO pos_loyalty_points (program_id, party_id, points_earned, points_redeemed, balance, tier)
        VALUES (:prog, :pid, 0, 0, 0, 'standard')
        RETURNING *
    """), {"prog": data["program_id"], "pid": data["party_id"]})
    db.commit()
    row = dict(result.fetchone()._mapping)

    log_activity(
        db, user_id=current_user.id, username=current_user.username,
        action="enroll_loyalty", resource_type="pos_loyalty",
        resource_id=str(row.get("id")),
        details={"party_id": data["party_id"], "program_id": data["program_id"]},
        request=request
    )

    return row


@router.post("/loyalty/earn", dependencies=[Depends(require_permission("pos.create"))])
def earn_points(data: dict, request: Request, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    """Award loyalty points after a sale."""
    loyalty = db.execute(text("SELECT * FROM pos_loyalty_points WHERE party_id = :pid"), {"pid": data["party_id"]}).fetchone()
    if not loyalty:
        raise HTTPException(status_code=404, detail="Customer not enrolled in loyalty")
    program = db.execute(text("SELECT * FROM pos_loyalty_programs WHERE id = :id"), {"id": loyalty.program_id}).fetchone()
    points = (_dec(data.get("amount", 0)) * _dec(program.points_per_unit)).quantize(_D2, ROUND_HALF_UP)
    db.execute(text("""
        UPDATE pos_loyalty_points SET points_earned = points_earned + :pts, balance = balance + :pts,
            last_activity_at = NOW() WHERE id = :id
    """), {"pts": points, "id": loyalty.id})
    db.execute(text("""
        INSERT INTO pos_loyalty_transactions (loyalty_id, order_id, txn_type, points, description)
        VALUES (:lid, :oid, 'earn', :pts, :desc)
    """), {"lid": loyalty.id, "oid": data.get("order_id"), "pts": points, "desc": "Earned from order"})
    db.commit()

    log_activity(
        db, user_id=current_user.id, username=current_user.username,
        action="earn_loyalty_points", resource_type="pos_loyalty",
        resource_id=str(loyalty.id),
        details={"party_id": data["party_id"], "points": str(points), "order_id": data.get("order_id")},
        request=request
    )

    return {"points_earned": str(points), "new_balance": str((_dec(loyalty.balance) + points).quantize(_D2, ROUND_HALF_UP))}


@router.post("/loyalty/redeem", dependencies=[Depends(require_permission("pos.create"))])
def redeem_points(data: dict, request: Request, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    """Redeem loyalty points as discount."""
    loyalty = db.execute(text("SELECT * FROM pos_loyalty_points WHERE party_id = :pid"), {"pid": data["party_id"]}).fetchone()
    if not loyalty:
        raise HTTPException(status_code=404, detail="Customer not enrolled")
    points = _dec(data.get("points", 0))
    if points > _dec(loyalty.balance):
        raise HTTPException(status_code=400, detail="Insufficient points")
    program = db.execute(text("SELECT * FROM pos_loyalty_programs WHERE id = :id"), {"id": loyalty.program_id}).fetchone()
    if points < _dec(program.min_points_redeem):
        raise HTTPException(status_code=400, detail=f"Minimum {program.min_points_redeem} points to redeem")
    discount_value = (points * _dec(program.currency_per_point)).quantize(_D2, ROUND_HALF_UP)
    db.execute(text("""
        UPDATE pos_loyalty_points SET points_redeemed = points_redeemed + :pts, balance = balance - :pts,
            last_activity_at = NOW() WHERE id = :id
    """), {"pts": points, "id": loyalty.id})
    db.execute(text("""
        INSERT INTO pos_loyalty_transactions (loyalty_id, order_id, txn_type, points, description)
        VALUES (:lid, :oid, 'redeem', :pts, :desc)
    """), {"lid": loyalty.id, "oid": data.get("order_id"), "pts": -points, "desc": "Redeemed for discount"})
    db.commit()

    log_activity(
        db, user_id=current_user.id, username=current_user.username,
        action="redeem_loyalty_points", resource_type="pos_loyalty",
        resource_id=str(loyalty.id),
        details={"party_id": data["party_id"], "points": str(points), "discount_value": str(discount_value)},
        request=request
    )

    return {"points_redeemed": str(points), "discount_value": str(discount_value), "new_balance": str((_dec(loyalty.balance) - points).quantize(_D2, ROUND_HALF_UP))}


# ---------- POS-006: Session Reports (Enhanced) ----------

@router.get("/sessions/{session_id}/detailed-report", dependencies=[Depends(require_permission("pos.sessions"))])
def session_detailed_report(
    session_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    session = db.execute(text("SELECT * FROM pos_sessions WHERE id = :id"), {"id": session_id}).fetchone()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Sales by product
    by_product = db.execute(text("""
        SELECT pol.product_id, p.product_name, SUM(pol.quantity) as total_qty,
               SUM(pol.subtotal) as total_amount
        FROM pos_order_lines pol
        JOIN pos_orders po ON pol.order_id = po.id
        JOIN products p ON pol.product_id = p.id
        WHERE po.session_id = :sid AND po.status != 'cancelled'
        GROUP BY pol.product_id, p.product_name ORDER BY total_amount DESC
    """), {"sid": session_id}).fetchall()

    # Sales by payment method
    by_payment = db.execute(text("""
        SELECT pop.method, COUNT(*) as txn_count, SUM(pop.amount) as total
        FROM pos_order_payments pop
        JOIN pos_orders po ON pop.order_id = po.id
        WHERE po.session_id = :sid AND po.status != 'cancelled'
        GROUP BY pop.method
    """), {"sid": session_id}).fetchall()

    # Hourly breakdown
    hourly = db.execute(text("""
        SELECT EXTRACT(HOUR FROM po.created_at) as hour, COUNT(*) as orders, SUM(po.total) as total
        FROM pos_orders po WHERE po.session_id = :sid AND po.status != 'cancelled'
        GROUP BY hour ORDER BY hour
    """), {"sid": session_id}).fetchall()

    return {
        "session": dict(session._mapping),
        "by_product": [dict(r._mapping) for r in by_product],
        "by_payment": [dict(r._mapping) for r in by_payment],
        "hourly_breakdown": [dict(r._mapping) for r in hourly],
    }


# ---------- POS-007: Table Management ----------

@router.get("/tables", dependencies=[Depends(require_permission("pos.view"))])
def list_tables(
    branch_id: Optional[int] = None,
    floor: Optional[str] = None,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    q = "SELECT * FROM pos_tables WHERE is_active = true"
    params = {}
    if branch_id:
        validate_branch_access(current_user, branch_id)
        q += " AND branch_id = :bid"
        params["bid"] = branch_id
    else:
        allowed_branches = current_user.allowed_branches or []
        if current_user.role != "admin" and allowed_branches:
            q += " AND branch_id = ANY(:branches)"
            params["branches"] = allowed_branches
    if floor:
        q += " AND floor = :floor"
        params["floor"] = floor
    q += " ORDER BY floor, table_number"
    rows = db.execute(text(q), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/tables", dependencies=[Depends(require_permission("pos.manage"))])
def create_table(data: dict, request: Request, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    branch_id = data.get("branch_id")
    if branch_id:
        validate_branch_access(current_user, branch_id)

    result = db.execute(text("""
        INSERT INTO pos_tables (table_number, table_name, floor, capacity, shape, pos_x, pos_y, branch_id)
        VALUES (:num, :name, :floor, :cap, :shape, :x, :y, :branch)
        RETURNING *
    """), {
        "num": data["table_number"],
        "name": data.get("table_name"),
        "floor": data.get("floor", "main"),
        "cap": data.get("capacity", 4),
        "shape": data.get("shape", "square"),
        "x": data.get("pos_x", 0),
        "y": data.get("pos_y", 0),
        "branch": branch_id,
    })
    db.commit()
    row = dict(result.fetchone()._mapping)

    log_activity(
        db, user_id=current_user.id, username=current_user.username,
        action="create_pos_table", resource_type="pos_table",
        resource_id=str(row.get("id")),
        details={"table_number": data["table_number"]},
        request=request, branch_id=branch_id
    )

    return row


@router.put("/tables/{table_id}", dependencies=[Depends(require_permission("pos.manage"))])
def update_table(table_id: int, data: dict, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    sets, params = [], {"id": table_id}
    for f in ["table_number", "table_name", "floor", "capacity", "shape", "pos_x", "pos_y", "status", "is_active"]:
        if f in data:
            sets.append(f"{f} = :{f}")
            params[f] = data[f]
    if not sets:
        raise HTTPException(status_code=400, detail="No fields")
    row = db.execute(text(f"UPDATE pos_tables SET {', '.join(sets)} WHERE id = :id RETURNING *"), params).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Table not found")
    db.commit()
    return dict(row._mapping)


@router.delete("/tables/{table_id}", dependencies=[Depends(require_permission("pos.manage"))])
def delete_table(table_id: int, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    db.execute(text("UPDATE pos_tables SET is_active = false WHERE id = :id"), {"id": table_id})
    db.commit()
    return {"message": "Table deactivated"}


@router.post("/tables/{table_id}/seat", dependencies=[Depends(require_permission("pos.create"))])
def seat_table(table_id: int, data: dict, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    db.execute(text("UPDATE pos_tables SET status = 'occupied' WHERE id = :id"), {"id": table_id})
    result = db.execute(text("""
        INSERT INTO pos_table_orders (table_id, guests, waiter_id, status)
        VALUES (:tid, :guests, :waiter, 'seated')
        RETURNING *
    """), {"tid": table_id, "guests": data.get("guests", 1), "waiter": current_user.id})
    db.commit()
    return dict(result.fetchone()._mapping)


@router.post("/tables/{table_id}/clear", dependencies=[Depends(require_permission("pos.create"))])
def clear_table(table_id: int, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    db.execute(text("UPDATE pos_tables SET status = 'available' WHERE id = :id"), {"id": table_id})
    db.execute(text("""
        UPDATE pos_table_orders SET status = 'cleared', cleared_at = NOW()
        WHERE table_id = :tid AND status = 'seated'
    """), {"tid": table_id})
    db.commit()
    return {"message": "Table cleared"}


# ---------- POS-008: Kitchen Display System ----------

@router.get("/kitchen/orders", dependencies=[Depends(require_permission("pos.view"))])
def kitchen_orders(
    station: Optional[str] = None,
    status: Optional[str] = "pending",
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    q = "SELECT * FROM pos_kitchen_orders WHERE 1=1"
    params = {}
    if station:
        q += " AND station = :station"
        params["station"] = station
    if status:
        q += " AND status = :status"
        params["status"] = status
    q += " ORDER BY priority DESC, sent_at ASC"
    rows = db.execute(text(q), params).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/kitchen/orders", dependencies=[Depends(require_permission("pos.create"))])
def send_to_kitchen(data: dict, request: Request, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    """Send order items to kitchen."""
    items = data.get("items", [])
    results = []
    for item in items:
        row = db.execute(text("""
            INSERT INTO pos_kitchen_orders (order_id, order_line_id, product_id, product_name,
                quantity, notes, station, priority, branch_id)
            VALUES (:oid, :olid, :pid, :pname, :qty, :notes, :station, :priority, :branch)
            RETURNING *
        """), {
            "oid": data.get("order_id"),
            "olid": item.get("order_line_id"),
            "pid": item.get("product_id"),
            "pname": item.get("product_name"),
            "qty": item.get("quantity", 1),
            "notes": item.get("notes"),
            "station": item.get("station", "main"),
            "priority": item.get("priority", 0),
            "branch": data.get("branch_id"),
        }).fetchone()
        results.append(dict(row._mapping))
    db.commit()
    log_activity(
        db=db,
        user_id=current_user.id,
        action="kitchen_order_created",
        resource_type="pos_kitchen_order",
        resource_id=data.get("order_id"),
        details={"items_count": len(items), "order_id": data.get("order_id")},
        request=request,
    )
    return results


@router.put("/kitchen/orders/{ko_id}/status", dependencies=[Depends(require_permission("pos.manage"))])
def update_kitchen_status(ko_id: int, data: dict, request: Request, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    new_status = data.get("status")
    ts_field = {"accepted": "accepted_at", "ready": "ready_at", "served": "served_at"}.get(new_status)
    if ts_field:
        db.execute(text(f"UPDATE pos_kitchen_orders SET status = :s, {ts_field} = NOW() WHERE id = :id"), {"s": new_status, "id": ko_id})
    else:
        db.execute(text("UPDATE pos_kitchen_orders SET status = :s WHERE id = :id"), {"s": new_status, "id": ko_id})
    db.commit()
    log_activity(
        db=db,
        user_id=current_user.id,
        action="kitchen_status_changed",
        resource_type="pos_kitchen_order",
        resource_id=ko_id,
        details={"new_status": new_status},
        request=request,
    )
    return {"message": f"Kitchen order {ko_id} → {new_status}"}


# ===================== B7: PWA Support =====================

@router.get("/pwa/manifest")
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


@router.get("/pwa/config")
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
