"""
AMAN ERP - External API Router
API-001: API Key management
API-002: Webhooks CRUD + logs
ZATCA: QR code + signing endpoints
TAX-001: Withholding Tax (WHT)
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error, i18n_message
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pydantic import BaseModel
import hashlib
import secrets
import json
import logging

from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import branch_scope_filter, require_permission, validate_branch_access
from utils.audit import log_activity
from utils.accounting import get_base_currency, get_mapped_account_id
from utils.fiscal_lock import check_fiscal_period_open
from utils.tax_precision import CALCULATION_VERSION, money_str, rate_str, require_idempotency_key
from utils.sql_builder import validate_update_keys
from services.gl_service import create_journal_entry as gl_create_journal_entry
from utils.zatca import (
    verify_invoice_signature,
    generate_rsa_keypair, process_invoice_for_zatca
)
from utils.webhooks import WEBHOOK_EVENTS, validate_webhook_url, encrypt_webhook_secret

router = APIRouter(prefix="/external", tags=["التكامل الخارجي"])
logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')


# ======================== Schemas ========================

class APIKeyCreate(BaseModel):
    name: str
    permissions: List[str] = []
    rate_limit_per_minute: int = 60
    expires_in_days: Optional[int] = None
    notes: Optional[str] = None

class WebhookCreate(BaseModel):
    name: str
    url: str
    secret: Optional[str] = None
    events: List[str]
    retry_count: int = 3
    timeout_seconds: int = 10

class WebhookUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    events: Optional[List[str]] = None
    is_active: Optional[bool] = None
    retry_count: Optional[int] = None
    timeout_seconds: Optional[int] = None

class WHTRateCreate(BaseModel):
    name: str
    name_ar: Optional[str] = None
    rate: Decimal
    country_code: Optional[str] = None
    category: str = "general"
    description: Optional[str] = None

class WHTTransactionCreate(BaseModel):
    invoice_id: Optional[int] = None
    payment_id: Optional[int] = None
    supplier_id: int
    wht_rate_id: int
    gross_amount: Decimal
    branch_id: Optional[int] = None

class WHTCalculateRequest(BaseModel):
    wht_rate_id: int
    gross_amount: Decimal
    branch_id: Optional[int] = None

class ZatcaRequest(BaseModel):
    invoice_id: int


# ======================== API-001: API Keys ========================

@router.get("/api-keys", dependencies=[Depends(require_permission("admin"))], response_model=List[Dict[str, Any]])
def list_api_keys(current_user=Depends(get_current_user)):
    """List all API keys (without revealing the actual key)."""
    with transactional(current_user.company_id) as db:
        rows = db.execute(text("""
            SELECT id, name, key_prefix, permissions, rate_limit_per_minute,
                   is_active, expires_at, last_used_at, usage_count, created_at, notes
            FROM api_keys ORDER BY created_at DESC
        """)).fetchall()
        return [dict(r._mapping) for r in rows]


@router.post("/api-keys", status_code=201, dependencies=[Depends(require_permission("admin"))], response_model=Dict[str, Any])
def create_api_key(request: Request, data: APIKeyCreate, current_user=Depends(get_current_user)):
    """Create a new API key. The raw key is returned ONLY ONCE."""
    with transactional(current_user.company_id) as db:
        raw_key = f"aman_{secrets.token_hex(32)}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_prefix = raw_key[:12]

        expires_at = None
        if data.expires_in_days:
            from datetime import timedelta
            expires_at = datetime.now() + timedelta(days=data.expires_in_days)

        row = db.execute(text("""
            INSERT INTO api_keys (name, key_hash, key_prefix, permissions, rate_limit_per_minute,
                                  created_by, expires_at, notes)
            VALUES (:name, :hash, :prefix, :perms, :rate, :user, :expires, :notes)
            RETURNING id
        """), {
            "name": data.name,
            "hash": key_hash,
            "prefix": key_prefix,
            "perms": json.dumps(data.permissions),
            "rate": data.rate_limit_per_minute,
            "user": current_user.id,
            "expires": expires_at,
            "notes": data.notes
        }).scalar()

        log_activity(
            db=db, user_id=current_user.id, username=current_user.username,
            action="create", resource_type="api_keys",
            resource_id=str(row), details={"name": data.name, "prefix": key_prefix}
        )

        return {
            "id": row,
            "api_key": raw_key,
            "prefix": key_prefix,
            "message": i18n_message("api_key_save_warning", request)
        }


@router.delete("/api-keys/{key_id}", dependencies=[Depends(require_permission("admin"))], response_model=Dict[str, Any])
def revoke_api_key(request: Request, key_id: int, current_user=Depends(get_current_user)):
    """Revoke API Key."""
    with transactional(current_user.company_id) as db:
        db.execute(text("UPDATE api_keys SET is_active = FALSE WHERE id = :id"), {"id": key_id})
        log_activity(
            db=db, user_id=current_user.id, username=current_user.username,
            action="revoke", resource_type="api_keys",
            resource_id=str(key_id), details={}
        )
        return {"message": i18n_message("api_key_revoked_success", request)}


# ======================== API-002: Webhooks ========================

@router.get("/webhooks/events", dependencies=[Depends(require_permission(["settings.view", "admin"]))], response_model=List[str])
def list_webhook_events(current_user=Depends(get_current_user)):
    """List all available webhook events."""
    return WEBHOOK_EVENTS


@router.get("/webhooks", dependencies=[Depends(require_permission(["settings.view", "admin"]))], response_model=List[Dict[str, Any]])
def list_webhooks(current_user=Depends(get_current_user)):
    """List Webhooks."""
    with transactional(current_user.company_id) as db:
        rows = db.execute(text("SELECT * FROM webhooks ORDER BY created_at DESC")).fetchall()
        return [dict(r._mapping) for r in rows]


@router.post("/webhooks", status_code=201, dependencies=[Depends(require_permission(["settings.manage", "admin"]))], response_model=Dict[str, Any])
def create_webhook(data: WebhookCreate, request: Request, current_user=Depends(get_current_user)):
    """Create Webhook."""
    # Validate events
    invalid = [e for e in data.events if e not in WEBHOOK_EVENTS]
    if invalid:
        raise HTTPException(**http_error(400, "zatca_unknown_events", request, events=", ".join(invalid)))

    try:
        validate_webhook_url(data.url)
    except ValueError:
        raise HTTPException(**http_error(400, "url_not_allowed"))

    with transactional(current_user.company_id) as db:
        auto_secret = data.secret or secrets.token_hex(32)
        encrypted_secret = encrypt_webhook_secret(auto_secret)
        row = db.execute(text("""
            INSERT INTO webhooks (name, url, secret, events, retry_count, timeout_seconds, created_by)
            VALUES (:name, :url, :secret, :events, :retry, :timeout, :user)
            RETURNING id
        """), {
            "name": data.name,
            "url": data.url,
            "secret": encrypted_secret,
            "events": json.dumps(data.events),
            "retry": data.retry_count,
            "timeout": data.timeout_seconds,
            "user": current_user.id
        }).scalar()
        log_activity(
            db=db, user_id=current_user.id, username=current_user.username,
            action="create", resource_type="webhook",
            resource_id=str(row), details={"name": data.name, "url": data.url}
        )
        return {"id": row, "secret": auto_secret, "message": i18n_message("webhook_created", request)}


@router.put("/webhooks/{webhook_id}", dependencies=[Depends(require_permission(["settings.manage", "admin"]))], response_model=Dict[str, Any])
def update_webhook(request: Request, webhook_id: int, data: WebhookUpdate, current_user=Depends(get_current_user)):
    """Update Webhook."""
    if data.url is not None:
        try:
            validate_webhook_url(data.url)
        except ValueError:
            raise HTTPException(**http_error(400, "url_not_allowed"))
    with transactional(current_user.company_id) as db:
        updates = {}
        if data.name is not None:
            updates["name"] = data.name
        if data.url is not None:
            updates["url"] = data.url
        if data.events is not None:
            updates["events"] = json.dumps(data.events)
        if data.is_active is not None:
            updates["is_active"] = data.is_active
        if data.retry_count is not None:
            updates["retry_count"] = data.retry_count
        if data.timeout_seconds is not None:
            updates["timeout_seconds"] = data.timeout_seconds

        if not updates:
            raise HTTPException(**http_error(400, "no_data_to_update"))

        validate_update_keys(updates.keys())  # T2.2 defense-in-depth
        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        updates["id"] = webhook_id
        db.execute(text(f"UPDATE webhooks SET {set_clause}, updated_at = NOW() WHERE id = :id"), updates) # noqa
        log_activity(
            db=db, user_id=current_user.id, username=current_user.username,
            action="update", resource_type="webhook",
            resource_id=str(webhook_id), details={k: v for k, v in updates.items() if k != "id"}
        )
        return {"message": i18n_message("webhook_updated_success", request)}


@router.delete("/webhooks/{webhook_id}", dependencies=[Depends(require_permission(["settings.manage", "admin"]))], response_model=Dict[str, Any])
def delete_webhook(request: Request, webhook_id: int, current_user=Depends(get_current_user)):
    """Delete Webhook."""
    with transactional(current_user.company_id) as db:
        db.execute(text("DELETE FROM webhooks WHERE id = :id"), {"id": webhook_id})
        log_activity(
            db=db, user_id=current_user.id, username=current_user.username,
            action="delete", resource_type="webhook",
            resource_id=str(webhook_id), details={}
        )
        return {"message": i18n_message("webhook_deleted_success", request)}


@router.get("/webhooks/{webhook_id}/logs", dependencies=[Depends(require_permission(["settings.view", "admin"]))], response_model=List[Dict[str, Any]])
def get_webhook_logs(webhook_id: int, limit: int = 50, current_user=Depends(get_current_user)):
    """Get Webhook Logs."""
    with transactional(current_user.company_id) as db:
        rows = db.execute(text("""
            SELECT id, event, response_status, success, attempt, error_message, created_at
            FROM webhook_logs WHERE webhook_id = :wid ORDER BY created_at DESC LIMIT :lim
        """), {"wid": webhook_id, "lim": limit}).fetchall()
        return [dict(r._mapping) for r in rows]


# ======================== ZATCA: QR + Signing ========================

@router.post("/zatca/generate-qr", dependencies=[Depends(require_permission(["sales.view", "accounting.view"]))], response_model=Dict[str, Any])
def generate_qr_code(
    body: ZatcaRequest,
    request: Request,
    current_user=Depends(get_current_user)
):
    """Generate ZATCA QR code for an invoice."""
    invoice_id = body.invoice_id
    with transactional(current_user.company_id) as db:
        try:
            # Get invoice details
            inv = db.execute(text("""
                SELECT i.id, i.invoice_number, i.invoice_date, i.total, i.tax_amount,
                       i.branch_id, p.name as customer_name
                FROM invoices i
                LEFT JOIN parties p ON i.party_id = p.id
                WHERE i.id = :id
            """), {"id": invoice_id}).fetchone()

            if not inv:
                raise HTTPException(**http_error(404, "invoice_not_found"))

            # Branch access validation
            if inv.branch_id:
                validate_branch_access(current_user, inv.branch_id)

            # Get company info
            seller_name = db.execute(text(
                "SELECT setting_value FROM company_settings WHERE setting_key = 'company_name'"
            )).scalar() or "AMAN ERP"

            vat_number = db.execute(text(
                "SELECT setting_value FROM company_settings WHERE setting_key = 'zatca_vat_number'"
            )).scalar() or db.execute(text(
                "SELECT setting_value FROM company_settings WHERE setting_key = 'tax_number'"
            )).scalar() or "000000000000000"

            # Get private key for signing (optional)
            # T2.5: read via secret_settings helper so legacy plaintext or new ciphertext both work.
            from utils.secret_settings import get_secret_setting
            private_key = get_secret_setting(db, "zatca_private_key", tenant_id=current_user.company_id)

            result = process_invoice_for_zatca(
                db=db,
                invoice_id=inv.id,
                company_id=current_user.company_id,
                seller_name=seller_name,
                vat_number=vat_number,
                invoice_number=inv.invoice_number,
                invoice_date=str(inv.invoice_date),
                total=inv.total,
                vat_amount=inv.tax_amount or Decimal("0"),
                private_key_pem=private_key
            )

            return {
                "invoice_id": invoice_id,
                "invoice_number": inv.invoice_number,
                **result
            }
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("ZATCA QR generation failed")
            raise HTTPException(**http_error(500, "qr_generation_error", request))


@router.post("/zatca/generate-keypair", dependencies=[Depends(require_permission("admin"))], response_model=Dict[str, Any])
def generate_keypair(request: Request, current_user=Depends(get_current_user)):
    """Generate RSA keypair for ZATCA signing and store in company settings."""
    with transactional(current_user.company_id) as db:
        private_pem, public_pem = generate_rsa_keypair()

        # Store in company settings — T2.5: encrypt private key at rest.
        from utils.secret_settings import set_secret_setting, is_secret_key
        for key, val in [("zatca_private_key", private_pem), ("zatca_public_key", public_pem)]:
            if is_secret_key(key):
                set_secret_setting(db, key, val, tenant_id=current_user.company_id)
                # Tag category for new rows (no-op if already set)
                db.execute(text("""
                    UPDATE company_settings SET category = 'zatca'
                    WHERE setting_key = :key AND (category IS NULL OR category = '')
                """), {"key": key})
            else:
                db.execute(text("""
                    INSERT INTO company_settings (setting_key, setting_value, category)
                    VALUES (:key, :val, 'zatca')
                    ON CONFLICT (setting_key) DO UPDATE SET setting_value = :val
                """), {"key": key, "val": val})

        return {
            "message": i18n_message("signing_key_generated", request),
            "public_key": public_pem
        }


@router.get("/zatca/verify/{invoice_id}", dependencies=[Depends(require_permission(["sales.view", "accounting.view"]))], response_model=Dict[str, Any])
def verify_invoice_qr(invoice_id: int, request: Request, current_user=Depends(get_current_user)):
    """Verify a ZATCA QR code and signature for an invoice."""
    with transactional(current_user.company_id) as db:
        inv = db.execute(text("""
            SELECT zatca_hash, zatca_signature, zatca_qr, zatca_status, branch_id
            FROM invoices WHERE id = :id
        """), {"id": invoice_id}).fetchone()

        if not inv or not inv.zatca_hash:
            raise HTTPException(**http_error(404, "zatca_data_not_found", request))

        # Branch access validation
        if inv.branch_id:
            validate_branch_access(current_user, inv.branch_id)

        result = {
            "invoice_id": invoice_id,
            "hash": inv.zatca_hash,
            "has_signature": bool(inv.zatca_signature),
            "has_qr": bool(inv.zatca_qr),
            "status": inv.zatca_status,
            "signature_valid": None
        }

        if inv.zatca_signature:
            public_key = db.execute(text(
                "SELECT setting_value FROM company_settings WHERE setting_key = 'zatca_public_key'"
            )).scalar()
            if public_key:
                result["signature_valid"] = verify_invoice_signature(
                    inv.zatca_hash, inv.zatca_signature, public_key
                )

        return result


# ======================== TAX-001: Withholding Tax ========================

@router.get("/wht/rates", dependencies=[Depends(require_permission(["accounting.view", "taxes.view"]))], response_model=List[Dict[str, Any]])
def list_wht_rates(
    country_code: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user=Depends(get_current_user)
):
    """List WHT Rates."""
    with transactional(current_user.company_id) as db:
        params = {}
        country_filter = ""
        if branch_id:
            branch_id = validate_branch_access(current_user, branch_id)
            row = db.execute(text("SELECT country_code FROM branches WHERE id = :id"), {"id": branch_id}).fetchone()
            if row and row.country_code:
                country_code = row.country_code
        if country_code:
            country_filter = "AND (country_code = :cc OR country_code IS NULL)"
            params["cc"] = country_code.upper()
        rows = db.execute(text( # noqa
                    f"""
            SELECT * FROM wht_rates
            WHERE is_active = TRUE {country_filter}
            ORDER BY category, name
        """), params).fetchall()
        result = []
        for r in rows:
            item = dict(r._mapping)
            item["rate"] = rate_str(item.get("rate"))
            result.append(item)
        return result


@router.post("/wht/rates", status_code=201, dependencies=[Depends(require_permission(["accounting.manage", "taxes.manage"]))], response_model=Dict[str, Any])
def create_wht_rate(request: Request, data: WHTRateCreate, current_user=Depends(get_current_user)):
    """Create WHT Rate."""
    with transactional(current_user.company_id) as db:
        rid = db.execute(text("""
            INSERT INTO wht_rates (name, name_ar, rate, country_code, category, description)
            VALUES (:name, :name_ar, :rate, :cc, :cat, :desc) RETURNING id
        """), {
            "name": data.name, "name_ar": data.name_ar, "rate": data.rate,
            "cc": data.country_code.upper() if data.country_code else None,
            "cat": data.category, "desc": data.description
        }).scalar()
        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="wht.rate.create", resource_type="wht_rate",
                     resource_id=str(rid), details={"rate": rate_str(data.rate), "country_code": data.country_code},
                     request=request)
        return {"id": rid}


@router.post("/wht/calculate", dependencies=[Depends(require_permission(["accounting.view", "buying.view"]))], response_model=Dict[str, Any])
def calculate_wht(request: Request, data: WHTCalculateRequest, current_user=Depends(get_current_user)):
    """Calculate WHT amount without creating a transaction."""
    with transactional(current_user.company_id) as db:
        branch_id = validate_branch_access(current_user, data.branch_id)
        if branch_id is None:
            raise HTTPException(**http_error(400, "branch_required", request))
        rate_row = db.execute(text("SELECT rate, country_code FROM wht_rates WHERE id = :id AND is_active = TRUE"),
                              {"id": data.wht_rate_id}).fetchone()
        if not rate_row:
            raise HTTPException(**http_error(404, "wht_rate_not_found"))
        if rate_row.country_code:
            branch = db.execute(text("SELECT country_code FROM branches WHERE id = :bid"), {"bid": branch_id}).fetchone()
            branch_cc = (branch.country_code or "SA").upper() if branch else "SA"
            if rate_row.country_code.upper() != branch_cc:
                raise HTTPException(**http_error(400, "wht_rate_not_found", request))

        wht_rate = _dec(rate_row.rate)
        gross_amount = _dec(data.gross_amount)
        wht_amount = (gross_amount * wht_rate / Decimal('100')).quantize(_D2, ROUND_HALF_UP)
        net_amount = (gross_amount - wht_amount).quantize(_D2, ROUND_HALF_UP)

        return {
            "gross_amount": money_str(data.gross_amount),
            "wht_rate": rate_str(wht_rate),
            "wht_amount": money_str(wht_amount),
            "net_amount": money_str(net_amount),
            "branch_id": branch_id,
            "calculation_version": CALCULATION_VERSION,
        }


@router.post("/wht/transactions", status_code=201,
             dependencies=[Depends(require_permission(["accounting.edit", "taxes.manage"]))], response_model=Dict[str, Any])
def create_wht_transaction(request: Request, data: WHTTransactionCreate, current_user=Depends(get_current_user)):
    """Create a WHT transaction and optionally post GL entries."""
    with transactional(current_user.company_id) as db:
        try:
            branch_id = validate_branch_access(current_user, data.branch_id)
            if branch_id is None:
                raise HTTPException(**http_error(400, "branch_required", request))
            idempotency_key = require_idempotency_key(
                request,
                operation="WHT transaction",
            )
            if not data.payment_id:
                raise HTTPException(**http_error(400, "wht_payment_required", request))
            existing_by_key = db.execute(text("""
                SELECT id, certificate_number
                FROM wht_transactions
                WHERE idempotency_key = :key
                LIMIT 1
            """), {"key": idempotency_key}).fetchone()
            if existing_by_key:
                return {
                    "id": existing_by_key.id,
                    "certificate_number": existing_by_key.certificate_number,
                    "idempotent": True,
                }
            rate_row = db.execute(text("SELECT rate, name, country_code FROM wht_rates WHERE id = :id AND is_active = TRUE"),
                                  {"id": data.wht_rate_id}).fetchone()
            if not rate_row:
                raise HTTPException(**http_error(404, "wht_rate_not_found_or_inactive"))

            # Validate country match
            if rate_row.country_code:
                branch = db.execute(text("SELECT country_code FROM branches WHERE id = :bid"), {"bid": branch_id}).fetchone()
                branch_cc = (branch.country_code or "SA").upper() if branch else "SA"
                if rate_row.country_code.upper() != branch_cc:
                    raise HTTPException(**http_error(400, "wht_rate_not_found", request))

            supplier = db.execute(text("""
                SELECT id, branch_id
                FROM parties
                WHERE id = :sid
                  AND COALESCE(is_supplier, FALSE) = TRUE
            """), {"sid": data.supplier_id}).fetchone()
            if not supplier:
                raise HTTPException(**http_error(400, "supplier_not_found_or_inactive", request))
            if supplier.branch_id is not None and int(supplier.branch_id) != int(branch_id):
                raise HTTPException(**http_error(400, "supplier_not_in_selected_branch", request))

            if data.invoice_id:
                invoice = db.execute(text("""
                    SELECT id, party_id, branch_id, invoice_type, total
                    FROM invoices
                    WHERE id = :id
                """), {"id": data.invoice_id}).fetchone()
                if not invoice:
                    raise HTTPException(**http_error(404, "withholding_invoice_not_found", request))
                if invoice.invoice_type != "purchase":
                    raise HTTPException(**http_error(400, "withholding_only_purchase_invoices", request))
                if int(invoice.party_id) != int(data.supplier_id):
                    raise HTTPException(**http_error(400, "invoice_not_from_selected_supplier", request))
                if invoice.branch_id is not None and int(invoice.branch_id) != int(branch_id):
                    raise HTTPException(**http_error(400, "invoice_not_in_selected_branch", request))

            if data.payment_id:
                payment = db.execute(text("""
                    SELECT id, party_id, branch_id, party_type, voucher_type,
                           amount, voucher_date, currency, exchange_rate,
                           treasury_account_id, bank_account_id
                    FROM payment_vouchers
                    WHERE id = :id
                """), {"id": data.payment_id}).fetchone()
                if not payment:
                    raise HTTPException(**http_error(404, "withholding_payment_not_found", request))
                if payment.party_type != "supplier" or payment.voucher_type != "payment":
                    raise HTTPException(**http_error(400, "withholding_only_supplier_payments", request))
                if int(payment.party_id) != int(data.supplier_id):
                    raise HTTPException(**http_error(400, "invoice_not_from_selected_supplier", request))
                if payment.branch_id is not None and int(payment.branch_id) != int(branch_id):
                    raise HTTPException(**http_error(400, "invoice_not_in_selected_branch", request))
                if data.invoice_id:
                    allocation = db.execute(text("""
                        SELECT 1
                        FROM payment_allocations
                        WHERE voucher_id = :pay_id
                          AND invoice_id = :inv_id
                        LIMIT 1
                    """), {"pay_id": data.payment_id, "inv_id": data.invoice_id}).fetchone()
                    if not allocation:
                        raise HTTPException(**http_error(400, "batch_not_assigned_to_invoice", request))

            wht_rate = _dec(rate_row.rate)
            gross_amount = _dec(data.gross_amount)
            wht_amount = (gross_amount * wht_rate / Decimal('100')).quantize(_D2, ROUND_HALF_UP)
            net_amount = (gross_amount - wht_amount).quantize(_D2, ROUND_HALF_UP)
            base_currency = get_base_currency(db)
            payment_currency = payment.currency or base_currency
            payment_rate = _dec(payment.exchange_rate or 1)
            if payment_rate <= 0:
                raise HTTPException(**http_error(400, "exchange_rate_must_be_positive", request))
            period_date = payment.voucher_date
            calc_details = {
                "version": CALCULATION_VERSION,
                "gross_amount": money_str(gross_amount),
                "wht_rate": rate_str(wht_rate),
                "wht_amount": money_str(wht_amount),
                "net_amount": money_str(net_amount),
                "branch_id": branch_id,
            }

            check_fiscal_period_open(db, period_date)
            if wht_amount > Decimal("0"):
                ap_account_id = get_mapped_account_id(db, "acc_map_ap")
                withholding_account_id = get_mapped_account_id(db, "acc_map_withholding_tax")
                if not ap_account_id or not withholding_account_id:
                    raise HTTPException(**http_error(400, "ap_wht_accounts_not_configured", request))
                cash_line = db.execute(text("""
                    SELECT jl.account_id, jl.credit, jl.amount_currency, jl.currency
                    FROM journal_entries je
                    JOIN journal_lines jl ON jl.journal_entry_id = je.id
                    WHERE je.source = 'payment_voucher'
                      AND je.source_id = :payment_id
                      AND je.entry_date = :period_date
                      AND jl.credit > 0
                      AND jl.account_id <> :ap_account_id
                    ORDER BY jl.credit DESC, jl.id
                    LIMIT 1
                """), {
                    "payment_id": data.payment_id,
                    "period_date": period_date,
                    "ap_account_id": ap_account_id,
                }).fetchone()
                if not cash_line:
                    cash_line = db.execute(text("""
                        SELECT ta.gl_account_id AS account_id,
                               0::numeric AS credit,
                               0::numeric AS amount_currency,
                               COALESCE(ta.currency, :payment_currency) AS currency
                        FROM treasury_accounts ta
                        WHERE ta.id = COALESCE(:treasury_id, :bank_id)
                    """), {
                        "treasury_id": payment.treasury_account_id,
                        "bank_id": payment.bank_account_id,
                        "payment_currency": payment_currency,
                    }).fetchone()
                if not cash_line or not cash_line.account_id:
                    raise HTTPException(**http_error(400, "cash_account_not_configured", request))

            # Generate certificate number
            cert_num = f"WHT-{datetime.now().year}-{datetime.now().strftime('%m%d%H%M%S')}"

            tid = db.execute(text("""
                INSERT INTO wht_transactions (
                    invoice_id, payment_id, supplier_id, branch_id, wht_rate_id,
                    gross_amount, wht_rate, wht_amount, net_amount,
                    currency, base_currency, exchange_rate,
                    certificate_number, period_date, created_by,
                    idempotency_key, calculation_version, calculation_details
                ) VALUES (
                    :inv, :pay, :sup, :branch_id, :rate_id,
                    :gross, :rate, :wht, :net,
                    :currency, :base_currency, 1,
                    :cert, :period, :user,
                    :idempotency_key, :calc_version, CAST(:calc_details AS jsonb)
                ) RETURNING id
            """), {
                "inv": data.invoice_id, "pay": data.payment_id,
                "sup": data.supplier_id, "branch_id": branch_id, "rate_id": data.wht_rate_id,
                "gross": gross_amount, "rate": wht_rate,
                "wht": wht_amount, "net": net_amount,
                "currency": base_currency, "base_currency": base_currency,
                "cert": cert_num, "period": period_date,
                "user": current_user.id,
                "idempotency_key": idempotency_key,
                "calc_version": CALCULATION_VERSION,
                "calc_details": json.dumps(calc_details),
            }).scalar()

            journal_entry_id = None
            journal_entry_number = None
            if wht_amount > Decimal("0"):
                wht_base = (wht_amount * payment_rate).quantize(_D2, ROUND_HALF_UP)
                cash_credit_base = _dec(getattr(cash_line, "credit", 0))
                cash_amount_currency = _dec(getattr(cash_line, "amount_currency", 0))
                cash_currency = getattr(cash_line, "currency", None) or payment_currency
                if cash_credit_base > 0 and cash_amount_currency > 0:
                    cash_debit_amount = (cash_amount_currency * wht_base / cash_credit_base).quantize(_D2, ROUND_HALF_UP)
                    cash_exchange_rate = (wht_base / cash_debit_amount).quantize(Decimal("0.000001"), ROUND_HALF_UP)
                else:
                    cash_debit_amount = wht_amount
                    cash_exchange_rate = payment_rate

                journal_entry_id, journal_entry_number = gl_create_journal_entry(
                    db=db,
                    company_id=current_user.company_id,
                    date=str(period_date),
                    description=f"WHT payable reclassification for supplier payment {data.payment_id}",
                    reference=cert_num,
                    lines=[
                        {
                            "account_id": cash_line.account_id,
                            "debit": cash_debit_amount,
                            "credit": 0,
                            "description": "Reverse withheld cash from supplier payment",
                            "currency": cash_currency,
                            "amount_currency": cash_debit_amount,
                            "exchange_rate": cash_exchange_rate,
                        },
                        {
                            "account_id": withholding_account_id,
                            "debit": 0,
                            "credit": wht_base,
                            "description": "Withholding tax payable",
                            "currency": base_currency,
                            "amount_currency": wht_base,
                            "exchange_rate": Decimal("1"),
                        },
                    ],
                    user_id=current_user.id,
                    branch_id=branch_id,
                    currency=base_currency,
                    exchange_rate=Decimal("1"),
                    source="payment_voucher_wht",
                    source_id=tid,
                    idempotency_key=f"{idempotency_key}:gl",
                )
                db.execute(text("""
                    UPDATE wht_transactions
                    SET journal_entry_id = :journal_entry_id,
                        status = 'posted',
                        updated_at = NOW()
                    WHERE id = :id
                """), {"journal_entry_id": journal_entry_id, "id": tid})

            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="wht.transaction.create", resource_type="wht_transaction",
                         resource_id=str(tid),
                         details={**calc_details, "payment_id": data.payment_id, "journal_entry": journal_entry_number},
                         request=request)

            return {
                "id": tid,
                "certificate_number": cert_num,
                "gross_amount": money_str(gross_amount),
                "wht_rate": rate_str(wht_rate),
                "wht_amount": money_str(wht_amount),
                "net_amount": money_str(net_amount),
                "branch_id": branch_id,
                "journal_entry_id": journal_entry_id,
                "journal_entry": journal_entry_number,
                "calculation_version": CALCULATION_VERSION,
            }
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Error creating WHT transaction")
            raise HTTPException(**http_error(500, "internal_error"))


@router.get("/wht/transactions", dependencies=[Depends(require_permission(["accounting.view", "taxes.view"]))], response_model=List[Dict[str, Any]])
def list_wht_transactions(
    supplier_id: Optional[int] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user=Depends(get_current_user)
):
    """List WHT Transactions."""
    with transactional(current_user.company_id) as db:
        query = """
            SELECT wt.*, wr.name as rate_name, p.name as supplier_name
            FROM wht_transactions wt
            LEFT JOIN wht_rates wr ON wt.wht_rate_id = wr.id
            LEFT JOIN parties p ON wt.supplier_id = p.id
            WHERE 1=1
        """
        params = {}
        branch_filter = branch_scope_filter(current_user, branch_id, "wt.branch_id", params)
        query += f" {branch_filter}"
        if supplier_id:
            query += " AND wt.supplier_id = :sup"
            params["sup"] = supplier_id
        if from_date:
            query += " AND wt.period_date >= :from"
            params["from"] = from_date
        if to_date:
            query += " AND wt.period_date <= :to"
            params["to"] = to_date

        query += " ORDER BY wt.created_at DESC"
        rows = db.execute(text(query), params).fetchall()
        result = []
        for r in rows:
            item = dict(r._mapping)
            for key in ("gross_amount", "wht_amount", "net_amount"):
                if key in item:
                    item[key] = money_str(item[key])
            if "wht_rate" in item:
                item["wht_rate"] = rate_str(item["wht_rate"])
            result.append(item)
        return result


# ==========================================================================
# TAX-F2 — WHT certificate PDF download (Phase-11 Sprint-5)
# ==========================================================================

@router.get("/wht/transactions/{tid}/certificate", dependencies=[Depends(require_permission(["accounting.view", "taxes.view"]))])
def download_wht_certificate(request: Request, tid: int, current_user=Depends(get_current_user)):
    """Download an official PDF withholding-tax certificate."""
    from io import BytesIO
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import cm
    except ImportError:
        raise HTTPException(**http_error(500, "reportlab_not_installed", request))
    from fastapi.responses import StreamingResponse

    with transactional(current_user.company_id) as db:
        row = db.execute(text("""
            SELECT wt.id, wt.certificate_number, wt.gross_amount, wt.wht_amount,
                   wt.net_amount, wt.wht_rate, wt.period_date, wt.created_at,
                   wt.branch_id,
                   wr.name AS rate_name,
                   p.name AS supplier_name, p.tax_number AS supplier_tax_number,
                   p.address AS supplier_address
            FROM wht_transactions wt
            LEFT JOIN wht_rates wr ON wt.wht_rate_id = wr.id
            LEFT JOIN parties p ON wt.supplier_id = p.id
            WHERE wt.id = :id
        """), {"id": tid}).fetchone()
        if not row:
            raise HTTPException(**http_error(404, "wht_transaction_not_found"))
        if row.branch_id:
            validate_branch_access(current_user, row.branch_id)

        db.execute(text("""
            SELECT setting_value FROM company_settings WHERE setting_key IN
              ('company_name_ar','company_name','tax_number','address')
        """)).fetchall()
        settings_map = {}
        # Fallback query per key since setting_key not returned above
        for k in ("company_name_ar", "company_name", "tax_number", "address"):
            r = db.execute(
                text("SELECT setting_value FROM company_settings WHERE setting_key = :k"),
                {"k": k},
            ).fetchone()
            settings_map[k] = r[0] if r else ""

        buf = BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        w, h = A4
        c.setTitle(f"WHT Certificate {row.certificate_number}")

        # Header
        c.setFont("Helvetica-Bold", 16)
        c.drawCentredString(w / 2, h - 2 * cm, "Withholding Tax Certificate")
        c.setFont("Helvetica", 10)
        c.drawCentredString(w / 2, h - 2.6 * cm, "شهادة ضريبة الاستقطاع")

        # Certificate number + date
        c.setFont("Helvetica-Bold", 11)
        c.drawString(2 * cm, h - 4 * cm, f"Certificate No: {row.certificate_number}")
        c.drawRightString(w - 2 * cm, h - 4 * cm, f"Date: {row.period_date}")

        # Payer (company)
        y = h - 5.5 * cm
        c.setFont("Helvetica-Bold", 11)
        c.drawString(2 * cm, y, "Payer / الجهة الدافعة")
        c.setFont("Helvetica", 10)
        y -= 0.6 * cm
        c.drawString(2 * cm, y, f"Name: {settings_map.get('company_name_ar') or settings_map.get('company_name') or ''}")
        y -= 0.5 * cm
        c.drawString(2 * cm, y, f"Tax No: {settings_map.get('tax_number') or ''}")
        y -= 0.5 * cm
        c.drawString(2 * cm, y, f"Address: {settings_map.get('address') or ''}")

        # Payee (supplier)
        y -= 1 * cm
        c.setFont("Helvetica-Bold", 11)
        c.drawString(2 * cm, y, "Payee / المورد")
        c.setFont("Helvetica", 10)
        y -= 0.6 * cm
        c.drawString(2 * cm, y, f"Name: {row.supplier_name or ''}")
        y -= 0.5 * cm
        c.drawString(2 * cm, y, f"Tax No: {row.supplier_tax_number or ''}")
        y -= 0.5 * cm
        c.drawString(2 * cm, y, f"Address: {row.supplier_address or ''}")

        # Amounts table
        y -= 1.2 * cm
        c.setFont("Helvetica-Bold", 11)
        c.drawString(2 * cm, y, "Tax Details / تفاصيل الضريبة")
        c.setFont("Helvetica", 10)
        y -= 0.7 * cm
        c.drawString(2 * cm, y, f"Gross Amount:   {row.gross_amount}")
        y -= 0.5 * cm
        c.drawString(2 * cm, y, f"WHT Rate:       {row.wht_rate}%  ({row.rate_name or ''})")
        y -= 0.5 * cm
        c.drawString(2 * cm, y, f"WHT Amount:     {row.wht_amount}")
        y -= 0.5 * cm
        c.drawString(2 * cm, y, f"Net Paid:       {row.net_amount}")

        # Footer
        c.setFont("Helvetica-Oblique", 8)
        c.drawString(2 * cm, 1.5 * cm,
                     "This certificate is auto-generated by AMAN ERP. Issued by the payer to the payee for tax-filing purposes.")

        c.showPage()
        c.save()
        buf.seek(0)

        filename = f"WHT-{row.certificate_number}.pdf"
        return StreamingResponse(
            buf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
