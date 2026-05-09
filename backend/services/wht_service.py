"""
Withholding Tax (WHT) service.

WHT is widely mandated for cross-border services payments (e.g. KSA ZATCA
WHT on non-resident service providers: 5% royalties, 15% royalty/technical,
20% dividends) and is applicable in Egypt, UAE, Kuwait, Jordan, etc.

This service keeps things framework-style:
  * ``configs`` table stores (country, payment_type) → (rate, gl_account).
  * ``compute`` returns a breakdown given gross amount + country/type.
  * ``post`` books the JE so the supplier's net cash moves to the bank
    and the withheld portion moves to a "WHT Payable" liability account.

The tables created here are idempotent via ``database.py`` so no manual
migration is required.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from . import gl_service
from utils.fiscal_lock import check_fiscal_period_open
from utils.tax_precision import money_str, q_money

logger = logging.getLogger(__name__)


@dataclass
class WHTBreakdown:
    gross: Decimal
    rate: Decimal          # e.g. Decimal("0.05") for 5%
    wht_amount: Decimal
    net: Decimal
    rule_id: Optional[int] = None
    country: Optional[str] = None
    payment_type: Optional[str] = None
    gl_account_id: Optional[int] = None


def find_rule(db, *, country: str, payment_type: str) -> Optional[Dict[str, Any]]:
    row = db.execute(
        text(
            "SELECT id, rate, gl_account_id, description "
            "  FROM wht_rules "
            " WHERE country_code = :c AND payment_type = :t AND is_active = TRUE "
            " ORDER BY id DESC LIMIT 1"
        ),
        {"c": country, "t": payment_type},
    ).fetchone()
    if not row:
        return None
    return {
        "id": row[0], "rate": Decimal(str(row[1])),
        "gl_account_id": row[2], "description": row[3],
    }


def compute(db, *, gross: Decimal, country: str, payment_type: str) -> WHTBreakdown:
    gross = Decimal(str(gross))
    rule = find_rule(db, country=country, payment_type=payment_type)
    if not rule:
        return WHTBreakdown(gross=gross, rate=Decimal("0"), wht_amount=Decimal("0"),
                            net=gross, country=country, payment_type=payment_type)
    rate = rule["rate"]
    wht = (gross * rate).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return WHTBreakdown(
        gross=gross, rate=rate, wht_amount=wht, net=gross - wht,
        rule_id=rule["id"], country=country, payment_type=payment_type,
        gl_account_id=rule["gl_account_id"],
    )


def augment_payment_lines(
    lines: List[Dict[str, Any]],
    breakdown: WHTBreakdown,
    *,
    bank_account_id: int,
    expense_account_id: int,
) -> List[Dict[str, Any]]:
    """
    Given a gross payment's proposed JE lines, reshape them so the
    credit-to-bank equals the net amount and a WHT-payable credit is
    added for the withheld portion.
    """
    if breakdown.wht_amount <= 0 or breakdown.gl_account_id is None:
        return lines
    out: List[Dict[str, Any]] = []
    bank_line_found = False
    for ln in lines:
        new = dict(ln)
        if new.get("account_id") == bank_account_id and Decimal(str(new.get("credit", 0))) > 0:
            new["credit"] = q_money(Decimal(str(new["credit"])) - breakdown.wht_amount)
            bank_line_found = True
        out.append(new)
    if not bank_line_found:   # conservative fallback: debit expense / credit bank net
        out.append({"account_id": expense_account_id, "debit": q_money(breakdown.gross), "credit": 0})
        out.append({"account_id": bank_account_id, "debit": 0, "credit": q_money(breakdown.net)})
    out.append({
        "account_id": breakdown.gl_account_id,
        "debit": 0,
        "credit": q_money(breakdown.wht_amount),
        "description": f"WHT {breakdown.rate*100:.1f}% ({breakdown.country}/{breakdown.payment_type})",
    })
    return out


def post_payment_with_wht(
    db, *, company_id: str, date: str, description: str,
    lines: List[Dict[str, Any]], user_id: int,
    bank_account_id: int, expense_account_id: int,
    gross: Decimal, country: str, payment_type: str,
    **kwargs,
) -> Tuple[int, str, WHTBreakdown]:
    br = compute(db, gross=gross, country=country, payment_type=payment_type)
    full_lines = augment_payment_lines(
        lines, br, bank_account_id=bank_account_id,
        expense_account_id=expense_account_id,
    )
    # Fiscal-period lock: block posting into a closed period.
    check_fiscal_period_open(db, date)
    idempotency_key = kwargs.pop("idempotency_key", None)
    if not idempotency_key:
        raise ValueError("idempotency_key is required for WHT payment posting")
    jid, num = gl_service.create_journal_entry(
        db, company_id=company_id, date=date, description=description,
        lines=full_lines, user_id=user_id,
        idempotency_key=idempotency_key,
        **kwargs,
    )
    return jid, num, br
