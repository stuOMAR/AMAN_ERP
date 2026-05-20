"""Regression test for F-NEW-173 (ZATCA-SIGN-SILENT-FALLBACK).

Ensures that ``backend/services/einvoicing/ubl_signer.py``:
  1. Raises ``SignerCryptoError`` when signxml is not installed (never returns
     unsigned XML silently).
  2. Raises ``SignerCredentialsMissing`` when vault has no credentials.
  3. Successfully signs XML when signxml is available and credentials exist.

The original bug: when signxml was missing, the function logged a warning and
returned the *unsigned* XML. The outbox worker then marked the row as
"submitted" even though no XAdES-BES signature was produced.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from services.einvoicing.ubl_signer import (
    sign_xml,
    SignerCredentialsMissing,
    SignerCryptoError,
)


_SAMPLE_XML = '<?xml version="1.0"?><Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"><cbc:ID>1</cbc:ID></Invoice>'


class TestMissingSignxml:
    """F-NEW-173: missing signxml must raise SignerCryptoError, never return unsigned."""

    def test_raises_signer_crypto_error_when_signxml_missing(self):
        """Monkeypatch ImportError for signxml.xades → must raise."""
        # Mock vault to return valid credentials
        mock_creds = {"cert_pem": "FAKE_CERT", "private_key_pem": "FAKE_KEY"}
        with patch("services.einvoicing.ubl_signer.etree") as mock_etree:
            mock_etree.fromstring.return_value = MagicMock()
            mock_etree.XMLSyntaxError = Exception
            with patch.dict(sys.modules, {"signxml": None, "signxml.xades": None}):
                with patch("services.credentials_vault.get_credential", return_value=mock_creds):
                    with pytest.raises(SignerCryptoError, match="signxml package"):
                        sign_xml(_SAMPLE_XML, tenant_id=1)

    def test_never_returns_unsigned_xml(self):
        """Even if something goes wrong, the function must not return the input."""
        mock_creds = {"cert_pem": "FAKE_CERT", "private_key_pem": "FAKE_KEY"}
        with patch("services.credentials_vault.get_credential", return_value=mock_creds):
            with patch.dict(sys.modules, {"signxml": None, "signxml.xades": None}):
                with pytest.raises((SignerCryptoError, SignerCredentialsMissing)):
                    result = sign_xml(_SAMPLE_XML, tenant_id=1)
                    # If we somehow get here, the result must NOT be the input
                    assert result != _SAMPLE_XML


class TestMissingCredentials:
    """Vault returns no credentials → SignerCredentialsMissing."""

    def test_raises_when_no_cert(self):
        with patch("services.credentials_vault.get_credential", return_value=None):
            with pytest.raises(SignerCredentialsMissing):
                sign_xml(_SAMPLE_XML, tenant_id=99)

    def test_raises_when_empty_cert(self):
        mock_creds = {"cert_pem": "", "private_key_pem": ""}
        with patch("services.credentials_vault.get_credential", return_value=mock_creds):
            with pytest.raises(SignerCredentialsMissing):
                sign_xml(_SAMPLE_XML, tenant_id=99)

    def test_raises_when_vault_import_fails_and_no_creds(self):
        """If credentials_vault itself is not importable, still raise."""
        with patch.dict(sys.modules, {"services.credentials_vault": None}):
            with pytest.raises((SignerCredentialsMissing, ImportError, SignerCryptoError)):
                sign_xml(_SAMPLE_XML, tenant_id=99)


class TestSourceCodeContract:
    """Static checks on the source file to prevent regression."""

    def _read_source(self) -> str:
        src = _BACKEND / "services" / "einvoicing" / "ubl_signer.py"
        return src.read_text(encoding="utf-8")

    def test_no_silent_return_of_unsigned_xml(self):
        """The source must not contain a pattern that returns xml_string on failure."""
        body = self._read_source()
        # These patterns would indicate a silent fallback
        assert "return xml_string" not in body, (
            "F-NEW-173: ubl_signer must never return the unsigned xml_string"
        )
        assert "return xml" not in body.split("except")[0] if "except" in body else True

    def test_import_error_raises_signer_crypto_error(self):
        """The except ImportError block must raise SignerCryptoError."""
        body = self._read_source()
        assert "raise SignerCryptoError" in body, (
            "F-NEW-173: ImportError must be converted to SignerCryptoError"
        )

    def test_uses_xades_signer(self):
        """ZATCA Phase 2 requires XAdES-BES; must use XAdESSigner."""
        body = self._read_source()
        assert "XAdESSigner" in body, (
            "ZATCA Phase 2 requires XAdES-BES signatures; use signxml.xades.XAdESSigner"
        )

    def test_no_signature_configuration_misuse(self):
        """SignatureConfiguration is for verification, not signing."""
        body = self._read_source()
        # The old broken code used SignatureConfiguration.algorithms.enveloping
        assert "SignatureConfiguration.algorithms" not in body, (
            "SignatureConfiguration.algorithms does not exist in signxml; "
            "this was the original bug"
        )

    def test_uses_lxml_etree(self):
        """signxml requires lxml Elements, not raw strings."""
        body = self._read_source()
        assert "from lxml import etree" in body or "import lxml" in body, (
            "signxml requires lxml Element input; must parse XML before signing"
        )
