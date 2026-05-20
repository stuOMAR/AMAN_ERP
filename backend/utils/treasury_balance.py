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
This helper recomputes `current_balance` **idempotently** from posted
`journal_lines` on the linked GL account. That makes it able to heal drift in
the denormalized `accounts.balance` columns rather than copying the drift into
treasury again. For foreign-currency treasuries it uses journal-line
transaction/original currency amounts when they match the treasury currency.
If no matching currency lines exist, it writes zero and logs the
data-quality gap instead of showing a base-currency balance under the
foreign-currency label.

Call sites replace ad-hoc ± UPDATEs with::

    from utils.treasury_balance import recalc_treasury_from_gl
    recalc_treasury_from_gl(db, treasury_id)

after any JE posting that affected the treasury. The result is independent
of how many times the helper is called and self-heals any prior drift.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from utils.accounting import get_base_currency

logger = logging.getLogger(__name__)


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
                a.account_type
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
    normal_side = "debit" if info.account_type in ("asset", "expense") else "credit"

    row = db.execute(
        text(
            """
            SELECT
                COALESCE(SUM(
                    CASE
                        WHEN :normal_side = 'debit' THEN COALESCE(jl.debit, 0) - COALESCE(jl.credit, 0)
                        ELSE COALESCE(jl.credit, 0) - COALESCE(jl.debit, 0)
                    END
                ), 0) AS base_balance,
                COALESCE(SUM(
                    CASE
                        WHEN COALESCE(jl.txn_currency, jl.currency) = :currency THEN
                            CASE
                                WHEN :normal_side = 'debit' THEN
                                    CASE WHEN COALESCE(jl.debit, 0) > 0
                                        THEN COALESCE(jl.txn_amount, jl.amount_currency, jl.debit, 0)
                                        ELSE -COALESCE(jl.txn_amount, jl.amount_currency, jl.credit, 0)
                                    END
                                ELSE
                                    CASE WHEN COALESCE(jl.credit, 0) > 0
                                        THEN COALESCE(jl.txn_amount, jl.amount_currency, jl.credit, 0)
                                        ELSE -COALESCE(jl.txn_amount, jl.amount_currency, jl.debit, 0)
                                    END
                            END
                        ELSE 0
                    END
                ), 0) AS currency_balance,
                COUNT(*) FILTER (WHERE COALESCE(jl.txn_currency, jl.currency) = :currency) AS currency_line_count
            FROM journal_lines jl
            JOIN journal_entries je ON je.id = jl.journal_entry_id
            WHERE jl.account_id = :account_id
              AND je.status = 'posted'
            """
        ),
        {
            "account_id": info.gl_account_id,
            "currency": info.currency,
            "normal_side": normal_side,
        },
    ).fetchone()

    if use_fc:
        if row and row.currency_line_count:
            new_balance = Decimal(str(row.currency_balance or 0))
        else:
            logger.warning(
                "Treasury %s uses currency %s but has no posted journal lines in that currency; "
                "setting current_balance to 0 instead of relabeling base balance %s",
                treasury_id,
                info.currency,
                row.base_balance if row else 0,
            )
            new_balance = Decimal("0")
    else:
        new_balance = Decimal(str(row.base_balance if row else 0))
    # Set GL context GUC so the treasury balance trigger allows this sanctioned path
    db.execute(text("SELECT set_config('aman.gl_context', 'on', true)"))
    db.execute(
        text(
            "UPDATE treasury_accounts SET current_balance = :bal, updated_at = NOW() WHERE id = :id"
        ),
        {"bal": new_balance, "id": treasury_id},
    )
    return new_balance
