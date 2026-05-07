# Phase 1 Data Model: Audit & Security + Finance Integrity Remediation

**Feature**: 022-audit-security-finance-integrity
**Date**: 2026-05-02

> **Documentation rule**: Tables and critical fields only. No DDL. Migrations and `backend/db_ddl/tenant_schema.py` produce the actual schema.

## New tables

### `audit_outbox`

Buffer for audit rows that must commit/rollback with the originating business transaction.

| Field | Type | Notes |
|-------|------|-------|
| `id` | BIGSERIAL PK | |
| `tenant_id` | BIGINT NOT NULL | tenant scope (for global DBs); in tenant DBs the column may be omitted but the writer always asserts context |
| `actor_id` | BIGINT NULL | who performed the action |
| `action` | VARCHAR(64) NOT NULL | enum-like; matches `audit_logs.action` |
| `entity_type` | VARCHAR(64) NULL | |
| `entity_id` | BIGINT NULL | |
| `payload` | JSONB NOT NULL | already sanitized when enqueued |
| `critical` | BOOLEAN NOT NULL DEFAULT false | |
| `enqueued_at` | TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp() | DB-authoritative |
| `flushed_at` | TIMESTAMPTZ NULL | set when worker writes to `audit_logs` |
| `attempt_count` | INT NOT NULL DEFAULT 0 | |
| `last_error` | TEXT NULL | |

Indices: `(tenant_id, enqueued_at) WHERE flushed_at IS NULL`. Retention: rows older than 30 days with `flushed_at IS NOT NULL` are archived/deleted by the existing data-lifecycle scheduler.

State transitions: `pending → flushed` (one-way). Failures stay `pending` and accumulate `attempt_count`; backoff is exponential up to a cap.

### `integration_credentials`

Single vault for all integration secrets.

| Field | Type | Notes |
|-------|------|-------|
| `id` | BIGSERIAL PK | |
| `tenant_id` | BIGINT NOT NULL | |
| `integration` | VARCHAR(32) NOT NULL | enum: `zatca | smtp | sms | payments | shipping | bank | ldap` |
| `name` | VARCHAR(128) NOT NULL | logical name (e.g., `primary-smtp`) |
| `secret_ciphertext` | BYTEA NOT NULL | envelope-encrypted |
| `key_version` | INT NOT NULL | rotation marker |
| `metadata` | JSONB NOT NULL DEFAULT '{}' | non-sensitive config (host, port…) |
| `status` | VARCHAR(16) NOT NULL DEFAULT 'active' | `active | rotating | soft_deleted` |
| `consecutive_failures` | INT NOT NULL DEFAULT 0 | for bank-feed alerting |
| `rotated_at` | TIMESTAMPTZ NULL | |
| `expires_at` | TIMESTAMPTZ NULL | |
| `created_by` | BIGINT NULL | |
| `created_at` | TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp() | |
| `deleted_at` | TIMESTAMPTZ NULL | soft delete |

Validation: unique `(tenant_id, integration, name)` where `status != 'soft_deleted'`. `secret_ciphertext` MUST be set via the vault service; never written directly. State transitions: `active → rotating → active` (rotation cycle), `active → soft_deleted` (terminal until restore).

### `account_classifications`

Replaces hard-coded account-code-range checks.

| Field | Type | Notes |
|-------|------|-------|
| `id` | BIGSERIAL PK | |
| `tenant_id` | BIGINT NOT NULL | |
| `account_id` | BIGINT NOT NULL | FK → `accounts.id` |
| `statement_category` | VARCHAR(32) NOT NULL | `asset | liability | equity | revenue | expense | contra_asset | contra_liability | contra_equity | contra_revenue | contra_expense` |
| `sign` | SMALLINT NOT NULL | `+1` or `-1` for report aggregation |
| `aggregation_hint` | VARCHAR(64) NULL | optional bucket key for KPI rollups |
| `is_active` | BOOLEAN NOT NULL DEFAULT true | |
| `valid_from` | DATE NOT NULL | |
| `valid_to` | DATE NULL | open-ended |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

Validation: at most one `is_active = true` row per `(tenant_id, account_id)`. `sign` must match `statement_category` semantics. Seed migration backfills based on current code-range heuristics.

### `device_fingerprints`

Privacy-safe fingerprint registry for login events.

| Field | Type | Notes |
|-------|------|-------|
| `id` | BIGSERIAL PK | |
| `tenant_id` | BIGINT NOT NULL | |
| `user_id` | BIGINT NOT NULL | |
| `fingerprint_hash` | VARCHAR(64) NOT NULL | SHA-256 hex of stable, non-PII components |
| `first_seen_at` | TIMESTAMPTZ NOT NULL | |
| `last_seen_at` | TIMESTAMPTZ NOT NULL | |
| `trust_level` | VARCHAR(16) NOT NULL DEFAULT 'unknown' | `unknown | trusted | flagged` |

No raw user-agent / no IP in this table. Index on `(tenant_id, user_id, fingerprint_hash)`.

### `login_geo_events`

Coarse geo placeholder for impossible-travel detection seam.

| Field | Type | Notes |
|-------|------|-------|
| `id` | BIGSERIAL PK | |
| `tenant_id` | BIGINT NOT NULL | |
| `user_id` | BIGINT NOT NULL | |
| `occurred_at` | TIMESTAMPTZ NOT NULL | |
| `country_code` | CHAR(2) NULL | provider-agnostic placeholder |
| `region_code` | VARCHAR(8) NULL | |
| `risk_decision` | VARCHAR(16) NOT NULL DEFAULT 'ok' | `ok | review | block` |
| `decision_reason` | VARCHAR(64) NULL | |

### `employee_receipt_settlements`

Wires employee receipts against advances with approval + GL link.

| Field | Type | Notes |
|-------|------|-------|
| `id` | BIGSERIAL PK | |
| `tenant_id` | BIGINT NOT NULL | |
| `employee_id` | BIGINT NOT NULL | |
| `advance_id` | BIGINT NOT NULL | FK → employee_advances |
| `receipt_id` | BIGINT NOT NULL | FK → expense receipts table |
| `amount` | NUMERIC(18,4) NOT NULL | |
| `status` | VARCHAR(16) NOT NULL DEFAULT 'draft' | `draft | submitted | approved | rejected | posted` |
| `approved_by` | BIGINT NULL | |
| `je_id` | BIGINT NULL | FK → journal_entries when posted |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

State transitions: `draft → submitted → approved → posted`; `submitted → rejected → draft`.

## Modified tables

### `audit_logs`

- Add `critical BOOLEAN NOT NULL DEFAULT false` if not present.
- Confirm composite index `(tenant_id, created_at DESC)`; add `(tenant_id, action, created_at DESC)` if not present.
- Document the `details` schema contract; no shape change.

### `recurring_je_templates`

| New field | Type | Notes |
|-----------|------|-------|
| `review_threshold` | NUMERIC(18,4) NULL | NULL ⇒ no review required |
| `auto_approve` | BOOLEAN NOT NULL DEFAULT false | |
| `expense_category_id` | BIGINT NOT NULL | FK → `expense_categories`; backfill from default category, then enforce NOT NULL |

### `journal_entries` and `invoices`

- Add CHECK constraint that `source` ∈ enum values: `sales | purchase | payroll | treasury | manufacturing | manual | recurring | asset | system`.
- Migration normalizes any legacy casing in one pass.
- Add `expense_category_id BIGINT NULL` to `journal_lines` (or keep on `journal_entries`) to carry the recurring-template category through to reporting (depends on existing schema; migration confirms placement and updates `tenant_schema.py`).

### `treasury_accounts`

- New trigger `tg_treasury_balance_authority` on `BEFORE UPDATE OF current_balance`. Raises unless the current session has `current_setting('aman.gl_context', true) = 'on'`.

## Settings keys (in `company_settings`)

These are configuration values, not schema; listed here so downstream tasks reference one source.

| Key | Type | Default | Used by |
|-----|------|---------|---------|
| `audit.outbox.flush_sla_seconds` | int | 60 | outbox worker monitoring |
| `audit.outbox.batch_size` | int | 200 | outbox worker |
| `audit.sanitizer.allow_paths` | list | `[]` | sanitizer |
| `webhook.ratelimit.window_seconds` | int | 60 | webhook rate limit |
| `webhook.ratelimit.max_requests` | int | 120 | webhook rate limit |
| `bank_feed.failure_alert_threshold` | int | 3 | bank-feed alerting |
| `reconciliation.drift_tolerance` | NUMERIC(18,4) | 0.01 | finalize guard |
| `gl.je_epsilon` | NUMERIC(18,4) | 0.005 | gl_service |
| `fiscal.allow_drafts_in_closed_period` | bool | false | period gate |
| `expenses.auto_approve_threshold` | NUMERIC(18,4) | 0 (off) | auto-approve scheduler |
| `expenses.cost_center_policy` | enum | `warn` | `off | warn | required` |
| `recurring.review_threshold_default` | NUMERIC(18,4) | 0 (off) | recurring service |

## Relationships (high level)

- `audit_outbox` → flushes into `audit_logs` (1:1).
- `integration_credentials.consecutive_failures` is updated by integration adapters; alerts route via the existing notification queue.
- `account_classifications.account_id` → `accounts.id` (one active row per account per tenant).
- `recurring_je_templates.expense_category_id` → `expense_categories.id`; the category propagates onto generated JE lines.
- `employee_receipt_settlements.je_id` → `journal_entries.id` (set after posting).
- `device_fingerprints` and `login_geo_events` are owned by the auth/login flow; consumed by future risk rules.

## Validation rules (cross-cutting)

- All new `tenant_id`-scoped tables enforce tenant isolation through `get_db_connection(company_id)`; no cross-tenant joins.
- All money fields are `NUMERIC(18,4)` (FX rates `NUMERIC(18,6)`).
- All timestamp fields default to DB time (`clock_timestamp()`).
- All "active" lookup tables (`integration_credentials`, `account_classifications`) define a deterministic single-active-row rule and validate it on save.
- Soft-deleted rows are excluded from default queries; the audit path always reads the full set.

## State machines summarized

- **Audit outbox row**: `pending → flushed` (worker), `pending` retries on failure.
- **Integration credential**: `active ↔ rotating`, `active → soft_deleted`.
- **Account classification**: implicit via `is_active` + `valid_from/valid_to`.
- **Employee receipt settlement**: `draft → submitted → approved → posted`; `submitted → rejected → draft`.
- **Recurring template run**: per-run, posts directly or routes to `pending_review → approved → posted` (or `rejected`).
