"""T3.4 (audit #19) — single source of truth for JE validation.

After consolidation:
  - `services.gl_service.validate_je_lines` holds the pure invariants
    (≥1 line, no negatives, no debit+credit on same line, balanced).
  - `utils.accounting.prepare_je_lines` is the routing wrapper
    (None-account guard, drop zero lines, ≥2 lines, then delegates to
    `validate_je_lines`).

This test asserts (a) the wrapper delegates correctly so a single
implementation enforces balance everywhere, and (b) no router still
duplicates that math.
"""
import pathlib

import pytest
from fastapi import HTTPException

from services.gl_service import validate_je_lines
from utils.accounting import prepare_je_lines


def test_pure_validate_balances():
    d, c = validate_je_lines([
        {"account_id": 1, "debit": 100, "credit": 0},
        {"account_id": 2, "debit": 0, "credit": 100},
    ])
    assert d == c == 100


def test_pure_validate_rejects_unbalanced():
    with pytest.raises(HTTPException):
        validate_je_lines([
            {"account_id": 1, "debit": 100, "credit": 0},
            {"account_id": 2, "debit": 0, "credit": 80},
        ])


def test_prepare_drops_zero_lines_and_passes_to_validator():
    out = prepare_je_lines([
        {"account_id": 1, "debit": 100, "credit": 0, "description": "A"},
        {"account_id": 2, "debit": 0, "credit": 100, "description": "B"},
        {"account_id": 3, "debit": 0, "credit": 0, "description": "Z"},
    ])
    assert len(out) == 2


def test_prepare_rejects_none_account():
    with pytest.raises(HTTPException) as exc:
        prepare_je_lines([
            {"account_id": None, "debit": 100, "credit": 0, "description": "X"},
            {"account_id": 2, "debit": 0, "credit": 100},
        ])
    assert "غير معرفة" in str(exc.value.detail)


def test_prepare_rejects_unbalanced_via_delegate():
    with pytest.raises(HTTPException):
        prepare_je_lines([
            {"account_id": 1, "debit": 100, "credit": 0},
            {"account_id": 2, "debit": 0, "credit": 80},
        ])


def test_prepare_requires_two_lines():
    with pytest.raises(HTTPException) as exc:
        prepare_je_lines([
            {"account_id": 1, "debit": 100, "credit": 0},
        ])
    assert "سطرين" in str(exc.value.detail)


def test_only_one_validate_je_lines_definition_in_codebase():
    """Regression: there must be a single `def validate_je_lines` in
    backend/, located in services/gl_service.py."""
    backend = pathlib.Path(__file__).resolve().parents[1]
    hits = []
    for py in backend.rglob("*.py"):
        if "/.venv/" in str(py) or "/__pycache__/" in str(py):
            continue
        for ln, line in enumerate(py.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if line.lstrip().startswith("def validate_je_lines"):
                hits.append(f"{py.relative_to(backend)}:{ln}")
    assert hits == ["services/gl_service.py:20"], (
        f"Expected single definition in gl_service, got: {hits}"
    )
