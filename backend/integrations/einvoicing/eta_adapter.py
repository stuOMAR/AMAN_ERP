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
from typing import Any, Callable, Dict, List, Optional

import requests

from .base import EInvoiceAdapter, SubmissionResult

logger = logging.getLogger(__name__)

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
    total_sales = 0.0
    total_tax = 0.0
    total_discount = 0.0
    currency = invoice.get("currency") or "EGP"
    fx_rate = float(invoice.get("exchange_rate") or 1)
    for idx, ln in enumerate(invoice.get("lines") or [], start=1):
        qty = float(ln.get("quantity") or 0)
        unit_price = float(ln.get("unit_price") or 0)
        sales = qty * unit_price
        discount = float(ln.get("discount") or 0)
        tax_amt = float(ln.get("tax_amount") or 0)
        tax_rate = float(ln.get("tax_rate") or 0)
        net = sales - discount
        total_sales += sales
        total_discount += discount
        total_tax += tax_amt
        lines.append({
            "description": ln.get("description") or ln.get("item_name") or f"Item {idx}",
            "itemType": ln.get("item_type") or "GS1",
            "itemCode": str(ln.get("item_code") or ln.get("sku") or ""),
            "unitType": ln.get("unit_type") or "EA",
            "quantity": qty,
            "internalCode": str(ln.get("internal_code") or ""),
            "salesTotal": {"currencySold": currency, "amountEGP": round(sales, 5)},
            "total": round(net + tax_amt, 5),
            "valueDifference": 0,
            "totalTaxableFees": 0,
            "netTotal": {"currencySold": currency, "amountEGP": round(net, 5)},
            "itemsDiscount": 0,
            "discount": {"rate": 0, "amount": round(discount, 5)},
            "taxableItems": [{
                "taxType": "T1",        # T1 = VAT
                "amount": round(tax_amt, 5),
                "subType": "V001",
                "rate": tax_rate,
            }],
            "unitValue": {"currencySold": currency,
                          "amountEGP": round(unit_price, 5),
                          "currencyExchangeRate": fx_rate},
        })

    grand_total = float(invoice.get("total") or (total_sales - total_discount + total_tax))
    net_total = float(invoice.get("net_total") or (total_sales - total_discount))
    vat_total = float(invoice.get("vat_amount") or total_tax)

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
        "totalDiscountAmount": round(total_discount, 5),
        "totalSalesAmount": round(total_sales, 5),
        "netAmount": round(net_total, 5),
        "taxTotals": [{"taxType": "T1", "amount": round(vat_total, 5)}],
        "totalAmount": round(grand_total, 5),
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
        self._token_exp = time.time() + float(body.get("expires_in", 3600))
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
            resp = requests.post(
                url,
                json={"documents": [document]},
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json"},
                timeout=self._timeout,
            )
        except requests.RequestException as e:
            logger.exception("[ETA] HTTP error during submission")
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
            resp = requests.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=self._timeout,
            )
        except requests.RequestException as e:
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
            resp = requests.put(
                url,
                json={"status": "cancelled", "reason": reason},
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json"},
                timeout=self._timeout,
            )
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
