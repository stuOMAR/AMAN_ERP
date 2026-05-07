# Data Model — Feature 024 (R5 + R6)

> Per AMAN ERP rule: this document lists table names, critical fields, relationships, validation rules, and state transitions only. **No full DDL.** Actual DDL is produced by Alembic migrations and the canonical `tenant_schema.py` / `database.py` updates during implementation.

All tables carry `tenant_id`, `created_at`, `updated_at`, `created_by_user_id`, `updated_by_user_id`, plus AuditMixin/SoftDeleteMixin where applicable per Principle XVII.

---

## R5 — HR / Payroll / PII

### `employees` (extension)

Critical fields added/changed:
- `salary` → `BYTEA` (encrypted; was NUMERIC).
- `iban`, `national_id`, `passport_number`, `bank_account_number`, `gosi_number` → `BYTEA` (encrypted).
- `salary_currency CHAR(3)`.
- `ticket_allowance_amount NUMERIC(18,4)`, `ticket_allowance_currency CHAR(3)`, `ticket_allowance_frequency_months SMALLINT DEFAULT 12`, `ticket_allowance_last_paid_at DATE`.
- `bank_code_id` → FK `bank_codes.id`.
- `technician_profile_id` → FK `technicians.id` (nullable; only employees who are technicians).

Validation:
- Encrypted columns never returned in API; `hr_pii_serializer` masks unless `hr.pii` permission present.
- Salary edits write a row in `employee_salary_history`.

### `employee_salary_history` (new)

Fields: `id`, `tenant_id`, `employee_id`, `salary` (BYTEA encrypted), `salary_currency`, `effective_from DATE`, `effective_to DATE NULL`, `change_reason VARCHAR(64)`, `created_by_user_id`.

Validation: non-overlapping (`employee_id`, `effective_from`–`effective_to`); `effective_from` cannot fall within a locked payroll period unless `allow_backdated=true`.

### `payroll_periods` (extension)

Critical fields:
- `state ENUM('draft','calculated','locked','reversed')` with state machine below.
- Existing `start_date DATE`, `end_date DATE`.

Validation:
- `EXCLUDE USING gist (tenant_id WITH =, tstzrange(start_date, end_date, '[]') WITH &&) WHERE (state <> 'reversed')`.
- Requires `btree_gist` extension.

State transitions:
```
draft → calculated → locked → reversed
       (period_writer)   (reverse_payroll_period)
```
Only canonical writers may transition.

### `payroll_runs` (extension)

Critical fields:
- `wps_superseded_by_run_id` → FK `payroll_runs.id` (nullable; set when this run was reversed and a successor exists).
- Existing `period_id`, `wps_file_id`.

### `payslips` (extension)

Critical fields: existing `(employee_id, period_id, run_id, gross, net, ...)` columns.

Validation:
- New unique constraint `(tenant_id, employee_id, period_id) WHERE deleted_at IS NULL`.
- Backfill migration deduplicates pre-existing duplicates by keeping the row tied to the latest `run_id`.

### `payroll_entries` (alignment)

ORM↔DDL alignment: ensure `period_id` exists in both with FK to `payroll_periods.id`. No new columns.

### `bank_transactions` (extension)

New rows produced by `payroll/bank_movements.py`:
- `source='payroll_run'`, `source_id=run_id`, `external_ref='<wps_file_id>:<payslip_id>'`, `direction='debit'`, `amount=payslip.net_pay`, `currency`, `bank_account_id`, `posted_at`.

Validation: partial unique `(tenant_id, source, source_id, external_ref) WHERE source='payroll_run'`.

### `bank_codes` (new)

Fields: `id`, `tenant_id`, `code` (e.g. `RJHISARI`), `name_en`, `name_ar`, `swift_bic`, `wps_routing_code`, `active BOOLEAN`.

Validation: unique `(tenant_id, code)`; unique `(tenant_id, swift_bic) WHERE swift_bic IS NOT NULL`. Seeded at tenant bootstrap.

### `acc_map_loans` (new — split from `acc_map_loans_adv`)

Fields: `id`, `tenant_id`, `debit_account_id`, `credit_account_id`, `valid_from`, `valid_to`.

Validation: non-overlapping per tenant; resolver in `account_mapping` reads this for loan postings.

### `acc_map_advances` (new — split from `acc_map_loans_adv`)

Fields: same as above; for advance postings.

Compatibility view `acc_map_loans_adv` UNIONs both for one release.

### `acc_map_payroll` (extension if needed)

Add `ticket_allowance_account_id` if not already present.

---

## R6 — FSM / DMS / Notifications

### `service_pricelists` (new)

Fields: `id`, `tenant_id`, `scope ENUM('tenant','customer','contract')`, `scope_ref_id BIGINT NULL` (NULL when scope=tenant; FK customer or contract otherwise), `item_id BIGINT`, `currency CHAR(3)`, `unit_price NUMERIC(18,4)`, `valid_from DATE`, `valid_to DATE NULL`, `active BOOLEAN`.

Validation:
- Unique `(tenant_id, scope, scope_ref_id, item_id, valid_from)`.
- `scope='tenant'` ⇒ `scope_ref_id IS NULL`; otherwise NOT NULL.
- Resolver enforces specificity precedence contract > customer > tenant.

### `service_contracts` (extension)

Critical fields added:
- `coverage_rules JSONB` (Pydantic-validated shape per research §R6.2).
- `pricing_strategy ENUM('pricelist','fixed_per_visit','fixed_total','time_and_material')`.
- `maintenance_schedule JSONB` (cron-like recurrence: `{cadence: 'monthly'|'quarterly'|'biannual'|'annual'|'custom_days', day_of_period: int, lead_days: int}`).
- `renew_policy ENUM('manual','auto_with_invoice','auto_no_invoice')`.
- `auto_renewed_to_id BIGINT NULL` → FK self.

Validation:
- `coverage_rules` schema-checked at write.
- `renew_policy='auto_with_invoice'` requires `customer_id` and a valid `account_mapping` for service revenue.

### `service_orders` (extension)

Critical fields added:
- `kind ENUM('break_fix','preventive','installation','rental','contract')`.
- `assigned_technician_id BIGINT NULL` → FK `technicians.id`.
- `pricelist_source_level ENUM('contract','customer','tenant','default')`.
- `revenue_total NUMERIC(18,4)`, `cost_total NUMERIC(18,4)`, `margin_amount NUMERIC(18,4)`, `margin_pct NUMERIC(7,4)`, `revenue_resolved_at TIMESTAMPTZ`.
- `contract_id BIGINT NULL` → FK `service_contracts.id`.

Validation:
- `kind='contract'` ⇒ `contract_id NOT NULL`.
- Close transition gated by `zero_revenue_gate` (see contract).

State transitions: existing FSM service-order state machine retained; gate hooks added at transition to `closed`.

### `technicians` (new)

Fields: `id`, `tenant_id`, `employee_id BIGINT NULL` (FK `employees.id`; null for external/freelance), `external_name VARCHAR(255) NULL`, `skills JSONB` (array of skill codes), `zones JSONB` (array of zone codes), `certifications JSONB` (array of `{code, valid_from, valid_to, issuer}`), `availability JSONB` (weekly windows + exceptions), `active BOOLEAN`.

Validation: exactly one of `employee_id` / `external_name` set.

### `maintenance_plans` (new — unified)

Fields: `id`, `tenant_id`, `asset_id BIGINT NULL` → FK `assets.id`, `equipment_id BIGINT NULL` → FK `equipment.id`, `contract_id BIGINT NULL` → FK `service_contracts.id`, `cadence JSONB` (same shape as `service_contracts.maintenance_schedule`), `template_service_order_id BIGINT NULL`, `next_due_at TIMESTAMPTZ`, `last_generated_at TIMESTAMPTZ NULL`, `active BOOLEAN`.

Validation: at least one of (`asset_id`, `equipment_id`, `contract_id`) NOT NULL.

### Unified maintenance work orders

`service_orders` (with `kind='preventive'`) is the single canonical work-order table. Legacy `asset_maintenance_orders` / `shopfloor_maintenance_orders` retained as views over `service_orders` filtered by source tag for one release.

### `dms_attachment_links` (new)

Fields: `id`, `tenant_id`, `document_id BIGINT` → FK `documents.id`, `entity_type VARCHAR(64)`, `entity_id BIGINT`, `link_role VARCHAR(64) NULL` (e.g. `'invoice_attachment'`, `'employee_contract'`, `'service_order_evidence'`), `created_by_user_id`.

Validation:
- Unique `(tenant_id, document_id, entity_type, entity_id, link_role)`.
- Indexes `(entity_type, entity_id)` and `(document_id)`.
- Replaces freeform `documents.related_module` / `related_id` (those columns deprecated).

### `documents` (extension)

Critical fields added:
- `state ENUM('pending_scan','clean','quarantined','deleted')`.
- `quarantine_path VARCHAR(1024) NULL`.
- `scanned_at TIMESTAMPTZ NULL`.
- `scan_engine VARCHAR(64) NULL`, `scan_engine_version VARCHAR(64) NULL`.
- `checksum_sha256 CHAR(64)`.
- `size BIGINT` (already typically present; ensured).

State transitions:
```
pending_scan → clean        (scan worker, clean signal)
pending_scan → quarantined  (scan worker, infected signal)
clean → deleted             (soft delete)
```

Validation: `state='pending_scan'` rows are not downloadable except by `dms.audit_admin`.

### `storage_quotas` (new)

Fields: `id`, `tenant_id`, `scope ENUM('tenant','user')`, `scope_ref_id BIGINT NULL`, `used_bytes BIGINT`, `quota_bytes BIGINT`, `last_recalculated_at TIMESTAMPTZ`.

Validation: unique `(tenant_id, scope, scope_ref_id)`. Snapshot table; live enforcement is via cached SUM (per research §R6.8).

### `notifications_queue` (new)

Fields: `id`, `tenant_id`, `idempotency_key CHAR(32)`, `event_type VARCHAR(64)`, `channel ENUM('email','sms','push','in_app','webhook')`, `recipient VARCHAR(512)` (email / msisdn / device_token / user_id / webhook url), `template_code VARCHAR(64) NULL`, `locale CHAR(5) NULL`, `payload JSONB`, `state ENUM('pending','sending','sent','failed','dead_letter')`, `attempts SMALLINT DEFAULT 0`, `next_attempt_at TIMESTAMPTZ`, `last_error TEXT NULL`, `claimed_at TIMESTAMPTZ NULL`, `sent_at TIMESTAMPTZ NULL`, `dlq_at TIMESTAMPTZ NULL`.

Validation:
- Unique `(tenant_id, idempotency_key) WHERE state IN ('pending','sending')` — prevents in-flight duplicates within dedupe window.
- Indexes: `(channel, state, next_attempt_at)` for the worker; `(state, dlq_at)` for DLQ admin.

State transitions:
```
pending → sending → sent
pending → sending → failed (transient) → pending (with backoff)
                  → failed (terminal, attempts ≥ max) → dead_letter
```

### `email_templates` (extension / formalization)

Fields: `id`, `tenant_id`, `code VARCHAR(64)`, `locale CHAR(5)`, `subject VARCHAR(512)`, `body_html TEXT`, `body_text TEXT`, `version INT`, `active BOOLEAN`.

Validation:
- Unique `(tenant_id, code, locale)`.
- For each transactional `code`, both `en` and `ar` must exist before `active=true` (CI lint).

### `approval_tokens` (new)

Fields: `nonce CHAR(32) PRIMARY KEY`, `tenant_id`, `action VARCHAR(64)`, `target_id BIGINT`, `issuer_user_id BIGINT`, `issued_at TIMESTAMPTZ`, `expires_at TIMESTAMPTZ`, `consumed_at TIMESTAMPTZ NULL`, `consumed_by_user_id BIGINT NULL`, `consumed_via_ip INET NULL`.

Validation:
- Partial unique `(nonce) WHERE consumed_at IS NULL` ensures single-use.
- Expired tokens (`now() > expires_at`) rejected.

State transitions:
```
issued → consumed
issued → expired (passive; sweeper removes after retention)
```

---

## Settings Keys (added in `company_settings`)

| Key | Default | Notes |
|-----|---------|-------|
| `hr.salary_encryption_enabled` | `true` | Toggle salary BYTEA encryption (new tenants always true). |
| `hr.service_years_policy` | `months_precise` | `months_precise` \| `days_365_25`. |
| `company_timezone` | `Asia/Riyadh` | IANA TZ for HR/payroll schedulers. |
| `payroll.allow_backdated_increment` | `false` | Allow salary effective_from before last locked period. |
| `fsm.auto_assign_threshold` | `0.75` | Matcher score threshold for auto-assign. |
| `fsm.zero_revenue_approval_required` | `true` | Block close when revenue=0 and cost>0 unless approved. |
| `dms.tenant_quota_mb` | `51200` | 50 GB default. |
| `dms.user_quota_mb` | `2048` | 2 GB default. |
| `dms.orphan_retention_days` | `30` | Delete unreferenced docs after N days. |
| `dms.storage_root` | `/var/aman/dms` | Centralized root; per-tenant subpath. |
| `dms.scan_max_pending_minutes` | `30` | Alarm when docs sit in `pending_scan`. |
| `dms.scan_engine` | `clamav` | `clamav` \| `none`. |
| `dms.allowed_mime_groups` | (whitelist) | image/*, application/pdf, … |
| `notifications.max_attempts` | `5` | Worker retry cap. |
| `notifications.dedupe_window_seconds` | `300` | Idempotency window. |
| `notifications.default_locale` | `en` | Fallback for templates. |
| `auth.approval_token_ttl_minutes` | `1440` | Default token TTL. |

---

## JESource enum extensions

New values to be added to the central `JESource` enum (additive, does not break 023):
- `PAYROLL`
- `PAYROLL_REVERSE`
- `TICKET_ALLOWANCE`
- `SERVICE_INVOICE` (if not already from 023)
- `SERVICE_INVOICE_REVERSE`

---

## Indices Summary

| Table | Index | Purpose |
|-------|-------|---------|
| `payroll_periods` | `EXCLUDE USING gist` (per above) | overlap prevention |
| `payslips` | unique `(tenant_id, employee_id, period_id) WHERE deleted_at IS NULL` | de-dupe |
| `bank_transactions` | partial unique `(tenant_id, source, source_id, external_ref) WHERE source='payroll_run'` | idempotent payroll bank movements |
| `service_pricelists` | `(tenant_id, scope, scope_ref_id, item_id, valid_from)` unique | resolver |
| `dms_attachment_links` | `(entity_type, entity_id)`, `(document_id)` | reverse lookup |
| `documents` | `(tenant_id, state)` partial on `pending_scan` | scan worker |
| `notifications_queue` | `(channel, state, next_attempt_at)`, `(state, dlq_at)` | worker + DLQ |
| `notifications_queue` | unique `(tenant_id, idempotency_key) WHERE state IN ('pending','sending')` | dedupe |
| `approval_tokens` | partial unique `(nonce) WHERE consumed_at IS NULL` | single-use |
| `email_templates` | unique `(tenant_id, code, locale)` | resolver |
| `bank_codes` | unique `(tenant_id, code)`, `(tenant_id, swift_bic) WHERE swift_bic IS NOT NULL` | lookup |
