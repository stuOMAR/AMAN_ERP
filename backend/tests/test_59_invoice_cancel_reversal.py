"""T3.8 — Sales-invoice cancellation must reverse inventory + JE precisely.

Scope:
- The cancel flow looks up the originating ``journal_entries`` row by
  ``(source, source_id)`` rather than the mutable ``reference`` column
  (audit gap T3.8). The ``reference`` column can be edited or duplicated
  across reposts, so the cancel must use the immutable source pair.
- If the invoice has product lines, ``inventory_transactions`` must
  contain matching rows; otherwise the cancel raises a clear 400 error
  instead of silently leaving inventory unchanged.

These are filesystem regressions: they pin the contract on the cancel
handler so the next refactor cannot quietly revert to the old behaviour.
A live HTTP integration test is intentionally out of scope here — it
already exists in ``tests/test_11_sales_scenarios.py`` /
``tests/test_27_sales_advanced.py`` and would need a fully provisioned
sales fixture chain.
"""

from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

INVOICES_PATH = os.path.join(ROOT, "routers", "sales", "invoices.py")


def _read() -> str:
    with open(INVOICES_PATH, "r", encoding="utf-8") as f:
        return f.read()


def test_cancel_uses_source_source_id_for_je_lookup():
    """The cancel handler must locate the JE by source/source_id."""
    src = _read()
    # New, correct lookup must be present.
    assert re.search(
        r"FROM\s+journal_entries\s+WHERE\s+source\s*=\s*'Sales-Invoice'\s+AND\s+source_id\s*=\s*:inv_id",
        src,
        re.IGNORECASE,
    ), "cancel_invoice must look up journal_entries by (source, source_id)"

    # Old, mutable-key lookup must NOT come back.
    assert "FROM journal_entries WHERE reference = :ref" not in src, (
        "regression: cancel_invoice fell back to looking up the JE by "
        "reference (mutable). Use source='Sales-Invoice' + source_id."
    )


def test_cancel_requires_inventory_transactions_when_lines_have_products():
    """Cancelling a product invoice without inventory_transactions errors."""
    src = _read()
    assert re.search(
        r"COUNT\(\*\)\s+FROM\s+inventory_transactions\s+WHERE\s+reference_type\s*=\s*'invoice'\s+AND\s+reference_id\s*=\s*:inv_id",
        src,
        re.IGNORECASE,
    ), (
        "cancel_invoice must verify inventory_transactions exist before "
        "reversing inventory for product lines"
    )
    assert "لا توجد حركات مخزون مرتبطة بهذه الفاتورة" in src, (
        "cancel_invoice must raise a clear Arabic error when no "
        "inventory_transactions back the invoice's product lines"
    )
    assert "status_code=400" in src, (
        "missing inventory_transactions must surface as HTTP 400, not 500"
    )


def test_cancel_handler_skips_inventory_when_no_product_lines():
    """A pure-service invoice (no product_id rows) should still cancel."""
    src = _read()
    # The presence check is gated on product_lines being non-empty.
    assert re.search(
        r"product_lines\s*=\s*\[ln\s+for\s+ln\s+in\s+inv_lines\s+if\s+ln\.product_id\]",
        src,
    ), (
        "cancel_invoice must only enforce the inventory-presence check "
        "when at least one invoice line carries a product_id"
    )
    assert "if product_lines:" in src, (
        "the inventory-presence guard must be conditional on product_lines"
    )
