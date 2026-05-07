# Tasks: HR/Payroll/PII + FSM/DMS/Notifications Remediation (R5 + R6)

**Input**: Design documents from `/specs/024-workforce-service-comms-integrity/`
**Prerequisites**: plan.md (✓), spec.md (✓), research.md (✓), data-model.md (✓), contracts/ (25 files ✓)

**Tests**: NOT requested. No test tasks generated. CI lints (static checks) are included as discovery-based gates.

**Organization**: Tasks are grouped by capability/requirement phase. No user stories.

## Format: `[ID] [P?] [Area?] Description`

- **[P]**: Independent of other [P] tasks in same phase (different files, no shared edits)
- **[Area]**: Capability/requirement label
- All paths are workspace-relative

---

## Phase 1: Setup (Shared Infrastructure)

- [x] T001 Create new service module skeleton directories: `backend/services/hr/`, `backend/services/payroll/`, `backend/services/wps/`, `backend/services/fsm/`, `backend/services/fsm/maintenance/`, `backend/services/dms/`, `backend/services/notifications/`, `backend/services/notifications/channels/`, `backend/services/auth/` — each with `__init__.py`.
- [x] T002 Create new router skeleton directories: `backend/routers/hr/`, `backend/routers/payroll/`, `backend/routers/fsm/`, `backend/routers/dms/`, `backend/routers/notifications/`, `backend/routers/auth/` — each with `__init__.py` (extend `backend/main.py` to include them).
- [x] T003 [P] Add new Python deps to `backend/requirements.txt`: `python-magic`, `clamd`, `Jinja2` (if not present at sandbox-required version). Pin versions; update `backend/Dockerfile` to install `libmagic1` and `clamav-clamdscan` system packages.
- [x] T004 [P] Add `clamav` and (optionally) a smtp test stub service to `docker-compose.yml` (dev profile only) so devs can validate scanning + mail flows locally.

---

## Phase 2: Foundational (Blocking Prerequisites)

**CRITICAL**: No capability work can begin until this phase is complete.

- [x] T005 Create migration `backend/alembic/versions/024a_hr_pii_encryption.py` — adds `BYTEA` columns for `employees.salary/iban/national_id/passport_number/bank_account_number/gosi_number`, `salary_currency`, ticket-allowance columns, `bank_code_id`, `technician_profile_id`. Includes data-preserving backfill stub (encrypted fill in T015). Mirror schema in `backend/db_ddl/tenant_schema.py` and `backend/database.py`.
- [x] T006 Extend the central `JESource` enum (located by 022) with `PAYROLL`, `PAYROLL_REVERSE`, `TICKET_ALLOWANCE`, `SERVICE_INVOICE`, `SERVICE_INVOICE_REVERSE` (additive; do not break 023). Update `backend/services/gl_service.py` allowed sources whitelist.
- [x] T007 Add new vault keys to `backend/services/credentials_vault.py` registry: `approval_token_signing_key` (HMAC, with `kid` rotation), `dek_pii_<tenant_id>` (per-tenant DEK), `clamav.endpoint`, `clamav.auth` (optional), `smtp.*`, `sms.*`, `push.*` provider credentials. Document required keys in `backend/services/credentials_vault.py` docstring.
- [x] T008 [P] Register all new sensitive permission scopes in `backend/services/permissions/sensitive.py`: `hr.pii`, `hr.salary.write`, `payroll.reverse`, `payroll.allow_backdated`, `contract.renew`, `dms.audit_admin`, `email_templates.admin`, `notifications.admin`. Update startup discovery hook to enumerate them.
- [x] T009 [P] Add new settings keys to `backend/db_ddl/seed_settings.json` (or equivalent default seeder) with the values from `quickstart.md` §3 (all 17 keys). Add seeder invocation to `backend/db_ddl/tenant_runner.py` for new tenants.
- [x] T010 [P] Add i18n error keys to `backend/locales/errors.en.json` and `backend/locales/errors.ar.json` for every error code listed across `contracts/` (45+ codes: `pii.forbidden`, `payroll.period_overlap`, `payroll.bank_movements_already_recorded`, `payroll.run_not_committed`, `payroll.period_not_locked`, `payroll.reverse.forbidden`, `salary.unchanged`, `salary.backdated_blocked`, `salary.invalid_employee`, `salary.invalid_amount`, `attendance.discrepancy_threshold_exceeded`, `ticket_allowance.already_accrued`, `ticket_allowance.no_mapping`, `service_years.future_hire`, `service_years.unknown_policy`, `wps.unknown_bank_code`, `pricelist.no_price`, `pricelist.currency_mismatch`, `coverage.invalid_rules`, `coverage.contract_inactive`, `margin.cost_unresolved`, `margin.revenue_unresolved`, `service_order.zero_revenue_requires_approval`, `technician.no_candidates`, `technician.required_skill_unknown`, `preventive.duplicate_window`, `preventive.invalid_cadence`, `contract.not_renewable`, `contract.already_renewed`, `contract.invoice_mapping_missing`, `dms.quota_exceeded`, `dms.mime_rejected`, `dms.mime_undetected`, `dms.document.pending_scan`, `dms.document.quarantined`, `attachment.unknown_entity_type`, `attachment.duplicate_link`, `notifications.duplicate_in_window`, `notifications.template_missing`, `notifications.invalid_recipient`, `template.invalid_jinja`, `template.missing_required_locale`, `approval_token.invalid_signature`, `approval_token.expired`, `approval_token.consumed`, `approval_token.scope_mismatch`).
- [x] T011 Create migration `backend/alembic/versions/024b_payroll_period_overlap.py` — `CREATE EXTENSION IF NOT EXISTS btree_gist;`, add `state` column to `payroll_periods` (enum draft/calculated/locked/reversed), add the `EXCLUDE USING gist (tenant_id WITH =, tstzrange(start_date,end_date,'[]') WITH &&) WHERE (state<>'reversed')` constraint. Sync `tenant_schema.py` + `database.py`.
- [x] T012 [P] Create migration `backend/alembic/versions/024p_notifications_queue.py` — `notifications_queue` table per data-model.md §notifications_queue with all indices including the in-flight unique on `(tenant_id, idempotency_key) WHERE state IN ('pending','sending')`. Sync schema files.
- [x] T013 [P] Create migration `backend/alembic/versions/024r_approval_tokens.py` — `approval_tokens` table per data-model.md §approval_tokens with partial unique on `(nonce) WHERE consumed_at IS NULL`. Sync schema files.

**Checkpoint**: Foundation ready — capability phases below may proceed (some in parallel where their files do not overlap).

---

## Phase 3: Capability — HR PII Protection (Priority: P1, R5)

**Goal**: Every HR endpoint that touches salary/IBAN/national_id/passport/bank_account/gosi is masked by default and only unmasks under `hr.pii`. Field encryption at rest. All unmasked reads audited.

**Independent Validation**: 
- `GET /api/hr/employees/{id}` without `hr.pii` returns `"salary":"****"`. 
- `GET /api/hr/employees/{id}/pii` with `hr.pii` returns plaintext + writes audit row. 
- DB inspection of `employees.salary` shows `BYTEA`, not numeric/varchar.

- [x] T014 [P] [PII] Create `backend/services/hr/pii.py` implementing `hr_pii_serializer.dump`, `unmask_field`, `encrypt_pii`, `decrypt_pii` per `contracts/hr-pii-gate.md`. Encryption uses 022 vault DEK per tenant.
- [x] T015 [PII] Create `backend/scripts/encrypt_existing_pii.py` and reference it from migration 024a's post-step. Reads existing plaintext, writes BYTEA, leaves a side-table `employees_salary_backfill_<ts>` for one release.
- [x] T016 [PII] Update `backend/schemas/employee.py` (or equivalent) Pydantic schemas to use the masked serializer; add `EmployeePiiOut` schema for the unmask endpoint.
- [x] T017 [PII] Create `backend/routers/hr/pii_admin.py` with `GET /api/hr/employees/{id}/pii`, `PATCH /api/hr/employees/{id}/pii`, `GET /api/hr/employees/{id}/salary-history` — all wrapped by `require_sensitive_permission('hr.pii')`. Audit every unmask via `audit_writer.log_activity` after `sanitize_for_audit`.
- [x] T018 [PII] Sweep existing HR routers (`backend/routers/hr.py` or `backend/routers/employees.py`) so every endpoint emitting employee data routes through the masked serializer.
- [x] T019 [P] [PII] Create CI lint `scripts/check_hr_pii_endpoints.py` per `contracts/hr-pii-gate.md` §CI Lint. Wire into existing CI lint stage.

**Checkpoint**: PII gating verified independently.

---

## Phase 4: Capability — Payroll Integrity (Priority: P1, R5)

**Goal**: Period overlap blocked at DB; reversal is a single canonical workflow with GL inverse + bank compensation + WPS supersession; payslip uniqueness; payroll → bank_transactions linkage.

**Independent Validation**:
- Overlapping period creation returns 409 `payroll.period_overlap`.
- Lock then reverse: GL inverse posted, bank rows compensating, idempotent replay returns same record.
- Two payslips for same `(employee_id, period_id)` rejected by unique constraint.

- [x] T020 [P] [PAYROLL] Create migration `024c_payroll_period_reversal_state.py` — adds `wps_superseded_by_run_id` to `payroll_runs`. Sync schema files.
- [x] T021 [P] [PAYROLL] Create migration `024d_payslip_uniqueness.py` — backfill duplicates (keep latest run_id), add unique `(tenant_id, employee_id, period_id) WHERE deleted_at IS NULL`. Sync schema files.
- [x] T022 [P] [PAYROLL] Create migration `024g_payroll_entries_period_id_align.py` — ensures `payroll_entries.period_id` exists with FK; aligns ORM in `backend/models/domain_models/payroll_entry.py`. Sync schema files.
- [x] T023 [P] [PAYROLL] Create `backend/services/payroll/period_writer.py` — canonical `create_period`, `transition_state` per `contracts/payroll-period-overlap.md`. Catches the exclusion violation and translates to 409.
- [x] T024 [P] [PAYROLL] Create `backend/services/payroll/bank_movements.py` — `record_payroll_bank_movements(period_id, run_id)` per contract; partial-unique idempotent insert.
- [x] T025 [PAYROLL] Create `backend/services/payroll/period_reversal.py` — `reverse_payroll_period` per contract; calls `gl_service.reverse(...)`, inserts compensating bank rows, sets `wps_superseded_by_run_id`, audit. Depends on T020, T023, T024, T006.
- [x] T026 [PAYROLL] Create `backend/routers/payroll/reversal.py` with `POST /api/payroll/periods/{id}/reverse` wrapped by `require_sensitive_permission('payroll.reverse')`. Mount in `main.py`.
- [x] T027 [PAYROLL] Update existing payroll router (or create endpoints) for `POST /api/payroll/periods`, `POST /api/payroll/periods/{id}/calculate`, `POST /api/payroll/periods/{id}/lock` to route through `period_writer` exclusively.
- [x] T028 [PAYROLL] Update WPS commit path (`backend/services/payroll/wps_*.py` or routers/payroll wps endpoint) to call `record_payroll_bank_movements` inside the same `transactional()` after WPS file commit.
- [x] T029 [P] [PAYROLL] Create CI lint `scripts/check_payroll_period_writers.py` — forbid `UPDATE payroll_periods SET state` outside `period_writer.py` / `period_reversal.py`. Wire into CI.
- [x] T030 [P] [PAYROLL] Frontend: `frontend/src/pages/payroll/PayrollReversal.jsx` — confirm-and-reason modal, calls reversal endpoint, shows GL/bank summary on success.

**Checkpoint**: Payroll integrity guarantees enforced.

---

## Phase 5: Capability — HR Detail Items (Priority: P2, R5)

**Goal**: Bulk salary increment with per-row outcomes; bank-codes registry replaces hardcoded WPS lookups; loans/advances mapping split; attendance↔timetracking link; ticket allowance; service-years policy; payslip branding.

**Independent Validation**:
- Bulk increment with one backdated row: that row reports `salary.backdated_blocked`, others `updated`.
- WPS file generated using a tenant-overridden bank code from the new table.
- `compute_service_years` returns identical values for both policies on a known fixture.

- [x] T031 [P] [HR-DETAIL] Create migration `024e_acc_map_loans_advances_split.py` — new tables `acc_map_loans`, `acc_map_advances`; backfill from `acc_map_loans_adv` with both copies; create compatibility view. Sync schema files.
- [x] T032 [P] [HR-DETAIL] Create migration `024f_bank_codes.py` — `bank_codes` table + unique indices; loads `backend/db_ddl/seed_bank_codes.json` at tenant bootstrap. Sync schema files. Commit the seed JSON.
- [x] T033 [P] [HR-DETAIL] Create `backend/services/wps/bank_codes.py` per `contracts/bank-codes-registry.md` — `lookup`, `lookup_by_code`. Sweep WPS file builder modules to use it.
- [x] T034 [P] [HR-DETAIL] Create CI lint `scripts/check_hardcoded_bank_codes.py`. Wire into CI.
- [x] T035 [P] [HR-DETAIL] Create `backend/services/hr/bulk_salary_increment.py` per `contracts/bulk-salary-increment.md` — per-row outcomes, dry-run, locked-period guard, history rows.
- [x] T036 [HR-DETAIL] Create `backend/routers/hr/salary_increments.py` with `POST /api/hr/employees/bulk-salary-increment` gated by `require_sensitive_permission('hr.salary.write')`. Depends on T035.
- [x] T037 [P] [HR-DETAIL] Create `backend/services/hr/attendance_timetracking.py` per `contracts/attendance-timetracking-link.md` — `link_attendance_to_timetracking`. Sweep payroll calculation to read `effective_hours` from this helper.
- [x] T038 [P] [HR-DETAIL] Create `backend/services/hr/ticket_allowance.py` per `contracts/ticket-allowance.md` — monthly accrual + pay-out with `JESource.TICKET_ALLOWANCE`. Add scheduler job entry in worker registry.
- [x] T039 [P] [HR-DETAIL] Update `acc_map_payroll` schema (extension migration if needed) to include `ticket_allowance_account_id`/`ticket_allowance_expense_account_id`. Update `services/sales/account_mapping.py::resolve` (from 023) to handle loans/advances split.
- [x] T040 [P] [HR-DETAIL] Create `backend/services/hr/service_years.py` per `contracts/service-years-policy.md` — `compute_service_years` honoring `hr.service_years_policy` setting. Sweep callsites (EOSI, leave-entitlement, any service-year-driven calc) to use this helper.
- [x] T041 [P] [HR-DETAIL] Update `company_settings` payroll subscription scheduler (existing) to use `zoneinfo.ZoneInfo(company_settings.company_timezone)` for trigger time computation.
- [x] T042 [P] [HR-DETAIL] Update payslip print template (`backend/services/payroll/payslip_pdf.py` or equivalent) to include tenant logo + branded header.
- [x] T043 [P] [HR-DETAIL] Frontend: `frontend/src/pages/payroll/BulkSalaryIncrement.jsx` — CSV upload + dry-run preview + per-row outcome table.

**Checkpoint**: HR detail capabilities verified.

---

## Phase 6: Capability — Service Pricing, Contracts & Margin (Priority: P1, R6)

**Goal**: Deterministic price resolver with contract>customer>tenant>default precedence; coverage rules JSONB; service-order margin computed at close; zero-revenue gate.

**Independent Validation**:
- Resolver returns the most-specific active price; `pricelist_source_level` recorded on order.
- Closing a service order with `revenue_total=0, cost_total>0` is rejected without an approval token.

- [x] T044 [P] [FSM-PRICE] Create migration `024h_service_pricelists.py` — new table per data-model.md §service_pricelists with unique index. Sync schema files.
- [x] T045 [P] [FSM-PRICE] Create migration `024i_service_contracts_extension.py` — adds `coverage_rules`, `pricing_strategy`, `maintenance_schedule`, `renew_policy`, `auto_renewed_to_id`. Sync schema files.
- [x] T046 [P] [FSM-PRICE] Create migration `024j_service_orders_extension.py` — adds `kind`, `assigned_technician_id`, `pricelist_source_level`, `revenue_total`, `cost_total`, `margin_amount`, `margin_pct`, `revenue_resolved_at`, `contract_id`. Sync schema files.
- [x] T047 [P] [FSM-PRICE] Create `backend/services/fsm/pricelists.py` per `contracts/service-pricelist-resolver.md` — `resolve_price` returning `(price, level)`.
- [x] T048 [P] [FSM-PRICE] Create `backend/services/fsm/coverage.py` per `contracts/contract-coverage.md` — `resolve_coverage` + Pydantic schema for `coverage_rules`.
- [x] T049 [FSM-PRICE] Create `backend/services/fsm/margin.py` per `contracts/service-margin.md` — `compute_margin` reading WAC via 023's `wac_per_warehouse`. Depends on T046.
- [x] T050 [FSM-PRICE] Create `backend/services/fsm/zero_revenue_gate.py` per `contracts/zero-revenue-gate.md` — invoked from service-order state machine on close. Depends on Phase 12 approval-tokens (T076–T079) for verification.
- [x] T051 [FSM-PRICE] Update existing service-order router (`backend/routers/fsm/service_orders.py` or equivalent) — call resolver on create, margin+gate on close.
- [x] T052 [P] [FSM-PRICE] Create `backend/routers/fsm/pricelists_admin.py` for CRUD + resolve endpoint.
- [x] T053 [P] [FSM-PRICE] Frontend: `frontend/src/pages/fsm/ServicePricelists.jsx` — DataTable + scope-aware editor with valid_from/valid_to.

**Checkpoint**: Pricing/coverage/margin verified.

---

## Phase 7: Capability — Technician Profile & Assignment Matcher (Priority: P1, R6)

**Goal**: `technicians` table with skills/zones/availability/certifications and a deterministic matcher that auto-assigns above threshold.

**Independent Validation**: Matcher returns ranked list; auto-assigns when top score ≥ threshold; excludes inactive/expired-cert technicians.

- [x] T054 [P] [FSM-TECH] Create migration `024k_technicians_profile.py` — `technicians` table with JSONB skills/zones/availability/certifications. Sync schema files.
- [x] T055 [P] [FSM-TECH] Create `backend/services/fsm/technicians.py` per `contracts/technician-profile-matcher.md` — profile CRUD + `technician_assignment_matcher`.
- [x] T056 [FSM-TECH] Wire matcher into service-order create flow (Phase 6 router) so `assigned_technician_id` is set when `top.score >= fsm.auto_assign_threshold`.
- [x] T057 [P] [FSM-TECH] Create `backend/routers/fsm/technicians_admin.py` — profile CRUD + `POST /match`.
- [x] T058 [P] [FSM-TECH] Frontend: `frontend/src/pages/fsm/TechnicianProfileAdmin.jsx` — editor + match preview.

**Checkpoint**: Technician matcher verified.

---

## Phase 8: Capability — Unified Maintenance & Preventive Scheduler (Priority: P1, R6)

**Goal**: One canonical maintenance writer for asset/service/shopfloor silos; preventive scheduler reads `maintenance_plans` and produces deduped `service_orders` (kind=preventive).

**Independent Validation**: Re-running scheduler in same window is a no-op; legacy silo views still readable.

- [x] T059 [P] [FSM-MAINT] Create migration `024l_maintenance_plans.py` — `maintenance_plans` table per data-model.md §maintenance_plans. Sync schema files.
- [x] T060 [P] [FSM-MAINT] Create `backend/services/fsm/maintenance/unified_writer.py` per `contracts/unified-maintenance-writer.md` — `create_work_order(source, ...)`. Sweep asset/service/shopfloor silos to delegate to it.
- [x] T061 [P] [FSM-MAINT] Create `backend/services/fsm/maintenance/preventive_scheduler.py` per `contracts/preventive-maintenance-scheduler.md` — APScheduler job; per-tenant advisory lock; idempotent on `(tenant_id, plan_id, due_window_start)`.
- [x] T062 [FSM-MAINT] Add migration step (in 024l) creating compatibility VIEWs `asset_maintenance_orders`, `shopfloor_maintenance_orders` over `service_orders` filtered by source tag. Drop the underlying legacy tables only after one release (mark TODO in migration docstring).
- [x] T063 [P] [FSM-MAINT] Create CI lint `scripts/check_maintenance_writers.py` per contract §CI Lint. Wire into CI.
- [x] T064 [P] [FSM-MAINT] Register `preventive_scheduler` in worker registry; ensure `dms_av_scanner` and existing schedulers are unaffected.

**Checkpoint**: Maintenance unification verified.

---

## Phase 9: Capability — Service Contract Renewal (Priority: P2, R6)

**Goal**: `service_contracts.renew()` produces successor + (when policy is auto_with_invoice) invoice via 023's Order→Invoice service.

**Independent Validation**: Renewing an in-window contract creates successor with `previous_contract_id`, sets `auto_renewed_to_id`, generates idempotent invoice.

- [x] T065 [FSM-RENEW] Create `backend/services/fsm/contract_renew.py` per `contracts/contract-renew.md`. Idempotency-Key support.
- [x] T066 [FSM-RENEW] Extend `backend/routers/fsm/contracts.py` (or create) with `POST /api/fsm/service-contracts/{id}/renew`. `require_sensitive_permission('contract.renew')` for auto-with-invoice.

**Checkpoint**: Contract renew verified.

---

## Phase 10: Capability — DMS Hardening (Priority: P1, R6)

**Goal**: Per-tenant + per-user quotas (HTTP 413 before persist); streaming MIME validator (415 before persist); ClamAV anti-malware with quarantine state; typed attachment-link table; centralized storage paths.

**Independent Validation**:
- Upload over quota → 413.
- Spoofed-extension binary → 415 before any disk write.
- EICAR test → quarantined; download → 451.

- [x] T067 [P] [DMS] Create migration `024m_dms_attachment_links.py` — new table per data-model.md §dms_attachment_links + indices; backfill from existing `documents.related_module/related_id`; mark old columns deprecated. Sync schema files.
- [x] T068 [P] [DMS] Create migration `024n_documents_scan_state.py` — adds `state`, `quarantine_path`, `scanned_at`, `scan_engine`, `scan_engine_version`, `checksum_sha256`. Sync schema files.
- [x] T069 [P] [DMS] Create migration `024o_storage_quotas.py` — `storage_quotas` snapshot table. Sync schema files.
- [x] T070 [P] [DMS] Create `backend/services/dms/storage_paths.py` per `contracts/dms-attachment-links.md` §Storage Path Centralization.
- [x] T071 [P] [DMS] Create `backend/services/dms/quotas.py` per `contracts/dms-quotas.md` — Redis-cached usage with INCR/DECR on upload/delete; `recompute` nightly.
- [x] T072 [P] [DMS] Create `backend/services/dms/streaming_mime.py` per `contracts/dms-streaming-mime-validator.md` — libmagic streaming validator.
- [x] T073 [P] [DMS] Create `backend/services/dms/antimalware.py` per `contracts/dms-anti-malware.md` — `clamd` adapter; scan worker; quarantine flow; stale-pending alarm.
- [x] T074 [P] [DMS] Create `backend/services/dms/attachment_links.py` per `contracts/dms-attachment-links.md` — `link/unlink/list_for/list_links`.
- [x] T075 [DMS] Update `backend/routers/dms/upload.py` (or equivalent) to streaming flow: chunk read → MIME validate (T072) → quota check (T071) → persist via storage_paths (T070) as `state='pending_scan'` → enqueue scan. Update download endpoint to honor 425/451 per `state`.
- [x] T076 [P] [DMS] Create `backend/routers/dms/quotas_admin.py` (`GET /api/dms/quotas`) and extend attachments admin router with quarantine release endpoint gated by `require_sensitive_permission('dms.audit_admin')`.
- [x] T077 [P] [DMS] Create CI lint `scripts/check_storage_paths.py` and `scripts/check_attachment_links.py` per contracts. Wire into CI.
- [x] T078 [P] [DMS] Sweep callsites that read/write `documents.related_module/related_id` to use `attachment_links` helper. Mark deprecated columns for removal next release.
- [x] T079 [DMS] Register `dms_av_scanner` (calls `antimalware.scan_pending`) and `dms_orphan_cleanup` workers in worker registry; both per-tenant.
- [x] T080 [P] [DMS] Frontend: `frontend/src/pages/dms/QuotaMeter.jsx` and `frontend/src/pages/dms/QuarantineAlerts.jsx`.

**Checkpoint**: DMS hardening verified.

---

## Phase 11: Capability — Notifications Dispatcher & Email Templates (Priority: P1, R6)

**Goal**: Single `notifications.dispatch` is the ONLY way to send transactional notifications. Per-channel `FOR UPDATE SKIP LOCKED` workers with backoff + DLQ. `email_templates` is the only source of email bodies. Webhook channel routes through 023's webhooks dispatcher.

**Independent Validation**:
- Two identical dispatches within window → second returns existing queue id.
- Provider transient error retried with backoff; permanent error → DLQ.
- Reprocess endpoint moves DLQ → pending.

- [x] T081 [P] [NOTIF] Create migration `024q_email_templates_finalize.py` — formalizes `email_templates` schema + unique `(tenant_id, code, locale)`; backfill from any inline templates. Sync schema files.
- [x] T082 [P] [NOTIF] Create `backend/services/notifications/templates.py` per `contracts/email-templates.md` — sandboxed Jinja2 renderer + locale fallback chain.
- [x] T083 [P] [NOTIF] Create `backend/services/notifications/dispatcher.py` per `contracts/notifications-dispatcher.md` — `dispatch` with idempotency-key compute + dedupe-window lookup + insert.
- [x] T084 [P] [NOTIF] Create `backend/services/notifications/queue_worker.py` — claim loop with `FOR UPDATE SKIP LOCKED`, backoff with jitter, DLQ.
- [x] T085 [P] [NOTIF] Create channel adapters: `backend/services/notifications/channels/email.py` (reads templates, SMTP from vault), `sms.py`, `push.py`, `inapp.py`, `webhook.py` (delegates to 023's webhooks dispatcher).
- [x] T086 [NOTIF] Sweep existing `send_email`/`send_sms`/`send_push` callsites in the codebase to call `notifications.dispatch` instead. Inline transactional email bodies replaced with `email_templates` rows (seed any missing codes in en+ar).
- [x] T087 [P] [NOTIF] Create CI lint `scripts/check_notifications_dispatch.py` and `scripts/check_hardcoded_email_bodies.py`. Wire into CI.
- [x] T088 [P] [NOTIF] Create `backend/routers/notifications/queue_admin.py` (`GET /api/admin/notifications/queue`, `POST /reprocess`, `GET /dlq`) gated by `notifications.read` / `notifications.admin`.
- [x] T089 [P] [NOTIF] Create `backend/routers/notifications/templates_admin.py` (`GET/POST/PATCH /api/admin/email-templates`) gated by `email_templates.admin`.
- [x] T090 [NOTIF] Register one queue worker per channel (`email`, `sms`, `push`, `in_app`, `webhook`) in the worker registry.
- [x] T091 [P] [NOTIF] Frontend: `frontend/src/pages/notifications/NotificationQueueMonitor.jsx` (paginated, filter by state/channel; reprocess button) and `EmailTemplateEditor.jsx` (Jinja preview, locale tabs).

**Checkpoint**: Notifications unification verified.

---

## Phase 12: Capability — Signed Approval Tokens (Priority: P2, R6)

**Goal**: Single HMAC-signed single-use approval tokens for any URL-borne approval action. Used by zero-revenue gate (Phase 6) and any future approval flows.

**Independent Validation**:
- Issue → consume succeeds.
- Replay → 409.
- Past-TTL → 410.
- Tampered signature → 401.

- [x] T092 [P] [TOKENS] Create `backend/services/auth/approval_tokens.py` per `contracts/approval-tokens.md` — `issue`, `verify_and_consume` with `kid` rotation support.
- [x] T093 [P] [TOKENS] Create `backend/routers/auth/approval_actions.py` — generic `POST /api/approvals/consume/{action}` that verifies+consumes, dispatches to action handlers (zero-revenue close handler is the first consumer).
- [x] T094 [P] [TOKENS] Add daily sweeper job for `approval_tokens WHERE expires_at < now() - 30d` in worker registry.
- [x] T095 [P] [TOKENS] Create CI lint `scripts/check_approval_tokens.py` — flag any HMAC issuance/verification of approval-action tokens outside `services/auth/approval_tokens.py`. Wire into CI.

**Checkpoint**: Approval tokens verified.

---

## Phase 13: Polish & Cross-Cutting

- [x] T096 [P] Verify the startup banner in `backend/main.py` emits all expected lines from `quickstart.md` §4 (sensitive permissions, notifications workers, schedulers, ClamAV reachability, btree_gist, vault keys present).
- [x] T097 [P] Add Prometheus metrics from `quickstart.md` §8: `aman_payroll_periods_overlap_rejected_total`, `aman_payroll_reversal_total{result}`, `aman_dms_documents_state{state}`, `aman_dms_scan_seconds`, `aman_notifications_queue_depth{channel,state}`, `aman_notifications_attempts_total{channel,result}`, `aman_approval_tokens_total{result}`, `aman_pii_unmask_total{field}`. Register via existing `monitoring/` infra.
- [x] T098 [P] Add Grafana dashboards in `monitoring/grafana/` for the metrics above (one panel per metric family).
- [x] T099 [P] Add Prometheus alert rules in `monitoring/alerts/` for: notifications DLQ depth, DMS pending_scan stalled (> `dms.scan_max_pending_minutes`), approval-token consumption failure spikes, ClamAV unreachable.
- [x] T100 Run all CI lints introduced in this feature locally; fix any flagged callsites: `check_hr_pii_endpoints`, `check_payroll_period_writers`, `check_notifications_dispatch`, `check_storage_paths`, `check_hardcoded_email_bodies`, `check_maintenance_writers`, `check_approval_tokens`, `check_attachment_links`, `check_hardcoded_bank_codes`.
- [x] T101 Run smoke checks 1–11 from `quickstart.md` §5 against a clean tenant DB; capture results in `specs/024-workforce-service-comms-integrity/quickstart-smoke-results.md`.
- [x] T102 [P] Update `docs/RUNBOOK.md` with operational entries: ClamAV outage procedure, notifications channel pause flag, DLQ reprocess flow, PII vault key rotation procedure, payroll reversal SOP.
- [x] T103 [P] Update `docs/PROJECT_DESIGN_REQUIREMENTS.md` (or equivalent design doc) section index referencing the 25 contract docs.

---

## Dependencies

**Phase order**: 1 → 2 → {3, 4, 5, 6, 7, 8, 9, 10, 11, 12} → 13.

Within Phase 2 (foundational): T005, T011, T012, T013 are sequential per file pair (each migration touches `tenant_schema.py` + `database.py`); T006/T007/T008/T009/T010 may run in parallel.

Cross-phase dependencies:
- Phase 6 T050 depends on Phase 12 T092 (approval token verifier). If schedule constraints, implement T092 early then return to Phase 6.
- Phase 6 T049 depends on 023's `wac_per_warehouse` (already shipped).
- Phase 9 T065 depends on 023's `services/sales/order_to_invoice.create_invoice_from_order` (already shipped).
- Phase 11 T085 webhook adapter depends on 023's webhooks dispatcher (already shipped).
- All phases depend on Phase 2 vault key registration (T007), JESource extension (T006), and sensitive permission registration (T008).

Within each capability phase, [P] tasks operate on different files; non-[P] tasks edit shared files (routers, sweeps, dependent services) and must run sequentially after their [P] siblings.

---

## Parallel Execution Examples

**Phase 2 parallel batch**:
```
T006 (gl_service.py extension)
T007 (credentials_vault.py extension)
T008 (sensitive permissions registry)
T009 (settings seeder)
T010 (i18n keys)
```

**Phase 4 parallel batch (after T005, T011 land)**:
```
T020 (024c migration)
T021 (024d migration)
T022 (024g migration)
T023 (period_writer.py)
T024 (bank_movements.py)
```

**Phase 10 parallel batch**:
```
T067, T068, T069 (three independent migrations)
T070, T071, T072, T073, T074 (five independent service modules)
T076, T077, T080 (independent admin/lints/UI)
```

**Phase 11 parallel batch**:
```
T081 (migration 024q)
T082 (templates.py)
T083 (dispatcher.py)
T084 (queue_worker.py)
T085 (5 channel adapter files in parallel internally)
T087, T088, T089, T091 (independent files)
```

---

## Implementation Strategy

**MVP scope (recommended Capability 1 cut)**: Phases 1, 2, 3, 4, 10, 11. Rationale:
- Phase 3 closes the highest-severity audit gap (PII exposure).
- Phase 4 closes the highest-severity finance gap (payroll integrity).
- Phase 10 closes the highest-severity operational gap (uploaded malware reaches users).
- Phase 11 unifies the most-duplicated callsite class (transactional emails) and unblocks every later DLQ requirement.

Phases 5, 6, 7, 8, 9, 12 follow as Increment 2.

Phase 13 (polish) runs continuously alongside or at the end.

---

## Format Validation

All 103 tasks above strictly follow:
- Markdown checkbox `- [ ]`
- Sequential ID `Tnnn`
- Optional `[P]` marker for parallelizable work
- Capability label (`[PII]`, `[PAYROLL]`, `[HR-DETAIL]`, `[FSM-PRICE]`, `[FSM-TECH]`, `[FSM-MAINT]`, `[FSM-RENEW]`, `[DMS]`, `[NOTIF]`, `[TOKENS]`) on capability-phase tasks; setup/foundational/polish tasks intentionally omit it
- Action description with concrete file path(s)

## Summary

- **Total tasks**: 103
- **Setup**: 4 (T001–T004)
- **Foundational**: 9 (T005–T013)
- **Capability — HR PII (P1)**: 6 (T014–T019)
- **Capability — Payroll Integrity (P1)**: 11 (T020–T030)
- **Capability — HR Detail (P2)**: 13 (T031–T043)
- **Capability — Service Pricing/Margin (P1)**: 10 (T044–T053)
- **Capability — Technician Matcher (P1)**: 5 (T054–T058)
- **Capability — Maintenance Unification (P1)**: 6 (T059–T064)
- **Capability — Contract Renew (P2)**: 2 (T065–T066)
- **Capability — DMS Hardening (P1)**: 14 (T067–T080)
- **Capability — Notifications (P1)**: 11 (T081–T091)
- **Capability — Approval Tokens (P2)**: 4 (T092–T095)
- **Polish**: 8 (T096–T103)

**Parallel opportunities**: ~62 of 103 tasks tagged `[P]`. Highest-throughput batches in Phases 10 (DMS) and 11 (Notifications) where ~10 tasks each can run concurrently.
