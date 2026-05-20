"""
Inventory Module - Shipments Lifecycle
"""

from fastapi import APIRouter, Depends, Header, HTTPException, status, Request
from utils.i18n import http_error, i18n_message
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.audit import log_activity
from utils.permissions import branch_scope_filter_from_scope, require_permission, resolve_branch_scope
from utils.accounting import get_mapped_account_id
from utils.quantity_validation import validate_quantities_for_products
from services.gl_service import create_journal_entry
from utils.fiscal_lock import check_fiscal_period_open
from .schemas import ShipmentCreate

shipments_router = APIRouter()
logger = logging.getLogger(__name__)


@shipments_router.post("/shipments", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("stock.transfer"))], response_model=Dict[str, Any])
def create_shipment(
    shipment: ShipmentCreate,
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key", max_length=64),
    current_user: dict = Depends(get_current_user)
):
    """إنشاء شحنة جديدة بين المستودعات"""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    user_id = current_user.get("id") if isinstance(current_user, dict) else current_user.id
    username = current_user.get("username") if isinstance(current_user, dict) else getattr(current_user, "username", None)
    db = get_db_connection(company_id)
    try:
        if not idempotency_key:
            raise HTTPException(**http_error(400, "idempotency_key_required", request))
        existing = db.execute(text("""
            SELECT id, shipment_ref FROM stock_shipments WHERE idempotency_key = :key LIMIT 1
        """), {"key": idempotency_key}).fetchone()
        if existing:
            return {"id": existing.id, "shipment_ref": existing.shipment_ref, "message": i18n_message("shipment_created_success", request), "idempotent_replay": True}

        if shipment.source_warehouse_id == shipment.destination_warehouse_id:
            raise HTTPException(**http_error(400, "same_warehouse_shipment", request))

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
                raise HTTPException(**http_error(403, "cross_branch_shipment_create_denied", request))

        import random
        shipment_ref = f"SHP-{datetime.now().year}-{random.randint(10000, 99999)}"

        # INV-QTY: Validate quantities for discrete units
        validate_quantities_for_products(db, shipment.items, request)

        aggregated: dict[int, Decimal] = {}
        for item in shipment.items:
            pid = int(item.product_id)
            aggregated[pid] = aggregated.get(pid, Decimal("0")) + Decimal(str(item.quantity))

        for pid, requested_qty in aggregated.items():
            inv_row = db.execute(text("""
                SELECT quantity, COALESCE(reserved_quantity, 0) AS reserved_quantity
                FROM inventory
                WHERE product_id = :pid AND warehouse_id = :wh
                FOR UPDATE
            """), {"pid": pid, "wh": shipment.source_warehouse_id}).fetchone()
            current_qty = Decimal(str(inv_row.quantity)) if inv_row else Decimal("0")
            reserved_qty = Decimal(str(inv_row.reserved_quantity or 0)) if inv_row else Decimal("0")
            pending_qty = db.execute(text("""
                SELECT COALESCE(SUM(si.quantity), 0)
                FROM stock_shipment_items si
                JOIN stock_shipments s ON s.id = si.shipment_id
                WHERE s.source_warehouse_id = :wh
                  AND s.status = 'pending'
                  AND si.product_id = :pid
            """), {"pid": pid, "wh": shipment.source_warehouse_id}).scalar() or 0
            available_qty = current_qty - reserved_qty - Decimal(str(pending_qty))
            if available_qty < requested_qty:
                raise HTTPException(status_code=400, detail=i18n_message("qty_not_available", request))

        # Create shipment
        result = db.execute(text("""
            INSERT INTO stock_shipments (shipment_ref, source_warehouse_id, destination_warehouse_id, 
                                        status, notes, created_by, idempotency_key, created_at)
            VALUES (:ref, :src, :dst, 'pending', :notes, :user, :idem_key, NOW())
            RETURNING id
        """), {
            "ref": shipment_ref,
            "src": shipment.source_warehouse_id,
            "dst": shipment.destination_warehouse_id,
            "notes": shipment.notes,
            "user": user_id,
            "idem_key": idempotency_key,
        })
        shipment_id = result.fetchone()[0]

        # Add items
        for item in shipment.items:
            # Validate stock availability with row lock to prevent race conditions
            inv_row = db.execute(text("""
                SELECT quantity, COALESCE(reserved_quantity, 0) as reserved_quantity
                FROM inventory
                WHERE product_id = :pid AND warehouse_id = :wh
                FOR UPDATE
            """), {"pid": item.product_id, "wh": shipment.source_warehouse_id}).fetchone()

            current_qty = inv_row.quantity if inv_row else 0
            reserved_qty = inv_row.reserved_quantity if inv_row else 0
            available_qty = current_qty - reserved_qty

            if available_qty < item.quantity:
                # Don't manually rollback — let the outer except handler do it.
                raise HTTPException(status_code=400, detail=i18n_message("qty_not_available", request))

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
                "title": i18n_message("notif_incoming_shipment", request),
                "message": i18n_message("shipment_pending_confirmation", request),
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

        return {"message": i18n_message("shipment_created_success", request), "reference": shipment_ref, "id": shipment_id}

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@shipments_router.get("/shipments", dependencies=[Depends(require_permission("stock.view"))], response_model=Dict[str, Any])
def list_shipments(
    status_filter: Optional[str] = None,
    branch_id: Optional[int] = None,
    page: int = 1,
    limit: int = 25,
    current_user: dict = Depends(get_current_user)
):
    """عرض جميع الشحنات — INV-20: paginated, default 25, max 100."""
    if limit > 100:
        limit = 100
    skip = (page - 1) * limit
    db = get_db_connection(current_user.company_id)
    try:
        branch_scope = resolve_branch_scope(current_user, branch_id)
        base_from = """
            FROM stock_shipments s
            JOIN warehouses sw ON s.source_warehouse_id = sw.id
            JOIN warehouses dw ON s.destination_warehouse_id = dw.id
            LEFT JOIN company_users u ON s.created_by = u.id
            WHERE 1=1
        """
        params: Dict[str, Any] = {}

        if branch_scope["branch_id"] is not None:
            params["branch_id"] = branch_scope["branch_id"]
            base_from += " AND (sw.branch_id = :branch_id OR dw.branch_id = :branch_id)"
        elif branch_scope["branch_ids"] is not None:
            if branch_scope["branch_ids"]:
                params["allowed_branch_ids"] = branch_scope["branch_ids"]
                base_from += " AND (sw.branch_id = ANY(:allowed_branch_ids) OR dw.branch_id = ANY(:allowed_branch_ids))"
            else:
                base_from += " AND 1=0"

        if status_filter:
            base_from += " AND s.status = :status"
            params["status"] = status_filter

        total = db.execute(text(f"SELECT COUNT(*) {base_from}"), params).scalar() or 0

        params["limit"] = limit
        params["skip"] = skip
        result = db.execute(text(f"""
            SELECT s.id, s.shipment_ref, s.status, s.notes, s.created_at, s.shipped_at, s.received_at,
                   sw.warehouse_name as source_warehouse,
                   dw.warehouse_name as destination_warehouse,
                   u.full_name as created_by_name,
                   (SELECT COUNT(*) FROM stock_shipment_items WHERE shipment_id = s.id) as item_count
            {base_from}
            ORDER BY s.created_at DESC
            LIMIT :limit OFFSET :skip
        """), params).fetchall()

        return {
            "items": [dict(r._mapping) for r in result],
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit,
        }
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
            WHERE s.status = 'dispatched'
        """
        params = {}
        query += branch_scope_filter_from_scope(branch_scope, "dw.branch_id", params)

        query += " ORDER BY s.created_at DESC"
        result = db.execute(text(query), params).fetchall()
        return [dict(r._mapping) for r in result]
    finally:
        db.close()


@shipments_router.get("/shipments/{id}", dependencies=[Depends(require_permission("stock.view"))], response_model=Dict[str, Any])
def get_shipment_details(request: Request, 
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
                raise HTTPException(**http_error(403, "shipment_not_viewable", request))

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


@shipments_router.post("/shipments/{id}/dispatch", dependencies=[Depends(require_permission("stock.transfer"))], response_model=Dict[str, Any])
def dispatch_shipment(
    id: int,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """T052-T054: Dispatch shipment — move source stock to in-transit."""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    user_id = current_user.get("id") if isinstance(current_user, dict) else current_user.id
    username = current_user.get("username") if isinstance(current_user, dict) else getattr(current_user, "username", None)
    db = get_db_connection(company_id)
    try:
        # T052: Lock shipment row FOR UPDATE
        shipment = db.execute(text("""
            SELECT s.*, sw.warehouse_name as source_name, dw.warehouse_name as dest_name
            FROM stock_shipments s
            JOIN warehouses sw ON s.source_warehouse_id = sw.id
            JOIN warehouses dw ON s.destination_warehouse_id = dw.id
            WHERE s.id = :id
            FOR UPDATE OF s
        """), {"id": id}).fetchone()

        if not shipment:
            raise HTTPException(**http_error(404, "shipment_not_found"))

        # T052: Reject already dispatched/received/cancelled
        if shipment.status != 'pending':
            raise HTTPException(status_code=400, detail=i18n_message("shipment_invalid_status", request))

        # Branch access check
        dst_branch = db.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": shipment.destination_warehouse_id}).scalar()
        allowed = getattr(current_user, 'allowed_branches', []) or []
        if allowed and "*" not in getattr(current_user, 'permissions', []):
            src_branch = db.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": shipment.source_warehouse_id}).scalar()
            if src_branch and src_branch not in allowed:
                raise HTTPException(**http_error(403, "cross_branch_shipment_dispatch_denied", request))

        # T053: Validate account mappings
        # F-31: dispatch credits the SOURCE warehouse's inventory account.
        from utils.inventory_accounts import resolve_warehouse_inventory_account
        inv_acc = resolve_warehouse_inventory_account(db, shipment.source_warehouse_id)
        intransit_acc = get_mapped_account_id(db, "acc_map_in_transit")
        if not inv_acc:
            raise HTTPException(**http_error(400, "inventory_account_not_configured", request))
        if not intransit_acc:
            raise HTTPException(**http_error(400, "in_transit_account_not_configured", request))

        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        check_fiscal_period_open(db, today_str)

        items = db.execute(text("""
            SELECT * FROM stock_shipment_items WHERE shipment_id = :id
        """), {"id": id}).fetchall()

        from services.costing_service import CostingService
        total_transit_value = Decimal("0")

        for item in items:
            # T053: Lock source inventory, check available quantity
            src_inv = db.execute(text("""
                SELECT quantity, reserved_quantity, in_transit_quantity FROM inventory
                WHERE product_id = :pid AND warehouse_id = :wh
                FOR UPDATE
            """), {"pid": item.product_id, "wh": shipment.source_warehouse_id}).fetchone()

            src_qty = Decimal(str(src_inv.quantity)) if src_inv else Decimal("0")
            reserved = Decimal(str(src_inv.reserved_quantity or 0)) if src_inv else Decimal("0")
            item_qty = Decimal(str(item.quantity))
            available = src_qty - reserved
            if available < item_qty:
                prod_name = db.execute(text("SELECT product_name FROM products WHERE id = :pid"), {"pid": item.product_id}).scalar()
                raise HTTPException(status_code=400, detail=i18n_message("qty_not_available", request))

            # T054: Consume FIFO/LIFO source layers before deducting source qty.
            method = CostingService._get_product_costing_method(db, item.product_id, shipment.source_warehouse_id)
            try:
                if method in ("fifo", "lifo"):
                    item_value = Decimal(str(CostingService.consume_layers(
                        db,
                        product_id=item.product_id,
                        warehouse_id=shipment.source_warehouse_id,
                        quantity=item_qty,
                        sale_document_type="shipment_dispatch",
                        sale_document_id=id,
                        costing_method=method,
                    )))
                    source_cost = (item_value / item_qty).quantize(Decimal("0.0001"), ROUND_HALF_UP) if item_qty else Decimal("0")
                else:
                    source_cost = CostingService.get_cogs_cost(db, item.product_id, shipment.source_warehouse_id)
                    item_value = (item_qty * source_cost).quantize(Decimal("0.0001"), ROUND_HALF_UP)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))

            # T053: Atomically deduct source quantity and increase in_transit_quantity
            db.execute(text("""
                UPDATE inventory
                SET quantity = quantity - :qty,
                    in_transit_quantity = COALESCE(in_transit_quantity, 0) + :qty,
                    updated_at = NOW()
                WHERE product_id = :pid AND warehouse_id = :wh
            """), {"qty": item.quantity, "pid": item.product_id, "wh": shipment.source_warehouse_id})

            total_transit_value += item_value

            # T053: Create shipment_dispatch inventory transaction
            db.execute(text("""
                INSERT INTO inventory_transactions (product_id, warehouse_id, transaction_type,
                                                   reference_type, reference_id, quantity, notes, created_by, unit_cost, total_cost)
                VALUES (:pid, :wh, 'shipment_out', 'shipment_dispatch', :sid, :qty, :notes, :user, :uc, :tc)
            """), {
                "pid": item.product_id,
                "wh": shipment.source_warehouse_id,
                "sid": id,
                "qty": -item.quantity,
                "notes": f"Shipment Dispatch {shipment.shipment_ref} to {shipment.dest_name}",
                "user": user_id,
                "uc": str(source_cost or 0),
                "tc": str(item_value),
            })

        # T053: Post GL — Dr In-Transit / Cr Source Inventory
        if total_transit_value > Decimal("0"):
            value_f = total_transit_value  # Decimal
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

        # Update shipment status
        db.execute(text("""
            UPDATE stock_shipments SET status = 'dispatched', shipped_at = NOW() WHERE id = :id
        """), {"id": id})

        db.commit()

        log_activity(
            db, user_id=user_id, username=username,
            action="shipment.dispatch", resource_type="stock_shipment",
            resource_id=str(id), details={"shipment_ref": shipment.shipment_ref, "items_count": len(items)},
            request=request,
        )

        return {"message": i18n_message("shipment_dispatched_success", request), "status": "dispatched"}

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@shipments_router.post("/shipments/{id}/confirm", dependencies=[Depends(require_permission("stock.transfer"))], response_model=Dict[str, Any])
def confirm_shipment(
    id: int,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """T055-T056: Confirm/receive shipment — move in-transit to destination.

    Idempotent: rejects already received/cancelled shipments.
    Only allowed from 'dispatched' state.
    """
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    user_id = current_user.get("id") if isinstance(current_user, dict) else current_user.id
    username = current_user.get("username") if isinstance(current_user, dict) else getattr(current_user, "username", None)
    db = get_db_connection(company_id)
    try:
        # T055: Lock shipment row FOR UPDATE
        shipment = db.execute(text("""
            SELECT s.*, sw.warehouse_name as source_name, dw.warehouse_name as dest_name
            FROM stock_shipments s
            JOIN warehouses sw ON s.source_warehouse_id = sw.id
            JOIN warehouses dw ON s.destination_warehouse_id = dw.id
            WHERE s.id = :id
            FOR UPDATE OF s
        """), {"id": id}).fetchone()

        if not shipment:
            raise HTTPException(**http_error(404, "shipment_not_found"))

        # T055: Idempotent — reject already received/cancelled
        if shipment.status == 'received':
            raise HTTPException(**http_error(400, "shipment_already_received", request))
        if shipment.status == 'cancelled':
            raise HTTPException(**http_error(400, "cannot_receive_cancelled", request))
        if shipment.status != 'dispatched':
            raise HTTPException(status_code=400, detail=i18n_message("cannot_receive_shipment_status", request))

        # Branch access check on destination warehouse
        dst_branch = db.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": shipment.destination_warehouse_id}).scalar()
        allowed = getattr(current_user, 'allowed_branches', []) or []
        if allowed and "*" not in getattr(current_user, 'permissions', []):
            if dst_branch and dst_branch not in allowed:
                raise HTTPException(**http_error(403, "cross_branch_receive_denied", request))

        # T056: Validate account mappings
        # F-31: receive debits the DESTINATION warehouse's inventory account.
        from utils.inventory_accounts import resolve_warehouse_inventory_account
        inv_acc = resolve_warehouse_inventory_account(db, shipment.destination_warehouse_id)
        intransit_acc = get_mapped_account_id(db, "acc_map_in_transit")
        if not inv_acc or not intransit_acc:
            raise HTTPException(**http_error(400, "inventory_transit_accounts_not_configured", request))

        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        check_fiscal_period_open(db, today_str)

        items = db.execute(text("""
            SELECT * FROM stock_shipment_items WHERE shipment_id = :id
        """), {"id": id}).fetchall()

        from services.costing_service import CostingService
        total_transit_value = Decimal("0")

        for item in items:
            # T055: Lock source inventory for in_transit_quantity deduction
            src_inv = db.execute(text("""
                SELECT in_transit_quantity FROM inventory
                WHERE product_id = :pid AND warehouse_id = :wh
                FOR UPDATE
            """), {"pid": item.product_id, "wh": shipment.source_warehouse_id}).fetchone()

            in_transit = Decimal(str(src_inv.in_transit_quantity or 0)) if src_inv else Decimal("0")
            if in_transit < Decimal(str(item.quantity)):
                prod_name = db.execute(text("SELECT product_name FROM products WHERE id = :pid"), {"pid": item.product_id}).scalar()
                raise HTTPException(status_code=400, detail=i18n_message("transit_qty_insufficient", request))

            # T055: Deduct from source in_transit_quantity
            db.execute(text("""
                UPDATE inventory SET in_transit_quantity = in_transit_quantity - :qty, updated_at = NOW()
                WHERE product_id = :pid AND warehouse_id = :wh
            """), {"qty": item.quantity, "pid": item.product_id, "wh": shipment.source_warehouse_id})

            item_qty = Decimal(str(item.quantity))
            dispatch_cost_row = db.execute(text("""
                SELECT COALESCE(
                           SUM(ABS(total_cost)) / NULLIF(SUM(ABS(quantity)), 0),
                           MAX(unit_cost),
                           0
                       ) AS unit_cost,
                       COALESCE(SUM(ABS(total_cost)), 0) AS total_cost,
                       COUNT(*) AS tx_count
                FROM inventory_transactions
                WHERE reference_type = 'shipment_dispatch'
                  AND reference_id = :sid
                  AND product_id = :pid
                  AND warehouse_id = :wid
            """), {
                "sid": id,
                "pid": item.product_id,
                "wid": shipment.source_warehouse_id,
            }).fetchone()
            if not dispatch_cost_row or Decimal(str(dispatch_cost_row.tx_count or 0)) <= 0:
                raise HTTPException(**http_error(400, "no_valid_stock_movement", request))
            source_cost = Decimal(str(dispatch_cost_row.unit_cost or 0))
            item_value = Decimal(str(dispatch_cost_row.total_cost or 0))
            total_transit_value += item_value

            # T055: Create destination cost layers from dispatch consumption details
            dest_method = CostingService._get_product_costing_method(db, item.product_id, shipment.destination_warehouse_id)
            if dest_method in ("fifo", "lifo"):
                consumed = db.execute(text("""
                    SELECT cl.unit_cost, clc.quantity_consumed
                      FROM cost_layer_consumptions clc
                      JOIN cost_layers cl ON cl.id = clc.cost_layer_id
                     WHERE clc.sale_document_type = 'shipment_dispatch'
                       AND clc.sale_document_id = :sid
                       AND cl.product_id = :pid
                       AND cl.warehouse_id = :wid
                """), {
                        "sid": id, "pid": item.product_id, "wid": shipment.source_warehouse_id,
                    }).fetchall()
                if consumed:
                    for src_layer in consumed:
                        CostingService.create_cost_layer(
                            db,
                            product_id=item.product_id,
                            warehouse_id=shipment.destination_warehouse_id,
                            quantity=Decimal(str(src_layer.quantity_consumed)),
                            unit_cost=Decimal(str(src_layer.unit_cost or 0)),
                            source_document_type="shipment_receive",
                            source_document_id=id,
                            costing_method=dest_method,
                        )
                else:
                    CostingService.create_cost_layer(
                        db,
                        product_id=item.product_id,
                        warehouse_id=shipment.destination_warehouse_id,
                        quantity=Decimal(str(item.quantity)),
                        unit_cost=source_cost,
                        source_document_type="shipment_receive",
                        source_document_id=id,
                        costing_method=dest_method,
                    )

            # T055: Update destination WAC
            CostingService.update_cost(
                db,
                product_id=item.product_id,
                warehouse_id=shipment.destination_warehouse_id,
                new_qty=Decimal(str(item.quantity)),
                new_price=source_cost,
            )

            # T055: Add to destination quantity
            db.execute(text("""
                INSERT INTO inventory (product_id, warehouse_id, quantity, average_cost, updated_at)
                VALUES (:pid, :wh, :qty, :cost, NOW())
                ON CONFLICT (product_id, warehouse_id)
                DO UPDATE SET quantity = inventory.quantity + EXCLUDED.quantity,
                              updated_at = NOW()
            """), {
                "pid": item.product_id,
                "wh": shipment.destination_warehouse_id,
                "qty": str(item_qty),
                "cost": str(source_cost or 0),
            })

            # T056: Create receipt inventory transaction
            db.execute(text("""
                INSERT INTO inventory_transactions (product_id, warehouse_id, transaction_type,
                                                   reference_type, reference_id, quantity, notes, created_by, unit_cost, total_cost)
                VALUES (:pid, :wh, 'shipment_in', 'shipment_receive', :sid, :qty, :notes, :user, :uc, :tc)
            """), {
                "pid": item.product_id,
                "wh": shipment.destination_warehouse_id,
                "sid": id,
                "qty": item.quantity,
                "notes": f"Shipment Receive {shipment.shipment_ref} from {shipment.source_name}",
                "user": user_id,
                "uc": str(source_cost or 0),
                "tc": str(item_value),
            })

            # Transfer log
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
                "sid": id, "pid": item.product_id,
                "fwh": shipment.source_warehouse_id, "twh": shipment.destination_warehouse_id,
                "qty": str(Decimal(str(item.quantity))),
                "tcost": str(source_cost),
                "fcast": str(source_cost),
                "tcast_b": "0",
                "tcast_a": str(Decimal(str(dest_stats_after.average_cost)) if dest_stats_after else Decimal("0")),
            })

        # T056: Post GL — Dr Destination Inventory / Cr In-Transit
        if total_transit_value > Decimal("0"):
            value_f = total_transit_value  # Decimal
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
            "title": i18n_message("notif_shipment_received", request),
            "message": i18n_message("shipment_received_at", request),
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

        return {"message": i18n_message("shipment_received_success", request)}

    except HTTPException:
        db.rollback()
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
            if shipment.status == 'dispatched':
                raise HTTPException(status_code=400, detail="لا يمكن إلغاء شحنة مرسلة. استخدم 'استرداد الشحنة' بدلاً من ذلك.")
            raise HTTPException(**http_error(400, "shipment_cannot_cancel", request))

        # INV-S06: Branch access check
        allowed = getattr(current_user, 'allowed_branches', []) or []
        if allowed and "*" not in getattr(current_user, 'permissions', []):
            if shipment.src_branch_id and shipment.src_branch_id not in allowed:
                raise HTTPException(**http_error(403, "cross_branch_cancel_denied", request))

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

        return {"message": i18n_message("shipment_cancelled_success", request)}

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@shipments_router.post("/shipments/{id}/recall", dependencies=[Depends(require_permission("stock.manage"))], response_model=Dict[str, Any])
def recall_shipment(
    id: int,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """INV-RECALL: Recall a dispatched shipment — reverse in-transit back to source.

    Only allowed from 'dispatched' state. Reverses the GL entry and restores
    source inventory quantity from in_transit_quantity.
    """
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    user_id = current_user.get("id") if isinstance(current_user, dict) else current_user.id
    username = current_user.get("username") if isinstance(current_user, dict) else getattr(current_user, "username", None)
    db = get_db_connection(company_id)
    try:
        # Lock shipment row
        shipment = db.execute(text("""
            SELECT s.*, sw.warehouse_name as source_name, dw.warehouse_name as dest_name
            FROM stock_shipments s
            JOIN warehouses sw ON s.source_warehouse_id = sw.id
            JOIN warehouses dw ON s.destination_warehouse_id = dw.id
            WHERE s.id = :id
            FOR UPDATE OF s
        """), {"id": id}).fetchone()

        if not shipment:
            raise HTTPException(**http_error(404, "shipment_not_found"))

        if shipment.status != 'dispatched':
            raise HTTPException(status_code=400, detail="يمكن استرداد الشحنات المرسلة فقط (dispatched)")

        # Branch access check
        allowed = getattr(current_user, 'allowed_branches', []) or []
        if allowed and "*" not in getattr(current_user, 'permissions', []):
            src_branch = db.execute(text("SELECT branch_id FROM warehouses WHERE id = :id"), {"id": shipment.source_warehouse_id}).scalar()
            if src_branch and src_branch not in allowed:
                raise HTTPException(**http_error(403, "cross_branch_recall_denied", request))

        # Validate account mappings
        # F-31: recall returns goods back into the SOURCE warehouse's inventory account.
        from utils.inventory_accounts import resolve_warehouse_inventory_account
        inv_acc = resolve_warehouse_inventory_account(db, shipment.source_warehouse_id)
        intransit_acc = get_mapped_account_id(db, "acc_map_in_transit")
        if not inv_acc or not intransit_acc:
            raise HTTPException(**http_error(400, "inventory_transit_accounts_not_configured", request))

        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        check_fiscal_period_open(db, today_str)

        items = db.execute(text("""
            SELECT * FROM stock_shipment_items WHERE shipment_id = :id
        """), {"id": id}).fetchall()

        from services.costing_service import CostingService
        total_recall_value = Decimal("0")

        for item in items:
            item_qty = Decimal(str(item.quantity))

            # Lock source inventory row
            src_inv = db.execute(text("""
                SELECT quantity, in_transit_quantity, average_cost FROM inventory
                WHERE product_id = :pid AND warehouse_id = :wh
                FOR UPDATE
            """), {"pid": item.product_id, "wh": shipment.source_warehouse_id}).fetchone()

            in_transit = Decimal(str(src_inv.in_transit_quantity or 0)) if src_inv else Decimal("0")
            if in_transit < item_qty:
                prod_name = db.execute(text("SELECT product_name FROM products WHERE id = :pid"), {"pid": item.product_id}).scalar()
                raise HTTPException(status_code=400, detail=f"كمية العبور غير كافية للمنتج {prod_name}")

            # Get the dispatch cost from original transaction
            dispatch_cost_row = db.execute(text("""
                SELECT COALESCE(
                           SUM(ABS(total_cost)) / NULLIF(SUM(ABS(quantity)), 0),
                           MAX(unit_cost),
                           0
                       ) AS unit_cost,
                       COALESCE(SUM(ABS(total_cost)), 0) AS total_cost
                FROM inventory_transactions
                WHERE reference_type = 'shipment_dispatch'
                  AND reference_id = :sid
                  AND product_id = :pid
                  AND warehouse_id = :wid
            """), {"sid": id, "pid": item.product_id, "wid": shipment.source_warehouse_id}).fetchone()

            source_cost = Decimal(str(dispatch_cost_row.unit_cost or 0)) if dispatch_cost_row else Decimal("0")
            item_value = Decimal(str(dispatch_cost_row.total_cost or 0)) if dispatch_cost_row else Decimal("0")

            # Restore source: decrease in_transit, increase quantity
            db.execute(text("""
                UPDATE inventory
                SET quantity = quantity + :qty,
                    in_transit_quantity = in_transit_quantity - :qty,
                    updated_at = NOW()
                WHERE product_id = :pid AND warehouse_id = :wh
            """), {"qty": item.quantity, "pid": item.product_id, "wh": shipment.source_warehouse_id})

            # Restore cost layers if FIFO/LIFO
            method = CostingService._get_product_costing_method(db, item.product_id, shipment.source_warehouse_id)
            if method in ("fifo", "lifo"):
                return_result = CostingService.handle_return(
                    db,
                    product_id=item.product_id,
                    warehouse_id=shipment.source_warehouse_id,
                    quantity=item_qty,
                    unit_cost=source_cost,
                    source_document_type="shipment_recall",
                    source_document_id=id,
                    costing_method=method,
                    original_source_document_type="shipment_dispatch",
                    original_source_document_id=id,
                )
                source_cost = Decimal(str(return_result.get("restored_unit_cost", source_cost)))
                item_value = Decimal(str(return_result.get("restored_total_cost", item_value)))

            total_recall_value += item_value

            # Log recall transaction
            db.execute(text("""
                INSERT INTO inventory_transactions (product_id, warehouse_id, transaction_type,
                                                   reference_type, reference_id, quantity, notes, created_by, unit_cost, total_cost)
                VALUES (:pid, :wh, 'shipment_recall', 'shipment_recall', :sid, :qty, :notes, :user, :uc, :tc)
            """), {
                "pid": item.product_id,
                "wh": shipment.source_warehouse_id,
                "sid": id,
                "qty": item.quantity,
                "notes": f"Shipment Recall {shipment.shipment_ref} — returned to source",
                "user": user_id,
                "uc": str(source_cost),
                "tc": str(item_value),
            })

        # Post GL reversal: Dr Source Inventory / Cr In-Transit
        if total_recall_value > Decimal("0"):
            value_f = total_recall_value  # Decimal
            create_journal_entry(
                db=db,
                company_id=str(company_id),
                date=today_str,
                description=f"Shipment {shipment.shipment_ref}: recall from in-transit",
                lines=[
                    {"account_id": inv_acc, "debit": value_f, "credit": 0},
                    {"account_id": intransit_acc, "debit": 0, "credit": value_f},
                ],
                user_id=user_id,
                reference=shipment.shipment_ref,
                source="shipment_recall",
                source_id=id,
                username=username,
                idempotency_key=f"shipment_recall:{id}",
            )

        # Update shipment status
        db.execute(text("""
            UPDATE stock_shipments SET status = 'recalled', updated_at = NOW() WHERE id = :id
        """), {"id": id})

        db.commit()

        # Audit log
        try:
            log_activity(
                db, user_id=user_id, username=username,
                action="shipment.recall", resource_type="stock_shipment",
                resource_id=str(id), details={"shipment_ref": shipment.shipment_ref, "items_count": len(items)},
                request=request,
            )
        except Exception:
            pass

        return {"message": "تم استرداد الشحنة بنجاح وإعادة المخزون إلى المصدر", "status": "recalled"}

    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
