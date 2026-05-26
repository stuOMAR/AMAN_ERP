"""
ZATCA (Saudi Arabia) Phase 2 e-invoicing adapter.

Scope (what this adapter does):
  * Build the ZATCA TLV QR payload (IRN tag 1..5) per the "Simplified
    tax invoice QR" spec.
  * Produce a minimal UBL 2.1 invoice XML compliant with the ZATCA
    data dictionary.
  * Compute the SHA-256 invoice hash + Previous Invoice Hash chain
    (the 'PIH' used in the <cac:AdditionalDocumentReference> block).
  * Provide the HTTPS submission contract to ZATCA's Clearance /
    Reporting endpoints.

Deliberately out of scope here:
  * CSR/Compliance CSID onboarding (tenant-specific; happens once via
    the ZATCA portal + a CLI step, keys are loaded from settings).
  * XMLDSig detached signature (requires the tenant's private key &
    PCSID; implemented as a hook — `_sign_xml` — that calls an
    injected signer callback).

Environment / settings keys consumed (per-tenant, via company_settings):
  * zatca.api_base        (default: https://gw-fatoora.zatca.gov.sa/e-invoicing/core)
  * zatca.pcsid           (Production CSID after onboarding)
  * zatca.secret          (Production secret for HTTP Basic auth)
  * zatca.seller_name
  * zatca.seller_vat
  * zatca.signer          (optional callable; when set, used to sign the
                           UBL XML before submission)

Phases:
  * "report" — simplified invoice (B2C) → POST /reporting/single
  * "clear"  — standard invoice (B2B)   → POST /invoices/clearance/single
"""

from __future__ import annotations

import base64
import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, Optional

import requests

from .base import EInvoiceAdapter, SubmissionResult
from utils.tax_precision import money_str, qty_str, dec

logger = logging.getLogger(__name__)

_DEFAULT_API_BASE = "https://gw-fatoora.zatca.gov.sa/e-invoicing/core"


# ═══════════════════════════════════════════════════════════════════════════
# TLV (Tag-Length-Value) QR encoder — required on every ZATCA invoice.
# ═══════════════════════════════════════════════════════════════════════════

def _tlv(tag: int, value: str) -> bytes:
    """Encode a single TLV triplet.

    Tags 1..5 are mandatory for Phase 1 simplified invoices; Phase 2 adds
    tags 6..9 (hash, signature, public key, certificate signature).
    """
    encoded = value.encode("utf-8")
    return bytes([tag, len(encoded)]) + encoded


def build_qr_payload(
    seller_name: str,
    seller_vat: str,
    timestamp,
    total_with_vat: Any,
    vat_amount: Any,
    invoice_hash: Optional[str] = None,
    ecdsa_signature: Optional[bytes] = None,
    public_key: Optional[bytes] = None,
    certificate_signature: Optional[bytes] = None,
) -> str:
    """Return the base64-encoded TLV QR payload for a ZATCA invoice.

    ``timestamp`` may be a ``datetime`` or an ISO-8601 string
    (``YYYY-MM-DDTHH:MM:SSZ``). Anything else is coerced via ``str()``.
    """
    if isinstance(timestamp, datetime):
        ts = timestamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        ts = str(timestamp)
    parts = [
        _tlv(1, seller_name),
        _tlv(2, seller_vat),
        _tlv(3, ts),
        _tlv(4, money_str(total_with_vat)),
        _tlv(5, money_str(vat_amount)),
    ]
    # Phase 2 extensions (only included if caller supplied them).
    if invoice_hash:
        parts.append(_tlv(6, invoice_hash))
    if ecdsa_signature:
        parts.append(bytes([7, len(ecdsa_signature)]) + ecdsa_signature)
    if public_key:
        parts.append(bytes([8, len(public_key)]) + public_key)
    if certificate_signature:
        parts.append(bytes([9, len(certificate_signature)]) + certificate_signature)
    return base64.b64encode(b"".join(parts)).decode("ascii")


# ═══════════════════════════════════════════════════════════════════════════
# UBL 2.1 XML — minimal, ZATCA-compliant skeleton.
# ═══════════════════════════════════════════════════════════════════════════

def _xml_escape(v: Any) -> str:
    s = "" if v is None else str(v)
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace("\"", "&quot;"))


def _parse_issue_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _gregorian_to_hijri(gregorian_date: date) -> str:
    year = gregorian_date.year
    month = gregorian_date.month
    day = gregorian_date.day
    if month < 3:
        year -= 1
        month += 12
    century = year // 100
    correction = 2 - century + (century // 4)
    julian_day = (
        int(365.25 * (year + 4716))
        + int(30.6001 * (month + 1))
        + day
        + correction
        - 1524
    )
    lunar_days = julian_day - 1948440 + 10632
    cycle = (lunar_days - 1) // 10631
    lunar_days = lunar_days - (10631 * cycle) + 354
    adjustment = (
        ((10985 - lunar_days) // 5316) * ((50 * lunar_days) // 17719)
        + (lunar_days // 5670) * ((43 * lunar_days) // 15238)
    )
    lunar_days = (
        lunar_days
        - ((30 - adjustment) // 15) * ((17719 * adjustment) // 50)
        - (adjustment // 16) * ((15238 * adjustment) // 43)
        + 29
    )
    hijri_month = (24 * lunar_days) // 709
    hijri_day = lunar_days - (709 * hijri_month) // 24
    hijri_year = (30 * cycle) + adjustment - 30
    return f"{hijri_year:04d}-{hijri_month:02d}-{hijri_day:02d}"


def _hijri_issue_note(invoice: dict) -> str:
    hijri_date = invoice.get("hijri_date") or invoice.get("hijri_issue_date")
    if not hijri_date:
        issue_date = _parse_issue_date(invoice.get("invoice_date"))
        if issue_date:
            hijri_date = _gregorian_to_hijri(issue_date)
    if not hijri_date:
        return ""
    return f"\n  <cbc:Note>HIJRI:{_xml_escape(hijri_date)}</cbc:Note>"


def build_ubl_xml(invoice: dict, seller_name: str, seller_vat: str,
                  previous_invoice_hash: str = "") -> str:
    """Build a minimal UBL 2.1 invoice.

    Expected `invoice` keys:
      invoice_number, invoice_date (ISO), invoice_type_code (388=tax, 381=credit),
      currency (default SAR), customer_name, customer_vat (optional),
      lines=[{description, quantity, unit_price, tax_rate, line_total, tax_amount}],
      subtotal, tax_total, grand_total.
    """
    hijri_issue_note = _hijri_issue_note(invoice)
    lines_xml = []
    for idx, line in enumerate(invoice.get("lines") or [], start=1):
        lines_xml.append(f"""
    <cac:InvoiceLine>
      <cbc:ID>{idx}</cbc:ID>
      <cbc:InvoicedQuantity unitCode="PCE">{qty_str(line.get("quantity") or 0)}</cbc:InvoicedQuantity>
      <cbc:LineExtensionAmount currencyID="{_xml_escape(invoice.get("currency", "SAR"))}">{money_str(line.get("line_total") or 0)}</cbc:LineExtensionAmount>
      <cac:TaxTotal>
        <cbc:TaxAmount currencyID="{_xml_escape(invoice.get("currency", "SAR"))}">{money_str(line.get("tax_amount") or 0)}</cbc:TaxAmount>
        <cbc:RoundingAmount currencyID="{_xml_escape(invoice.get("currency", "SAR"))}">{money_str(dec(line.get("line_total") or 0) + dec(line.get("tax_amount") or 0))}</cbc:RoundingAmount>
      </cac:TaxTotal>
      <cac:Item>
        <cbc:Name>{_xml_escape(line.get("description"))}</cbc:Name>
        <cac:ClassifiedTaxCategory>
          <cbc:ID>S</cbc:ID>
          <cbc:Percent>{money_str(line.get("tax_rate") or 0)}</cbc:Percent>
          <cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>
        </cac:ClassifiedTaxCategory>
      </cac:Item>
      <cac:Price>
        <cbc:PriceAmount currencyID="{_xml_escape(invoice.get("currency", "SAR"))}">{money_str(line.get("unit_price") or 0)}</cbc:PriceAmount>
      </cac:Price>
    </cac:InvoiceLine>""")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ProfileID>reporting:1.0</cbc:ProfileID>
  <cbc:ID>{_xml_escape(invoice.get("invoice_number"))}</cbc:ID>
  <cbc:UUID>{_xml_escape(invoice.get("uuid") or invoice.get("invoice_number"))}</cbc:UUID>
  <cbc:IssueDate>{_xml_escape(invoice.get("invoice_date"))}</cbc:IssueDate>{hijri_issue_note}
  <cbc:IssueTime>{_xml_escape(invoice.get("invoice_time") or "00:00:00")}</cbc:IssueTime>
  <cbc:InvoiceTypeCode name="0200000">{_xml_escape(invoice.get("invoice_type_code") or "388")}</cbc:InvoiceTypeCode>
  <cbc:DocumentCurrencyCode>{_xml_escape(invoice.get("currency", "SAR"))}</cbc:DocumentCurrencyCode>
  <cbc:TaxCurrencyCode>SAR</cbc:TaxCurrencyCode>
  <cac:AdditionalDocumentReference>
    <cbc:ID>ICV</cbc:ID>
    <cbc:UUID>{_xml_escape(invoice.get("icv") or 1)}</cbc:UUID>
  </cac:AdditionalDocumentReference>
  <cac:AdditionalDocumentReference>
    <cbc:ID>PIH</cbc:ID>
    <cac:Attachment>
      <cbc:EmbeddedDocumentBinaryObject mimeCode="text/plain">{_xml_escape(previous_invoice_hash or "0")}</cbc:EmbeddedDocumentBinaryObject>
    </cac:Attachment>
  </cac:AdditionalDocumentReference>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyIdentification><cbc:ID schemeID="CRN">{_xml_escape(invoice.get("seller_crn") or "")}</cbc:ID></cac:PartyIdentification>
      <cac:PartyTaxScheme>
        <cbc:CompanyID>{_xml_escape(seller_vat)}</cbc:CompanyID>
        <cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>
      </cac:PartyTaxScheme>
      <cac:PartyLegalEntity><cbc:RegistrationName>{_xml_escape(seller_name)}</cbc:RegistrationName></cac:PartyLegalEntity>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty>
    <cac:Party>
      <cac:PartyTaxScheme>
        <cbc:CompanyID>{_xml_escape(invoice.get("customer_vat") or "")}</cbc:CompanyID>
        <cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>
      </cac:PartyTaxScheme>
      <cac:PartyLegalEntity><cbc:RegistrationName>{_xml_escape(invoice.get("customer_name") or "")}</cbc:RegistrationName></cac:PartyLegalEntity>
    </cac:Party>
  </cac:AccountingCustomerParty>
  <cac:TaxTotal>
    <cbc:TaxAmount currencyID="{_xml_escape(invoice.get("currency", "SAR"))}">{money_str(invoice.get("tax_total") or 0)}</cbc:TaxAmount>
  </cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="{_xml_escape(invoice.get("currency", "SAR"))}">{money_str(invoice.get("subtotal") or 0)}</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="{_xml_escape(invoice.get("currency", "SAR"))}">{money_str(invoice.get("subtotal") or 0)}</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="{_xml_escape(invoice.get("currency", "SAR"))}">{money_str(invoice.get("grand_total") or 0)}</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="{_xml_escape(invoice.get("currency", "SAR"))}">{money_str(invoice.get("grand_total") or 0)}</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  {"".join(lines_xml)}
</Invoice>"""
    return xml


def invoice_hash(xml: str) -> str:
    """ZATCA-spec SHA-256 of UBL XML, base64-encoded."""
    return base64.b64encode(hashlib.sha256(xml.encode("utf-8")).digest()).decode("ascii")


# ═══════════════════════════════════════════════════════════════════════════
# Adapter
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ZATCAConfig:
    api_base: str = _DEFAULT_API_BASE
    pcsid: Optional[str] = None
    secret: Optional[str] = None
    seller_name: str = ""
    seller_vat: str = ""
    seller_crn: Optional[str] = None
    signer: Optional[Callable[[str, "ZATCAConfig"], str]] = None
    phase: str = "report"          # report | clear
    timeout_seconds: int = 30
    verify_ssl: bool = True


class ZATCAAdapter(EInvoiceAdapter):
    jurisdiction = "SA"

    def __init__(self, config: Optional[ZATCAConfig] = None, **kwargs):
        self.config = config or ZATCAConfig(**kwargs)

    # -- building blocks --------------------------------------------------
    def build_document(self, invoice: dict, previous_invoice_hash: str = "") -> Dict[str, Any]:
        xml = build_ubl_xml(invoice, self.config.seller_name,
                            self.config.seller_vat, previous_invoice_hash)
        if self.config.signer:
            xml = self.config.signer(xml, self.config)
        ihash = invoice_hash(xml)
        ts = invoice.get("issued_at") or datetime.now(timezone.utc)
        if isinstance(ts, str):
            # best-effort parse; fall back to now.
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                ts = datetime.now(timezone.utc)
        qr = build_qr_payload(
            seller_name=self.config.seller_name,
            seller_vat=self.config.seller_vat,
            timestamp=ts,
            total_with_vat=invoice.get("grand_total") or 0,
            vat_amount=invoice.get("tax_total") or 0,
            invoice_hash=ihash,
        )
        return {"xml": xml, "hash": ihash, "qr": qr}

    # -- EInvoiceAdapter surface -----------------------------------------
    def submit(self, invoice: dict) -> SubmissionResult:
        try:
            built = self.build_document(invoice,
                                        previous_invoice_hash=invoice.get("pih", ""))
        except Exception as e:
            logger.exception("ZATCA build_document failed")
            return SubmissionResult(status="error", error_message=f"build_error: {e}")

        # If no PCSID/secret configured, run in offline mode: return the
        # locally-built artefacts so the caller can persist them and submit
        # manually / later via the ZATCA portal.
        if not (self.config.pcsid and self.config.secret):
            return SubmissionResult(
                status="submitted",
                document_uuid=invoice.get("uuid") or invoice.get("invoice_number"),
                response={"offline": True, "qr": built["qr"], "hash": built["hash"]},
            )

        payload = {
            "invoiceHash": built["hash"],
            "uuid": invoice.get("uuid") or invoice.get("invoice_number"),
            "invoice": base64.b64encode(built["xml"].encode("utf-8")).decode("ascii"),
        }
        endpoint = "/invoices/reporting/single" if self.config.phase == "report" else "/invoices/clearance/single"
        # EINV-F1: bounded exponential-backoff retry on transient failures
        # (network errors and 5xx). Terminal 4xx responses are not retried.
        max_attempts = int(getattr(self.config, "max_retries", 3) or 3)
        backoff_base = dec(getattr(self.config, "retry_backoff_seconds", "1.5") or "1.5")
        last_exc: Optional[Exception] = None
        for attempt in range(1, max_attempts + 1):
            try:
                headers = {"Accept-Version": "V2", "Content-Type": "application/json"}
                if invoice.get("idempotency_key"):
                    headers["Idempotency-Key"] = str(invoice["idempotency_key"])
                r = requests.post(
                    self.config.api_base.rstrip("/") + endpoint,
                    json=payload,
                    auth=(self.config.pcsid, self.config.secret),
                    headers=headers,
                    timeout=self.config.timeout_seconds,
                    verify=self.config.verify_ssl,
                )
                ok = r.status_code in (200, 202)
                retriable = r.status_code in (408, 429, 500, 502, 503, 504)
                body = r.json() if "application/json" in (r.headers.get("Content-Type") or "") else {"raw": r.text}

                if retriable and attempt < max_attempts:
                    sleep_for = backoff_base * (2 ** (attempt - 1))
                    logger.warning(
                        "ZATCA transient HTTP %s (attempt %s/%s); retrying in %ss",
                        r.status_code, attempt, max_attempts, sleep_for,
                    )
                    time.sleep(int(sleep_for * dec(1000)) / 1000)
                    continue

                return SubmissionResult(
                    status="accepted" if ok else "rejected",
                    document_uuid=payload["uuid"],
                    response={"http_status": r.status_code, "body": body, "qr": built["qr"],
                              "hash": built["hash"], "attempts": attempt},
                    error_message=None if ok else f"HTTP {r.status_code}",
                )
            except requests.RequestException as e:
                last_exc = e
                if attempt < max_attempts:
                    sleep_for = backoff_base * (2 ** (attempt - 1))
                    logger.warning(
                        "ZATCA network error (attempt %s/%s): %s — retrying in %ss",
                        attempt, max_attempts, e, sleep_for,
                    )
                    time.sleep(int(sleep_for * dec(1000)) / 1000)
                    continue
                logger.exception("ZATCA submit failed after %s attempts", attempt)
                return SubmissionResult(
                    status="error",
                    error_message=f"{e} (after {attempt} attempts)",
                )
        # Unreachable, but keeps the type checker happy.
        return SubmissionResult(status="error", error_message=str(last_exc) if last_exc else "unknown")

    def fetch_status(self, document_uuid: str) -> SubmissionResult:
        # ZATCA's real-time clearance is synchronous; this is a stub for
        # parity with the other adapters.
        return SubmissionResult(status="accepted", document_uuid=document_uuid,
                                response={"note": "ZATCA is synchronous — see submit() response"})
