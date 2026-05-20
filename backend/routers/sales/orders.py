"""Sales orders endpoints."""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from utils.i18n import http_error, i18n_message
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.audit import log_activity
from utils.permissions import branch_scope_filter_from_scope, require_permission, resolve_branch_scope, validate_branch_access
from .schemas import SOCreate, SalesDocumentPreviewRequest
from services.tax_engine import resolve_line_tax
from services.sales.preview import preview_sales_totals

orders_router = APIRouter()
logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_COLUMN_CACHE: dict[str, set[str]] = {}


def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')


def _table_columns(db, table_name: str) -> set[str]:
    cached = _COLUMN_CACHE.get(table_name)
    if cached is not None:
        return cached
    cols = {
        row.column_name
        for row in db.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"),
            {"t": table_name},
        ).fetchall()
    }
    _COLUMN_CACHE[table_name] = cols
    return cols


def _company_id(user) -> str:
    return user.get("company_id") if isinstance(user, dict) else user.company_id


def _user_id(user) -> int:
    return user.get("id") if isinstance(user, dict) else user.id


def _username(user) -> str:
    return user.get("username") if isinstance(user, dict) else user.username


@orders_router.get("/orders", response_model=List[dict], dependencies=[Depends(require_permission("sales.view"))])
def list_sales_orders(branch_id: Optional[int] = None, current_user: dict = Depends(get_current_user)):
    """عرض قائمة أوامر البيع"""
    branch_scope = resolve_branch_scope(current_user, branch_id)

    db = get_db_connection(_company_id(current_user))
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


@orders_router.post("/orders/preview", response_model=Dict[str, Any], dependencies=[Depends(require_permission("sales.view"))])
def preview_sales_order(data: SalesDocumentPreviewRequest, current_user: dict = Depends(get_current_user)):
    """Preview sales-order totals without reserving inventory or writing state."""
    branch_id = validate_branch_access(current_user, data.branch_id) if data.branch_id else None
    db = get_db_connection(_company_id(current_user))
    try:
        return preview_sales_totals(
            db,
            lines=data.lines,
            branch_id=branch_id,
            party_id=data.customer_id or data.party_id,
            document_date=data.document_date,
            currency=data.currency,
            paid_amount=data.paid_amount,
            header_discount_pct=data.header_discount_pct,
            markup_amount=data.markup_amount,
        )
    finally:
        db.close()


@orders_router.post("/orders/{order_id}/cancel", dependencies=[Depends(require_permission("sales.void"))], response_model=Dict[str, Any])
def cancel_sales_order(request: Request, order_id: int, current_user: dict = Depends(get_current_user)):
    """إلغاء أمر بيع draft وتحرير حجوزات المخزون المرتبطة به."""
    db = get_db_connection(_company_id(current_user))
    user_id = _user_id(current_user)
    username = _username(current_user)
    try:
        order = db.execute(text("""
            SELECT *
            FROM sales_orders
            WHERE id = :id
            FOR UPDATE
        """), {"id": order_id}).fetchone()
        if not order:
            raise HTTPException(**http_error(404, "sales_order_not_found", request))

        if order.branch_id:
            validate_branch_access(current_user, order.branch_id)

        if order.status == "cancelled":
            raise HTTPException(**http_error(400, "sales_order_already_cancelled", request))
        if order.status not in ("draft", "pending", "approved"):
            raise HTTPException(status_code=400, detail=i18n_message("sales_order_cannot_cancel_status", request))

        lines = db.execute(text("""
            SELECT product_id, quantity
            FROM sales_order_lines
            WHERE so_id = :id
        """), {"id": order_id}).fetchall()

        if order.warehouse_id:
            for line in lines:
                qty = _dec(line.quantity)
                if qty <= 0:
                    continue
                db.execute(text("""
                    UPDATE inventory
                    SET reserved_quantity = GREATEST(0, COALESCE(reserved_quantity, 0) - :qty),
                        updated_at = NOW()
                    WHERE product_id = :pid AND warehouse_id = :wid
                """), {
                    "pid": line.product_id,
                    "wid": order.warehouse_id,
                    "qty": qty,
                })
                db.execute(text("""
                    INSERT INTO inventory_transactions (
                        product_id, warehouse_id, transaction_type, reference_type,
                        reference_id, reference_document, quantity, notes, created_by
                    ) VALUES (
                        :pid, :wid, 'reservation_release', 'sales_order_cancel',
                        :ref_id, :ref_doc, :qty, :notes, :user
                    )
                """), {
                    "pid": line.product_id,
                    "wid": order.warehouse_id,
                    "ref_id": order_id,
                    "ref_doc": order.so_number,
                    "qty": -qty,
                    "notes": "Release reservation for cancelled Sales Order",
                    "user": user_id,
                })

        db.execute(text("""
            UPDATE sales_orders
            SET status = 'cancelled', updated_at = NOW()
            WHERE id = :id
        """), {"id": order_id})

        db.commit()
        log_activity(
            db,
            user_id=user_id,
            username=username,
            action="sales.order.cancel",
            resource_type="sales_order",
            resource_id=str(order_id),
            details={"so_number": order.so_number, "total": str(order.total or 0)},
            request=request,
            branch_id=order.branch_id,
        )
        return {"success": True, "message": i18n_message("sales_order_cancelled", request)}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error cancelling Sales Order: {str(e)}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@orders_router.get("/orders/{order_id}", response_model=dict, dependencies=[Depends(require_permission("sales.view"))])
def get_sales_order(order_id: int, current_user: dict = Depends(get_current_user)):
    """جلب تفاصيل أمر البيع"""
    db = get_db_connection(_company_id(current_user))
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
    company_id = _company_id(current_user)
    user_id = _user_id(current_user)
    username = _username(current_user)
    db = get_db_connection(company_id)
    try:
        # 0. Validate quotation if provided
        if data.quotation_id:
            quot = db.execute(text("""
                SELECT id, party_id, status
                FROM sales_quotations
                WHERE id = :qid
            """), {"qid": data.quotation_id}).fetchone()
            if not quot:
                raise HTTPException(**http_error(404, "quotation_not_found", request))
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
            raise HTTPException(**http_error(400, "branch_required", request))
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
        cols = [
            "so_number", "party_id", "order_date", "expected_delivery_date",
            "subtotal", "tax_amount", "discount", "total", "status", "notes",
            "created_by", "branch_id", "warehouse_id", "quotation_id",
            "currency", "exchange_rate",
        ]
        vals = [
            ":num", ":cust", ":odate", ":edate",
            ":sub", ":tax", ":disc", ":total", "'draft'", ":notes",
            ":user", ":bid", ":whid", ":qid",
            ":currency", ":exchange_rate",
        ]
        order_cols = _table_columns(db, "sales_orders")
        if data.party_site_id and "party_site_id" in order_cols:
            cols.append("party_site_id")
            vals.append(":party_site_id")
        res = db.execute(text(f"""
            INSERT INTO sales_orders ({', '.join(cols)})
            VALUES ({', '.join(vals)})
            RETURNING id
        """), {
            "num": so_num, "cust": data.customer_id, "odate": data.order_date,
            "edate": data.expected_delivery_date, "sub": subtotal, "tax": total_tax,
            "disc": total_discount, "total": grand_total, "notes": data.notes, "user": user_id,
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
                inv = db.execute(text("""
                    UPDATE inventory
                    SET reserved_quantity = COALESCE(reserved_quantity, 0) + :qty,
                        last_costing_update = NOW(),
                        updated_at = NOW()
                    WHERE product_id = :pid
                      AND warehouse_id = :wid
                      AND quantity - COALESCE(reserved_quantity, 0) >= :qty
                    RETURNING id
                """), {
                    "pid": line["product_id"],
                    "wid": data.warehouse_id,
                    "qty": line["quantity"],
                }).fetchone()

                if not inv:
                    exists = db.execute(text("""
                        SELECT 1 FROM inventory
                        WHERE product_id = :pid AND warehouse_id = :wid
                    """), {"pid": line["product_id"], "wid": data.warehouse_id}).scalar()
                    if not exists:
                        raise HTTPException(**http_error(400, "no_inventory_record_product", request))
                    raise HTTPException(**http_error(400, "insufficient_stock_product", request))

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
                    "user": user_id
                })

        # Update quotation status to 'converted' if applicable
        if data.quotation_id:
            db.execute(text("""
                UPDATE sales_quotations
                SET status = 'converted', updated_at = NOW(), updated_by = :user
                WHERE id = :qid
            """), {"qid": data.quotation_id, "user": username})

        db.commit()

        cust_name = db.execute(text("SELECT name FROM parties WHERE id = :id"), {"id": data.customer_id}).scalar()
        # AUDIT LOG
        log_activity(
            db,
            user_id=user_id,
            username=username,
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
