"""Sales orders endpoints."""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.audit import log_activity
from utils.permissions import branch_scope_filter_from_scope, require_permission, resolve_branch_scope, validate_branch_access
from .schemas import SOCreate
from services.tax_engine import resolve_line_tax

orders_router = APIRouter()
logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')


def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')


@orders_router.get("/orders", response_model=List[dict], dependencies=[Depends(require_permission("sales.view"))])
def list_sales_orders(branch_id: Optional[int] = None, current_user: dict = Depends(get_current_user)):
    """عرض قائمة أوامر البيع"""
    branch_scope = resolve_branch_scope(current_user, branch_id)

    db = get_db_connection(current_user.company_id)
    try:
        query_str = """
            SELECT so.*, p.name as customer_name 
            FROM sales_orders so
            JOIN parties p ON so.party_id = p.id
            WHERE 1=1
        """
        params = {}
        query_str += branch_scope_filter_from_scope(branch_scope, "so.branch_id", params)

        query_str += " ORDER BY so.created_at DESC"

        result = db.execute(text(query_str), params).fetchall()
        return [dict(row._mapping) for row in result]
    finally:
        db.close()


@orders_router.get("/orders/{order_id}", response_model=dict, dependencies=[Depends(require_permission("sales.view"))])
def get_sales_order(order_id: int, current_user: dict = Depends(get_current_user)):
    """جلب تفاصيل أمر البيع"""
    db = get_db_connection(current_user.company_id)
    try:
        # Header
        query = """
            SELECT so.*, so.party_id as customer_id, p.name as customer_name, p.party_code as customer_code
            FROM sales_orders so
            JOIN parties p ON so.party_id = p.id
            WHERE so.id = :id
        """
        header_row = db.execute(text(query), {"id": order_id}).fetchone()
        if not header_row:
            raise HTTPException(**http_error(404, "sales_order_not_found"))

        # Enforce branch access for single resource
        from utils.permissions import validate_branch_access
        if header_row.branch_id:
            validate_branch_access(current_user, header_row.branch_id)

        # Lines
        lines_query = """
            SELECT sol.*, p.product_name, u.unit_name as unit
            FROM sales_order_lines sol
            LEFT JOIN products p ON sol.product_id = p.id
            LEFT JOIN product_units u ON p.unit_id = u.id
            WHERE sol.so_id = :id
        """
        lines_result = db.execute(text(lines_query), {"id": order_id}).fetchall()

        return {
            **dict(header_row._mapping),
            "items": [dict(r._mapping) for r in lines_result]
        }
    finally:
        db.close()


@orders_router.post("/orders", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def create_sales_order(request: Request, data: SOCreate, current_user: dict = Depends(get_current_user)):
    """إنشاء أمر بيع جديد"""
    db = get_db_connection(current_user.company_id)
    try:
        # 0. Validate quotation if provided
        if data.quotation_id:
            quot = db.execute(text("""
                SELECT id, party_id, status
                FROM sales_quotations
                WHERE id = :qid
            """), {"qid": data.quotation_id}).fetchone()
            if not quot:
                raise HTTPException(**http_error(404, ("quotation_not_found", request)))
            if quot.status in ('expired', 'converted', 'cancelled'):
                raise HTTPException(status_code=400, detail=i18n_message("quotation_cannot_convert_status", request))
            if quot.party_id and quot.party_id != data.customer_id:
                raise HTTPException(**http_error(400, "customer_mismatch_quotation", request))

        # 1. Generate Sequential SO Number
        from utils.accounting import generate_sequential_number
        so_num = generate_sequential_number(db, f"SO-{datetime.now().year}", "sales_orders", "so_number")

        # 2. Calculate Totals (tax resolved via engine)
        validated_branch_id = validate_branch_access(current_user, data.branch_id)
        if validated_branch_id is None:
            raise HTTPException(**http_error(400, ("branch_required", request)))
        from utils.accounting import compute_invoice_totals, compute_line_amounts
        items_to_save = []

        for item in data.items:
            tax_info = resolve_line_tax(validated_branch_id, item.product_id, db, data.order_date, customer_id=data.customer_id)
            line_amounts = compute_line_amounts(
                item.quantity,
                item.unit_price,
                tax_info["tax_rate"],
                item.discount,
                discount_is_percent=False,
            )

            items_to_save.append({
                **item.model_dump(),
                "tax_rate": tax_info["tax_rate"],
                "tax_rate_id": tax_info["tax_rate_id"],
                "total": line_amounts["line_total"],
            })

        totals = compute_invoice_totals(
            [
                {
                    "quantity": item["quantity"],
                    "unit_price": item["unit_price"],
                    "tax_rate": item["tax_rate"],
                    "discount": item["discount"],
                }
                for item in items_to_save
            ],
            discount_is_percent=False,
        )
        subtotal = totals["subtotal"]
        total_tax = totals["total_tax"]
        total_discount = totals["total_discount"]
        grand_total = totals["grand_total"]

        # 3. Save Header
        res = db.execute(text("""
            INSERT INTO sales_orders (
                so_number, party_id, order_date, expected_delivery_date,
                subtotal, tax_amount, discount, total, status, notes, created_by, branch_id,
                warehouse_id, quotation_id,
                currency, exchange_rate, party_site_id
            ) VALUES (
                :num, :cust, :odate, :edate,
                :sub, :tax, :disc, :total, 'draft', :notes, :user, :bid,
                :whid, :qid,
                :currency, :exchange_rate, :party_site_id
            ) RETURNING id
        """), {
            "num": so_num, "cust": data.customer_id, "odate": data.order_date,
            "edate": data.expected_delivery_date, "sub": subtotal, "tax": total_tax,
            "disc": total_discount, "total": grand_total, "notes": data.notes, "user": current_user.id,
            "bid": validated_branch_id, "whid": data.warehouse_id, "qid": data.quotation_id,
            "currency": data.currency, "exchange_rate": data.exchange_rate,
            "party_site_id": data.party_site_id,
        }).fetchone()

        so_id = res[0]

        # 4. Save Lines
        for line in items_to_save:
            db.execute(text("""
                INSERT INTO sales_order_lines (
                    so_id, product_id, description, quantity, unit_price, tax_rate, tax_rate_id, discount, total
                ) VALUES (
                    :so_id, :pid, :desc, :qty, :price, :tax_rate, :tax_rate_id, :disc, :total
                )
            """), {
                "so_id": so_id, "pid": line["product_id"], "desc": line["description"],
                "qty": line["quantity"], "price": line["unit_price"],
                "tax_rate": line["tax_rate"], "tax_rate_id": line.get("tax_rate_id"),
                "disc": line["discount"], "total": line["total"]
            })

            # 5. Inventory Reservation
            if data.warehouse_id:
                # Check/Create inventory record
                inv = db.execute(text("""
                    SELECT id, quantity, reserved_quantity FROM inventory 
                    WHERE product_id = :pid AND warehouse_id = :wid
                """), {"pid": line["product_id"], "wid": data.warehouse_id}).fetchone()

                if not inv:
                    # Create new inventory record if not exists
                    inv_id = db.execute(text("""
                        INSERT INTO inventory (product_id, warehouse_id, quantity, reserved_quantity, available_quantity)
                        VALUES (:pid, :wid, 0, 0, 0) RETURNING id
                    """), {"pid": line["product_id"], "wid": data.warehouse_id}).scalar()
                    current_qty = Decimal('0')
                    current_reserved = Decimal('0')
                else:
                    inv_id = inv.id
                    current_qty = _dec(inv.quantity)
                    current_reserved = _dec(inv.reserved_quantity)

                new_reserved = current_reserved + _dec(line["quantity"])
                new_available = current_qty - new_reserved

                db.execute(text("""
                    UPDATE inventory 
                    SET reserved_quantity = :reserved, available_quantity = :available, last_costing_update = NOW()
                    WHERE id = :id
                """), {"reserved": new_reserved, "available": new_available, "id": inv_id})

                # Log Transaction
                db.execute(text("""
                    INSERT INTO inventory_transactions (
                        product_id, warehouse_id, transaction_type, reference_type, 
                        reference_id, reference_document, quantity, notes, created_by
                    ) VALUES (
                        :pid, :wid, 'reservation', 'sales_order', 
                        :ref_id, :ref_doc, :qty, :notes, :user
                    )
                """), {
                    "pid": line["product_id"],
                    "wid": data.warehouse_id,
                    "ref_id": so_id,
                    "ref_doc": so_num,
                    "qty": _dec(line["quantity"]),
                    "notes": "Reservation for Sales Order",
                    "user": current_user.id
                })

        # Update quotation status to 'converted' if applicable
        if data.quotation_id:
            db.execute(text("""
                UPDATE sales_quotations
                SET status = 'converted', updated_at = NOW(), updated_by = :user
                WHERE id = :qid
            """), {"qid": data.quotation_id, "user": current_user.username})

        db.commit()

        cust_name = db.execute(text("SELECT name FROM parties WHERE id = :id"), {"id": data.customer_id}).scalar()
        # AUDIT LOG
        log_activity(
            db,
            user_id=current_user.id,
            username=current_user.username,
            action="sales.order.create",
            resource_type="sales_order",
            resource_id=str(so_id),
            details={"so_number": so_num, "total": str(grand_total or 0), "customer_id": data.customer_id, "customer_name": cust_name},
            request=request,
            branch_id=data.branch_id
        )
        return {"id": so_id, "so_number": so_num}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating Sales Order: {str(e)}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
