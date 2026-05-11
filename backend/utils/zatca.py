"""
AMAN ERP - ZATCA Utilities
ZATCA-004: QR Code generation with TLV (Tag-Length-Value) encoding
ZATCA-002: Digital signing using SHA-256 with RSA
"""

import base64
import hashlib
import io
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any

import qrcode

import logging
from utils.tax_precision import money_str, q_money

logger = logging.getLogger(__name__)


# ======================== TLV Encoding ========================

def _tlv_encode(tag: int, value: str) -> bytes:
    """Encode a single TLV field per ZATCA spec."""
    value_bytes = value.encode("utf-8")
    return bytes([tag]) + bytes([len(value_bytes)]) + value_bytes


def build_zatca_tlv(
    seller_name: str,
    vat_number: str,
    timestamp: str,
    total_with_vat: str,
    vat_amount: str,
    invoice_hash: Optional[str] = None,
    digital_signature: Optional[str] = None
) -> str:
    """
    Build ZATCA-compliant TLV-encoded Base64 string.
    
    Tags (per ZATCA specification):
        1 = Seller Name (اسم البائع)
        2 = VAT Registration Number (الرقم الضريبي)
        3 = Timestamp ISO 8601 (تاريخ ووقت الفاتورة)
        4 = Invoice Total with VAT (الإجمالي شامل الضريبة)
        5 = VAT Amount (مبلغ الضريبة)
        6 = Invoice Hash (اختياري — مرحلة 2)
        7 = Digital Signature (اختياري — مرحلة 2)
    
    Returns: Base64-encoded TLV string
    """
    tlv_data = b""
    tlv_data += _tlv_encode(1, seller_name)
    tlv_data += _tlv_encode(2, vat_number)
    tlv_data += _tlv_encode(3, timestamp)
    tlv_data += _tlv_encode(4, total_with_vat)
    tlv_data += _tlv_encode(5, vat_amount)
    
    if invoice_hash:
        tlv_data += _tlv_encode(6, invoice_hash)
    if digital_signature:
        tlv_data += _tlv_encode(7, digital_signature)
    
    return base64.b64encode(tlv_data).decode("utf-8")


def decode_zatca_tlv(base64_string: str) -> Dict[int, str]:
    """Decode a ZATCA TLV Base64 string back to tag-value pairs (for verification)."""
    data = base64.b64decode(base64_string)
    result = {}
    pos = 0
    while pos < len(data):
        tag = data[pos]
        length = data[pos + 1]
        value = data[pos + 2: pos + 2 + length].decode("utf-8")
        result[tag] = value
        pos += 2 + length
    return result


# ======================== QR Code Generation ========================

def generate_zatca_qr_base64(
    seller_name: str,
    vat_number: str,
    timestamp: str,
    total_with_vat,
    vat_amount,
    invoice_hash: Optional[str] = None,
    digital_signature: Optional[str] = None,
    size: int = 200
) -> str:
    """
    Generate a ZATCA-compliant QR code and return it as a Base64-encoded PNG image.
    
    This can be embedded directly in HTML: <img src="data:image/png;base64,{result}" />
    """
    tlv_base64 = build_zatca_tlv(
        seller_name=seller_name,
        vat_number=vat_number,
        timestamp=timestamp,
        total_with_vat=money_str(total_with_vat),
        vat_amount=money_str(vat_amount),
        invoice_hash=invoice_hash,
        digital_signature=digital_signature
    )
    
    qr = qrcode.QRCode(
        version=None,  # Auto-determine
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=8,
        border=2
    )
    qr.add_data(tlv_base64)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Resize
    img = img.resize((size, size))
    
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


# ======================== Invoice Hashing ========================

def compute_invoice_hash(
    invoice_number: str,
    invoice_date: str,
    total,
    vat,
    seller_vat: str,
    previous_hash: Optional[str] = None
) -> str:
    """
    ZATCA-002: Compute SHA-256 hash of an invoice.
    Implements hash chaining — each invoice hash includes the previous invoice's hash.
    """
    data = f"{previous_hash or '0'}|{invoice_number}|{invoice_date}|{money_str(total)}|{money_str(vat)}|{seller_vat}"
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


# ======================== Digital Signing (RSA) ========================

def generate_rsa_keypair() -> tuple:
    """Generate RSA 2048-bit keypair for invoice signing. Returns (private_key_pem, public_key_pem)."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048
    )
    
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode("utf-8")
    
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode("utf-8")
    
    return private_pem, public_pem


def sign_invoice(invoice_hash: str, private_key_pem: str) -> str:
    """
    ZATCA-002: Sign an invoice hash using RSA + SHA-256.
    Returns Base64-encoded signature.
    """
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import serialization, hashes
    
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode("utf-8"),
        password=None
    )
    
    signature = private_key.sign(
        invoice_hash.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256()
    )
    
    return base64.b64encode(signature).decode("utf-8")


def verify_invoice_signature(invoice_hash: str, signature_b64: str, public_key_pem: str) -> bool:
    """Verify an invoice signature. Returns True if valid."""
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import serialization, hashes
    
    try:
        public_key = serialization.load_pem_public_key(
            public_key_pem.encode("utf-8")
        )
        signature = base64.b64decode(signature_b64)
        public_key.verify(
            signature,
            invoice_hash.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        return True
    except Exception:
        return False


# ======================== Full Pipeline ========================

def process_invoice_for_zatca(
    db,
    invoice_id: int,
    company_id: str,
    seller_name: str = None,
    vat_number: str = None,
    invoice_number: str = None,
    invoice_date: str = None,
    total=None,
    vat_amount=None,
    private_key_pem: Optional[str] = None
) -> Dict[str, Any]:
    """
    Full ZATCA processing pipeline for an invoice:
    1. Get previous invoice hash (for chain)
    2. Compute this invoice's hash
    3. Sign the hash (if private key provided)
    4. Generate QR code
    5. Store hash + signature + QR in DB
    6. Return all artifacts
    
    If seller_name/vat/invoice fields are not provided, auto-fetches from DB.
    """
    from sqlalchemy import text
    
    # Auto-fetch invoice data if not provided
    if not invoice_number or total is None:
        inv = db.execute(text("""
            SELECT invoice_number, invoice_date, total_amount, tax_amount
            FROM invoices WHERE id = :id
        """), {"id": invoice_id}).fetchone()
        if not inv:
            return None
        invoice_number = invoice_number or inv[0]
        invoice_date = invoice_date or str(inv[1])
        total = q_money(total if total is not None else Decimal(str(inv[2] or 0)))
        vat_amount = q_money(vat_amount if vat_amount is not None else Decimal(str(inv[3] or 0)))
    else:
        total = q_money(total)
        vat_amount = q_money(vat_amount)
    
    # Auto-fetch company info if not provided
    if not seller_name or not vat_number:
        settings_rows = db.execute(text("""
            SELECT setting_key, setting_value FROM company_settings
            WHERE setting_key IN ('company_name', 'vat_number')
        """)).fetchall()
        settings_map = {r[0]: r[1] for r in settings_rows}
        seller_name = seller_name or settings_map.get("company_name", "Unknown")
        vat_number = vat_number or settings_map.get("vat_number", "")
    
    # Auto-fetch private key if available
    if not private_key_pem:
        # T2.5: secret stored encrypted; helper falls back to plaintext for legacy rows.
        from utils.secret_settings import get_secret_setting  # local import: avoid cycle
        private_key_pem = get_secret_setting(db, "zatca_private_key", tenant_id=company_id)
    
    # 1. Get previous hash for chaining
    prev_hash_row = db.execute(text("""
        SELECT zatca_hash FROM invoices 
        WHERE id < :id AND zatca_hash IS NOT NULL 
        ORDER BY id DESC LIMIT 1
    """), {"id": invoice_id}).fetchone()
    
    previous_hash = prev_hash_row[0] if prev_hash_row else None
    
    # 2. Compute hash
    invoice_hash = compute_invoice_hash(
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        total=total,
        vat=vat_amount,
        seller_vat=vat_number,
        previous_hash=previous_hash
    )
    
    # 3. Sign (optional)
    digital_signature = None
    if private_key_pem:
        digital_signature = sign_invoice(invoice_hash, private_key_pem)
    
    # 4. ISO 8601 timestamp
    timestamp = datetime.fromisoformat(invoice_date).strftime("%Y-%m-%dT%H:%M:%SZ") if "T" not in invoice_date else invoice_date
    if "T" not in timestamp:
        timestamp = f"{invoice_date}T00:00:00Z"
    
    # 5. Generate QR
    qr_base64 = generate_zatca_qr_base64(
        seller_name=seller_name,
        vat_number=vat_number,
        timestamp=timestamp,
        total_with_vat=total,
        vat_amount=vat_amount,
        invoice_hash=invoice_hash,
        digital_signature=digital_signature
    )
    
    # 6. Store in DB
    db.execute(text("""
        UPDATE invoices SET 
            zatca_hash = :hash,
            zatca_signature = :sig,
            zatca_qr = :qr,
            zatca_status = 'generated'
        WHERE id = :id
    """), {
        "hash": invoice_hash,
        "sig": digital_signature,
        "qr": qr_base64,
        "id": invoice_id
    })
    
    return {
        "invoice_hash": invoice_hash,
        "digital_signature": digital_signature,
        "qr_base64": qr_base64,
        "qr_code_base64": qr_base64,
        "previous_hash": previous_hash,
        "zatca_status": "generated"
    }
