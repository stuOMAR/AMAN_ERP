"""Account classifier — replaces hard-coded account-code-range checks.

Single source of truth for statement-category mapping.  All report modules
MUST call ``classify()`` instead of inspecting account codes directly.

Contract: see specs/022-audit-security-finance-integrity/contracts/account-classifier.md
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Literal

from sqlalchemy import text

from database import get_db_connection
from utils.audit import log_activity

logger = logging.getLogger(__name__)

# ── Data classes ──────────────────────────────────────────────────────────────

StatementCategory = Literal[
    "asset", "liability", "equity", "revenue", "expense",
    "contra_asset", "contra_liability", "contra_equity",
    "contra_revenue", "contra_expense",
]

_SIGN_MAP: dict[str, int] = {
    "asset": +1,
    "liability": -1,
    "equity": +1,
    "revenue": -1,
    "expense": +1,
    "contra_asset": -1,
    "contra_liability": +1,
    "contra_equity": -1,
    "contra_revenue": +1,
    "contra_expense": -1,
}


@dataclass(frozen=True)
class AccountClassification:
    account_id: int
    statement_category: StatementCategory
    sign: Literal[-1, 1]
    aggregation_hint: str | None


# ── Errors ────────────────────────────────────────────────────────────────────

class MissingClassificationError(Exception):
    """Raised when no active classification row exists for an account."""

    def __init__(self, account_id: int):
        self.account_id = account_id
        super().__init__(f"No active classification for account {account_id}")


# ── Per-request cache ────────────────────────────────────────────────────────

_cache: dict[int, AccountClassification] = {}


def _cache_key(tenant_id: int, account_id: int) -> int:
    """Composite key — tenant_id is always set by DB session so we key by account_id only
    but the query always filters tenant_id for isolation."""
    return account_id


def invalidate_cache() -> None:
    """Clear the per-request cache (called on upsert)."""
    _cache.clear()


# ── Query helper ─────────────────────────────────────────────────────────────

_QUERY = text(
    """
    SELECT account_id, statement_category, sign, aggregation_hint
    FROM account_classifications
    WHERE tenant_id = current_setting('app.tenant_id', true)::bigint
      AND account_id = :account_id
      AND is_active = true
      AND valid_from <= current_date
      AND (valid_to IS NULL OR valid_to >= current_date)
    ORDER BY valid_from DESC
    LIMIT 1
    """
)

_QUERY_MANY = text(
    """
    SELECT DISTINCT ON (account_id)
           account_id, statement_category, sign, aggregation_hint
    FROM account_classifications
    WHERE tenant_id = current_setting('app.tenant_id', true)::bigint
      AND account_id = ANY(:account_ids)
      AND is_active = true
      AND valid_from <= current_date
      AND (valid_to IS NULL OR valid_to >= current_date)
    ORDER BY account_id, valid_from DESC
    """
)


def _row_to_classification(row) -> AccountClassification:
    return AccountClassification(
        account_id=row.account_id,
        statement_category=row.statement_category,
        sign=row.sign,
        aggregation_hint=row.aggregation_hint,
    )


# ── Public API ────────────────────────────────────────────────────────────────

def classify(tenant_id: int, account_id: int) -> AccountClassification:
    """Return the active classification for *account_id*.

    Uses per-request cache.  Raises ``MissingClassificationError`` when
    no active row is found.
    """
    key = _cache_key(tenant_id, account_id)
    if key in _cache:
        return _cache[key]

    conn = get_db_connection(tenant_id)
    try:
        row = conn.execute(_QUERY, {"account_id": account_id}).fetchone()
        if row is None:
            raise MissingClassificationError(account_id)
        cls = _row_to_classification(row)
        _cache[key] = cls
        return cls
    finally:
        conn.close()


def classify_many(
    tenant_id: int, account_ids: Iterable[int]
) -> dict[int, AccountClassification]:
    """Return classifications for *account_ids*, skipping missing ones.

    Cached rows are returned without a DB round-trip.
    """
    ids = list(account_ids)
    result: dict[int, AccountClassification] = {}

    uncached = [aid for aid in ids if _cache_key(tenant_id, aid) not in _cache]
    for aid in ids:
        key = _cache_key(tenant_id, aid)
        if key in _cache:
            result[aid] = _cache[key]

    if not uncached:
        return result

    conn = get_db_connection(tenant_id)
    try:
        rows = conn.execute(
            _QUERY_MANY, {"account_ids": uncached}
        ).fetchall()
        for row in rows:
            cls = _row_to_classification(row)
            _cache[_cache_key(tenant_id, cls.account_id)] = cls
            result[cls.account_id] = cls
    finally:
        conn.close()

    return result


def upsert_classification(
    tenant_id: int,
    account_id: int,
    *,
    statement_category: str,
    sign: int,
    aggregation_hint: str | None = None,
    valid_from: date,
    valid_to: date | None = None,
    actor_id: int,
) -> AccountClassification:
    """Insert a new classification and close the previous active row.

    Validates *sign* matches *statement_category* semantics.
    Emits a critical audit event.
    """
    # Validate sign
    expected_sign = _SIGN_MAP.get(statement_category)
    if expected_sign is None:
        raise ValueError(f"Unknown statement_category: {statement_category}")
    if sign != expected_sign:
        raise ValueError(
            f"sign={sign} conflicts with statement_category={statement_category} "
            f"(expected {expected_sign})"
        )

    conn = get_db_connection(tenant_id)
    try:
        # Close previous active row (if any)
        conn.execute(
            text(
                """
                UPDATE account_classifications
                SET valid_to = :close_date, updated_at = clock_timestamp()
                WHERE tenant_id = current_setting('app.tenant_id', true)::bigint
                  AND account_id = :account_id
                  AND is_active = true
                  AND (valid_to IS NULL OR valid_to >= :valid_from)
                """
            ),
            {
                "account_id": account_id,
                "close_date": valid_from,
                "valid_from": valid_from,
            },
        )

        # Insert new row
        row = conn.execute(
            text(
                """
                INSERT INTO account_classifications
                    (tenant_id, account_id, statement_category, sign,
                     aggregation_hint, is_active, valid_from, valid_to,
                     created_at, updated_at)
                VALUES
                    (current_setting('app.tenant_id', true)::bigint,
                     :account_id, :statement_category, :sign,
                     :aggregation_hint, true, :valid_from, :valid_to,
                     clock_timestamp(), clock_timestamp())
                RETURNING account_id, statement_category, sign, aggregation_hint
                """
            ),
            {
                "account_id": account_id,
                "statement_category": statement_category,
                "sign": sign,
                "aggregation_hint": aggregation_hint,
                "valid_from": valid_from,
                "valid_to": valid_to,
            },
        ).fetchone()

        conn.commit()

        cls = _row_to_classification(row)
        # Invalidate cache
        _cache.pop(_cache_key(tenant_id, account_id), None)

        # Audit
        log_activity(
            conn,
            user_id=actor_id,
            username="system",
            action="account_classification.upsert",
            resource_type="account_classification",
            resource_id=str(account_id),
            details={
                "statement_category": statement_category,
                "sign": sign,
                "valid_from": str(valid_from),
                "valid_to": str(valid_to),
            },
            critical=True,
        )
        conn.commit()

        return cls
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
