"""
Egypt Tax Authority (ETA) e-invoicing adapter.

Implements:
  * OAuth client-credentials token acquisition (cached until expiry).
  * Mapping of an invoice dict → ETA's JSON document schema.
  * Optional document signing via an injected ``signer`` callback (the
    real CMS/USB-token signer is tenant-specific and lives outside the ERP).
  * HTTPS submission to the configured ETA endpoint.
  * Status polling via ``GET /documents/{uuid}/details``.

Environment / settings keys (per-tenant):
  * ETA_BASE_URL            — defaults to the production gateway.
  * ETA_TOKEN_URL           — OAuth token endpoint (id-server).
  * ETA_CLIENT_ID / SECRET  — OAuth credentials.
  * ETA_ISSUER_ID / TYPE    — seller registration metadata.
  * ETA_ACTIVITY_CODE       — tenant's activity code.

Reference: https://sdk.invoicing.eta.gov.eg/document-signing/
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any, Callable, List, Optional

import requests

from .base import EInvoiceAdapter, SubmissionResult

logger = logging.getLogger(__name__)

from utils.masking import redact_token  # noqa: E402
from utils.tax_precision import dec as _dec, q_money, q_qty, q_rate, money_str, qty_str, rate_str  # noqa: E402

_DEFAULT_BASE_URL = "https://api.invoicing.eta.gov.eg"
_DEFAULT_TOKEN_URL = "https://id.eta.gov.eg/connect/token"


def _iso_utc(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, str) and value:
        return value
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_eta_document(
    invoice: dict,
    *,
    issuer_id: str,
    issuer_name: str,
    issuer_type: str = "B",
    activity_code: str = "",
) -> dict:
    """Map an internal invoice dict to ETA's documentsubmissions schema.

    Required ``invoice`` fields: ``invoice_number`` (or ``id``), ``issue_date``,
    ``customer_name``, ``customer_tax_id``, ``currency``, ``lines`` (list of
    dicts with ``description``, ``quantity``, ``unit_price``, ``tax_amount``).
    """
    lines: List[dict] = []
    # Keep the inputs in Decimal end-to-end and serialize monetary/rate/qty
    # values as fixed decimal strings so JSON payloads cannot reintroduce
    # binary floating-point rounding.
    from decimal import Decimal as _Decimal
    total_sales = _Decimal("0")
    total_tax = _Decimal("0")
    total_discount = _Decimal("0")
    currency = invoice.get("currency") or "EGP"
    fx_rate = q_rate(invoice.get("exchange_rate") or 1)
    for idx, ln in enumerate(invoice.get("lines") or [], start=1):
        # Compute first, quantize last: ``unit_price`` is held at full
        # Decimal precision through the multiplication so high-precision
        # prices (e.g. 1.2345 EGP) do not lose accuracy before the
        # ``salesTotal`` and ``netTotal`` quantization steps.
        qty = q_qty(ln.get("quantity") or 0)
        unit_price = _dec(ln.get("unit_price") or 0)
        sales = qty * unit_price
        discount = _dec(ln.get("discount") or 0)
        tax_amt = q_money(ln.get("tax_amount") or 0)
        tax_rate = q_rate(ln.get("tax_rate") or 0)
        net = sales - discount
        total_sales += sales
        total_discount += discount
        total_tax += tax_amt
        lines.append({
            "description": ln.get("description") or ln.get("item_name") or f"Item {idx}",
            "itemType": ln.get("item_type") or "GS1",
            "itemCode": str(ln.get("item_code") or ln.get("sku") or ""),
            "unitType": ln.get("unit_type") or "EA",
            "quantity": qty_str(qty),
            "internalCode": str(ln.get("internal_code") or ""),
            "salesTotal": {"currencySold": currency, "amountEGP": money_str(sales)},
            "total": money_str(net + tax_amt),
            "valueDifference": 0,
            "totalTaxableFees": 0,
            "netTotal": {"currencySold": currency, "amountEGP": money_str(net)},
            "itemsDiscount": 0,
            "discount": {"rate": "0.0000", "amount": money_str(discount)},
            "taxableItems": [{
                "taxType": "T1",        # T1 = VAT
                "amount": money_str(tax_amt),
                "subType": "V001",
                "rate": rate_str(tax_rate),
            }],
            "unitValue": {"currencySold": currency,
                          "amountEGP": money_str(unit_price),
                          "currencyExchangeRate": rate_str(fx_rate)},
        })

    # ``total`` / ``net_total`` / ``vat_amount`` may be supplied
    # explicitly by the caller (e.g. the GL-derived figures); honour
    # those when present and otherwise rebuild from the per-line
    # Decimals so the wire totals are auditable against the JE.
    grand_total = q_money(invoice.get("total")) if invoice.get("total") is not None else q_money(total_sales - total_discount + total_tax)
    net_total = q_money(invoice.get("net_total")) if invoice.get("net_total") is not None else q_money(total_sales - total_discount)
    vat_total = q_money(invoice.get("vat_amount")) if invoice.get("vat_amount") is not None else q_money(total_tax)

    return {
        "issuer": {
            "address": invoice.get("seller_address") or {},
            "type": issuer_type,
            "id": issuer_id,
            "name": issuer_name,
        },
        "receiver": {
            "address": invoice.get("customer_address") or {},
            "type": invoice.get("customer_type") or "B",
            "id": invoice.get("customer_tax_id") or "",
            "name": invoice.get("customer_name") or "",
        },
        "documentType": invoice.get("document_type") or "I",
        "documentTypeVersion": "1.0",
        "dateTimeIssued": _iso_utc(invoice.get("issue_date") or invoice.get("issued_at")),
        "taxpayerActivityCode": activity_code,
        "internalID": str(invoice.get("invoice_number") or invoice.get("id") or _uuid.uuid4()),
        "purchaseOrderReference": str(invoice.get("po_reference") or ""),
        "purchaseOrderDescription": invoice.get("po_description") or "",
        "salesOrderReference": str(invoice.get("sales_order_ref") or ""),
        "proformaInvoiceNumber": str(invoice.get("proforma_number") or ""),
        "totalDiscountAmount": money_str(total_discount),
        "totalSalesAmount": money_str(total_sales),
        "netAmount": money_str(net_total),
        "taxTotals": [{"taxType": "T1", "amount": money_str(vat_total)}],
        "totalAmount": money_str(grand_total),
        "extraDiscountAmount": 0,
        "totalItemsDiscountAmount": 0,
        "invoiceLines": lines,
        "signatures": [],
    }


class EgyptETAAdapter(EInvoiceAdapter):
    """ETA adapter — supports dry-run and live submission."""

    jurisdiction = "EG"

    def __init__(
        self,
        base_url: Optional[str] = None,
        token_url: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        issuer_id: Optional[str] = None,
        issuer_name: Optional[str] = None,
        issuer_type: str = "B",
        activity_code: Optional[str] = None,
        dry_run: bool = True,
        signer: Optional[Callable[[dict], List[dict]]] = None,
        timeout: float = 30.0,
    ):
        self.base_url = (base_url or os.getenv("ETA_BASE_URL", _DEFAULT_BASE_URL)).rstrip("/")
        self.token_url = token_url or os.getenv("ETA_TOKEN_URL", _DEFAULT_TOKEN_URL)
        self.client_id = client_id or os.getenv("ETA_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("ETA_CLIENT_SECRET", "")
        self.issuer_id = issuer_id or os.getenv("ETA_ISSUER_ID", "")
        self.issuer_name = issuer_name or os.getenv("ETA_ISSUER_NAME", "")
        self.issuer_type = issuer_type or os.getenv("ETA_ISSUER_TYPE", "B")
        self.activity_code = activity_code or os.getenv("ETA_ACTIVITY_CODE", "")
        # Auto-flip to dry_run when essential credentials are missing.
        self.dry_run = dry_run or not (self.client_id and self.client_secret and self.issuer_id)
        self._signer = signer
        self._timeout = timeout
        self._token: Optional[str] = None
        self._token_exp: float = 0.0

    # ─── auth ───────────────────────────────────────────────────────────

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_exp - 30:
            return self._token
        resp = requests.post(
            self.token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "InvoicingAPI",
            },
            timeout=self._timeout,
        )
        resp.raise_for_status()
        body = resp.json()
        self._token = body["access_token"]
        self._token_exp = time.time() + int(_dec(body.get("expires_in", 3600)))
        return self._token

    # ─── document build + sign ─────────────────────────────────────────

    def build_document(self, invoice: dict) -> dict:
        doc = build_eta_document(
            invoice,
            issuer_id=self.issuer_id,
            issuer_name=self.issuer_name,
            issuer_type=self.issuer_type,
            activity_code=self.activity_code,
        )
        if self._signer:
            try:
                doc["signatures"] = list(self._signer(doc))
            except Exception:
                logger.exception("[ETA] signer callback failed; submitting unsigned")
        return doc

    # ─── public API ────────────────────────────────────────────────────

    def submit(self, invoice: dict) -> SubmissionResult:
        document = self.build_document(invoice)
        if self.dry_run:
            doc_uuid = f"dryrun-eta-{_uuid.uuid4()}"
            logger.info("[ETA dry_run] would submit invoice %s as %s",
                        invoice.get("id"), doc_uuid)
            return SubmissionResult(
                status="submitted",
                document_uuid=doc_uuid,
                response={"dry_run": True, "document_preview": document},
            )
        url = f"{self.base_url}/api/v1/documentsubmissions"
        try:
            token = self._get_token()
            # Audit F-NEW-001: never echo the raw bearer token in logs.
            logger.debug("[ETA] submit invoice=%s auth=%s",
                         invoice.get("id"), redact_token(token))
            resp = requests.post(
                url,
                json={"documents": [document]},
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json"},
                timeout=self._timeout,
            )
        except requests.RequestException as e:
            # Use a redacted log message so any logging hook that walks the
            # exception chain cannot reach the token via the request object.
            logger.warning("[ETA] HTTP error during submission: %s", str(e)[:500])
            return SubmissionResult(status="error", error_message=str(e))
        if resp.status_code >= 400:
            logger.warning("[ETA] submission rejected (%s): %s",
                           resp.status_code, resp.text[:500])
            return SubmissionResult(
                status="rejected",
                response={"status_code": resp.status_code, "body": resp.text[:2000]},
                error_message=f"HTTP {resp.status_code}",
            )
        body = resp.json()
        accepted = (body.get("acceptedDocuments") or [{}])[0]
        rejected = body.get("rejectedDocuments") or []
        if rejected:
            return SubmissionResult(
                status="rejected",
                response=body,
                error_message=json.dumps(rejected[0])[:500],
            )
        return SubmissionResult(
            status="submitted",
            document_uuid=accepted.get("uuid") or body.get("submissionId"),
            response=body,
        )

    def fetch_status(self, document_uuid: str) -> SubmissionResult:
        if self.dry_run:
            return SubmissionResult(status="accepted", document_uuid=document_uuid,
                                    response={"dry_run": True})
        url = f"{self.base_url}/api/v1/documents/{document_uuid}/details"
        try:
            token = self._get_token()
            # Audit F-NEW-002: never echo the raw bearer token in logs.
            logger.debug("[ETA] fetch_status uuid=%s auth=%s",
                         document_uuid, redact_token(token))
            resp = requests.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=self._timeout,
            )
        except requests.RequestException as e:
            logger.warning("[ETA] HTTP error during fetch_status: %s", str(e)[:500])
            return SubmissionResult(status="error", document_uuid=document_uuid,
                                    error_message=str(e))
        if resp.status_code >= 400:
            return SubmissionResult(
                status="error",
                document_uuid=document_uuid,
                error_message=f"HTTP {resp.status_code}: {resp.text[:300]}",
            )
        body = resp.json()
        eta_status = (body.get("status") or "").lower()
        normalised = {
            "valid": "accepted",
            "submitted": "submitted",
            "invalid": "rejected",
            "rejected": "rejected",
            "cancelled": "rejected",
        }.get(eta_status, eta_status or "submitted")
        return SubmissionResult(
            status=normalised,
            document_uuid=document_uuid,
            response=body,
        )

    def cancel(self, document_uuid: str, reason: str) -> SubmissionResult:
        if self.dry_run:
            return SubmissionResult(status="accepted", document_uuid=document_uuid,
                                    response={"dry_run": True, "cancelled": True,
                                              "reason": reason})
        url = f"{self.base_url}/api/v1/documents/state/{document_uuid}/state"
        try:
            token = self._get_token()
            # Audit F-NEW-003: never echo the raw bearer token in logs.
            logger.debug("[ETA] cancel uuid=%s auth=%s",
                         document_uuid, redact_token(token))
            resp = requests.put(
                url,
                json={"status": "cancelled", "reason": reason},
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json"},
                timeout=self._timeout,
            )
        except requests.RequestException as e:
            logger.warning("[ETA] HTTP error during cancel: %s", str(e)[:500])
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
