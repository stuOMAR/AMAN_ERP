"""Audit PR 3 — verify zatca_adapter uses Decimal+ROUND_HALF_UP for all
monetary fields in QR TLV payload and UBL XML.

Closes F-NEW-005 (TLV) and F-NEW-006 (UBL). The contract under test is
that for any Decimal monetary input, the rendered string equals
``money_str(input)`` (i.e. quantized to 2 dp with HALF_UP, not banker's
rounding) — so the QR + UBL bytes always agree with the hash inputs.
"""
from __future__ import annotations

import base64
from decimal import Decimal
from datetime import datetime, timezone

import pytest

from integrations.einvoicing.zatca_adapter import build_qr_payload, build_ubl_xml
from utils.tax_precision import money_str, qty_str, q_money


# ──────────────────────────────────────────────────────────────────────
# QR (Tag 4 / Tag 5) — F-NEW-005
# ──────────────────────────────────────────────────────────────────────


def _decode_tlv(b64: str) -> dict[int, bytes]:
    raw = base64.b64decode(b64)
    out: dict[int, bytes] = {}
    i = 0
    while i < len(raw):
        tag = raw[i]
        length = raw[i + 1]
        out[tag] = raw[i + 2 : i + 2 + length]
        i += 2 + length
    return out


@pytest.mark.parametrize(
    "total,vat,expected_total,expected_vat",
    [
        (Decimal("100.00"), Decimal("15.00"), "100.00", "15.00"),
        # Banker's-rounding trap: 1.005 → 1.0 with banker, 1.01 with HALF_UP.
        (Decimal("1.005"), Decimal("0.155"), "1.01", "0.16"),
        # Float-precision trap: 0.1+0.2 binary float ≠ 0.30 string.
        (Decimal("0.30"), Decimal("0.045"), "0.30", "0.05"),
    ],
)
def test_qr_tlv_uses_half_up_money_str(total, vat, expected_total, expected_vat):
    b64 = build_qr_payload(
        seller_name="Acme",
        seller_vat="123456789012345",
        timestamp=datetime(2026, 5, 19, tzinfo=timezone.utc),
        total_with_vat=total,
        vat_amount=vat,
    )
    tlv = _decode_tlv(b64)
    assert tlv[4].decode() == expected_total
    assert tlv[5].decode() == expected_vat


def test_qr_payload_deterministic_across_decimal_inputs():
    """Two runs with identical Decimal inputs produce byte-equal output."""
    args = dict(
        seller_name="Acme",
        seller_vat="300000000000003",
        timestamp=datetime(2026, 5, 19, tzinfo=timezone.utc),
        total_with_vat=Decimal("999.99"),
        vat_amount=Decimal("130.43"),
    )
    a = build_qr_payload(**args)
    b = build_qr_payload(**args)
    assert a == b


# ──────────────────────────────────────────────────────────────────────
# UBL XML — F-NEW-006
# ──────────────────────────────────────────────────────────────────────


def _sample_invoice() -> dict:
    return {
        "invoice_number": "INV-1",
        "invoice_date": "2026-05-19",
        "invoice_time": "12:00:00",
        "currency": "SAR",
        "customer_name": "Buyer",
        "customer_vat": "300000000000111",
        "icv": 1,
        "subtotal": Decimal("100.00"),
        "tax_total": Decimal("15.00"),
        "grand_total": Decimal("115.00"),
        "lines": [
            {
                "description": "Widget",
                "quantity": Decimal("2"),
                "unit_price": Decimal("50.00"),
                "tax_rate": Decimal("15.00"),
                "line_total": Decimal("100.00"),
                "tax_amount": Decimal("15.00"),
            }
        ],
    }


def test_ubl_xml_uses_money_str_for_totals():
    xml = build_ubl_xml(_sample_invoice(), seller_name="Acme",
                        seller_vat="300000000000003", previous_invoice_hash="0")
    # Header totals
    assert ">100.00</cbc:TaxExclusiveAmount>" in xml
    assert ">115.00</cbc:TaxInclusiveAmount>" in xml
    assert ">115.00</cbc:PayableAmount>" in xml
    assert ">15.00</cbc:TaxAmount>" in xml  # appears at line + header
    # Line: quantity is 3-dp, monetary fields are 2-dp.
    assert ">2.000</cbc:InvoicedQuantity>" in xml
    assert ">50.00</cbc:PriceAmount>" in xml
    assert ">100.00</cbc:LineExtensionAmount>" in xml


def test_ubl_xml_byte_equal_for_identical_decimal_inputs():
    inv = _sample_invoice()
    a = build_ubl_xml(inv, seller_name="X", seller_vat="V", previous_invoice_hash="0")
    b = build_ubl_xml(inv, seller_name="X", seller_vat="V", previous_invoice_hash="0")
    assert a == b


def test_ubl_xml_no_float_casts_remain_at_runtime():
    """Regression test: feed dirty inputs that would expose binary-float
    drift if any ``float(...)`` cast slipped back into the builder.
    """
    inv = _sample_invoice()
    inv["lines"][0]["line_total"] = Decimal("0.1") + Decimal("0.2")  # = 0.3
    inv["subtotal"] = Decimal("0.1") + Decimal("0.2")
    inv["tax_total"] = Decimal("0.045")
    inv["grand_total"] = Decimal("0.345")
    xml = build_ubl_xml(inv, seller_name="X", seller_vat="V", previous_invoice_hash="0")
    # 0.3 → "0.30" with HALF_UP; 0.045 → "0.05".
    assert ">0.30</cbc:LineExtensionAmount>" in xml
    assert ">0.30</cbc:TaxExclusiveAmount>" in xml
    assert ">0.05</cbc:TaxAmount>" in xml
    # Float arithmetic 0.1+0.2 == 0.30000000000000004 must NOT appear.
    assert "0.30000000000000004" not in xml
