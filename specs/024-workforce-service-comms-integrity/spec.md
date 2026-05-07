# Feature Specification: HR/Payroll/PII + FSM/DMS/Notifications Remediation (R5 + R6)

**Feature Branch**: `024-workforce-service-comms-integrity`
**Created**: 2026-05-02
**Status**: Draft
**Input**: User description: "do R5 — HR/Payroll/PII and R6 — FSM/DMS/Notifications on one speckit; the coder is cheaper than you, so spec everything well"

## Scope & Functional Flows *(mandatory)*

### Problem / Goal

Two adjacent operational tracks remain open after batch B41 and after features 022/023:

- **R5 — Workforce lane** (HR, Payroll, PII): payroll periods can overlap, salary/IBAN visibility is not yet uniformly gated, payroll bank movements are not fully recorded in `bank_transactions`, period reversal has no formal workflow, and several smaller items (bulk salary increments, period_id mismatch, payslip uniqueness, attendance↔timetracking link, ticket allowance, payslip header, loan account split, service-years rounding, bank-code seeds, timezone of subscription scheduler) need closure.
- **R6 — Service/Comms lane** (FSM, DMS, Notifications): service pricing and contract-coverage/margin model is missing, technician profile (skills/zones/availability) is missing, preventive maintenance scheduler is not driven from assets/contracts, asset/service/shopfloor maintenance models are not unified, contract↔invoice↔service-order linkage is incomplete, DMS lacks anti-malware/streaming MIME validation/per-tenant quotas, related-module FK is still string-typed, and notifications still have per-channel ad-hoc retry logic without a unified queue/DLQ/idempotency.

These two lanes are coupled at multiple points (HR-driven notifications, FSM-driven email/SMS, payroll-driven document attachments, contract auto-renew that emits invoices and service orders). Shipping them as one coordinated change set avoids a third round-trip for cross-cutting plumbing (notification queue, attachment validation, audit + sensitive permissions on payroll/HR).

The outcome must:

- Close **PII protection** end-to-end across HR endpoints (salary/IBAN behind `hr.pii`, field encryption at rest, sanitized error paths).
- Make **payroll periods** safe (no overlap, deterministic period_id, configurable timezone, payslip uniqueness, bank movements recorded, formal reversal workflow with GL + WPS reversal).
- Deliver **bulk salary increments** with approval and audit, **service-years policy** beyond 365.25 rounding, **ticket allowance** computation, **bank code** sourcing from a seed table.
- Establish a **service pricing + contract coverage + margin** model that drives FSM correctly (zero-revenue / positive-cost gate, contract→service-order, contract→invoice, technician profile matching).
- Deliver a **preventive maintenance scheduler** that reads from assets/contracts/equipment and unifies the three maintenance silos under one engine (with backward-compatible facades).
- Establish a **unified DMS** with per-tenant/per-user quotas + scheduler cleanup, streaming MIME/signature validation, anti-malware scan, and FK-typed `related_module/related_id` (or relation model).
- Establish a **unified notification dispatcher** with retry, deduplication, idempotency, DLQ, and the existing `email_templates` table powering email; a single signed approval-action token format across channels.

This feature consumes contracts shipped by features 022 and 023 (audit outbox, PII sanitizer, sensitive-permission gate, secret vault, account classification, JE source enum, fiscal-period policy, treasury balance trigger, and the unified webhooks dispatcher introduced in 023's R3). It MUST NOT re-implement those contracts; it MUST consume them.

### In Scope

**R5 — HR / Payroll / PII**

- **HR PII gating** (#434): every endpoint that returns `salary`, `IBAN`, `national_id`, `passport_number`, `bank_account_number`, `gosi_number`, or any equivalent column is wrapped by `require_sensitive_permission('hr.pii')` from feature 022, and serializers default to masked output unless the caller has the permission. A static check enumerates the endpoints and asserts coverage.
- **Field encryption at rest** (#429): salary and IBAN columns are encrypted using the project's existing field-encryption helper, keys sourced from feature 022's secret vault. A migration encrypts existing rows; ORM read/write paths transparently decrypt for permitted callers.
- **Payroll overlap prevention** (#192): a partial unique index (or `tstzrange` exclusion constraint) prevents two `payroll_periods` for the same `(tenant_id, company_id)` from overlapping; the canonical writer raises `PayrollPeriodOverlap` with a structured payload listing the conflicting period.
- **Payroll bank movements** (#193): every WPS transfer / payroll cheque writes a row into `bank_transactions` with `(source='payroll', source_id=payroll_run_id, line_id=payslip_id)`, balanced against the existing GL JE.
- **Payroll period reversal workflow** (#435): a single `reverse_payroll_period(period_id, reason)` service that (a) reverses the GL JE via `gl_service.reverse(source='payroll', source_id=period_id)`, (b) reverses the WPS file (or marks it `superseded` with a new file), (c) flips period state to `reversed`, (d) audits, (e) is gated by `require_sensitive_permission('payroll.reverse')`. Idempotent on (period_id, reason_hash).
- **Bulk salary increment API** (#436): `POST /hr/salary-increments/bulk` accepts a list of `(employee_id, increment_value | percent, effective_from)` items, runs them inside `transactional()`, requires `require_sensitive_permission('hr.salary.bulk_update')`, writes one audit event per item plus one batch summary event, and returns a per-row outcome (applied / skipped / failed-with-reason).
- **payroll_entries.period_id mismatch** (#419): align legacy DDL with ORM, write a forward migration that drops the legacy column or renames it, and sync `tenant_schema.py` + `database.py`.
- **Subscription scheduler timezone** (#419c): replace `date.today()` with company-timezone aware `now(company_tz).date()` in payroll subscription / scheduled tasks; persist `company_timezone` setting and respect it across all schedulers.
- **Bank code seed** (#305): create `bank_codes` reference table seeded from KSA + GCC banks; remove hardcoded WPS/HR bank code lookups; expose admin-only edit endpoints under `require_sensitive_permission('hr.admin')`.
- **Payslip uniqueness** (#308): unique index `(tenant_id, employee_id, period_id)` on `payslips`; canonical writer raises `PayslipDuplicate` on conflict; backfill resolves any pre-existing dupes by collapsing to the latest row and audit-logging the merge.
- **Attendance ↔ timetracking link** (#373): a service `link_attendance_to_timetracking(employee_id, date_range)` produces consolidated daily rows used by payroll and shopfloor; replaces ad-hoc reads scattered across services.
- **Ticket allowance computation** (#374): a deterministic computation rule on the employee's `ticket_allowance_policy` (annual flat amount, or per-trip with destination matrix), applied at payroll run; entry is its own payslip line with its own GL line.
- **Loan/Advance account split** (#419g): split `acc_map_loans_adv` into `acc_map_loans` and `acc_map_advances` with separate debit/credit mapping rows; migrate callers; legacy view kept read-only for one release.
- **Service-years rounding policy** (#419i): replace `365.25` heuristic with a documented policy: month-precision on completed months from `hire_date` to `as_of_date`, with leap-year aware month-length; expose `service_years_policy` setting (`days_365_25 | months_precise`), default `months_precise`.
- **Payslip printable header/logo** (#376): payslip rendering uses tenant's company branding (logo URL + legal name + CR number) from `company_settings`; falls back to default header when not configured.

**R6 — FSM / DMS / Notifications**

- **Service pricing + contract coverage + margin model** (#213, #214, #424, #272v):
  - `service_pricelists` (per-tenant, per-customer, optional per-contract) with `(service_code, list_price, currency, effective_from, effective_to)`.
  - `service_contracts` extended with `coverage_rules` (covered service codes, excluded service codes, qty limits, value limits) and `pricing_strategy` (`included | discounted_pct | fixed_rate`).
  - Margin computed at service-order completion: `margin = revenue − (parts_cost + labor_cost + overhead)` where `revenue` honours contract coverage; reported on the order and rolled up to the contract.
- **Zero-revenue / positive-cost gate** (#272w): when service-order revenue resolves to zero (fully covered by contract) AND any cost line > 0, the order requires explicit approval via `require_sensitive_permission('fsm.zero_revenue_approve')` before close; otherwise it is auto-closed.
- **Technician profile** (#217, #426): `technicians` table with `skills jsonb`, `zones jsonb`, `availability_rules jsonb`, `certifications jsonb`; service-order assignment uses a deterministic matcher (skill match score + zone match + availability) and exposes a fallback to manual assignment.
- **Preventive maintenance** (#423, #272y, #427, #370, #371, #372):
  - Unified scheduler reads `equipment.next_maintenance_date`, `service_contracts.maintenance_schedule`, and `assets.maintenance_plan`; produces `service_orders` with `kind='preventive'`.
  - Three legacy maintenance silos (asset / service / shopfloor) are unified behind one writer; legacy reads keep working through a thin compatibility layer.
- **Contract → invoice → service-order linkage** (#316, #367, #368):
  - `service_contracts.renew()` produces the next contract period and (per policy) the recurring service-order schedule.
  - `generate_contract_invoice()` produces an invoice through the Order→Invoice path from feature 023 and (per policy) the recurring service orders.
  - Service-order revenue lines link back to the contract invoice line that funds them.
- **DMS quotas + cleanup** (#171, #171b, #299d): per-tenant and per-user storage quotas (settings: `dms.tenant_quota_mb`, `dms.user_quota_mb`); scheduler cleans orphaned uploads (no `related_id`) older than `dms.orphan_retention_days`; reject upload with structured 413 when quota exceeded.
- **Streaming MIME/signature validator** (#299): replace one-shot `python-magic` reads with a streaming `validate_upload_stream(file, declared_mime, max_bytes)` that checks magic bytes, signature consistency, and size limit incrementally; rejects on first mismatch.
- **Anti-malware scan** (#169, #87): integrate ClamAV (default, configured via env) or a vetted cloud provider; uploads with positive scan result are quarantined (state `quarantined`) and admin-notified; failed-scan retry policy + DLQ.
- **`related_module` FK** (#357): introduce `dms_attachment_links` table with `(attachment_id, related_module, related_id)` plus per-module FK constraints via a small registry pattern (one trigger per module checks referential integrity); deprecate string-only `related_module/related_id` columns on `documents` (kept as `archived_*` for backward compatibility).
- **Storage path runtime/config** (#358): centralize storage path resolution in `services/dms/storage_paths.py` reading `dms.storage_root` from settings; remove hardcoded paths.
- **Notification dispatcher unification** (#90, #91, #231, #456, #443, #229, #329):
  - One `notifications.dispatch(event, payload, channels=['email'|'sms'|'push'|'in_app'|'webhook'])` entry point.
  - Persistent `notifications_queue` table with `(idempotency_key, channel, state, attempts, next_attempt_at, last_error, dlq_at)`.
  - One worker per channel pulls `FOR UPDATE SKIP LOCKED`; exponential backoff with jitter; DLQ after `notifications.max_attempts`.
  - Deduplication on `idempotency_key`; default key = `sha256(event_type, entity_id, channel)` over a configurable debounce window.
  - In-app + push retain their existing front-ends; this feature only routes through the queue.
- **`email_templates` table** (#327, #328): existing table becomes the only source for transactional email bodies; legacy hardcoded strings are replaced; templates support `{var}` interpolation and i18n (`en/ar`); admin endpoints are sensitive.
- **Signed approval-action tokens** (#237): single `auth/approval_tokens.py` issues HMAC-signed tokens with `(action, entity_type, entity_id, actor_id, exp)` claims; consumers verify in one helper; replaces ad-hoc tokens scattered in expense / leave / payroll approvals. Keys from feature 022's secret vault.

### Out of Scope

- Sales / POS / CRM / ZATCA / Inventory / Manufacturing remediation (R3 + R4 / feature 023).
- Reports MVs, dashboard widgets, cache strategy, BRIN/partitioning (R7 track).
- Frontend `useApi` migration, CSS splitting, format/debounce/router-navigation sweeps (R8 track) — frontend changes are limited to the small surfaces this feature requires (HR PII unmask UI, payroll reversal screen, bulk salary increment, service-pricing admin, technician profile, DMS quota meter, notification queue monitor, signed-token approval pages).
- Settings JSONB typed-model migration and tax-group junction (#178/#179) — explicitly deferred (same as 023).
- Replacing existing payroll calculation engine, GL posting service, or invoice-creation path. This feature consumes them; it does not redesign them.
- Designing a full HRIS workflow engine (leaves, performance review revamp). Only the items listed in scope are addressed.
- Replacing `python-magic` with a different library — the streaming MIME validator wraps it, not replaces it.

### Functional Flow Summary

- **Flow-100 (HR PII Read)**: A caller reads an HR record. The router gate `require_sensitive_permission('hr.pii')` decides whether PII fields are emitted in plaintext (decrypt + return) or as masked placeholders. Audit row records `pii_revealed=true|false`.
- **Flow-101 (Payroll Period Create)**: Creating a payroll period validates non-overlap via the DB constraint; on conflict the writer raises `PayrollPeriodOverlap` with the conflicting period in the body.
- **Flow-102 (Payroll Run → Bank)**: At payroll run, the WPS file (or cheque set) is generated and one row per payslip is inserted into `bank_transactions` with `(source='payroll', source_id, line_id)`; the JE is posted; both happen in one `transactional()`.
- **Flow-103 (Payroll Reversal)**: An admin invokes reversal with a reason. The service reverses the JE, supersedes the WPS file, sets period state to `reversed`, audits, and emits `payroll.reversed` for the notification queue.
- **Flow-104 (Bulk Salary Increment)**: Admin uploads a list. The service iterates inside `transactional()`, applies validation per row, writes audit per row, and returns a per-row outcome. Failed rows do not poison the batch unless `atomic=true` is set.
- **Flow-105 (Subscription Scheduler)**: A scheduled task computes "today" using `now(company_timezone).date()`. The setting `company_timezone` is per-tenant.
- **Flow-110 (Service Pricelist Resolve)**: A service order resolves price by walking `customer_pricelist → contract_pricelist → tenant_pricelist → service_default_price`; first hit wins. Caching keyed by `(tenant, customer, contract, service_code, as_of)`.
- **Flow-111 (Contract Coverage at Order Close)**: At service-order close, each line is matched against contract coverage. Covered lines have `revenue=0` (or discounted rate per strategy). The zero-revenue / positive-cost gate fires when applicable.
- **Flow-112 (Technician Assignment)**: Assignment matcher scores candidate technicians; auto-assign when the top score exceeds `fsm.auto_assign_threshold`; otherwise route to a human dispatcher.
- **Flow-113 (Preventive Maintenance Scheduler)**: A scheduled task scans assets/equipment/contracts for due maintenance, generates `service_orders` with `kind='preventive'`, deduplicates against open preventive orders for the same `(asset, plan_id, due_window)`.
- **Flow-114 (Contract Renew)**: `service_contracts.renew()` clones the contract for the next period, may auto-emit the next contract invoice, and may schedule recurring service orders per the contract's plan.
- **Flow-120 (DMS Upload)**: A streaming upload runs MIME/signature validation incrementally; on validation pass, the file is written to storage and queued for anti-malware scan; on positive scan, the attachment is `quarantined`. Quota check happens before any byte is persisted.
- **Flow-121 (DMS Cleanup)**: A scheduled task deletes orphaned uploads (no `related_id`) older than `dms.orphan_retention_days`; emits an audit summary.
- **Flow-130 (Notification Dispatch)**: Any service emitting a notification calls `notifications.dispatch(event, payload, channels)`. The dispatcher writes one queue row per channel keyed by `idempotency_key` (ON CONFLICT DO NOTHING). Channel workers pull rows, render templates from `email_templates` (or per-channel templates), send, and update state.
- **Flow-131 (Notification DLQ)**: Rows that exceed `notifications.max_attempts` move to `dead_letter` and emit a `notifications.dead_letter` event for admin attention.
- **Flow-132 (Approval Token)**: Any approval link emitted by email/in-app uses a signed token. Consuming the link verifies signature + expiry + entity match; valid tokens authenticate the action without re-login (single use).

### Acceptance Criteria

1. **Given** a caller without `hr.pii`, **When** they read an employee record via any HR endpoint, **Then** salary, IBAN, national_id, and equivalent fields appear masked (or absent) in the response and an audit row is written with `pii_revealed=false`.
2. **Given** a caller with `hr.pii`, **When** they read the same record, **Then** the fields are decrypted on the fly and returned in plaintext, and the audit row records `pii_revealed=true`.
3. **Given** an existing employee row with plaintext salary/IBAN, **When** the encryption migration runs, **Then** the columns hold ciphertext and reads via permitted callers transparently decrypt to the original values (verified by a parity script across a sample).
4. **Given** an existing payroll period for `(company, 2026-01-01..2026-01-31)`, **When** another period is created with overlap, **Then** the canonical writer raises `PayrollPeriodOverlap` with the conflicting period id and HTTP code 409.
5. **Given** a payroll run, **When** the WPS file is finalised, **Then** one `bank_transactions` row per payslip exists with `(source='payroll', source_id=run_id, line_id=payslip_id)` and the GL JE is balanced.
6. **Given** an admin invokes period reversal, **When** the service runs, **Then** the JE is reversed via `gl_service.reverse(source='payroll', source_id=period_id)`, the WPS file is superseded, the period is `reversed`, audit and `payroll.reversed` notification are emitted, and idempotent retry on the same `(period_id, reason_hash)` is a no-op.
7. **Given** a bulk salary increment of N rows with K invalid, **When** `atomic=false`, **Then** N−K rows are applied, K rows return structured failures, audit has N+1 rows (per-row + summary), and the response surfaces every row's outcome.
8. **Given** payslips backfill, **When** the unique-index migration runs, **Then** any pre-existing duplicates are collapsed to the latest row and the merge is audited; zero unique-index violations remain.
9. **Given** a subscription scheduler job, **When** it runs at 23:30 in `Asia/Riyadh` and the company timezone is `Asia/Riyadh`, **Then** "today" is the local date — not UTC date — and idempotent against re-runs within the same local day.
10. **Given** a service order whose customer has a contract, **When** the price resolver runs, **Then** the precedence customer→contract→tenant→service-default is honoured and the resolved unit price + source level are recorded on the order line.
11. **Given** a service order with positive cost and revenue resolving to zero (full contract coverage), **When** the close action is invoked, **Then** the action requires `fsm.zero_revenue_approve`; without permission the action returns 403 with code `fsm.zero_revenue_requires_approval`.
12. **Given** an asset with `next_maintenance_date = today`, **When** the preventive scheduler runs, **Then** exactly one `service_order` of `kind='preventive'` is generated for that asset and the next due date is computed for the following cycle; re-running the scheduler the same day generates zero additional orders.
13. **Given** three legacy maintenance writers (asset, service, shopfloor), **When** the unified writer is in place, **Then** all three legacy callsites delegate to the unified writer and a static check reports zero direct writes outside the unified writer.
14. **Given** a contract is renewed, **When** `renew()` is called, **Then** the next contract period exists, an invoice is generated through the Order→Invoice service from feature 023 (idempotent on contract+period), and recurring service orders for the new period appear per the contract plan.
15. **Given** a DMS upload exceeding the tenant quota by 1 byte, **When** it is submitted, **Then** zero bytes are persisted and the response is HTTP 413 with code `dms.quota_exceeded`.
16. **Given** a DMS upload with a declared MIME of `application/pdf` but a JPEG signature in the first chunk, **When** streaming validation runs, **Then** the upload is rejected before the second chunk is read and the response is HTTP 415 with code `dms.mime_mismatch`.
17. **Given** an upload that passes MIME validation and is later flagged by ClamAV, **When** the scan completes, **Then** the attachment state moves to `quarantined`, the file is moved to a quarantine path, an admin alert is emitted, and downloads of the attachment return HTTP 451 with code `dms.quarantined`.
18. **Given** a deleted parent record, **When** the new attachment-links FK trigger fires, **Then** orphan attachment links are detected and routed to the cleanup scheduler (not silently kept).
19. **Given** the unified dispatcher receives 100 concurrent calls for the same `(event_type, entity_id, channel)`, **When** the queue processes them, **Then** exactly one channel send occurs (idempotency_key ON CONFLICT DO NOTHING) and the other 99 calls are absorbed without error.
20. **Given** a notification fails permanently (e.g., bounced email), **When** the worker exhausts `notifications.max_attempts`, **Then** the row state is `dead_letter`, a `notifications.dead_letter` event is emitted, and a manual reprocess endpoint can flip the row back to `pending` after admin review.
21. **Given** an approval link is generated for an expense, **When** a user clicks it, **Then** the consumer helper verifies HMAC signature, expiry, and entity binding before executing the action; tampered or expired tokens return HTTP 400 with code `auth.token_invalid`.
22. **Given** a hard-coded transactional email body in legacy code, **When** the migration is applied, **Then** the body lives in the `email_templates` table with `en/ar` locales, and a static check reports zero remaining hardcoded transactional bodies in the modules in scope.

### Edge Cases

- HR PII read by a service-account: the gate evaluates `hr.pii` against the service-account's role; same audit semantics apply.
- Encryption migration interrupted mid-way: rerunning the migration is idempotent (writes only rows where the column is still plaintext, identified by a marker column or a length/format check).
- Payroll period overlap edge: a new period whose end equals an existing period's start (touching) is allowed; only true overlap is rejected.
- WPS file regenerated for the same period (correction): the prior row in `bank_transactions` is marked superseded with `replaced_by_id`; balance and reconciliation are unaffected.
- Period reversal partially completed (JE reversed, WPS not yet superseded) — the reversal is wrapped in `transactional()`; partial state is impossible. If WPS supersession fails, the entire reversal is rolled back.
- Bulk salary increment with effective dates in the past: applied retroactively only when `allow_backdated=true` (admin-set); audit records `effective_from` for traceability; payroll for already-closed periods is not retroactively recomputed unless reversal is also performed.
- Subscription scheduler crossing DST: company-timezone-aware `now()` handles transitions; tasks scheduled at non-existent local times shift forward by the DST gap and are still single-fire.
- Service pricelist with overlapping `effective_from/to`: resolver picks the row with the latest `effective_from ≤ as_of`; on tie, picks `created_at` desc and emits a warning.
- Contract coverage at zero revenue + zero cost: closes silently with no gate (gate fires only on positive cost).
- Technician matching when no candidate scores ≥ threshold: order routes to a manual queue with the top three scored candidates listed.
- Preventive maintenance scheduler running in long catch-up after downtime: each `(asset, plan_id, due_window)` produces at most one order regardless of how many windows passed; a backlog endpoint exposes the missed windows for admin choice.
- DMS upload streaming reaching `max_bytes` exactly: accepted; `max_bytes + 1` byte: rejected with HTTP 413.
- Anti-malware service unreachable: uploads remain in `pending_scan` for `dms.scan_max_pending_minutes`, after which they are auto-quarantined and admin alerted; this is NOT a silent allow.
- Notification template missing for a locale: dispatcher falls back to default locale (`en`) and emits a warning audit event; never blocks the dispatch.
- Notification queue race: worker pulls a row, sender call hangs, worker dies. The row's `next_attempt_at` is set on pickup (visibility timeout) so another worker re-picks after the timeout; no stuck-forever rows.
- Signed approval token replay: `auth/approval_tokens` records `consumed_at` on first use; replay returns HTTP 409 with code `auth.token_consumed`.

## Requirements *(mandatory)*

### Functional Requirements

**R5 — HR / Payroll / PII**

- **FR-100**: System MUST gate every HR endpoint that emits salary, IBAN, national_id, passport_number, bank_account_number, or gosi_number with `require_sensitive_permission('hr.pii')`; serializers MUST default to masked output unless the gate passes.
- **FR-101**: System MUST encrypt salary and IBAN at rest using the project's field-encryption helper with keys from feature 022's secret vault, and MUST migrate existing plaintext rows in a forward, idempotent migration.
- **FR-102**: System MUST prevent `payroll_periods` overlap on `(tenant_id, company_id)` via a DB constraint and MUST surface conflicts as `PayrollPeriodOverlap` (HTTP 409 with the conflicting period id).
- **FR-103**: System MUST insert one `bank_transactions` row per payslip during payroll runs with `(source='payroll', source_id=run_id, line_id=payslip_id)`, balanced against the GL JE, in one `transactional()`.
- **FR-104**: System MUST provide a single `reverse_payroll_period(period_id, reason)` workflow that reverses GL via `gl_service.reverse(source='payroll', source_id=period_id)`, supersedes the WPS file, flips period state to `reversed`, audits, and emits `payroll.reversed`. Idempotent on `(period_id, reason_hash)`. Gated by `require_sensitive_permission('payroll.reverse')`.
- **FR-105**: System MUST expose `POST /hr/salary-increments/bulk` accepting a list of `(employee_id, increment_value | percent, effective_from)` items, gated by `require_sensitive_permission('hr.salary.bulk_update')`, returning a per-row outcome and writing audit per row plus a batch summary.
- **FR-106**: System MUST resolve the `payroll_entries.period_id` mismatch between legacy DDL and ORM via a forward migration and MUST keep `tenant_schema.py` and `database.py` in sync.
- **FR-107**: Subscription scheduler and any payroll-adjacent scheduled task MUST compute "today" as `now(company_timezone).date()`, with `company_timezone` configurable per tenant.
- **FR-108**: System MUST seed bank codes from a `bank_codes` reference table, remove hardcoded WPS/HR bank-code lookups, and expose admin-only edit endpoints under `require_sensitive_permission('hr.admin')`.
- **FR-109**: System MUST enforce uniqueness on `(tenant_id, employee_id, period_id)` for `payslips`; canonical writer raises `PayslipDuplicate`; backfill collapses pre-existing duplicates with audit.
- **FR-110**: System MUST provide `link_attendance_to_timetracking(employee_id, date_range)` as the single source of consolidated daily worked-time rows; payroll and shopfloor consumers MUST call it instead of ad-hoc reads.
- **FR-111**: System MUST compute ticket allowance per the employee's `ticket_allowance_policy` (annual flat or per-trip with destination matrix), as its own payslip + GL line.
- **FR-112**: System MUST split `acc_map_loans_adv` into `acc_map_loans` and `acc_map_advances` with separate debit/credit mapping rows; legacy view kept read-only for one release.
- **FR-113**: Service-years MUST be computed by a `service_years_policy` setting (`days_365_25 | months_precise`, default `months_precise`) and the chosen policy MUST be reflected on every payslip and end-of-service calculation.
- **FR-114**: Payslip rendering MUST use tenant company branding (logo URL, legal name, CR number) from `company_settings` with a documented default fallback.

**R6 — FSM / DMS / Notifications**

- **FR-150**: System MUST provide `service_pricelists` (per-tenant, per-customer, per-contract) with effective-dating and a single price-resolver that walks customer→contract→tenant→service-default precedence.
- **FR-151**: `service_contracts` MUST carry coverage rules and pricing strategy (`included | discounted_pct | fixed_rate`) and MUST expose contract-coverage resolution to service orders.
- **FR-152**: System MUST compute `margin = revenue − (parts_cost + labor_cost + overhead)` at service-order close and roll up per-contract margin.
- **FR-153**: System MUST require `fsm.zero_revenue_approve` permission to close any service order where revenue resolves to zero AND any cost > 0.
- **FR-154**: System MUST maintain a `technicians` profile with `skills`, `zones`, `availability_rules`, `certifications`, and a deterministic assignment matcher with a configurable auto-assign threshold.
- **FR-155**: System MUST provide a unified preventive maintenance scheduler that reads from assets, equipment, and contracts; produces preventive `service_orders`; deduplicates per `(asset, plan_id, due_window)`.
- **FR-156**: Three legacy maintenance silos (asset/service/shopfloor) MUST delegate to a single unified writer; a static check MUST report zero direct writes outside it.
- **FR-157**: `service_contracts.renew()` MUST produce the next contract period and (per policy) a contract invoice via feature 023's Order→Invoice service plus the recurring service orders for the new period.
- **FR-158**: `generate_contract_invoice()` MUST link service-order revenue lines back to the originating contract invoice line.
- **FR-159**: System MUST enforce per-tenant and per-user DMS storage quotas; quota exceedance MUST return HTTP 413 with code `dms.quota_exceeded`; zero bytes are persisted on rejection.
- **FR-160**: System MUST validate every upload streaming-wise for declared-MIME ↔ signature consistency and `max_bytes`; mismatch returns HTTP 415 `dms.mime_mismatch`.
- **FR-161**: System MUST scan every accepted upload via ClamAV (default) or a configured cloud provider; positive scan moves the attachment to `quarantined` with admin alert; downloads of quarantined attachments return HTTP 451 `dms.quarantined`.
- **FR-162**: System MUST scheduler-clean orphaned uploads older than `dms.orphan_retention_days`.
- **FR-163**: System MUST replace string-only `related_module/related_id` with a typed `dms_attachment_links` table guarded by per-module FK constraints (registry-driven trigger pattern); legacy columns kept as `archived_*` for backward compatibility.
- **FR-164**: System MUST centralize storage path resolution behind `services/dms/storage_paths.py` reading from `dms.storage_root`; no module may compute paths inline.
- **FR-165**: System MUST provide a single `notifications.dispatch(event, payload, channels)` entry point backed by a persistent `notifications_queue` with `(idempotency_key, channel, state, attempts, next_attempt_at, last_error, dlq_at)`.
- **FR-166**: System MUST process `notifications_queue` per channel via `FOR UPDATE SKIP LOCKED` workers with exponential backoff with jitter and DLQ after `notifications.max_attempts`.
- **FR-167**: System MUST deduplicate notifications using `idempotency_key` (default `sha256(event_type, entity_id, channel)` over a configurable debounce window); ON CONFLICT DO NOTHING semantics on enqueue.
- **FR-168**: System MUST source all transactional email bodies from `email_templates` (with `en/ar` locales and `{var}` interpolation); legacy hardcoded bodies MUST be migrated; admin endpoints MUST be sensitive.
- **FR-169**: System MUST provide a single signed approval-token format (HMAC; claims = `action, entity_type, entity_id, actor_id, exp`), one issuer + one verifier helper, single-use semantics, keys from feature 022's vault.
- **FR-170**: All new sensitive endpoints in this feature (HR PII admin, payroll reverse, bulk salary, service pricelist admin, technician admin, DMS quotas admin, notifications admin, email templates admin) MUST be gated by `require_sensitive_permission` and registered in the curated discovery registry from feature 022.

**Cross-cutting**

- **FR-190**: All new audit-relevant writes (PII reveal, payroll reversal, bulk salary increments, contract renew, attachment quarantine, notification DLQ moves, email-template edits) MUST go through the audit-outbox pattern shipped in feature 022.
- **FR-191**: All new credentials (signing keys, ClamAV credentials if any, cloud anti-malware tokens, email provider creds) MUST be stored in feature 022's secret vault.
- **FR-192**: All new posted JEs (payroll reversal, ticket allowance, bank movements) MUST use the normalized `JESource` enum and respect feature 022's fiscal-period draft policy.
- **FR-193**: All new schemas / migrations MUST keep `tenant_schema.py` and `database.py` in sync (Principle XXVIII).
- **FR-194**: All new endpoints MUST be reachable from the served OpenAPI spec; the existing OpenAPI coverage check MUST pass.

### Key Entities

- **`employees`**: existing; salary/IBAN/national_id move to encrypted columns; serializer default = masked.
- **`payroll_periods`**: existing; add overlap constraint `(tenant_id, company_id, tstzrange(start_date, end_date, '[]'))` EXCLUDE WITH `&&`; add state extension `reversed`.
- **`payroll_runs`**: existing; add `wps_superseded_by_run_id` (nullable FK self-reference).
- **`payslips`**: existing; add unique `(tenant_id, employee_id, period_id)`; add ticket-allowance line slot via existing line model; backfill resolves duplicates.
- **`bank_transactions`**: existing; ensure `(source, source_id, line_id)` indexed; payroll writes go through here.
- **`bank_codes`**: new. Critical fields: `code`, `name_en`, `name_ar`, `country_code`, `swift`, `active`, `created_at`. Seeded from KSA + GCC banks.
- **`acc_map_loans`** + **`acc_map_advances`**: new (split from `acc_map_loans_adv`). Each has `mapping_kind` (`debit|credit`).
- **`technicians`**: new (or extension of `employees` with role flag). Critical fields: `employee_id`, `skills jsonb`, `zones jsonb`, `availability_rules jsonb`, `certifications jsonb`.
- **`service_pricelists`**: new. Critical fields: `id`, `tenant_id`, `scope` (`tenant|customer|contract`), `customer_id`, `contract_id`, `service_code`, `list_price`, `currency`, `effective_from`, `effective_to`. Indexed on `(tenant_id, scope, customer_id, contract_id, service_code, effective_from)`.
- **`service_contracts`**: existing; add `coverage_rules jsonb`, `pricing_strategy` (`included|discounted_pct|fixed_rate`), `maintenance_schedule jsonb`, `renew_policy` (`auto|manual`).
- **`service_orders`**: existing; add `kind` (`corrective|preventive|installation`), `assigned_technician_id`, `pricelist_source_level`, `revenue_resolved_at`, `margin_revenue`, `margin_cost_parts`, `margin_cost_labor`, `margin_cost_overhead`.
- **`equipment` / `assets`**: existing; preventive scheduler reads `next_maintenance_date` and a maintenance plan (`maintenance_plans` table — new or formalised: `id`, `tenant_id`, `kind`, `period_kind` (`days|hours|km`), `period_value`).
- **`maintenance_writer`**: not a table — a service module under `backend/services/fsm/maintenance/` that the three legacy paths delegate to.
- **`dms_attachment_links`**: new. Critical fields: `id`, `tenant_id`, `attachment_id`, `related_module`, `related_id`, `created_at`. Per-module FK enforcement via registry-driven triggers.
- **`documents`** (DMS): existing; add `state` (`pending_scan|clean|quarantined`), `quarantine_path`, `scanned_at`, `scan_engine`, `scan_engine_version`, `checksum_sha256`.
- **`storage_quotas`**: new (or settings keys + view). Critical fields: `tenant_id`, `user_id NULL`, `quota_mb`, `used_mb` (computed), `updated_at`.
- **`notifications_queue`**: new. Critical fields: `id`, `tenant_id`, `event_type`, `entity_type`, `entity_id`, `channel`, `idempotency_key`, `payload jsonb`, `state` (`pending|sending|sent|failed|dead_letter`), `attempts`, `next_attempt_at`, `last_error`, `dlq_at`, timestamps. Unique on `(tenant_id, idempotency_key, channel)`. Indexed on `(state, channel, next_attempt_at)`.
- **`email_templates`**: existing; ensure `(tenant_id, code, locale)` unique; columns `subject_template`, `body_template`, `format` (`text|html`), `active`.
- **`approval_tokens`**: new. Critical fields: `id`, `tenant_id`, `action`, `entity_type`, `entity_id`, `actor_id`, `issued_at`, `expires_at`, `consumed_at NULL`, `idempotency_key`. Single-use semantics enforced by partial unique on `(idempotency_key) WHERE consumed_at IS NULL`.

**Data Documentation Rule**: Mention table names and critical fields only. Do not include full DDL unless explicitly requested.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-100**: Static analysis reports 100% of HR endpoints that emit salary/IBAN/national_id are wrapped by `require_sensitive_permission('hr.pii')`; zero unmasked PII leaks observed in a one-week audit-log sample.
- **SC-101**: After encryption migration, a parity script confirms decrypted reads match a pre-migration sample for 100% of rows; zero columns remain plaintext.
- **SC-102**: Zero overlapping payroll periods exist in production after 30 days; conflict attempts are blocked at the DB layer (load test with concurrent inserts asserts exactly one success).
- **SC-103**: 100% of WPS payroll runs produce one `bank_transactions` row per payslip and the GL JE balances to zero (verified by a nightly reconciliation script).
- **SC-104**: Payroll reversal end-to-end test asserts JE reversed, WPS superseded, period state `reversed`, audit + notification emitted, and idempotent retry is a no-op.
- **SC-105**: Bulk salary increment test asserts per-row outcome contract: applied / skipped / failed-with-reason; audit count = N + 1; failed rows do not poison the batch in `atomic=false` mode.
- **SC-106**: Subscription scheduler test runs under a non-UTC company timezone (e.g. `Asia/Riyadh`) and asserts "today" boundary matches the local date, including a DST transition fixture.
- **SC-107**: Static check reports zero hardcoded bank codes in WPS / HR modules; bank_codes seed parity test asserts the seeded set matches the documented list.
- **SC-108**: Zero duplicate payslips after the unique-index migration; backfill audit shows the resolved duplicates.
- **SC-109**: Service pricelist resolver fixture suite (customer / contract / tenant / service-default precedence) passes with deterministic prices and source-level recorded on the order line.
- **SC-110**: Zero-revenue / positive-cost gate test asserts the close action is blocked without `fsm.zero_revenue_approve` permission and allowed with it.
- **SC-111**: Technician assignment matcher test asserts the top-scoring technician is auto-assigned when the score ≥ threshold and the order is routed to manual queue otherwise; tie-breaking is deterministic.
- **SC-112**: Preventive maintenance scheduler test asserts exactly one preventive order per `(asset, plan_id, due_window)` and zero duplicates on re-run within the same day.
- **SC-113**: Contract renew test asserts a new contract period exists, a contract invoice is generated through feature 023's Order→Invoice path (idempotent), and recurring service orders are scheduled.
- **SC-114**: DMS quota test asserts a 1-byte over-quota upload is rejected with HTTP 413 before any byte is persisted; zero orphaned files appear in storage.
- **SC-115**: Streaming MIME validator test asserts a JPEG-signature upload declared as `application/pdf` is rejected before the second chunk read.
- **SC-116**: Anti-malware test asserts a positive scan moves the attachment to `quarantined`, the file is moved to a quarantine path, an admin alert is emitted, and download returns HTTP 451.
- **SC-117**: A static check reports zero code paths that compute storage paths inline outside `services/dms/storage_paths.py`.
- **SC-118**: A static check reports zero direct writes to legacy maintenance silos outside the unified writer; a parity script asserts the three legacy reads still see consistent data through the compatibility layer.
- **SC-119**: Notification deduplication load test asserts 100 concurrent calls for the same `(event, entity, channel)` produce exactly one channel send (idempotency_key ON CONFLICT DO NOTHING).
- **SC-120**: Notification DLQ test asserts permanent failures move to `dead_letter` after `notifications.max_attempts` and the manual reprocess endpoint flips them back to `pending`.
- **SC-121**: Approval-token replay test asserts re-using a consumed token returns HTTP 409 `auth.token_consumed`; tampered token returns HTTP 400 `auth.token_invalid`.
- **SC-122**: Static check reports zero hardcoded transactional email bodies in modules in scope; all paths read from `email_templates`.

## Assumptions

- Feature 022 (Audit & Security + Finance Integrity) and Feature 023 (Sales/POS/CRM/ZATCA + Inventory/Costing/Manufacturing) ship before this feature and provide: audit outbox writer, PII sanitizer, `require_sensitive_permission` decorator, secret vault, account classification table, fiscal-period draft policy, JE source enum, treasury balance trigger (022); plus invoice state machine, Order→Invoice service, account-mapping resolver, returns-unified, ZATCA outbox, WAC-per-warehouse, MRP, production-completion (023). This feature consumes those primitives and does not duplicate them.
- The unified webhooks dispatcher introduced in 023's R3 is reused for outbound webhooks from this feature (e.g., `dms.attachment_quarantined`, `notifications.dead_letter`).
- Notifications front-end surfaces (in-app drawer, push registration, SMS provider client) already exist; this feature wires them through the new dispatcher rather than rebuilding them.
- ClamAV is the default anti-malware engine, deployed alongside the backend (docker-compose service or sidecar). Cloud providers (Cloudflare, Sophos cloud, etc.) can be configured later via the same interface.
- The "cheaper coder" implementing this spec follows existing module conventions (services + repositories + transactional boundaries, Pydantic schemas, Alembic migrations with backfill scripts, structured errors, audit on every state-changing endpoint) without inventing new architectural patterns.
- Frontend changes are limited to the small surfaces this feature requires; broader frontend sweeps live in R8.
- All migrations include reversible down-paths and backfill scripts; tables introduced as `_v2` are renamed to canonical names within the same release window.
- Tests are written but **not** executed by the implementer unless the user explicitly asks; verification relies on `py_compile`, static checks, EXPLAIN where relevant, and code review.
