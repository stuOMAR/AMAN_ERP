"""Audit PR 5 — GL writer monopoly regression tests.

Closes:
  * F-NEW-009 — opening-balance replace must not DELETE a posted JE.
  * F-NEW-010 — journal-entry POST handler must route through
                ``gl_service.post_draft_journal_entry``.
  * F-NEW-035 — same hunk as F-NEW-009 (no direct ``update_account_balance``
                outside ``gl_service``).

These are static-source regression checks (no DB required) — they grep
the live router source to ensure the prohibited patterns no longer appear
in the audited blocks. This mirrors how the existing
``test_inventory_sales_purchase_integrity_regressions.py`` family asserts
invariants by reading source text.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ACCOUNTS_PY = REPO_ROOT / "backend/routers/finance/accounting/accounts.py"
JOURNAL_PY = REPO_ROOT / "backend/routers/finance/accounting/journal.py"


# ──────────────────────────────────────────────────────────────────────
# F-NEW-009 / F-NEW-035 — opening-balance replace block in accounts.py
# ──────────────────────────────────────────────────────────────────────


def _find_block(text: str, anchor: str, lines_after: int = 40) -> str:
    """Slice the source from ``anchor`` to ``lines_after`` lines after."""
    idx = text.find(anchor)
    assert idx >= 0, f"anchor not found: {anchor!r}"
    end = text.find("\n", idx)
    rest = text[end:].splitlines()[:lines_after]
    return "\n".join([anchor, *rest])


def test_opening_balance_replace_no_direct_delete_of_posted_je():
    src = ACCOUNTS_PY.read_text(encoding="utf-8")
    block = _find_block(src, "if existing.status == 'posted':", lines_after=20)
    # The fix routes through gl_service.reverse_journal_entry, NOT a raw
    # DELETE. The block must contain the central call.
    assert "gl_reverse_journal_entry(" in block, (
        "F-NEW-009: posted opening-balance entry must be reversed via "
        "gl_service, not deleted directly."
    )
    # And the block must NOT contain the prior pattern: a raw
    # ``update_account_balance as _uab`` import + per-line ± UPDATE loop.
    assert "from utils.accounting import update_account_balance as _uab" not in block, (
        "F-NEW-035: balance-writer monopoly violated — _uab fallback still present."
    )


def test_opening_balance_replace_only_deletes_drafts():
    src = ACCOUNTS_PY.read_text(encoding="utf-8")
    # The DELETE on journal_entries must be guarded by ``status = 'draft'``.
    # Find every DELETE on journal_entries and assert the guard.
    import re
    deletes = re.findall(
        r"DELETE FROM journal_entries[^;]+",
        src,
    )
    assert deletes, "expected at least one journal_entries DELETE in accounts.py"
    for d in deletes:
        assert "status = 'draft'" in d or "status='draft'" in d, (
            f"F-NEW-009: bare DELETE on journal_entries without draft guard: {d}"
        )


# ──────────────────────────────────────────────────────────────────────
# F-NEW-010 — journal post must use gl_service.post_draft_journal_entry
# ──────────────────────────────────────────────────────────────────────


def test_journal_post_handler_uses_gl_service():
    src = JOURNAL_PY.read_text(encoding="utf-8")
    # Find the @router.post(".../post") handler body.
    anchor = "@router.post(\"/journal-entries/{entry_id}/post\""
    idx = src.find(anchor)
    assert idx >= 0, "post-journal handler anchor not found"
    # Slice ~120 lines so we cover the whole handler body.
    body = "\n".join(src[idx:].splitlines()[:120])

    assert "gl_post_draft_journal_entry(" in body, (
        "F-NEW-010: post handler must route through gl_service."
    )
    # The handler must NOT re-implement the balance loop.
    assert "for line in lines:" not in body or "update_account_balance" not in body, (
        "F-NEW-010: post handler still calls update_account_balance directly."
    )
    # And there must be no inline closed-period check using fiscal_periods —
    # gl_service.post_draft_journal_entry calls the canonical guard.
    assert "FROM fiscal_periods" not in body, (
        "F-NEW-010: inline fiscal_periods query bypasses canonical guard "
        "(C-ARCH-002 — must use utils.fiscal_lock.check_fiscal_period_open)."
    )
    # Defence-in-depth: the handler must NOT issue a raw status='posted' UPDATE.
    assert "UPDATE journal_entries SET status = 'posted'" not in body, (
        "F-NEW-010: handler still flips status manually instead of via gl_service."
    )


def test_journal_module_imports_post_draft():
    src = JOURNAL_PY.read_text(encoding="utf-8")
    # Importing the helper proves the central path is wired.
    assert "post_draft_journal_entry" in src, (
        "F-NEW-010: gl_service.post_draft_journal_entry not imported."
    )
