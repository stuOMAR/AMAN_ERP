"""POS cancellation endpoint.

Feature 023 — T039.  POST /pos/sales/{id}/cancel

INV-02 fix: added require_permission guard, FOR UPDATE row lock, CostingService
cost-layer restoration, GL reversal via gl_service, and all missing imports.
Constitution §3 [CRITICAL] — every financial reversal must post a balanced JE.
Constitution §4 [CRITICAL] — every protected endpoint needs a permission guard.
Constitution §6 — inventory writes must use row-level locks.
"""
from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from database import get_company_db
from routers.auth import get_current_user
from schemas import UserResponse
from utils.i18n import http_error, i18n_message
from utils.permissions import require_permission
from utils.audit import log_activity
from utils.fiscal_lock import check_fiscal_period_open
from services.gl_service import create_journal_entry as gl_create_journal_entry

logger = logging.getLogger(__name__)
router = APIRouter()

_D2 = Decimal("0.01")
_D4 = Decimal("0.0001")


class PosCancellationRequest(BaseModel):
    reason: Optional[str] = None
    restock_warehouse_id: Optional[int] = None


def get_db(current_user: UserResponse = Depends(get_current_user)):
    yield from get_company_db(current_user.company_id)


@router.post(
    "/pos/sales/{sale_id}/cancel",
    dependencies=[Depends(require_permission("pos.cancel"))],
)
async def cancel_pos_sale(
    sale_id: int,
    body: PosCancellationRequest,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cancel a paid POS order.

    Restores inventory (with cost-layer reversal), posts a reversing GL entry,
    and marks the order as cancelled — all within a single atomic transaction.
    """
    from utils.accounting import get_base_currency, get_mapped_account_id
    from utils.inventory_accounts import resolve_warehouse_inventory_account
    from services.costing_service import CostingService

    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    # ── 1. Load and lock the POS order ──────────────────────────────────
    order = db.execute(
        text("""
            SELECT id, order_number, status, warehouse_id, session_id,
                   branch_id, total, tax_amount, created_by
            FROM pos_orders
            WHERE id = :order_id
            FOR UPDATE
        """),
        {"order_id": sale_id},
    ).fetchone()

    if not order:
        raise HTTPException(**http_error(404, "pos_order_not_found", request))
    if order.status == "cancelled":
        raise HTTPException(**http_error(400, "order_already_cancelled", request))
    if order.status != "paid":
        raise HTTPException(**http_error(400, "only_paid_orders_can_be_cancelled", request))

    # ── 2. Fiscal period check ───────────────────────────────────────────
    check_fiscal_period_open(db, today_str)

    # ── 3. Load order lines ──────────────────────────────────────────────
    lines = db.execute(
        text("""
            SELECT product_id, quantity, warehouse_id, unit_cost, total_cost,
                   tax_rate, tax_amount, subtotal, total
            FROM pos_order_lines
            WHERE order_id = :order_id
        """),
        {"order_id": sale_id},
    ).fetchall()

    restock_wh = body.restock_warehouse_id or order.warehouse_id
    base_currency = get_base_currency(db)

    total_cogs_restored = Decimal("0")
    total_revenue_reversed = Decimal("0")
    total_tax_reversed = Decimal("0")

    # ── 4. Per-line: lock inventory, restore cost layers, update quantity ─
    if restock_wh:
        for line in lines:
            pid = line.product_id
            qty = Decimal(str(line.quantity or 0))
            if qty <= 0:
                continue

            # Lock inventory row before any read/write (Constitution §6)
            inv_row = db.execute(text("""
                SELECT id, quantity, average_cost
                FROM inventory
                WHERE product_id = :pid AND warehouse_id = :wh
                FOR UPDATE
            """), {"pid": pid, "wh": restock_wh}).fetchone()

            # Restore cost layers (FIFO/LIFO) or update WAC
            costing_method = CostingService._get_product_costing_method(db, pid, restock_wh)
            unit_cost = Decimal(str(line.unit_cost or 0))

            if costing_method in ("fifo", "lifo"):
                try:
                    result = CostingService.handle_return(
                        db,
                        product_id=pid,
                        warehouse_id=restock_wh,
                        quantity=qty,
                        unit_cost=unit_cost,
                        source_document_type="pos_cancellation",
                        source_document_id=sale_id,
                        costing_method=costing_method,
                        original_source_document_type="pos_order",
                        original_source_document_id=sale_id,
                    )
                    unit_cost = Decimal(str(result.get("restored_unit_cost", unit_cost)))
                except ValueError:
                    raise HTTPException(**http_error(400, "invalid_request", request))
            else:
                # WAC: update cost with returned quantity
                CostingService.update_cost(
                    db,
                    product_id=pid,
                    warehouse_id=restock_wh,
                    new_qty=qty,
                    new_price=unit_cost,
                )

            item_cost = (qty * unit_cost).quantize(_D2, ROUND_HALF_UP)
            total_cogs_restored += item_cost

            # Restore inventory quantity
            if inv_row:
                db.execute(text("""
                    UPDATE inventory
                    SET quantity = quantity + :qty,
                        last_movement_date = NOW(),
                        updated_at = NOW()
                    WHERE product_id = :pid AND warehouse_id = :wh
                """), {"qty": str(qty), "pid": pid, "wh": restock_wh})
            else:
                db.execute(text("""
                    INSERT INTO inventory (product_id, warehouse_id, quantity, average_cost, updated_at)
                    VALUES (:pid, :wh, :qty, :cost, NOW())
                    ON CONFLICT (product_id, warehouse_id)
                    DO UPDATE SET quantity = inventory.quantity + EXCLUDED.quantity,
                                  updated_at = NOW()
                """), {"pid": pid, "wh": restock_wh, "qty": str(qty), "cost": str(unit_cost)})

            # Log inventory transaction
            db.execute(text("""
                INSERT INTO inventory_transactions (
                    product_id, warehouse_id, transaction_type,
                    reference_type, reference_id, reference_document,
                    quantity, unit_cost, total_cost, notes, created_by
                ) VALUES (
                    :pid, :wh, 'return_in',
                    'pos_cancellation', :order_id, :order_num,
                    :qty, :uc, :tc, :notes, :uid
                )
            """), {
                "pid": pid, "wh": restock_wh,
                "order_id": sale_id, "order_num": order.order_number,
                "qty": str(qty), "uc": str(unit_cost), "tc": str(item_cost),
                "notes": f"POS Cancellation — {body.reason or 'Cancelled'}",
                "uid": current_user.id,
            })

            # Accumulate revenue/tax for GL reversal
            total_revenue_reversed += Decimal(str(line.subtotal or 0))
            total_tax_reversed += Decimal(str(line.tax_amount or 0))

    # ── 5. Post reversing GL entry (Constitution §3 [CRITICAL]) ──────────
    if total_cogs_restored > _D2 or total_revenue_reversed > _D2:
        inv_acc = resolve_warehouse_inventory_account(db, restock_wh) if restock_wh else None
        cogs_acc = get_mapped_account_id(db, "acc_map_cogs")
        revenue_acc = get_mapped_account_id(db, "acc_map_sales_revenue")
        vat_acc = get_mapped_account_id(db, "acc_map_vat_output")
        ar_acc = get_mapped_account_id(db, "acc_map_ar") or get_mapped_account_id(db, "acc_map_cash")

        je_lines = []

        # Reverse revenue: Dr Revenue / Cr AR (or Cash)
        if revenue_acc and ar_acc and total_revenue_reversed > _D2:
            je_lines.append({
                "account_id": revenue_acc,
                "debit": str(total_revenue_reversed.quantize(_D2, ROUND_HALF_UP)),
                "credit": 0,
                "description": f"POS Cancel Revenue Reversal — {order.order_number}",
            })
            credit_total = total_revenue_reversed + total_tax_reversed
            je_lines.append({
                "account_id": ar_acc,
                "debit": 0,
                "credit": str(credit_total.quantize(_D2, ROUND_HALF_UP)),
                "description": f"POS Cancel AR/Cash Reversal — {order.order_number}",
            })
            # Reverse VAT
            if vat_acc and total_tax_reversed > _D2:
                je_lines.append({
                    "account_id": vat_acc,
                    "debit": str(total_tax_reversed.quantize(_D2, ROUND_HALF_UP)),
                    "credit": 0,
                    "description": f"POS Cancel VAT Reversal — {order.order_number}",
                })

        # Reverse COGS: Dr Inventory / Cr COGS
        if inv_acc and cogs_acc and total_cogs_restored > _D2:
            je_lines.append({
                "account_id": inv_acc,
                "debit": str(total_cogs_restored.quantize(_D2, ROUND_HALF_UP)),
                "credit": 0,
                "description": f"POS Cancel Inventory Restore — {order.order_number}",
            })
            je_lines.append({
                "account_id": cogs_acc,
                "debit": 0,
                "credit": str(total_cogs_restored.quantize(_D2, ROUND_HALF_UP)),
                "description": f"POS Cancel COGS Reversal — {order.order_number}",
            })

        if je_lines:
            gl_create_journal_entry(
                db=db,
                company_id=current_user.company_id,
                date=today_str,
                description=f"إلغاء طلب POS {order.order_number}",
                lines=je_lines,
                user_id=current_user.id,
                branch_id=order.branch_id,
                reference=order.order_number,
                currency=base_currency,
                source="pos_cancellation",
                source_id=sale_id,
                idempotency_key=f"pos_cancel:{sale_id}",
            )

    # ── 6. Mark order as cancelled ───────────────────────────────────────
    db.execute(text("""
        UPDATE pos_orders
        SET status = 'cancelled',
            note = COALESCE(note || ' | ', '') || :reason,
            updated_at = NOW()
        WHERE id = :order_id
    """), {"order_id": sale_id, "reason": body.reason or "Cancelled"})

    db.commit()

    # ── 7. Audit log ─────────────────────────────────────────────────────
    try:
        log_activity(
            db,
            user_id=current_user.id,
            username=current_user.username,
            action="pos.cancel",
            resource_type="pos_order",
            resource_id=str(sale_id),
            details={
                "order_number": order.order_number,
                "reason": body.reason,
                "cogs_restored": str(total_cogs_restored),
                "revenue_reversed": str(total_revenue_reversed),
            },
            request=request,
            branch_id=order.branch_id,
        )
    except Exception:
        pass

    return {"id": sale_id, "status": "cancelled", "message": i18n_message("pos_order_cancelled_success", request)}
