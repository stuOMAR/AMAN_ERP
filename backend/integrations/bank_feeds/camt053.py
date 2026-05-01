"""
ISO 20022 CAMT.053 bank-statement parser.

CAMT.053 is the modern XML successor to MT940 used across SEPA banks and
many international banks. Each file contains one or more ``<Stmt>`` blocks
under ``<BkToCstmrStmt>``.

This parser extracts the subset we need for reconciliation:

  * ``Acct/Id/IBAN``                     → account / IBAN
  * ``Acct/Ccy``                         → currency
  * ``Bal[Tp/CdOrPrtry/Cd='OPBD']``      → opening balance (booked)
  * ``Bal[Tp/CdOrPrtry/Cd='CLBD']``      → closing balance (booked)
  * ``Stmt/Id`` / ``ElctrncSeqNb``       → statement number
  * ``Ntry``                             → one transaction line
      * ``Amt``                          → amount + currency
      * ``CdtDbtInd``                    → CRDT (+) or DBIT (-)
      * ``BookgDt`` / ``ValDt``          → booking + value dates
      * ``BkTxCd/Domn/Fmly/SubFmlyCd``  → transaction subtype
      * ``AcctSvcrRef``                  → bank reference
      * ``NtryDtls/TxDtls/RmtInf/Ustrd`` → unstructured remittance info
      * ``NtryDtls/TxDtls/Refs/EndToEndId`` → counterparty reference

Reference: ISO 20022 BankToCustomerStatement V02+ (camt.053.001.xx).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)


@dataclass
class CAMT053Transaction:
    value_date: date
    entry_date: Optional[date]
    amount: Decimal                   # signed: +credit, -debit
    currency: str
    transaction_type: str             # synthesised from BkTxCd (Domn/Fmly/SubFmly)
    reference: str                    # EndToEndId or AcctSvcrRef
    bank_reference: Optional[str] = None
    description: str = ""


@dataclass
class CAMT053Statement:
    account: str
    statement_number: str
    currency: str
    opening_balance: Decimal
    closing_balance: Decimal
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    transactions: List[CAMT053Transaction] = field(default_factory=list)


# ─── helpers ────────────────────────────────────────────────────────────────

# CAMT.053 uses an XML namespace that varies by version (.02, .04, .08, etc.).
# We strip the namespace from each tag for simpler XPath matching.
_NS_RE = re.compile(r"^\{[^}]+\}")


def _localname(tag: str) -> str:
    return _NS_RE.sub("", tag)


def _strip_ns(elem: ET.Element) -> None:
    """Recursively rewrite tags as their local-name only (in-place)."""
    for el in elem.iter():
        el.tag = _localname(el.tag)


def _findtext(elem: ET.Element, path: str) -> Optional[str]:
    node = elem.find(path)
    return node.text.strip() if node is not None and node.text is not None else None


def _parse_iso_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    value = value.strip()
    # Date-only or datetime; we only need the date portion.
    try:
        if "T" in value:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _parse_amount(elem: ET.Element) -> tuple[Decimal, str]:
    if elem is None or elem.text is None:
        return Decimal("0"), ""
    return Decimal(elem.text.strip()), (elem.attrib.get("Ccy") or "").strip()


def _balance_for_code(stmt: ET.Element, codes: tuple[str, ...]) -> tuple[Decimal, str]:
    """Return (amount, currency) for the first ``Bal`` whose code matches ``codes``.

    OPBD/PRCD = opening (booked / previously closed); CLBD = closing booked.
    """
    for bal in stmt.findall("Bal"):
        code = _findtext(bal, "Tp/CdOrPrtry/Cd") or _findtext(bal, "Tp/CdOrPrtry/Prtry") or ""
        if code in codes:
            amt_node = bal.find("Amt")
            amount, currency = _parse_amount(amt_node)
            sign = (_findtext(bal, "CdtDbtInd") or "CRDT").upper()
            if sign == "DBIT":
                amount = -amount
            return amount, currency
    return Decimal("0"), ""


def _build_tx_type(ntry: ET.Element) -> str:
    """Synthesise a short type code: ``DOMN-FMLY-SUBFMLY`` (best-effort)."""
    parts = [
        _findtext(ntry, "BkTxCd/Domn/Cd"),
        _findtext(ntry, "BkTxCd/Domn/Fmly/Cd"),
        _findtext(ntry, "BkTxCd/Domn/Fmly/SubFmlyCd"),
    ]
    code = "-".join(p for p in parts if p)
    return code or (_findtext(ntry, "BkTxCd/Prtry/Cd") or "NTRF")


def _collect_description(ntry: ET.Element) -> str:
    """Gather all unstructured remittance lines + AddtlNtryInf into one string."""
    chunks: List[str] = []
    for ustrd in ntry.findall(".//Ustrd"):
        if ustrd.text:
            chunks.append(ustrd.text.strip())
    addtl = _findtext(ntry, "AddtlNtryInf")
    if addtl:
        chunks.append(addtl)
    return " | ".join(c for c in chunks if c)


def _entry_reference(ntry: ET.Element) -> tuple[str, Optional[str]]:
    """Return (reference, bank_reference). Prefer EndToEndId; fallback to AcctSvcrRef."""
    end_to_end = _findtext(ntry, ".//Refs/EndToEndId")
    bank_ref = _findtext(ntry, "AcctSvcrRef")
    reference = end_to_end or bank_ref or ""
    return reference, bank_ref


# ─── public API ─────────────────────────────────────────────────────────────


def parse_camt053(xml_input) -> List[CAMT053Statement]:
    """Parse a CAMT.053 document and return one :class:`CAMT053Statement` per ``Stmt``.

    ``xml_input`` may be ``bytes``, ``str``, a file path, or an open file-like
    object. Raises ``ValueError`` if the document is malformed or contains no
    statement blocks.
    """
    if isinstance(xml_input, (bytes, bytearray)):
        root = ET.fromstring(bytes(xml_input))
    elif isinstance(xml_input, str) and xml_input.lstrip().startswith("<"):
        root = ET.fromstring(xml_input)
    else:
        # path or file-like
        root = ET.parse(xml_input).getroot()

    _strip_ns(root)

    stmts = root.findall(".//Stmt")
    if not stmts:
        raise ValueError("CAMT.053: no <Stmt> blocks found")

    results: List[CAMT053Statement] = []
    for stmt in stmts:
        iban = _findtext(stmt, "Acct/Id/IBAN") or _findtext(stmt, "Acct/Id/Othr/Id") or ""
        currency = _findtext(stmt, "Acct/Ccy") or ""
        statement_number = _findtext(stmt, "ElctrncSeqNb") or _findtext(stmt, "Id") or ""

        opening, opn_ccy = _balance_for_code(stmt, ("OPBD", "PRCD"))
        closing, cls_ccy = _balance_for_code(stmt, ("CLBD",))
        if not currency:
            currency = opn_ccy or cls_ccy or ""

        # Period
        period_start = _parse_iso_date(_findtext(stmt, "FrToDt/FrDtTm")) \
            or _parse_iso_date(_findtext(stmt, "FrToDt/FrDt"))
        period_end = _parse_iso_date(_findtext(stmt, "FrToDt/ToDtTm")) \
            or _parse_iso_date(_findtext(stmt, "FrToDt/ToDt"))

        transactions: List[CAMT053Transaction] = []
        for ntry in stmt.findall("Ntry"):
            amount, amt_ccy = _parse_amount(ntry.find("Amt"))
            sign = (_findtext(ntry, "CdtDbtInd") or "CRDT").upper()
            if sign == "DBIT":
                amount = -amount
            value_date = _parse_iso_date(_findtext(ntry, "ValDt/Dt") or _findtext(ntry, "ValDt/DtTm"))
            entry_date = _parse_iso_date(_findtext(ntry, "BookgDt/Dt") or _findtext(ntry, "BookgDt/DtTm"))
            if value_date is None and entry_date is not None:
                value_date = entry_date
            if value_date is None:
                # CAMT.053 should always have ValDt or BookgDt; skip if neither.
                logger.warning("CAMT.053: skipping <Ntry> without ValDt/BookgDt")
                continue
            ref, bank_ref = _entry_reference(ntry)
            transactions.append(CAMT053Transaction(
                value_date=value_date,
                entry_date=entry_date,
                amount=amount,
                currency=amt_ccy or currency,
                transaction_type=_build_tx_type(ntry),
                reference=ref,
                bank_reference=bank_ref,
                description=_collect_description(ntry),
            ))

        # Fall back period from transactions if not declared.
        if period_start is None and transactions:
            period_start = min(t.value_date for t in transactions)
        if period_end is None and transactions:
            period_end = max(t.value_date for t in transactions)

        results.append(CAMT053Statement(
            account=iban,
            statement_number=statement_number,
            currency=currency,
            opening_balance=opening,
            closing_balance=closing,
            period_start=period_start,
            period_end=period_end,
            transactions=transactions,
        ))

    return results
