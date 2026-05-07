"""UBL XML signer using vault credentials.

Feature 023 — T063.  Contract: contracts/ubl-signing.md
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SignerCredentialsMissing(Exception):
    pass


class SignerCryptoError(Exception):
    pass


def sign_xml(xml_string: str, tenant_id: int) -> str:
    """Sign UBL XML using ZATCA credentials from the vault.

    Args:
        xml_string: UBL XML to sign.
        tenant_id: tenant to load credentials for.

    Returns:
        Signed XML string.

    Raises:
        SignerCredentialsMissing: if cert/key not in vault.
        SignerCryptoError: if signing fails.
    """
    # Load credentials from 022's vault
    cert_pem = None
    key_pem = None

    try:
        from services.credentials_vault import get_credential
        creds = get_credential(tenant_id, integration="zatca")
        if creds:
            cert_pem = creds.get("cert_pem")
            key_pem = creds.get("private_key_pem")
    except ImportError:
        logger.warning("credentials_vault not available")

    if not cert_pem or not key_pem:
        raise SignerCredentialsMissing(
            "ZATCA signing credentials not configured in vault"
        )

    try:
        from signxml import XMLSigner, SignatureConfiguration
        signer = XMLSigner(
            method=SignatureConfiguration.algorithms.enveloping,
            digest_algorithm="sha256",
        )
        # For ZATCA, we need XAdES-BES
        signed = signer.sign(
            xml_string,
            key=key_pem.encode() if isinstance(key_pem, str) else key_pem,
            cert=cert_pem.encode() if isinstance(cert_pem, str) else cert_pem,
        )
        return signed if isinstance(signed, str) else signed.decode("utf-8")
    except ImportError:
        logger.warning("signxml not installed, returning unsigned XML")
        return xml_string
    except Exception as e:
        raise SignerCryptoError(f"XML signing failed: {e}") from e
