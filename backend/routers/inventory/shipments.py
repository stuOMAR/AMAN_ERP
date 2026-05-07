"""
Inventory Module - Shipments Lifecycle
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime
from decimal import Decimal
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.audit import log_activity
from utils.permissions import branch_scope_filter_from_scope, require_permission, resolve_branch_scope
from utils.accounting import get_mapped_account_id
from services.gl_service import create_journal_entry
from utils.fiscal_lock import check_fiscal_period_open
from .schemas import ShipmentCreate

shipments_router = APIRouter()
logger = logging.getLogger(__name__)


@shipments_router.post("/shipments", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("stock.transfer"))], response_model=Dict[str, Any])
def create_shipment(
    shipment: ShipmentCreate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """إنشاء شحنة جديدة بين المستودعات"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    user_id = current_user.get("id") if isinstance(current_user, dict) else current_user.id
    username = current_user.get("username") if isinstance(current_user, dict) else getattr(current_user, "username", None)
    db = get_db_connection(company_id)
    try:
        if shipment.source_warehouse_id == shipment.destination_warehouse_id:
            raise HTTPException(status_code=400, detail="لا يمكن الشحن لنفس المستودع")

        # Validate warehouses
        src = db.execute(text("SELECT warehouse_name, branch_id FROM warehouses WHERE id = :id"),
                        {"id": shipment.source_warehouse_id}).fetchone()
        dst = db.execute(text("SELECT warehouse_name, branch_id FROM warehouses WHERE id = :id"),
                        {"id": shipment.destination_warehouse_id}).fetchone()

        if not src or not dst:
            raise HTTPException(**http_error(404, "warehouse_not_found"))

        # INV-S01: Branch access check on both warehouses
        allowed = getattr(current_user, 'allowed_branches', []) or []
        if allowed and "*" not in getattr(current_user, 'permissions', []):
            if (src.branch_id and src.branch_id not in allowed) or (dst.branch_id and dst.branch_id not in allowed):
                raise HTTPException(status_code=403, detail="لا يمكنك إنشاء شحنة بين مستودعات خارج فروعك")

        import random
        shipment_ref = f"SHP-{datetime.now().year}-{random.randint(10000, 99999)}"

        # Create shipment
        result = db.execute(text("""
            INSERT INTO stock_shipments (shipment_ref, source_warehouse_id, destination_warehouse_id, 
                                        status, notes, created_by, created_at)
            VALUES (:ref, :src, :dst, 'pending', :notes, :user, NOW())
            RETURNING id
        """), {
            "ref": shipment_ref,
            "src": shipment.source_warehouse_id,
            "dst": shipment.destination_warehouse_id,
            "notes": shipment.notes,
            "user": user_id
        })
        shipment_id = result.fetchone()[0]

        # Add items
        for item in shipment.items:
            # Validate stock availability
            current_qty = db.execute(text("""
                SELECT quantity FROM inventory 
                WHERE product_id = :pid AND warehouse_id = :wh
            """), {"pid": item.product_id, "wh": shipment.source_warehouse_id}).scalar() or 0

            if current_qty < item.quantity:
                prod_name = db.execute(text("SELECT product_name FROM products WHERE id = :pid"),
                                      {"pid": item.product_id}).scalar()
                db.rollback()
                raise HTTPException(status_code=400, detail=f"الكمية غير متوفرة للمنتج: {prod_name}")

            db.execute(text("""
                INSERT INTO stock_shipment_items (shipment_id, product_id, quantity)
                VALUES (:sid, :pid, :qty)
            """), {"sid": shipment_id, "pid": item.product_id, "qty": item.quantity})

        # Create targeted notifications for destination branch
        dest_branch_info = db.execute(text("""
            SELECT branch_id, manager_id FROM warehouses WHERE id = :id
        """), {"id": shipment.destination_warehouse_id}).fetchone()

        if dest_branch_info:
            d_branch_id = dest_branch_info.branch_id
            d_manager_id = dest_branch_info.manager_id

            db.execute(text("""
                INSERT INTO notifications (user_id, type, title, message, link, created_at)
                SELECT DISTINCT u.id, 'shipment_incoming', :title, :message, :link, NOW()
                FROM company_users u
                LEFT JOIN user_branches ub ON u.id = ub.user_id
                WHERE u.is_active = TRUE 
                AND (ub.branch_id = :bid OR u.id = :mid OR u.role = 'superuser' OR u.role = 'admin')
            """), {
                "title": "📦 شحنة واردة جديدة",
                "message": f"شحنة {shipment_ref} من {src.warehouse_name} إلى {dst.warehouse_name} في انتظار التأكيد",
                "link": "/stock/shipments/incoming",
                "bid": d_branch_id,
                "mid": d_manager_id
            })

        db.commit()

        # INV-S01: Audit log
        try:
            log_activity(
                db, user_id=user_id, username=username,
                action="shipment.create", resource_type="stock_shipment",
                resource_id=str(shipment_id), details={"shipment_ref": shipment_ref, "source": shipment.source_warehouse_id, "destination": shipment.destination_warehouse_id},
                request=request, branch_id=src.branch_id
            )
        except Exception:
            pass

        return {"message": "تم إنشاء الشحنة بنجاح", "reference": shipment_ref, "id": shipment_id}

    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@shipments_router.get("/shipments", dependencies=[Depends(require_permission("stock.view"))], response_model=List[Dict[str, Any]])
def list_shipments(
    status_filter: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """عرض جميع الشحنات"""
    db = get_db_connection(current_user.company_id)
    try:
        branch_scope = resolve_branch_scope(current_user, branch_id)
        query = """
            SELECT s.id, s.shipment_ref, s.status, s.notes, s.created_at, s.shipped_at, s.received_at,
                   sw.warehouse_name as source_warehouse,
                   dw.warehouse_name as destination_warehouse,
                   u.full_name as created_by_name,
                   (SELECT COUNT(*) FROM stock_shipment_items WHERE shipment_id = s.id) as item_count
            FROM stock_shipments s
            JOIN warehouses sw ON s.source_warehouse_id = sw.id
            JOIN warehouses dw ON s.destination_warehouse_id = dw.id
            LEFT JOIN company_users u ON s.created_by = u.id
            WHERE 1=1
        """
        params = {}
        if branch_scope["branch_id"] is not None:
            params["branch_id"] = branch_scope["branch_id"]
            query += " AND (sw.branch_id = :branch_id OR dw.branch_id = :branch_id)"
        elif branch_scope["branch_ids"] is not None:
            if branch_scope["branch_ids"]:
                params["allowed_branch_ids"] = branch_scope["branch_ids"]
                query += " AND (sw.branch_id = ANY(:allowed_branch_ids) OR dw.branch_id = ANY(:allowed_branch_ids))"
            else:
                query += " AND 1=0"

        if status_filter:
            query += " AND s.status = :status"
            params["status"] = status_filter
        query += " ORDER BY s.created_at DESC"

        result = db.execute(text(query), params).fetchall()
        return [dict(r._mapping) for r in result]
    finally:
        db.close()


@shipments_router.get("/shipments/incoming", dependencies=[Depends(require_permission("stock.view"))], response_model=List[Dict[str, Any]])
def list_incoming_shipments(
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """عرض الشحنات الواردة المعلقة"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    db = get_db_connection(company_id)
    try:
        branch_scope = resolve_branch_scope(current_user, branch_id)
        query = """
            SELECT s.id, s.shipment_ref, s.status, s.notes, s.created_at,
                   sw.warehouse_name as source_warehouse,
                   dw.warehouse_name as destination_warehouse,
                   u.full_name as created_by_name,
                   (SELECT json_agg(json_build_object(
                       'product_id', i.product_id,
                       'product_name', p.product_name,
                       'quantity', i.quantity
                   )) FROM stock_shipment_items i 
                   JOIN products p ON i.product_id = p.id 
                   WHERE i.shipment_id = s.id) as items
            FROM stock_shipments s
            JOIN warehouses sw ON s.source_warehouse_id = sw.id
            JOIN warehouses dw ON s.destination_warehouse_id = dw.id
            LEFT JOIN company_users u ON s.created_by = u.id
            WHERE s.status = 'pending'
        """
        params = {}
        query += branch_scope_filter_from_scope(branch_scope, "dw.branch_id", params)

        query += " ORDER BY s.created_at DESC"
        result = db.execute(text(query), params).fetchall()
        return [dict(r._mapping) for r in result]
    finally:
        db.close()


@shipments_router.get("/shipments/{id}", dependencies=[Depends(require_permission("stock.view"))], response_model=Dict[str, Any])
def get_shipment_details(
    id: int,
    current_user: dict = Depends(get_current_user)
):
    """عرض تفاصيل شحنة"""
    db = get_db_connection(current_user.company_id)
    try:
        shipment = db.execute(text("""
            SELECT s.*, sw.warehouse_name as source_warehouse, dw.warehouse_name as destination_warehouse,
                   u.full_name as created_by_name, r.full_name as received_by_name
            FROM stock_shipments s
            JOIN warehouses sw ON s.source_warehouse_id = sw.id
            JOIN warehouses dw ON s.destination_warehouse_id = dw.id
            LEFT JOIN company_users u ON s.created_by = u.id
            LEFT JOIN company_users r ON s.received_by = r.id
            WHERE s.id = :id
        """), {"id": id}).fetchone()

        if not shipment:
            raise HTTPException(**http_error(404, "shipment_not_found"))

        # INV-S03: Branch access check
        src_branch = db.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": shipment.source_warehouse_id}).scalar()
        dst_branch = db.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": shipment.destination_warehouse_id}).scalar()
        allowed = getattr(current_user, 'allowed_branches', []) or []
        if allowed and "*" not in getattr(current_user, 'permissions', []):
            if (src_branch and src_branch not in allowed) and (dst_branch and dst_branch not in allowed):
                raise HTTPException(status_code=403, detail="لا يمكنك عرض هذه الشحنة")

        items = db.execute(text("""
            SELECT i.*, p.product_name, p.product_code
            FROM stock_shipment_items i
            JOIN products p ON i.product_id = p.id
            WHERE i.shipment_id = :id
        """), {"id": id}).fetchall()

        return {
            **dict(shipment._mapping),
            "items": [dict(i._mapping) for i in items]
        }
    finally:
        db.close()


@shipments_router.post("/shipments/{id}/confirm", dependencies=[Depends(require_permission("stock.transfer"))], response_model=Dict[str, Any])
def confirm_shipment(
    id: int,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """تأكيد استلام الشحنة"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    user_id = current_user.get("id") if isinstance(current_user, dict) else current_user.id
    username = current_user.get("username") if isinstance(current_user, dict) else getattr(current_user, "username", None)
    db = get_db_connection(company_id)
    try:
        # Get shipment
        shipment = db.execute(text("""
            SELECT s.*, sw.warehouse_name as source_name, dw.warehouse_name as dest_name
            FROM stock_shipments s
            JOIN warehouses sw ON s.source_warehouse_id = sw.id
            JOIN warehouses dw ON s.destination_warehouse_id = dw.id
            WHERE s.id = :id
        """), {"id": id}).fetchone()

        if not shipment:
            raise HTTPException(**http_error(404, "shipment_not_found"))

        if shipment.status != 'pending':
            raise HTTPException(status_code=400, detail="لا يمكن تأكيد هذه الشحنة")

        # INV-S04: Branch access check on destination warehouse
        dst_branch = db.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": shipment.destination_warehouse_id}).scalar()
        allowed = getattr(current_user, 'allowed_branches', []) or []
        if allowed and "*" not in getattr(current_user, 'permissions', []):
            if dst_branch and dst_branch not in allowed:
                raise HTTPException(status_code=403, detail="لا يمكنك تأكيد شحنة لمستودع خارج فروعك")

        # Get items
        items = db.execute(text("""
            SELECT * FROM stock_shipment_items WHERE shipment_id = :id
        """), {"id": id}).fetchall()

        from services.costing_service import CostingService

        # TASK-026: accumulate inventory value in transit for GL posting
        total_transit_value = Decimal("0")

        # Process each item
        for item in items:
            # INV-S05: Lock source inventory row with FOR UPDATE to prevent race conditions
            src_inv = db.execute(text("""
                SELECT quantity FROM inventory
                WHERE product_id = :pid AND warehouse_id = :wh
                FOR UPDATE
            """), {"pid": item.product_id, "wh": shipment.source_warehouse_id}).fetchone()

            src_qty = float(src_inv.quantity) if src_inv else 0
            if src_qty < item.quantity:
                prod_name = db.execute(text("SELECT product_name FROM products WHERE id = :pid"), {"pid": item.product_id}).scalar()
                raise HTTPException(status_code=400, detail=f"الكمية غير متوفرة للمنتج: {prod_name}. المتوفر: {src_qty}")

            # 1. Deduct from source (row already locked)
            db.execute(text("""
                UPDATE inventory SET quantity = quantity - :qty
                WHERE product_id = :pid AND warehouse_id = :wh
            """), {"qty": item.quantity, "pid": item.product_id, "wh": shipment.source_warehouse_id})

            # 2. Get Source Cost for Valuation
            source_cost = CostingService.get_cogs_cost(db, item.product_id, shipment.source_warehouse_id)
            total_transit_value += (Decimal(str(item.quantity)) * Decimal(str(source_cost or 0)))

            # T3.9: move FIFO/LIFO cost layers from source → destination so
            # the destination warehouse keeps an auditable cost history per
            # batch. Without this the cost basis at the destination collapses
            # to a single WAC update and any subsequent FIFO/LIFO valuation
            # at the destination is wrong.
            try:
                policy = CostingService.get_active_policy(db) or "fifo"
                CostingService.consume_layers(
                    db,
                    product_id=item.product_id,
                    warehouse_id=shipment.source_warehouse_id,
                    quantity=item.quantity,
                    sale_document_type="shipment_dispatch",
                    sale_document_id=id,
                    costing_method=policy,
                )
                # T10.1 P1 #101 — recreate one destination layer per
                # *source* layer (preserving its original unit_cost) so
                # FIFO/LIFO valuation at the destination matches the
                # source. Old code created a single bulk layer at the
                # WAC source_cost, which lost the basis.
                consumed = db.execute(text("""
                    SELECT cl.unit_cost, clc.quantity_consumed
                      FROM cost_layer_consumptions clc
                      JOIN cost_layers cl ON cl.id = clc.cost_layer_id
                     WHERE clc.sale_document_type = 'shipment_dispatch'
                       AND clc.sale_document_id = :sid
                       AND cl.product_id = :pid
                       AND cl.warehouse_id = :wid
                """), {
                    "sid": id,
                    "pid": item.product_id,
                    "wid": shipment.source_warehouse_id,
                }).fetchall()
                if consumed:
                    for src_layer in consumed:
                        CostingService.create_cost_layer(
                            db,
                            product_id=item.product_id,
                            warehouse_id=shipment.destination_warehouse_id,
                            quantity=float(src_layer.quantity_consumed),
                            unit_cost=float(src_layer.unit_cost or 0),
                            source_document_type="shipment_receive",
                            source_document_id=id,
                            costing_method=policy,
                        )
                else:
                    # Defensive fallback (no consumption rows): keep the
                    # legacy single-layer behaviour using the WAC cost.
                    CostingService.create_cost_layer(
                        db,
                        product_id=item.product_id,
                        warehouse_id=shipment.destination_warehouse_id,
                        quantity=item.quantity,
                        unit_cost=float(source_cost or 0),
                        source_document_type="shipment_receive",
                        source_document_id=id,
                        costing_method=policy,
                    )
            except ValueError:
                # Source warehouse has no cost layers (legacy stock created
                # outside the layered system). Leave the WAC update below
                # to keep the valuation reasonable; do NOT block the move.
                pass

            # 3. Update Destination Cost (WAC Calculation)
            CostingService.update_cost(
                db,
                product_id=item.product_id,
                warehouse_id=shipment.destination_warehouse_id,
                new_qty=float(item.quantity),
                new_price=float(source_cost)
            )

            # 4. Add to destination Qty
            exists = db.execute(text("""
                SELECT 1 FROM inventory WHERE product_id = :pid AND warehouse_id = :wh
            """), {"pid": item.product_id, "wh": shipment.destination_warehouse_id}).scalar()

            if exists:
                db.execute(text("""
                    UPDATE inventory SET quantity = quantity + :qty
                    WHERE product_id = :pid AND warehouse_id = :wh
                """), {"qty": item.quantity, "pid": item.product_id, "wh": shipment.destination_warehouse_id})
            else:
                exists_now = db.execute(text("""
                    SELECT 1 FROM inventory WHERE product_id = :pid AND warehouse_id = :wh
                """), {"pid": item.product_id, "wh": shipment.destination_warehouse_id}).scalar()

                if exists_now:
                    db.execute(text("UPDATE inventory SET quantity = quantity + :qty WHERE product_id = :pid AND warehouse_id = :wh"),
                               {"qty": item.quantity, "pid": item.product_id, "wh": shipment.destination_warehouse_id})
                else:
                    db.execute(text("""
                        INSERT INTO inventory (product_id, warehouse_id, quantity)
                        VALUES (:pid, :wh, :qty)
                    """), {"pid": item.product_id, "wh": shipment.destination_warehouse_id, "qty": item.quantity})

            # 5. Log transactions
            db.execute(text("""
                INSERT INTO inventory_transactions (product_id, warehouse_id, transaction_type, 
                                                   reference_type, quantity, notes, created_by)
                VALUES (:pid, :wh, 'shipment_out', 'shipment', :qty, :notes, :user)
            """), {
                "pid": item.product_id,
                "wh": shipment.source_warehouse_id,
                "qty": -item.quantity,
                "notes": f"Shipment {shipment.shipment_ref} to {shipment.dest_name}",
                "user": user_id
            })

            db.execute(text("""
                INSERT INTO inventory_transactions (product_id, warehouse_id, transaction_type, 
                                                   reference_type, quantity, notes, created_by)
                VALUES (:pid, :wh, 'shipment_in', 'shipment', :qty, :notes, :user)
            """), {
                "pid": item.product_id,
                "wh": shipment.destination_warehouse_id,
                "qty": item.quantity,
                "notes": f"Shipment {shipment.shipment_ref} from {shipment.source_name}",
                "user": user_id
            })

            # 5b. Log in stock_transfer_log (V2 Upgrade)
            dest_stats_after = db.execute(text("""
                SELECT average_cost FROM inventory 
                WHERE product_id = :pid AND warehouse_id = :wh
            """), {"pid": item.product_id, "wh": shipment.destination_warehouse_id}).fetchone()

            db.execute(text("""
                INSERT INTO stock_transfer_log 
                (shipment_id, product_id, from_warehouse_id, to_warehouse_id, quantity, transfer_cost, 
                 from_avg_cost_before, to_avg_cost_before, to_avg_cost_after)
                VALUES (:sid, :pid, :fwh, :twh, :qty, :tcost, :fcast, :tcast_b, :tcast_a)
            """), {
                "sid": id,
                "pid": item.product_id,
                "fwh": shipment.source_warehouse_id,
                "twh": shipment.destination_warehouse_id,
                "qty": item.quantity,
                "tcost": source_cost,
                "fcast": source_cost,
                "tcast_b": 0,
                "tcast_a": float(dest_stats_after.average_cost if dest_stats_after else 0)
            })

        # TASK-026: Post GL entries recording the inter-warehouse transfer via
        # the Inventory-in-Transit bridge account. We emit two balanced JEs so
        # that the In-Transit account has a visible (net-zero) round trip in the
        # GL, which auditors expect for warehouse-to-warehouse movements.
        if total_transit_value > Decimal("0"):
            inv_acc = get_mapped_account_id(db, "acc_map_inventory")
            intransit_acc = get_mapped_account_id(db, "acc_map_in_transit")
            if inv_acc and intransit_acc:
                today_str = datetime.utcnow().strftime("%Y-%m-%d")
                # Fiscal-period lock: block posting into a closed period.
                check_fiscal_period_open(db, today_str)
                value_f = float(total_transit_value)
                # Leg A: dispatch — Dr In-Transit / Cr Source Inventory
                create_journal_entry(
                    db=db,
                    company_id=str(company_id),
                    date=today_str,
                    description=f"Shipment {shipment.shipment_ref}: dispatch to in-transit",
                    lines=[
                        {"account_id": intransit_acc, "debit": value_f, "credit": 0},
                        {"account_id": inv_acc, "debit": 0, "credit": value_f},
                    ],
                    user_id=user_id,
                    reference=shipment.shipment_ref,
                    source="shipment_dispatch",
                    source_id=id,
                    username=username,
                    idempotency_key=f"shipment_dispatch:{id}",
                )
                # Leg B: receipt — Dr Destination Inventory / Cr In-Transit
                create_journal_entry(
                    db=db,
                    company_id=str(company_id),
                    date=today_str,
                    description=f"Shipment {shipment.shipment_ref}: received into destination",
                    lines=[
                        {"account_id": inv_acc, "debit": value_f, "credit": 0},
                        {"account_id": intransit_acc, "debit": 0, "credit": value_f},
                    ],
                    user_id=user_id,
                    reference=shipment.shipment_ref,
                    source="shipment_receive",
                    source_id=id,
                    username=username,
                    idempotency_key=f"shipment_receive:{id}",
                )

        # Update shipment status
        db.execute(text("""
            UPDATE stock_shipments 
            SET status = 'received', received_at = NOW(), received_by = :user
            WHERE id = :id
        """), {"id": id, "user": user_id})

        # Notify sender
        db.execute(text("""
            INSERT INTO notifications (user_id, type, title, message, link, created_at)
            VALUES (:user, 'shipment_confirmed', :title, :message, :link, NOW())
        """), {
            "user": shipment.created_by,
            "title": "✅ تم تأكيد استلام الشحنة",
            "message": f"تم تأكيد استلام الشحنة {shipment.shipment_ref} في {shipment.dest_name}",
            "link": f"/stock/shipments/{id}"
        })

        db.commit()

        # INV-S04: Audit log
        try:
            log_activity(
                db, user_id=user_id, username=username,
                action="shipment.confirm", resource_type="stock_shipment",
                resource_id=str(id), details={"shipment_ref": shipment.shipment_ref, "items_count": len(items)},
                request=request, branch_id=dst_branch
            )
        except Exception:
            pass

        return {"message": "تم تأكيد استلام الشحنة بنجاح"}

    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@shipments_router.post("/shipments/{id}/cancel", dependencies=[Depends(require_permission("stock.manage"))], response_model=Dict[str, Any])
def cancel_shipment(
    id: int,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """إلغاء الشحنة"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    user_id = current_user.get("id") if isinstance(current_user, dict) else current_user.id
    username = current_user.get("username") if isinstance(current_user, dict) else getattr(current_user, "username", None)
    db = get_db_connection(company_id)
    try:
        shipment = db.execute(text("""
            SELECT s.*, sw.branch_id as src_branch_id FROM stock_shipments s
            JOIN warehouses sw ON s.source_warehouse_id = sw.id
            WHERE s.id = :id
        """), {"id": id}).fetchone()

        if not shipment:
            raise HTTPException(**http_error(404, "shipment_not_found"))

        if shipment.status != 'pending':
            raise HTTPException(status_code=400, detail="لا يمكن إلغاء هذه الشحنة")

        # INV-S06: Branch access check
        allowed = getattr(current_user, 'allowed_branches', []) or []
        if allowed and "*" not in getattr(current_user, 'permissions', []):
            if shipment.src_branch_id and shipment.src_branch_id not in allowed:
                raise HTTPException(status_code=403, detail="لا يمكنك إلغاء هذه الشحنة")

        db.execute(text("""
            UPDATE stock_shipments SET status = 'cancelled' WHERE id = :id
        """), {"id": id})

        db.commit()

        # INV-S06: Audit log
        try:
            log_activity(
                db, user_id=user_id, username=username,
                action="shipment.cancel", resource_type="stock_shipment",
                resource_id=str(id), details={"shipment_ref": shipment.shipment_ref},
                request=request, branch_id=shipment.src_branch_id
            )
        except Exception:
            pass

        return {"message": "تم إلغاء الشحنة"}

    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
