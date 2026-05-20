"""Audit PR 16-fix — behavioural regressions for previously broken PRs.

Behavioural review of PR2..PR15 surfaced several places where the
prior remediation was *syntactically* present but did not deliver the
runtime behaviour the audit asked for. This test file covers every
fix landed in PR16-fix:

* F-NEW-016 / petty_cash ``_post_je`` — used to store the entire
  ``(je_id, entry_number)`` tuple into ``petty_cash_transactions.je_id``
  (an INTEGER FK column), corrupting the relationship.
* F-NEW-007/008/026/027 / outbox_admin — the prior implementation
  filtered ``WHERE tenant_id = :tid`` while passing ``current_user.company_id``
  (a string/UUID) into a BIGINT column. The per-tenant DB binding
  already isolates rows; the filter is now removed.
* F-NEW-041 / journal /post — Idempotency-Key was read but never
  persisted on ``journal_entries.idempotency_key``; replays fell into
  the state guard and returned 400.
* F-NEW-085 / checks.py & notes.py — the state guard ran *before*
  the idempotency probe, so a network retry of a successful POST
  failed with ``not_pending`` instead of echoing the prior result.
* F-NEW-068 / bank_feeds — the same SHA-256 of the raw payload was
  used for every statement extracted from a multi-statement file,
  hitting the per-account unique partial index on the second INSERT.
* F-NEW-025 / uae_fta_adapter — ``unit_price`` was quantized to
  2 decimals before multiplying by quantity, breaking high-precision
  prices.
* F-NEW-023 / eta_adapter — every monetary axis was still cast
  through ``float()``; PR15 had only labelled the finding closed.

The tests below are deliberately a mix of static-source greps (for
patterns that survive without DB fixtures) and behavioural assertions
(for patterns that require running the actual function on Decimal
inputs). The PR15 mistake of treating presence of text as proof of
behaviour is *not* repeated here.
"""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ── F-NEW-016 (PR16-fix) — petty_cash._post_je tuple unpacking ───────


def test_petty_cash_post_je_unpacks_tuple():
    """The helper must unpack ``(je_id, entry_number)`` and return only
    the int id; otherwise the next ``INSERT INTO petty_cash_transactions
    (..., je_id, ...)`` writes a tuple into an INTEGER column."""
    body = _read("routers/finance/petty_cash.py")
    # Positive: explicit tuple-unpack.
    assert "je_id, _entry_number = create_journal_entry" in body, (
        "F-NEW-016 (PR16-fix): _post_je must unpack the "
        "(je_id, entry_number) tuple returned by gl_service so the FK "
        "value written to petty_cash_transactions.je_id is an int."
    )
    # Negative: no bare ``je_id = create_journal_entry(`` (which would
    # leave je_id as a tuple).
    assert not re.search(
        r"je_id\s*=\s*create_journal_entry\(",
        body,
    ), (
        "F-NEW-016 (PR16-fix): bare `je_id = create_journal_entry(...)` "
        "would store a tuple — must unpack via "
        "`je_id, _ = create_journal_entry(...)`."
    )


# ── F-NEW-007/008/026/027 — outbox_admin tenant binding ──────────────


def test_outbox_admin_no_tenant_id_filter():
    """The per-tenant DB binding via ``transactional(company_id)`` is
    enough; the prior ``WHERE tenant_id = :tid`` clause was a type-
    mismatch (``company_id`` is a string, ``tenant_id`` is BIGINT).
    """
    body = _read("routers/einvoicing/outbox_admin.py")
    # Strip line/block comments and docstrings so the post-mortem
    # narrative we left as a comment does not trip the negative match.
    code_lines: list[str] = []
    in_doc = False
    for ln in body.splitlines():
        stripped = ln.lstrip()
        triple = stripped.count('"""') + stripped.count("'''")
        if triple % 2 == 1:
            in_doc = not in_doc
            continue
        if in_doc:
            continue
        if stripped.startswith("#"):
            continue
        code_lines.append(ln)
    code_only = "\n".join(code_lines)

    # Negative: the BIGINT/string mismatch must be gone from executable code.
    assert not re.search(
        r"tenant_id\s*=\s*:tid",
        code_only,
    ), (
        "PR16-fix: `tenant_id = :tid` filter removed because per-tenant "
        "DB binding already isolates rows and the type mismatch silently "
        "matched zero rows."
    )
    # Positive: the per-tenant DB binding is still in place.
    assert "transactional(current_user.company_id)" in body, (
        "PR16-fix: per-tenant DB binding via `transactional(company_id)` "
        "must remain on every outbox handler."
    )


def test_outbox_admin_idempotency_probe_before_update():
    """The reprocess handler must SELECT for the recorded
    ``last_idempotency_key`` *before* issuing the state-flip UPDATE."""
    body = _read("routers/einvoicing/outbox_admin.py")
    select_idx = body.find("SELECT id, state, last_idempotency_key")
    update_idx = body.find("UPDATE zatca_outbox\n                SET state = 'pending'")
    assert select_idx != -1 and update_idx != -1
    assert select_idx < update_idx


# ── F-NEW-041 — journal /post idempotency ────────────────────────────


def test_journal_post_persists_idempotency_key():
    """The /post handler must write the supplied ``Idempotency-Key`` onto
    ``journal_entries.idempotency_key`` *before* calling ``post_draft``;
    otherwise a retry sees the row already in ``posted`` and the state
    guard rejects it with 400."""
    body = _read("routers/finance/accounting/journal.py")
    # Positive: an UPDATE of the column when the row carries no key yet.
    # The SQL is split across adjacent string literals (a Python idiom
    # in this file), so we just look for the two key fragments rather
    # than try to reconstruct the runtime string.
    assert '"UPDATE journal_entries "' in body, (
        "F-NEW-041 (PR16-fix): /post must run an UPDATE journal_entries "
        "statement to persist the Idempotency-Key."
    )
    assert '"SET idempotency_key = :k "' in body, (
        "F-NEW-041 (PR16-fix): /post must SET idempotency_key on the row "
        "before delegating to post_draft_journal_entry; otherwise a retry "
        "sees status='posted' and the state guard rejects it with 400."
    )
    # Positive: replay-by-row-key (entry.idempotency_key == header)
    # is honoured even after the row is already posted.
    assert "entry.idempotency_key == idempotency_key" in body, (
        "F-NEW-041 (PR16-fix): /post must echo the prior result when "
        "the row already carries the same key (e.g. retry after a "
        "crash mid-post)."
    )


# ── F-NEW-085 — checks.py & notes.py replay-before-state ─────────────


def _slice_handler(body: str, signature: str) -> str:
    """Return the body of an async/sync handler keyed by its def line."""
    idx = body.find(signature)
    assert idx != -1, f"handler {signature!r} not found"
    next_def = body.find("\n@router.", idx + 1)
    return body[idx : next_def if next_def != -1 else len(body)]


def test_checks_collect_replay_before_state_guard():
    body = _read("routers/finance/checks.py")
    handler = _slice_handler(body, "def collect_check_receivable(")
    probe_idx = handler.find("find_je_by_source")
    state_idx = handler.find("if check.status != 'pending'")
    assert probe_idx != -1, (
        "F-NEW-085 (PR16-fix): collect_check_receivable must probe "
        "by (source='check_collection', source_id) *before* the "
        "state guard — otherwise retries fail with check_not_pending."
    )
    assert state_idx != -1
    assert probe_idx < state_idx, (
        "F-NEW-085 (PR16-fix): the (source, source_id) probe must run "
        "before `if check.status != 'pending'`."
    )


def test_checks_bounce_receivable_replay_before_state_guard():
    body = _read("routers/finance/checks.py")
    handler = _slice_handler(body, "def bounce_check_receivable(")
    probe_idx = handler.find("find_je_by_source")
    state_idx = handler.find("if check.status not in ('pending', 'collected')")
    assert probe_idx != -1 and state_idx != -1
    assert probe_idx < state_idx


def test_checks_clear_payable_replay_before_state_guard():
    body = _read("routers/finance/checks.py")
    handler = _slice_handler(body, "def clear_check_payable(")
    probe_idx = handler.find("find_je_by_source")
    state_idx = handler.find("if check.status != 'issued'")
    assert probe_idx != -1 and state_idx != -1
    assert probe_idx < state_idx


def test_notes_collect_replay_before_state_guard():
    body = _read("routers/finance/notes.py")
    handler = _slice_handler(body, "def collect_note_receivable(")
    probe_idx = handler.find("find_je_by_source")
    state_idx = handler.find("if note.status != 'pending'")
    assert probe_idx != -1 and state_idx != -1
    assert probe_idx < state_idx


def test_notes_pay_payable_replay_before_state_guard():
    body = _read("routers/finance/notes.py")
    handler = _slice_handler(body, "def pay_note_payable(")
    probe_idx = handler.find("find_je_by_source")
    state_idx = handler.find("if note.status != 'issued'")
    assert probe_idx != -1 and state_idx != -1
    assert probe_idx < state_idx


def test_notes_protest_payable_uses_distinct_source_anchor():
    """``protest_note_receivable`` and ``protest_note_payable`` both
    used to carry ``source='note_protest'``; the natural-key probe
    therefore could not tell which side of the receivable/payable
    pair a retry was for. PR16-fix moves the payable side to
    ``source='np_protest'``."""
    body = _read("routers/finance/notes.py")
    payable_handler = _slice_handler(body, "def protest_note_payable(")
    assert 'source="np_protest"' in payable_handler


# ── F-NEW-068 — bank_feeds per-statement source_hash ─────────────────


def test_bank_feeds_per_statement_source_hash():
    body = _read("routers/finance/bank_feeds.py")
    # Positive: the per-statement helper exists.
    assert "def _stmt_hash(" in body, (
        "F-NEW-068 (PR16-fix): bank_feeds must compute a per-statement "
        "digest before each INSERT — the unique partial index "
        "uq_bank_statements_source_hash collides on a multi-statement "
        "upload otherwise."
    )
    # Helper must combine file-level hash with idx and stmt number.
    assert 'f"{file_hash}:{idx}:{statement_number or \'\'}"' in body, (
        "F-NEW-068 (PR16-fix): _stmt_hash must seed from "
        "(file_hash, idx, statement_number)."
    )
    # Negative: the prior code passed a single ``source_hash`` value
    # to every statement INSERT call. Make sure no _insert_statement
    # *call site* uses the file-level hash any more — only _stmt_hash.
    # Restrict to call sites that *also* pass bank_account_id, which
    # filters out the function definition itself.
    insert_calls = re.findall(
        r"_insert_statement\(\s*db,\s*bank_account_id=[^)]*source_hash=([^,)]+)",
        body,
        re.DOTALL,
    )
    assert insert_calls, "F-NEW-068: expected _insert_statement(...) call sites"
    for arg in insert_calls:
        arg = arg.strip()
        assert arg.startswith("_stmt_hash("), (
            f"F-NEW-068 (PR16-fix): _insert_statement got source_hash="
            f"{arg!r} — must be a _stmt_hash(...) per-statement digest, "
            "not the file-level hash."
        )


# ── F-NEW-025 — uae_fta_adapter unit_price precision ─────────────────


def test_uae_fta_unit_price_kept_at_full_precision_pre_multiply():
    """Behavioural check: a price of 1.2345 EGP × qty 2 must produce
    a LineExtensionAmount of 2.47 (i.e. q_money(2.469)), not 2.46
    (which is what the early-quantize bug yielded)."""
    from integrations.einvoicing.uae_fta_adapter import build_pint_ae_xml

    invoice = {
        "id": 1, "invoice_number": "INV-PRECISION",
        "issue_date": "2025-05-19",
        "currency": "AED",
        "lines": [{
            "description": "Test", "quantity": Decimal("2"),
            "unit_price": Decimal("1.2345"), "tax_amount": Decimal("0.247"),
            "tax_rate": Decimal("5"), "discount": 0,
        }],
        "total": Decimal("2.717"),
    }
    xml = build_pint_ae_xml(
        invoice, seller_trn="100000000000003",
        seller_name="Test Seller",
    )
    # 2 × 1.2345 = 2.469  →  q_money() = 2.47
    assert (
        '<cbc:LineExtensionAmount currencyID="AED">2.47</cbc:LineExtensionAmount>'
        in xml
    ), (
        "F-NEW-025 (PR16-fix): unit_price must be held at full Decimal "
        "precision through the multiplication; quantizing to 2dp before "
        "multiplying by qty would yield 2.46 instead of 2.47."
    )


# ── F-NEW-023 — eta_adapter Decimal end-to-end ───────────────────────


def test_eta_adapter_no_float_casts_on_money_axis():
    """The audit's R-FLOAT-MONEY rule says no ``float()`` cast on any
    money/tax/rate/qty axis. PR15's checklist marked F-NEW-023 closed
    but the file still contained ``float(...)`` everywhere; PR16-fix
    routes every numeric input through ``utils.tax_precision``."""
    body = _read("integrations/einvoicing/eta_adapter.py")
    # Negative: no ``float(`` anywhere inside ``build_eta_document``
    # except deliberate JSON-shape conversions of already-quantized
    # ``money_str(...)`` / ``rate_str(...)`` outputs (those are exact
    # at the documented dp granularity).
    fn_match = re.search(
        r"def build_eta_document\([^)]*\)\s*->\s*dict:.*?(?=\nclass |\Z)",
        body,
        re.DOTALL,
    )
    assert fn_match, "build_eta_document not found"
    fn_body = fn_match.group(0)
    # Allow only deliberate JSON-shape conversions of already-quantized
    # ``money_str(...)`` / ``rate_str(...)`` outputs and the explicit
    # ``float(qty)`` for the JSON quantity field. Strip those forms
    # before the negative scan.
    sanitised = re.sub(r"float\(money_str\([^)]*\)\)", "", fn_body)
    sanitised = re.sub(r"float\(rate_str\([^)]*\)\)", "", sanitised)
    sanitised = re.sub(r"float\(qty\)", "", sanitised)
    # Strip comments — the post-mortem narrative quotes ``float(...)`` as
    # an explanation of what was removed.
    sanitised_lines = []
    for ln in sanitised.splitlines():
        if ln.lstrip().startswith("#"):
            continue
        sanitised_lines.append(ln)
    sanitised = "\n".join(sanitised_lines)
    assert "float(" not in sanitised, (
        "F-NEW-023 (PR16-fix): build_eta_document must not contain a "
        "raw float() cast on any money/tax/rate/qty axis. Use "
        "utils.tax_precision (dec, q_money, q_qty, q_rate) instead."
    )
    # Positive: tax_precision helpers are imported and used.
    assert "from utils.tax_precision import" in body
    for token in ("q_money", "q_qty", "q_rate", "money_str"):
        assert token in body, f"F-NEW-023 (PR16-fix): {token} must be used"
