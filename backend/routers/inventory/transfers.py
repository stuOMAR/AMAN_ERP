"""
Inventory Module - Stock Transfers (Single-item with GL + Multi-item)
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from utils.i18n import http_error
from sqlalchemy import text
from datetime import datetime
from decimal import Decimal
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.audit import log_activity
from utils.permissions import require_permission
from services.gl_service import create_journal_entry as gl_create_journal_entry
from utils.fiscal_lock import check_fiscal_period_open
from .schemas import StockTransferSingleCreate, StockTransferCreate

transfers_router = APIRouter()
logger = logging.getLogger(__name__)


@transfers_router.post("/transfers", dependencies=[Depends(require_permission("stock.adjustment"))])
def create_stock_transfer(
    transfer: StockTransferSingleCreate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """تحويل مخزني مباشر بين المستودعات مع تطبيق سياسة التكلفة"""

    db = get_db_connection(current_user.company_id)
    try:
        from utils.accounting import get_base_currency
        base_currency = get_base_currency(db)
        user_id = current_user.id

        # 1. Validate source and destination are different
        if transfer.source_warehouse_id == transfer.destination_warehouse_id:
            raise HTTPException(status_code=400, detail="لا يمكن التحويل لنفس المستودع")

        # 2. Check warehouses exist
        src_wh = db.execute(text("SELECT warehouse_name FROM warehouses WHERE id = :id"),
                           {"id": transfer.source_warehouse_id}).fetchone()
        dst_wh = db.execute(text("SELECT warehouse_name FROM warehouses WHERE id = :id"),
                           {"id": transfer.destination_warehouse_id}).fetchone()

        if not src_wh:
            raise HTTPException(status_code=404, detail="المستودع المصدر غير موجود")
        if not dst_wh:
            raise HTTPException(status_code=404, detail="المستودع الوجهة غير موجود")

        # INV-006: Check branch access on both warehouses
        allowed = getattr(current_user, 'allowed_branches', []) or []
        if allowed and "*" not in getattr(current_user, 'permissions', []):
            src_branch = db.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": transfer.source_warehouse_id}).scalar()
            dst_branch = db.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": transfer.destination_warehouse_id}).scalar()
            if (src_branch and src_branch not in allowed) or (dst_branch and dst_branch not in allowed):
                raise HTTPException(status_code=403, detail="لا يمكنك التحويل بين مستودعات خارج فروعك")

        # 3. Check product exists
        product = db.execute(text("SELECT product_name FROM products WHERE id = :id"),
                            {"id": transfer.product_id}).fetchone()
        if not product:
            raise HTTPException(**http_error(404, "product_not_found"))

        # 4. Check available stock in source — lock row to prevent phantom stock
        source_inv = db.execute(text("""
            SELECT quantity, average_cost FROM inventory 
            WHERE product_id = :pid AND warehouse_id = :wh
            FOR UPDATE
        """), {"pid": transfer.product_id, "wh": transfer.source_warehouse_id}).fetchone()

        transfer_qty = Decimal(str(transfer.quantity))
        source_qty = Decimal(str(source_inv.quantity)) if source_inv else Decimal("0")
        source_cost = Decimal(str(source_inv.average_cost or 0)) if source_inv else Decimal("0")

        if source_qty < transfer_qty:
            raise HTTPException(
                status_code=400,
                detail=f"الكمية المتوفرة ({source_qty}) أقل من المطلوب ({transfer.quantity})"
            )

        # 5. Get destination current state — lock row to ensure consistent WAC
        dest_inv = db.execute(text("""
            SELECT quantity, average_cost FROM inventory 
            WHERE product_id = :pid AND warehouse_id = :wh
            FOR UPDATE
        """), {"pid": transfer.product_id, "wh": transfer.destination_warehouse_id}).fetchone()

        dest_qty_before = Decimal(str(dest_inv.quantity)) if dest_inv else Decimal("0")
        dest_cost_before = Decimal(str(dest_inv.average_cost or 0)) if dest_inv else Decimal("0")

        # 6. Update source inventory (decrease)
        db.execute(text("""
            UPDATE inventory SET quantity = quantity - :qty, updated_at = NOW()
            WHERE product_id = :pid AND warehouse_id = :wh
        """), {"qty": transfer.quantity, "pid": transfer.product_id, "wh": transfer.source_warehouse_id})

        # 7. Update destination inventory (increase with WAC calculation)
        if dest_inv:
            # Calculate new weighted average cost
            new_total_qty = dest_qty_before + transfer_qty
            if new_total_qty > 0:
                new_avg_cost = ((dest_qty_before * dest_cost_before) + (transfer_qty * source_cost)) / new_total_qty
            else:
                new_avg_cost = source_cost

            db.execute(text("""
                UPDATE inventory 
                SET quantity = :qty, average_cost = :cost, updated_at = NOW()
                WHERE product_id = :pid AND warehouse_id = :wh
            """), {
                "qty": float(new_total_qty),
                "cost": float(new_avg_cost),
                "pid": transfer.product_id,
                "wh": transfer.destination_warehouse_id
            })
        else:
            # Insert new inventory record with source cost
            db.execute(text("""
                INSERT INTO inventory (product_id, warehouse_id, quantity, average_cost, updated_at)
                VALUES (:pid, :wh, :qty, :cost, NOW())
            """), {
                "pid": transfer.product_id,
                "wh": transfer.destination_warehouse_id,
                "qty": transfer.quantity,
                "cost": float(source_cost)
            })
            new_avg_cost = source_cost

        # 8. Log transactions
        db.execute(text("""
            INSERT INTO inventory_transactions (product_id, warehouse_id, transaction_type, 
                                               reference_type, quantity, notes, created_by)
            VALUES (:pid, :wh, 'transfer_out', 'transfer', :qty, :notes, :user)
        """), {
            "pid": transfer.product_id,
            "wh": transfer.source_warehouse_id,
            "qty": -transfer.quantity,
            "notes": transfer.notes or f"تحويل إلى {dst_wh.warehouse_name}",
            "user": user_id
        })

        db.execute(text("""
            INSERT INTO inventory_transactions (product_id, warehouse_id, transaction_type, 
                                               reference_type, quantity, notes, created_by)
            VALUES (:pid, :wh, 'transfer_in', 'transfer', :qty, :notes, :user)
        """), {
            "pid": transfer.product_id,
            "wh": transfer.destination_warehouse_id,
            "qty": transfer.quantity,
            "notes": transfer.notes or f"تحويل من {src_wh.warehouse_name}",
            "user": user_id
        })

        # 9. Log in stock_transfer_log for V2 tracking
        db.execute(text("""
            INSERT INTO stock_transfer_log 
            (product_id, from_warehouse_id, to_warehouse_id, quantity, transfer_cost, 
             from_avg_cost_before, to_avg_cost_before, to_avg_cost_after)
            VALUES (:pid, :fwh, :twh, :qty, :tcost, :fcast, :tcast_b, :tcast_a)
        """), {
            "pid": transfer.product_id,
            "fwh": transfer.source_warehouse_id,
            "twh": transfer.destination_warehouse_id,
            "qty": transfer.quantity,
            "tcost": float(source_cost),
            "fcast": float(source_cost),
            "tcast_b": float(dest_cost_before),
            "tcast_a": float(new_avg_cost)
        })

        # 9b. Create GL Journal Entry for warehouse transfer via GL service
        src_branch = db.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": transfer.source_warehouse_id}).scalar()
        dst_branch = db.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": transfer.destination_warehouse_id}).scalar()

        transfer_value = float(transfer_qty * source_cost)
        if transfer_value > 0.01:
            from utils.accounting import get_mapped_account_id

            acc_inventory = get_mapped_account_id(db, "acc_map_inventory")

            if acc_inventory:
                transfer_date = datetime.now().strftime("%Y-%m-%d")
                # Fiscal-period lock: block posting into a closed period.
                check_fiscal_period_open(db, transfer_date)
                lines = [
                    {"account_id": acc_inventory, "debit": transfer_value, "credit": 0, "description": f"Transfer In - {dst_wh.warehouse_name}"},
                    {"account_id": acc_inventory, "debit": 0, "credit": transfer_value, "description": f"Transfer Out - {src_wh.warehouse_name}"},
                ]
                gl_create_journal_entry(
                    db,
                    company_id=current_user.company_id,
                    date=transfer_date,
                    description=f"تحويل مخزني: {src_wh.warehouse_name} → {dst_wh.warehouse_name}",
                    lines=lines,
                    user_id=user_id,
                    branch_id=src_branch or dst_branch,
                    reference=f"TRF-{transfer.product_id}",
                    currency=base_currency,
                )

        # 10. Log activity
        log_activity(
            db,
            user_id=user_id,
            username=current_user.username if hasattr(current_user, 'username') else None,
            action="stock.transfer",
            resource_type="stock_transfer",
            resource_id=str(transfer.product_id),
            details={"product": product.product_name, "qty": transfer.quantity, "from": src_wh.warehouse_name, "to": dst_wh.warehouse_name},
            request=request,
            branch_id=src_branch
        )

        db.commit()

        return {
            "message": "تم التحويل بنجاح",
            "transfer_details": {
                "product_name": product.product_name,
                "quantity": transfer.quantity,
                "source_warehouse": src_wh.warehouse_name,
                "destination_warehouse": dst_wh.warehouse_name,
                "transfer_cost": float(source_cost),
                "new_destination_avg_cost": float(new_avg_cost)
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Stock transfer error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@transfers_router.post("/transfer", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("stock.transfer"))])
def transfer_stock(
    transfer: StockTransferCreate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """نقل مخزون بين المستودعات (متعدد الأصناف)"""
    db = get_db_connection(current_user.company_id)
    try:
        if transfer.source_warehouse_id == transfer.destination_warehouse_id:
            raise HTTPException(status_code=400, detail="لا يمكن النقل لنفس المستودع")

        # Validate warehouses exist
        src = db.execute(text("SELECT warehouse_name FROM warehouses WHERE id = :id"), {"id": transfer.source_warehouse_id}).fetchone()
        dst = db.execute(text("SELECT warehouse_name FROM warehouses WHERE id = :id"), {"id": transfer.destination_warehouse_id}).fetchone()

        if not src or not dst:
            raise HTTPException(**http_error(404, "warehouse_not_found"))

        # INV-006: Check branch access on both warehouses
        allowed = getattr(current_user, 'allowed_branches', []) or []
        if allowed and "*" not in getattr(current_user, 'permissions', []):
            src_branch = db.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": transfer.source_warehouse_id}).scalar()
            dst_branch = db.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": transfer.destination_warehouse_id}).scalar()
            if (src_branch and src_branch not in allowed) or (dst_branch and dst_branch not in allowed):
                raise HTTPException(status_code=403, detail="لا يمكنك النقل بين مستودعات خارج فروعك")

        transfer_ref = f"TRF-{datetime.now().strftime('%Y%m%d')}-{__import__('uuid').uuid4().hex[:8].upper()}"

        # INV-L04: Validate fiscal period is open before any inventory/GL movement.
        from utils.fiscal_lock import check_fiscal_period_open
        transfer_date = datetime.now().strftime("%Y-%m-%d")
        check_fiscal_period_open(db, transfer_date)

        # Aggregate total transfer value for GL posting after the loop.
        total_transfer_value = 0.0
        item_descriptions: list[str] = []

        for item in transfer.items:
            # INV-009: Check source stock with FOR UPDATE to prevent race conditions
            src_inv = db.execute(text("""
                SELECT quantity, average_cost FROM inventory 
                WHERE product_id = :pid AND warehouse_id = :wh
                FOR UPDATE
            """), {"pid": item.product_id, "wh": transfer.source_warehouse_id}).fetchone()

            current_qty = float(src_inv.quantity) if src_inv else 0

            if current_qty < item.quantity:
                prod_name = db.execute(text("SELECT product_name FROM products WHERE id = :pid"), {"pid": item.product_id}).scalar()
                raise HTTPException(status_code=400, detail=f"الكمية غير متوفرة للمنتج: {prod_name}")

            # 1. Get source cost for WAC calculation
            source_cost = float(src_inv.average_cost or 0) if src_inv else 0

            # Track aggregate GL value (INV-L04)
            total_transfer_value += float(item.quantity) * source_cost

            # 2. Deduct from Source
            db.execute(text("""
                UPDATE inventory SET quantity = quantity - :qty 
                WHERE product_id = :pid AND warehouse_id = :wh
            """), {"qty": item.quantity, "pid": item.product_id, "wh": transfer.source_warehouse_id})

            # 3. Add to Destination with WAC recalculation
            exists_dest = db.execute(text("""
                SELECT quantity, average_cost FROM inventory WHERE product_id = :pid AND warehouse_id = :wh
            """), {"pid": item.product_id, "wh": transfer.destination_warehouse_id}).fetchone()

            if exists_dest:
                dest_qty = float(exists_dest.quantity or 0)
                dest_cost = float(exists_dest.average_cost or 0)
                new_total_qty = dest_qty + item.quantity
                if new_total_qty > 0:
                    new_avg_cost = ((dest_qty * dest_cost) + (item.quantity * source_cost)) / new_total_qty
                else:
                    new_avg_cost = source_cost
                db.execute(text("""
                    UPDATE inventory SET quantity = :qty, average_cost = :cost
                    WHERE product_id = :pid AND warehouse_id = :wh
                """), {"qty": new_total_qty, "cost": new_avg_cost, "pid": item.product_id, "wh": transfer.destination_warehouse_id})
            else:
                db.execute(text("""
                    INSERT INTO inventory (product_id, warehouse_id, quantity, average_cost)
                    VALUES (:pid, :wh, :qty, :cost)
                """), {"pid": item.product_id, "wh": transfer.destination_warehouse_id, "qty": item.quantity, "cost": source_cost})

            # 3. Log Transactions
            db.execute(text("""
                INSERT INTO inventory_transactions (
                    product_id, warehouse_id, transaction_type, reference_type, 
                    quantity, notes, created_by
                ) VALUES (
                    :pid, :wh, 'transfer_out', 'transfer', 
                    :qty, :notes, :user
                )
            """), {
                "pid": item.product_id,
                "wh": transfer.source_warehouse_id,
                "qty": -item.quantity,
                "notes": f"Transfer to {dst.warehouse_name} ({transfer_ref})",
                "user": current_user.id
            })

            db.execute(text("""
                INSERT INTO inventory_transactions (
                    product_id, warehouse_id, transaction_type, reference_type, 
                    quantity, notes, created_by
                ) VALUES (
                    :pid, :wh, 'transfer_in', 'transfer', 
                    :qty, :notes, :user
                )
            """), {
                "pid": item.product_id,
                "wh": transfer.destination_warehouse_id,
                "qty": item.quantity,
                "notes": f"Transfer from {src.warehouse_name} ({transfer_ref})",
                "user": current_user.id
            })

        # INV-L04: Emit one aggregate GL journal entry covering all items in this
        # multi-item transfer (debit destination-side inventory, credit source-side
        # inventory, both using the same acc_map_inventory account — the goods are
        # just moving between locations, not changing book value).
        if total_transfer_value > 0.01:
            from utils.accounting import get_mapped_account_id
            acc_inventory = get_mapped_account_id(db, "acc_map_inventory")
            if acc_inventory:
                src_branch_id = db.execute(
                    text("SELECT branch_id FROM warehouses WHERE id = :id"),
                    {"id": transfer.source_warehouse_id},
                ).scalar()
                dst_branch_id = db.execute(
                    text("SELECT branch_id FROM warehouses WHERE id = :id"),
                    {"id": transfer.destination_warehouse_id},
                ).scalar()
                base_currency = db.execute(
                    text("SELECT currency FROM companies WHERE id = :cid"),
                    {"cid": current_user.company_id},
                ).scalar() or "SAR"
                lines = [
                    {
                        "account_id": acc_inventory,
                        "debit": total_transfer_value,
                        "credit": 0,
                        "description": f"Transfer In - {dst.warehouse_name}",
                    },
                    {
                        "account_id": acc_inventory,
                        "debit": 0,
                        "credit": total_transfer_value,
                        "description": f"Transfer Out - {src.warehouse_name}",
                    },
                ]
                gl_create_journal_entry(
                    db,
                    company_id=current_user.company_id,
                    date=transfer_date,
                    description=f"تحويل مخزني ({len(transfer.items)} صنف): {src.warehouse_name} → {dst.warehouse_name}",
                    lines=lines,
                    user_id=current_user.id,
                    branch_id=src_branch_id or dst_branch_id,
                    reference=transfer_ref,
                    currency=base_currency,
                )

        db.commit()

        # AUDIT LOG
        log_activity(
            db,
            user_id=current_user.id,
            username=current_user.username,
            action="stock.transfer",
            resource_type="stock_transfer",
            resource_id=transfer_ref,
            details={"from": transfer.source_warehouse_id, "to": transfer.destination_warehouse_id, "items_count": len(transfer.items)},
            request=request,
            branch_id=db.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": transfer.source_warehouse_id}).scalar()
        )

        return {"message": "تم نقل المخزون بنجاح", "reference": transfer_ref}

    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
