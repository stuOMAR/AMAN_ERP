"""Audit PR 11 (Batch 11) — Missing Idempotency.

Closes the 10 R-MISSING-IDEMPOTENCY High findings from the
finance/treasury/tax/zatca audit:

* F-NEW-041 / 043 / 044  — backend/routers/finance/accounting/journal.py
                            /post, /void, /reverse handlers.
* F-NEW-065              — backend/routers/finance/assets/transfers.py
                            POST /transfers.
* F-NEW-068              — backend/routers/finance/bank_feeds.py
                            POST /finance/bank-feeds/import.
* F-NEW-085              — backend/routers/finance/checks.py (6 endpoints)
                            + backend/routers/finance/notes.py (4 endpoints)
                            + backend/routers/finance/petty_cash.py
                              (replenish + disburse).
* F-NEW-116              — backend/routers/finance/expenses.py
                            POST /expenses/{id}/reverse.
* F-NEW-135              — backend/routers/finance/payments.py
                            POST /payments/{provider}/{charge_id}/refund.
* F-NEW-142              — backend/routers/finance/reconciliation.py
                            POST /{id}/auto-match, /{id}/match,
                            /{id}/finalize.
* F-NEW-162              — backend/routers/finance/treasury.py
                            POST /treasury/transactions/transfer.

The acceptance bar (Req 8.9) is "every sensitive POST that mutates state
either accepts an Idempotency-Key OR performs an explicit
``(source, source_id)`` dedup before posting via ``gl_service``." For
this batch we wired the Idempotency-Key header through every cited
handler and forwarded it to ``gl_service.create_journal_entry`` /
``gl_service.reverse_journal_entry`` (which already dedupe via the
``uq_je_idempotency`` partial unique index).

Static-grep regression assertions only — DB fixtures are not available
in this test environment, matching the rest of the
``test_audit_pr*`` family.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"

JOURNAL_PY        = BACKEND / "routers/finance/accounting/journal.py"
ASSETS_TRANSFERS  = BACKEND / "routers/finance/assets/transfers.py"
BANK_FEEDS_PY     = BACKEND / "routers/finance/bank_feeds.py"
CHECKS_PY         = BACKEND / "routers/finance/checks.py"
NOTES_PY          = BACKEND / "routers/finance/notes.py"
PETTY_CASH_PY     = BACKEND / "routers/finance/petty_cash.py"
EXPENSES_PY       = BACKEND / "routers/finance/expenses.py"
PAYMENTS_PY       = BACKEND / "routers/finance/payments.py"
RECON_PY          = BACKEND / "routers/finance/reconciliation.py"
TREASURY_PY       = BACKEND / "routers/finance/treasury.py"
GL_SERVICE_PY     = BACKEND / "services/gl_service.py"
IDEMPOTENCY_HELPER = BACKEND / "utils/idempotency.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _slice_handler(src: str, decorator_substring: str, lines: int = 200) -> str:
    """Return the handler body starting from a ``@router.post`` decorator
    that contains ``decorator_substring``.
    """
    idx = src.find(decorator_substring)
    assert idx >= 0, f"decorator anchor not found: {decorator_substring}"
    return "\n".join(src[idx:].splitlines()[:lines])


# ── helper module landed ─────────────────────────────────────────────────


def test_idempotency_helper_exists():
    """Batch 11 ships ``utils.idempotency`` with the three lookup helpers."""
    assert IDEMPOTENCY_HELPER.is_file()
    src = _read(IDEMPOTENCY_HELPER)
    assert "def find_je_by_idempotency_key" in src
    assert "def find_treasury_txn_by_idempotency_key" in src
    assert "def find_bank_statement_by_source_hash" in src


# ── F-NEW-041 / 043 / 044 — journal.py post / void / reverse ─────────────


def test_journal_post_accepts_idempotency_key():
    body = _slice_handler(_read(JOURNAL_PY), "/journal-entries/{entry_id}/post")
    assert 'request.headers.get("Idempotency-Key")' in body, (
        "F-NEW-041: /journal-entries/{id}/post must read Idempotency-Key."
    )
    assert "find_je_by_idempotency_key" in body, (
        "F-NEW-041: must dedup against journal_entries.idempotency_key."
    )


def test_journal_void_accepts_idempotency_key_and_forwards_to_gl_service():
    body = _slice_handler(_read(JOURNAL_PY), "/journal-entries/{entry_id}/void")
    assert 'request.headers.get("Idempotency-Key")' in body, (
        "F-NEW-043: /void must read Idempotency-Key from headers."
    )
    assert "idempotency_key=idempotency_key" in body, (
        "F-NEW-043: /void must forward the key into gl_create_journal_entry."
    )


def test_journal_reverse_accepts_idempotency_key_and_forwards():
    body = _slice_handler(_read(JOURNAL_PY), "/journal-entries/{entry_id}/reverse")
    assert 'request.headers.get("Idempotency-Key")' in body, (
        "F-NEW-044: /reverse must read Idempotency-Key from headers."
    )
    assert "idempotency_key=idempotency_key" in body, (
        "F-NEW-044: /reverse must forward the key into gl_reverse_journal_entry."
    )


def test_gl_reverse_accepts_idempotency_key_argument():
    """gl_service.reverse_journal_entry must accept idempotency_key."""
    src = _read(GL_SERVICE_PY)
    sig_block = _slice_handler(src, "def reverse_journal_entry(", lines=40)
    assert "idempotency_key" in sig_block, (
        "F-NEW-044: gl_service.reverse_journal_entry must accept "
        "idempotency_key so the route handler can forward retries."
    )


# ── F-NEW-065 — assets/transfers.py POST /transfers ──────────────────────


def test_assets_transfer_dedups_pending_natural_key():
    """The POST /transfers handler must dedup on the natural key
    ``(asset_id, to_branch_id, status='pending')`` so a retried request
    returns the existing pending row instead of creating a second one.
    """
    src = _read(ASSETS_TRANSFERS)
    body = _slice_handler(src, '@router.post("/transfers"', lines=60)
    assert "F-NEW-065" in body, "transfers.py must cite the finding id"
    assert "status = 'pending'" in body and "asset_transfers" in body, (
        "F-NEW-065: must SELECT against asset_transfers WHERE status='pending'."
    )


# ── F-NEW-068 — bank_feeds.py POST /import ───────────────────────────────


def test_bank_feeds_import_computes_source_hash_and_dedups():
    src = _read(BANK_FEEDS_PY)
    assert "import hashlib" in src, (
        "F-NEW-068: bank_feeds.py must import hashlib for SHA-256 dedup."
    )
    body = _slice_handler(src, '@router.post(\n    "/import"', lines=200)
    assert "hashlib.sha256(" in body, (
        "F-NEW-068: must compute SHA-256 of the raw payload."
    )
    assert "find_bank_statement_by_source_hash" in body, (
        "F-NEW-068: must dedup against bank_statements.source_hash."
    )


def test_bank_feeds_insert_persists_source_hash():
    src = _read(BANK_FEEDS_PY)
    insert_body = _slice_handler(src, "def _insert_statement(", lines=30)
    assert "source_hash" in insert_body, (
        "F-NEW-068: _insert_statement must persist source_hash so retries "
        "can be deduped on subsequent calls."
    )


# ── F-NEW-085 — checks.py 6 endpoints ────────────────────────────────────


def _checks_anchor(decorator: str) -> str:
    return _slice_handler(_read(CHECKS_PY), decorator, lines=180)


def test_checks_collect_forwards_idempotency_key():
    body = _checks_anchor('"/receivable/{check_id}/collect"')
    assert 'request.headers.get("Idempotency-Key")' in body
    assert "idempotency_key=idempotency_key" in body


def test_checks_receivable_bounce_forwards_idempotency_key():
    body = _checks_anchor('"/receivable/{check_id}/bounce"')
    assert 'request.headers.get("Idempotency-Key")' in body
    # Both the cleared-path and pending-path must forward the key.
    assert body.count("idempotency_key=idempotency_key") >= 2


def test_checks_receivable_represent_forwards_idempotency_key():
    body = _checks_anchor('"/receivable/{check_id}/represent"')
    assert 'request.headers.get("Idempotency-Key")' in body
    assert "idempotency_key=idempotency_key" in body


def test_checks_payable_clear_forwards_idempotency_key():
    body = _checks_anchor('"/payable/{check_id}/clear"')
    assert 'request.headers.get("Idempotency-Key")' in body
    assert "idempotency_key=idempotency_key" in body


def test_checks_payable_bounce_forwards_idempotency_key():
    body = _checks_anchor('"/payable/{check_id}/bounce"')
    assert 'request.headers.get("Idempotency-Key")' in body
    assert body.count("idempotency_key=idempotency_key") >= 2


def test_checks_payable_represent_forwards_idempotency_key():
    body = _checks_anchor('"/payable/{check_id}/represent"')
    assert 'request.headers.get("Idempotency-Key")' in body
    assert "idempotency_key=idempotency_key" in body


# ── F-NEW-085 — notes.py 4 endpoints ─────────────────────────────────────


def _notes_anchor(decorator: str) -> str:
    return _slice_handler(_read(NOTES_PY), decorator, lines=120)


def test_notes_receivable_collect_forwards_idempotency_key():
    body = _notes_anchor('"/receivable/{note_id}/collect"')
    assert 'request.headers.get("Idempotency-Key")' in body
    assert "idempotency_key=idempotency_key" in body


def test_notes_receivable_protest_forwards_idempotency_key():
    body = _notes_anchor('"/receivable/{note_id}/protest"')
    assert 'request.headers.get("Idempotency-Key")' in body
    assert "idempotency_key=idempotency_key" in body


def test_notes_payable_pay_forwards_idempotency_key():
    body = _notes_anchor('"/payable/{note_id}/pay"')
    assert 'request.headers.get("Idempotency-Key")' in body
    assert "idempotency_key=idempotency_key" in body


def test_notes_payable_protest_forwards_idempotency_key():
    body = _notes_anchor('"/payable/{note_id}/protest"')
    assert 'request.headers.get("Idempotency-Key")' in body
    assert "idempotency_key=idempotency_key" in body


# ── F-NEW-085 — petty_cash.py replenish + disburse ───────────────────────


def test_petty_cash_replenish_forwards_idempotency_key():
    body = _slice_handler(
        _read(PETTY_CASH_PY), '/funds/{fund_id}/replenish', lines=80
    )
    assert 'request.headers.get("Idempotency-Key")' in body
    assert "idempotency_key=idempotency_key" in body


def test_petty_cash_disburse_forwards_idempotency_key():
    body = _slice_handler(
        _read(PETTY_CASH_PY), '/funds/{fund_id}/disburse', lines=80
    )
    assert 'request.headers.get("Idempotency-Key")' in body
    assert "idempotency_key=idempotency_key" in body


def test_petty_cash_post_je_helper_accepts_idempotency_key():
    body = _slice_handler(_read(PETTY_CASH_PY), "def _post_je(", lines=30)
    assert "idempotency_key" in body, (
        "_post_je helper must accept and forward idempotency_key."
    )


# ── F-NEW-116 — expenses.py /reverse ────────────────────────────────────


def test_expenses_reverse_forwards_idempotency_key():
    body = _slice_handler(_read(EXPENSES_PY), '"/{expense_id}/reverse"', lines=200)
    assert 'request.headers.get("Idempotency-Key")' in body, (
        "F-NEW-116: /expenses/{id}/reverse must read Idempotency-Key."
    )
    assert "idempotency_key=idempotency_key" in body, (
        "F-NEW-116: /reverse must forward the key into reverse_journal_entry."
    )


# ── F-NEW-135 — payments.py /refund ─────────────────────────────────────


def test_payments_refund_dedups_on_idempotency_key():
    src = _read(PAYMENTS_PY)
    body = _slice_handler(src, '"/{provider}/{charge_id}/refund"', lines=100)
    assert 'request.headers.get("Idempotency-Key")' in body, (
        "F-NEW-135: /payments/{provider}/{charge_id}/refund must read "
        "Idempotency-Key."
    )
    # Dedup against gateway_charges.idempotency_key.
    assert "idempotency_key" in body and "gateway_charges" in body, (
        "F-NEW-135: must SELECT against gateway_charges.idempotency_key."
    )


# ── F-NEW-142 — reconciliation.py three endpoints ────────────────────────


def test_recon_auto_match_acknowledges_idempotency_header():
    body = _slice_handler(_read(RECON_PY), '"/{id}/auto-match"', lines=40)
    assert 'request.headers.get("Idempotency-Key")' in body, (
        "F-NEW-142: /auto-match must read Idempotency-Key."
    )


def test_recon_match_acknowledges_idempotency_header():
    body = _slice_handler(_read(RECON_PY), '"/{id}/match"', lines=40)
    assert 'request.headers.get("Idempotency-Key")' in body, (
        "F-NEW-142: /match must read Idempotency-Key."
    )


def test_recon_finalize_acknowledges_idempotency_header_and_replays():
    body = _slice_handler(_read(RECON_PY), '"/{id}/finalize"', lines=80)
    assert 'request.headers.get("Idempotency-Key")' in body, (
        "F-NEW-142: /finalize must read Idempotency-Key."
    )
    # Replay path: when status='posted' and key supplied → return idempotent ok.
    assert "idempotent" in body, (
        "F-NEW-142: /finalize must surface idempotent replay."
    )


# ── F-NEW-162 — treasury.py /transactions/transfer ───────────────────────


def test_treasury_transfer_dedups_on_idempotency_key():
    body = _slice_handler(
        _read(TREASURY_PY), '"/transactions/transfer"', lines=200
    )
    assert 'request.headers.get("Idempotency-Key")' in body, (
        "F-NEW-162: /treasury/transactions/transfer must read "
        "Idempotency-Key from headers."
    )
    # Dedup against the Batch-10 column treasury_transactions.idempotency_key.
    assert (
        "FROM treasury_transactions" in body
        and "idempotency_key = :k" in body
    ), (
        "F-NEW-162: must SELECT FROM treasury_transactions WHERE "
        "idempotency_key = :k as the dedup pre-check."
    )
    assert "idempotency_key=idempotency_key" in body, (
        "F-NEW-162: transfer must forward the key into gl_create_journal_entry."
    )
    # Persist on the new INSERT too.
    assert "idempotency_key" in body and "INSERT INTO treasury_transactions" in body, (
        "F-NEW-162: the INSERT INTO treasury_transactions must persist "
        "idempotency_key for future replay."
    )
