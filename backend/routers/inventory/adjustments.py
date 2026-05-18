"""
Inventory Module - Stock Adjustments
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.audit import log_activity
from utils.i18n import http_error, i18n_message
from utils.permissions import branch_scope_filter_from_scope, require_permission, resolve_branch_scope
from utils.fiscal_lock import check_fiscal_period_open
from services.gl_service import create_journal_entry as gl_create_journal_entry
from .schemas import StockAdjustmentCreate

adjustments_router = APIRouter()
logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')


def post_inventory_adjustment(
    db,
    *,
    items: List[Dict[str, Any]],
    adjustment_account_id: Optional[int] = None,
    inventory_account_id: Optional[int] = None,
    reference: Optional[str] = None,
    reference_id: Optional[int] = None,
    notes: Optional[str] = None,
    txn_date: Optional[str] = None,
    user_id: Any = None,
    username: Any = None,
    company_id: Any = None,
    request: Request = None,
) -> Dict[str, Any]:
    """Shared adjustment posting helper (T046-T048).

    Handles row locks, quantity changes, inventory transaction rows, GL posting,
    fiscal lock, and audit within the caller's transaction.

    Each item dict must have: product_id, warehouse_id, quantity_delta (signed float).
    Optional per-item keys: unit_cost (float), reason (str).

    Returns dict with reference, net_value_delta, and items_processed.
    """
    from utils.accounting import get_mapped_account_id, get_base_currency

    base_currency = get_base_currency(db)
    txn_date = txn_date or datetime.now().strftime("%Y-%m-%d")
    check_fiscal_period_open(db, txn_date if isinstance(txn_date, str) else txn_date)

    # F-31: per-warehouse inventory account resolution. We use the resolver
    # later (one bucket per warehouse) so adjustments that span multiple
    # warehouses post a balanced entry that hits each warehouse's mapped
    # inventory account. The legacy behaviour (single global account) still
    # falls out when only one warehouse is involved or when warehouses share
    # the same mapping.
    from utils.inventory_accounts import resolve_warehouse_inventory_account

    # Adjustment account is global by design (P&L offset).
    adj_acc = adjustment_account_id or get_mapped_account_id(db, "acc_map_inventory_adjustment")
    if not adj_acc:
        raise HTTPException(**http_error(400, "adjustment_account_not_configured", request))

    # Probe at least one resolution upfront so the error is surfaced before
    # any item-level processing happens. The actual per-warehouse account is
    # resolved again per bucket below.
    if items:
        probe_wh = items[0].get("warehouse_id")
        probe_acc = inventory_account_id or resolve_warehouse_inventory_account(db, probe_wh)
        if not probe_acc:
            raise HTTPException(**http_error(400, "inventory_account_not_configured", request))

    if not reference:
        from uuid import uuid4
        reference = f"ADJ-{datetime.now().strftime('%Y%m%d')}-{uuid4().hex[:8].upper()}"

    # F-31: track net delta per warehouse so the GL entry can hit the right
    # per-warehouse inventory account.
    net_value_per_wh: dict[int, Decimal] = {}
    net_value_delta = Decimal("0")

    for item in items:
        pid = item["product_id"]
        wh = item["warehouse_id"]
        qty_delta = Decimal(str(item["quantity_delta"]))
        item_reason = item.get("reason", "")

        # T048: Lock inventory row FOR UPDATE before checking quantity
        stock_row = db.execute(text("""
            SELECT id, quantity, reserved_quantity, average_cost FROM inventory
            WHERE product_id = :pid AND warehouse_id = :wh
            FOR UPDATE
        """), {"pid": pid, "wh": wh}).fetchone()

        current_qty = Decimal(str(stock_row.quantity)) if stock_row else Decimal("0")
        reserved_qty = Decimal(str(stock_row.reserved_quantity or 0)) if stock_row else Decimal("0")

        # T048: Reject decreases that would make available quantity negative
        if qty_delta < 0 and (current_qty - reserved_qty) + qty_delta < 0:
            prod_name = db.execute(text("SELECT product_name FROM products WHERE id = :id"), {"id": pid}).scalar()
            raise HTTPException(
                status_code=400,
                detail=f"لا يمكن تقليل المخزون للمنتج {prod_name} إلى ما دون صفر. المتوفر: {current_qty - reserved_qty}"
            )

        # T048: Get cost from inventory.average_cost with fallback to products.cost_price
        wh_cost = Decimal(str(stock_row.average_cost or 0)) if stock_row else Decimal("0")
        if wh_cost <= 0:
            fallback = db.execute(text("SELECT cost_price FROM products WHERE id = :id"), {"id": pid}).scalar()
            wh_cost = Decimal(str(fallback or 0))
        # Allow per-item override if provided
        if "unit_cost" in item and item["unit_cost"] is not None:
            wh_cost = Decimal(str(item["unit_cost"]))

        from services.costing_service import CostingService
        costing_method = CostingService._get_product_costing_method(db, pid, wh)
        if qty_delta > 0:
            CostingService.update_cost(
                db,
                product_id=pid,
                warehouse_id=wh,
                new_qty=qty_delta,
                new_price=wh_cost,
            )
            if costing_method in ("fifo", "lifo"):
                CostingService.create_cost_layer(
                    db,
                    product_id=pid,
                    warehouse_id=wh,
                    quantity=qty_delta,
                    unit_cost=wh_cost,
                    source_document_type="adjustment",
                    source_document_id=reference_id or 0,
                    costing_method=costing_method,
                )
        elif qty_delta < 0 and costing_method in ("fifo", "lifo"):
            try:
                consumed_value = CostingService.consume_layers(
                    db,
                    product_id=pid,
                    warehouse_id=wh,
                    quantity=abs(qty_delta),
                    sale_document_type="adjustment",
                    sale_document_id=reference_id or 0,
                    costing_method=costing_method,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            wh_cost = (Decimal(str(consumed_value)) / abs(qty_delta)).quantize(_D4, ROUND_HALF_UP)

        # Upsert inventory quantity
        new_qty = current_qty + qty_delta
        if stock_row:
            db.execute(text("""
                UPDATE inventory SET quantity = :qty, last_movement_date = NOW(), updated_at = NOW()
                WHERE product_id = :pid AND warehouse_id = :wh
            """), {"qty": str(new_qty), "pid": pid, "wh": wh})
        else:
            if qty_delta < 0:
                raise HTTPException(status_code=400, detail=i18n_message("no_stock_for_product_in_warehouse", request))
            db.execute(text("""
                INSERT INTO inventory (product_id, warehouse_id, quantity, average_cost, last_movement_date)
                VALUES (:pid, :wh, :qty, :cost, NOW())
            """), {"pid": pid, "wh": wh, "qty": str(new_qty), "cost": str(wh_cost)})

        # Log inventory transaction
        trans_type = 'adjustment_in' if qty_delta > 0 else 'adjustment_out'
        db.execute(text("""
            INSERT INTO inventory_transactions (
                product_id, warehouse_id, transaction_type,
                reference_type, reference_id, reference_document,
                quantity, unit_cost, total_cost, notes, created_by
            ) VALUES (
                :pid, :wh, :type,
                'adjustment', :ref_id, :doc_num,
                :qty, :uc, :tc, :notes, :uid
            )
        """), {
            "pid": pid, "wh": wh, "type": trans_type,
            "ref_id": reference_id or 0, "doc_num": reference,
            "qty": str(qty_delta),
            "uc": str(wh_cost.quantize(_D4, ROUND_HALF_UP)),
            "tc": str((abs(qty_delta) * wh_cost).quantize(_D2, ROUND_HALF_UP)),
            "notes": item_reason or notes or "Stock Adjustment",
            "uid": user_id,
        })

        net_value_delta += qty_delta * wh_cost
        net_value_per_wh[wh] = net_value_per_wh.get(wh, Decimal("0")) + (qty_delta * wh_cost)

    # GL posting
    net_value = net_value_delta.quantize(_D2, ROUND_HALF_UP)

    # Query branch_id once for GL and audit
    branch_id = db.execute(
        text("SELECT branch_id FROM warehouses WHERE id = :id"),
        {"id": items[0]["warehouse_id"]},
    ).scalar()

    if abs(net_value) > Decimal("0.005"):
        # F-31: build one (Dr inventory / Cr adjustment) pair per warehouse.
        lines: list[dict] = []
        for wh_id, wh_delta in net_value_per_wh.items():
            wh_delta_q = wh_delta.quantize(_D2, ROUND_HALF_UP)
            if abs(wh_delta_q) <= Decimal("0.005"):
                continue
            wh_inv_acc = inventory_account_id or resolve_warehouse_inventory_account(db, wh_id)
            if not wh_inv_acc:
                raise HTTPException(**http_error(400, "inventory_account_not_configured", request))
            if wh_delta_q > 0:
                lines.append({
                    "account_id": wh_inv_acc,
                    "debit": float(wh_delta_q),
                    "credit": 0,
                    "description": f"Inventory Adjustment Gain (WH#{wh_id}) - {reference}",
                })
                lines.append({
                    "account_id": adj_acc,
                    "debit": 0,
                    "credit": float(wh_delta_q),
                    "description": f"Adjustment Gain (WH#{wh_id}) - {reference}",
                })
            else:
                abs_val = float(-wh_delta_q)
                lines.append({
                    "account_id": adj_acc,
                    "debit": abs_val,
                    "credit": 0,
                    "description": f"Adjustment Loss (WH#{wh_id}) - {reference}",
                })
                lines.append({
                    "account_id": wh_inv_acc,
                    "debit": 0,
                    "credit": abs_val,
                    "description": f"Inventory Decrease (WH#{wh_id}) - {reference}",
                })

        if lines:
            gl_create_journal_entry(
                db,
                company_id=company_id,
                date=txn_date,
                description=f"Stock Adjustment - {reference}",
                lines=lines,
                user_id=user_id,
                branch_id=branch_id,
                reference=reference,
                currency=base_currency,
            )

    # Audit log
    try:
        log_activity(
            db,
            user_id=user_id,
            username=username,
            action="stock.adjustment",
            resource_type="stock_adjustment",
            resource_id=reference,
            details={
                "reference": reference,
                "items_count": len(items),
                "net_value_delta": float(net_value_delta),
            },
            request=request,
            branch_id=branch_id,
        )
    except Exception as audit_err:
        logger.warning(f"Audit logging failed: {audit_err}")

    return {
        "reference": reference,
        "net_value_delta": float(net_value_delta),
        "items_processed": len(items),
    }


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
        branch_scope = resolve_branch_scope(current_user, branch_id)
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
        query += branch_scope_filter_from_scope(branch_scope, "w.branch_id", params)

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
    """إنشاء تسوية جردية (تعديل الكمية يدوياً) — T049: calls shared helper."""
    db = get_db_connection(current_user.company_id)
    try:
        user_id = current_user.id if hasattr(current_user, 'id') else current_user.get('id')
        username = current_user.username if hasattr(current_user, 'username') else current_user.get('username')
        company_id = current_user.company_id if hasattr(current_user, 'company_id') else current_user.get('company_id')

        # INV-005: Check warehouse branch access
        wh_branch = db.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": data.warehouse_id}).scalar()
        allowed = getattr(current_user, 'allowed_branches', []) or []
        if allowed and "*" not in getattr(current_user, 'permissions', []):
            if wh_branch and wh_branch not in allowed:
                raise HTTPException(**http_error(403, "adjustment_warehouse_outside_branch", request))

        # INV-QTY: Validate quantity for discrete units
        from utils.quantity_validation import validate_quantity_for_product
        validate_quantity_for_product(db, data.product_id, data.new_quantity, request)

        # Get current quantity to compute difference — under lock to prevent
        # race condition with concurrent sales/adjustments.
        stock_row = db.execute(text("""
            SELECT quantity FROM inventory
            WHERE product_id = :pid AND warehouse_id = :wh
            FOR UPDATE
        """), {"pid": data.product_id, "wh": data.warehouse_id}).fetchone()
        current_qty = Decimal(str(stock_row.quantity)) if stock_row else Decimal("0")
        new_qty_dec = Decimal(str(data.new_quantity))
        difference = new_qty_dec - current_qty

        if difference == 0:
            raise HTTPException(**http_error(400, "adjustment_quantity_no_change", request))
        if new_qty_dec < 0:
            raise HTTPException(**http_error(400, "adjustment_negative_quantity", request))

        adjustment_type = 'increase' if difference > 0 else 'decrease'

        # Generate adjustment number
        year = datetime.now().year
        max_num = db.execute(text("""
            SELECT MAX(CAST(SUBSTRING(adjustment_number FROM 'ADJ-\\d{4}-(\\d+)') AS INTEGER))
            FROM stock_adjustments WHERE adjustment_number LIKE :pattern
        """), {"pattern": f"ADJ-{year}-%"}).scalar() or 0
        adj_number = f"ADJ-{year}-{str(max_num + 1).zfill(4)}"

        # Create adjustment record
        adj_id_result = db.execute(text("""
            INSERT INTO stock_adjustments (
                adjustment_number, warehouse_id, product_id,
                adjustment_type, reason, old_quantity, new_quantity, difference,
                notes, status, created_by
            ) VALUES (
                :num, :wh, :pid, :type, :reason, :old, :new, :diff,
                :notes, 'approved', :uid
            ) RETURNING id
        """), {
            "num": adj_number, "wh": data.warehouse_id, "pid": data.product_id,
            "type": adjustment_type, "reason": data.reason,
            "old": str(current_qty), "new": str(new_qty_dec), "diff": str(difference),
            "notes": data.notes, "uid": user_id
        }).fetchone()

        if not adj_id_result:
            raise Exception("Failed to insert stock adjustment record")
        adj_id = adj_id_result[0]

        # T049: Call shared helper for stock/GL/audit
        result = post_inventory_adjustment(
            db,
            items=[{
                "product_id": data.product_id,
                "warehouse_id": data.warehouse_id,
                "quantity_delta": str(difference),
                "reason": data.notes or f"Stock Adjustment {adjustment_type}",
            }],
            reference=adj_number,
            reference_id=adj_id,
            notes=data.notes,
            user_id=user_id,
            username=username,
            company_id=company_id,
            request=request,
        )

        db.commit()

        # Notify about inventory adjustment
        try:
            prod_name = db.execute(text("SELECT product_name FROM products WHERE id = :id"), {"id": data.product_id}).scalar()
            db.execute(text("""
                INSERT INTO notifications (user_id, type, title, message, link, is_read, created_at)
                SELECT DISTINCT u.id, 'inventory', :title, :message, :link, FALSE, NOW()
                FROM company_users u
                WHERE u.is_active = TRUE AND u.role IN ('admin', 'superuser')
                AND u.id != :current_uid
            """), {
                "title": i18n_message("notif_stock_adjustment", request),
                "message": i18n_message("stock_adjustment_details", request),
                "link": "/stock/adjustments",
                "current_uid": user_id
            })
            db.commit()
        except Exception:
            pass

        return {"id": adj_id, "message": i18n_message("adjustment_saved", request)}

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Stock adjustment failed")
        raise HTTPException(**http_error(500, "adjustment_save_error", request))
    finally:
        db.close()
