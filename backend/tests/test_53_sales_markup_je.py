"""T3.2 (audit #15) — sales JE must balance when invoice has a header markup.

The bug: `grand_total = subtotal - discount + tax + markup` was used as the
debit (AR / Cash) but the credit side only summed Revenue (= subtotal -
discount) + VAT, omitting `markup`. The fix folds the markup into the
Revenue credit line so debits == credits regardless of markup.

These tests are pure-Python: they re-implement the JE math the same way
`backend/routers/sales/invoices.py` does, asserting the legs balance.
"""
from decimal import Decimal

from utils.accounting import compute_invoice_totals


def _je_balance(*, lines, header_discount_pct=0, markup_amount=0):
    totals = compute_invoice_totals(
        lines,
        header_discount_pct=header_discount_pct,
        markup_amount=markup_amount,
    )
    subtotal = totals["subtotal"]
    total_discount = totals["total_discount"]
    total_tax = totals["total_tax"]
    grand_total = totals["grand_total"]
    markup = Decimal(str(markup_amount or 0))

    # Debit side (AR — assume fully credit sale, no COGS for this unit test).
    debits = grand_total

    # Credit side, mirroring routers/sales/invoices.py after the fix:
    #   Revenue = subtotal - discount + markup
    #   VAT     = total_tax
    revenue = subtotal - total_discount + markup
    credits = revenue + total_tax

    return debits, credits, totals


def test_sales_je_balances_without_markup():
    lines = [{"quantity": 2, "unit_price": 100, "tax_rate": 15, "discount": 0}]
    debits, credits, _ = _je_balance(lines=lines, markup_amount=0)
    assert debits == credits


def test_sales_je_balances_with_markup_only():
    lines = [{"quantity": 2, "unit_price": 100, "tax_rate": 15, "discount": 0}]
    debits, credits, totals = _je_balance(lines=lines, markup_amount=20)
    assert debits == credits
    # grand_total must include markup
    assert totals["grand_total"] == Decimal("250.00")  # 200 + 30 VAT + 20


def test_sales_je_balances_with_discount_and_markup():
    # Note: in production a header can be either discount OR markup, but the
    # math should still balance defensively.
    lines = [{"quantity": 4, "unit_price": 50, "tax_rate": 15, "discount": 5}]
    debits, credits, _ = _je_balance(
        lines=lines, header_discount_pct=0, markup_amount=10
    )
    assert debits == credits


def test_sales_je_balances_with_header_discount():
    lines = [{"quantity": 1, "unit_price": 1000, "tax_rate": 15, "discount": 0}]
    debits, credits, _ = _je_balance(
        lines=lines, header_discount_pct=10, markup_amount=0
    )
    assert debits == credits
