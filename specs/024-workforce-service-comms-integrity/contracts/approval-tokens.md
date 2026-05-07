# Contract: Signed Approval Tokens

## Helpers

`services/auth/approval_tokens.py::issue(action, target_id, ttl_minutes=None, issuer_user_id) -> token_str`
`services/auth/approval_tokens.py::verify_and_consume(token_str, action, target_id, consumer_user_id, ip) -> ConsumeResult`

## Token Format

```
token = base64url(json({tenant_id, action, target_id, issued_at, expires_at, nonce, issuer_user_id}))
       + "."
       + base64url(hmac_sha256(signing_key, payload))
```

`signing_key` from 022's vault key `approval_token_signing_key` (rotatable; tokens carry `kid` to support rotation).

`nonce` = 32 hex chars (`secrets.token_hex(16)`).

## Verify Flow (in one `transactional()`)

1. Split `payload.signature`; recompute HMAC; reject on mismatch (HTTP 401 `approval_token.invalid_signature`).
2. Decode payload; reject if `action`/`target_id`/`tenant_id` mismatch (HTTP 422 `approval_token.scope_mismatch`).
3. Reject if `now() > expires_at` (HTTP 410 `approval_token.expired`).
4. INSERT into `approval_tokens` with the partial unique on `(nonce) WHERE consumed_at IS NULL`.
   - On conflict: HTTP 409 `approval_token.consumed`.
5. Set `consumed_at`, `consumed_by_user_id`, `consumed_via_ip`.
6. Audit `approval_token.consumed`.

## TTL

Default `company_settings.auth.approval_token_ttl_minutes` = 1440 (24h). Issuer can pass shorter; longer requires `auth.long_lived_tokens` permission.

## Sweeper

`approval_tokens` rows with `expires_at < now() - 30d` are deleted by a daily sweeper.

## CI Lint

`scripts/check_approval_tokens.py` — flag any HMAC issuance/verification of approval-action tokens outside `services/auth/approval_tokens.py`.

## Errors

| Code | When |
|------|------|
| 401 `approval_token.invalid_signature` | HMAC mismatch. |
| 410 `approval_token.expired` | Past `expires_at`. |
| 409 `approval_token.consumed` | Replay. |
| 422 `approval_token.scope_mismatch` | `action`/`target_id`/`tenant_id` mismatch. |
