"""
AMAN ERP — Delivery Orders Router
أوامر التسليم: مستند وسيط بين أمر البيع والفاتورة
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error, i18n_message
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
from pydantic import BaseModel
import logging

from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import branch_scope_filter_from_scope, require_permission, require_sensitive_permission, resolve_branch_scope, validate_branch_access
from utils.audit import log_activity
from utils.accounting import (
    generate_sequential_number, get_mapped_account_id,
    get_base_currency
)
from utils.fiscal_lock import check_fiscal_period_open
from utils.party_balance import update_party_site_balance
from services.gl_service import create_journal_entry  # TASK-015: centralized GL posting
from services.tax_engine import resolve_line_tax

router = APIRouter(prefix="/sales/delivery-orders", tags=["Delivery Orders"])
logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')
def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')


# ─── Schemas ───────────────────────────────────────────────────────────────────

class DeliveryLineCreate(BaseModel):
    product_id: int
    so_line_id: Optional[int] = None
    description: Optional[str] = None
    ordered_qty: Decimal = Decimal('0')
    delivered_qty: Decimal = Decimal('0')
    unit: Optional[str] = None
    batch_number: Optional[str] = None
    serial_numbers: Optional[str] = None
    notes: Optional[str] = None

class DeliveryOrderCreate(BaseModel):
    delivery_date: Optional[str] = None
    sales_order_id: Optional[int] = None
    party_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    branch_id: Optional[int] = None
    shipping_method: Optional[str] = None
    tracking_number: Optional[str] = None
    driver_name: Optional[str] = None
    driver_phone: Optional[str] = None
    vehicle_number: Optional[str] = None
    delivery_address: Optional[str] = None
    notes: Optional[str] = None
    lines: List[DeliveryLineCreate] = []

class DeliveryOrderUpdate(BaseModel):
    shipping_method: Optional[str] = None
    tracking_number: Optional[str] = None
    driver_name: Optional[str] = None
    driver_phone: Optional[str] = None
    vehicle_number: Optional[str] = None
    delivery_address: Optional[str] = None
    notes: Optional[str] = None


# ─── LIST ──────────────────────────────────────────────────────────────────────

@router.get("", dependencies=[Depends(require_permission("sales.view"))], response_model=List[dict])
def list_delivery_orders(
    status_filter: Optional[str] = None,
    party_id: Optional[int] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """قائمة أوامر التسليم"""
    company_id = current_user.get("company_id")
    branch_scope = resolve_branch_scope(current_user, branch_id)
    with transactional(company_id) as db:
        query = """
            SELECT do.*, p.name as party_name, w.warehouse_name,
                   so.order_number as so_number, b.branch_name,
                   cu.full_name as created_by_name
            FROM delivery_orders do
            LEFT JOIN parties p ON p.id = do.party_id
            LEFT JOIN warehouses w ON w.id = do.warehouse_id
            LEFT JOIN sales_orders so ON so.id = do.sales_order_id
            LEFT JOIN branches b ON b.id = do.branch_id
            LEFT JOIN company_users cu ON cu.id = do.created_by
            WHERE 1=1
        """
        params = {}

        if status_filter:
            query += " AND do.status = :status"
            params["status"] = status_filter
        if party_id:
            query += " AND do.party_id = :pid"
            params["pid"] = party_id
        if from_date:
            query += " AND do.delivery_date >= :fd"
            params["fd"] = from_date
        if to_date:
            query += " AND do.delivery_date <= :td"
            params["td"] = to_date

        query += branch_scope_filter_from_scope(branch_scope, "do.branch_id", params)

        query += " ORDER BY do.id DESC"

        rows = db.execute(text(query), params).fetchall()
        return [dict(row._mapping) for row in rows]


# ─── GET ONE ───────────────────────────────────────────────────────────────────

@router.get("/{do_id}", dependencies=[Depends(require_permission("sales.view"))], response_model=dict)
def get_delivery_order(do_id: int, current_user: dict = Depends(get_current_user)):
    """تفاصيل أمر التسليم"""
    company_id = current_user.get("company_id")
    with transactional(company_id) as db:
        order = db.execute(text("""
            SELECT do.*, p.name as party_name, p.phone, p.address,
                   w.warehouse_name, so.order_number as so_number,
                   b.branch_name, cu.full_name as created_by_name
            FROM delivery_orders do
            LEFT JOIN parties p ON p.id = do.party_id
            LEFT JOIN warehouses w ON w.id = do.warehouse_id
            LEFT JOIN sales_orders so ON so.id = do.sales_order_id
            LEFT JOIN branches b ON b.id = do.branch_id
            LEFT JOIN company_users cu ON cu.id = do.created_by
            WHERE do.id = :id
        """), {"id": do_id}).fetchone()

        if not order:
            raise HTTPException(**http_error(404, "delivery_order_not_found"))

        lines = db.execute(text("""
            SELECT dol.*, pr.product_name, pr.product_name_en, pr.sku
            FROM delivery_order_lines dol
            LEFT JOIN products pr ON pr.id = dol.product_id
            WHERE dol.delivery_order_id = :doid
            ORDER BY dol.id
        """), {"doid": do_id}).fetchall()

        result = dict(order._mapping)
        result["lines"] = [dict(line._mapping) for line in lines]
        return result


# ─── CREATE ────────────────────────────────────────────────────────────────────

@router.post("", status_code=201, dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def create_delivery_order(body: DeliveryOrderCreate, request: Request, current_user: dict = Depends(get_current_user)):
    """إنشاء أمر تسليم — يمكن ربطه بأمر بيع"""
    company_id = current_user.get("company_id")
    user_id = current_user.get("user_id")
    with transactional(company_id) as db:
        try:
            year = datetime.now().year
            delivery_number = generate_sequential_number(db, f"DO-{year}", "delivery_orders", "delivery_number")
    
            # If from sales order, populate lines automatically
            lines = body.lines
            so_id = body.sales_order_id
            party_id = body.party_id
            warehouse_id = body.warehouse_id
            branch_id = body.branch_id
    
            if so_id and not lines:
                so = db.execute(text("SELECT * FROM sales_orders WHERE id = :id"), {"id": so_id}).fetchone()
                if not so:
                    raise HTTPException(**http_error(404, "sales_order_not_found"))
                if so.branch_id:
                    branch_id = validate_branch_access(current_user, so.branch_id, request)
                party_id = party_id or so.party_id
                warehouse_id = warehouse_id or so.warehouse_id
    
                so_lines = db.execute(text("""
                    SELECT sol.*, p.product_name, p.sku
                    FROM sales_order_lines sol
                    LEFT JOIN products p ON p.id = sol.product_id
                    WHERE sol.so_id = :soid
                """), {"soid": so_id}).fetchall()
    
                lines = []
                for sl in so_lines:
                    already_delivered = db.execute(text("""
                        SELECT COALESCE(SUM(dol.delivered_qty), 0)
                        FROM delivery_order_lines dol
                        JOIN delivery_orders do2 ON do2.id = dol.delivery_order_id
                        WHERE dol.so_line_id = :slid AND do2.status != 'cancelled'
                    """), {"slid": sl.id}).scalar() or 0
    
                    remaining = _dec(sl.quantity) - _dec(already_delivered)
                    if remaining > 0:
                        lines.append(DeliveryLineCreate(
                            product_id=sl.product_id,
                            so_line_id=sl.id,
                            description=getattr(sl, 'description', ''),
                            ordered_qty=remaining,
                            delivered_qty=remaining,
                            unit=getattr(sl, 'unit', None)
                        ))

            branch_id = validate_branch_access(current_user, branch_id, request)
    
            validated_lines = []
            for line in lines:
                if line.so_line_id:
                    so_line = db.execute(text("""
                        SELECT id, so_id, product_id, quantity
                        FROM sales_order_lines
                        WHERE id = :id
                    """), {"id": line.so_line_id}).fetchone()
                    if not so_line:
                        raise HTTPException(**http_error(404, "sales_order_line_not_found", request))
                    if so_id and int(so_line.so_id) != int(so_id):
                        raise HTTPException(**http_error(400, "sales_order_line_mismatch", request))
                    if int(so_line.product_id) != int(line.product_id):
                        raise HTTPException(**http_error(400, "sales_order_line_mismatch", request))

                    already_delivered = db.execute(text("""
                        SELECT COALESCE(SUM(dol.delivered_qty), 0)
                        FROM delivery_order_lines dol
                        JOIN delivery_orders do2 ON do2.id = dol.delivery_order_id
                        WHERE dol.so_line_id = :slid AND do2.status != 'cancelled'
                    """), {"slid": line.so_line_id}).scalar() or 0
                    remaining = (_dec(so_line.quantity) - _dec(already_delivered)).quantize(_D4, ROUND_HALF_UP)
                    if _dec(line.delivered_qty) <= 0 or _dec(line.delivered_qty) > remaining:
                        raise HTTPException(**http_error(400, "delivery_quantity_exceeds_remaining", request))
                    line.ordered_qty = remaining
                validated_lines.append(line)

            lines = validated_lines
            total_items = len(lines)
            total_qty = sum(line.delivered_qty for line in lines)
    
            result = db.execute(text("""
                INSERT INTO delivery_orders (
                    delivery_number, delivery_date, sales_order_id, party_id,
                    warehouse_id, branch_id, shipping_method, tracking_number,
                    driver_name, driver_phone, vehicle_number, delivery_address,
                    notes, total_items, total_quantity, created_by, status
                ) VALUES (
                    :dn, :dd, :soid, :pid, :wid, :bid, :sm, :tn,
                    :drn, :drp, :vn, :da, :notes, :ti, :tq, :uid, 'draft'
                ) RETURNING id
            """), {
                "dn": delivery_number,
                "dd": body.delivery_date or date.today().isoformat(),
                "soid": so_id, "pid": party_id, "wid": warehouse_id,
                "bid": branch_id, "sm": body.shipping_method,
                "tn": body.tracking_number, "drn": body.driver_name,
                "drp": body.driver_phone, "vn": body.vehicle_number,
                "da": body.delivery_address, "notes": body.notes,
                "ti": total_items, "tq": total_qty, "uid": user_id
            })
            do_id = result.fetchone()[0]
    
            for line in lines:
                db.execute(text("""
                    INSERT INTO delivery_order_lines (
                        delivery_order_id, product_id, so_line_id, description,
                        ordered_qty, delivered_qty, unit, batch_number, serial_numbers, notes
                    ) VALUES (:doid, :pid, :slid, :desc, :oq, :dq, :unit, :bn, :sn, :notes)
                """), {
                    "doid": do_id, "pid": line.product_id, "slid": line.so_line_id,
                    "desc": line.description, "oq": line.ordered_qty,
                    "dq": line.delivered_qty, "unit": line.unit,
                    "bn": line.batch_number, "sn": line.serial_numbers,
                    "notes": line.notes
                })
    
    
            log_activity(db, user_id, "delivery_order.create", f"أمر تسليم {delivery_number}", {"id": do_id})
    
            return {"id": do_id, "delivery_number": delivery_number, "status": "draft"}
        except HTTPException:
            raise
        except Exception as e:
            pass
            logger.error(f"Error creating delivery order: {e}")
            raise HTTPException(**http_error(500, "delivery_order_create_error", request))


# ─── CONFIRM (ship) ───────────────────────────────────────────────────────────

@router.post("/{do_id}/confirm", dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def confirm_delivery_order(do_id: int, request: Request, current_user: dict = Depends(get_current_user)):
    """
    تأكيد أمر التسليم — خصم المخزون من المستودع
    يُنشئ حركات مخزون ولكن ليس قيداً (القيد عند الفاتورة)
    """
    company_id = current_user.get("company_id")
    user_id = current_user.get("user_id")
    with transactional(company_id) as db:
        try:
            # AUDIT-H2: lock the DO header row to serialise concurrent
            # confirm/create-invoice/cancel attempts. Without FOR UPDATE
            # two parallel calls could each pass the status check and
            # double-deduct stock.
            order = db.execute(text(
                "SELECT * FROM delivery_orders WHERE id = :id FOR UPDATE"
            ), {"id": do_id}).fetchone()
            if not order:
                raise HTTPException(**http_error(404, "delivery_order_not_found"))
            if order.status != 'draft':
                raise HTTPException(**http_error(400, "delivery_order_confirm_invalid_status", request))
    
            lines = db.execute(text(
                "SELECT * FROM delivery_order_lines WHERE delivery_order_id = :doid"
            ), {"doid": do_id}).fetchall()
    
            warehouse_id = order.warehouse_id
    
            for line in lines:
                delivered_qty = _dec(line.delivered_qty)
                if not line.product_id or delivered_qty <= 0:
                    continue
    
                from services.costing_service import CostingService

                # Check stock and lock row
                stock = db.execute(text("""
                    SELECT quantity, reserved_quantity, average_cost FROM inventory
                    WHERE product_id = :pid AND warehouse_id = :wid
                    FOR UPDATE
                """), {"pid": line.product_id, "wid": warehouse_id}).fetchone()
    
                available = (_dec(stock.quantity) - _dec(stock.reserved_quantity)) if stock else Decimal('0')
                if available < delivered_qty:
                    db.execute(text("SELECT product_name FROM products WHERE id = :id"), {"id": line.product_id}).fetchone()
                    raise HTTPException(**http_error(400, "delivery_order_insufficient_stock", request))

                costing_method = CostingService._get_product_costing_method(db, line.product_id, warehouse_id)
                if costing_method in ("fifo", "lifo"):
                    try:
                        cogs = CostingService.consume_layers(
                            db,
                            product_id=line.product_id,
                            warehouse_id=warehouse_id,
                            quantity=delivered_qty,
                            sale_document_type="delivery_order",
                            sale_document_id=do_id,
                            costing_method=costing_method,
                        )
                    except ValueError:
                        raise HTTPException(**http_error(400, "invalid_request", request))
                    unit_cost = (_dec(cogs) / delivered_qty).quantize(_D4, ROUND_HALF_UP) if delivered_qty else Decimal("0")
                    total_cost = _dec(cogs).quantize(_D2, ROUND_HALF_UP)
                else:
                    unit_cost = _dec(stock.average_cost if stock else 0)
                    if unit_cost <= 0:
                        unit_cost = _dec(db.execute(text("SELECT cost_price FROM products WHERE id = :id"), {"id": line.product_id}).scalar() or 0)
                    total_cost = (unit_cost * delivered_qty).quantize(_D2, ROUND_HALF_UP)

                # Deduct inventory
                deducted = db.execute(text("""
                    UPDATE inventory SET quantity = quantity - :qty, updated_at = CURRENT_TIMESTAMP
                    WHERE product_id = :pid AND warehouse_id = :wid
                      AND quantity - COALESCE(reserved_quantity, 0) >= :qty
                    RETURNING id
                """), {"qty": delivered_qty, "pid": line.product_id, "wid": warehouse_id}).fetchone()
                if not deducted:
                    raise HTTPException(**http_error(400, "delivery_order_qty_changed", request))
    
                # Record inventory transaction
                db.execute(text("""
                    INSERT INTO inventory_transactions (
                        product_id, warehouse_id, transaction_type, quantity,
                        reference_type, reference_id, notes, created_by,
                        unit_cost, total_cost
                    ) VALUES (
                        :pid, :wid, 'delivery', :qty, 'delivery_order', :doid,
                        :notes, :uid, :uc, :tc
                    )
                """), {
                    "pid": line.product_id, "wid": warehouse_id,
                    "qty": -delivered_qty, "doid": do_id,
                    "notes": f"تسليم بموجب {order.delivery_number}", "uid": user_id,
                    "uc": Decimal(str(unit_cost)), "tc": Decimal(str(total_cost))
                })
    
            # Update status
            db.execute(text("""
                UPDATE delivery_orders SET status = 'confirmed', shipped_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """), {"id": do_id})
    
    
            log_activity(db, user_id, "delivery_order.confirm", f"تأكيد تسليم {order.delivery_number}", {"id": do_id})
    
            return {"message": i18n_message("delivery_order_confirmed", request), "status": "confirmed"}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ─── MARK DELIVERED ────────────────────────────────────────────────────────────

@router.post("/{do_id}/deliver", dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def mark_delivered(do_id: int, request: Request, current_user: dict = Depends(get_current_user)):
    """تسجيل وصول الشحنة / تسليم العميل"""
    company_id = current_user.get("company_id")
    with transactional(company_id) as db:
        # AUDIT-H2: lock the DO row before transitioning to 'delivered'
        # to keep concurrent deliver/cancel calls serialised.
        order = db.execute(text(
            "SELECT * FROM delivery_orders WHERE id = :id FOR UPDATE"
        ), {"id": do_id}).fetchone()
        if not order:
            raise HTTPException(**http_error(404, "delivery_order_not_found"))
        if order.status not in ('confirmed', 'shipped'):
            raise HTTPException(**http_error(400, "delivery_status_invalid", request))

        db.execute(text("""
            UPDATE delivery_orders SET status = 'delivered', delivered_at = CURRENT_TIMESTAMP
            WHERE id = :id
        """), {"id": do_id})

        return {"message": i18n_message("delivery_completed_success", request), "status": "delivered"}


# ─── CREATE INVOICE FROM DO ───────────────────────────────────────────────────

from fastapi import Header  # noqa: E402

@router.post("/{do_id}/create-invoice", dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def create_invoice_from_delivery(
    do_id: int, 
    request: Request, 
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key", max_length=64),
    current_user: dict = Depends(get_current_user)
):
    """إنشاء فاتورة مبيعات من أمر التسليم"""
    company_id = current_user.get("company_id")
    user_id = current_user.get("user_id")
    with transactional(company_id) as db:
        try:
            if idempotency_key:
                existing = db.execute(text("""
                    SELECT id, invoice_number, journal_entry_id FROM invoices
                    WHERE idempotency_key = :key
                """), {"key": idempotency_key}).fetchone()
                if existing:
                    return {
                        "message": i18n_message("delivery_invoice_created", request),
                        "invoice_id": existing.id,
                        "invoice_number": existing.invoice_number,
                        "journal_entry_id": existing.journal_entry_id,
                        "idempotent_replay": True
                    }

            # AUDIT-H2: lock DO row to prevent concurrent invoice creation.
            order = db.execute(text(
                "SELECT * FROM delivery_orders WHERE id = :id FOR UPDATE"
            ), {"id": do_id}).fetchone()
            if not order:
                raise HTTPException(**http_error(404, "delivery_order_not_found"))
            if order.status not in ('confirmed', 'delivered'):
                raise HTTPException(**http_error(400, "delivery_order_must_confirm_first", request))
            if order.invoice_id:
                raise HTTPException(**http_error(400, "delivery_order_invoice_already_linked", request))
    
            lines = db.execute(text("""
                SELECT dol.*, p.selling_price, p.tax_rate, p.product_name, p.cost_price
                FROM delivery_order_lines dol
                JOIN products p ON p.id = dol.product_id
                WHERE dol.delivery_order_id = :doid
            """), {"doid": do_id}).fetchall()
    
            if not lines:
                raise HTTPException(**http_error(400, "delivery_order_no_items_to_invoice", request))
    
            # Generate invoice number
            year = datetime.now().year
            inv_number = generate_sequential_number(db, f"SINV-{year}", "invoices", "invoice_number", branch_id=order.branch_id)
            base_currency = get_base_currency(db)
    
            # Calculate totals (tax resolved via engine)
            from utils.accounting import compute_invoice_totals
            _branch_id = order.branch_id
            resolved_lines = []
            for line in lines:
                tax_info = resolve_line_tax(_branch_id, line.product_id, db, customer_id=order.party_id)
                resolved_lines.append({"line": line, "tax_info": tax_info})
            
            totals = compute_invoice_totals([
                {
                    "quantity": rl["line"].delivered_qty,
                    "unit_price": rl["line"].selling_price or 0,
                    "tax_rate": rl["tax_info"]["tax_rate"],
                    "discount": 0,
                }
                for rl in resolved_lines
            ])
            subtotal = totals["subtotal"]
            tax_total = totals["total_tax"]
            grand_total = totals["grand_total"]
    
            # AUDIT-C2: align column list with the actual `invoices` DDL
            # (db_ddl/tenant_schema.py:948). The legacy INSERT used
            # `total_amount`, `delivery_order_id`, and `payment_method`,
            # none of which exist on the table — so the DO→Invoice flow
            # would fail at runtime or silently drop columns where
            # tolerant DBs allow it. We now use the canonical column set
            # and persist the linkage via the existing `related_invoice_id`
            # field (already used by sales returns / credit notes).
            inv = db.execute(text("""
                INSERT INTO invoices (
                    invoice_number, invoice_type, invoice_date, party_id,
                    subtotal, tax_amount, total, status,
                    branch_id, warehouse_id, currency,
                    created_by, idempotency_key
                ) VALUES (
                    :num, 'sales', CURRENT_DATE, :pid,
                    :sub, :tax, :total, 'posted',
                    :bid, :wid, :curr,
                    :uid, :idem_key
                ) RETURNING id
            """), {
                "num": inv_number, "pid": order.party_id,
                "sub": subtotal, "tax": tax_total, "total": grand_total,
                "bid": order.branch_id, "wid": order.warehouse_id,
                "curr": base_currency, "uid": user_id,
                "idem_key": idempotency_key
            })
            inv_id = inv.fetchone()[0]
    
            # Create invoice lines (tax resolved via engine)
            for rl in resolved_lines:
                line = rl["line"]
                tax_info = rl["tax_info"]
                line_total = (_dec(line.delivered_qty) * _dec(line.selling_price or 0)).quantize(_D2, ROUND_HALF_UP)
                line_tax = (line_total * _dec(tax_info["tax_rate"]) / Decimal('100')).quantize(_D2, ROUND_HALF_UP)
                db.execute(text("""
                    INSERT INTO invoice_lines (
                        invoice_id, product_id, description, quantity,
                        unit_price, tax_rate, tax_rate_id, tax_amount, line_total
                    ) VALUES (:iid, :pid, :desc, :qty, :up, :tr, :trid, :ta, :lt)
                """), {
                    "iid": inv_id, "pid": line.product_id,
                    "desc": line.product_name, "qty": _dec(line.delivered_qty),
                    "up": _dec(line.selling_price or 0),
                    "tr": tax_info["tax_rate"], "trid": tax_info.get("tax_rate_id"),
                    "ta": line_tax, "lt": line_total + line_tax
                })
    
            # Link DO to invoice
            db.execute(text("UPDATE delivery_orders SET invoice_id = :iid WHERE id = :doid"),
                       {"iid": inv_id, "doid": do_id})

            # ── Fiscal period check before GL posting ──
            check_fiscal_period_open(db, datetime.now().date())

            # ── Create Journal Entry via centralized GL service (TASK-015) ──
            ar_account = get_mapped_account_id(db, "acc_map_ar")
            revenue_account = get_mapped_account_id(db, "acc_map_sales_rev")
            vat_out_account = get_mapped_account_id(db, "acc_map_vat_out")
            cogs_account = get_mapped_account_id(db, "acc_map_cogs")
            # F-31: credit the source warehouse's inventory account.
            from utils.inventory_accounts import resolve_warehouse_inventory_account
            inventory_account = resolve_warehouse_inventory_account(db, order.warehouse_id)

            total_cogs = _dec(db.execute(text("""
                SELECT COALESCE(SUM(ABS(total_cost)), 0)
                FROM inventory_transactions
                WHERE reference_type = 'delivery_order'
                  AND reference_id = :doid
                  AND transaction_type = 'delivery'
            """), {"doid": do_id}).scalar()).quantize(_D2, ROUND_HALF_UP)

            je_lines = []
            if ar_account:
                je_lines.append({"account_id": ar_account, "debit": grand_total, "credit": 0,
                                 "description": "ذمم مدينة - فاتورة تسليم"})
            if revenue_account:
                je_lines.append({"account_id": revenue_account, "debit": 0, "credit": subtotal,
                                 "description": "إيرادات مبيعات"})
            if vat_out_account and tax_total > 0:
                je_lines.append({"account_id": vat_out_account, "debit": 0, "credit": tax_total,
                                 "description": "ضريبة مخرجات"})
            if cogs_account and inventory_account and total_cogs > 0:
                je_lines.append({"account_id": cogs_account, "debit": total_cogs, "credit": 0,
                                 "description": "تكلفة البضاعة المباعة"})
                je_lines.append({"account_id": inventory_account, "debit": 0, "credit": total_cogs,
                                 "description": "خصم مخزون (COGS)"})

            if not je_lines:
                raise HTTPException(**http_error(400, "ar_sales_revenue_accounts_incomplete", request))

            je_id, je_number = create_journal_entry(
                db=db,
                company_id=company_id,
                date=datetime.now().date().isoformat(),
                description=f"فاتورة من أمر تسليم {order.delivery_number}",
                lines=je_lines,
                user_id=user_id,
                branch_id=order.branch_id,
                reference=inv_number,
                status="posted",
                currency=base_currency,
                source="DeliveryOrder",
                source_id=do_id,
                username=current_user.get("username"),
                idempotency_key=f"{idempotency_key}:je" if idempotency_key else None,
            )

            # Update invoice with JE
            db.execute(text("UPDATE invoices SET journal_entry_id = :jeid WHERE id = :iid"),
                       {"jeid": je_id, "iid": inv_id})

            # AUDIT-C2: customer balance must flow through
            # party_site_balances (the source of truth for AR aging /
            # statements / credit checks). The legacy INSERT into
            # `party_transactions` was a stale code path that no report
            # reads from. Sign matches `sales/invoices.py:687`: the
            # remaining receivable increases the customer's balance.
            update_party_site_balance(
                db,
                party_id=order.party_id,
                branch_id=order.branch_id,
                currency=base_currency,
                amount=Decimal(str(grand_total)),
            )

            return {
                "message": i18n_message("delivery_invoice_created", request),
                "invoice_id": inv_id,
                "invoice_number": inv_number,
                "journal_entry_id": je_id
            }
        except HTTPException:
            raise
        except Exception as e:
            pass
            logger.error(f"Error creating invoice from DO: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ─── CANCEL ───────────────────────────────────────────────────────────────────

@router.post("/{do_id}/cancel", dependencies=[Depends(require_sensitive_permission("sales.void"))], response_model=Dict[str, Any])
def cancel_delivery_order(do_id: int, request: Request, current_user: dict = Depends(get_current_user)):
    """إلغاء أمر التسليم — إعادة المخزون إذا كان مؤكداً"""
    company_id = current_user.get("company_id")
    user_id = current_user.get("user_id")
    with transactional(company_id) as db:
        try:
            # AUDIT-H2: lock DO row to prevent racing cancel + confirm.
            order = db.execute(text(
                "SELECT * FROM delivery_orders WHERE id = :id FOR UPDATE"
            ), {"id": do_id}).fetchone()
            if not order:
                raise HTTPException(**http_error(404, "delivery_order_not_found"))
            if order.status == 'cancelled':
                raise HTTPException(**http_error(400, "delivery_order_already_cancelled", request))
            if order.invoice_id:
                raise HTTPException(**http_error(400, "delivery_order_cannot_cancel_with_invoice", request))
    
            # If confirmed, reverse inventory
            if order.status in ('confirmed', 'shipped', 'delivered'):
                lines = db.execute(text(
                    "SELECT * FROM delivery_order_lines WHERE delivery_order_id = :doid"
                ), {"doid": do_id}).fetchall()
    
                for line in lines:
                    delivered_qty = _dec(line.delivered_qty)
                    if not line.product_id or delivered_qty <= 0:
                        continue

                    from services.costing_service import CostingService
                    original_cost = db.execute(text("""
                        SELECT unit_cost
                        FROM inventory_transactions
                        WHERE reference_type = 'delivery_order'
                          AND reference_id = :doid
                          AND product_id = :pid
                          AND quantity < 0
                        ORDER BY id DESC
                        LIMIT 1
                    """), {"doid": do_id, "pid": line.product_id}).scalar()
                    unit_cost = _dec(original_cost)
                    if unit_cost <= 0:
                        unit_cost = _dec(db.execute(text("SELECT cost_price FROM products WHERE id = :id"), {"id": line.product_id}).scalar() or 0)

                    costing_method = CostingService._get_product_costing_method(db, line.product_id, order.warehouse_id)
                    if costing_method in ("fifo", "lifo"):
                        try:
                            return_result = CostingService.handle_return(
                                db,
                                product_id=line.product_id,
                                warehouse_id=order.warehouse_id,
                                quantity=delivered_qty,
                                unit_cost=Decimal(str(unit_cost)),
                                source_document_type="delivery_cancel",
                                source_document_id=do_id,
                                costing_method=costing_method,
                                original_source_document_type="delivery_order",
                                original_source_document_id=do_id,
                            )
                        except ValueError:
                            raise HTTPException(**http_error(400, "invalid_request", request))
                        unit_cost = _dec(return_result.get("restored_unit_cost", unit_cost))
                        total_cost = _dec(return_result.get("restored_total_cost", unit_cost * delivered_qty)).quantize(_D2, ROUND_HALF_UP)
                    else:
                        total_cost = (unit_cost * delivered_qty).quantize(_D2, ROUND_HALF_UP)
                        CostingService.update_cost(
                            db,
                            product_id=line.product_id,
                            warehouse_id=order.warehouse_id,
                            new_qty=Decimal(str(delivered_qty)),
                            new_price=Decimal(str(unit_cost)),
                        )

                    db.execute(text("""
                        INSERT INTO inventory (product_id, warehouse_id, quantity, average_cost, updated_at)
                        VALUES (:pid, :wid, :qty, :cost, NOW())
                        ON CONFLICT (product_id, warehouse_id)
                        DO UPDATE SET quantity = inventory.quantity + EXCLUDED.quantity,
                                      updated_at = NOW()
                    """), {
                        "qty": delivered_qty,
                        "pid": line.product_id,
                        "wid": order.warehouse_id,
                        "cost": Decimal(str(unit_cost)),
                    })
    
                    db.execute(text("""
                        INSERT INTO inventory_transactions (
                            product_id, warehouse_id, transaction_type, quantity,
                            reference_type, reference_id, notes, created_by,
                            unit_cost, total_cost
                        ) VALUES (:pid, :wid, 'delivery_cancel', :qty, 'delivery_order', :doid, :notes, :uid, :uc, :tc)
                    """), {
                        "pid": line.product_id, "wid": order.warehouse_id,
                        "qty": delivered_qty, "doid": do_id,
                        "notes": f"إلغاء أمر تسليم {order.delivery_number}", "uid": user_id,
                        "uc": Decimal(str(unit_cost)), "tc": Decimal(str(total_cost))
                    })
    
            db.execute(text("UPDATE delivery_orders SET status = 'cancelled' WHERE id = :id"), {"id": do_id})
    
            return {"message": i18n_message("delivery_cancelled_success", request), "status": "cancelled"}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ─── UPDATE ───────────────────────────────────────────────────────────────────

@router.put("/{do_id}", dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def update_delivery_order(do_id: int, body: DeliveryOrderUpdate, request: Request, current_user: dict = Depends(get_current_user)):
    """تعديل بيانات الشحن في أمر التسليم"""
    company_id = current_user.get("company_id")
    with transactional(company_id) as db:
        order = db.execute(text("SELECT status FROM delivery_orders WHERE id = :id"), {"id": do_id}).fetchone()
        if not order:
            raise HTTPException(**http_error(404, "delivery_order_not_found"))
        if order.status == 'cancelled':
            raise HTTPException(**http_error(400, "delivery_order_cannot_edit_cancelled", request))

        updates = {}
        data = body.dict(exclude_none=True)
        if not data:
            raise HTTPException(**http_error(400, "no_data_to_update"))

        set_parts = []
        for key, val in data.items():
            set_parts.append(f"{key} = :{key}")
            updates[key] = val
        updates["id"] = do_id

        db.execute(text(f"UPDATE delivery_orders SET {', '.join(set_parts)} WHERE id = :id"), updates) # noqa

        return {"message": i18n_message("delivery_order_updated", request)}
