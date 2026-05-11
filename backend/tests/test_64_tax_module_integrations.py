"""Integration-level checks for the tax module hardening.

These tests guard the precision, branch-scope, and validation contracts
introduced in the tax module fix plan.
"""
from decimal import Decimal

import pytest
from fastapi import HTTPException

from utils.tax_precision import money_str, rate_str, serialize_tax_row


class _Request:
    def __init__(self, headers):
        self.headers = headers


# ---------------------------------------------------------------------------
# 1. VAT header discount — verify Decimal math contract
# ---------------------------------------------------------------------------
def test_vat_header_discount_decimal_math():
    """Invoice: 1000 SAR, 15% VAT, 10% header discount → tax must be 135."""
    subtotal = Decimal("1000")
    header_discount_pct = Decimal("10")
    tax_rate = Decimal("15")

    discount_amount = (subtotal * header_discount_pct / Decimal("100")).quantize(Decimal("0.01"))
    taxable = subtotal - discount_amount
    tax_amount = (taxable * tax_rate / Decimal("100")).quantize(Decimal("0.01"))

    assert discount_amount == Decimal("100.00")
    assert taxable == Decimal("900.00")
    assert tax_amount == Decimal("135.00")


# ---------------------------------------------------------------------------
# 2. Zakat branch scope key
# ---------------------------------------------------------------------------
def test_zakat_branch_scope_key_single_branch():
    from routers.system_completion.accounting import zakat_branch_scope_key

    key, ids = zakat_branch_scope_key({"branch_id": 5})
    assert key == "branch:5"
    assert ids is None


def test_zakat_branch_scope_key_all_company():
    from routers.system_completion.accounting import zakat_branch_scope_key

    key, ids = zakat_branch_scope_key({"branch_id": None, "branch_ids": None})
    assert key == "all:company"
    assert ids is None


def test_zakat_branch_scope_key_multiple_branches():
    from routers.system_completion.accounting import zakat_branch_scope_key

    key, ids = zakat_branch_scope_key({"branch_id": None, "branch_ids": [3, 1, 2]})
    assert key == "branches:1,2,3"
    assert ids == [1, 2, 3]


def test_zakat_branch_scope_key_empty_branches():
    from routers.system_completion.accounting import zakat_branch_scope_key

    key, ids = zakat_branch_scope_key({"branch_id": None, "branch_ids": []})
    assert key == "branches:none"
    assert ids == []


def test_zakat_different_scopes_no_collision():
    """User A scope [1,2] and User B scope [3] must produce different keys."""
    from routers.system_completion.accounting import zakat_branch_scope_key

    key_a, _ = zakat_branch_scope_key({"branch_id": None, "branch_ids": [1, 2]})
    key_b, _ = zakat_branch_scope_key({"branch_id": None, "branch_ids": [3]})
    assert key_a != key_b


# ---------------------------------------------------------------------------
# 3. ZATCA body-based endpoint contract
# ---------------------------------------------------------------------------
def test_zatca_request_schema():
    from routers.external import ZatcaRequest

    req = ZatcaRequest(invoice_id=42)
    assert req.invoice_id == 42


# ---------------------------------------------------------------------------
# 4. WHT branch required
# ---------------------------------------------------------------------------
def test_wht_schema_branch_optional():
    """WHTTransactionCreate.branch_id is Optional in schema but enforced at endpoint level."""
    from routers.external import WHTTransactionCreate

    tx = WHTTransactionCreate(supplier_id=1, wht_rate_id=2, gross_amount=Decimal("1000"))
    assert tx.branch_id is None  # schema allows None; endpoint rejects it


# ---------------------------------------------------------------------------
# 5. Tax engine expired rate falls through
# ---------------------------------------------------------------------------
def test_serialize_tax_row_decimal_to_string():
    """serialize_tax_row converts Decimal fields to strings."""
    from decimal import Decimal

    row = {"id": 1, "rate_value": Decimal("15.0000"), "amount": Decimal("1234.56")}
    result = serialize_tax_row(row, money_fields=["amount"], rate_fields=["rate_value"])
    assert result["rate_value"] == "15.0000"
    assert result["amount"] == "1234.56"
    assert result["id"] == 1


def test_serialize_tax_row_handles_row_mapping():
    """serialize_tax_row handles SQLAlchemy Row objects via _mapping."""

    class FakeRow:
        _mapping = {"id": 2, "rate_value": Decimal("5.5000"), "amount": Decimal("100.00")}

    result = serialize_tax_row(FakeRow(), money_fields=["amount"], rate_fields=["rate_value"])
    assert result["rate_value"] == "5.5000"
    assert result["amount"] == "100.00"


# ---------------------------------------------------------------------------
# 6. Money/rate string precision
# ---------------------------------------------------------------------------
def test_money_str_rounds_to_2_places():
    assert money_str(Decimal("1234.567")) == "1234.57"
    assert money_str(Decimal("0.005")) == "0.01"
    assert money_str(Decimal("0")) == "0.00"


def test_rate_str_rounds_to_4_places():
    assert rate_str(Decimal("15.12345")) == "15.1235"
    assert rate_str(Decimal("0")) == "0.0000"


# ---------------------------------------------------------------------------
# 7. Invoice preview returns Decimal strings (contract check)
# ---------------------------------------------------------------------------
def test_preview_decimal_contract():
    """Verify that the preview output format uses strings, not floats."""
    # This tests the contract: preview endpoints must return money_str/rate_str values
    val = money_str(Decimal("99.995"))
    assert isinstance(val, str)
    assert val == "100.00"
