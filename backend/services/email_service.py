"""
Email & SMS Notification Service - NOT-001, NOT-002
خدمة الإشعارات عبر البريد الإلكتروني و SMS
"""
import hashlib
import hmac
import html
import smtplib
import ssl
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, List
from sqlalchemy import text

logger = logging.getLogger("aman.email")


def _mask_email(value: str) -> str:
    local, _, domain = (value or "").partition("@")
    if not domain:
        return "***"
    visible = local[:1] if local else ""
    return f"{visible}***@{domain}"


def _mask_phone(value: str) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) <= 4:
        return "***"
    return f"***{digits[-4:]}"


# ===================== Email Service =====================

class EmailService:
    """SMTP Email Service with HTML template support."""

    def __init__(self, host: str, port: int, username: str, password: str,
                 from_email: str, from_name: str = "AMAN ERP", use_tls: bool = True):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_email = from_email
        self.from_name = from_name
        self.use_tls = use_tls

    def send(
        self,
        to: str,
        subject: str,
        html_body: str,
        text_body: str = None,
        unsubscribe_url: Optional[str] = None,
    ) -> bool:
        """Send an email. Returns True on success, False on failure."""
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{self.from_name} <{self.from_email}>"
            msg["To"] = to
            # RFC 8058 / RFC 2369 List-Unsubscribe header
            if unsubscribe_url:
                msg["List-Unsubscribe"] = (
                    f"<mailto:unsubscribe@aman-erp.com?subject=unsubscribe>, "
                    f"<{unsubscribe_url}>"
                )
                msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

            if text_body:
                msg.attach(MIMEText(text_body, "plain", "utf-8"))
            msg.attach(MIMEText(html_body, "html", "utf-8"))

            if self.use_tls:
                context = ssl.create_default_context()
                with smtplib.SMTP(self.host, self.port, timeout=30) as server:
                    server.ehlo()
                    server.starttls(context=context)
                    server.ehlo()
                    server.login(self.username, self.password)
                    server.sendmail(self.from_email, to, msg.as_string())
            else:
                with smtplib.SMTP_SSL(self.host, self.port, timeout=30) as server:
                    server.login(self.username, self.password)
                    server.sendmail(self.from_email, to, msg.as_string())

            logger.info(f"✅ Email sent to {to}: {subject}")
            return True
        except Exception:
            logger.exception(f"Email send failed to {to}")
            return False

    def send_bulk(self, recipients: List[str], subject: str, html_body: str) -> dict:
        """Send to multiple recipients. Returns success/failure counts and per-user failures."""
        success = 0
        failed = 0
        failed_recipients = []
        for email in recipients:
            if self.send(email, subject, html_body):
                success += 1
            else:
                failed += 1
                failed_recipients.append({"email": _mask_email(email), "reason": "send_failed"})
        return {"sent": success, "failed": failed, "failures": failed_recipients}


# ===================== SMS Service =====================

class SMSService:
    """SMS Notification Service - Saudi SMS gateway integration."""

    def __init__(self, api_url: str, api_key: str, sender_name: str = "AMAN"):
        self.api_url = api_url
        self.api_key = api_key
        self.sender_name = sender_name

    def send(self, phone: str, message: str) -> bool:
        """Send an SMS. Returns True on success."""
        try:
            import requests
            response = requests.post(self.api_url, json={
                "api_key": self.api_key,
                "sender": self.sender_name,
                "to": phone,
                "message": message
            }, timeout=10)
            if response.status_code == 200:
                logger.info("SMS sent to %s", _mask_phone(phone))
                return True
            else:
                logger.error("SMS failed to %s: %s", _mask_phone(phone), response.text)
                return False
        except Exception as e:
            logger.error("SMS send failed to %s: %s", _mask_phone(phone), str(e))
            return False


# ===================== Email Templates =====================

def get_base_template(content: str, company_name: str = "AMAN ERP") -> str:
    """Wrap content in a styled HTML email template."""
    return f"""
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Arial, sans-serif; margin: 0; padding: 0; background-color: #f5f5f5; direction: rtl; }}
            .container {{ max-width: 600px; margin: 20px auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
            .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 24px; text-align: center; }}
            .header h1 {{ margin: 0; font-size: 22px; font-weight: 600; }}
            .body {{ padding: 32px 24px; color: #333; line-height: 1.8; }}
            .body h2 {{ color: #667eea; margin-bottom: 12px; }}
            .btn {{ display: inline-block; padding: 12px 32px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white !important; text-decoration: none; border-radius: 8px; margin-top: 16px; font-weight: 600; }}
            .footer {{ background: #f9f9f9; padding: 16px 24px; text-align: center; color: #999; font-size: 12px; border-top: 1px solid #eee; }}
            .info-box {{ background: #f0f4ff; border-right: 4px solid #667eea; padding: 16px; border-radius: 8px; margin: 16px 0; }}
            .amount {{ font-size: 24px; font-weight: bold; color: #667eea; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🏢 {company_name}</h1>
            </div>
            <div class="body">
                {content}
            </div>
            <div class="footer">
                <p>هذه رسالة تلقائية من نظام {company_name} - لا ترد على هذا البريد</p>
            </div>
        </div>
    </body>
    </html>
    """


def approval_request_template(requester: str, document_type: str, amount: float,
                               description: str, approval_url: str) -> str:
    """Email template for new approval request.

    P1 #92 fix: HTML-escape every user-controlled value before splicing
    into the template body. ``approval_url`` is escaped for attribute
    context to defang ``" onclick=...`` style payloads.
    """
    doc_labels = {
        "purchase_order": "أمر شراء",
        "expense": "مصروف",
        "leave_request": "طلب إجازة",
        "payment_voucher": "سند صرف",
        "sales_order": "أمر بيع",
    }
    doc_label = doc_labels.get(document_type, html.escape(str(document_type or "")))
    safe_requester = html.escape(str(requester or ""))
    safe_description = html.escape(str(description or ""))
    safe_url = html.escape(str(approval_url or ""), quote=True)

    content = f"""
    <h2>📋 طلب اعتماد جديد</h2>
    <div class="info-box">
        <p><strong>النوع:</strong> {doc_label}</p>
        <p><strong>من:</strong> {safe_requester}</p>
        <p><strong>المبلغ:</strong> <span class="amount">{amount:,.2f}</span></p>
        <p><strong>الوصف:</strong> {safe_description}</p>
    </div>
    <a href="{safe_url}" class="btn">مراجعة واعتماد</a>
    """
    return get_base_template(content)


def approval_result_template(status: str, document_type: str, amount: float,
                              notes: str = "", approver: str = "") -> str:
    """Email template for approval result notification.

    P1 #92 fix: HTML-escape user values (notes, approver, document_type).
    """
    doc_labels = {
        "purchase_order": "أمر شراء",
        "expense": "مصروف",
        "leave_request": "طلب إجازة",
    }
    doc_label = doc_labels.get(document_type, html.escape(str(document_type or "")))
    safe_notes = html.escape(str(notes or ""))
    safe_approver = html.escape(str(approver or ""))

    status_labels = {
        "approved": ("✅ تم الاعتماد", "#28a745"),
        "rejected": ("❌ تم الرفض", "#dc3545"),
        "returned": ("🔄 تم الإرجاع", "#ffc107"),
    }
    label, color = status_labels.get(status, ("📋 تحديث", "#667eea"))

    content = f"""
    <h2 style="color: {color};">{label}</h2>
    <div class="info-box">
        <p><strong>النوع:</strong> {doc_label}</p>
        <p><strong>المبلغ:</strong> <span class="amount">{amount:,.2f}</span></p>
        {"<p><strong>المعتمد:</strong> " + safe_approver + "</p>" if safe_approver else ""}
        {"<p><strong>ملاحظات:</strong> " + safe_notes + "</p>" if safe_notes else ""}
    </div>
    """
    return get_base_template(content)


def invoice_template(invoice_number: str, customer_name: str, total: float,
                      due_date: str, items_html: str = "") -> str:
    """Email template for invoice notification."""
    safe_invoice_number = html.escape(str(invoice_number or ""))
    safe_customer_name = html.escape(str(customer_name or ""))
    safe_due_date = html.escape(str(due_date or ""))
    content = f"""
    <h2>📄 فاتورة جديدة</h2>
    <div class="info-box">
        <p><strong>رقم الفاتورة:</strong> {safe_invoice_number}</p>
        <p><strong>العميل:</strong> {safe_customer_name}</p>
        <p><strong>الإجمالي:</strong> <span class="amount">{total:,.2f}</span></p>
        <p><strong>تاريخ الاستحقاق:</strong> {safe_due_date}</p>
    </div>
    {items_html}
    """
    return get_base_template(content)


def payroll_template(employee_name: str, period: str, net_salary: float,
                      gross: float, deductions: float) -> str:
    """Email template for payroll notification."""
    safe_employee_name = html.escape(str(employee_name or ""))
    safe_period = html.escape(str(period or ""))
    content = f"""
    <h2>💰 إشعار راتب</h2>
    <p>مرحباً <strong>{safe_employee_name}</strong>،</p>
    <div class="info-box">
        <p><strong>الفترة:</strong> {safe_period}</p>
        <p><strong>الراتب الإجمالي:</strong> {gross:,.2f}</p>
        <p><strong>الاستقطاعات:</strong> {deductions:,.2f}</p>
        <p><strong>صافي الراتب:</strong> <span class="amount">{net_salary:,.2f}</span></p>
    </div>
    """
    return get_base_template(content)


def expiry_alert_template(item_type: str, item_name: str, expiry_date: str,
                           days_remaining: int) -> str:
    """Email template for expiry alerts (documents, iqama, etc.)."""
    urgency = "🔴" if days_remaining <= 7 else "🟡" if days_remaining <= 30 else "🟢"
    safe_item_type = html.escape(str(item_type or ""))
    safe_item_name = html.escape(str(item_name or ""))
    safe_expiry_date = html.escape(str(expiry_date or ""))

    content = f"""
    <h2>{urgency} تنبيه انتهاء صلاحية</h2>
    <div class="info-box">
        <p><strong>النوع:</strong> {safe_item_type}</p>
        <p><strong>الاسم:</strong> {safe_item_name}</p>
        <p><strong>تاريخ الانتهاء:</strong> {safe_expiry_date}</p>
        <p><strong>الأيام المتبقية:</strong> <span class="amount">{days_remaining}</span> يوم</p>
    </div>
    """
    return get_base_template(content)


# ===================== DB-backed Template Engine =====================

def render_db_template(db, template_name: str, context: dict) -> Optional[str]:
    """Render an HTML email template stored in the ``email_templates`` table.

    Performs a simple ``str.format_map`` substitution using ``context``.
    Returns the rendered HTML string, or ``None`` when the template is not
    found in the database (callers should then fall back to hardcoded templates).

    Security: context values are NOT html-escaped here — callers must ensure
    that user-supplied values are sanitised before passing to this function.
    """
    try:
        row = db.execute(
            text(
                "SELECT body, subject FROM email_templates "
                "WHERE template_name = :name AND is_active = TRUE LIMIT 1"
            ),
            {"name": template_name},
        ).fetchone()
        if not row or not row.body:
            return None
        rendered = row.body.format_map(context)
        return rendered
    except Exception as exc:
        logger.warning("render_db_template(%s) failed: %s", template_name, exc)
        return None


def get_db_template_subject(db, template_name: str) -> Optional[str]:
    """Return the subject line for a DB-stored email template, or None."""
    try:
        row = db.execute(
            text(
                "SELECT subject FROM email_templates "
                "WHERE template_name = :name AND is_active = TRUE LIMIT 1"
            ),
            {"name": template_name},
        ).fetchone()
        return row.subject if row and row.subject else None
    except Exception:
        return None


# ===================== Unsubscribe Token Helpers =====================

def _get_secret_key() -> bytes:
    """Return the application secret key as bytes for HMAC signing."""
    try:
        from config import get_settings
        return get_settings().SECRET_KEY.encode()
    except Exception:
        return b"aman-fallback-key"


def generate_unsubscribe_token(user_id: int, event_type: Optional[str] = None) -> str:
    """Generate a signed HMAC-SHA256 unsubscribe token.

    Format: ``{user_id}:{event_type}:{signature}``
    event_type may be empty string for 'all events'.
    """
    event_type = event_type or ""
    payload = f"{user_id}:{event_type}"
    sig = hmac.new(
        _get_secret_key(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return f"{payload}:{sig}"


def verify_unsubscribe_token(token: str) -> Optional[dict]:
    """Verify an unsubscribe token and return ``{user_id, event_type}`` or None."""
    try:
        parts = token.split(":")
        if len(parts) != 3:
            return None
        user_id_str, event_type, sig = parts
        payload = f"{user_id_str}:{event_type}"
        expected = hmac.new(
            _get_secret_key(), payload.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        return {"user_id": int(user_id_str), "event_type": event_type or None}
    except Exception:
        return None


# ===================== Notification Helper =====================

def get_email_service_from_settings(db, *, tenant_id: Optional[str] = None) -> Optional[EmailService]:
    """Create an EmailService instance from company_settings."""
    try:
        settings = db.execute(text("""
            SELECT setting_key, setting_value FROM company_settings
            WHERE setting_key IN ('smtp_host', 'smtp_port', 'smtp_username', 'smtp_password', 'smtp_from_email', 'smtp_from_name', 'smtp_tls')
        """)).fetchall()

        config = {s.setting_key: s.setting_value for s in settings}

        if not config.get("smtp_host") or not config.get("smtp_username"):
            return None

        # T2.5: smtp_password may be encrypted at rest; transparently decrypt.
        if tenant_id:
            from utils.secret_settings import decrypt_settings_map
            config = decrypt_settings_map(config, tenant_id=tenant_id, only_keys=("smtp_password",))

        return EmailService(
            host=config["smtp_host"],
            port=int(config.get("smtp_port", 587)),
            username=config["smtp_username"],
            password=config.get("smtp_password", ""),
            from_email=config.get("smtp_from_email", config["smtp_username"]),
            from_name=config.get("smtp_from_name", "AMAN ERP"),
            use_tls=config.get("smtp_tls", "true").lower() == "true"
        )
    except Exception as e:
        logger.error(f"Failed to create EmailService: {str(e)}")
        return None


def get_sms_service_from_settings(db, *, tenant_id: Optional[str] = None) -> Optional[SMSService]:
    """Create an SMSService instance from company_settings."""
    try:
        settings = db.execute(text("""
            SELECT setting_key, setting_value FROM company_settings
            WHERE setting_key IN ('sms_api_url', 'sms_api_key', 'sms_sender_name')
        """)).fetchall()

        config = {s.setting_key: s.setting_value for s in settings}

        if not config.get("sms_api_url") or not config.get("sms_api_key"):
            return None

        # T2.5: sms_api_key may be encrypted at rest; transparently decrypt.
        if tenant_id:
            from utils.secret_settings import decrypt_settings_map
            config = decrypt_settings_map(config, tenant_id=tenant_id, only_keys=("sms_api_key",))

        return SMSService(
            api_url=config["sms_api_url"],
            api_key=config["sms_api_key"],
            sender_name=config.get("sms_sender_name", "AMAN")
        )
    except Exception as e:
        logger.error(f"Failed to create SMSService: {str(e)}")
        return None


def send_notification_email(db, user_id: int, subject: str, html_body: str, *, tenant_id: Optional[str] = None) -> bool:
    """Send an email notification to a specific user using SMTP settings from company_settings."""
    try:
        # Get user's email
        user = db.execute(text("SELECT email FROM company_users WHERE id = :id"), {"id": user_id}).fetchone()
        if not user or not user.email:
            return False

        email_service = get_email_service_from_settings(db, tenant_id=tenant_id)
        if not email_service:
            logger.warning("SMTP not configured, skipping email notification")
            return False

        # Generate unsubscribe URL so recipients can opt-out via email footer
        try:
            unsub_token = generate_unsubscribe_token(user_id)
            from config import get_settings as _gs
            base = getattr(_gs(), "BASE_URL", "https://aman-erp.com")
        except Exception:
            unsub_token = None
            base = "https://aman-erp.com"
        unsubscribe_url = f"{base}/api/notifications/unsubscribe?token={unsub_token}" if unsub_token else None

        return email_service.send(user.email, subject, html_body, unsubscribe_url=unsubscribe_url)
    except Exception as e:
        logger.error(f"Failed to send notification email: {str(e)}")
        return False


def send_notification_sms(db, user_id: int, message: str, *, tenant_id: Optional[str] = None) -> bool:
    """Send an SMS notification to a specific user."""
    try:
        user = db.execute(text("SELECT phone FROM company_users WHERE id = :id"), {"id": user_id}).fetchone()
        if not user or not user.phone:
            return False

        sms_service = get_sms_service_from_settings(db, tenant_id=tenant_id)
        if not sms_service:
            logger.warning("SMS not configured, skipping SMS notification")
            return False

        return sms_service.send(user.phone, message)
    except Exception as e:
        logger.error(f"Failed to send SMS notification: {str(e)}")
        return False
