"""
Inventory Module - Stock Movements (T6.5).

The legacy ``/receipt`` and ``/delivery`` endpoints have been removed
(they mutated inventory without GL posting). All movements MUST go through
``/adjustment`` which posts a balanced JE via ``gl_service.create_journal_entry``
and runs the fiscal-lock check, gated by ``stock.adjust`` permission.
"""

from datetime import datetime
from decimal import Decimal
import uuid
import logging
from typing import List as _List, Optional as _Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from utils.i18n import http_error

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
    """تسوية مخزون مع ترحيل محاسبي إلزامي (INV-F1) — T050: calls shared helper."""
    from utils.accounting import get_mapped_account_id
    from utils.fiscal_lock import check_fiscal_period_open
    from routers.inventory.adjustments import post_inventory_adjustment

    if not adjustment.items:
        raise HTTPException(**http_error(400, "no_items"))

    db = get_db_connection(current_user.company_id)
    try:
        # Validate adjustment account exists
        acc_check = db.execute(
            text("SELECT id FROM accounts WHERE id = :id"),
            {"id": adjustment.adjustment_account_id},
        ).fetchone()
        if not acc_check:
            raise HTTPException(**http_error(404, "adjustment_account_not_found"))

        # Resolve inventory account
        inv_account_id = adjustment.inventory_account_id
        if inv_account_id is None:
            inv_account_id = get_mapped_account_id(db, "acc_map_inventory")
        if not inv_account_id:
            raise HTTPException(**http_error(400, "inventory_account_not_mapped"))

        txn_date = adjustment.date or datetime.now().strftime("%Y-%m-%d")

        # T050: Validate warehouses exist
        for item in adjustment.items:
            wh = db.execute(
                text("SELECT branch_id FROM warehouses WHERE id = :id"),
                {"id": item.warehouse_id},
            ).fetchone()
            if not wh:
                raise HTTPException(**http_error(404, "warehouse_not_found"))

        # T050: Call shared helper — supports multi-item + explicit adjustment_account_id
        result = post_inventory_adjustment(
            db,
            items=[
                {
                    "product_id": item.product_id,
                    "warehouse_id": item.warehouse_id,
                    "quantity_delta": item.quantity_delta,
                    "unit_cost": item.unit_cost,
                    "reason": item.reason,
                }
                for item in adjustment.items
            ],
            adjustment_account_id=adjustment.adjustment_account_id,
            inventory_account_id=inv_account_id,
            reference=adjustment.reference,
            notes=adjustment.notes,
            txn_date=txn_date,
            user_id=current_user.id,
            username=getattr(current_user, "username", None),
            company_id=current_user.company_id,
            request=request,
        )

        db.commit()
        return {
            "message": i18n_message("inventory_adjustment_success", request),
            "reference": result["reference"],
            "net_value_delta": result["net_value_delta"],
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Stock adjustment failed")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
