# Contract: Credential Vault (`services/credentials_vault.py`)

**Feature**: 022-audit-security-finance-integrity

## Public interface

```python
def create_credential(tenant_id: int, integration: str, name: str, secret: str, metadata: dict | None = None, expires_at: datetime | None = None, actor_id: int | None = None) -> CredentialRef: ...

def get_credential(tenant_id: int, integration: str, name: str) -> CredentialPlain: ...

def rotate_credential(tenant_id: int, credential_id: int, new_secret: str, *, grace_seconds: int, actor_id: int) -> CredentialRef: ...

def soft_delete_credential(tenant_id: int, credential_id: int, *, actor_id: int) -> None: ...

def restore_credential(tenant_id: int, credential_id: int, *, actor_id: int) -> CredentialRef: ...

def record_failure(tenant_id: int, credential_id: int) -> None: ...

def record_success(tenant_id: int, credential_id: int) -> None: ...
```

## Behavior

- All writes MUST log to `audit_logs` via `log_activity()` (action = `credential.create | credential.rotate | credential.soft_delete | credential.restore`), with `critical = True`.
- `secret` MUST be encrypted via the existing tenant-aware key-derivation helper before persistence; raw secret never written to disk or logs.
- `get_credential` MUST refuse to return a `soft_deleted` row.
- `rotate_credential` MUST keep the old row in `status = 'rotating'` for `grace_seconds`, then transition it to `soft_deleted` via the scheduler.
- `record_failure` increments `consecutive_failures`; on reaching `bank_feed.failure_alert_threshold` (or integration-specific override), MUST enqueue a notification via the existing notification queue.
- `record_success` resets `consecutive_failures` to `0`.

## Migration of existing credentials

A one-shot migration script (NOT in Alembic — runs as a tenant-aware command):

```bash
python -m backend.scripts.migrate_credentials_to_vault --tenant <id|all>
```

- Reads all known scattered storage locations (ZATCA settings table, SMTP env-style settings, SMS gateway settings, payments/shipping configs, bank-feed config, LDAP config).
- Inserts into `integration_credentials`, marks origin in `metadata.origin`, and removes the old plaintext storage in a follow-up migration once code has switched.

## LDAP-over-HTTPS rule

- Storing/updating an LDAP credential when `ENV in {"prod", "production"}` MUST refuse if the request scheme is not HTTPS (return 400 with `code = "ldap_https_required"`).

## Forbidden patterns

- Reading integration secrets from anywhere except `credentials_vault.get_credential()`. CI scan: `scripts/check_credential_callsites.py`.
