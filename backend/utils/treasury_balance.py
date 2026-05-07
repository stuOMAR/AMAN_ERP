"""Treasury balance recomputation helper.

T1.3a — Single source of truth for `treasury_accounts.current_balance`.

Rationale
---------
Historically, every business path that posts a journal entry touching a
treasury's GL account also issued a manual::

    UPDATE treasury_accounts
       SET current_balance = current_balance ± :amt
     WHERE id = :id

This created two divergent sources of truth:
  * `accounts.balance` — kept in sync by the GL trigger on every JE posting.
  * `treasury_accounts.current_balance` — maintained by ad-hoc ± delta
    UPDATEs in 17 places (audit item P0 #3).

Any forgotten/duplicated ± would silently desync the cash-on-hand reported
to users from the GL truth.

Approach
--------
This helper recomputes `current_balance` **idempotently** from the linked
GL account balance. Some tenants carry opening balances in `accounts.balance`
without a matching opening-balance journal entry, so replaying only
`journal_lines` would drop opening cash. For foreign-currency treasuries the
denominated amount comes from `accounts.balance_currency`, falling back to a
conversion from the base balance when the currency column has not been kept.

Call sites replace ad-hoc ± UPDATEs with::

    from utils.treasury_balance import recalc_treasury_from_gl
    recalc_treasury_from_gl(db, treasury_id)

after any JE posting that affected the treasury. The result is independent
of how many times the helper is called and self-heals any prior drift.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from utils.accounting import get_base_currency


def recalc_treasury_from_gl(db, treasury_id: int) -> Optional[Decimal]:
    """Recompute `treasury_accounts.current_balance` from posted JE lines.

    Returns the new balance, or None if the treasury does not exist or has
    no linked GL account (in which case current_balance is left untouched).

    Safe to call multiple times — always derives the same value from the
    underlying journal_lines on the linked gl_account_id.
    """
    info = db.execute(
        text(
            """
            SELECT
                ta.gl_account_id,
                ta.currency,
                a.balance,
                a.balance_currency,
                a.currency AS account_currency
            FROM treasury_accounts ta
            JOIN accounts a ON a.id = ta.gl_account_id
            WHERE ta.id = :id
            """
        ),
        {"id": treasury_id},
    ).fetchone()
    if not info or not info.gl_account_id:
        return None

    base_currency = get_base_currency(db)
    use_fc = bool(info.currency) and info.currency.upper() != base_currency.upper()

    if use_fc:
        balance_currency = Decimal(str(info.balance_currency or 0))
        if info.account_currency and info.account_currency.upper() == info.currency.upper() and balance_currency != 0:
            new_balance = balance_currency
        else:
            row = db.execute(
                text(
                    """
                    SELECT er.rate
                    FROM exchange_rates er
                    JOIN currencies c ON c.id = er.currency_id
                    WHERE c.code = :curr
                    ORDER BY er.rate_date DESC
                    LIMIT 1
                    """
                ),
                {"curr": info.currency},
            ).fetchone()
            rate = Decimal(str(row.rate if row and row.rate else 1))
            new_balance = Decimal(str(info.balance or 0)) / rate
    else:
        new_balance = Decimal(str(info.balance or 0))
    # Set GL context GUC so the treasury balance trigger allows this sanctioned path
    db.execute(text("SELECT set_config('aman.gl_context', 'on', true)"))
    db.execute(
        text(
            "UPDATE treasury_accounts SET current_balance = :bal, updated_at = NOW() WHERE id = :id"
        ),
        {"bal": new_balance, "id": treasury_id},
    )
    return new_balance
