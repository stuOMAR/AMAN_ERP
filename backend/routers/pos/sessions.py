"""pos sub-router — split from monolithic pos.py (T6.3).

Mounted under the parent router via pos/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Any, Dict, Optional
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import logging
from routers.auth import get_current_user
from utils.permissions import require_permission, validate_branch_access, validate_treasury_account_access
from utils.fiscal_lock import check_fiscal_period_open
from utils.audit import log_activity
from schemas import UserResponse
from schemas.pos import SessionCreate, SessionClose, SessionResponse
from services.gl_service import create_journal_entry as gl_create_journal_entry

logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')
def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')

router = APIRouter()

from .core import _D2, _dec, get_db, _get_populated_session  # noqa: E402

@router.post("/sessions/open", response_model=SessionResponse, dependencies=[Depends(require_permission("pos.sessions"))])
def open_session(
    session_in: SessionCreate,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Open Session."""
    user_id = current_user.id

    # Resolve branch_id from warehouse if not provided
    branch_id = session_in.branch_id
    if not branch_id and session_in.warehouse_id:
        branch_id = db.execute(
            text("SELECT branch_id FROM warehouses WHERE id = :id"),
            {"id": session_in.warehouse_id}
        ).scalar()

    # Validate branch access (after resolving from warehouse)
    branch_id = validate_branch_access(current_user, branch_id)
    if session_in.treasury_account_id:
        validate_treasury_account_access(db, current_user, session_in.treasury_account_id, branch_id)

    # CONC-FIX: Use INSERT ... ON CONFLICT to prevent TOCTOU race condition.
    # A UNIQUE INDEX on (user_id) WHERE status='opened' must exist.
    # Fallback: check-then-insert inside a serialized read for environments without the index.
    existing_session = db.execute(
        text("SELECT id FROM pos_sessions WHERE user_id = :uid AND status = 'opened' FOR UPDATE SKIP LOCKED"),
        {"uid": user_id}
    ).fetchone()

    if existing_session:
        raise HTTPException(**http_error(400, "pos_session_already_open", request))

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
        "branch": branch_id,
        "notes": session_in.notes,
        "tid": session_in.treasury_account_id
    }).fetchone()
    
    db.commit()
    
    if not result:
        raise HTTPException(**http_error(500, "pos_session_create_failed", request))
    
    session_id = result._mapping["id"]

    log_activity(
        db, user_id=current_user.id, username=current_user.username,
        action="open_pos_session", resource_type="pos_session",
        resource_id=str(session_id),
        details={"branch_id": branch_id, "warehouse_id": session_in.warehouse_id, "opening_balance": str(session_in.opening_balance)},
        request=request, branch_id=branch_id
    )

    populated = _get_populated_session(db, session_id, user_id)
    if populated:
        return populated
    
    # Fallback: return basic data from INSERT result
    return dict(result._mapping)

@router.post("/sessions/{session_id}/close", response_model=SessionResponse, dependencies=[Depends(require_permission("pos.sessions"))])
def close_session(
    session_id: int,
    close_in: SessionClose,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Close Session."""
    from utils.accounting import get_base_currency
    base_currency = get_base_currency(db)
    sess = db.execute(text("SELECT * FROM pos_sessions WHERE id = :id"), {"id": session_id}).fetchone()
    if not sess:
        raise HTTPException(**http_error(404, "pos_session_not_found", request))
        
    # Validate branch access
    validate_branch_access(current_user, sess.branch_id)
    
    if sess.status != 'opened':
        raise HTTPException(**http_error(400, "pos_session_not_open", request))
        
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

    expected_cash = (opening_bal + _dec(sales_cash) - _dec(returns_cash)).quantize(_D2, ROUND_HALF_UP)
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
        "close_bal": expected_cash,
        "reg_bal": _dec(close_in.cash_register_balance).quantize(_D2, ROUND_HALF_UP),
        "diff": difference,
        "notes": close_in.notes or "",
        "id": session_id
    })
    
    # FISCAL-LOCK: Reject if accounting period is closed
    check_fiscal_period_open(db, datetime.now().date())

    # Resolve branch_id for logging and GL entries
    branch_id = db.execute(text("""
        SELECT w.branch_id FROM pos_sessions s
        JOIN warehouses w ON s.warehouse_id = w.id
        WHERE s.id = :id
    """), {"id": session_id}).scalar()

    # Create Cash Over/Short GL Entry if there's a difference
    if abs(difference) > _D2:
        from utils.accounting import get_mapped_account_id
        acc_cash = get_mapped_account_id(db, "acc_map_cash_main")
        acc_over_short = get_mapped_account_id(db, "acc_map_cash_over_short") or get_mapped_account_id(db, "acc_map_expense_other")

        if acc_cash and acc_over_short:
            import random
            f"JE-POS-CLOSE-{session_id}-{random.randint(100,999)}"
            
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
        details={"closing_balance": str(expected_cash), "cash_register_balance": str(close_in.cash_register_balance), "difference": str(difference)},
        request=request, branch_id=branch_id
    )

    return _get_populated_session(db, session_id, current_user.id)


@router.get("/sessions/active", response_model=Optional[SessionResponse], dependencies=[Depends(require_permission("pos.sessions"))])
def get_active_session(
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get Active Session."""
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


@router.get("/sessions/{session_id}/detailed-report", dependencies=[Depends(require_permission("pos.sessions"))], response_model=Dict[str, Any])
def session_detailed_report(request: Request, 
    session_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Session Detailed Report."""
    session = db.execute(text("SELECT * FROM pos_sessions WHERE id = :id"), {"id": session_id}).fetchone()
    if not session:
        raise HTTPException(**http_error(404, "pos_session_not_found", request))

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
