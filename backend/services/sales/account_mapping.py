"""Central account-mapping resolver.

Feature 023 — T030.  Contract: contracts/account-mapping-resolver.md
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


class MissingAccountMapping(Exception):
    def __init__(self, mapping_kind: str):
        self.mapping_kind = mapping_kind
        super().__init__(f"No account mapping found for '{mapping_kind}'")


class AccountClassificationAmbiguous(Exception):
    def __init__(self, classification: str):
        self.classification = classification
        super().__init__(f"Ambiguous classification '{classification}' matched multiple accounts")


def resolve(
    db: Any,
    *,
    mapping_kind: str,
    account_code: str | None = None,
    classification: str | None = None,
    company_id: str,
    direction: str = "forward",
    policy: str = "block",
) -> int:
    """Resolve a GL account ID for the given mapping kind.

    Args:
        db: SQLAlchemy connection.
        mapping_kind: e.g. 'sales_revenue', 'cogs', 'sales_return_revenue', etc.
        account_code: direct account code lookup (optional).
        classification: class-based lookup via 022's classifier (optional).
        company_id: tenant scope.
        direction: 'forward' or 'reversal'.
        policy: 'block' or 'warn'.

    Returns:
        account_id: int.

    Raises:
        MissingAccountMapping: when no mapping exists and policy='block'.
        AccountClassificationAmbiguous: when classifier returns multiple.
    """
    # 1. Direct account_code lookup
    if account_code:
        row = db.execute(
            text("SELECT id FROM accounts WHERE account_code = :code AND is_active = true"),
            {"code": account_code},
        ).fetchone()
        if row:
            return row.id

    # 2. Look up in acc_map_sales
    row = db.execute(
        text("""
            SELECT account_code FROM acc_map_sales
            WHERE mapping_key = :kind AND direction = :direction
            LIMIT 1
        """),
        {"kind": mapping_kind, "direction": direction},
    ).fetchone()

    if row and row.account_code:
        # Check if it's a direct account
        acc = db.execute(
            text("SELECT id FROM accounts WHERE account_code = :code AND is_active = true"),
            {"code": row.account_code},
        ).fetchone()
        if acc:
            return acc.id

        # Might be a classification — try 022's classifier
        try:
            from services.account_classifier import resolve_one
            result = resolve_one(db, classification=row.account_code, company_id=company_id)
            if result:
                return result
        except ImportError:
            pass

    # 3. Classification-based lookup
    if classification:
        try:
            from services.account_classifier import resolve_one
            result = resolve_one(db, classification=classification, company_id=company_id)
            if result:
                return result
        except ImportError:
            pass

    # 4. Policy handling
    if policy == "warn":
        logger.warning(f"Missing account mapping for '{mapping_kind}', policy=warn")
        try:
            from services.audit_writer import log_activity
            log_activity(
                db,
                action="account_mapping.fallback",
                entity_type="account_mapping",
                details={"mapping_kind": mapping_kind, "direction": direction},
            )
        except Exception:
            pass
        # Return a default account if configured
        default = db.execute(
            text("SELECT id FROM accounts WHERE account_code = 'GEN-EXP' AND is_active = true LIMIT 1")
        ).fetchone()
        if default:
            return default.id

    raise MissingAccountMapping(mapping_kind)
