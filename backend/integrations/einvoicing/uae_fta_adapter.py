"""
UAE Federal Tax Authority (FTA) e-invoicing adapter.

The UAE July 2026 mandate uses **PINT AE** — a Peppol UBL 2.1 profile —
exchanged through **Accredited Service Providers (ASPs)** on the Peppol
5-corner network (corner 1 = supplier ERP, corner 5 = FTA).

This adapter therefore targets the **ASP HTTPS contract** rather than a
direct FTA API:

  POST {asp_endpoint}/invoices                — submit a PINT-AE document
  GET  {asp_endpoint}/invoices/{document_uuid} — pre-clearance status
  POST {asp_endpoint}/invoices/{document_uuid}/cancel — cancellation

Most ASPs accept either:
  * Multipart upload of the signed UBL XML, OR
  * JSON envelope with the XML base64-encoded.

We default to the JSON envelope for simplicity. ASPs that require
multipart can be supported by injecting a custom ``submit_callback``.

Environment / settings keys (per-tenant):
  * UAE_ASP_ENDPOINT   — ASP gateway base URL.
  * UAE_ASP_API_KEY    — bearer / API key issued by the ASP.
  * UAE_SELLER_TRN     — supplier 15-digit TRN.
  * UAE_SELLER_NAME    — supplier legal name.
"""

from __future__ import annotations

import base64
import logging
import os
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any, Callable, List, Optional

import requests

from .base import EInvoiceAdapter, SubmissionResult

logger = logging.getLogger(__name__)


def _xml_escape(v: Any) -> str:
    s = "" if v is None else str(v)
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace("\"", "&quot;"))


def _iso_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%d")
    if isinstance(value, str) and value:
        return value[:10]
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def build_pint_ae_xml(
    invoice: dict,
    *,
    seller_trn: str,
    seller_name: str,
) -> str:
    """Build a minimal PINT-AE UBL 2.1 invoice XML.

    Required ``invoice`` keys: ``invoice_number``, ``issue_date``,
    ``customer_name``, ``customer_trn`` (or ``customer_tax_id``),
    ``currency``, ``lines`` (list with ``description``, ``quantity``,
    ``unit_price``, ``tax_amount``, optional ``tax_rate``).

    The output is a structurally valid UBL document; the real ASP/Peppol
    transport layer will further wrap it in an SBDH envelope and apply
    XAdES signatures using the supplier's certificate.
    """
    inv_id = invoice.get("invoice_number") or invoice.get("id") or str(_uuid.uuid4())
    issue_date = _iso_date(invoice.get("issue_date") or invoice.get("issued_at"))
    currency = invoice.get("currency") or "AED"

    customer_trn = invoice.get("customer_trn") or invoice.get("customer_tax_id") or ""
    customer_name = invoice.get("customer_name") or ""
    customer_country = invoice.get("customer_country") or "AE"

    line_total = 0.0
    tax_total = 0.0
    line_xml = []
    for idx, ln in enumerate(invoice.get("lines") or [], start=1):
        qty = float(ln.get("quantity") or 0)
        unit_price = float(ln.get("unit_price") or 0)
        tax_amt = float(ln.get("tax_amount") or 0)
        tax_rate = float(ln.get("tax_rate") or 5)        # default UAE VAT 5%
        net = qty * unit_price - float(ln.get("discount") or 0)
        line_total += net
        tax_total += tax_amt
        desc = _xml_escape(ln.get("description") or ln.get("item_name") or f"Item {idx}")
        line_xml.append(f"""<cac:InvoiceLine>
  <cbc:ID>{idx}</cbc:ID>
  <cbc:InvoicedQuantity unitCode="EA">{qty:.4f}</cbc:InvoicedQuantity>
  <cbc:LineExtensionAmount currencyID="{currency}">{net:.2f}</cbc:LineExtensionAmount>
  <cac:Item><cbc:Name>{desc}</cbc:Name>
    <cac:ClassifiedTaxCategory><cbc:ID>S</cbc:ID>
      <cbc:Percent>{tax_rate:.2f}</cbc:Percent>
      <cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>
    </cac:ClassifiedTaxCategory></cac:Item>
  <cac:Price><cbc:PriceAmount currencyID="{currency}">{unit_price:.4f}</cbc:PriceAmount></cac:Price>
</cac:InvoiceLine>""")

    grand_total = float(invoice.get("total") or (line_total + tax_total))

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:CustomizationID>urn:peppol:pint:billing-1@ae-1</cbc:CustomizationID>
  <cbc:ProfileID>urn:peppol:bis:billing</cbc:ProfileID>
  <cbc:ID>{_xml_escape(inv_id)}</cbc:ID>
  <cbc:IssueDate>{issue_date}</cbc:IssueDate>
  <cbc:InvoiceTypeCode>388</cbc:InvoiceTypeCode>
  <cbc:DocumentCurrencyCode>{currency}</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyTaxScheme>
      <cbc:CompanyID>{_xml_escape(seller_trn)}</cbc:CompanyID>
      <cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>
    </cac:PartyTaxScheme>
    <cac:PartyLegalEntity><cbc:RegistrationName>{_xml_escape(seller_name)}</cbc:RegistrationName></cac:PartyLegalEntity>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    <cac:PartyTaxScheme>
      <cbc:CompanyID>{_xml_escape(customer_trn)}</cbc:CompanyID>
      <cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>
    </cac:PartyTaxScheme>
    <cac:PartyLegalEntity><cbc:RegistrationName>{_xml_escape(customer_name)}</cbc:RegistrationName></cac:PartyLegalEntity>
    <cac:Country><cbc:IdentificationCode>{_xml_escape(customer_country)}</cbc:IdentificationCode></cac:Country>
  </cac:Party></cac:AccountingCustomerParty>
  <cac:TaxTotal>
    <cbc:TaxAmount currencyID="{currency}">{tax_total:.2f}</cbc:TaxAmount>
    <cac:TaxSubtotal>
      <cbc:TaxableAmount currencyID="{currency}">{line_total:.2f}</cbc:TaxableAmount>
      <cbc:TaxAmount currencyID="{currency}">{tax_total:.2f}</cbc:TaxAmount>
      <cac:TaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>5.00</cbc:Percent>
        <cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:TaxCategory>
    </cac:TaxSubtotal>
  </cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="{currency}">{line_total:.2f}</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="{currency}">{line_total:.2f}</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="{currency}">{grand_total:.2f}</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="{currency}">{grand_total:.2f}</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  {''.join(line_xml)}
</Invoice>"""


class UAEFTAAdapter(EInvoiceAdapter):
    """UAE FTA adapter via Peppol-AE Accredited Service Provider."""

    jurisdiction = "AE"

    def __init__(
        self,
        asp_endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        seller_trn: Optional[str] = None,
        seller_name: Optional[str] = None,
        dry_run: bool = True,
        signer: Optional[Callable[[str], str]] = None,
        timeout: float = 30.0,
    ):
        self.asp_endpoint = (asp_endpoint or os.getenv("UAE_ASP_ENDPOINT", "")).rstrip("/")
        self.api_key = api_key or os.getenv("UAE_ASP_API_KEY", "")
        self.seller_trn = seller_trn or os.getenv("UAE_SELLER_TRN", "")
        self.seller_name = seller_name or os.getenv("UAE_SELLER_NAME", "")
        # Auto-flip to dry_run when essentials missing.
        self.dry_run = dry_run or not (self.asp_endpoint and self.api_key and self.seller_trn)
        self._signer = signer
        self._timeout = timeout

    # ─── document build + sign ─────────────────────────────────────────

    def build_document(self, invoice: dict) -> str:
        xml = build_pint_ae_xml(
            invoice, seller_trn=self.seller_trn, seller_name=self.seller_name,
        )
        if self._signer:
            try:
                xml = self._signer(xml)
            except Exception:
                logger.exception("[UAE-FTA] signer callback failed; submitting unsigned")
        return xml

    # ─── public API ────────────────────────────────────────────────────

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"}

    def submit(self, invoice: dict) -> SubmissionResult:
        xml = self.build_document(invoice)
        if self.dry_run:
            doc_uuid = f"dryrun-ae-{_uuid.uuid4()}"
            logger.info("[UAE-FTA dry_run] would submit invoice %s as %s",
                        invoice.get("id"), doc_uuid)
            return SubmissionResult(
                status="submitted",
                document_uuid=doc_uuid,
                response={"dry_run": True, "xml_size": len(xml)},
            )
        url = f"{self.asp_endpoint}/invoices"
        payload = {
            "documentType": "Invoice",
            "documentFormat": "UBL",
            "supplierTrn": self.seller_trn,
            "documentBase64": base64.b64encode(xml.encode("utf-8")).decode("ascii"),
            "internalId": str(invoice.get("invoice_number") or invoice.get("id") or ""),
        }
        try:
            resp = requests.post(url, json=payload, headers=self._auth_headers(),
                                 timeout=self._timeout)
        except requests.RequestException as e:
            logger.exception("[UAE-FTA] HTTP error during submission")
            return SubmissionResult(status="error", error_message=str(e))
        if resp.status_code >= 400:
            logger.warning("[UAE-FTA] ASP rejected (%s): %s",
                           resp.status_code, resp.text[:500])
            return SubmissionResult(
                status="rejected",
                response={"status_code": resp.status_code, "body": resp.text[:2000]},
                error_message=f"HTTP {resp.status_code}",
            )
        body = resp.json() if resp.text else {}
        # Most ASPs return: {documentUuid, status: 'accepted'|'pending'|...}
        return SubmissionResult(
            status=(body.get("status") or "submitted").lower(),
            document_uuid=body.get("documentUuid") or body.get("uuid"),
            response=body,
        )

    def fetch_status(self, document_uuid: str) -> SubmissionResult:
        if self.dry_run:
            return SubmissionResult(status="accepted", document_uuid=document_uuid,
                                    response={"dry_run": True})
        url = f"{self.asp_endpoint}/invoices/{document_uuid}"
        try:
            resp = requests.get(url, headers=self._auth_headers(), timeout=self._timeout)
        except requests.RequestException as e:
            return SubmissionResult(status="error", document_uuid=document_uuid,
                                    error_message=str(e))
        if resp.status_code >= 400:
            return SubmissionResult(
                status="error",
                document_uuid=document_uuid,
                error_message=f"HTTP {resp.status_code}: {resp.text[:300]}",
            )
        body = resp.json() if resp.text else {}
        return SubmissionResult(
            status=(body.get("status") or "submitted").lower(),
            document_uuid=document_uuid,
            response=body,
        )

    def cancel(self, document_uuid: str, reason: str) -> SubmissionResult:
        if self.dry_run:
            return SubmissionResult(status="accepted", document_uuid=document_uuid,
                                    response={"dry_run": True, "cancelled": True,
                                              "reason": reason})
        url = f"{self.asp_endpoint}/invoices/{document_uuid}/cancel"
        try:
            resp = requests.post(url, json={"reason": reason},
                                 headers=self._auth_headers(),
                                 timeout=self._timeout)
        except requests.RequestException as e:
            return SubmissionResult(status="error", document_uuid=document_uuid,
                                    error_message=str(e))
        if resp.status_code >= 400:
            return SubmissionResult(
                status="error",
                document_uuid=document_uuid,
                error_message=f"HTTP {resp.status_code}: {resp.text[:300]}",
            )
        return SubmissionResult(status="accepted", document_uuid=document_uuid,
                                response=resp.json() if resp.text else {})
