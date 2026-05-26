"""Sales preview helpers.

These helpers keep Sales UI previews read-only and route all monetary
arithmetic through the existing Decimal/tax utilities.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable

from sqlalchemy import text

from services.tax_engine import resolve_line_tax_group
from utils.accounting import compute_invoice_totals, compute_line_amounts
from utils.tax_precision import money_str, rate_str


_D2 = Decimal("0.01")
_D4 = Decimal("0.0001")
_D6 = Decimal("0.000001")


def dec(value: Any) -> Decimal:
    return Decimal(str(value)) if value not in (None, "") else Decimal("0")


def resolve_document_exchange_rate(db, *, currency: str | None, base_currency: str, document_date, provided_rate: Any = None) -> Decimal:
    """Resolve a document FX rate from an explicit value or the backend rate table."""
    if not currency or currency == base_currency:
        return Decimal("1").quantize(_D6)

    explicit_rate = dec(provided_rate)
    if explicit_rate > 0:
        return explicit_rate.quantize(_D6, ROUND_HALF_UP)

    row = db.execute(text("""
        SELECT rate
        FROM exchange_rates
        WHERE currency_id = (SELECT id FROM currencies WHERE code = :code)
          AND rate_date <= COALESCE(:date, CURRENT_DATE)
        ORDER BY rate_date DESC
        LIMIT 1
    """), {"code": currency, "date": document_date}).fetchone()
    if not row:
        raise ValueError("no_exchange_rate_for_currency")
    rate = dec(row.rate)
    if rate <= 0:
        raise ValueError("exchange_rate_must_be_positive")
    return rate.quantize(_D6, ROUND_HALF_UP)


def _line_dict(line: Any) -> dict[str, Any]:
    if hasattr(line, "model_dump"):
        return line.model_dump()
    if isinstance(line, dict):
        return line
    return {
        "product_id": getattr(line, "product_id", None),
        "description": getattr(line, "description", None),
        "quantity": getattr(line, "quantity", Decimal("0")),
        "unit_price": getattr(line, "unit_price", Decimal("0")),
        "tax_rate": getattr(line, "tax_rate", None),
        "discount": getattr(line, "discount", Decimal("0")),
    }


def _tax_details(db, branch_id: int | None, product_id: int | None, document_date, party_id: int | None, fallback_rate) -> tuple[Decimal, int | None, list[dict[str, Any]] | None]:
    if branch_id and product_id:
        taxes = resolve_line_tax_group(branch_id, product_id, db, document_date, customer_id=party_id)
        tax_rate = sum((dec(t.get("tax_rate")) for t in taxes), Decimal("0"))
        tax_rate_id = taxes[0].get("tax_rate_id") if len(taxes) == 1 else None
        applied_taxes = [
            {
                "tax_rate_id": t.get("tax_rate_id"),
                "tax_name": t.get("tax_name"),
                "tax_rate": rate_str(t.get("tax_rate", 0)),
            }
            for t in taxes
        ] if len(taxes) > 1 else None
        return tax_rate, tax_rate_id, applied_taxes

    return dec(fallback_rate), None, None


def preview_sales_totals(
    db,
    *,
    lines: Iterable[Any],
    branch_id: int | None,
    party_id: int | None,
    document_date,
    currency: str | None,
    paid_amount: Any = Decimal("0"),
    header_discount_pct: Any = Decimal("0"),
    markup_amount: Any = Decimal("0"),
) -> dict[str, Any]:
    """Return line/totals preview without persisting anything."""
    calculation_lines: list[dict[str, Decimal]] = []
    line_details: list[dict[str, Any]] = []

    for index, raw_line in enumerate(lines or []):
        line = _line_dict(raw_line)
        product_id = line.get("product_id")
        quantity = dec(line.get("quantity"))
        unit_price = dec(line.get("unit_price"))
        discount = dec(line.get("discount"))
        tax_rate, tax_rate_id, applied_taxes = _tax_details(
            db,
            branch_id,
            int(product_id) if product_id else None,
            document_date,
            party_id,
            line.get("tax_rate"),
        )

        amounts = compute_line_amounts(
            quantity,
            unit_price,
            tax_rate,
            discount,
            discount_is_percent=False,
        )
        calculation_lines.append({
            "quantity": quantity,
            "unit_price": unit_price,
            "tax_rate": tax_rate,
            "discount": discount,
        })
        line_details.append({
            "index": index,
            "product_id": product_id,
            "description": line.get("description"),
            "quantity": money_str(quantity),
            "unit_price": money_str(unit_price),
            "tax_rate": rate_str(tax_rate),
            "tax_rate_id": tax_rate_id,
            "applied_taxes": applied_taxes,
            "discount": money_str(discount),
            "subtotal": money_str(amounts["subtotal"]),
            "discount_amount": money_str(amounts["discount_amount"]),
            "taxable": money_str(amounts["taxable"]),
            "tax_amount": money_str(amounts["tax_amount"]),
            "line_total": money_str(amounts["line_total"]),
            "total": money_str(amounts["line_total"]),
        })

    totals = compute_invoice_totals(
        calculation_lines,
        header_discount_pct=header_discount_pct,
        markup_amount=markup_amount,
        discount_is_percent=False,
    )
    paid = dec(paid_amount)
    grand = totals["grand_total"]

    return {
        "subtotal": money_str(totals["subtotal"]),
        "total_discount": money_str(totals["total_discount"]),
        "total_tax": money_str(totals["total_tax"]),
        "grand_total": money_str(grand),
        "paid_amount": money_str(paid),
        "remaining_balance": money_str(grand - paid),
        "currency": currency,
        "lines": line_details,
    }


def customer_voucher_invoice_types(voucher_type: str | None) -> tuple[str, ...]:
    return (
        ("sales_return", "sales_credit_note")
        if voucher_type in {"refund", "payment"}
        else ("sales", "sales_debit_note")
    )


def allocation_preview_rows(invoice_rows, allocations, voucher_rate: Decimal):
    invoice_by_id = {int(row.id): row for row in invoice_rows}
    rows = []
    total_allocated = Decimal("0")

    for alloc in allocations:
        invoice_id = int(alloc["invoice_id"])
        invoice = invoice_by_id.get(invoice_id)
        if not invoice:
            continue
        allocated_amount = dec(alloc["allocated_amount"]).quantize(_D4, ROUND_HALF_UP)
        if allocated_amount <= 0:
            continue
        invoice_rate = dec(invoice.exchange_rate or 1)
        invoice_currency_amount = (allocated_amount * (voucher_rate / invoice_rate)).quantize(_D4, ROUND_HALF_UP)
        remaining = dec(invoice.remaining_balance or 0).quantize(_D4, ROUND_HALF_UP)
        total_allocated = (total_allocated + allocated_amount).quantize(_D4, ROUND_HALF_UP)
        rows.append({
            "invoice_id": invoice_id,
            "invoice_number": invoice.invoice_number,
            "invoice_currency": invoice.currency,
            "invoice_exchange_rate": rate_str(invoice_rate),
            "remaining_balance": money_str(remaining),
            "allocated_amount": money_str(allocated_amount),
            "invoice_currency_amount": money_str(invoice_currency_amount),
            "exceeds_remaining": invoice_currency_amount > (remaining + _D2),
        })

    return rows, total_allocated


def fetch_customer_open_invoices(db, *, customer_id: int, branch_filter_sql: str, params: dict[str, Any], voucher_type: str | None):
    query_params = {
        **params,
        "customer_id": customer_id,
        "types": list(customer_voucher_invoice_types(voucher_type)),
    }
    return db.execute(text(f"""
        SELECT id, invoice_number, invoice_date, total, COALESCE(paid_amount, 0) AS paid_amount,
               status, invoice_type, currency, COALESCE(exchange_rate, 1) AS exchange_rate,
               (total - COALESCE(paid_amount, 0)) AS remaining_balance
        FROM invoices
        WHERE party_id = :customer_id
          AND invoice_type = ANY(:types)
          AND status IN ('unpaid', 'partial', 'posted')
          AND COALESCE(total, 0) > COALESCE(paid_amount, 0)
          {branch_filter_sql}
        ORDER BY invoice_date ASC, id ASC
    """), query_params).fetchall()
