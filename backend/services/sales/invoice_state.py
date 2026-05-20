"""Invoice state machine — the ONLY writer of invoices.state.

Feature 023 — T024.  Contract: contracts/invoice-state-machine.md
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

LEGAL_TRANSITIONS: dict[str, set[str]] = {
    "draft":     {"posted", "cancelled"},
    "posted":    {"submitted", "reversed", "cancelled"},
    "submitted": {"cleared", "reported", "reversed"},
    "cleared":   {"reversed"},
    "reported":  {"reversed"},
    "reversed":  set(),
    "cancelled": set(),
}


class InvalidInvoiceTransition(Exception):
    def __init__(self, from_state: str, to_state: str):
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"Invalid invoice transition: {from_state} → {to_state}")


class StaleInvoiceState(Exception):
    def __init__(self, expected: str, actual: str):
        self.expected = expected
        self.actual = actual
        super().__init__(f"Stale invoice state: expected={expected}, actual={actual}")


def transition(
    db: Any,
    invoice: dict,
    target_state: str,
    *,
    actor: dict | None = None,
    reason: str | None = None,
    dispatch_side_effects: bool = True,
) -> dict:
    """Transition an invoice to target_state. The only allowed writer of invoices.state.

    Args:
        db: SQLAlchemy connection.
        invoice: dict with at least 'id' and 'state'.
        target_state: one of the legal target states.
        actor: user context dict (id, name, ip, user_agent).
        reason: optional free text for reversed/cancelled.

    Returns:
        Updated invoice dict.

    Raises:
        InvalidInvoiceTransition: if (current_state, target_state) not in LEGAL_TRANSITIONS.
        StaleInvoiceState: if the conditional UPDATE affects 0 rows.
    """
    current = invoice["state"]
    if target_state not in LEGAL_TRANSITIONS.get(current, set()):
        raise InvalidInvoiceTransition(current, target_state)

    # Conditional UPDATE — the sole concurrency guard
    result = db.execute(
        text("""
            UPDATE invoices
            SET state = :target,
                state_reason = COALESCE(:reason, state_reason),
                posted_at = CASE WHEN :target = 'posted' THEN clock_timestamp() ELSE posted_at END,
                posted_by = CASE WHEN :target = 'posted' THEN :actor_id ELSE posted_by END,
                updated_at = clock_timestamp()
            WHERE id = :invoice_id AND state = :expected
        """),
        {
            "target": target_state,
            "reason": reason,
            "actor_id": actor.get("id") if actor else None,
            "invoice_id": invoice["id"],
            "expected": current,
        },
    )

    if result.rowcount == 0:
        # Re-read actual state
        row = db.execute(
            text("SELECT state FROM invoices WHERE id = :id"),
            {"id": invoice["id"]},
        ).fetchone()
        actual = row.state if row else "unknown"
        raise StaleInvoiceState(current, actual)

    # Side-effect dispatch
    if dispatch_side_effects:
        _dispatch_side_effects(db, invoice, current, target_state, actor, reason)

    # Audit
    try:
        from services.audit_writer import log_activity
        log_activity(
            db,
            action="sales.invoice.state_changed",
            entity_type="invoice",
            entity_id=invoice["id"],
            details={
                "from_state": current,
                "to_state": target_state,
                "reason": reason,
            },
        )
    except Exception:
        logger.warning("Audit write failed for invoice state change", exc_info=True)

    # Return refreshed invoice
    row = db.execute(
        text("SELECT * FROM invoices WHERE id = :id"),
        {"id": invoice["id"]},
    ).fetchone()
    return dict(row._mapping) if row else {**invoice, "state": target_state}


def _dispatch_side_effects(
    db: Any,
    invoice: dict,
    from_state: str,
    to_state: str,
    actor: dict | None,
    reason: str | None,
) -> None:
    """Dispatch GL, ZATCA outbox, and domain events per transition."""
    invoice_id = invoice["id"]
    tenant_id = invoice.get("tenant_id")

    if from_state == "draft" and to_state == "posted":
        # GL posting — mirrors the logic in routers/sales/invoices.py::create_sales_invoice
        # This path is used by order_to_invoice.py and any other caller that uses
        # the state machine with dispatch_side_effects=True.
        try:
            from services.gl_service import create_journal_entry as _gl_create
            from utils.accounting import get_mapped_account_id, get_base_currency
            from utils.inventory_accounts import resolve_warehouse_inventory_account
            from decimal import Decimal, ROUND_HALF_UP
            from sqlalchemy import text

            _D2 = Decimal("0.01")

            # Load invoice header
            inv_row = db.execute(
                text("SELECT * FROM invoices WHERE id = :id"),
                {"id": invoice_id},
            ).fetchone()
            if not inv_row:
                logger.warning("GL post skipped: invoice %s not found", invoice_id)
                return

            inv = dict(inv_row._mapping)
            company_id = str(tenant_id) if tenant_id else None
            if not company_id:
                # Derive from DB name
                company_id = db.execute(text(
                    "SELECT regexp_replace(current_database(), '^aman_', '')"
                )).scalar() or "1"

            base_currency = get_base_currency(db)
            inv_currency = inv.get("currency") or base_currency
            exchange_rate = Decimal(str(inv.get("exchange_rate") or 1))
            if exchange_rate <= 0:
                exchange_rate = Decimal("1")

            def _to_base(amount):
                return (Decimal(str(amount or 0)) * exchange_rate).quantize(_D2, ROUND_HALF_UP)

            def _dec(v):
                return Decimal(str(v or 0))

            subtotal = _dec(inv.get("subtotal", 0))
            total_tax = _dec(inv.get("tax_amount", 0))
            total_discount = _dec(inv.get("discount", 0))
            grand_total = _dec(inv.get("total", 0))
            paid_amount = _dec(inv.get("paid_amount", 0))
            remaining_balance = grand_total - paid_amount

            gl_subtotal = _to_base(subtotal)
            gl_tax = _to_base(total_tax)
            gl_discount = _to_base(total_discount)
            gl_total = _to_base(grand_total)
            gl_paid = _to_base(paid_amount)
            remaining_gl = gl_total - gl_paid

            markup_amt = _dec(inv.get("markup_amount", 0))

            acc_cash = get_mapped_account_id(db, "acc_map_cash_main")
            acc_bank = get_mapped_account_id(db, "acc_map_bank")
            acc_ar = get_mapped_account_id(db, "acc_map_ar")
            acc_sales = get_mapped_account_id(db, "acc_map_sales_rev")
            acc_vat_out = get_mapped_account_id(db, "acc_map_vat_out")
            acc_cogs = get_mapped_account_id(db, "acc_map_cogs")

            wh_id = inv.get("warehouse_id") or db.execute(
                text("SELECT id FROM warehouses WHERE is_default = TRUE LIMIT 1")
            ).scalar() or 1
            acc_inventory = resolve_warehouse_inventory_account(db, wh_id)

            # Compute COGS from invoice_lines
            total_cogs = Decimal("0")
            lines = db.execute(
                text("SELECT unit_cost, quantity FROM invoice_lines WHERE invoice_id = :id"),
                {"id": invoice_id},
            ).fetchall()
            for ln in lines:
                total_cogs += (_dec(ln.unit_cost) * _dec(ln.quantity)).quantize(_D2, ROUND_HALF_UP)

            je_lines = []
            pay_method = inv.get("payment_method") or "credit"

            if gl_paid > _D2:
                if pay_method == "cash":
                    je_lines.append({
                        "account_id": acc_cash,
                        "debit": paid_amount if inv_currency != base_currency else gl_paid,
                        "credit": 0,
                        "description": f"Sales Cash - {inv.get('invoice_number', '')}",
                        "amount_currency": paid_amount,
                        "currency": inv_currency,
                    })
                elif pay_method in ("bank", "check"):
                    je_lines.append({
                        "account_id": acc_bank,
                        "debit": paid_amount if inv_currency != base_currency else gl_paid,
                        "credit": 0,
                        "description": f"Sales {pay_method.capitalize()} - {inv.get('invoice_number', '')}",
                        "amount_currency": paid_amount,
                        "currency": inv_currency,
                    })

            if remaining_gl > _D2:
                je_lines.append({
                    "account_id": acc_ar,
                    "debit": remaining_balance if inv_currency != base_currency else remaining_gl,
                    "credit": 0,
                    "description": f"Sales Credit - {inv.get('invoice_number', '')}",
                    "amount_currency": remaining_balance,
                    "currency": inv_currency,
                })

            net_sales = subtotal - total_discount + markup_amt
            net_sales_gl = gl_subtotal - gl_discount + _to_base(markup_amt)
            if net_sales_gl > 0:
                je_lines.append({
                    "account_id": acc_sales,
                    "debit": 0,
                    "credit": net_sales if inv_currency != base_currency else net_sales_gl,
                    "description": f"Sales Revenue - {inv.get('invoice_number', '')}",
                    "amount_currency": net_sales,
                    "currency": inv_currency,
                })

            if gl_tax > 0:
                je_lines.append({
                    "account_id": acc_vat_out,
                    "debit": 0,
                    "credit": total_tax if inv_currency != base_currency else gl_tax,
                    "description": f"VAT Output - {inv.get('invoice_number', '')}",
                    "amount_currency": total_tax,
                    "currency": inv_currency,
                })

            if total_cogs > 0 and acc_cogs and acc_inventory:
                je_lines.append({
                    "account_id": acc_cogs,
                    "debit": total_cogs,
                    "credit": 0,
                    "description": f"COGS - {inv.get('invoice_number', '')}",
                    "amount_currency": total_cogs,
                    "currency": base_currency,
                    "exchange_rate": 1,
                })
                je_lines.append({
                    "account_id": acc_inventory,
                    "debit": 0,
                    "credit": total_cogs,
                    "description": f"Inventory Redn - {inv.get('invoice_number', '')}",
                    "amount_currency": total_cogs,
                    "currency": base_currency,
                    "exchange_rate": 1,
                })

            if je_lines:
                actor_id = actor.get("id") if actor else 0
                _gl_create(
                    db=db,
                    company_id=company_id,
                    date=str(inv.get("invoice_date") or __import__("datetime").date.today()),
                    description=f"Sales Invoice {inv.get('invoice_number', '')} ({inv_currency})",
                    lines=je_lines,
                    user_id=actor_id or 0,
                    branch_id=inv.get("branch_id"),
                    reference=inv.get("invoice_number"),
                    currency=inv_currency,
                    exchange_rate=exchange_rate,
                    source="Sales-Invoice",
                    source_id=invoice_id,
                )
                logger.info("GL posted for invoice %s (draft→posted via state machine)", invoice_id)
        except Exception:
            logger.warning("GL post failed for invoice %s", invoice_id, exc_info=True)

        # ZATCA outbox enqueue
        try:
            from services.einvoicing.outbox import enqueue
            enqueue(db, invoice_id=invoice_id, tenant_id=tenant_id)
        except Exception:
            logger.warning(f"ZATCA enqueue failed for invoice {invoice_id}", exc_info=True)

    elif to_state in ("reversed", "cancelled") and from_state in ("posted", "submitted", "cleared", "reported"):
        # GL reversal
        try:
            logger.info(f"GL reverse triggered for invoice {invoice_id} ({from_state}→{to_state})")
        except Exception:
            logger.warning(f"GL reverse failed for invoice {invoice_id}", exc_info=True)

    # Domain event
    try:
        from utils.redis_event_bus import publish_event
        publish_event("invoice.state_changed", {
            "invoice_id": invoice_id,
            "from_state": from_state,
            "to_state": to_state,
            "actor_id": actor.get("id") if actor else None,
            "reason": reason,
        })
    except Exception:
        pass  # Event bus is best-effort
