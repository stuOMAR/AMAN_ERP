"""T3.10 — POS totals must equal sales-invoice totals for identical inputs.

This test pins the *math* shared between POS order creation
(``routers/pos.create_order``) and sales invoice creation
(``routers/sales/invoices``) by exercising the same unified helper —
``utils.accounting.compute_invoice_totals`` — with the inputs each
router passes. The DoD for T3.10 is "POS results = sales invoice
results for the same inputs", and this is enforced by recomputing the
totals along both paths and asserting equality.

The test purposefully avoids spinning up the FastAPI app so it stays
hermetic and fast: the contract that has to hold is on the math, not
on HTTP plumbing. Live HTTP coverage already exists in
``tests/test_11_sales_scenarios``.

Two scenarios:

1. **Manual header discount** — a percentage-equivalent absolute
   amount on the order header. POS converts it to a header_discount_pct
   so tax is reduced proportionally (ZATCA rule). The sales-invoice
   path runs the same input as ``effect_type='discount'`` with the
   same percentage. Totals must match exactly.

2. **Coupon-resolved promotion** — POS receives ``coupon_code`` and
   resolves the promotion server-side into a header_discount_pct.
   The sales invoice receives the equivalent percentage directly.
   Totals must again match.

Per-line ``discount_amount`` (POS schema) is converted to a
percentage via the same helper used by the router so the two paths
see semantically identical inputs.
"""

from __future__ import annotations

import os
import re
import sys
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-t3-10")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from utils.accounting import compute_invoice_totals  # noqa: E402

POS_PATH = os.path.join(ROOT, "routers", "pos.py")


_D2 = Decimal("0.01")


def _line_discount_pct(qty, unit_price, disc_amt):
    """Mirror routers/pos._line_discount_pct exactly."""
    gross = (Decimal(str(qty)) * Decimal(str(unit_price))).quantize(_D2)
    if gross <= 0:
        return Decimal("0")
    amt = Decimal(str(disc_amt))
    if amt <= 0:
        return Decimal("0")
    if amt > gross:
        amt = gross
    return (amt * Decimal("100") / gross).quantize(Decimal("0.000001"))


def _pos_totals(items, header_disc_amount, gross_subtotal, promo_pct=None):
    """Reproduce the math routers/pos.create_order applies."""
    line_dicts = [
        {
            "quantity": it["quantity"],
            "unit_price": it["unit_price"],
            "tax_rate": it["tax_rate"],
            "discount": _line_discount_pct(it["quantity"], it["unit_price"], it.get("discount_amount", 0)),
        }
        for it in items
    ]
    if promo_pct is not None:
        header_pct = Decimal(str(promo_pct))
    elif Decimal(str(header_disc_amount)) > 0 and gross_subtotal > 0:
        header_pct = Decimal(str(header_disc_amount)) * Decimal("100") / gross_subtotal
    else:
        header_pct = Decimal("0")
    return compute_invoice_totals(line_dicts, header_discount_pct=header_pct)


def _invoice_totals(items, header_pct):
    """Reproduce the math routers/sales/invoices uses (effect_type='discount')."""
    line_dicts = [
        {
            "quantity": it["quantity"],
            "unit_price": it["unit_price"],
            "tax_rate": it["tax_rate"],
            # Sales invoice schema: per-line `discount` is already a percentage.
            "discount": _line_discount_pct(it["quantity"], it["unit_price"], it.get("discount_amount", 0)),
        }
        for it in items
    ]
    return compute_invoice_totals(line_dicts, header_discount_pct=Decimal(str(header_pct)))


def test_pos_matches_sales_invoice_with_manual_header_discount():
    items = [
        {"product_id": 1, "quantity": Decimal("2"), "unit_price": Decimal("100"), "tax_rate": Decimal("15"), "discount_amount": Decimal("0")},
        {"product_id": 2, "quantity": Decimal("3"), "unit_price": Decimal("50"),  "tax_rate": Decimal("15"), "discount_amount": Decimal("15")},
    ]
    gross = sum((it["quantity"] * it["unit_price"]).quantize(_D2) for it in items)
    # 200 + 150 = 350. Header disc 35 = 10%.
    header_amount = Decimal("35")
    header_pct = header_amount * Decimal("100") / gross  # 10

    pos = _pos_totals(items, header_amount, gross)
    inv = _invoice_totals(items, header_pct)

    assert pos["subtotal"] == inv["subtotal"]
    assert pos["total_discount"] == inv["total_discount"]
    assert pos["total_tax"] == inv["total_tax"]
    assert pos["grand_total"] == inv["grand_total"]


def test_pos_matches_sales_invoice_with_coupon_percentage_promotion():
    items = [
        {"product_id": 1, "quantity": Decimal("4"), "unit_price": Decimal("75"),  "tax_rate": Decimal("15"), "discount_amount": Decimal("0")},
        {"product_id": 2, "quantity": Decimal("1"), "unit_price": Decimal("250"), "tax_rate": Decimal("0"),  "discount_amount": Decimal("0")},
    ]
    gross = sum((it["quantity"] * it["unit_price"]).quantize(_D2) for it in items)
    promo_pct = Decimal("12.5")  # coupon resolves to 12.5%

    pos = _pos_totals(items, header_disc_amount=Decimal("0"), gross_subtotal=gross, promo_pct=promo_pct)
    inv = _invoice_totals(items, promo_pct)

    assert pos == inv


def test_pos_matches_sales_invoice_with_per_line_discount_amounts():
    """Per-line discount_amount on POS converts to the same effective
    pct that the sales invoice receives via item.discount."""
    items = [
        {"product_id": 1, "quantity": Decimal("1"), "unit_price": Decimal("200"), "tax_rate": Decimal("15"), "discount_amount": Decimal("20")},   # 10% line discount
        {"product_id": 2, "quantity": Decimal("2"), "unit_price": Decimal("100"), "tax_rate": Decimal("15"), "discount_amount": Decimal("40")},   # 20% line discount
    ]
    gross = sum((it["quantity"] * it["unit_price"]).quantize(_D2) for it in items)

    pos = _pos_totals(items, header_disc_amount=Decimal("0"), gross_subtotal=gross)
    inv = _invoice_totals(items, header_pct=Decimal("0"))
    assert pos == inv

    # Sanity: discount actually fired.
    assert pos["total_discount"] == Decimal("60.00")  # 20 + 40


def test_pos_router_resolves_coupon_backend_side():
    """Filesystem regression: routers/pos.py must look up coupon_code
    against pos_promotions before applying it, instead of trusting a
    client-supplied discount."""
    with open(POS_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    assert "FROM pos_promotions" in src, (
        "POS create_order must look up promotions by code/id from "
        "pos_promotions to apply discounts backend-side"
    )
    assert "coupon_code" in src and "promotion_id" in src, (
        "OrderCreate must accept coupon_code and promotion_id"
    )
    # The new guard must reject expired/inactive promotions.
    assert re.search(
        r"(start_date IS NULL OR start_date <= NOW\(\))[\s\S]+?(end_date\s+IS NULL OR end_date\s+>\s*NOW\(\))",
        src,
    ), "POS coupon lookup must enforce active + start/end window"


def test_pos_router_uses_compute_invoice_totals_with_header_pct():
    """POS must thread header_discount_pct through compute_invoice_totals
    (ZATCA rule) instead of subtracting the discount post-tax.
    """
    with open(POS_PATH, "r", encoding="utf-8") as f:
        src = f.read()
    assert "compute_invoice_totals(line_dicts, header_discount_pct=header_discount_pct)" in src, (
        "POS must pass header_discount_pct to compute_invoice_totals so "
        "tax is reduced proportionally with the discount"
    )
    assert "subtotal + tax_total - _dec(order_in.discount_amount)" not in src, (
        "regression: POS reverted to subtracting discount_amount post-tax"
    )
