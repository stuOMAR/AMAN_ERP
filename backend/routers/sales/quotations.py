"""Sales quotations endpoints."""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import List, Optional
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import html
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.audit import log_activity
from utils.permissions import branch_scope_filter_from_scope, require_permission, resolve_branch_scope
from services.tax_engine import resolve_line_tax
from .schemas import QuotationCreate

quotations_router = APIRouter()
logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')


def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')


def _format_money(value) -> str:
    return f"{_dec(value).quantize(_D2, ROUND_HALF_UP):,.2f}"


@quotations_router.get("/quotations", response_model=List[dict], dependencies=[Depends(require_permission("sales.view"))])
def list_quotations(branch_id: Optional[int] = None, current_user: dict = Depends(get_current_user)):
    """List all sales quotations"""
    branch_scope = resolve_branch_scope(current_user, branch_id)

    db = get_db_connection(current_user.company_id)
    try:
        query_str = """
            SELECT q.id, q.sq_number, q.quotation_date, q.expiry_date, q.total, q.status,
                   p.name as customer_name
            FROM sales_quotations q
            JOIN parties p ON q.party_id = p.id
            WHERE 1=1
        """
        params = {}
        query_str += branch_scope_filter_from_scope(branch_scope, "q.branch_id", params)

        query_str += " ORDER BY q.created_at DESC"

        result = db.execute(text(query_str), params).fetchall()
        return [dict(row._mapping) for row in result]
    except Exception as e:
        logger.error(f"Error listing quotations: {str(e)}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@quotations_router.get("/quotations/{id}", response_model=dict, dependencies=[Depends(require_permission("sales.view"))])
def get_quotation(request: Request, id: int, current_user: dict = Depends(get_current_user)):
    """Get quotation details"""
    db = get_db_connection(current_user.company_id)
    try:
        # Get Header
        quotation = db.execute(text("""
            SELECT q.*, p.name as customer_name, p.email as customer_email, 
                   p.phone as customer_phone, p.address as customer_address, p.tax_number as customer_tax_number
            FROM sales_quotations q
            JOIN parties p ON q.party_id = p.id
            WHERE q.id = :id
        """), {"id": id}).fetchone()

        if not quotation:
            raise HTTPException(**http_error(404, "quotation_not_found", request))

        # Enforce branch access for single resource
        from utils.permissions import validate_branch_access
        if quotation.branch_id:
            validate_branch_access(current_user, quotation.branch_id)

        # Get Items
        items = db.execute(text("""
            SELECT l.*, p.product_name, p.product_code, p.sku
            FROM sales_quotation_lines l
            LEFT JOIN products p ON l.product_id = p.id
            WHERE l.sq_id = :id
        """), {"id": id}).fetchall()

        data = dict(quotation._mapping)
        data["customer_id"] = data.get("party_id") or data.get("customer_id")

        return {
            **data,
            "items": [dict(row._mapping) for row in items]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching quotation {id}: {str(e)}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@quotations_router.post("/quotations", response_model=dict, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("sales.create"))])
def create_quotation(request: Request, quotation: QuotationCreate, current_user: dict = Depends(get_current_user)):
    """Create a new sales quotation"""
    db = get_db_connection(current_user.company_id)
    try:
        customer = db.execute(text("""
            SELECT id, name, email, branch_id
            FROM parties
            WHERE id = :id AND (party_type = 'customer' OR is_customer = TRUE)
        """), {"id": quotation.customer_id}).fetchone()
        if not customer:
            raise HTTPException(**http_error(404, "customer_not_valid", request))

        # Generate SQ Number (SQ-YYYY-XXXX)
        year = datetime.now().year
        last_sq = db.execute(text(
            "SELECT sq_number FROM sales_quotations WHERE sq_number LIKE :prefix ORDER BY id DESC LIMIT 1"
        ), {"prefix": f"SQ-{year}-%"}).scalar()

        if last_sq:
            last_seq = int(last_sq.split('-')[-1])
            new_seq = last_seq + 1
        else:
            new_seq = 1

        sq_num = f"SQ-{year}-{new_seq:04d}"

        # Calculate Totals
        subtotal = Decimal('0')
        total_tax = Decimal('0')
        total_discount = Decimal('0')
        items_to_save = []
        _branch_id = quotation.branch_id or customer.branch_id

        for item in quotation.items:
            product = db.execute(text("""
                SELECT id, product_name, product_code, selling_price, tax_rate, is_active
                FROM products
                WHERE id = :id
            """), {"id": item.product_id}).fetchone()
            if not product:
                raise HTTPException(**http_error(400, "product_not_in_inventory", request))
            if product.is_active is False:
                raise HTTPException(status_code=400, detail=i18n_message("product_inactive_cannot_add_quotation", request))

            tax_info = resolve_line_tax(_branch_id, item.product_id, db, quotation.quotation_date, customer_id=quotation.customer_id)

            line_subtotal = _dec(item.quantity) * _dec(item.unit_price)
            taxable = line_subtotal - _dec(item.discount)
            if taxable < 0:
                raise HTTPException(**http_error(400, "discount_exceeds_line_value", request))
            line_tax = taxable * (tax_info["tax_rate"] / Decimal('100'))
            line_total = (taxable + line_tax).quantize(_D2, ROUND_HALF_UP)

            subtotal += line_subtotal
            total_tax += line_tax
            total_discount += _dec(item.discount)

            items_to_save.append({
                **item.model_dump(),
                "tax_rate": tax_info["tax_rate"],
                "tax_rate_id": tax_info.get("tax_rate_id"),
                "total": line_total
            })

        grand_total = (subtotal - total_discount + total_tax).quantize(_D2, ROUND_HALF_UP)

        # Save Header
        res = db.execute(text("""
            INSERT INTO sales_quotations (
                sq_number, party_id, quotation_date, expiry_date,
                subtotal, tax_amount, discount, total, status, notes, terms_conditions, created_by, branch_id,
                currency, exchange_rate, party_site_id
            ) VALUES (
                :num, :cust, :qdate, :expdate,
                :sub, :tax, :disc, :total, 'draft', :notes, :terms, :user, :bid,
                :currency, :exchange_rate, :party_site_id
            ) RETURNING id
        """), {
            "num": sq_num, "cust": quotation.customer_id, "qdate": quotation.quotation_date,
            "expdate": quotation.expiry_date, "sub": subtotal, "tax": total_tax,
            "disc": total_discount, "total": grand_total, "notes": quotation.notes,
            "terms": quotation.terms_conditions, "user": current_user.id,
            "bid": quotation.branch_id or customer.branch_id, "currency": quotation.currency,
            "exchange_rate": quotation.exchange_rate,
            "party_site_id": quotation.party_site_id,
        }).fetchone()

        sq_id = res[0]

        # Save Lines
        for line in items_to_save:
            db.execute(text("""
                INSERT INTO sales_quotation_lines (
                    sq_id, product_id, description, quantity, unit_price, tax_rate, tax_rate_id, discount, total
                ) VALUES (
                    :sq_id, :pid, :desc, :qty, :price, :tax_rate, :tax_rate_id, :disc, :total
                )
            """), {
                "sq_id": sq_id, "pid": line["product_id"], "desc": line["description"],
                "qty": line["quantity"], "price": line["unit_price"],
                "tax_rate": line["tax_rate"], "tax_rate_id": line.get("tax_rate_id"),
                "disc": line["discount"], "total": line["total"]
            })

        db.commit()

        cust_name = db.execute(text("SELECT name FROM parties WHERE id = :id"), {"id": quotation.customer_id}).scalar()
        # AUDIT LOG
        log_activity(
            db,
            user_id=current_user.id,
            username=current_user.username,
            action="sales.quotation.create",
            resource_type="sales_quotation",
            resource_id=str(sq_id),
            details={"sq_number": sq_num, "total": str(grand_total or 0), "customer_id": quotation.customer_id, "customer_name": cust_name},
            request=request
        )
        return {"id": sq_id, "sq_number": sq_num}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating Quotation: {str(e)}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@quotations_router.post("/quotations/{id}/send-email", response_model=dict, dependencies=[Depends(require_permission("sales.create"))])
def send_quotation_email(id: int, request: Request, current_user: dict = Depends(get_current_user)):
    """Send a quotation to the customer email and mark it as sent."""
    db = get_db_connection(current_user.company_id)
    try:
        quotation = db.execute(text("""
            SELECT q.*, p.name AS customer_name, p.email AS customer_email
            FROM sales_quotations q
            JOIN parties p ON q.party_id = p.id
            WHERE q.id = :id
        """), {"id": id}).fetchone()
        if not quotation:
            raise HTTPException(**http_error(404, "quotation_not_found", request))
        if quotation.status in ('converted', 'cancelled', 'expired'):
            raise HTTPException(status_code=400, detail=i18n_message("cannot_send_quotation_status", request))
        if not quotation.customer_email:
            raise HTTPException(**http_error(400, "no_customer_email", request))

        items = db.execute(text("""
            SELECT l.*, p.product_name, p.product_code
            FROM sales_quotation_lines l
            LEFT JOIN products p ON l.product_id = p.id
            WHERE l.sq_id = :id
            ORDER BY l.id
        """), {"id": id}).fetchall()
        if not items:
            raise HTTPException(**http_error(400, "cannot_send_empty_quotation", request))

        rows_html = "".join(
            "<tr>"
            f"<td>{html.escape(str(item.product_code or ''))}</td>"
            f"<td>{html.escape(str(item.product_name or item.description or ''))}</td>"
            f"<td>{_format_money(item.quantity)}</td>"
            f"<td>{_format_money(item.unit_price)}</td>"
            f"<td>{_format_money(item.total)}</td>"
            "</tr>"
            for item in items
        )
        content = f"""
            <h2>عرض سعر {html.escape(str(quotation.sq_number))}</h2>
            <p>عميلنا العزيز {html.escape(str(quotation.customer_name or ''))}،</p>
            <p>مرفق أدناه تفاصيل عرض السعر الصادر من نظام AMAN ERP.</p>
            <div class="info-box">
                <p><strong>تاريخ العرض:</strong> {html.escape(str(quotation.quotation_date))}</p>
                <p><strong>تاريخ الانتهاء:</strong> {html.escape(str(quotation.expiry_date or '-'))}</p>
                <p><strong>الإجمالي:</strong> <span class="amount">{_format_money(quotation.total)} {html.escape(str(quotation.currency or 'SAR'))}</span></p>
            </div>
            <table style="width:100%; border-collapse:collapse" border="1" cellpadding="8">
                <thead>
                    <tr><th>الكود</th><th>الصنف</th><th>الكمية</th><th>السعر</th><th>الإجمالي</th></tr>
                </thead>
                <tbody>{rows_html}</tbody>
            </table>
        """

        from services.email_service import get_base_template, get_email_service_from_settings
        service = get_email_service_from_settings(db, tenant_id=str(current_user.company_id))
        if not service:
            raise HTTPException(**http_error(400, "email_settings_incomplete", request))

        sent = service.send(
            quotation.customer_email,
            f"عرض سعر {quotation.sq_number}",
            get_base_template(content),
        )
        if not sent:
            raise HTTPException(**http_error(500, "email_send_failed_smtp", request))

        db.execute(text("""
            UPDATE sales_quotations
            SET status = 'sent', updated_at = NOW(), updated_by = :user
            WHERE id = :id
        """), {"id": id, "user": current_user.username})

        log_activity(
            db,
            user_id=current_user.id,
            username=current_user.username,
            action="sales.quotation.send_email",
            resource_type="sales_quotation",
            resource_id=str(id),
            details={"sq_number": quotation.sq_number, "recipient": quotation.customer_email},
            request=request,
            branch_id=quotation.branch_id,
        )
        db.commit()
        return {"success": True, "message": i18n_message("quotation_sent_email", request), "status": "sent", "recipient": quotation.customer_email}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error sending quotation email: {str(e)}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
