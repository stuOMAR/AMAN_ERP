"""Constitution checks for the hardened tax paths.

These tests stay intentionally small and fast: they guard the shared precision
helpers and the ZATCA formatting contract that tax endpoints rely on.
"""
from decimal import Decimal

import pytest
from fastapi import HTTPException

from utils.tax_precision import (
    CALCULATION_VERSION,
    get_idempotency_key,
    money_str,
    q_money,
    rate_str,
    require_idempotency_key,
)
from utils.zatca import build_zatca_tlv, compute_invoice_hash, decode_zatca_tlv


class _Request:
    def __init__(self, headers):
        self.headers = headers


def test_tax_money_and_rates_use_round_half_up_strings():
    assert q_money(Decimal("10.005")) == Decimal("10.01")
    assert money_str(Decimal("99.995")) == "100.00"
    assert rate_str(Decimal("2.577645")) == "2.5776"
    assert CALCULATION_VERSION == "tax-v1.1.0"


def test_idempotency_key_accepts_header_aliases_and_fallback():
    assert get_idempotency_key(_Request({"Idempotency-Key": " tax-123 "}), fallback="fallback") == "tax-123"
    assert get_idempotency_key(_Request({"X-Idempotency-Key": "tax-456"}), fallback="fallback") == "tax-456"
    assert get_idempotency_key(_Request({}), fallback="fallback") == "fallback"


def test_high_risk_tax_mutations_require_explicit_idempotency_key():
    assert require_idempotency_key(_Request({"Idempotency-Key": "tax-pay-1"}), operation="tax payment") == "tax-pay-1"
    with pytest.raises(HTTPException) as exc:
        require_idempotency_key(_Request({}), operation="tax payment")
    assert exc.value.status_code == 400
    assert "Idempotency-Key" in exc.value.detail


def test_zatca_hash_uses_decimal_money_formatting_not_binary_float_repr():
    h1 = compute_invoice_hash(
        invoice_number="INV-1",
        invoice_date="2026-05-09",
        total=Decimal("100.005"),
        vat=Decimal("15.005"),
        seller_vat="300000000000003",
    )
    h2 = compute_invoice_hash(
        invoice_number="INV-1",
        invoice_date="2026-05-09",
        total="100.01",
        vat="15.01",
        seller_vat="300000000000003",
    )
    assert h1 == h2


def test_zatca_tlv_amounts_are_serialized_as_money_strings():
    tlv = build_zatca_tlv(
        seller_name="AMAN",
        vat_number="300000000000003",
        timestamp="2026-05-09T00:00:00Z",
        total_with_vat=money_str("100.005"),
        vat_amount=money_str("15.005"),
    )
    decoded = decode_zatca_tlv(tlv)
    assert decoded[4] == "100.01"
    assert decoded[5] == "15.01"
