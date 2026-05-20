"""Audit PR 7 — petty_cash must call recalc_treasury_from_gl after JE post.

Closes F-NEW-015. Static-source check that both petty-cash money paths
(replenish + disburse) recompute the linked treasury_account balance from
the GL after a JE landed, preserving Treasury_Balance ≡ Cash/Bank GL
parity (Req 5.2 / Req 8.8).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PETTY_PY = REPO_ROOT / "backend/routers/finance/petty_cash.py"


def _slice(src: str, anchor: str, lines: int = 70) -> str:
    idx = src.find(anchor)
    assert idx >= 0, f"anchor not found: {anchor}"
    return "\n".join(src[idx:].splitlines()[:lines])


def test_petty_cash_module_imports_recalc():
    src = PETTY_PY.read_text(encoding="utf-8")
    assert "from utils.treasury_balance import recalc_treasury_from_gl" in src, (
        "F-NEW-015: petty_cash must import the canonical treasury-recompute helper."
    )


def test_replenish_fund_calls_recalc_after_je():
    src = PETTY_PY.read_text(encoding="utf-8")
    body = _slice(src, "def replenish_fund(", lines=60)
    assert "_post_je(" in body
    assert "recalc_treasury_from_gl(" in body, (
        "F-NEW-015: replenish_fund must recompute treasury balance after JE post."
    )
    # Order: recalc must come AFTER the JE post.
    je_idx = body.index("_post_je(")
    rec_idx = body.index("recalc_treasury_from_gl(")
    assert je_idx < rec_idx, (
        "F-NEW-015: recalc_treasury_from_gl must be called AFTER _post_je."
    )


def test_disburse_fund_calls_recalc_after_je():
    src = PETTY_PY.read_text(encoding="utf-8")
    body = _slice(src, "def disburse_fund(", lines=60)
    assert "_post_je(" in body
    assert "recalc_treasury_from_gl(" in body, (
        "F-NEW-015: disburse_fund must recompute treasury balance after JE post."
    )
    je_idx = body.index("_post_je(")
    rec_idx = body.index("recalc_treasury_from_gl(")
    assert je_idx < rec_idx


def test_petty_cash_no_direct_treasury_balance_update():
    """Defence-in-depth: petty_cash must NEVER do
    ``UPDATE treasury_accounts SET current_balance ...`` itself."""
    src = PETTY_PY.read_text(encoding="utf-8")
    bad = re.findall(
        r"UPDATE\s+treasury_accounts\s+SET\s+current_balance",
        src,
        re.IGNORECASE,
    )
    assert not bad, (
        "F-NEW-015: petty_cash must not directly UPDATE treasury_accounts.current_balance"
    )
