"""
AMAN ERP — Delivery Orders Router
أوامر التسليم: مستند وسيط بين أمر البيع والفاتورة
"""

from fastapi import APIRouter, Depends, HTTPException
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
from pydantic import BaseModel
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import require_permission, require_sensitive_permission
from utils.audit import log_activity
from utils.accounting import (
    generate_sequential_number, get_mapped_account_id,
    get_base_currency
)
from utils.fiscal_lock import check_fiscal_period_open
from services.gl_service import create_journal_entry  # TASK-015: centralized GL posting

router = APIRouter(prefix="/sales/delivery-orders", tags=["Delivery Orders"])
logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')


# ─── Schemas ───────────────────────────────────────────────────────────────────

class DeliveryLineCreate(BaseModel):
    product_id: int
    so_line_id: Optional[int] = None
    description: Optional[str] = None
    ordered_qty: float = 0
    delivered_qty: float = 0
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
    current_user: dict = Depends(get_current_user)
):
    """قائمة أوامر التسليم"""
    company_id = current_user.get("company_id")
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

        # Branch filtering
        allowed = current_user.get("allowed_branches")
        if allowed and isinstance(allowed, list):
            query += " AND (do.branch_id = ANY(:branches) OR do.branch_id IS NULL)"
            params["branches"] = allowed

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
        result["lines"] = [dict(l._mapping) for l in lines]
        return result


# ─── CREATE ────────────────────────────────────────────────────────────────────

@router.post("", status_code=201, dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def create_delivery_order(body: DeliveryOrderCreate, current_user: dict = Depends(get_current_user)):
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
    
            if so_id and not lines:
                so = db.execute(text("SELECT * FROM sales_orders WHERE id = :id"), {"id": so_id}).fetchone()
                if not so:
                    raise HTTPException(**http_error(404, "sales_order_not_found"))
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
    
            total_items = len(lines)
            total_qty = sum(l.delivered_qty for l in lines)
    
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
                "bid": body.branch_id, "sm": body.shipping_method,
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
            raise HTTPException(500, "حدث خطأ في إنشاء أمر التسليم")


# ─── CONFIRM (ship) ───────────────────────────────────────────────────────────

@router.post("/{do_id}/confirm", dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def confirm_delivery_order(do_id: int, current_user: dict = Depends(get_current_user)):
    """
    تأكيد أمر التسليم — خصم المخزون من المستودع
    يُنشئ حركات مخزون ولكن ليس قيداً (القيد عند الفاتورة)
    """
    company_id = current_user.get("company_id")
    user_id = current_user.get("user_id")
    with transactional(company_id) as db:
        try:
            order = db.execute(text("SELECT * FROM delivery_orders WHERE id = :id"), {"id": do_id}).fetchone()
            if not order:
                raise HTTPException(**http_error(404, "delivery_order_not_found"))
            if order.status != 'draft':
                raise HTTPException(400, f"لا يمكن تأكيد أمر بحالة {order.status}")
    
            lines = db.execute(text(
                "SELECT * FROM delivery_order_lines WHERE delivery_order_id = :doid"
            ), {"doid": do_id}).fetchall()
    
            warehouse_id = order.warehouse_id
    
            for line in lines:
                delivered_qty = _dec(line.delivered_qty)
                if not line.product_id or delivered_qty <= 0:
                    continue
    
                # Check stock
                stock = db.execute(text("""
                    SELECT quantity FROM inventory
                    WHERE product_id = :pid AND warehouse_id = :wid
                """), {"pid": line.product_id, "wid": warehouse_id}).fetchone()
    
                available = _dec(stock.quantity) if stock else Decimal('0')
                if available < delivered_qty:
                    product = db.execute(text("SELECT product_name FROM products WHERE id = :id"), {"id": line.product_id}).fetchone()
                    pname = product.product_name if product else f"#{line.product_id}"
                    raise HTTPException(400, f"المخزون غير كافٍ للمنتج {pname}: متوفر {available}, مطلوب {line.delivered_qty}")
    
                # Deduct inventory
                db.execute(text("""
                    UPDATE inventory SET quantity = quantity - :qty, updated_at = CURRENT_TIMESTAMP
                    WHERE product_id = :pid AND warehouse_id = :wid
                """), {"qty": delivered_qty, "pid": line.product_id, "wid": warehouse_id})
    
                # Record inventory transaction
                db.execute(text("""
                    INSERT INTO inventory_transactions (
                        product_id, warehouse_id, transaction_type, quantity,
                        reference_type, reference_id, notes, created_by
                    ) VALUES (
                        :pid, :wid, 'delivery', :qty, 'delivery_order', :doid,
                        :notes, :uid
                    )
                """), {
                    "pid": line.product_id, "wid": warehouse_id,
                    "qty": -delivered_qty, "doid": do_id,
                    "notes": f"تسليم بموجب {order.delivery_number}", "uid": user_id
                })
    
            # Update status
            db.execute(text("""
                UPDATE delivery_orders SET status = 'confirmed', shipped_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """), {"id": do_id})
    
    
            log_activity(db, user_id, "delivery_order.confirm", f"تأكيد تسليم {order.delivery_number}", {"id": do_id})
    
            return {"message": "تم تأكيد أمر التسليم وخصم المخزون", "status": "confirmed"}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ─── MARK DELIVERED ────────────────────────────────────────────────────────────

@router.post("/{do_id}/deliver", dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def mark_delivered(do_id: int, current_user: dict = Depends(get_current_user)):
    """تسجيل وصول الشحنة / تسليم العميل"""
    company_id = current_user.get("company_id")
    with transactional(company_id) as db:
        order = db.execute(text("SELECT * FROM delivery_orders WHERE id = :id"), {"id": do_id}).fetchone()
        if not order:
            raise HTTPException(**http_error(404, "delivery_order_not_found"))
        if order.status not in ('confirmed', 'shipped'):
            raise HTTPException(400, f"لا يمكن وضع حالة تسليم لأمر بحالة {order.status}")

        db.execute(text("""
            UPDATE delivery_orders SET status = 'delivered', delivered_at = CURRENT_TIMESTAMP
            WHERE id = :id
        """), {"id": do_id})

        return {"message": "تم تسجيل التسليم بنجاح", "status": "delivered"}


# ─── CREATE INVOICE FROM DO ───────────────────────────────────────────────────

@router.post("/{do_id}/create-invoice", dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def create_invoice_from_delivery(do_id: int, current_user: dict = Depends(get_current_user)):
    """إنشاء فاتورة مبيعات من أمر التسليم"""
    company_id = current_user.get("company_id")
    user_id = current_user.get("user_id")
    with transactional(company_id) as db:
        try:
            order = db.execute(text("SELECT * FROM delivery_orders WHERE id = :id"), {"id": do_id}).fetchone()
            if not order:
                raise HTTPException(**http_error(404, "delivery_order_not_found"))
            if order.status not in ('confirmed', 'delivered'):
                raise HTTPException(400, "يجب تأكيد أمر التسليم أولاً")
            if order.invoice_id:
                raise HTTPException(400, f"يوجد فاتورة مرتبطة بالفعل: #{order.invoice_id}")
    
            lines = db.execute(text("""
                SELECT dol.*, p.selling_price, p.tax_rate, p.product_name, p.cost_price
                FROM delivery_order_lines dol
                JOIN products p ON p.id = dol.product_id
                WHERE dol.delivery_order_id = :doid
            """), {"doid": do_id}).fetchall()
    
            if not lines:
                raise HTTPException(400, "لا توجد أصناف للفوترة")
    
            # Generate invoice number
            year = datetime.now().year
            inv_number = generate_sequential_number(db, f"SINV-{year}", "invoices", "invoice_number")
            base_currency = get_base_currency(db)
    
            # Calculate totals (TASK-027: unified via compute_invoice_totals)
            from utils.accounting import compute_invoice_totals
            totals = compute_invoice_totals([
                {
                    "quantity": line.delivered_qty,
                    "unit_price": line.selling_price or 0,
                    "tax_rate": line.tax_rate or 0,
                    "discount": 0,
                }
                for line in lines
            ])
            subtotal = totals["subtotal"]
            tax_total = totals["total_tax"]
            grand_total = totals["grand_total"]
    
            # Create invoice
            inv = db.execute(text("""
                INSERT INTO invoices (
                    invoice_number, invoice_type, invoice_date, party_id,
                    subtotal, tax_amount, total_amount, status,
                    branch_id, warehouse_id, delivery_order_id, currency,
                    payment_method, created_by
                ) VALUES (
                    :num, 'sales', CURRENT_DATE, :pid,
                    :sub, :tax, :total, 'posted',
                    :bid, :wid, :doid, :curr,
                    'credit', :uid
                ) RETURNING id
            """), {
                "num": inv_number, "pid": order.party_id,
                "sub": subtotal, "tax": tax_total, "total": grand_total,
                "bid": order.branch_id, "wid": order.warehouse_id,
                "doid": do_id, "curr": base_currency, "uid": user_id
            })
            inv_id = inv.fetchone()[0]
    
            # Create invoice lines
            for line in lines:
                line_total = (_dec(line.delivered_qty) * _dec(line.selling_price or 0)).quantize(_D2, ROUND_HALF_UP)
                line_tax = (line_total * _dec(line.tax_rate or 0) / Decimal('100')).quantize(_D2, ROUND_HALF_UP)
                db.execute(text("""
                    INSERT INTO invoice_lines (
                        invoice_id, product_id, description, quantity,
                        unit_price, tax_rate, tax_amount, line_total
                    ) VALUES (:iid, :pid, :desc, :qty, :up, :tr, :ta, :lt)
                """), {
                    "iid": inv_id, "pid": line.product_id,
                    "desc": line.product_name, "qty": _dec(line.delivered_qty),
                    "up": _dec(line.selling_price or 0),
                    "tr": _dec(line.tax_rate or 0),
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
            inventory_account = get_mapped_account_id(db, "acc_map_inventory")
    
            total_cogs = sum(
                (_dec(l.delivered_qty) * _dec(l.cost_price or 0)).quantize(_D2, ROUND_HALF_UP)
                for l in lines
            )
    
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
                raise HTTPException(400, "خريطة الحسابات غير مكتملة للمبيعات")
    
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
                idempotency_key=f"do-invoice-{do_id}",
            )
    
            # Update invoice with JE
            db.execute(text("UPDATE invoices SET journal_entry_id = :jeid WHERE id = :iid"),
                       {"jeid": je_id, "iid": inv_id})
    
            # Party transaction
            db.execute(text("""
                INSERT INTO party_transactions (
                    party_id, transaction_type, debit, credit, balance,
                    reference_type, reference_id, description, created_by
                ) VALUES (:pid, 'invoice', :amt, 0, :amt, 'invoice', :iid, :desc, :uid)
            """), {"pid": order.party_id, "amt": grand_total, "iid": inv_id,
                   "desc": f"فاتورة {inv_number}", "uid": user_id})
    
    
            return {
                "message": "تم إنشاء الفاتورة بنجاح",
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
def cancel_delivery_order(do_id: int, current_user: dict = Depends(get_current_user)):
    """إلغاء أمر التسليم — إعادة المخزون إذا كان مؤكداً"""
    company_id = current_user.get("company_id")
    user_id = current_user.get("user_id")
    with transactional(company_id) as db:
        try:
            order = db.execute(text("SELECT * FROM delivery_orders WHERE id = :id"), {"id": do_id}).fetchone()
            if not order:
                raise HTTPException(**http_error(404, "delivery_order_not_found"))
            if order.status == 'cancelled':
                raise HTTPException(400, "أمر التسليم ملغى بالفعل")
            if order.invoice_id:
                raise HTTPException(400, "لا يمكن إلغاء أمر تسليم مرتبط بفاتورة")
    
            # If confirmed, reverse inventory
            if order.status in ('confirmed', 'shipped', 'delivered'):
                lines = db.execute(text(
                    "SELECT * FROM delivery_order_lines WHERE delivery_order_id = :doid"
                ), {"doid": do_id}).fetchall()
    
                for line in lines:
                    delivered_qty = _dec(line.delivered_qty)
                    if not line.product_id or delivered_qty <= 0:
                        continue
                    db.execute(text("""
                        UPDATE inventory SET quantity = quantity + :qty
                        WHERE product_id = :pid AND warehouse_id = :wid
                    """), {"qty": delivered_qty, "pid": line.product_id, "wid": order.warehouse_id})
    
                    db.execute(text("""
                        INSERT INTO inventory_transactions (
                            product_id, warehouse_id, transaction_type, quantity,
                            reference_type, reference_id, notes, created_by
                        ) VALUES (:pid, :wid, 'delivery_cancel', :qty, 'delivery_order', :doid, :notes, :uid)
                    """), {
                        "pid": line.product_id, "wid": order.warehouse_id,
                        "qty": delivered_qty, "doid": do_id,
                        "notes": f"إلغاء أمر تسليم {order.delivery_number}", "uid": user_id
                    })
    
            db.execute(text("UPDATE delivery_orders SET status = 'cancelled' WHERE id = :id"), {"id": do_id})
    
            return {"message": "تم إلغاء أمر التسليم", "status": "cancelled"}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ─── UPDATE ───────────────────────────────────────────────────────────────────

@router.put("/{do_id}", dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def update_delivery_order(do_id: int, body: DeliveryOrderUpdate, current_user: dict = Depends(get_current_user)):
    """تعديل بيانات الشحن في أمر التسليم"""
    company_id = current_user.get("company_id")
    with transactional(company_id) as db:
        order = db.execute(text("SELECT status FROM delivery_orders WHERE id = :id"), {"id": do_id}).fetchone()
        if not order:
            raise HTTPException(**http_error(404, "delivery_order_not_found"))
        if order.status == 'cancelled':
            raise HTTPException(400, "لا يمكن تعديل أمر ملغى")

        updates = {}
        data = body.dict(exclude_none=True)
        if not data:
            raise HTTPException(**http_error(400, "no_data_to_update"))

        set_parts = []
        for key, val in data.items():
            set_parts.append(f"{key} = :{key}")
            updates[key] = val
        updates["id"] = do_id

        db.execute(text(f"UPDATE delivery_orders SET {', '.join(set_parts)} WHERE id = :id"), updates)

        return {"message": "تم تحديث أمر التسليم"}
