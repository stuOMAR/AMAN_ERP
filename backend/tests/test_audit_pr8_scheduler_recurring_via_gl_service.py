"""Audit PR 8 — scheduler recurring-template materialisation must route
through ``gl_service.create_journal_entry``.

Closes F-NEW-017 (raw INSERT into journal_entries) and F-NEW-018 (raw
INSERT into journal_lines). These are the same hunk inside
``run_due_recurring_templates`` — the audit's writer-monopoly invariant
(Req 8.7e) requires every persisted JE to land via the central service.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHED_PY = REPO_ROOT / "backend/services/scheduler.py"


def _slice(src: str, anchor: str, lines: int = 120) -> str:
    idx = src.find(anchor)
    assert idx >= 0, f"anchor not found: {anchor}"
    return "\n".join(src[idx:].splitlines()[:lines])


def test_recurring_templates_use_gl_service():
    """The handler must build a `lines` payload and call
    ``gl_service.create_journal_entry`` — not raw INSERTs."""
    src = SCHED_PY.read_text(encoding="utf-8")
    body = _slice(src, "def run_due_recurring_templates(", lines=180)
    assert "gl_service" in body or "_gl.create_journal_entry(" in body or \
           "create_journal_entry(" in body, (
        "F-NEW-017/018: scheduler must call the central GL service."
    )
    # Specifically, a call to create_journal_entry with source='recurring_template'.
    assert "recurring_template" in body
    assert "create_journal_entry(" in body


def test_no_raw_insert_into_journal_entries_in_recurring_block():
    """The previous code did `INSERT INTO journal_entries ... VALUES (:num, ...)`
    inline. After PR 8 that block must be gone from the recurring handler."""
    src = SCHED_PY.read_text(encoding="utf-8")
    body = _slice(src, "def run_due_recurring_templates(", lines=180)
    # No raw INSERT into journal_entries / journal_lines should remain.
    assert "INSERT INTO journal_entries" not in body, (
        "F-NEW-017: raw INSERT into journal_entries still present in the "
        "recurring-template loop."
    )
    assert "INSERT INTO journal_lines" not in body, (
        "F-NEW-018: raw INSERT into journal_lines still present in the "
        "recurring-template loop."
    )


def test_no_manual_entry_number_generation_in_recurring_block():
    """The handler used to roll its own sequence with
    ``COALESCE(MAX(CAST(SPLIT_PART(entry_number, '-', 2) AS INTEGER)), 0)``.
    The central service handles numbering."""
    src = SCHED_PY.read_text(encoding="utf-8")
    body = _slice(src, "def run_due_recurring_templates(", lines=180)
    assert "SPLIT_PART(entry_number" not in body, (
        "F-NEW-017: scheduler must not roll its own JE sequence; gl_service "
        "calls generate_sequential_number."
    )
