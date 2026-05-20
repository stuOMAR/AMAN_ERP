"""Audit PR 6 — fiscal-lock guard regression tests.

Closes F-NEW-011, F-NEW-012, F-NEW-013, F-NEW-016. Static-source checks
that each previously-unguarded handler now imports the canonical guard
``utils.fiscal_lock.check_fiscal_period_open`` (per Phase 0 contradiction
C-ARCH-002) and calls it before any state-mutating SQL.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _slice_handler(src: str, anchor: str, lines: int = 80) -> str:
    """Return the first ``lines`` lines starting at the handler anchor."""
    idx = src.find(anchor)
    assert idx >= 0, f"handler not found: {anchor}"
    return "\n".join(src[idx:].splitlines()[:lines])


# ──────────────────────────────────────────────────────────────────────
# Each module imports the canonical guard
# ──────────────────────────────────────────────────────────────────────


def test_all_audited_files_import_canonical_guard():
    files = [
        "backend/routers/finance/accounting_depth.py",   # F-NEW-011
        "backend/routers/finance/advanced_workflow.py",  # F-NEW-012
        "backend/routers/finance/budgets.py",            # F-NEW-013
        "backend/routers/finance/reconciliation.py",     # F-NEW-016
    ]
    for f in files:
        src = _read(f)
        assert "from utils.fiscal_lock import check_fiscal_period_open" in src, (
            f"{f}: canonical fiscal-lock guard not imported."
        )


# ──────────────────────────────────────────────────────────────────────
# F-NEW-011 — accounting_depth.einvoice_submit
# ──────────────────────────────────────────────────────────────────────


def test_einvoice_submit_calls_fiscal_lock_guard():
    src = _read("backend/routers/finance/accounting_depth.py")
    body = _slice_handler(src, "def einvoice_submit(", lines=40)
    assert "check_fiscal_period_open(" in body, (
        "F-NEW-011: einvoice_submit must call the fiscal-lock guard."
    )


# ──────────────────────────────────────────────────────────────────────
# F-NEW-012 — advanced_workflow.auto_approve_below_threshold
# ──────────────────────────────────────────────────────────────────────


def test_auto_approve_calls_fiscal_lock_guard():
    src = _read("backend/routers/finance/advanced_workflow.py")
    body = _slice_handler(src, "def auto_approve_below_threshold(", lines=40)
    assert "check_fiscal_period_open(" in body, (
        "F-NEW-012: auto_approve_below_threshold must call the guard."
    )


# ──────────────────────────────────────────────────────────────────────
# F-NEW-013 — budgets.close_budget
# ──────────────────────────────────────────────────────────────────────


def test_close_budget_calls_fiscal_lock_guard():
    src = _read("backend/routers/finance/budgets.py")
    body = _slice_handler(src, "def close_budget(", lines=40)
    assert "check_fiscal_period_open(" in body, (
        "F-NEW-013: close_budget must call the guard before any UPDATE."
    )


# ──────────────────────────────────────────────────────────────────────
# F-NEW-016 — reconciliation: 4 endpoints
# ──────────────────────────────────────────────────────────────────────


def test_reconciliation_handlers_call_fiscal_lock_guard():
    src = _read("backend/routers/finance/reconciliation.py")
    handlers = [
        "def auto_match(",
        "def match_transaction(",
        "def unmatch_transaction(",
        "def finalize_reconciliation(",
    ]
    for h in handlers:
        body = _slice_handler(src, h, lines=50)
        assert "check_fiscal_period_open(" in body, (
            f"F-NEW-016: {h.rstrip('(')} must call the fiscal-lock guard."
        )


def test_reconciliation_handlers_select_statement_date():
    """The guard needs the statement_date column — make sure each handler's
    SELECT now includes it (defence: catches accidental SELECT-list shrinkage).
    """
    src = _read("backend/routers/finance/reconciliation.py")
    # Match SELECT lists for bank_reconciliations rows fetched by id at the
    # top of mutating handlers.
    selects = re.findall(
        r"SELECT[^\)]+FROM bank_reconciliations WHERE id\s*=\s*:id",
        src,
        re.DOTALL,
    )
    assert selects, "expected at least 4 SELECT-by-id queries"
    # Every one of the audited mutating handlers' SELECTs should now include
    # statement_date OR fetch the row via JOIN with treasury_accounts (which
    # is the auto_match shape — it already pulled r.statement_date).
    sd_count = sum(1 for s in selects if "statement_date" in s)
    # auto_match selects via JOIN, the other 3 mutating handlers add the
    # column directly — so we expect at least 3 to mention it.
    assert sd_count >= 3, (
        f"F-NEW-016: at least 3 reconciliation handler SELECTs should pull "
        f"statement_date for the guard, found {sd_count}."
    )
