"""Audit PR 9 — POST /api/expenses/validate-policy must carry a BE
permission gate matching the FE (`expenses.create`).

Closes F-NEW-014. Static-source check on the expenses router.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPENSES_PY = REPO_ROOT / "backend/routers/finance/expenses.py"


def test_validate_policy_route_has_require_permission():
    src = EXPENSES_PY.read_text(encoding="utf-8")
    # Locate the decorator block that immediately precedes
    # ``def validate_expense_against_policy``.
    needle = "def validate_expense_against_policy("
    idx = src.find(needle)
    assert idx >= 0, "validate_expense_against_policy not found"

    # Walk backwards to the @router.post line covering this handler.
    head = src[:idx]
    deco_idx = head.rfind("@router.post(")
    assert deco_idx >= 0, "no @router.post decorator above validate-policy handler"

    decorator_block = src[deco_idx:idx]
    assert "/validate-policy" in decorator_block, (
        "decorator block does not match /validate-policy"
    )
    assert 'require_permission("expenses.create")' in decorator_block, (
        "F-NEW-014: /validate-policy must require expenses.create on the BE."
    )
