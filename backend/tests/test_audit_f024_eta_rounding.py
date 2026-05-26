"""Regression test for F-NEW-024 (R-NON-HALF-UP-ROUND).

Ensures that ``backend/integrations/einvoicing/eta_adapter.py`` does NOT use
Python's built-in ``round(x, n)`` on monetary values. The built-in ``round``
uses banker's rounding (ROUND_HALF_EVEN) which is incompatible with the
Decimal_Money_Rule (Req 4.7) that mandates ROUND_HALF_UP.

The fix (PR16) replaced all ``round(x, n)`` calls with helpers from
``utils.tax_precision`` (q_money, q_rate, q_qty) which use
``Decimal.quantize(..., ROUND_HALF_UP)``.
"""
from __future__ import annotations

import re
from pathlib import Path


_BACKEND = Path(__file__).resolve().parent.parent
_ETA_ADAPTER = _BACKEND / "integrations" / "einvoicing" / "eta_adapter.py"


def _read_source() -> str:
    return _ETA_ADAPTER.read_text(encoding="utf-8")


class TestNoBuiltinRound:
    """F-NEW-024: no ``round(x, n)`` anywhere in eta_adapter.py."""

    def test_no_round_call_in_source(self):
        """The file must not contain any call to Python's built-in round()."""
        body = _read_source()
        # Strip comments so narrative references to round() don't false-positive
        lines = [
            ln for ln in body.splitlines()
            if not ln.lstrip().startswith("#")
        ]
        code_only = "\n".join(lines)
        # Match round( with optional whitespace — but NOT "ROUND_HALF_UP" etc.
        matches = re.findall(r'\bround\s*\(', code_only)
        assert not matches, (
            f"F-NEW-024: eta_adapter.py must not use built-in round(). "
            f"Found {len(matches)} occurrence(s). Use q_money/q_rate/q_qty from "
            f"utils.tax_precision instead."
        )

    def test_tax_precision_imported(self):
        """The file must import from utils.tax_precision."""
        body = _read_source()
        assert "from utils.tax_precision import" in body, (
            "F-NEW-024: eta_adapter.py must import helpers from utils.tax_precision"
        )

    def test_q_money_used(self):
        """q_money must be used for monetary quantization."""
        body = _read_source()
        assert "q_money" in body

    def test_q_rate_used(self):
        """q_rate must be used for rate quantization."""
        body = _read_source()
        assert "q_rate" in body


class TestRoundingBehavior:
    """Verify that the ETA builder produces ROUND_HALF_UP results."""

    def test_banker_rounding_trap(self):
        """Decimal('1.005') must round to '1.01' (HALF_UP), not '1.00' (banker)."""
        from decimal import Decimal
        # Import the project's helper
        import sys
        sys.path.insert(0, str(_BACKEND))
        from utils.tax_precision import money_str
        # This is the classic banker's rounding trap
        assert money_str(Decimal("1.005")) == "1.01", (
            "money_str must use ROUND_HALF_UP: 1.005 → 1.01"
        )

    def test_half_up_on_tax_rate(self):
        """Rate '0.00005' must round to '0.0001' (HALF_UP)."""
        from decimal import Decimal
        import sys
        sys.path.insert(0, str(_BACKEND))
        from utils.tax_precision import rate_str
        assert rate_str(Decimal("0.00005")) == "0.0001"

    def test_eta_document_totals_are_deterministic(self):
        """build_eta_document must produce identical output for same Decimal input."""
        from decimal import Decimal
        import sys
        sys.path.insert(0, str(_BACKEND))
        from integrations.einvoicing.eta_adapter import build_eta_document

        invoice = {
            "invoice_number": "TEST-001",
            "issue_date": "2024-01-15T10:00:00Z",
            "customer_name": "Test Co",
            "customer_tax_id": "123456789",
            "currency": "EGP",
            "lines": [
                {
                    "description": "Widget",
                    "quantity": Decimal("3"),
                    "unit_price": Decimal("1.005"),
                    "tax_amount": Decimal("0.455"),
                    "tax_rate": Decimal("15.0"),
                },
            ],
        }
        doc1 = build_eta_document(
            invoice, issuer_id="I1", issuer_name="Seller", activity_code="1234"
        )
        doc2 = build_eta_document(
            invoice, issuer_id="I1", issuer_name="Seller", activity_code="1234"
        )
        # Deterministic: same input → same output
        assert doc1 == doc2
        # HALF_UP: 1.005 → 1.01 (not 1.00 banker)
        line = doc1["invoiceLines"][0]
        assert line["unitValue"]["amountEGP"] == "1.01"
        # tax_amount 0.455 → 0.46 (HALF_UP)
        assert line["taxableItems"][0]["amount"] == "0.46"
