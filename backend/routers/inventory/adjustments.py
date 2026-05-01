"""
Inventory Module - Stock Adjustments
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.audit import log_activity
from utils.permissions import require_permission
from utils.fiscal_lock import check_fiscal_period_open
from services.gl_service import create_journal_entry as gl_create_journal_entry
from .schemas import StockAdjustmentCreate

adjustments_router = APIRouter()
logger = logging.getLogger(__name__)


@adjustments_router.get("/adjustments", response_model=List[dict], dependencies=[Depends(require_permission("stock.view"))])
def list_adjustments(
    branch_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(get_current_user)
):
    """عرض قائمة تسويات الجرد"""
    db = get_db_connection(current_user.company_id)
    try:
        query = """
            SELECT sa.id, sa.adjustment_number, sa.adjustment_type, sa.reason, 
                   sa.created_at, sa.status, sa.difference,
                   w.warehouse_name, p.product_name
            FROM stock_adjustments sa
            JOIN warehouses w ON sa.warehouse_id = w.id
            JOIN products p ON sa.product_id = p.id
            WHERE 1=1
        """
        params = {"limit": limit, "skip": skip}

        if branch_id:
            query += " AND w.branch_id = :branch_id"
            params["branch_id"] = branch_id
        else:
            # INV-004: Enforce allowed_branches
            allowed = getattr(current_user, 'allowed_branches', []) or []
            if allowed and "*" not in getattr(current_user, 'permissions', []):
                branch_placeholders = ", ".join(f":_ab_{i}" for i in range(len(allowed)))
                query += f" AND w.branch_id IN ({branch_placeholders})"
                for i, bid in enumerate(allowed):
                    params[f"_ab_{i}"] = bid

        query += " ORDER BY sa.created_at DESC LIMIT :limit OFFSET :skip"
        result = db.execute(text(query), params).fetchall()

        adjustments = []
        for row in result:
            adjustments.append({
                "id": row.id,
                "adjustment_number": row.adjustment_number,
                "type": row.adjustment_type,
                "reason": row.reason,
                "created_at": row.created_at,
                "status": row.status,
                "difference": row.difference,
                "warehouse_name": row.warehouse_name,
                "product_name": row.product_name
            })
        return adjustments
    finally:
        db.close()


@adjustments_router.post("/adjustments", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("stock.adjustment"))], response_model=Dict[str, Any])
def create_adjustment(
    data: StockAdjustmentCreate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """إنشاء تسوية جردية (تعديل الكمية يدوياً)"""
    db = get_db_connection(current_user.company_id)
    try:
        # Get base currency
        from utils.accounting import get_base_currency
        base_currency = get_base_currency(db)
        # Get user info safely
        user_id = current_user.id if hasattr(current_user, 'id') else current_user.get('id')
        username = current_user.username if hasattr(current_user, 'username') else current_user.get('username')
        company_id = current_user.company_id if hasattr(current_user, 'company_id') else current_user.get('company_id')

        # INV-005: Check warehouse branch access
        wh_branch = db.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": data.warehouse_id}).scalar()
        allowed = getattr(current_user, 'allowed_branches', []) or []
        if allowed and "*" not in getattr(current_user, 'permissions', []):
            if wh_branch and wh_branch not in allowed:
                raise HTTPException(status_code=403, detail="لا يمكنك إجراء تسوية على مستودع خارج فروعك")

        # 1. Get Current Stock
        stock_query = """
            SELECT quantity FROM inventory 
            WHERE product_id = :pid AND warehouse_id = :wh
        """
        current_qty = db.execute(text(stock_query), {"pid": data.product_id, "wh": data.warehouse_id}).scalar() or 0.0

        difference = data.new_quantity - float(current_qty)

        if difference == 0:
            raise HTTPException(status_code=400, detail="الكمية الجديدة تطابق الكمية الحالية، لا يوجد تعديل")

        # Prevent negative stock
        if data.new_quantity < 0:
            raise HTTPException(status_code=400, detail="لا يمكن تعيين كمية المخزون بقيمة سالبة")

        adjustment_type = 'increase' if difference > 0 else 'decrease'

        # 2. Generate Number (unique via MAX)
        year = datetime.now().year
        max_num = db.execute(text("""
            SELECT MAX(CAST(SUBSTRING(adjustment_number FROM 'ADJ-\\d{4}-(\\d+)') AS INTEGER))
            FROM stock_adjustments 
            WHERE adjustment_number LIKE :pattern
        """), {"pattern": f"ADJ-{year}-%"}).scalar() or 0
        adj_number = f"ADJ-{year}-{str(max_num + 1).zfill(4)}"

        # 3. Create Adjustment Record
        adj_id_result = db.execute(text("""
            INSERT INTO stock_adjustments (
                adjustment_number, warehouse_id, product_id,
                adjustment_type, reason, old_quantity, new_quantity, difference,
                notes, status, created_by
            ) VALUES (
                :num, :wh, :pid,
                :type, :reason, :old, :new, :diff,
                :notes, 'approved', :uid
            ) RETURNING id
        """), {
            "num": adj_number, "wh": data.warehouse_id, "pid": data.product_id,
            "type": adjustment_type, "reason": data.reason,
            "old": current_qty, "new": data.new_quantity, "diff": difference,
            "notes": data.notes, "uid": user_id
        }).fetchone()

        if not adj_id_result:
            raise Exception("Failed to insert stock adjustment record")

        adj_id = adj_id_result[0]

        # 4. Update Inventory
        exists = db.execute(text("SELECT 1 FROM inventory WHERE product_id=:pid AND warehouse_id=:wh"),
                           {"pid": data.product_id, "wh": data.warehouse_id}).scalar()

        if exists:
            db.execute(text("""
                UPDATE inventory 
                SET quantity = :new_qty, last_movement_date = NOW()
                WHERE product_id = :pid AND warehouse_id = :wh
            """), {"new_qty": data.new_quantity, "pid": data.product_id, "wh": data.warehouse_id})
        else:
            db.execute(text("""
                INSERT INTO inventory (product_id, warehouse_id, quantity, last_movement_date)
                VALUES (:pid, :wh, :new_qty, NOW())
            """), {"pid": data.product_id, "wh": data.warehouse_id, "new_qty": data.new_quantity})

        # 5. Log Transaction
        trans_type = 'adjustment_in' if difference > 0 else 'adjustment_out'

        db.execute(text("""
            INSERT INTO inventory_transactions (
                product_id, warehouse_id, transaction_type, 
                reference_type, reference_id, reference_document,
                quantity, notes, created_by
            ) VALUES (
                :pid, :wh, :type,
                'adjustment', :ref_id, :doc_num,
                :qty, :notes, :uid
            )
        """), {
            "pid": data.product_id, "wh": data.warehouse_id, "type": trans_type,
            "ref_id": adj_id, "doc_num": adj_number,
            "qty": difference, "notes": data.notes or f"Stock Adjustment {adjustment_type}",
            "uid": user_id
        })

        # 6. Create GL Journal Entry for Inventory Adjustment via GL Service
        from utils.accounting import get_mapped_account_id
        acc_inventory = get_mapped_account_id(db, "acc_map_inventory")
        acc_adjustment = get_mapped_account_id(db, "acc_map_inventory_adjustment")

        if acc_inventory and acc_adjustment:
            cost_price = db.execute(text("SELECT cost_price FROM products WHERE id = :id"), {"id": data.product_id}).scalar() or 0
            adjustment_value = abs(difference) * float(cost_price)

            if adjustment_value > 0.01:
                # Fiscal lock check (T019 fix — was bypassing fiscal lock)
                check_fiscal_period_open(db, datetime.now().date())

                branch_id = db.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": data.warehouse_id}).scalar()

                if difference > 0:
                    lines = [
                        {"account_id": acc_inventory, "debit": adjustment_value, "credit": 0, "description": f"Inventory Increase - {adj_number}"},
                        {"account_id": acc_adjustment, "debit": 0, "credit": adjustment_value, "description": f"Adjustment Gain - {adj_number}"},
                    ]
                else:
                    lines = [
                        {"account_id": acc_adjustment, "debit": adjustment_value, "credit": 0, "description": f"Adjustment Loss - {adj_number}"},
                        {"account_id": acc_inventory, "debit": 0, "credit": adjustment_value, "description": f"Inventory Decrease - {adj_number}"},
                    ]

                gl_create_journal_entry(
                    db,
                    company_id=company_id,
                    date=datetime.now().strftime("%Y-%m-%d"),
                    description=f"Stock Adjustment - {adj_number}",
                    lines=lines,
                    user_id=user_id,
                    branch_id=branch_id,
                    reference=adj_number,
                    currency=base_currency,
                )

        db.commit()

        # AUDIT LOG
        try:
            branch_id = db.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": data.warehouse_id}).scalar()

            log_activity(
                db,
                user_id=user_id,
                username=username,
                action="stock.adjustment",
                resource_type="stock_adjustment",
                resource_id=str(adj_id),
                details={"adjustment_number": adj_number, "product_id": data.product_id, "difference": difference},
                request=request,
                branch_id=branch_id
            )
        except Exception as audit_err:
            logger.warning(f"Audit logging failed: {audit_err}")

        # Notify about inventory adjustment
        try:
            prod_name = db.execute(text("SELECT name FROM products WHERE id = :id"), {"id": data.product_id}).scalar()
            db.execute(text("""
                INSERT INTO notifications (user_id, type, title, message, link, is_read, created_at)
                SELECT DISTINCT u.id, 'inventory', :title, :message, :link, FALSE, NOW()
                FROM company_users u
                WHERE u.is_active = TRUE AND u.role IN ('admin', 'superuser')
                AND u.id != :current_uid
            """), {
                "title": "📦 تسوية مخزون",
                "message": f"تسوية جرد {adj_number} — {prod_name or ''} — فرق: {difference:+}",
                "link": "/stock/adjustments",
                "current_uid": user_id
            })
            db.commit()
        except Exception:
            pass

        return {"id": adj_id, "message": "تم حفظ تسوية الجرد بنجاح"}

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        # SEC-T2.10: do not leak internal exception text to the client.
        logger.exception("Stock adjustment failed")
        raise HTTPException(status_code=500, detail="حدث خطأ أثناء حفظ التسوية")
    finally:
        db.close()
