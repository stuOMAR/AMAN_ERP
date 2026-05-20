"""
Parallel multi-book posting (Phase 6 follow-up).

Posts the same JE into multiple ledgers simultaneously, applying
per-ledger transformation rules (account remapping, rate overrides,
IFRS/local-GAAP adjustments). This complements the single-ledger
``ledger_id`` column added to ``journal_entries`` in Phase 6.

Mapping rules are stored in the ``ledger_account_maps`` table:

    CREATE TABLE IF NOT EXISTS ledger_account_maps (
        id SERIAL PRIMARY KEY,
        ledger_id INTEGER NOT NULL REFERENCES ledgers(id),
        source_account_id INTEGER NOT NULL REFERENCES accounts(id),
        target_account_id INTEGER NOT NULL REFERENCES accounts(id),
        UNIQUE (ledger_id, source_account_id)
    );

If a ledger has no entry for a given source account, the JE line falls
back to the source account unchanged — so you only need to declare
actual differences.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from . import gl_service
from utils.fiscal_lock import check_fiscal_period_open

logger = logging.getLogger(__name__)


def _remap_lines(db, ledger_id: int, lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Apply the ``ledger_account_maps`` rules for this ledger."""
    src_ids = [l["account_id"] for l in lines if l.get("account_id")]
    if not src_ids:
        return lines
    rows = db.execute(
        text(
            "SELECT source_account_id, target_account_id "
            "  FROM ledger_account_maps "
            " WHERE ledger_id = :lid AND source_account_id = ANY(:ids)"
        ),
        {"lid": ledger_id, "ids": list(set(src_ids))},
    ).fetchall()
    mapping = {r[0]: r[1] for r in rows}
    if not mapping:
        return lines
    out = []
    for line in lines:
        new = dict(line)
        src = new.get("account_id")
        if src in mapping:
            new["account_id"] = mapping[src]
        out.append(new)
    return out


def post_multibook_journal_entry(
    db,
    company_id: str,
    date: str,
    description: str,
    lines: List[Dict[str, Any]],
    user_id: int,
    *,
    ledger_ids: Optional[List[int]] = None,
    branch_id: Optional[int] = None,
    reference: Optional[str] = None,
    currency: Optional[str] = None,
    exchange_rate: Decimal = Decimal("1"),
    source: str = "manual",
    source_id: Optional[int] = None,
    username: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Post the same JE into every requested ledger. If ``ledger_ids`` is
    None, post to every active ledger. Returns a list of
    ``{"ledger_id", "journal_id", "entry_number"}`` dicts.
    """
    # Discover ledgers
    if ledger_ids is None:
        rows = db.execute(
            text("SELECT id FROM ledgers WHERE is_active = TRUE ORDER BY id")
        ).fetchall()
        ledger_ids = [r[0] for r in rows]
    if not ledger_ids:
        raise ValueError("no active ledgers configured for this tenant")

    # Fiscal-period lock: block posting into a closed period (all ledgers).
    check_fiscal_period_open(db, date)

    results: List[Dict[str, Any]] = []
    for ledger_id in ledger_ids:
        remapped = _remap_lines(db, ledger_id, lines)
        # Per-ledger idempotency key derivation to prevent duplicate posts
        # while still allowing a single caller-level key to fan out.
        lk = f"{idempotency_key}:L{ledger_id}" if idempotency_key else None
        try:
            jid, num = gl_service.create_journal_entry(
                db, company_id=company_id, date=date, description=description,
                lines=remapped, user_id=user_id, branch_id=branch_id,
                reference=reference, status="posted", currency=currency,
                exchange_rate=exchange_rate, source=source, source_id=source_id,
                username=username, idempotency_key=lk, ledger_id=ledger_id,
            )
            results.append({"ledger_id": ledger_id, "journal_id": jid, "entry_number": num})
        except Exception:
            logger.exception("multibook: posting to ledger %s failed; rolling back all ledgers", ledger_id)
            raise
    return results
