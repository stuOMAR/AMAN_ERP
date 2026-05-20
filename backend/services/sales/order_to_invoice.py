"""Order-to-invoice conversion service for Sales."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text

from utils.accounting import generate_sequential_number
from utils.i18n import http_error, i18n_message
from utils.permissions import validate_branch_access

logger = logging.getLogger(__name__)


def _actor_get(actor: Any, key: str, default=None):
    if isinstance(actor, dict):
        return actor.get(key, default)
    return getattr(actor, key, default)


def _actor_context(actor: Any) -> dict:
    return {
        "id": _actor_get(actor, "id"),
        "username": _actor_get(actor, "username"),
        "role": _actor_get(actor, "role"),
        "permissions": _actor_get(actor, "permissions", []),
        "allowed_branches": _actor_get(actor, "allowed_branches", []),
        "company_id": _actor_get(actor, "company_id"),
    }


def _table_columns(db: Any, table_name: str) -> set[str]:
    return {
        row.column_name
        for row in db.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"),
            {"t": table_name},
        ).fetchall()
    }


def _existing_invoice_for_order(db: Any, order_id: int, idempotency_key: str | None, invoice_cols: set[str]):
    clauses = []
    params: dict[str, Any] = {"order_id": order_id, "key": idempotency_key}
    if "sales_order_id" in invoice_cols:
        clauses.append("sales_order_id = :order_id")
    if idempotency_key and "idempotency_key" in invoice_cols:
        clauses.append("idempotency_key = :key")
    if not clauses:
        return None
    return db.execute(
        text(f"SELECT * FROM invoices WHERE {' OR '.join(clauses)} ORDER BY id DESC LIMIT 1"),
        params,
    ).fetchone()


def convert_order_to_invoice(
    db: Any,
    *,
    order_id: int,
    company_id: str,
    actor: Any,
    idempotency_key: str | None,
    posting_date: str | None = None,
    memo: str | None = None,
) -> dict:
    """Convert a confirmed sales order to an invoice exactly once."""
    actor_ctx = _actor_context(actor)

    order_row = db.execute(
        text("SELECT * FROM sales_orders WHERE id = :order_id FOR UPDATE"),
        {"order_id": order_id},
    ).fetchone()
    if not order_row:
        raise HTTPException(**http_error(404, "sales_order_not_found"))

    order = dict(order_row._mapping)
    validate_branch_access(actor, order.get("branch_id"))

    invoice_cols = _table_columns(db, "invoices")
    existing = _existing_invoice_for_order(db, order_id, idempotency_key, invoice_cols)
    if existing:
        return {**dict(existing._mapping), "idempotent_replay": True}

    if order.get("converted_to_invoice_id"):
        existing = db.execute(
            text("SELECT * FROM invoices WHERE id = :id"),
            {"id": order["converted_to_invoice_id"]},
        ).fetchone()
        if existing:
            return {**dict(existing._mapping), "idempotent_replay": True}
        raise HTTPException(status_code=409, detail={
            "code": "sales.order_already_converted",
            "message": i18n_message("order_already_converted"),
        })

    if order.get("state") not in (None, "confirmed") and order.get("status") != "confirmed":
        raise HTTPException(status_code=409, detail={
            "code": "sales_order.invalid_state",
            "message": i18n_message("order_must_be_confirmed"),
        })

    lines = db.execute(
        text("SELECT * FROM sales_order_lines WHERE so_id = :order_id ORDER BY id"),
        {"order_id": order_id},
    ).fetchall()
    if not lines:
        raise HTTPException(**http_error(422, "order_has_no_lines"))

    inv_num = generate_sequential_number(db, "INV", "invoices", "invoice_number", branch_id=order.get("branch_id"))
    cols = [
        "invoice_number", "invoice_type", "invoice_date", "party_id",
        "subtotal", "tax_amount", "discount", "total", "paid_amount",
        "status", "notes", "branch_id", "warehouse_id", "currency",
        "exchange_rate", "created_by",
    ]
    vals = [
        ":invoice_number", "'sales'", "COALESCE(:posting_date, CURRENT_DATE)", ":party_id",
        ":subtotal", ":tax_amount", ":discount", ":total", "0",
        "'draft'", ":notes", ":branch_id", ":warehouse_id", ":currency",
        ":exchange_rate", ":created_by",
    ]
    if "state" in invoice_cols:
        cols.append("state")
        vals.append("'draft'")
    if "sales_order_id" in invoice_cols:
        cols.append("sales_order_id")
        vals.append(":sales_order_id")
    if idempotency_key and "idempotency_key" in invoice_cols:
        cols.append("idempotency_key")
        vals.append(":idempotency_key")

    insert_sql = f"INSERT INTO invoices ({', '.join(cols)}) VALUES ({', '.join(vals)})"
    if idempotency_key and "idempotency_key" in invoice_cols:
        insert_sql += """
            ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL
            DO NOTHING
        """
    insert_sql += " RETURNING id"

    result = db.execute(text(insert_sql), {
        "invoice_number": inv_num,
        "posting_date": posting_date,
        "party_id": order.get("party_id") or order.get("customer_id"),
        "subtotal": order.get("subtotal") or 0,
        "tax_amount": order.get("tax_amount") or 0,
        "discount": order.get("discount") or 0,
        "total": order.get("total") or 0,
        "notes": memo if memo is not None else order.get("notes"),
        "branch_id": order.get("branch_id"),
        "warehouse_id": order.get("warehouse_id"),
        "currency": order.get("currency"),
        "exchange_rate": order.get("exchange_rate"),
        "created_by": actor_ctx["id"],
        "sales_order_id": order_id,
        "idempotency_key": idempotency_key,
    }).fetchone()

    if result is None:
        existing = _existing_invoice_for_order(db, order_id, idempotency_key, invoice_cols)
        if existing:
            return {**dict(existing._mapping), "idempotent_replay": True}
        raise HTTPException(**http_error(409, "duplicate_idempotency_key"))

    invoice_id = result.id
    for row in lines:
        line = dict(row._mapping)
        db.execute(text("""
            INSERT INTO invoice_lines (
                invoice_id, product_id, description, quantity, unit_price,
                tax_rate, tax_rate_id, applied_taxes, discount, total
            ) VALUES (
                :invoice_id, :product_id, :description, :quantity, :unit_price,
                :tax_rate, :tax_rate_id, :applied_taxes, :discount, :total
            )
        """), {
            "invoice_id": invoice_id,
            "product_id": line.get("product_id"),
            "description": line.get("description") or "",
            "quantity": line.get("quantity") or 0,
            "unit_price": line.get("unit_price") or 0,
            "tax_rate": line.get("tax_rate") or 0,
            "tax_rate_id": line.get("tax_rate_id"),
            "applied_taxes": line.get("applied_taxes"),
            "discount": line.get("discount") or 0,
            "total": line.get("total") or 0,
        })

    if "converted_to_invoice_id" in _table_columns(db, "sales_orders"):
        db.execute(
            text("""
                UPDATE sales_orders
                SET converted_to_invoice_id = :invoice_id, updated_at = clock_timestamp()
                WHERE id = :order_id
            """),
            {"invoice_id": invoice_id, "order_id": order_id},
        )

    invoice = db.execute(text("SELECT * FROM invoices WHERE id = :id"), {"id": invoice_id}).fetchone()
    invoice_dict = dict(invoice._mapping) if invoice else {"id": invoice_id}

    if "state" in invoice_cols:
        try:
            from services.sales.invoice_state import transition
            invoice_dict = transition(db, invoice_dict, "posted", actor=actor_ctx)
        except Exception:
            logger.warning("Order-to-invoice state transition failed; returning draft invoice", exc_info=True)

    try:
        from services.audit_writer import log_activity
        log_activity(
            db,
            action="sales.invoice.created_from_order",
            entity_type="invoice",
            entity_id=invoice_id,
            details={"order_id": order_id, "idempotency_key": idempotency_key},
        )
    except Exception:
        logger.warning("Audit write failed for order-to-invoice", exc_info=True)

    return invoice_dict
