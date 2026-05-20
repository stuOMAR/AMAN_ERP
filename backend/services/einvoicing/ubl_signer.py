"""UBL XML signer using vault credentials.

Feature 023 — T063.  Contract: contracts/ubl-signing.md

Implements XAdES-BES enveloped signature as required by ZATCA Phase 2
Clearance. Uses the ``signxml`` library (v4.x) with its XAdES extension.

Audit trail:
  - F-NEW-173 (ZATCA-SIGN-SILENT-FALLBACK): missing ``signxml`` now raises
    ``SignerCryptoError`` — never silently returns unsigned XML.
"""
from __future__ import annotations

import logging
from typing import Any

from lxml import etree

logger = logging.getLogger(__name__)


class SignerCredentialsMissing(Exception):
    """Raised when ZATCA signing credentials are not available in the vault."""
    pass


class SignerCryptoError(Exception):
    """Raised when XML signing fails for any reason (missing lib, bad cert, etc.)."""
    pass


def sign_xml(xml_string: str, tenant_id: int) -> str:
    """Sign UBL XML using ZATCA credentials from the vault.

    The function produces an XAdES-BES enveloped signature using SHA-256,
    which is the minimum requirement for ZATCA Phase 2 Clearance.

    Args:
        xml_string: UBL 2.1 XML document to sign.
        tenant_id: tenant whose credentials to load from the vault.

    Returns:
        Signed XML string (UTF-8).

    Raises:
        SignerCredentialsMissing: if cert/key not found in vault for tenant.
        SignerCryptoError: if signxml is not installed or signing fails.
    """
    # ── 1. Load credentials from vault ──────────────────────────────────
    cert_pem: str | None = None
    key_pem: str | None = None

    try:
        from services.credentials_vault import get_credential
        creds = get_credential(tenant_id, integration="zatca")
        if creds:
            cert_pem = creds.get("cert_pem")
            key_pem = creds.get("private_key_pem")
    except ImportError:
        logger.warning("credentials_vault module not available")

    if not cert_pem or not key_pem:
        raise SignerCredentialsMissing(
            f"ZATCA signing credentials not configured in vault for tenant {tenant_id}"
        )

    # ── 2. Parse XML into lxml Element (required by signxml) ────────────
    try:
        root = etree.fromstring(xml_string.encode("utf-8") if isinstance(xml_string, str) else xml_string)
    except etree.XMLSyntaxError as e:
        raise SignerCryptoError(f"XML parsing failed: {e}") from e

    # ── 3. Sign with XAdES-BES (ZATCA requirement) ──────────────────────
    try:
        from signxml.xades import XAdESSigner
    except ImportError as e:
        raise SignerCryptoError(
            "XML signing failed: signxml package (with XAdES support) is required; "
            "refusing to submit unsigned XML. Install with: pip install signxml>=4.0"
        ) from e

    try:
        signer = XAdESSigner(
            c14n_algorithm="http://www.w3.org/2006/12/xml-c14n11",
        )
        key_bytes = key_pem.encode("utf-8") if isinstance(key_pem, str) else key_pem
        cert_bytes = cert_pem.encode("utf-8") if isinstance(cert_pem, str) else cert_pem

        signed_root = signer.sign(
            root,
            key=key_bytes,
            cert=cert_bytes,
        )
        return etree.tostring(signed_root, xml_declaration=True, encoding="UTF-8").decode("utf-8")
    except Exception as e:
        raise SignerCryptoError(f"XML signing failed: {e}") from e
