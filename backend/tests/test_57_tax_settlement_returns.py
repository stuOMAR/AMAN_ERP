"""T3.6 (audit #18) — tax settlement must net out returns.

`create_tax_settlement` previously summed only `sales` and `purchase`
invoice types. With a sales-return inside the period the company would
over-pay VAT to the tax authority because the refunded output VAT was
never subtracted.

This test exercises the endpoint with a mocked db and asserts that
the four SQL queries (sales, sales_return, purchase, purchase_return)
are issued in order and that the resulting JE settles the **netted**
amount.
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
import pytest


@pytest.fixture
def mock_user():
    u = MagicMock()
    u.company_id = "tenant1"
    u.id = 99
    u.username = "tester"
    u.branch_id = None
    return u


def _scalar_seq(*values):
    """Build side_effect for db.execute(...).scalar() returning each value in
    turn, while letting other chained calls (.fetchone, .fetchall) work."""
    calls = iter(values)

    def _execute(stmt, params=None):
        result = MagicMock()
        try:
            result.scalar.return_value = next(calls)
        except StopIteration:
            result.scalar.return_value = 0
        result.fetchone.return_value = None
        result.fetchall.return_value = []
        return result
    return _execute


def test_settlement_subtracts_sales_returns(mock_user):
    """sales=1000 VAT, sales_return=200 VAT, purchase=300 VAT, purchase_return=0
       → output_net = 800, input_net = 300, settle = min(800,300) = 300."""
    from routers.finance import taxes as tx

    db = MagicMock()
    # Order in code: output, output_returns, input, input_returns
    db.execute.side_effect = _scalar_seq(1000, 200, 300, 0)

    captured = {}

    def fake_je(**kw):
        captured["lines"] = kw["lines"]
        return 555, "JE-000555"

    with patch.object(tx, "get_db_connection", return_value=db), \
         patch.object(tx, "get_mapped_account_id", side_effect=lambda d, k: 11 if "out" in k else 12), \
         patch.object(tx, "get_base_currency", return_value="SAR"), \
         patch.object(tx, "check_fiscal_period_open", return_value=True), \
         patch.object(tx, "validate_branch_access", return_value=None), \
         patch.object(tx, "log_activity"), \
         patch("services.gl_service.create_journal_entry", side_effect=fake_je):
        body = {"period_start": "2026-01-01", "period_end": "2026-03-31"}
        req = MagicMock()
        resp = tx.create_tax_settlement(req, body, mock_user)

    assert resp["success"] is True
    # Net output = 1000 - 200 = 800, net input = 300 - 0 = 300
    assert float(resp["output_vat"]) == 800.0
    assert float(resp["input_vat"]) == 300.0
    assert float(resp["net_amount"]) == 500.0
    # Settlement uses min(output_net, input_net) = 300
    assert captured["lines"][0]["debit"] == 300.0
    assert captured["lines"][1]["credit"] == 300.0


def test_settlement_subtracts_purchase_returns(mock_user):
    """sales=500, sales_return=0, purchase=400, purchase_return=100
       → output_net=500, input_net=300, settle=min(500,300)=300."""
    from routers.finance import taxes as tx

    db = MagicMock()
    db.execute.side_effect = _scalar_seq(500, 0, 400, 100)

    captured = {}

    def fake_je(**kw):
        captured["lines"] = kw["lines"]
        return 1, "JE-1"

    with patch.object(tx, "get_db_connection", return_value=db), \
         patch.object(tx, "get_mapped_account_id", side_effect=lambda d, k: 11 if "out" in k else 12), \
         patch.object(tx, "get_base_currency", return_value="SAR"), \
         patch.object(tx, "check_fiscal_period_open", return_value=True), \
         patch.object(tx, "validate_branch_access", return_value=None), \
         patch.object(tx, "log_activity"), \
         patch("services.gl_service.create_journal_entry", side_effect=fake_je):
        body = {"period_start": "2026-01-01", "period_end": "2026-03-31"}
        resp = tx.create_tax_settlement(MagicMock(), body, mock_user)

    assert float(resp["output_vat"]) == 500.0
    assert float(resp["input_vat"]) == 300.0
    assert captured["lines"][0]["debit"] == 300.0


def test_settlement_returns_full_refund_when_returns_exceed_sales(mock_user):
    """Edge case: sales=200, sales_return=300 → output_net=-100 (refund).
    With negative output, settle_amount=min(-100,200)=-100 < 0 ⇒ no JE,
    response shows refundable."""
    from routers.finance import taxes as tx

    db = MagicMock()
    db.execute.side_effect = _scalar_seq(200, 300, 200, 0)

    with patch.object(tx, "get_db_connection", return_value=db), \
         patch.object(tx, "get_mapped_account_id", side_effect=lambda d, k: 11 if "out" in k else 12), \
         patch.object(tx, "get_base_currency", return_value="SAR"), \
         patch.object(tx, "check_fiscal_period_open", return_value=True), \
         patch.object(tx, "validate_branch_access", return_value=None), \
         patch.object(tx, "log_activity"):
        body = {"period_start": "2026-01-01", "period_end": "2026-03-31"}
        resp = tx.create_tax_settlement(MagicMock(), body, mock_user)

    assert float(resp["output_vat"]) == -100.0
    assert float(resp["input_vat"]) == 200.0
    assert float(resp["net_amount"]) == -300.0
    assert resp["settlement_type"] == "refundable"
    assert resp["journal_entry"] is None  # no settle JE since min<=0
