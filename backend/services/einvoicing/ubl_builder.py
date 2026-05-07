"""UBL 2.1 builder for ZATCA e-invoicing (standard + simplified).

Feature 023 — T062.  Contract: contracts/ubl-signing.md
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

logger = logging.getLogger(__name__)

UBL_NS = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
CAC_NS = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
CBC_NS = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"


class UblValidationError(Exception):
    pass


def build_ubl(invoice: dict, profile: str = "standard") -> str:
    """Build UBL 2.1 XML for an invoice.

    Args:
        invoice: dict with invoice data.
        profile: 'standard' or 'simplified'.

    Returns:
        XML string.

    Raises:
        UblValidationError: if required fields are missing.
    """
    if profile not in ("standard", "simplified"):
        raise UblValidationError(f"Invalid profile: {profile}")

    root = Element(f"{{{UBL_NS}}}Invoice")
    root.set("xmlns", UBL_NS)
    root.set("xmlns:cac", CAC_NS)
    root.set("xmlns:cbc", CBC_NS)

    # Invoice number
    inv_id = invoice.get("invoice_number") or invoice.get("id")
    if not inv_id:
        raise UblValidationError("Invoice number is required")
    _sub(root, CBC_NS, "ID", str(inv_id))

    # Issue date
    _sub(root, CBC_NS, "IssueDate", str(invoice.get("invoice_date", "")))

    # Invoice type code
    type_code = "388" if profile == "standard" else "381"
    _sub(root, CBC_NS, "InvoiceTypeCode", type_code)

    # Currency
    _sub(root, CBC_NS, "DocumentCurrencyCode", invoice.get("currency", "SAR"))

    # Supplier (AccountingSupplierParty)
    _add_party(root, CAC_NS, CBC_NS, "AccountingSupplierParty", invoice.get("supplier", {}))

    # Customer (AccountingCustomerParty)
    _add_party(root, CAC_NS, CBC_NS, "AccountingCustomerParty", invoice.get("customer", {}))

    # Invoice lines
    for i, line in enumerate(invoice.get("lines", []), 1):
        _add_invoice_line(root, CAC_NS, CBC_NS, line, i)

    # Tax total
    tax_total = SubElement(root, f"{{{CAC_NS}}}TaxTotal")
    _sub(tax_total, CBC_NS, "TaxAmount", str(invoice.get("tax_amount", 0)),
         currencyID=invoice.get("currency", "SAR"))

    # Legal monetary total
    legal_total = SubElement(root, f"{{{CAC_NS}}}LegalMonetaryTotal")
    _sub(legal_total, CBC_NS, "LineExtensionAmount", str(invoice.get("subtotal", 0)),
         currencyID=invoice.get("currency", "SAR"))
    _sub(legal_total, CBC_NS, "TaxExclusiveAmount", str(invoice.get("subtotal", 0)),
         currencyID=invoice.get("currency", "SAR"))
    _sub(legal_total, CBC_NS, "TaxInclusiveAmount", str(invoice.get("total", 0)),
         currencyID=invoice.get("currency", "SAR"))
    _sub(legal_total, CBC_NS, "PayableAmount", str(invoice.get("total", 0)),
         currencyID=invoice.get("currency", "SAR"))

    return tostring(root, encoding="unicode", xml_declaration=True)


def _sub(parent: Element, ns: str, tag: str, text: str, **attrs) -> Element:
    el = SubElement(parent, f"{{{ns}}}{tag}")
    el.text = text
    for k, v in attrs.items():
        el.set(k, str(v))
    return el


def _add_party(root: Element, cac_ns: str, cbc_ns: str, tag: str, party: dict) -> None:
    party_el = SubElement(root, f"{{{cac_ns}}}{tag}")
    party_inner = SubElement(party_el, f"{{{cac_ns}}}Party")
    if party.get("name"):
        _sub(party_inner, cbc_ns, "Name", party["name"])
    if party.get("tax_id"):
        party_id = SubElement(party_inner, f"{{{cac_ns}}}PartyIdentification")
        _sub(party_id, cbc_ns, "ID", party["tax_id"])


def _add_invoice_line(root: Element, cac_ns: str, cbc_ns: str, line: dict, line_no: int) -> None:
    inv_line = SubElement(root, f"{{{cac_ns}}}InvoiceLine")
    _sub(inv_line, cbc_ns, "ID", str(line_no))
    _sub(inv_line, cbc_ns, "InvoicedQuantity", str(line.get("qty", 0)))
    _sub(inv_line, cbc_ns, "LineExtensionAmount", str(line.get("subtotal", 0)))
    item = SubElement(inv_line, f"{{{cac_ns}}}Item")
    _sub(item, cbc_ns, "Name", line.get("description", ""))
    price = SubElement(inv_line, f"{{{cac_ns}}}Price")
    _sub(price, cbc_ns, "PriceAmount", str(line.get("unit_price", 0)))
