"""Idempotency-Key dedup helpers for finance/treasury/tax remediation.

The audit's R-MISSING-IDEMPOTENCY rule (Req 8.9) requires every sensitive
state-mutating POST to expose a deterministic replay surface. We satisfy
that contract by accepting an ``Idempotency-Key`` HTTP header and looking
the key up in one of two canonical stores before doing any work:

* ``journal_entries.idempotency_key`` — the primary store; populated by
  ``services.gl_service.create_journal_entry`` (and
  ``post_draft_journal_entry`` / ``reverse_journal_entry``) which already
  dedupes on this column with a unique partial index. Every handler that
  posts a JE through the central service inherits its protection by
  forwarding the key.

* ``treasury_transactions.idempotency_key`` — added by Batch 10 (alembic
  ``0030_audit_h_ddl_sync``) for handlers that create a treasury row in
  addition to a JE (e.g. ``/api/treasury/transactions/transfer``).

This module is deliberately tiny: it just centralises the SQL so each
remediation site can call one helper instead of inlining the same SELECT.
"""
from __future__ import annotations

from typing import Optional, Tuple

from sqlalchemy import text


def find_je_by_idempotency_key(db, key: Optional[str]) -> Optional[Tuple[int, str]]:
    """Return ``(id, entry_number)`` for a journal_entries row whose
    ``idempotency_key`` matches ``key``, or ``None`` when no key was
    supplied or no prior entry exists.

    Callers should treat a non-``None`` return value as a successful
    replay and short-circuit any further side effects.
    """
    if not key:
        return None
    row = db.execute(
        text(
            "SELECT id, entry_number FROM journal_entries "
            "WHERE idempotency_key = :k LIMIT 1"
        ),
        {"k": key},
    ).fetchone()
    if row is None:
        return None
    return int(row.id), str(row.entry_number)


def find_treasury_txn_by_idempotency_key(
    db, key: Optional[str]
) -> Optional[Tuple[int, str]]:
    """Return ``(id, transaction_number)`` for a treasury_transactions
    row whose ``idempotency_key`` matches ``key``, or ``None``.

    Backed by the ``treasury_transactions.idempotency_key`` column added
    by alembic ``0030_audit_h_ddl_sync``.
    """
    if not key:
        return None
    row = db.execute(
        text(
            "SELECT id, transaction_number FROM treasury_transactions "
            "WHERE idempotency_key = :k LIMIT 1"
        ),
        {"k": key},
    ).fetchone()
    if row is None:
        return None
    return int(row.id), str(row.transaction_number)


def find_bank_statement_by_source_hash(
    db, *, bank_account_id: Optional[int], source_hash: Optional[str]
) -> Optional[int]:
    """Return the id of an existing ``bank_statements`` row with the same
    ``(bank_account_id, source_hash)`` tuple, or ``None``.

    Backed by the ``bank_statements.source_hash`` column added by alembic
    ``0030_audit_h_ddl_sync`` and its per-account partial unique index.
    """
    if not source_hash:
        return None
    row = db.execute(
        text(
            "SELECT id FROM bank_statements "
            "WHERE bank_account_id IS NOT DISTINCT FROM :ba "
            "AND (source_hash = :h OR source_file_hash = :h) LIMIT 1"
        ),
        {"ba": bank_account_id, "h": source_hash},
    ).fetchone()
    return int(row.id) if row else None


def find_je_by_source(
    db, *, source: Optional[str], source_id: Optional[int]
) -> Optional[Tuple[int, str]]:
    """Return ``(id, entry_number)`` for an existing journal_entries row
    posted under the given ``(source, source_id)`` pair, or ``None``.

    Audit PR16-fix: state-mutating handlers (``checks/{id}/collect``,
    ``notes/{id}/collect``, etc.) used to short-circuit on
    ``check.status != 'pending'`` *before* checking the idempotency
    key; that meant a network retry of a successful POST would fail
    with a 400 ``not_in_pending_status`` error rather than echoing
    the prior result. The supported pattern is now:

        1. probe by ``(source, source_id)`` (this helper) — if a JE
           already exists, return it as ``idempotent=True``
        2. only then run the state machine guard
        3. forward ``Idempotency-Key`` to ``gl_service.create_journal_entry``
           which carries its own unique-index dedup as a backstop

    The check is keyed on the *natural* idempotency anchor of the
    operation rather than the HTTP header alone, so retries collapse
    even when the client forgets to send the header.
    """
    if not source or source_id is None:
        return None
    row = db.execute(
        text(
            "SELECT id, entry_number FROM journal_entries "
            "WHERE source = :s AND source_id = :sid LIMIT 1"
        ),
        {"s": source, "sid": int(source_id)},
    ).fetchone()
    if row is None:
        return None
    return int(row.id), str(row.entry_number)


def find_reversal_by_source_je(
    db, *, source_je_id: int
) -> Optional[Tuple[int, str]]:
    """Return ``(id, entry_number)`` for the reversing JE of a given
    posted JE, or ``None`` when no reversal exists.

    Reversal entries are written by ``gl_service.reverse_journal_entry``
    with ``source='reversal'`` and ``source_id=<original je_id>``.
    Handlers that expose a ``/reverse`` endpoint should probe this
    helper *before* the state-mismatch guard so a retry returns the
    existing reversal instead of failing.
    """
    if source_je_id is None:
        return None
    row = db.execute(
        text(
            "SELECT id, entry_number FROM journal_entries "
            "WHERE source = 'reversal' AND source_id = :sid LIMIT 1"
        ),
        {"sid": int(source_je_id)},
    ).fetchone()
    if row is None:
        return None
    return int(row.id), str(row.entry_number)
