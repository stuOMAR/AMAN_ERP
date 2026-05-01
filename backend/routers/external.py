"""
AMAN ERP - External API Router
API-001: API Key management
API-002: Webhooks CRUD + logs
ZATCA: QR code + signing endpoints
TAX-001: Withholding Tax (WHT)
"""

from fastapi import APIRouter, Depends, HTTPException
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pydantic import BaseModel
import hashlib
import secrets
import json
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import require_permission
from utils.audit import log_activity
from utils.sql_builder import validate_update_keys
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
    rate: float
    category: str = "general"
    description: Optional[str] = None

class WHTTransactionCreate(BaseModel):
    invoice_id: Optional[int] = None
    payment_id: Optional[int] = None
    supplier_id: int
    wht_rate_id: int
    gross_amount: float


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
def create_api_key(data: APIKeyCreate, current_user=Depends(get_current_user)):
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
            "message": "احفظ المفتاح الآن — لن يظهر مرة أخرى"
        }


@router.delete("/api-keys/{key_id}", dependencies=[Depends(require_permission("admin"))], response_model=Dict[str, Any])
def revoke_api_key(key_id: int, current_user=Depends(get_current_user)):
    """Revoke API Key."""
    with transactional(current_user.company_id) as db:
        db.execute(text("UPDATE api_keys SET is_active = FALSE WHERE id = :id"), {"id": key_id})
        log_activity(
            db=db, user_id=current_user.id, username=current_user.username,
            action="revoke", resource_type="api_keys",
            resource_id=str(key_id), details={}
        )
        return {"message": "تم إلغاء المفتاح"}


# ======================== API-002: Webhooks ========================

@router.get("/webhooks/events", dependencies=[Depends(require_permission(["settings.view", "admin"]))], response_model=Dict[str, Any])
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
def create_webhook(data: WebhookCreate, current_user=Depends(get_current_user)):
    """Create Webhook."""
    # Validate events
    invalid = [e for e in data.events if e not in WEBHOOK_EVENTS]
    if invalid:
        raise HTTPException(400, f"أحداث غير معروفة: {invalid}")

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
        return {"id": row, "secret": auto_secret, "message": "تم إنشاء الـ webhook"}


@router.put("/webhooks/{webhook_id}", dependencies=[Depends(require_permission(["settings.manage", "admin"]))], response_model=Dict[str, Any])
def update_webhook(webhook_id: int, data: WebhookUpdate, current_user=Depends(get_current_user)):
    """Update Webhook."""
    if data.url is not None:
        try:
            validate_webhook_url(data.url)
        except ValueError:
            raise HTTPException(**http_error(400, "url_not_allowed"))
    with transactional(current_user.company_id) as db:
        updates = {}
        if data.name is not None: updates["name"] = data.name
        if data.url is not None: updates["url"] = data.url
        if data.events is not None: updates["events"] = json.dumps(data.events)
        if data.is_active is not None: updates["is_active"] = data.is_active
        if data.retry_count is not None: updates["retry_count"] = data.retry_count
        if data.timeout_seconds is not None: updates["timeout_seconds"] = data.timeout_seconds
        
        if not updates:
            raise HTTPException(**http_error(400, "no_data_to_update"))
        
        validate_update_keys(updates.keys())  # T2.2 defense-in-depth
        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        updates["id"] = webhook_id
        db.execute(text(f"UPDATE webhooks SET {set_clause}, updated_at = NOW() WHERE id = :id"), updates)
        log_activity(
            db=db, user_id=current_user.id, username=current_user.username,
            action="update", resource_type="webhook",
            resource_id=str(webhook_id), details={k: v for k, v in updates.items() if k != "id"}
        )
        return {"message": "تم التحديث"}


@router.delete("/webhooks/{webhook_id}", dependencies=[Depends(require_permission(["settings.manage", "admin"]))], response_model=Dict[str, Any])
def delete_webhook(webhook_id: int, current_user=Depends(get_current_user)):
    """Delete Webhook."""
    with transactional(current_user.company_id) as db:
        db.execute(text("DELETE FROM webhooks WHERE id = :id"), {"id": webhook_id})
        log_activity(
            db=db, user_id=current_user.id, username=current_user.username,
            action="delete", resource_type="webhook",
            resource_id=str(webhook_id), details={}
        )
        return {"message": "تم الحذف"}


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
    invoice_id: int,
    current_user=Depends(get_current_user)
):
    """Generate ZATCA QR code for an invoice."""
    with transactional(current_user.company_id) as db:
        try:
            # Get invoice details
            inv = db.execute(text("""
                SELECT i.id, i.invoice_number, i.invoice_date, i.total, i.tax_amount,
                       p.name as customer_name
                FROM invoices i
                LEFT JOIN parties p ON i.party_id = p.id
                WHERE i.id = :id
            """), {"id": invoice_id}).fetchone()
            
            if not inv:
                raise HTTPException(**http_error(404, "invoice_not_found"))
            
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
                total=float(inv.total),
                vat_amount=float(inv.tax_amount or 0),
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
            raise HTTPException(500, "خطأ في توليد QR")


@router.post("/zatca/generate-keypair", dependencies=[Depends(require_permission("admin"))], response_model=Dict[str, Any])
def generate_keypair(current_user=Depends(get_current_user)):
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
            "message": "تم توليد مفتاح التوقيع الرقمي",
            "public_key": public_pem
        }


@router.get("/zatca/verify/{invoice_id}", dependencies=[Depends(require_permission(["sales.view", "accounting.view"]))], response_model=Dict[str, Any])
def verify_invoice_qr(invoice_id: int, current_user=Depends(get_current_user)):
    """Verify a ZATCA QR code and signature for an invoice."""
    with transactional(current_user.company_id) as db:
        inv = db.execute(text("""
            SELECT zatca_hash, zatca_signature, zatca_qr, zatca_status
            FROM invoices WHERE id = :id
        """), {"id": invoice_id}).fetchone()
        
        if not inv or not inv.zatca_hash:
            raise HTTPException(404, "لم يتم توليد بيانات ZATCA لهذه الفاتورة")
        
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
def list_wht_rates(current_user=Depends(get_current_user)):
    """List WHT Rates."""
    with transactional(current_user.company_id) as db:
        rows = db.execute(text("SELECT * FROM wht_rates WHERE is_active = TRUE ORDER BY category, name")).fetchall()
        return [dict(r._mapping) for r in rows]


@router.post("/wht/rates", status_code=201, dependencies=[Depends(require_permission(["accounting.manage", "taxes.manage"]))], response_model=Dict[str, Any])
def create_wht_rate(data: WHTRateCreate, current_user=Depends(get_current_user)):
    """Create WHT Rate."""
    with transactional(current_user.company_id) as db:
        rid = db.execute(text("""
            INSERT INTO wht_rates (name, name_ar, rate, category, description)
            VALUES (:name, :name_ar, :rate, :cat, :desc) RETURNING id
        """), {
            "name": data.name, "name_ar": data.name_ar, "rate": data.rate,
            "cat": data.category, "desc": data.description
        }).scalar()
        return {"id": rid}


@router.post("/wht/calculate", dependencies=[Depends(require_permission(["accounting.view", "buying.view"]))], response_model=Dict[str, Any])
def calculate_wht(data: WHTTransactionCreate, current_user=Depends(get_current_user)):
    """Calculate WHT amount without creating a transaction."""
    with transactional(current_user.company_id) as db:
        rate_row = db.execute(text("SELECT rate FROM wht_rates WHERE id = :id AND is_active = TRUE"),
                              {"id": data.wht_rate_id}).fetchone()
        if not rate_row:
            raise HTTPException(**http_error(404, "wht_rate_not_found"))
        
        wht_rate = _dec(rate_row.rate)
        gross_amount = _dec(data.gross_amount)
        wht_amount = (gross_amount * wht_rate / Decimal('100')).quantize(_D2, ROUND_HALF_UP)
        net_amount = (gross_amount - wht_amount).quantize(_D2, ROUND_HALF_UP)
        
        return {
            "gross_amount": data.gross_amount,
            "wht_rate": float(wht_rate),
            "wht_amount": wht_amount,
            "net_amount": net_amount
        }


@router.post("/wht/transactions", status_code=201, 
             dependencies=[Depends(require_permission(["accounting.edit", "taxes.manage"]))], response_model=Dict[str, Any])
def create_wht_transaction(data: WHTTransactionCreate, current_user=Depends(get_current_user)):
    """Create a WHT transaction and optionally post GL entries."""
    with transactional(current_user.company_id) as db:
        try:
            rate_row = db.execute(text("SELECT rate, name FROM wht_rates WHERE id = :id"),
                                  {"id": data.wht_rate_id}).fetchone()
            if not rate_row:
                raise HTTPException(**http_error(404, "wht_rate_not_found"))
            
            wht_rate = _dec(rate_row.rate)
            gross_amount = _dec(data.gross_amount)
            wht_amount = (gross_amount * wht_rate / Decimal('100')).quantize(_D2, ROUND_HALF_UP)
            net_amount = (gross_amount - wht_amount).quantize(_D2, ROUND_HALF_UP)
            
            # Generate certificate number
            cert_num = f"WHT-{datetime.now().year}-{datetime.now().strftime('%m%d%H%M%S')}"
            
            tid = db.execute(text("""
                INSERT INTO wht_transactions (
                    invoice_id, payment_id, supplier_id, wht_rate_id,
                    gross_amount, wht_rate, wht_amount, net_amount,
                    certificate_number, period_date, created_by
                ) VALUES (
                    :inv, :pay, :sup, :rate_id,
                    :gross, :rate, :wht, :net,
                    :cert, :period, :user
                ) RETURNING id
            """), {
                "inv": data.invoice_id, "pay": data.payment_id,
                "sup": data.supplier_id, "rate_id": data.wht_rate_id,
                "gross": gross_amount, "rate": wht_rate,
                "wht": wht_amount, "net": net_amount,
                "cert": cert_num, "period": datetime.now().date(),
                "user": current_user.id
            }).scalar()
            
            
            return {
                "id": tid,
                "certificate_number": cert_num,
                "gross_amount": data.gross_amount,
                "wht_rate": wht_rate,
                "wht_amount": wht_amount,
                "net_amount": net_amount
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
        return [dict(r._mapping) for r in rows]


# ==========================================================================
# TAX-F2 — WHT certificate PDF download (Phase-11 Sprint-5)
# ==========================================================================

@router.get("/wht/transactions/{tid}/certificate", dependencies=[Depends(require_permission(["accounting.view", "taxes.view"]))])
def download_wht_certificate(tid: int, current_user=Depends(get_current_user)):
    """Download an official PDF withholding-tax certificate."""
    from io import BytesIO
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import cm
    except ImportError:
        raise HTTPException(status_code=500, detail="reportlab not installed")
    from fastapi.responses import StreamingResponse

    with transactional(current_user.company_id) as db:
        row = db.execute(text("""
            SELECT wt.id, wt.certificate_number, wt.gross_amount, wt.wht_amount,
                   wt.net_amount, wt.wht_rate, wt.period_date, wt.created_at,
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

        company = db.execute(text("""
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
