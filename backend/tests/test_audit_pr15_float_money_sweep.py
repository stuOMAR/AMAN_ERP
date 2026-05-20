"""Audit PR 15 (Batch 15) — Float→Decimal sweep on the High-tier R-FLOAT-MONEY files.

The audit's R-FLOAT-MONEY rule (Req 8.5) bans ``float()`` casts on
money/tax/exchange-rate/quantity axes. This batch closes the 16 High
findings:

* F-NEW-025  — backend/integrations/einvoicing/uae_fta_adapter.py
* F-NEW-054  — backend/routers/finance/assets/core.py
* F-NEW-055  — backend/routers/finance/assets/depreciation.py
* F-NEW-059  — backend/routers/finance/assets/leases.py
* F-NEW-063  — backend/routers/finance/assets/reports.py
* F-NEW-083  — backend/routers/finance/checks.py
* F-NEW-097  — backend/routers/finance/costing_policies.py
* F-NEW-098  — backend/routers/finance/currencies.py (compute_fx_revaluation_diff
                                                      switched to Decimal+HALF_UP)
* F-NEW-126  — backend/routers/finance/notes.py
* F-NEW-136  — backend/routers/finance/petty_cash.py
* F-NEW-139  — backend/routers/finance/reconciliation.py
* F-NEW-147  — backend/routers/finance/revenue_recognition.py
* F-NEW-151  — backend/routers/finance/subscriptions.py
* F-NEW-170  — backend/routers/reports/industry.py
* F-NEW-171  — backend/routers/reports/inventory.py
* F-NEW-172  — backend/routers/reports/sales.py

For each file we assert: zero ``float(`` casts remain on lines whose
context names them as money/tax/rate/qty (per the prompt's negative
test pattern from PR 3). Some files retain ``float(`` casts unrelated
to the money axis (e.g. ``float(timeout)`` on rate-limiter knobs);
those are intentionally allow-listed.
"""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


# Files cleared of all `float(` casts (every remaining `float(` is a
# false-positive on the money axis — there are none in these files).
FILES_FULLY_CLEAN = [
    "backend/routers/finance/assets/depreciation.py",
    "backend/routers/finance/assets/leases.py",
    "backend/routers/finance/assets/reports.py",
    "backend/routers/finance/checks.py",
    "backend/routers/finance/costing_policies.py",
    "backend/routers/finance/currencies.py",
    "backend/routers/finance/notes.py",
    "backend/routers/finance/petty_cash.py",
    "backend/routers/finance/reconciliation.py",
    "backend/routers/finance/revenue_recognition.py",
    "backend/routers/finance/subscriptions.py",
    "backend/routers/reports/industry.py",
    "backend/routers/reports/inventory.py",
    "backend/routers/reports/sales.py",
    "backend/integrations/einvoicing/uae_fta_adapter.py",
]


# Files where a single ``float(`` may remain on a non-money axis. We
# assert the *money-axis* lines are clean instead.
PARTIALLY_CLEAN = {
    "backend/routers/finance/assets/core.py": [
        # Line 489-491 specifically — F-NEW-054 anchor:
        ("acc_loss",   r"\bfloat\(nbv\)"),
        ("acc_fixed",  r"\bfloat\(nbv\)"),
    ],
}


# ── helpers ───────────────────────────────────────────────────────────────


_MONEY_LINE_RE = re.compile(
    r"\bfloat\([^)]*\)",
    re.IGNORECASE,
)
_MONEY_AXIS_RE = re.compile(
    r"(amount|debit|credit|rate|qty|quantity|total|price|tax|balance|cost|"
    r"profit|revenue|exchange|fc_balance|bc_balance|net_book_value|nbv|"
    r"depreciation|residual|outstanding|hours|planned|produced|scrapped|"
    r"unit_price|line_total|tax_total|grand_total|new_rate|fx)",
    re.IGNORECASE,
)


def _audit_file(rel: str) -> list[str]:
    """Return list of offending lines (1-indexed) where a ``float(`` cast
    is still present on a money-axis line."""
    p = REPO_ROOT / rel
    bad = []
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        if "float(" not in line:
            continue
        # If the surrounding line names a money/tax/rate/qty axis the cast
        # is a violation.
        if _MONEY_AXIS_RE.search(line):
            bad.append(f"{rel}:{i}: {line.strip()}")
    return bad


# ── tests ────────────────────────────────────────────────────────────────


def test_fully_clean_files_have_no_money_axis_float_casts():
    """The 15 files in FILES_FULLY_CLEAN must contain zero ``float(``
    casts on money/tax/rate/qty lines after Batch 15.
    """
    offenders = []
    for rel in FILES_FULLY_CLEAN:
        offenders.extend(_audit_file(rel))
    assert not offenders, (
        "R-FLOAT-MONEY (Req 8.5): residual float() casts on money axis:\n"
        + "\n".join(offenders)
    )


def test_assets_core_money_lines_are_decimal():
    """F-NEW-054 — assets/core.py:489,491 — the asset-return write-down
    JE lines must pass Decimal (via ``_dec``) into gl_service rather
    than ``float(nbv)``.
    """
    rel = "backend/routers/finance/assets/core.py"
    src = (REPO_ROOT / rel).read_text(encoding="utf-8")
    idx = src.find('"description": "Loss on asset return"')
    assert idx >= 0, "anchor missing"
    block = src[max(0, idx - 400):idx + 200]
    assert "float(nbv)" not in block, (
        "F-NEW-054: Asset return JE must not float()-cast nbv."
    )
    assert "_dec(nbv)" in block, (
        "F-NEW-054: Asset return JE must pass _dec(nbv) into gl_service."
    )


# ── F-NEW-098: compute_fx_revaluation_diff is Decimal-correct ─────────────


def test_compute_fx_revaluation_diff_uses_decimal():
    """F-NEW-098: the helper must return Decimal-typed diff/target_bc
    so downstream JE construction never demotes through float."""
    from routers.finance.currencies import compute_fx_revaluation_diff

    r = compute_fx_revaluation_diff(
        fc_balance=Decimal("100"),
        bc_balance=Decimal("100"),
        new_rate=Decimal("1.10"),
        account_type="asset",
    )
    assert isinstance(r["diff"], Decimal)
    assert isinstance(r["target_bc"], Decimal)
    assert r["target_bc"] == Decimal("110.0000")
    assert r["diff"] == Decimal("10.0000")
    assert r["side"] == "gain"


def test_compute_fx_revaluation_diff_round_half_up():
    """F-NEW-098: ROUND_HALF_UP semantics, not banker's rounding.

    Differential test: ``100 × 1.0000025 = 100.00025`` quantized to 4dp:

      * HALF_UP   → ``100.0003`` (the legacy ``round()`` would give this)
      * HALF_EVEN → ``100.0002``

    The audit's R-FLOAT-MONEY rule mandates ROUND_HALF_UP for fiscal
    rounding. The helper must therefore return ``100.0003``.
    """
    from routers.finance.currencies import compute_fx_revaluation_diff

    r = compute_fx_revaluation_diff(
        fc_balance=Decimal("100"),
        bc_balance=Decimal("0"),
        new_rate=Decimal("1.0000025"),
        account_type="asset",
    )
    assert r["target_bc"] == Decimal("100.0003"), (
        f"F-NEW-098: expected ROUND_HALF_UP at 4dp = 100.0003, "
        f"got {r['target_bc']!r}"
    )


# ── F-NEW-025: uae_fta_adapter renders Decimal via tax_precision ──────────


def test_uae_fta_adapter_uses_tax_precision_helpers():
    rel = "backend/integrations/einvoicing/uae_fta_adapter.py"
    src = (REPO_ROOT / rel).read_text(encoding="utf-8")
    assert "from utils.tax_precision import" in src
    for sym in ("money_str", "qty_str", "q_money", "q_qty", "q_rate"):
        assert sym in src, (
            f"F-NEW-025: uae_fta_adapter must import {sym} from tax_precision."
        )
    # And no float(...) casts on the money axis remain.
    assert not _audit_file(rel), (
        "F-NEW-025: residual float() on money axis in uae_fta_adapter."
    )


# ── F-NEW-098: smoke-test the FX revaluation diff helper still
# returns the correct gain/loss direction (regression for audit #16) ───────


def test_fx_revaluation_decimal_smoke():
    from routers.finance.currencies import compute_fx_revaluation_diff

    # Asset, rate up → gain.
    r = compute_fx_revaluation_diff(100.0, 100.0, 1.1, account_type="asset")
    assert r["side"] == "gain"
    # Liability, rate up → loss.
    r = compute_fx_revaluation_diff(-100.0, -100.0, 1.1, account_type="liability")
    assert r["side"] == "loss"
