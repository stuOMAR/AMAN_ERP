"""
AMAN ERP - Webhook Utilities
API-002: Send webhooks with retry logic and logging.
"""

import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import socket
import threading
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import requests
from cryptography.fernet import Fernet
from sqlalchemy import text

logger = logging.getLogger(__name__)


def _get_fernet() -> Fernet:
    """Derive a Fernet key from SECRET_KEY for webhook secret encryption."""
    from config import settings
    key = base64.urlsafe_b64encode(
        hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    )
    return Fernet(key)


def encrypt_webhook_secret(plaintext: str) -> str:
    """Encrypt a webhook secret for storage."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_webhook_secret(ciphertext: str) -> str:
    """Decrypt a stored webhook secret."""
    return _get_fernet().decrypt(ciphertext.encode()).decode()

# ── Private/reserved IP ranges blocked for SSRF protection ───────────────────
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def validate_webhook_url(url: str) -> None:
    """
    Validate a webhook URL is safe from SSRF attacks.

    Checks:
    - Only http/https schemes allowed
    - Hostname resolves to a public (non-private/reserved) IP
    - Blocks loopback, link-local, and private ranges
    - SEC-10: optional hostname allowlist via WEBHOOK_HOSTNAME_ALLOWLIST
      env var (comma-separated). When set, only those exact hostnames
      (or sub-domains) are accepted. Leave unset to permit any public host.

    Raises ValueError if the URL is unsafe.
    """
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http and https schemes are allowed")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL must include a hostname")

    # SEC-10: hostname allowlist (outbound webhook policy)
    raw_allow = os.environ.get("WEBHOOK_HOSTNAME_ALLOWLIST", "").strip()
    if raw_allow:
        allow = [h.strip().lower().lstrip(".") for h in raw_allow.split(",") if h.strip()]
        host_l = hostname.lower()
        matched = any(
            host_l == a or host_l.endswith("." + a)
            for a in allow
        )
        if not matched:
            raise ValueError(
                f"Hostname '{hostname}' is not in WEBHOOK_HOSTNAME_ALLOWLIST"
            )

    try:
        addr_infos = socket.getaddrinfo(hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ValueError("Could not resolve hostname")

    for family, _, _, _, sockaddr in addr_infos:
        ip = ipaddress.ip_address(sockaddr[0])
        for network in _BLOCKED_NETWORKS:
            if ip in network:
                raise ValueError("URL resolves to a blocked IP range")


# Supported events
WEBHOOK_EVENTS = [
    "invoice.created", "invoice.paid", "invoice.cancelled",
    "order.created", "order.confirmed", "order.delivered",
    "payment.received", "payment.refunded",
    "inventory.low_stock", "inventory.adjustment",
    "purchase.created", "purchase.approved",
    "employee.leave_request", "employee.attendance",
    "ticket.created", "ticket.resolved",
    "opportunity.stage_changed", "opportunity.won", "opportunity.lost",
]


def _compute_signature(payload: str, secret: str) -> str:
    """Compute HMAC-SHA256 signature for payload verification."""
    return hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def _send_single_webhook(webhook_id: int, url: str, secret: Optional[str],
                          event: str, payload: dict, timeout: int,
                          retry_count: int, db_factory):
    """Send webhook with retry logic (runs in background thread)."""
    # Defense-in-depth SSRF check before dispatch (DNS rebinding protection)
    try:
        validate_webhook_url(url)
    except ValueError as e:
        logger.warning("Webhook %d blocked by SSRF check: %s - %s", webhook_id, url, e)
        return

    payload_json = json.dumps(payload, default=str, ensure_ascii=False)
    
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "X-Webhook-Event": event,
        "X-Webhook-Timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    if secret:
        try:
            decrypted_secret = decrypt_webhook_secret(secret)
        except Exception:
            logger.warning("Webhook %d: failed to decrypt secret, using raw", webhook_id)
            decrypted_secret = secret
        headers["X-Webhook-Signature"] = _compute_signature(payload_json, decrypted_secret)
    
    for attempt in range(1, retry_count + 1):
        response_status = None
        response_body = None
        error_msg = None
        success = False
        
        try:
            resp = requests.post(url, data=payload_json, headers=headers, timeout=timeout)
            response_status = resp.status_code
            response_body = resp.text[:2000]  # Limit stored body size
            success = 200 <= resp.status_code < 300
        except requests.Timeout:
            error_msg = f"Timeout after {timeout}s"
        except requests.ConnectionError as e:
            error_msg = f"Connection error: {str(e)[:200]}"
        except Exception as e:
            error_msg = f"Error: {str(e)[:200]}"
        
        # Log this attempt
        try:
            db = db_factory()
            db.execute(text("""
                INSERT INTO webhook_logs (webhook_id, event, payload, response_status, response_body, success, attempt, error_message)
                VALUES (:wid, :event, :payload, :status, :body, :success, :attempt, :error)
            """), {
                "wid": webhook_id,
                "event": event,
                "payload": payload_json,
                "status": response_status,
                "body": response_body,
                "success": success,
                "attempt": attempt,
                "error": error_msg
            })
            db.commit()
            db.close()
        except Exception as log_err:
            logger.error(f"Failed to log webhook attempt: {log_err}")
        
        if success:
            logger.info(f"✅ Webhook #{webhook_id} sent: {event} → {url} (attempt {attempt})")
            return
        
        if attempt < retry_count:
            import time
            # IN-F5: per-adapter retry backoff knob (env override)
            try:
                backoff_base = float(os.environ.get("WEBHOOK_RETRY_BACKOFF_BASE", "2"))
                backoff_cap = float(os.environ.get("WEBHOOK_RETRY_BACKOFF_CAP_SEC", "60"))
            except ValueError:
                backoff_base, backoff_cap = 2.0, 60.0
            wait = min(backoff_base ** attempt, backoff_cap)
            logger.warning(f"⚠️ Webhook #{webhook_id} failed (attempt {attempt}), retrying in {wait}s...")
            time.sleep(wait)
    
    logger.error(f"❌ Webhook #{webhook_id} failed after {retry_count} attempts: {event} → {url}")
    try:
        db = db_factory()
        db.execute(text("""
            INSERT INTO integration_dlq (
                queue_type, queue_item_id, provider, final_status, reason,
                payload, gateway_response
            ) VALUES (
                'webhook', :wid, 'outgoing_webhook', 'permanently_failed', :reason,
                CAST(:payload AS JSONB), CAST(:gateway_response AS JSONB)
            )
        """), {
            "wid": webhook_id,
            "reason": (error_msg or "max retries exceeded")[:1000],
            "payload": json.dumps({"event": event, "target_url": url, "payload": payload}, default=str),
            "gateway_response": json.dumps({
                "status": response_status,
                "body": response_body,
                "attempts": retry_count,
            }, default=str),
        })
        db.commit()
        db.close()
    except Exception as dlq_err:
        logger.error(f"Failed to move webhook #{webhook_id} to DLQ: {dlq_err}")


def fire_webhook_event(db, event: str, payload: dict, db_factory=None):
    """
    Fire a webhook event to all subscribed active webhooks.
    Runs in background threads so it doesn't block the request.
    
    Usage:
        fire_webhook_event(db, "invoice.created", {"invoice_id": 123, "total": 5000})
    """
    if not db_factory:
        logger.warning("No db_factory provided for webhook logging")
        return
    
    try:
        webhooks = db.execute(text("""
            SELECT id, url, secret, retry_count, timeout_seconds 
            FROM webhooks 
            WHERE is_active = TRUE AND events @> :event::jsonb
        """), {"event": json.dumps([event])}).fetchall()
        
        # IN-F5: env-level caps for timeout + retry_count (safety net)
        try:
            max_retries_env = int(os.environ.get("WEBHOOK_RETRY_MAX_ATTEMPTS", "0") or 0)
            max_timeout_env = int(os.environ.get("WEBHOOK_TIMEOUT_MAX_SEC", "0") or 0)
        except ValueError:
            max_retries_env, max_timeout_env = 0, 0

        for wh in webhooks:
            effective_retries = wh.retry_count or 3
            effective_timeout = wh.timeout_seconds or 10
            if max_retries_env > 0:
                effective_retries = min(effective_retries, max_retries_env)
            if max_timeout_env > 0:
                effective_timeout = min(effective_timeout, max_timeout_env)
            thread = threading.Thread(
                target=_send_single_webhook,
                args=(wh.id, wh.url, wh.secret, event, payload,
                      effective_timeout, effective_retries, db_factory),
                daemon=True
            )
            thread.start()
    except Exception as e:
        logger.error(f"Error firing webhook event {event}: {e}")
