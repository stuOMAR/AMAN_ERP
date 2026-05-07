# Phase 0 Research — Feature 024 (R5 + R6)

This document resolves all open questions for the HR/Payroll/PII + FSM/DMS/Notifications remediation. Each entry follows Decision / Rationale / Alternatives.

---

## R5 — HR / Payroll / PII

### R5.1 PII field encryption strategy

**Decision**: Application-level encryption via 022's `credentials_vault` envelope (KEK in vault, DEK per-tenant). Affected columns (`employees.salary`, `employees.iban`, `employees.national_id`, `employees.passport_number`, `employees.bank_account_number`, `employees.gosi_number`) stored as `BYTEA`. Reads always go through `hr_pii_serializer` which masks by default and only unmasks when the request has `hr.pii` sensitive permission. A toggleable settings flag `hr.salary_encryption_enabled` controls salary encryption (default `true` for new tenants; backfill migration encrypts existing data).

**Rationale**: pgcrypto column encryption requires the key in the DB session and exposes plaintext to anyone with `SELECT`; 022 already owns a vetted vault. Application-level matches AMAN's other secret-bearing flows.

**Alternatives considered**:
- pgcrypto symmetric column encryption — rejected (key in session, broader exposure surface).
- Transparent disk encryption only — rejected (does not protect against logical access).
- Vaulted-side decryption proxy — rejected (latency + operational complexity not justified for read-heavy salary fields).

### R5.2 Payroll period overlap mechanism

**Decision**: Single PostgreSQL `EXCLUDE USING gist` constraint on `payroll_periods` over `(tenant_id WITH =, tstzrange(start_date, end_date, '[]') WITH &&)` filtered to non-reversed states. `btree_gist` extension required (already used by fiscal-period checks).

**Rationale**: Database-level enforcement is the only way to reliably block overlap under concurrent inserts. Filtered to active states so a reversed period can be replaced.

**Alternatives considered**:
- Application-level check — rejected (race conditions).
- Partial unique constraint per `(tenant_id, start_date)` — rejected (does not detect overlapping but non-equal ranges).

### R5.3 Payroll → bank movement linkage contract

**Decision**: `services/payroll/bank_movements.py::record_payroll_bank_movements(period_id, run_id)` inserts one `bank_transactions` row per payslip with `source='payroll_run'`, `source_id=run_id`, `external_ref=<wps_file_id>:<payslip_id>`, in the same `transactional()` as WPS file commit. Idempotent on `(source, source_id, employee_id)` partial unique.

**Rationale**: The audit reference cited the gap between "payslip exists" and "bank ledger sees the movement". Inserting at WPS commit time keeps reconciliation deterministic.

**Alternatives considered**:
- Per-payslip insert at payslip create — rejected (payslips can be calculated without WPS commit).
- Trigger-driven — rejected (harder to reason about with reversal flow).

### R5.4 Payroll period reversal idempotency

**Decision**: `reverse_payroll_period(period_id, reason)` is a single canonical service. It (1) sets `payroll_periods.state='reversed'`, (2) calls `gl_service.reverse(source='payroll', source_id=period_id)` which posts the inverse JE under `JESource.PAYROLL_REVERSE`, (3) inserts compensating `bank_transactions` rows referencing the original `wps_file_id`, (4) sets `payroll_runs.wps_superseded_by_run_id` on the affected run, (5) emits `payroll.reversed` audit event. Idempotent: re-call returns the existing reversal record. Reverses only `state='locked'` periods. Re-running payroll produces a new run with a new `run_id` rather than modifying the reversed one.

**Rationale**: Mirrors invoice cancellation pattern from 023 — reversal is a first-class workflow, not free-text edits.

**Alternatives considered**:
- Allow direct edits with audit trail — rejected (breaks GL trial balance; violates Principle XI).
- Soft-revert via boolean flag — rejected (loses GL inverse).

### R5.5 Bulk salary increment atomicity

**Decision**: `POST /api/hr/employees/bulk-salary-increment` accepts `{rows: [{employee_id, new_salary, effective_from}], allow_backdated, dry_run}`. Per-row outcome (`updated|skipped|error`). Each successful row writes a versioned salary history record. Default policy: `allow_backdated=false` blocks `effective_from` earlier than the last locked payroll period for that employee. `dry_run` returns outcomes without persisting. Whole request runs in a single `transactional()` only when `atomic=true` flag is set; default behavior is per-row commits to support large batches with partial success.

**Rationale**: Mirrors 023's bulk-by-row pattern; partial success is the norm for HR mass updates.

**Alternatives considered**:
- All-or-nothing — rejected (one bad row blocks 5k good rows).
- No backdated guard — rejected (would silently rewrite locked periods).

### R5.6 Service-years computation policy

**Decision**: New setting `hr.service_years_policy` with values `months_precise` (default) or `days_365_25`. `months_precise` = `(today.year - hire.year)*12 + (today.month - hire.month)` adjusted by day-of-month, divided by 12 with `ROUND_HALF_UP` to 4 dp. `days_365_25` = `(today - hire).days / Decimal('365.25')`. Single `compute_service_years(employee_id, as_of)` helper.

**Rationale**: Both policies are observed in regional HR practice; default to the one matching ZATCA/GOSI illustrations.

**Alternatives considered**:
- 360-day banking convention — rejected (uncommon for HR).

### R5.7 Ticket allowance modeling

**Decision**: `employees.ticket_allowance_amount NUMERIC(18,4)` + `ticket_allowance_currency CHAR(3)` + `ticket_allowance_frequency_months SMALLINT` (default 12) + `ticket_allowance_last_paid_at DATE`. Scheduler accrues monthly via `gl_service` posting under `JESource.TICKET_ALLOWANCE` to the configured account from `acc_map_payroll`. Pay-out marks `last_paid_at` and reverses the accrual.

**Rationale**: Allowance is a recurring liability accrued monthly, paid out at frequency boundary — matches GAAP and matches existing leave-accrual pattern.

**Alternatives considered**:
- Lump-sum at pay-out only — rejected (distorts monthly P&L).

### R5.8 Timezone-aware payroll/HR schedulers

**Decision**: `company_settings.company_timezone` (IANA, default `Asia/Riyadh`). All HR/payroll schedulers compute trigger times via `zoneinfo.ZoneInfo(company_timezone)`. Scheduler stores `scheduled_at_utc` for ordering but evaluates day boundaries in the company TZ.

**Rationale**: Multi-tenant ERP cannot assume server-local TZ; explicit IANA name is auditable.

**Alternatives considered**:
- UTC-only — rejected (misses month-end boundary in regional tenants).

### R5.9 Bank codes registry

**Decision**: `bank_codes(tenant_id, code, name_en, name_ar, swift_bic, wps_routing_code, active)` with global seed loaded at tenant bootstrap from `backend/db_ddl/seed_bank_codes.json`. WPS file builder calls `bank_codes.lookup(swift_bic)` instead of inline dict.

**Rationale**: Removes hardcoded WPS code maps; enables per-tenant overrides without code change.

### R5.10 Loans/advances mapping split

**Decision**: New tables `acc_map_loans(tenant_id, debit_account_id, credit_account_id, valid_from, valid_to)` and `acc_map_advances(tenant_id, debit_account_id, credit_account_id, valid_from, valid_to)`. Compatibility view `acc_map_loans_adv` UNIONs both for one release. Resolver in 023's `account_mapping` extended to read both. Migration backfills using existing rows' purpose flag (or, if absent, copies into both and marks for manual review).

**Rationale**: Loans and advances post to different accounts in regional CoA; combined mapping forced ambiguity.

---

## R6 — FSM / DMS / Notifications

### R6.1 Service pricelist resolver

**Decision**: `service_pricelists(id, tenant_id, scope, scope_ref_id, item_id, currency, unit_price, valid_from, valid_to)` where `scope` ∈ `{tenant, customer, contract}`. Resolver `resolve_price(item_id, customer_id, contract_id, as_of)` returns the price with the most-specific active scope: `contract` > `customer` > `tenant` > item default. Returns `(price, level)` so `service_orders.pricelist_source_level` records the level at order creation.

**Rationale**: Most specific wins is the intuition customers expect; recording the level enables audit.

**Alternatives considered**:
- Single global pricelist per tenant — rejected (rejected by spec FR-153).
- Lookup at invoicing time — rejected (price drift from order time).

### R6.2 Contract coverage rules format

**Decision**: `service_contracts.coverage_rules JSONB` with shape `{labour: {covered: bool, cap_amount?: Decimal, cap_hours?: Decimal}, parts: {covered: bool, cap_amount?: Decimal, exclusions?: [item_id]}, travel: {covered: bool, cap_per_visit?: Decimal}}`. `coverage_resolver(contract_id, line)` returns `{covered: bool, billable_amount: Decimal, reason}`. Validated against a Pydantic schema at write.

**Rationale**: JSONB with a strict Pydantic shape gives flexibility without freeform.

### R6.3 Technician matcher scoring

**Decision**: `technician_assignment_matcher(service_order)` returns ranked list. Score = `0.5*skills_match + 0.2*zone_match + 0.2*availability + 0.1*workload_inverse`. Auto-assigns when top score ≥ `fsm.auto_assign_threshold` (default `0.75`); else returns ranked list for dispatcher UI.

**Rationale**: Weighted multi-factor matches industry FSM matchers; threshold is per-tenant.

### R6.4 Preventive maintenance dedupe key

**Decision**: Dedupe on `(tenant_id, asset_id, plan_id, due_window_start)` where `due_window_start` is the floored start of the recurrence period. Re-runs of the scheduler in the same window are no-ops.

**Rationale**: Idempotent scheduling under at-least-once cron.

### R6.5 Maintenance silo unification

**Decision**: All silos (asset module, service module, shopfloor maintenance) call `unified_maintenance_writer.create_work_order(...)`. Legacy tables retained as views over the unified table for backward compatibility for one release. Lint enforces no direct INSERT into legacy maintenance tables.

**Rationale**: Single writer eliminates GL/inventory drift between silos.

### R6.6 DMS streaming MIME validator

**Decision**: `python-magic` (libmagic) wrapped by `streaming_mime.validate(stream, declared_mime, max_chunk=64KB)` which inspects the first chunk, computes magic + extension reconciliation, and reject-streams (returns 415) before persisting. Whitelist per category (image/*, application/pdf, application/zip-derived office, text/*, csv) configurable via `dms.allowed_mime_groups`.

**Rationale**: Streaming inspection avoids persisting hostile uploads.

**Alternatives considered**:
- File extension only — rejected (trivially spoofed).
- Post-write scan only — rejected (file already on disk).

### R6.7 Anti-malware deployment

**Decision**: ClamAV as default, accessed via `clamd` Python client over Unix socket or TCP. Configurable via `dms.scan_engine` (`clamav` default, `none` for dev, plug for future engines). On upload: file enters `state='pending_scan'`, scan worker consumes pending rows and transitions to `clean` or `quarantined`. Quarantined files moved to `dms.quarantine_root`. Documents in `pending_scan` are not downloadable except by `dms.audit_admin`. Stale-pending alarm at `dms.scan_max_pending_minutes` (default 30).

**Rationale**: ClamAV is the de facto OSS engine; pluggable engine spec keeps door open.

### R6.8 DMS quotas accounting

**Decision**: Tenant quota: `dms.tenant_quota_mb` (settings) checked against `SUM(documents.size) WHERE tenant_id=?` cached in Redis with 60s TTL and invalidated on upload/delete. Per-user quota: `dms.user_quota_mb` enforced similarly. Quota check returns HTTP 413 before persist (after streaming MIME check). `storage_quotas` table tracks per-tenant usage snapshots for reporting.

**Rationale**: Cached SUM avoids per-upload table scan; settings-driven thresholds satisfy Principle V.

### R6.9 Notifications queue worker concurrency

**Decision**: Per-channel worker (`email`, `sms`, `push`, `in_app`, `webhook`) polls `SELECT ... FROM notifications_queue WHERE channel=? AND state='pending' AND next_attempt_at<=now() ORDER BY next_attempt_at FOR UPDATE SKIP LOCKED LIMIT 100`. Visibility timeout via `state='sending'` + `claimed_at`. Max attempts default 5 with exponential backoff `2^attempts * 30s` capped at 1 hour, with ±20% jitter. After max attempts, `state='dead_letter'` + `dlq_at=now()` + DLQ alarm via webhook dispatcher.

**Rationale**: `FOR UPDATE SKIP LOCKED` is the canonical pattern for parallel queue workers in Postgres.

### R6.10 Idempotency key default formula

**Decision**: When caller does not provide `idempotency_key`, default = `sha256(f"{tenant_id}|{event_type}|{recipient}|{channel}|{template_code}|{payload_hash}")` truncated to 32 hex chars. Dedupe window: `notifications.dedupe_window_seconds` (default 300). Within the window, identical key returns the existing queue row id.

**Rationale**: Hash-based default protects against accidental floods (e.g., retried webhooks).

### R6.11 Email templates i18n + interpolation

**Decision**: `email_templates(tenant_id, code, locale, subject, body_html, body_text, version, active)` with unique `(tenant_id, code, locale)`. Locales `en`, `ar` required for transactional codes (validation gate). Interpolation via Jinja2 in sandboxed mode (no filesystem, no inheritance, only safe filters). Resolver picks recipient's locale → tenant default → `en`.

**Rationale**: Sandboxed Jinja2 is widely vetted for templating; locked-down env eliminates injection risk.

### R6.12 Signed approval token format

**Decision**: HMAC-SHA256 token: `base64url(json({tenant_id, action, target_id, issued_at, expires_at, nonce, issuer_user_id})) || "." || hmac_sha256(key, payload)`. Key from 022's vault (`approval_token_signing_key`, rotatable). Single-use enforced by `approval_tokens(nonce PK, tenant_id, action, target_id, expires_at, consumed_at)` with partial unique on `(nonce) WHERE consumed_at IS NULL`. Replay returns HTTP 409. Expired token returns HTTP 410. Default TTL `auth.approval_token_ttl_minutes` = 1440 (24h).

**Rationale**: HMAC + nonce table is the standard signed-stateless+single-use combo.

**Alternatives considered**:
- JWT — rejected (overweight, larger surface).
- Pure stateless HMAC without nonce table — rejected (cannot enforce single-use).

---

## Summary

All NEEDS CLARIFICATION items resolved. No outstanding open questions blocking Phase 1.
