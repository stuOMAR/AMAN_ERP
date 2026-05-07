# Feature Specification: Audit & Security + Finance Integrity Remediation (R1 + R2)

**Feature Branch**: `022-audit-security-finance-integrity`
**Created**: 2026-05-02
**Status**: Draft
**Input**: User description: "do R1 — Audit & Security and R2 — Finance Integrity on one speckit; the coder will write so spec everything"

## Scope & Functional Flows *(mandatory)*

### Problem / Goal

Two adjacent risk classes in AMAN ERP are still partially mitigated and pose the highest residual risk after batch B41:

1. **R1 — Audit & Security**: Audit logging can corrupt outer transactions, audit payloads may leak PII, sensitive HR/finance/report endpoints lack uniform `require_sensitive_permission` coverage, integration secrets are scattered across stores, and webhook/credential lifecycle controls are missing.
2. **R2 — Finance Integrity**: Reconciliation finalize, period gating, JE reversal contracts, account-classification logic and treasury balance authority are inconsistent — creating risk of silent ledger drift, hard-coded account-code ranges, and out-of-policy postings.

This feature delivers the consolidated remediation for both risk classes as one coordinated change set so that the audit chain, permission gates, JE/treasury contracts and account-classification model become the single source of truth that downstream features (sales, payroll, reports) can rely on.

The outcome must:

- Guarantee that audit log writes never break the calling business transaction and never silently drop.
- Guarantee that no audit payload, error response or log line contains raw PII (salary, IBAN, national ID, password, secret material, full credentials).
- Guarantee that every endpoint reading or mutating sensitive HR / finance / settings / reports data is gated by `require_sensitive_permission` with consistent semantics.
- Guarantee that every integration secret (ZATCA, SMTP, SMS, payments, shipping, bank feeds, LDAP) lives in one encrypted store with rotation, audit, soft-delete and lifecycle alerts.
- Guarantee that finance posting, reconciliation finalize, fiscal-period gating and treasury balance updates can only happen through the official GL pathway, with explicit, configurable account classification replacing hard-coded code-range heuristics.

### In Scope

**R1 — Audit & Security**

- Atomic, schema-stable audit logging that survives nested rollbacks and uses an outbox/async-safe writer (#132, #133, #134, #136).
- Centralized PII sanitizer applied to audit `details`, request body capture, error responses and import error messages (#272a, #352).
- Sensitive-permission sweep covering HR, payroll, finance, reconciliation, reports, treasury and settings endpoints — including the `critical=True` tag set (#351, #408, #487).
- Encrypted secret vault unification for ZATCA, SMTP, SMS, payments, shipping, bank feeds and LDAP credentials, with rotation, soft-delete, audit, and per-tenant inbound-webhook rate limiting (#162, #225, #226, #227, #228, #413).
- Safe body capture for audit and structured logging that runs after sanitization (#352).
- Optional/foundational hook for impossible-travel and device-fingerprint tracking — a single privacy-safe data model and integration point, with the actual provider/heuristics deferred (#135, #275). The activation policy itself is in scope; remote IP-geo provider selection is out.
- Ghost-employee detection rule executed against payroll snapshots (#353).

**R2 — Finance Integrity**

- Reconciliation `finalize` MUST validate GL balance against the linked treasury / bank / account balance and refuse on drift (#272u, #419x).
- Configurable, table-driven **Account Classification** model that replaces hard-coded account-code ranges in reports, KPI dashboards, and balance-sheet sign logic (#219, #269, #463).
- Tightened JE balance tolerance with a single configurable epsilon and explicit policy (#271).
- Unified casing and value set for invoice/JE `source` fields (#272).
- Fiscal-period draft policy: define and enforce whether drafts are allowed in closed periods (#273).
- Asset-return write-down JE generation aligned with depreciation policy (#419q).
- Multi-currency revaluation rounding policy with documented precision bounds (#419p).
- Treasury balance authority: DB-level guard ensuring `treasury_accounts.current_balance` is only updated through the sanctioned GL/treasury service path (T1.3b).
- Recurring-template safety: optional human-review workflow above a configurable amount, plus mandatory link from each recurring template to a unified expense category for reporting (#195, #196).
- Employee-receipt-vs-advance reconciliation model wired to approvals and GL (#197).
- Auto-approve-below-threshold scheduler/hook for expense approvals (#310).
- Configurable `cost_center_id` enforcement policy (per-company toggle and override) (#311).
- Uniform audit policy for who-viewed financial reports (#322, #465).

### Out of Scope

- New rule-engine for compound expense-approval policies (#312) — keep simple threshold + cost-center policy here, defer engine.
- Treasury / JE / cash-movement contract reshape (#177) — only the treasury balance trigger ships here; full re-modelling is deferred.
- Settings JSONB typed-model migration (#178) and tax-group junction migration (#179) — explicitly deferred to their own architectural tracks; this feature only ensures the new account-classification table does not block them.
- Replacing the IP-geolocation provider itself (#135) — this feature ships only the data model and integration seam.
- Sales/POS/ZATCA, inventory/manufacturing, HR/payroll, FSM/DMS/notifications, reports/search/dashboard and frontend tracks (R3–R8). They consume the contracts shipped here but are out of this feature's scope.

### Functional Flow Summary

- **Flow-001 (Audit-Atomic-Write)**: A business operation runs inside `transactional()`. The operation calls `log_activity(...)`. The audit write is buffered to an audit outbox in the same DB transaction. If the outer transaction commits, an async worker flushes the outbox to `audit_logs`. If the outer transaction rolls back, the buffered audit row rolls back with it. No `commit` is issued from inside `log_activity`.
- **Flow-002 (PII-Safe Audit & Errors)**: Every write into `audit_logs.details`, every request-body capture for audited endpoints, and every error message returned from import/validation flows passes through a single `sanitize_for_audit()` helper that strips/masks salary, IBAN, national ID, password, secret material, full tokens, and SQL/structural hints.
- **Flow-003 (Sensitive-Permission Gate)**: A request hits a sensitive endpoint (HR PII, finance posting, reconciliation, reports, settings, integration credentials). Middleware/decorator `require_sensitive_permission(scope, critical=...)` enforces RBAC + step-up policy + audit tagging. Endpoints without the gate are rejected at startup discovery.
- **Flow-004 (Secret Vault Lifecycle)**: An admin registers/rotates/soft-deletes an integration credential (ZATCA/SMTP/SMS/payments/shipping/bank/LDAP). The credential is stored encrypted in a single vault table with rotation metadata; every read/write is audited; soft-delete keeps history; expiry/rotation due-date triggers an alert; LDAP password POSTs require HTTPS in production policy.
- **Flow-005 (Webhook Rate-Limit & Failure Alert)**: An inbound webhook arrives. The system applies a per-tenant rate limit; on exceeding threshold, it returns 429 + audit. If a bank feed (or other inbound integration) fails N consecutive times, an alert is raised via the notification queue.
- **Flow-006 (Reconciliation Finalize Guard)**: An accountant clicks "Finalize" on a reconciliation. The service computes the GL balance for the linked account/treasury at the cut-off date and compares it against the reconciled bank/treasury balance. If the absolute difference exceeds the configured tolerance, finalize is rejected with a structured drift report; otherwise it commits and stamps `finalized_at`.
- **Flow-007 (Account Classification Lookup)**: A report (Balance Sheet, P&L, Trial Balance, KPI) requests sign / category / aggregation for an account. It calls `account_classifier.classify(account_id)` which reads from `account_classifications` (configurable per company) instead of hard-coded code-range checks.
- **Flow-008 (Treasury Balance Authority)**: Any direct UPDATE/INSERT/DELETE on `treasury_accounts.current_balance` outside the official GL/treasury session context is blocked by a DB trigger that raises a domain error and writes an audit row.
- **Flow-009 (Recurring Template Safety)**: When a recurring JE template runs, if its amount exceeds the configured human-review threshold, the entry is created in `pending_review` state and routed to an approver before posting. Every recurring template is linked to an expense category, and that category is propagated into the generated JE for reporting.
- **Flow-010 (JE Source Casing & Period Gate)**: When any service creates a JE, `source` is normalized to a single casing/enum, and the posting date is validated against fiscal-period status using the configured draft policy (drafts may or may not be allowed in closed periods, but the rule is uniform across modules).

### Acceptance Criteria

1. **Given** an outer business transaction running inside `transactional()`, **When** `log_activity()` is called and the outer transaction is later rolled back, **Then** no row is left in `audit_logs` for that activity, no premature `COMMIT` was issued, and no exception was masked.
2. **Given** an outer business transaction that commits successfully, **When** `log_activity()` was called inside it, **Then** within a bounded SLA (configurable, default ≤ 60 seconds) the corresponding `audit_logs` row exists and has the same `details` schema as direct callsites use today.
3. **Given** an audited request whose body contains `salary`, `iban`, `national_id`, `password`, or a secret token, **When** the request is logged, **Then** every such field is masked or removed before persistence; an automated test scans the last 1000 audit rows in a seeded environment and finds zero raw matches for the configured PII patterns.
4. **Given** any HR/finance/reconciliation/reports/settings endpoint that reads or mutates sensitive data, **When** the application starts, **Then** an automated audit lists every such endpoint and confirms each one is wrapped by `require_sensitive_permission`; missing wraps fail CI.
5. **Given** an integration credential is registered, rotated, or soft-deleted, **When** the action completes, **Then** the change is persisted in the unified vault table, encrypted at rest, written to the audit log, and visible in the credential history view.
6. **Given** a tenant exceeds its configured inbound-webhook rate, **When** another inbound webhook arrives, **Then** the system returns HTTP 429, records the event in audit, and does not invoke downstream processing.
7. **Given** a reconciliation in `draft` state where GL balance and bank balance differ by more than the configured tolerance at the cut-off date, **When** an accountant calls `finalize`, **Then** the call fails with a structured drift report (GL total, bank total, difference, tolerance) and the reconciliation remains in `draft`.
8. **Given** a report (Balance Sheet / P&L / Trial Balance / KPI) that previously relied on hard-coded account-code ranges, **When** account classifications are changed by an admin via the new configurable model, **Then** the report reflects the new classification on the next run without code changes.
9. **Given** a direct SQL `UPDATE treasury_accounts SET current_balance = ...` outside the GL/treasury session context, **When** it is executed, **Then** the DB trigger raises an error and writes an audit row; the same update via the official treasury service path succeeds.
10. **Given** a recurring template whose amount is above the configured human-review threshold, **When** the scheduler runs the template, **Then** the resulting JE is created in `pending_review` and is not posted until an authorized approver acts; below the threshold and with auto-approve enabled, the JE posts and is audited as auto-approved.
11. **Given** any code path that creates a JE, **When** the JE is persisted, **Then** `source` matches the unified enum/casing, fiscal-period gating is applied per the configured draft policy, and JE imbalance beyond the configured epsilon is rejected with a clear error.
12. **Given** an asset return is recorded, **When** the asset has remaining net book value, **Then** the system generates the write-down JE in line with the depreciation policy and links it to the asset record.
13. **Given** a user views a financial report, **When** the request completes, **Then** an audit row is written under the unified report-view audit policy (who, what, when, filters/period), regardless of which report endpoint was used.

### Edge Cases

- `log_activity()` is invoked outside any transaction context (e.g., from a background script): the writer must still produce a durable audit row without polluting an unrelated session.
- The audit outbox worker is down for hours: buffered audit rows must not be lost; on recovery they are flushed in order, and a backlog metric/alert is exposed.
- A sanitization rule has a false positive that masks a non-PII field (e.g., a column literally named `ibanic_code`): rules must be allow-listable per field path and the failure mode must be logged, not silent.
- An endpoint is moved to a new router but its sensitive-permission wrap is forgotten: startup discovery must fail loudly (not warn) so the gap cannot ship.
- An integration credential is rotated while a long-running job uses the old version: the job must continue with the credential snapshot it acquired, and the next job picks up the new one.
- Reconciliation finalize is called concurrently by two users on the same period: only one finalize commits; the other receives a clear conflict error, not a partial state.
- An account is mapped to multiple classifications by misconfiguration: lookup must be deterministic (single active row per company+account) and configuration changes must be validated before save.
- Treasury balance update is attempted by a legitimate migration script: the trigger must offer a clearly-named, audited bypass (e.g., a session-scoped flag set only by Alembic migrations), not a silent escape.
- A recurring template's category is deleted: the scheduler must refuse to generate new JEs and surface a configuration error rather than posting uncategorized JEs.
- Fiscal period is closed mid-month while drafts exist: the draft policy decides behavior; users must see a clear, consistent message regardless of the module they are in.

## Requirements *(mandatory)*

### Functional Requirements

**R1 — Audit logging atomicity & schema**

- **FR-001**: System MUST write audit log rows through a transaction-safe path that never issues `COMMIT` or `ROLLBACK` on the caller's session inside `log_activity()` or any helper it invokes.
- **FR-002**: System MUST persist audit entries via an outbox (or equivalent transactionally-bound buffer) so that audit rows are committed if and only if the originating business transaction commits.
- **FR-003**: System MUST guarantee a single, documented schema for `audit_logs.details` across every callsite; legacy callsites that pass divergent shapes MUST be normalized at the writer boundary.
- **FR-004**: System MUST flush buffered audit rows to `audit_logs` within a bounded, configurable SLA after the originating transaction commits, with backlog metrics and alerting.
- **FR-005**: System MUST use database-authoritative timestamps (e.g., `NOW()` / `clock_timestamp()`) for audit and time-sensitive metadata fields where the policy requires it, not application clock, and MUST document each exception.

**R1 — PII sanitization**

- **FR-006**: System MUST route every write to `audit_logs.details`, every captured request body intended for audit, and every import/validation error message through a single sanitization helper.
- **FR-007**: The sanitizer MUST mask or drop, at minimum: salary amounts, IBANs, national IDs, passwords, API keys/tokens, and full credential payloads, with patterns configured centrally.
- **FR-008**: System MUST allow per-field-path allow-listing of false positives, with the allow-list itself audited.
- **FR-009**: Import-error responses MUST NOT echo internal table/column names or other structural hints to the caller.

**R1 — Sensitive-permission coverage**

- **FR-010**: System MUST expose a single `require_sensitive_permission(scope, critical=...)` decorator/middleware with consistent RBAC, step-up, and audit tagging behavior.
- **FR-011**: System MUST apply this gate to every endpoint reading or mutating: HR PII (salary, IBAN, national ID, contracts), finance posting (JE create/edit/post/reverse), reconciliation finalize, financial-report views, integration credentials, and company settings.
- **FR-012**: System MUST run a startup-time (and CI-time) discovery check that lists all such endpoints and fails the build if any required endpoint is missing the gate.
- **FR-013**: System MUST tag `critical=True` on the agreed list of endpoints (finance posting, credential rotation, payroll mutations, period close) so they are surfaced separately in audit dashboards.

**R1 — Integration secrets & lifecycle**

- **FR-014**: System MUST store ZATCA, SMTP, SMS, payments, shipping, bank-feed, and LDAP credentials in one encrypted vault table with a uniform schema, encrypted at rest using the existing tenant-aware key derivation.
- **FR-015**: System MUST support credential rotation with overlap (new + old usable until cutover) and record rotation events in audit.
- **FR-016**: System MUST support soft-delete on credentials with audit trail and a configurable retention horizon.
- **FR-017**: System MUST raise an alert via the notification queue when a bank feed (or other inbound integration) fails N consecutive times, with N configurable per integration.
- **FR-018**: System MUST enforce a per-tenant rate limit on inbound webhooks, returning HTTP 429 and an audit row when exceeded.
- **FR-019**: System MUST refuse LDAP password POSTs over non-HTTPS in production policy, returning a configuration error rather than silently downgrading.

**R1 — Foundational fraud/security data**

- **FR-020**: System MUST provide a privacy-safe device-fingerprint data model and integration seam (no raw PII stored) so future detection rules can attach without schema changes.
- **FR-021**: System MUST provide an integration seam for impossible-travel detection (login event + coarse geo placeholder + decision hook) without binding to a specific provider.
- **FR-022**: System MUST run a ghost-employee detection rule against payroll snapshots and write findings to audit.

**R2 — Reconciliation, periods, and JE contracts**

- **FR-023**: Reconciliation `finalize` MUST recompute the GL balance for the linked account/treasury at the cut-off date and reject finalize if the absolute drift exceeds the configured tolerance, returning a structured drift report.
- **FR-024**: System MUST enforce a single configurable epsilon for JE balance and refuse to post any JE outside that tolerance.
- **FR-025**: System MUST normalize `source` on invoices and JEs to a single casing/enum, including a one-time backfill for historical rows.
- **FR-026**: System MUST enforce a uniform fiscal-period draft policy (allow or block drafts in closed periods) consistently across all modules, configurable per company.
- **FR-027**: System MUST generate the asset-return write-down JE in line with depreciation policy and link it to the asset record.
- **FR-028**: System MUST document and enforce a multi-currency revaluation rounding policy with explicit precision bounds.

**R2 — Account classification (replaces code ranges)**

- **FR-029**: System MUST introduce a configurable `account_classifications` table (per company) that maps each account to its statement category, sign, and aggregation hints.
- **FR-030**: System MUST replace hard-coded account-code-range checks in Balance Sheet, Income Statement, Trial Balance, KPI dashboard, and balance-sheet sign logic with calls to the new classifier.
- **FR-031**: System MUST validate the classification configuration on save (no overlapping ranges, no orphan accounts, single active row per company+account).
- **FR-032**: System MUST seed defaults for new companies that match today's effective behavior so existing reports remain stable post-migration.

**R2 — Treasury balance authority**

- **FR-033**: System MUST install a DB-level trigger that blocks direct mutation of `treasury_accounts.current_balance` outside the official GL/treasury session context, with a clearly-named, audited bypass for migrations.
- **FR-034**: System MUST audit every blocked attempt with caller context.

**R2 — Expenses, recurring templates, cost centers**

- **FR-035**: System MUST support an optional human-review workflow above a configurable amount on recurring JE templates; below the threshold, auto-approve runs via a scheduler/hook with audit.
- **FR-036**: System MUST require every recurring template to be linked to a unified expense category, and MUST propagate that category to generated JEs for reporting.
- **FR-037**: System MUST provide an employee-receipt-vs-advance reconciliation model wired to approvals and GL, replacing ad-hoc handling.
- **FR-038**: System MUST support a per-company `cost_center_id` enforcement policy (off / warn / required) with override hooks for documented exceptions.
- **FR-039**: System MUST audit financial-report views under a single uniform policy, regardless of which report endpoint served the request.

### Key Entities *(include if feature involves data)*

- **audit_logs**: existing table; this feature adds a stable `details` schema contract, ensures all writes go through the outbox path, and adds indices supporting the backlog/SLA monitoring. Critical fields: `tenant_id`, `actor_id`, `action`, `entity_type`, `entity_id`, `details` (JSONB, sanitized), `created_at` (DB time), `critical` (bool).
- **audit_outbox**: new buffer table holding pending audit rows in the originating transaction. Critical fields: `id`, `tenant_id`, `payload` (JSONB, sanitized), `enqueued_at`, `flushed_at`, `attempt_count`, `last_error`.
- **integration_credentials**: new unified vault table replacing scattered storage. Critical fields: `tenant_id`, `integration` (enum: zatca/smtp/sms/payments/shipping/bank/ldap), `name`, `secret_ciphertext`, `key_version`, `status` (active/rotating/soft_deleted), `rotated_at`, `expires_at`, `created_by`, `deleted_at`.
- **integration_webhook_events**: existing/new table used for inbound webhook records, extended with rate-limit decisions and per-tenant counters.
- **device_fingerprints**: new privacy-safe table holding hashed device identifiers tied to a session/login event; no raw user-agent/IP stored beyond what is already retained by login audit.
- **login_geo_events**: new lightweight table holding coarse geo placeholders for impossible-travel detection seam.
- **account_classifications**: new table mapping `(tenant_id, account_id) → statement_category, sign, aggregation`. Replaces hard-coded code ranges.
- **expense_categories**: existing/new unified table referenced by recurring templates and generated JEs.
- **recurring_je_templates**: existing table extended with `review_threshold`, `auto_approve` flag, and mandatory `expense_category_id` FK.
- **employee_receipt_settlements**: new table linking employee receipts to advances and approval/GL records.
- **treasury_accounts**: existing table; protected by the new `current_balance` mutation trigger.
- **journal_entries** / **invoices**: existing tables; `source` column normalized via migration; fiscal-period gate consumes the same enum.
- **company_settings**: existing key-value store; this feature adds (without restructuring it) the keys for JE epsilon, draft-in-closed-period policy, audit-log SLA, recurring-review threshold, cost-center policy, and webhook rate limits.

**Data Documentation Rule**: Mention table names and critical fields only. Do not include full DDL unless explicitly requested.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of audit-log writes in production code paths go through the outbox writer; an automated check finds zero direct `INSERT INTO audit_logs` statements outside the writer module.
- **SC-002**: Zero `COMMIT` or `ROLLBACK` calls inside `log_activity()` or its dependencies, verified by a static check in CI.
- **SC-003**: Audit-log SLA: 99% of buffered audit rows are flushed within the configured SLA (default ≤ 60 seconds) under normal load; a backlog alert fires within 5 minutes of breach.
- **SC-004**: PII sweep on a seeded environment returns zero raw matches for salary, IBAN, national ID, password, or API-token patterns across the last 1000 audit rows, the last 1000 captured request bodies, and import-error samples.
- **SC-005**: 100% of the agreed list of sensitive endpoints (HR PII / finance posting / reconciliation / report views / integration credentials / settings) are wrapped by `require_sensitive_permission`; CI fails when coverage is incomplete.
- **SC-006**: 100% of integration credentials (ZATCA/SMTP/SMS/payments/shipping/bank/LDAP) are read from the unified vault; legacy storage paths return zero hits in a code/data audit.
- **SC-007**: Inbound-webhook rate limiter rejects requests above the configured per-tenant threshold and emits an audit row in 100% of test cases, with no false rejections under threshold in load test.
- **SC-008**: Bank-feed failure alert fires within 1 scheduling cycle after N consecutive failures (N configurable, default 3).
- **SC-009**: Reconciliation finalize blocks every drifted reconciliation in test fixtures and admits every clean one; zero false negatives on a curated drift dataset.
- **SC-010**: 100% of report sign/category lookups in Balance Sheet, Income Statement, Trial Balance, and KPI dashboard go through the new account classifier; zero remaining hard-coded account-code-range checks in those report modules.
- **SC-011**: Direct SQL update of `treasury_accounts.current_balance` outside the sanctioned path is blocked in 100% of test attempts; sanctioned path succeeds in 100% of test attempts.
- **SC-012**: All recurring JE templates have a non-null `expense_category_id`; auto-approve below threshold posts in 100% of test cases; above threshold routes to review in 100% of test cases.
- **SC-013**: 100% of JEs created post-migration have `source` matching the unified enum; one-time backfill leaves zero rows with legacy casing.
- **SC-014**: 100% of financial-report view requests, regardless of endpoint, write a uniform audit row.
- **SC-015**: No regression in tenant-isolation tests, JE-balance tests, or fiscal-period tests after migration.

## Assumptions

- The existing `transactional()` helper and SQLAlchemy session model are the canonical transaction boundary; the audit outbox flush worker can run inside the existing scheduler/worker.
- The existing tenant-aware key derivation used by current encryption helpers is suitable for the unified credential vault; a separate KMS rollout is not required for this feature.
- Account classification can be modeled per-company without breaking multi-tenant isolation, and the chart of accounts already has stable account IDs that can be referenced.
- Default account-classification seed values can be derived from current code-range heuristics so the migration is behavior-preserving on day one.
- Treasury balance authority is enforceable in PostgreSQL via a session-context flag (e.g., `set_config(...)`) recognized by the trigger; this matches existing `transactional()` patterns.
- Fiscal-period status is already authoritative in the database; this feature configures, not redesigns, the draft policy.
- Notification queue exists (or is at least usable in stub form) and can be invoked for credential-expiry, bank-feed-failure, and webhook-rate-limit alerts; a full notification redesign (R6) is not required.
- Tests will be added/extended by the implementer; per the user's instruction, scope here covers everything else needed for a coder to implement without further specification.
- Frontend changes are limited to admin screens for the credential vault, account classification, recurring-template thresholds, and policy toggles; the broader frontend refactor (R8) is not part of this feature.
- Provider-specific work (real IP-geo provider for impossible-travel, real device-fingerprint heuristics, ClamAV/anti-malware, etc.) is intentionally out; only data models and integration seams are delivered for those.
