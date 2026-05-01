"""
Inventory Module - Stock Movements (T6.5).

The legacy ``/receipt`` and ``/delivery`` endpoints have been removed
(they mutated inventory without GL posting). All movements MUST go through
``/adjustment`` which posts a balanced JE via ``gl_service.create_journal_entry``
and runs the fiscal-lock check, gated by ``stock.adjust`` permission.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from utils.i18n import http_error
from sqlalchemy import text
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.audit import log_activity
from utils.permissions import require_permission

stock_movements_router = APIRouter()
logger = logging.getLogger(__name__)


# Legacy /receipt and /delivery endpoints removed in T6.5 — use /adjustment.


# ==========================================================================
# INV-F1: Stock adjustment with mandatory GL posting (Phase-11 Sprint-5)
# ==========================================================================

from pydantic import BaseModel, Field
from typing import List as _List, Optional as _Optional


class StockAdjustmentItem(BaseModel):
    product_id: int
    warehouse_id: int
    quantity_delta: float  # positive = stock_in, negative = stock_out
    unit_cost: float = Field(..., gt=0)
    reason: _Optional[str] = None


class StockAdjustmentCreate(BaseModel):
    adjustment_account_id: int  # P&L account (gain/loss on inventory)
    inventory_account_id: _Optional[int] = None  # Override; else from company_settings
    reference: _Optional[str] = None
    notes: _Optional[str] = None
    date: _Optional[str] = None
    items: _List[StockAdjustmentItem]


@stock_movements_router.post(
    "/adjustment",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("stock.adjust"))],
)
def create_stock_adjustment(
    adjustment: StockAdjustmentCreate,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """تسوية مخزون مع ترحيل محاسبي إلزامي (INV-F1).

    Unlike the legacy /receipt and /delivery endpoints, every adjustment here
    MUST post a balanced journal entry through ``gl_service.create_journal_entry``
    so inventory value and ledger balances stay reconciled.
    """
    from utils.accounting import get_mapped_account_id
    from services import gl_service
    from utils.fiscal_lock import check_fiscal_period_open

    if not adjustment.items:
        raise HTTPException(**http_error(400, "no_items"))

    db = get_db_connection(current_user.company_id)
    try:
        # Resolve inventory control account
        inv_account_id = adjustment.inventory_account_id
        if inv_account_id is None:
            inv_account_id = get_mapped_account_id(db, "acc_map_inventory")
        if not inv_account_id:
            raise HTTPException(**http_error(400, "inventory_account_not_mapped"))

        # Validate adjustment account exists
        acc_check = db.execute(
            text("SELECT id FROM accounts WHERE id = :id"),
            {"id": adjustment.adjustment_account_id},
        ).fetchone()
        if not acc_check:
            raise HTTPException(**http_error(404, "adjustment_account_not_found"))

        txn_date = adjustment.date or datetime.now().strftime("%Y-%m-%d")
        check_fiscal_period_open(db, txn_date)

        ref = adjustment.reference or f"ADJ-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"

        # UOM guard
        from utils.quantity_validation import validate_quantity_for_product
        net_value_delta = Decimal("0")
        for item in adjustment.items:
            validate_quantity_for_product(db, item.product_id, abs(item.quantity_delta))
            # Resolve warehouse
            wh = db.execute(
                text("SELECT branch_id FROM warehouses WHERE id = :id"),
                {"id": item.warehouse_id},
            ).fetchone()
            if not wh:
                raise HTTPException(**http_error(404, "warehouse_not_found"))

            # Enforce non-negative stock on decreases
            if item.quantity_delta < 0:
                current_qty = db.execute(
                    text(
                        "SELECT COALESCE(quantity, 0) FROM inventory "
                        "WHERE product_id = :pid AND warehouse_id = :wh"
                    ),
                    {"pid": item.product_id, "wh": item.warehouse_id},
                ).scalar() or 0
                if float(current_qty) + item.quantity_delta < 0:
                    raise HTTPException(**http_error(400, "insufficient_stock"))

            # Upsert inventory quantity
            exists = db.execute(
                text(
                    "SELECT 1 FROM inventory WHERE product_id = :pid AND warehouse_id = :wh"
                ),
                {"pid": item.product_id, "wh": item.warehouse_id},
            ).scalar()
            if exists:
                db.execute(
                    text(
                        "UPDATE inventory SET quantity = quantity + :qty "
                        "WHERE product_id = :pid AND warehouse_id = :wh"
                    ),
                    {"qty": item.quantity_delta, "pid": item.product_id, "wh": item.warehouse_id},
                )
            else:
                db.execute(
                    text(
                        "INSERT INTO inventory (product_id, warehouse_id, quantity) "
                        "VALUES (:pid, :wh, :qty)"
                    ),
                    {"pid": item.product_id, "wh": item.warehouse_id, "qty": item.quantity_delta},
                )

            # Log transaction
            db.execute(
                text(
                    """
                    INSERT INTO inventory_transactions
                        (product_id, warehouse_id, transaction_type, reference_type,
                         quantity, notes, created_by, created_at)
                    VALUES (:pid, :wh, :tt, 'adjustment', :qty, :notes, :user, :date)
                    """
                ),
                {
                    "pid": item.product_id,
                    "wh": item.warehouse_id,
                    "tt": "stock_in" if item.quantity_delta >= 0 else "stock_out",
                    "qty": abs(item.quantity_delta),
                    "notes": f"Stock Adjustment {ref} - {item.reason or adjustment.notes or ''}",
                    "user": current_user.id,
                    "date": txn_date,
                },
            )

            net_value_delta += Decimal(str(item.quantity_delta)) * Decimal(str(item.unit_cost))

        # Post balanced JE
        net_value = net_value_delta.quantize(Decimal("0.01"))
        if abs(net_value) > Decimal("0.005"):
            if net_value > 0:
                # Stock increased → DR Inventory / CR Adjustment (gain)
                lines = [
                    {"account_id": inv_account_id, "debit": float(net_value), "credit": 0, "description": f"Stock adjustment gain {ref}"},
                    {"account_id": adjustment.adjustment_account_id, "debit": 0, "credit": float(net_value), "description": f"Stock adjustment gain {ref}"},
                ]
            else:
                # Stock decreased → DR Adjustment (loss) / CR Inventory
                abs_val = float(-net_value)
                lines = [
                    {"account_id": adjustment.adjustment_account_id, "debit": abs_val, "credit": 0, "description": f"Stock adjustment loss {ref}"},
                    {"account_id": inv_account_id, "debit": 0, "credit": abs_val, "description": f"Stock adjustment loss {ref}"},
                ]
            gl_service.create_journal_entry(
                db,
                company_id=current_user.company_id,
                date=txn_date,
                description=f"Stock Adjustment {ref}",
                lines=lines,
                user_id=current_user.id,
                reference=ref,
                source="StockAdjustment",
                source_id=None,
                username=getattr(current_user, "username", None),
                idempotency_key=f"stock_adj:{ref}",
            )

        db.commit()
        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="stock.adjust", resource_type="stock_movement",
            resource_id=ref,
            details={
                "items_count": len(adjustment.items),
                "net_value_delta": float(net_value_delta),
                "adjustment_account_id": adjustment.adjustment_account_id,
            },
            request=request,
        )
        return {"message": "تمت تسوية المخزون مع ترحيل القيد بنجاح", "reference": ref, "net_value_delta": float(net_value_delta)}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Stock adjustment failed")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
