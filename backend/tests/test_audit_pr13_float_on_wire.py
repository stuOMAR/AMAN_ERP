"""Audit PR 13 (Batch 13) — Float-on-wire Pydantic schemas.

Closes:

* F-NEW-036 — backend/routers/finance/accounting/core.py:243 ProvisionRequest.amount
              (and the sibling ``FXRevaluationRequest.new_rate`` flagged on the
              same hunk) — both monetary axes were typed ``float``.
* F-NEW-125 — backend/routers/finance/notes.py:33  NoteReceivableCreate.amount
              (and the sibling ``exchange_rate``).
* F-NEW-127 — backend/routers/finance/notes.py:50  NotePayableCreate.amount
              (and the sibling ``exchange_rate``).

The audit's R-FLOAT-ON-WIRE rule (Req 8.8) requires Pydantic schemas on
the wire to preserve fiscal precision, so the field type must be
``Decimal`` (or stringified Decimal) with a json_encoders bridge.
"""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_PY = REPO_ROOT / "backend/routers/finance/accounting/core.py"
NOTES_PY = REPO_ROOT / "backend/routers/finance/notes.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _slice(src: str, anchor: str, lines: int = 25) -> str:
    idx = src.find(anchor)
    assert idx >= 0, f"anchor not found: {anchor}"
    return "\n".join(src[idx:].splitlines()[:lines])


# ── F-NEW-036 — ProvisionRequest / FXRevaluationRequest ────────────────────


def test_provision_request_amount_is_decimal():
    body = _slice(_read(CORE_PY), "class ProvisionRequest(BaseModel):", lines=15)
    assert re.search(r"^\s*amount:\s*Decimal\s*$", body, re.M), (
        "F-NEW-036: ProvisionRequest.amount must be Decimal."
    )
    assert "json_encoders" in body and "Decimal: str" in body, (
        "F-NEW-036: ProvisionRequest must declare a Decimal→str encoder so "
        "the response wire shape preserves fiscal precision."
    )
    # Defensive: no `: float` in the same block.
    assert ": float" not in body, "F-NEW-036: stray float type in ProvisionRequest."


def test_fx_revaluation_request_new_rate_is_decimal():
    body = _slice(_read(CORE_PY), "class FXRevaluationRequest(BaseModel):", lines=15)
    assert re.search(r"^\s*new_rate:\s*Decimal\s*$", body, re.M), (
        "F-NEW-036 (sibling): FXRevaluationRequest.new_rate must be Decimal."
    )
    assert "json_encoders" in body and "Decimal: str" in body


# ── F-NEW-125 — NoteReceivableCreate ──────────────────────────────────────


def test_note_receivable_create_money_fields_are_decimal():
    body = _slice(_read(NOTES_PY), "class NoteReceivableCreate(BaseModel):", lines=25)
    assert re.search(r"^\s*amount:\s*Decimal\s*$", body, re.M), (
        "F-NEW-125: NoteReceivableCreate.amount must be Decimal."
    )
    assert re.search(r"exchange_rate:\s*Optional\[Decimal\]", body), (
        "F-NEW-125: NoteReceivableCreate.exchange_rate must be Decimal."
    )
    assert "json_encoders" in body and "Decimal: str" in body
    assert ": float" not in body, "F-NEW-125: stray float type in NoteReceivableCreate."


# ── F-NEW-127 — NotePayableCreate ─────────────────────────────────────────


def test_note_payable_create_money_fields_are_decimal():
    body = _slice(_read(NOTES_PY), "class NotePayableCreate(BaseModel):", lines=25)
    assert re.search(r"^\s*amount:\s*Decimal\s*$", body, re.M), (
        "F-NEW-127: NotePayableCreate.amount must be Decimal."
    )
    assert re.search(r"exchange_rate:\s*Optional\[Decimal\]", body), (
        "F-NEW-127: NotePayableCreate.exchange_rate must be Decimal."
    )
    assert "json_encoders" in body and "Decimal: str" in body
    assert ": float" not in body, "F-NEW-127: stray float type in NotePayableCreate."


# ── Behavioural check: the schemas actually accept Decimal cleanly ────────


def test_schemas_validate_decimal_inputs():
    """Smoke-test: instantiating the schemas with Decimal inputs must
    succeed and round-trip the value as Decimal (not float)."""
    from routers.finance.accounting.core import (
        ProvisionRequest,
        FXRevaluationRequest,
    )
    from routers.finance.notes import NoteReceivableCreate, NotePayableCreate

    p = ProvisionRequest(amount=Decimal("123.45"))
    assert isinstance(p.amount, Decimal)
    assert str(p.amount) == "123.45"

    fx = FXRevaluationRequest(currency_code="USD", new_rate=Decimal("3.7500"))
    assert isinstance(fx.new_rate, Decimal)

    nr = NoteReceivableCreate(
        note_number="N-1",
        amount=Decimal("999.99"),
        due_date="2026-12-31",
    )
    assert isinstance(nr.amount, Decimal)
    assert isinstance(nr.exchange_rate, Decimal)

    np_ = NotePayableCreate(
        note_number="P-1",
        amount=Decimal("1000.00"),
        due_date="2026-12-31",
    )
    assert isinstance(np_.amount, Decimal)
