"""Audit PR 16 — close the four partial-band High clusters.

The audit's High tier had four clusters that were *partially* closed by
prior PRs but still had stragglers. Batch 16 closes the four remaining
findings, fully retiring each cluster:

* F-NEW-026 (R-MISSING-PERMISSION) — POST /einvoicing/outbox/{id}/reprocess
  was already gated with ``require_sensitive_permission`` in PR 4 (when
  the route was rebound to the per-tenant DB). This regression test
  pins the gate so a future refactor cannot silently drop it.
* F-NEW-027 (R-MISSING-IDEMPOTENCY) — same route now requires an
  ``Idempotency-Key`` header (or falls back to a deterministic per-row
  key) and persists it on ``zatca_outbox.last_idempotency_key``. Replays
  of the same key collapse to ``{"idempotent": true}`` instead of
  re-flipping the row.
* F-NEW-042 (GL-4.3 fiscal-lock guard) — the journal-post endpoint
  must route through ``utils.fiscal_lock.check_fiscal_period_open``
  rather than running its own ``SELECT ... FROM fiscal_periods``.
  PR 5 delegated the post path to ``gl_service.post_draft_journal_entry``
  (which calls the canonical guard internally); this test asserts the
  inline pattern stays out of the router.
* F-NEW-110 (GL-4.4 posted-immutability) — expense JE creation no
  longer issues ``UPDATE journal_entries SET entry_number`` after
  ``gl_service.create_journal_entry`` returns. The router pre-allocates
  the EXP- prefixed number and passes it in via the new
  ``entry_number_override`` parameter, so the row is born with the
  correct number and never re-UPDATEd.

The tests are deliberately static: they grep over the source files
(no DB fixtures) so they survive the same baseline gaps that pre-date
the audit.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ── F-NEW-026: outbox reprocess permission ────────────────────────────


def test_reprocess_outbox_requires_sensitive_permission():
    """F-NEW-026: the reprocess endpoint must keep its
    ``require_sensitive_permission`` gate (with ``critical=True``) so a
    read-only role cannot replay ZATCA submissions."""
    body = _read("routers/einvoicing/outbox_admin.py")
    # The decorator-level dependency must remain on the reprocess route.
    m = re.search(
        r"@router\.post\(\s*\"/\{outbox_id\}/reprocess\"[^)]*\)",
        body,
        re.DOTALL,
    )
    assert m, "F-NEW-026: reprocess route declaration not found"
    decl = m.group(0)
    assert "require_sensitive_permission" in decl, (
        "F-NEW-026: reprocess must use require_sensitive_permission(...)"
    )
    assert "critical=True" in decl, (
        "F-NEW-026: reprocess is critical (mutates ZATCA submission state) "
        "— the dependency must mark critical=True."
    )
    # Permission keys must be the documented ones.
    assert "einvoicing.manage" in decl or "taxes.manage" in decl, (
        "F-NEW-026: reprocess must cite einvoicing.manage / taxes.manage."
    )


def test_list_outbox_requires_permission():
    """F-NEW-026 (paired): the GET also needs a permission gate; PR 4
    used the lighter ``require_permission`` because the read does not
    mutate ZATCA state."""
    body = _read("routers/einvoicing/outbox_admin.py")
    m = re.search(
        r'@router\.get\(\s*""[^)]*\)',
        body,
        re.DOTALL,
    )
    assert m, "F-NEW-026: list_outbox route declaration not found"
    assert "require_permission" in m.group(0), (
        "F-NEW-026: list_outbox must keep its require_permission gate."
    )


# ── F-NEW-027: Idempotency-Key on reprocess ───────────────────────────


def test_reprocess_outbox_uses_idempotency_key():
    """F-NEW-027: the handler must read an ``Idempotency-Key`` header
    and persist it on ``zatca_outbox.last_idempotency_key`` so two
    concurrent retry clicks cannot both succeed."""
    body = _read("routers/einvoicing/outbox_admin.py")
    assert "get_idempotency_key" in body, (
        "F-NEW-027: reprocess must read the Idempotency-Key header via "
        "utils.tax_precision.get_idempotency_key (or require_idempotency_key)."
    )
    assert "last_idempotency_key" in body, (
        "F-NEW-027: the column added in migration 0030 (F-NEW-021) must be "
        "written by the reprocess handler."
    )
    # Idempotent replay path: when the prior key matches, the handler
    # must short-circuit instead of re-running the UPDATE.
    assert '"idempotent": True' in body or "'idempotent': True" in body, (
        "F-NEW-027: replays of the same key must return idempotent=True "
        "without re-flipping the row state."
    )


def test_reprocess_outbox_no_unconditional_update():
    """F-NEW-027 (negative): the old handler issued an unconditional
    ``UPDATE ... SET state = 'pending'`` regardless of the replay key.
    The new handler must run the SELECT probe before the UPDATE so the
    second concurrent caller observes the recorded outcome."""
    body = _read("routers/einvoicing/outbox_admin.py")
    # Expect both: a SELECT for the probe, and the UPDATE guarded by the
    # key match. Order matters in the rendered file.
    select_idx = body.find("SELECT id, state, last_idempotency_key")
    update_idx = body.find(
        "UPDATE zatca_outbox\n                SET state = 'pending'"
    )
    assert select_idx != -1, (
        "F-NEW-027: idempotency probe SELECT not found before UPDATE."
    )
    assert update_idx != -1, (
        "F-NEW-027: state-flip UPDATE not found."
    )
    assert select_idx < update_idx, (
        "F-NEW-027: the idempotency-key probe SELECT must run before the "
        "state-flip UPDATE so replays short-circuit."
    )


# ── F-NEW-042: fiscal-lock guard on /post ─────────────────────────────


def test_post_journal_entry_uses_canonical_fiscal_guard():
    """F-NEW-042 (GL-4.3): the /journal-entries/{id}/post endpoint must
    not contain an inline ``SELECT ... FROM fiscal_periods``; it must
    delegate to ``utils.fiscal_lock.check_fiscal_period_open`` (called
    transitively via ``gl_service.post_draft_journal_entry``)."""
    body = _read("routers/finance/accounting/journal.py")

    # Negative: the inline pattern must be absent from the file.
    assert not re.search(
        r"SELECT[^;]*FROM\s+fiscal_periods", body, re.IGNORECASE
    ), (
        "F-NEW-042: inline `SELECT FROM fiscal_periods` is forbidden — "
        "use utils.fiscal_lock.check_fiscal_period_open."
    )
    # Positive: the canonical guard is imported and used.
    assert "from utils.fiscal_lock import check_fiscal_period_open" in body, (
        "F-NEW-042: the canonical fiscal-lock guard must be imported."
    )
    # And the post endpoint delegates to gl_service.post_draft_journal_entry.
    # Slice from the route decorator to the next function definition so
    # we inspect just the handler body.
    decl_idx = body.find('"/journal-entries/{entry_id}/post"')
    assert decl_idx != -1, "F-NEW-042: /post route declaration not found"
    next_def = body.find("\nasync def ", decl_idx + 1)
    next_def = body.find("\nasync def ", next_def + 1) if next_def != -1 else -1
    handler = body[decl_idx : next_def if next_def != -1 else len(body)]
    assert "gl_post_draft_journal_entry" in handler or (
        "post_draft_journal_entry" in handler
    ), (
        "F-NEW-042: post endpoint must route through "
        "gl_service.post_draft_journal_entry (which calls the canonical "
        "fiscal-lock guard internally)."
    )


# ── F-NEW-110: posted-immutability on expenses ────────────────────────


def test_expense_je_no_post_create_entry_number_update():
    """F-NEW-110 (GL-4.4): the expense JE-creation helper must not
    issue ``UPDATE journal_entries SET entry_number`` after
    ``gl_service.create_journal_entry`` returns. The supported path is
    the new ``entry_number_override`` kwarg on the central writer."""
    body = _read("routers/finance/expenses.py")

    # Strip line-comments and docstrings so the historical narrative in
    # the comment block does not trigger the negative match.
    code_lines: list[str] = []
    in_doc = False
    for ln in body.splitlines():
        stripped = ln.lstrip()
        # Toggle triple-quoted blocks (very simple but adequate for this
        # file — there is no nested doc-string trickery).
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

    # Negative: the post-create UPDATE must be gone from executable code.
    assert not re.search(
        r"UPDATE\s+journal_entries\s+SET\s+entry_number",
        code_only,
        re.IGNORECASE,
    ), (
        "F-NEW-110: post-create UPDATE on journal_entries.entry_number is "
        "forbidden. Pass entry_number_override=... to "
        "gl_service.create_journal_entry instead."
    )
    # Positive: the helper now passes the pre-allocated number through
    # the override kwarg.
    assert "entry_number_override=je_number" in body, (
        "F-NEW-110: create_expense_journal_entry must hand its EXP- "
        "prefixed number to gl_service via entry_number_override=."
    )


def test_create_journal_entry_accepts_entry_number_override():
    """F-NEW-110 (paired): the central writer must accept the override
    kwarg so callers like expenses.py can stop UPDATEing journal_entries
    after the row is born."""
    body = _read("services/gl_service.py")
    # The new parameter is part of the public signature.
    assert "entry_number_override:" in body, (
        "F-NEW-110: gl_service.create_journal_entry must declare an "
        "entry_number_override parameter."
    )
    # And it must actually take effect — i.e. the value is used in
    # place of generate_sequential_number when supplied.
    assert "if entry_number_override:" in body, (
        "F-NEW-110: entry_number_override must short-circuit "
        "generate_sequential_number(...) when supplied."
    )
