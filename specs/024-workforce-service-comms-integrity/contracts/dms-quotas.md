# Contract: DMS Quotas

## Helpers

`services/dms/quotas.py::check_quota(tenant_id, user_id, incoming_size_bytes) -> QuotaCheck`
`services/dms/quotas.py::recompute(tenant_id) -> StorageQuota`

`QuotaCheck` fields: `tenant_used`, `tenant_limit`, `user_used`, `user_limit`, `would_exceed: 'tenant'|'user'|None`.

## Behavior

- Tenant quota = `company_settings.dms.tenant_quota_mb * 1024 * 1024`.
- Per-user quota = `company_settings.dms.user_quota_mb * 1024 * 1024`.
- `tenant_used` cached in Redis key `dms:tenant_used:<tenant_id>` with 60s TTL; invalidated on upload/delete via `INCR/DECR`.
- `user_used` cached similarly.
- Upload pipeline calls `check_quota` AFTER streaming MIME validation but BEFORE persisting bytes; rejects with HTTP 413 if `would_exceed` non-null.
- `recompute()` runs nightly to correct cache drift; writes snapshot to `storage_quotas`.

## Errors

| Code | When |
|------|------|
| 413 `dms.quota_exceeded` | Body: `{scope: 'tenant'\|'user', used, limit, incoming}`. |
