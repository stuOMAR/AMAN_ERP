# Contract: HTTP Endpoints

**Feature**: 022-audit-security-finance-integrity

All endpoints below MUST declare `require_permission()`; the ones marked **Sensitive** MUST also declare `require_sensitive_permission(scope, critical=...)`. Pydantic schemas live under `backend/schemas/` and are produced during implementation; this contract specifies the verbs, paths, status codes, and error shapes.

## Admin: Integration credentials  *(Sensitive — `admin.credentials`, critical=True)*

| Method | Path | Status | Notes |
|--------|------|--------|-------|
| GET | `/api/admin/credentials` | 200 | List (excludes soft-deleted by default; `?include_deleted=true` includes them; secrets never returned). |
| POST | `/api/admin/credentials` | 201 | Create. Body: `{integration, name, secret, metadata?, expires_at?}`. |
| GET | `/api/admin/credentials/{id}` | 200 | Detail (no secret). |
| POST | `/api/admin/credentials/{id}/rotate` | 200 | Body: `{new_secret, grace_seconds?}`. |
| POST | `/api/admin/credentials/{id}/soft-delete` | 204 | |
| POST | `/api/admin/credentials/{id}/restore` | 200 | |

Errors: `409 ldap_https_required`, `409 duplicate_name`, `404 not_found`, `403` per permission gate.

## Admin: Account classifications  *(Sensitive — `admin.account_classifications`, critical=True)*

| Method | Path | Status | Notes |
|--------|------|--------|-------|
| GET | `/api/admin/account-classifications` | 200 | List with filters (`account_id`, `is_active`, `as_of`). |
| POST | `/api/admin/account-classifications` | 201 | Upsert. Body: `{account_id, statement_category, sign, aggregation_hint?, valid_from, valid_to?}`. |
| POST | `/api/admin/account-classifications/preview` | 200 | Dry-run that returns affected reports. |

## Admin: Recurring template review queue  *(Sensitive — `admin.recurring`, critical=True)*

| Method | Path | Status | Notes |
|--------|------|--------|-------|
| GET | `/api/admin/recurring/pending` | 200 | List pending. |
| POST | `/api/admin/recurring/pending/{id}/approve` | 200 | Posts JE via `gl_service`. |
| POST | `/api/admin/recurring/pending/{id}/reject` | 200 | Body: `{reason}`. |

## Finance: Reconciliation finalize  *(Sensitive — `finance.reconciliation.finalize`, critical=True)*

| Method | Path | Status | Notes |
|--------|------|--------|-------|
| POST | `/api/finance/reconciliations/{id}/finalize` | 200 / 409 | 409 returns `DriftReport`. |

## Finance reports  *(Sensitive — `reports.finance.view`, critical=False, audit_view=True)*

Existing endpoints under `/api/reports/finance/**` and `/api/reports/kpi/**` are wrapped by the new decorator; no new routes added. Each successful GET writes a uniform report-view audit row.

## HR PII surfaces  *(Sensitive — `hr.pii`, critical=True)*

Existing endpoints exposing `salary`, `iban`, `national_id` are wrapped by the new decorator. Body responses MUST go through `sanitize_for_audit()` for audit logging; user-facing responses keep masking rules already in place.

## Integration: inbound webhooks  *(Public/per-integration auth, plus rate limit)*

Existing inbound webhook handlers are wrapped by `webhook_rate_limit.check_and_consume()` early in the request. On rejection: HTTP 429 + `Retry-After`.

## Error envelope (uniform)

All non-2xx responses share the existing project error envelope:

```json
{
  "error": {
    "code": "<machine_code>",
    "message": "<i18n key>",
    "details": { ... }
  }
}
```

`details` MUST be sanitized via `sanitize_for_audit` before being returned for any code that originates inside business services, to avoid leaking PII or structural hints.
