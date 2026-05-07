# Contract: UBL Builder & Signer

**Modules**: `services/einvoicing/ubl_builder.py`, `services/einvoicing/ubl_signer.py`.

## Purpose

Build a ZATCA-conformant UBL 2.1 invoice document from an `Invoice` and sign it inline using credentials from 022's `credentials_vault`. Replaces the external signer dependency and the duplicated builder used in legacy POS.

## Builder

```
build_ubl(invoice, *, profile: Literal['standard', 'simplified']) -> bytes
```

- Inputs:
  - `invoice` — fully resolved invoice row + lines + tenant party + buyer party.
  - `profile` — controls invoice type code, party identification rules, payment means, line content.
- Output: UBL XML bytes, validated against the bundled XSD before return.
- Errors:
  - `UblValidationError` — structured per element/path, sanitized.
  - `MissingTenantParty` — tenant lacks required ZATCA registration data.

## Signer

```
sign_ubl(xml_bytes: bytes, *, tenant_id: int) -> bytes
```

- Loads `(cert_pem, private_key_pem)` from `credentials_vault.get(tenant_id, integration='zatca')`.
- Computes invoice hash (SHA-256), embeds prior-invoice-hash chain reference (read from `zatca_outbox.previous_hash` or `None` for the first).
- Signs the document using XAdES-BES style as specified by ZATCA. Library: `signxml` (or vetted in-house wrapper); the choice is fixed to one to keep behavior deterministic.
- Returns signed XML bytes.
- Errors:
  - `SignerCredentialsMissing` — vault returns nothing.
  - `SignerCryptoError` — sanitized.

## No external service

Both functions run in-process. There is no HTTP signer dependency. CI grep forbids any reintroduction of the old external signer URL/config keys.

## Audit

Signing failures audited as `einvoicing.signer.failed` with sanitized error.
