"""
Inventory Module - Stock Transfers (Single-item with GL + Multi-item)
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request, Header
from utils.i18n import http_error, i18n_message
from sqlalchemy import text
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
import logging
import uuid

from database import get_db_connection
from routers.auth import get_current_user
from utils.audit import log_activity
from utils.permissions import require_permission
from utils.quantity_validation import validate_quantities_for_products
from services.gl_service import create_journal_entry as gl_create_journal_entry
from utils.fiscal_lock import check_fiscal_period_open
from utils.tx import transactional
from .schemas import StockTransferSingleCreate, StockTransferCreate

transfers_router = APIRouter()
logger = logging.getLogger(__name__)


def _company_id(user) -> str:
    return user.get("company_id") if isinstance(user, dict) else user.company_id


def _user_id(user) -> int:
    return user.get("id") if isinstance(user, dict) else user.id


def _username(user) -> str | None:
    return user.get("username") if isinstance(user, dict) else getattr(user, "username", None)


def _user_permissions(user) -> list:
    return user.get("permissions", []) if isinstance(user, dict) else (getattr(user, "permissions", []) or [])


def _allowed_branches(user) -> list:
    return user.get("allowed_branches", []) if isinstance(user, dict) else (getattr(user, "allowed_branches", []) or [])


def _warehouse_info(db, warehouse_id: int, base_currency: str):
    return db.execute(text("""
        SELECT w.id,
               w.warehouse_name,
               w.branch_id,
               w.gl_inventory_account_id,
               COALESCE(b.default_currency, :base_currency) AS branch_currency
        FROM warehouses w
        LEFT JOIN branches b ON b.id = w.branch_id
        WHERE w.id = :id
    """), {"id": warehouse_id, "base_currency": base_currency}).fetchone()


def _resolve_inventory_account_for_wh(db, wh_row) -> int | None:
    """Return the inventory GL account for a warehouse with global fallback.

    Equivalent to ``utils.inventory_accounts.resolve_warehouse_inventory_account``
    but reuses the already-fetched warehouse row to avoid an extra query.
    """
    if wh_row and wh_row.gl_inventory_account_id:
        return int(wh_row.gl_inventory_account_id)
    from utils.accounting import get_mapped_account_id
    acc = get_mapped_account_id(db, "acc_map_inventory")
    return int(acc) if acc else None


def _next_transfer_doc_id(db) -> int:
    """Allocate a stable transfer document id from the DB sequence."""
    return int(db.execute(text("""
        SELECT nextval(pg_get_serial_sequence('stock_transfer_log', 'id'))
    """)).scalar())


@transfers_router.post("/transfers", dependencies=[Depends(require_permission("stock.transfer"))])
def create_stock_transfer(
    transfer: StockTransferSingleCreate,
    request: Request,
    # INV-16: Idempotency-Key prevents duplicate transfers on network retry.
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key", max_length=64),
    current_user: dict = Depends(get_current_user)
):
    """تحويل مخزني مباشر بين المستودعات مع تطبيق سياسة التكلفة"""

    with transactional(_company_id(current_user)) as db:
        from utils.accounting import get_base_currency
        base_currency = get_base_currency(db)
        user_id = _user_id(current_user)

        # INV-16: Idempotency check at document level
        if idempotency_key:
            existing = db.execute(text("""
                SELECT id FROM stock_transfer_log WHERE idempotency_key = :key LIMIT 1
            """), {"key": idempotency_key}).fetchone()
            if existing:
                return {"message": i18n_message("transfer_successful", request), "idempotent_replay": True}

        transfer_ref = f"TRF-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
        transfer_doc_id = _next_transfer_doc_id(db)

        # 1. Validate source and destination are different
        if transfer.source_warehouse_id == transfer.destination_warehouse_id:
            raise HTTPException(**http_error(400, "same_warehouse_transfer", request))

        # 2. Check warehouses exist
        src_wh = _warehouse_info(db, transfer.source_warehouse_id, base_currency)
        dst_wh = _warehouse_info(db, transfer.destination_warehouse_id, base_currency)

        if not src_wh:
            raise HTTPException(**http_error(404, "source_warehouse_not_found", request))
        if not dst_wh:
            raise HTTPException(**http_error(404, "dest_warehouse_not_found", request))

        # F-30: cross-currency transfers are now allowed. The journal entry
        # is always posted in base currency against the per-warehouse
        # inventory accounts (F-31), so the value never needs FX conversion.
        # The branch currency is recorded on the transaction-side fields of
        # journal_lines for reporting purposes.

        # INV-006: Check branch access on both warehouses
        allowed = _allowed_branches(current_user)
        if allowed and "*" not in _user_permissions(current_user):
            src_branch = src_wh.branch_id
            dst_branch = dst_wh.branch_id
            if (src_branch and src_branch not in allowed) or (dst_branch and dst_branch not in allowed):
                raise HTTPException(**http_error(403, "cross_branch_transfer_denied", request))

        # 3. Check product exists
        product = db.execute(text("SELECT product_name FROM products WHERE id = :id"),
                            {"id": transfer.product_id}).fetchone()
        if not product:
            raise HTTPException(**http_error(404, "product_not_found"))

        # INV-QTY: Validate quantity for discrete units
        validate_quantities_for_products(db, [{"product_id": transfer.product_id, "quantity": transfer.quantity}], request)

        # 4. Check available stock in source — lock row to prevent phantom stock
        source_inv = db.execute(text("""
            SELECT quantity, reserved_quantity, average_cost FROM inventory
            WHERE product_id = :pid AND warehouse_id = :wh
            FOR UPDATE
        """), {"pid": transfer.product_id, "wh": transfer.source_warehouse_id}).fetchone()

        transfer_qty = Decimal(str(transfer.quantity))
        source_qty = Decimal(str(source_inv.quantity)) if source_inv else Decimal("0")
        source_reserved = Decimal(str(source_inv.reserved_quantity or 0)) if source_inv else Decimal("0")
        source_cost = Decimal(str(source_inv.average_cost or 0)) if source_inv else Decimal("0")
        available_qty = source_qty - source_reserved

        if available_qty < transfer_qty:
            raise HTTPException(
                status_code=400,
                detail=f"الكمية المتوفرة ({available_qty}) أقل من المطلوب ({transfer.quantity})"
            )

        from services.costing_service import CostingService
        method = CostingService._get_product_costing_method(db, transfer.product_id, transfer.source_warehouse_id)
        consumption_details = []
        if method in ("fifo", "lifo"):
            try:
                consumption_result = CostingService.consume_layers(
                    db,
                    product_id=transfer.product_id,
                    warehouse_id=transfer.source_warehouse_id,
                    quantity=transfer_qty,
                    sale_document_type="transfer",
                    sale_document_id=transfer_doc_id,
                    costing_method=method,
                    return_consumptions=True,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            transfer_value = Decimal(str(consumption_result["total_cogs"]))
            consumption_details = consumption_result["consumptions"]
            source_cost = (transfer_value / transfer_qty).quantize(Decimal("0.0001"), ROUND_HALF_UP) if transfer_qty else Decimal("0")
        else:
            transfer_value = (transfer_qty * source_cost).quantize(Decimal("0.0001"), ROUND_HALF_UP)

        # 5. Get destination current state — lock row to ensure consistent WAC
        dest_inv = db.execute(text("""
            SELECT quantity, average_cost FROM inventory 
            WHERE product_id = :pid AND warehouse_id = :wh
            FOR UPDATE
        """), {"pid": transfer.product_id, "wh": transfer.destination_warehouse_id}).fetchone()

        dest_qty_before = Decimal(str(dest_inv.quantity)) if dest_inv else Decimal("0")
        dest_cost_before = Decimal(str(dest_inv.average_cost or 0)) if dest_inv else Decimal("0")

        # 6. Update source inventory (decrease)
        source_update = db.execute(text("""
            UPDATE inventory SET quantity = quantity - :qty, updated_at = NOW()
            WHERE product_id = :pid AND warehouse_id = :wh
              AND quantity - COALESCE(reserved_quantity, 0) >= :qty
            RETURNING id
        """), {"qty": transfer.quantity, "pid": transfer.product_id, "wh": transfer.source_warehouse_id}).fetchone()
        if not source_update:
            raise HTTPException(**http_error(400, "qty_changed_before_save", request))

        dest_method = CostingService._get_product_costing_method(db, transfer.product_id, transfer.destination_warehouse_id)
        if dest_method in ("fifo", "lifo"):
            if consumption_details:
                for consumed in consumption_details:
                    CostingService.create_cost_layer(
                        db,
                        product_id=transfer.product_id,
                        warehouse_id=transfer.destination_warehouse_id,
                        quantity=consumed["quantity"],
                        unit_cost=consumed["unit_cost"],
                        source_document_type="transfer",
                        source_document_id=transfer_doc_id,
                        costing_method=dest_method,
                    )
            else:
                CostingService.create_cost_layer(
                    db,
                    product_id=transfer.product_id,
                    warehouse_id=transfer.destination_warehouse_id,
                    quantity=transfer_qty,
                    unit_cost=source_cost,
                    source_document_type="transfer",
                    source_document_id=transfer_doc_id,
                    costing_method=dest_method,
                )

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
                "qty": str(new_total_qty),
                "cost": str(new_avg_cost.quantize(Decimal("0.0001"), ROUND_HALF_UP)),
                "pid": transfer.product_id,
                "wh": transfer.destination_warehouse_id
            })
        else:
            # Insert new inventory record with source cost
            db.execute(text("""
                INSERT INTO inventory (product_id, warehouse_id, quantity, average_cost, updated_at)
                VALUES (:pid, :wh, :qty, :cost, NOW())
                ON CONFLICT (product_id, warehouse_id)
                DO UPDATE SET quantity = inventory.quantity + EXCLUDED.quantity,
                              average_cost = CASE
                                  WHEN inventory.quantity + EXCLUDED.quantity > 0 THEN
                                      ((inventory.quantity * COALESCE(inventory.average_cost, 0))
                                       + (EXCLUDED.quantity * EXCLUDED.average_cost))
                                      / (inventory.quantity + EXCLUDED.quantity)
                                  ELSE EXCLUDED.average_cost
                              END,
                              updated_at = NOW()
            """), {
                "pid": transfer.product_id,
                "wh": transfer.destination_warehouse_id,
                "qty": str(transfer_qty),
                "cost": str(source_cost)
            })
            new_avg_cost = source_cost

        # 8. Log transactions
        db.execute(text("""
            INSERT INTO inventory_transactions (product_id, warehouse_id, transaction_type,
                                               reference_type, reference_id, reference_document,
                                               quantity, notes, created_by, unit_cost, total_cost,
                                               balance_before, balance_after)
            VALUES (:pid, :wh, 'transfer_out', 'transfer', :ref_id, :ref_doc,
                    :qty, :notes, :user, :unit_cost, :total_cost,
                    :bal_before, :bal_after)
        """), {
            "pid": transfer.product_id,
            "wh": transfer.source_warehouse_id,
            "ref_id": transfer_doc_id,
            "ref_doc": transfer_ref,
            "qty": str(-transfer_qty),
            "notes": transfer.notes or f"تحويل إلى {dst_wh.warehouse_name}",
            "user": user_id,
            "unit_cost": str(source_cost),
            "total_cost": str(transfer_value),
            "bal_before": str(source_qty),
            "bal_after": str(source_qty - transfer_qty),
        })

        db.execute(text("""
            INSERT INTO inventory_transactions (product_id, warehouse_id, transaction_type, 
                                               reference_type, reference_id, reference_document,
                                               quantity, notes, created_by, unit_cost, total_cost)
            VALUES (:pid, :wh, 'transfer_in', 'transfer', :ref_id, :ref_doc,
                    :qty, :notes, :user, :unit_cost, :total_cost)
        """), {
            "pid": transfer.product_id,
            "wh": transfer.destination_warehouse_id,
            "ref_id": transfer_doc_id,
            "ref_doc": transfer_ref,
            "qty": str(transfer_qty),
            "notes": transfer.notes or f"تحويل من {src_wh.warehouse_name}",
            "user": user_id,
            "unit_cost": str(source_cost),
            "total_cost": str(transfer_value),
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
            "qty": str(transfer_qty),
            "tcost": str(source_cost),
            "fcast": str(source_cost),
            "tcast_b": str(dest_cost_before),
            "tcast_a": str(new_avg_cost)
        })

        # 9b. Create GL Journal Entry for warehouse transfer via GL service.
        # F-31: use per-warehouse inventory accounts so the entry has real
        # ledger meaning when src/dst are mapped to different accounts.
        # When both warehouses share the same account (or fall back to the
        # global mapping) the result is the legacy debit/credit on a single
        # account, which still keeps the trial balance reconciled.
        src_branch = src_wh.branch_id
        dst_branch = dst_wh.branch_id

        gl_transfer_value = transfer_value  # keep as Decimal — no float cast
        if gl_transfer_value > Decimal("0.01"):
            src_inv_acc = _resolve_inventory_account_for_wh(db, src_wh)
            dst_inv_acc = _resolve_inventory_account_for_wh(db, dst_wh)

            if src_inv_acc and dst_inv_acc:
                transfer_date = datetime.now().strftime("%Y-%m-%d")
                # Fiscal-period lock: block posting into a closed period.
                check_fiscal_period_open(db, transfer_date)
                # F-30: capture per-side currency on the transactional fields
                # (txn_currency / txn_amount) while keeping the booking-side
                # value in base currency for clean balancing.
                src_currency = (src_wh.branch_currency or base_currency).upper()
                dst_currency = (dst_wh.branch_currency or base_currency).upper()
                lines = [
                    {
                        "account_id": dst_inv_acc,
                        "debit": gl_transfer_value,
                        "credit": 0,
                        "description": f"Transfer In - WH#{dst_wh.id} {dst_wh.warehouse_name} / branch {dst_branch or '-'}",
                        "amount_currency": gl_transfer_value,
                        "currency": base_currency,
                        "txn_currency": dst_currency,
                        "txn_amount": gl_transfer_value,
                    },
                    {
                        "account_id": src_inv_acc,
                        "debit": 0,
                        "credit": gl_transfer_value,
                        "description": f"Transfer Out - WH#{src_wh.id} {src_wh.warehouse_name} / branch {src_branch or '-'}",
                        "amount_currency": gl_transfer_value,
                        "currency": base_currency,
                        "txn_currency": src_currency,
                        "txn_amount": gl_transfer_value,
                    },
                ]
                gl_create_journal_entry(
                    db,
                    company_id=_company_id(current_user),
                    date=transfer_date,
                    description=f"تحويل مخزني: {src_wh.warehouse_name} → {dst_wh.warehouse_name}",
                    lines=lines,
                    user_id=user_id,
                    branch_id=src_branch or dst_branch,
                    reference=transfer_ref,
                    currency=base_currency,
                    source="inventory_transfer",
                    source_id=transfer_doc_id,
                    idempotency_key=f"inventory_transfer:{transfer_doc_id}",
                )

        # 10. Log activity
        log_activity(
            db,
            user_id=user_id,
            username=_username(current_user),
            action="stock.transfer",
            resource_type="stock_transfer",
            resource_id=str(transfer.product_id),
            details={"product": product.product_name, "qty": str(transfer_qty), "from": src_wh.warehouse_name, "to": dst_wh.warehouse_name},
            request=request,
            branch_id=src_branch
        )

        return {
            "message": i18n_message("transfer_successful", request),
            "transfer_details": {
                "product_name": product.product_name,
                "quantity": transfer.quantity,
                "source_warehouse": src_wh.warehouse_name,
                "destination_warehouse": dst_wh.warehouse_name,
                "transfer_cost": str(source_cost.quantize(Decimal("0.0001"), ROUND_HALF_UP)),
                "new_destination_avg_cost": str(new_avg_cost.quantize(Decimal("0.0001"), ROUND_HALF_UP))
            }
        }


@transfers_router.post("/transfer", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("stock.transfer"))])
def transfer_stock(
    transfer: StockTransferCreate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """نقل مخزون بين المستودعات (متعدد الأصناف).

    H4: مُلَف بـ ``transactional()`` ليطابق سلوك single-item transfer ـ يضمن
    rollback تلقائي إذا فشل GL post بعد تحريك المخزون.

    M10: عند ``policy_type == 'global_wac'`` لا يتغير ``products.cost_price``
    العام عند التحويل لأن الكمية الإجمالية للمنتج لا تتغير ـ يتغير فقط
    ``inventory.average_cost`` لكل مستودع. هذا متعمد ومتسق مع نموذج WAC.
    """
    with transactional(_company_id(current_user)) as db:
        from utils.accounting import get_base_currency
        base_currency = get_base_currency(db)
        user_id = _user_id(current_user)
        if transfer.source_warehouse_id == transfer.destination_warehouse_id:
            raise HTTPException(**http_error(400, "cannot_transfer_same_warehouse", request))

        # Validate warehouses exist
        src = _warehouse_info(db, transfer.source_warehouse_id, base_currency)
        dst = _warehouse_info(db, transfer.destination_warehouse_id, base_currency)

        if not src or not dst:
            raise HTTPException(**http_error(404, "warehouse_not_found"))
        # F-30: cross-currency transfers are allowed (see single-item endpoint
        # for the rationale). JE posted in base currency against per-warehouse
        # inventory accounts (F-31).

        # INV-006: Check branch access on both warehouses
        allowed = _allowed_branches(current_user)
        if allowed and "*" not in _user_permissions(current_user):
            src_branch = src.branch_id
            dst_branch = dst.branch_id
            if (src_branch and src_branch not in allowed) or (dst_branch and dst_branch not in allowed):
                raise HTTPException(**http_error(403, "cross_branch_transfer_denied", request))

        transfer_ref = f"TRF-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
        transfer_doc_id = _next_transfer_doc_id(db)

        # INV-QTY: Validate quantities for discrete units
        validate_quantities_for_products(db, transfer.items, request)

        # INV-L04: Validate fiscal period is open before any inventory/GL movement.
        from utils.fiscal_lock import check_fiscal_period_open
        transfer_date = datetime.now().strftime("%Y-%m-%d")
        check_fiscal_period_open(db, transfer_date)

        # T051: Aggregate duplicate products before stock checks
        aggregated: dict[int, Decimal] = {}
        for item in transfer.items:
            pid = item.product_id
            aggregated[pid] = aggregated.get(pid, Decimal("0")) + Decimal(str(item.quantity))

        # Validate each aggregated product has sufficient stock
        for pid, total_qty in aggregated.items():
            src_inv = db.execute(text("""
                SELECT quantity, reserved_quantity FROM inventory
                WHERE product_id = :pid AND warehouse_id = :wh
                FOR UPDATE
            """), {"pid": pid, "wh": transfer.source_warehouse_id}).fetchone()
            current_qty = Decimal(str(src_inv.quantity)) if src_inv else Decimal("0")
            reserved_qty = Decimal(str(src_inv.reserved_quantity or 0)) if src_inv else Decimal("0")
            available_qty = current_qty - reserved_qty
            if available_qty < total_qty:
                prod_name = db.execute(text("SELECT product_name FROM products WHERE id = :pid"), {"pid": pid}).scalar()
                raise HTTPException(status_code=400, detail=i18n_message("qty_not_available", request))

        # Aggregate total transfer value for GL posting after the loop.
        total_transfer_value = Decimal("0")
        item_descriptions: list[str] = []

        from services.costing_service import CostingService

        for item in transfer.items:
            # T051: Stock already validated via aggregation above; re-lock for update
            src_inv = db.execute(text("""
                SELECT quantity, reserved_quantity, average_cost FROM inventory
                WHERE product_id = :pid AND warehouse_id = :wh
                FOR UPDATE
            """), {"pid": item.product_id, "wh": transfer.source_warehouse_id}).fetchone()

            item_qty = Decimal(str(item.quantity))
            method = CostingService._get_product_costing_method(db, item.product_id, transfer.source_warehouse_id)
            consumption_details = []
            if method in ("fifo", "lifo"):
                try:
                    consumption_result = CostingService.consume_layers(
                        db,
                        product_id=item.product_id,
                        warehouse_id=transfer.source_warehouse_id,
                        quantity=item_qty,
                        sale_document_type="transfer",
                        sale_document_id=transfer_doc_id,
                        costing_method=method,
                        return_consumptions=True,
                    )
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc))
                item_value = Decimal(str(consumption_result["total_cogs"]))
                consumption_details = consumption_result["consumptions"]
                source_cost = (item_value / item_qty).quantize(Decimal("0.0001"), ROUND_HALF_UP) if item_qty else Decimal("0")
            else:
                source_cost = Decimal(str(src_inv.average_cost or 0)) if src_inv else Decimal("0")
                item_value = (item_qty * source_cost).quantize(Decimal("0.0001"), ROUND_HALF_UP)

            # Track aggregate GL value (INV-L04)
            total_transfer_value += item_value

            # 2. Deduct from Source
            deducted = db.execute(text("""
                UPDATE inventory SET quantity = quantity - :qty, updated_at = NOW()
                WHERE product_id = :pid AND warehouse_id = :wh
                  AND quantity - COALESCE(reserved_quantity, 0) >= :qty
                RETURNING id
            """), {"qty": item.quantity, "pid": item.product_id, "wh": transfer.source_warehouse_id}).fetchone()
            if not deducted:
                prod_name = db.execute(text("SELECT product_name FROM products WHERE id = :pid"), {"pid": item.product_id}).scalar()
                raise HTTPException(status_code=400, detail=i18n_message("qty_changed_during_transfer", request))

            # 3. Add to Destination with WAC recalculation
            exists_dest = db.execute(text("""
                SELECT quantity, average_cost FROM inventory
                WHERE product_id = :pid AND warehouse_id = :wh
                FOR UPDATE
            """), {"pid": item.product_id, "wh": transfer.destination_warehouse_id}).fetchone()

            dest_method = CostingService._get_product_costing_method(db, item.product_id, transfer.destination_warehouse_id)
            if dest_method in ("fifo", "lifo"):
                if consumption_details:
                    for consumed in consumption_details:
                        CostingService.create_cost_layer(
                            db,
                            product_id=item.product_id,
                            warehouse_id=transfer.destination_warehouse_id,
                            quantity=consumed["quantity"],
                            unit_cost=consumed["unit_cost"],
                            source_document_type="transfer",
                            source_document_id=transfer_doc_id,
                            costing_method=dest_method,
                        )
                else:
                    CostingService.create_cost_layer(
                        db,
                        product_id=item.product_id,
                        warehouse_id=transfer.destination_warehouse_id,
                        quantity=item_qty,
                        unit_cost=source_cost,
                        source_document_type="transfer",
                        source_document_id=transfer_doc_id,
                        costing_method=dest_method,
                    )

            if exists_dest:
                dest_qty = Decimal(str(exists_dest.quantity or 0))
                dest_cost = Decimal(str(exists_dest.average_cost or 0))
                new_total_qty = dest_qty + item_qty
                if new_total_qty > 0:
                    new_avg_cost = ((dest_qty * dest_cost) + (item_qty * source_cost)) / new_total_qty
                else:
                    new_avg_cost = source_cost
                db.execute(text("""
                    UPDATE inventory SET quantity = :qty, average_cost = :cost, updated_at = NOW()
                    WHERE product_id = :pid AND warehouse_id = :wh
                """), {
                    "qty": str(new_total_qty),
                    "cost": str(new_avg_cost.quantize(Decimal("0.0001"), ROUND_HALF_UP)),
                    "pid": item.product_id,
                    "wh": transfer.destination_warehouse_id,
                })
            else:
                db.execute(text("""
                    INSERT INTO inventory (product_id, warehouse_id, quantity, average_cost, updated_at)
                    VALUES (:pid, :wh, :qty, :cost, NOW())
                    ON CONFLICT (product_id, warehouse_id)
                    DO UPDATE SET quantity = inventory.quantity + EXCLUDED.quantity,
                                  average_cost = CASE
                                      WHEN inventory.quantity + EXCLUDED.quantity > 0 THEN
                                          ((inventory.quantity * COALESCE(inventory.average_cost, 0))
                                           + (EXCLUDED.quantity * EXCLUDED.average_cost))
                                          / (inventory.quantity + EXCLUDED.quantity)
                                      ELSE EXCLUDED.average_cost
                                  END,
                                  updated_at = NOW()
                """), {
                    "pid": item.product_id,
                    "wh": transfer.destination_warehouse_id,
                    "qty": str(item_qty),
                    "cost": str(source_cost),
                })

            # 3. Log Transactions
            db.execute(text("""
                INSERT INTO inventory_transactions (
                    product_id, warehouse_id, transaction_type, reference_type, 
                    reference_id, reference_document, quantity, notes, created_by,
                    unit_cost, total_cost
                ) VALUES (
                    :pid, :wh, 'transfer_out', 'transfer', 
                    :ref_id, :ref_doc, :qty, :notes, :user,
                    :unit_cost, :total_cost
                )
            """), {
                "pid": item.product_id,
                "wh": transfer.source_warehouse_id,
                "ref_id": transfer_doc_id,
                "ref_doc": transfer_ref,
                "qty": str(-item_qty),
                "notes": f"Transfer to {dst.warehouse_name} ({transfer_ref})",
                "user": user_id,
                "unit_cost": str(source_cost),
                "total_cost": str(item_value),
            })

            db.execute(text("""
                INSERT INTO inventory_transactions (
                    product_id, warehouse_id, transaction_type, reference_type, 
                    reference_id, reference_document, quantity, notes, created_by,
                    unit_cost, total_cost
                ) VALUES (
                    :pid, :wh, 'transfer_in', 'transfer', 
                    :ref_id, :ref_doc, :qty, :notes, :user,
                    :unit_cost, :total_cost
                )
            """), {
                "pid": item.product_id,
                "wh": transfer.destination_warehouse_id,
                "ref_id": transfer_doc_id,
                "ref_doc": transfer_ref,
                "qty": str(item_qty),
                "notes": f"Transfer from {src.warehouse_name} ({transfer_ref})",
                "user": user_id,
                "unit_cost": str(source_cost),
                "total_cost": str(item_value),
            })

        # INV-L04 / F-31: Emit one aggregate GL journal entry covering all
        # items in this multi-item transfer. We post Dr Inventory-Destination
        # / Cr Inventory-Source using each warehouse's mapped account so the
        # entry is meaningful when the two warehouses (or branches) carry
        # separate inventory ledgers. When the same account is mapped to both
        # warehouses the result collapses to the legacy in-place debit/credit.
        if total_transfer_value > Decimal("0.01"):
            src_inv_acc = _resolve_inventory_account_for_wh(db, src)
            dst_inv_acc = _resolve_inventory_account_for_wh(db, dst)
            if src_inv_acc and dst_inv_acc:
                src_branch_id = src.branch_id
                dst_branch_id = dst.branch_id
                src_currency = (src.branch_currency or base_currency).upper()
                dst_currency = (dst.branch_currency or base_currency).upper()
                lines = [
                    {
                        "account_id": dst_inv_acc,
                        "debit": str(total_transfer_value.quantize(Decimal("0.0001"), ROUND_HALF_UP)),
                        "credit": 0,
                        "description": f"Transfer In - WH#{dst.id} {dst.warehouse_name} / branch {dst_branch_id or '-'}",
                        "amount_currency": str(total_transfer_value.quantize(Decimal("0.0001"), ROUND_HALF_UP)),
                        "currency": base_currency,
                        "txn_currency": dst_currency,
                        "txn_amount": str(total_transfer_value.quantize(Decimal("0.0001"), ROUND_HALF_UP)),
                    },
                    {
                        "account_id": src_inv_acc,
                        "debit": 0,
                        "credit": str(total_transfer_value.quantize(Decimal("0.0001"), ROUND_HALF_UP)),
                        "description": f"Transfer Out - WH#{src.id} {src.warehouse_name} / branch {src_branch_id or '-'}",
                        "amount_currency": str(total_transfer_value.quantize(Decimal("0.0001"), ROUND_HALF_UP)),
                        "currency": base_currency,
                        "txn_currency": src_currency,
                        "txn_amount": str(total_transfer_value.quantize(Decimal("0.0001"), ROUND_HALF_UP)),
                    },
                ]
                gl_create_journal_entry(
                    db,
                    company_id=_company_id(current_user),
                    date=transfer_date,
                    description=f"تحويل مخزني ({len(transfer.items)} صنف): {src.warehouse_name} → {dst.warehouse_name}",
                    lines=lines,
                    user_id=user_id,
                    branch_id=src_branch_id or dst_branch_id,
                    reference=transfer_ref,
                    currency=base_currency,
                    source="inventory_transfer",
                    source_id=transfer_doc_id,
                    idempotency_key=f"inventory_transfer:{transfer_doc_id}",
                )

        # AUDIT LOG
        log_activity(
            db,
            user_id=user_id,
            username=_username(current_user),
            action="stock.transfer",
            resource_type="stock_transfer",
            resource_id=transfer_ref,
            details={"from": transfer.source_warehouse_id, "to": transfer.destination_warehouse_id, "items_count": len(transfer.items)},
            request=request,
            branch_id=src.branch_id
        )

        return {"message": i18n_message("stock_transfer_success", request), "reference": transfer_ref}
