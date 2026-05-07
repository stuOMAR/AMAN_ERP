# Implementation Plan: HR/Payroll/PII + FSM/DMS/Notifications Remediation (R5 + R6)

**Branch**: `024-workforce-service-comms-integrity` | **Date**: 2026-05-02 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/024-workforce-service-comms-integrity/spec.md`

## Summary

Deliver **R5 (HR / Payroll / PII)** and **R6 (FSM / DMS / Notifications)** from `docs/audit/REMAINING_REMEDIATION_PLAN.md` as one coordinated change set built on top of the primitives shipped by features 022 (audit outbox, PII sanitizer, sensitive-permission gate, secret vault, account classification, JE source enum, fiscal-period policy, treasury balance trigger) and 023 (Order→Invoice service, account-mapping resolver, returns-unified, unified webhooks dispatcher).

The plan introduces:

- **HR PII protection**: every salary/IBAN/national_id/passport/bank-account/gosi endpoint gated by `require_sensitive_permission('hr.pii')`, masked-by-default serializers, and field encryption at rest with keys from 022's vault;
- **Payroll integrity**: tstzrange exclusion constraint preventing period overlap, formal `reverse_payroll_period(...)` workflow that reverses GL via `(source='payroll', source_id=period_id)` and supersedes the WPS file, `bank_transactions` rows for every WPS payslip, `payslips` uniqueness backfill, `payroll_entries.period_id` ORM/DDL alignment, company-timezone-aware schedulers, bulk salary increment API with per-row outcomes;
- **HR detail items**: `bank_codes` reference table (no hardcoded WPS lookups), `link_attendance_to_timetracking(...)` consolidator, ticket-allowance rule, `acc_map_loans_adv` split into separate loans/advances mappings, `service_years_policy` setting, payslip branding header;
- **Service pricing + contract coverage + margin**: `service_pricelists` (tenant/customer/contract scopes), extended `service_contracts.coverage_rules` + `pricing_strategy`, deterministic price resolver, margin computed at SO close, zero-revenue / positive-cost approval gate;
- **Technician profile + assignment matcher**: `technicians.skills/zones/availability/certifications` + scoring matcher with auto-assign threshold;
- **Unified maintenance**: one preventive-maintenance scheduler reading from assets/equipment/contracts; one unified maintenance writer that the asset/service/shopfloor silos delegate to; deduped per `(asset, plan_id, due_window)`;
- **Contract lifecycle**: `service_contracts.renew()` produces the next period and emits a contract invoice through 023's Order→Invoice service plus recurring service orders;
- **DMS hardening**: per-tenant + per-user quota with HTTP 413 before persist, streaming MIME/signature validator, ClamAV-backed anti-malware with quarantine state, `dms_attachment_links` typed FK table replacing string `related_module/related_id`, centralised storage path resolver;
- **Unified notification dispatcher**: persistent `notifications_queue` with `(idempotency_key, channel, state, attempts, next_attempt_at, last_error, dlq_at)`, per-channel `FOR UPDATE SKIP LOCKED` workers, exponential backoff with jitter, DLQ + manual reprocess, `email_templates` table as the only source of transactional bodies (en/ar);
- **Signed approval-action tokens**: single HMAC issuer/verifier with single-use semantics, keys from 022's vault.

The technical approach mirrors features 022 and 023: small, sequenced migrations + additive contracts, callsites swept onto the new helpers behind CI lints. Existing modules continue to compile while sweeps progress.

## Technical Context

**Language/Version**: Python 3.12 (FastAPI), JavaScript (React 18 / Vite) for the small frontend surfaces this feature requires.
**Primary Dependencies**: FastAPI, SQLAlchemy + raw SQL, Pydantic at API boundary, APScheduler / existing worker, Redis (notification dispatcher dedupe + visibility timeouts + DMS scan deduplication), PostgreSQL `btree_gist` (tstzrange exclusion constraint on `payroll_periods`), `python-magic` (wrapped by streaming validator), `clamd` (Python ClamAV client), existing `transactional()`, `gl_service`, `sales/order_to_invoice` (from 023), `webhooks.dispatch` (from 023), `account_classifier` + `account_mapping.resolve` (from 022/023), `require_sensitive_permission` + startup discovery (from 022), `audit_writer.log_activity` + `sanitize_for_audit` (from 022), `credentials_vault` (from 022).
**Storage**: PostgreSQL 15, one DB per tenant. New tables: `bank_codes`, `acc_map_loans`, `acc_map_advances`, `technicians` (or `employees.technician_profile_id` + `technician_profiles`), `service_pricelists`, `maintenance_plans`, `dms_attachment_links`, `storage_quotas` (or settings + view), `notifications_queue`, `approval_tokens`. Extensions to existing tables: `employees` (encrypted columns + serializer flag), `payroll_periods` (state + tstzrange), `payroll_runs` (`wps_superseded_by_run_id`), `payslips` (unique constraint), `service_contracts` (`coverage_rules`, `pricing_strategy`, `maintenance_schedule`, `renew_policy`), `service_orders` (`kind`, `assigned_technician_id`, `pricelist_source_level`, `revenue_resolved_at`, `margin_*`), `documents` (`state`, `quarantine_path`, `scanned_at`, `scan_engine`, `scan_engine_version`, `checksum_sha256`), `email_templates` (unique `(tenant_id, code, locale)`). Compatibility views: `acc_map_loans_adv`, legacy maintenance read facades.
**Testing**: Tests are not required by this plan; the user explicitly asked for an exhaustive spec/plan but did not request tests. CI gates here are static / discovery-based:
- `scripts/check_hr_pii_endpoints.py` — every HR router that emits salary/IBAN/national_id/passport/bank-account/gosi MUST be wrapped by `require_sensitive_permission('hr.pii')` (or use the masked serializer);
- `scripts/check_payroll_period_writers.py` — `payroll_periods.state` writes only via the canonical period writer;
- `scripts/check_notifications_dispatch.py` — no direct `send_email(...)` / `send_sms(...)` / `send_push(...)` outside `services/notifications/dispatcher.py`;
- `scripts/check_storage_paths.py` — no inline storage path arithmetic outside `services/dms/storage_paths.py`;
- `scripts/check_hardcoded_email_bodies.py` — no inline transactional email bodies in modules in scope; everything reads from `email_templates`;
- `scripts/check_maintenance_writers.py` — asset/service/shopfloor maintenance silos delegate to the unified writer;
- `scripts/check_approval_tokens.py` — approval token issuance/verification uses the single helper.
Tests may be added by the implementer when risk warrants (e.g., the deterministic margin / preventive-scheduler / dispatcher dedupe fixtures).
**Target Platform**: Linux server backend; browser frontend; existing mobile surface unchanged.
**Project Type**: AMAN ERP web application (backend + frontend; no mobile changes).
**Performance Goals**: Notification enqueue ≤ 5ms p95 (single INSERT + dedupe); per-channel worker drains 1000 pending rows ≤ 30s under healthy provider; DMS streaming validator decides reject within first chunk (≤ 64KB) when MIME mismatch; ClamAV scan for files ≤ 10MB completes ≤ 5s p95; preventive scheduler 10k assets ≤ 2 min; bulk salary increment for 5k rows ≤ 30s.
**Constraints**: Decimal/NUMERIC for all money; tenant isolation via `get_db_connection(company_id)`; GL postings only via `gl_service` with `JESource` enum (`PAYROLL`, `PAYROLL_REVERSE`, `TICKET_ALLOWANCE`, `SERVICE_ORDER`, `SERVICE_INVOICE`, `SERVICE_INVOICE_REVERSE`); every new endpoint declares `require_permission()` and (for sensitive surfaces) `require_sensitive_permission()`; every schema change ships an Alembic migration **and** updates `backend/db_ddl/tenant_schema.py` + `backend/database.py`; every credential read goes through 022's vault; every audit write goes through 022's outbox writer; every transactional email body lives in `email_templates`.
**Scale/Scope**: Multi-tenant; ~10 new tables, ~7 modified tables, 1 new worker (notifications dispatcher per channel) plus extended scheduler jobs (preventive maintenance, DMS orphan cleanup, approval-token expiry sweeper, anti-malware scan), ~14 service modules touched (HR core, HR PII, payroll, WPS, attendance, FSM service-orders, FSM service-contracts, FSM technicians, FSM maintenance, DMS upload, DMS scanner, notifications dispatcher per channel, notifications templates, approvals). Frontend changes limited to ~7 surfaces (HR PII unmask UI, payroll reversal screen, bulk salary increment, service-pricelist admin, technician profile, DMS quota meter + quarantine alerts, notification queue monitor + DLQ).

## Constitution Check

*Initial pass — pre-research. Re-evaluated after Phase 1 design (see end of section).*

| Gate | Required Evidence | Status |
|------|-------------------|--------|
| Financial precision | Salary, ticket allowance, service-order revenue/cost/margin all `NUMERIC(18,4)`; FX where applicable via 022's `round_amount()` / `round_fx_rate()`; no `float` in payroll or margin arithmetic | PASS |
| Tenant isolation | All new tables carry `tenant_id`; all access via `get_db_connection(company_id)`; notification workers scoped per tenant; Redis keys namespaced `<tenant_id>:`; ClamAV scan results stored per tenant | PASS |
| GL integrity | Payroll reversal posts via `gl_service.reverse(source='payroll', source_id=period_id)`; ticket allowance posts via `gl_service` with its own JE line; service-order revenue/cost recognition flows through existing service-invoice posting (which uses 023's Order→Invoice when applicable); JE source enum extended | PASS |
| Security boundary | New sensitive endpoints (HR PII admin, payroll reverse, bulk salary increment, service pricelist admin, technician admin, DMS quota admin, notifications admin, email templates admin, approval-token issuance internal-only) wrapped with `require_sensitive_permission`; startup discovery from 022 enforces coverage; signed approval tokens for any URL-borne approval action | PASS |
| Regulatory settings | `company_timezone`, `service_years_policy`, `dms.tenant_quota_mb`, `dms.user_quota_mb`, `dms.orphan_retention_days`, `dms.scan_max_pending_minutes`, `notifications.max_attempts`, `notifications.dedupe_window_seconds`, `fsm.auto_assign_threshold`, `fsm.zero_revenue_approval_required`, all in `company_settings`; bank codes seeded from regulator-published list | PASS |
| Calculation centralization | One PII gate (`hr_pii_serializer`); one canonical period writer; one `reverse_payroll_period` service; one `link_attendance_to_timetracking`; one `service_pricelist_resolver`; one `service_margin_calculator`; one `technician_assignment_matcher`; one `unified_maintenance_writer`; one `notifications.dispatch`; one `approval_tokens.issue/verify` helper | PASS |
| Report consistency | Margin and contract coverage flow into existing finance reports through GL postings; payroll reversal reflected in payroll register / WPS reconciliation reports through GL `(source, source_id)` linkage | PASS |
| Concurrency | Notification queue workers use `FOR UPDATE SKIP LOCKED` with visibility timeout; payroll period reversal wraps both GL reversal and WPS supersession in `transactional()`; DMS scan results write under row lock on the attachment row; preventive scheduler holds per-tenant advisory lock; approval-token consumption uses partial-unique-on-not-consumed | PASS |
| Query discipline | Bulk INSERT for bulk salary increment; bounded batch sizes for notification workers + DMS cleanup; partial indices on queue + token + attachment state; bank-code reference table small + cached; preventive scheduler scoped per-tenant + paginated | PASS |
| UI consistency | New admin / monitor screens reuse DataTable, inline error, i18n, destructive-confirm patterns | PASS |
| Schema sync | Every new/changed table ships an Alembic migration **and** updates `backend/db_ddl/tenant_schema.py` + `backend/database.py` in the same task | PASS |
| Artifact boundaries | `data-model.md` lists tables and critical fields only — no full DDL | PASS |
| Spec format | Spec uses requirements + acceptance criteria + edge cases; no user stories | PASS |

**Initial Constitution Check: PASS — proceed to Phase 0.**

## Design Artifact Rules

`data-model.md` lists table names, critical fields, relationships, validation rules and state transitions only. No full DDL is generated; the actual DDL is produced by Alembic migrations and the canonical `tenant_schema.py` / `database.py` updates during implementation.

## Project Structure

### Documentation (this feature)

```text
specs/024-workforce-service-comms-integrity/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── hr-pii-gate.md
│   ├── payroll-period-overlap.md
│   ├── payroll-bank-movements.md
│   ├── payroll-period-reversal.md
│   ├── bulk-salary-increment.md
│   ├── attendance-timetracking-link.md
│   ├── ticket-allowance.md
│   ├── service-years-policy.md
│   ├── bank-codes-registry.md
│   ├── service-pricelist-resolver.md
│   ├── contract-coverage.md
│   ├── service-margin.md
│   ├── zero-revenue-gate.md
│   ├── technician-profile-matcher.md
│   ├── preventive-maintenance-scheduler.md
│   ├── unified-maintenance-writer.md
│   ├── contract-renew.md
│   ├── dms-quotas.md
│   ├── dms-streaming-mime-validator.md
│   ├── dms-anti-malware.md
│   ├── dms-attachment-links.md
│   ├── notifications-dispatcher.md
│   ├── email-templates.md
│   ├── approval-tokens.md
│   └── http-endpoints.md
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
backend/
├── alembic/versions/
│   ├── 024a_hr_pii_encryption.py
│   ├── 024b_payroll_period_overlap.py
│   ├── 024c_payroll_period_reversal_state.py
│   ├── 024d_payslip_uniqueness.py
│   ├── 024e_acc_map_loans_advances_split.py
│   ├── 024f_bank_codes.py
│   ├── 024g_payroll_entries_period_id_align.py
│   ├── 024h_service_pricelists.py
│   ├── 024i_service_contracts_extension.py
│   ├── 024j_service_orders_extension.py
│   ├── 024k_technicians_profile.py
│   ├── 024l_maintenance_plans.py
│   ├── 024m_dms_attachment_links.py
│   ├── 024n_documents_scan_state.py
│   ├── 024o_storage_quotas.py
│   ├── 024p_notifications_queue.py
│   ├── 024q_email_templates_finalize.py
│   └── 024r_approval_tokens.py
├── db_ddl/
│   └── tenant_schema.py            # extended with all new tables/columns/views
├── database.py                     # synced with the tenant_schema additions
├── models/
│   └── domain_models/
│       ├── bank_code.py
│       ├── technician.py
│       ├── service_pricelist.py
│       ├── maintenance_plan.py
│       ├── dms_attachment_link.py
│       ├── storage_quota.py
│       ├── notifications_queue.py
│       ├── approval_token.py
│       └── acc_map_loans_advances.py
├── services/
│   ├── hr/
│   │   ├── pii.py                  # NEW: serializer + decrypt-on-permitted helpers
│   │   ├── attendance_timetracking.py # NEW: link_attendance_to_timetracking()
│   │   ├── ticket_allowance.py     # NEW
│   │   ├── service_years.py        # NEW: months_precise + days_365_25 policies
│   │   └── bulk_salary_increment.py # NEW
│   ├── payroll/
│   │   ├── period_writer.py        # NEW: canonical state writer
│   │   ├── period_reversal.py      # NEW: reverse_payroll_period()
│   │   └── bank_movements.py       # NEW: writes bank_transactions rows
│   ├── wps/
│   │   └── bank_codes.py           # NEW: replaces hardcoded lookups
│   ├── fsm/
│   │   ├── pricelists.py           # NEW: resolver
│   │   ├── coverage.py             # NEW: contract coverage resolver
│   │   ├── margin.py               # NEW: margin calculator
│   │   ├── zero_revenue_gate.py    # NEW
│   │   ├── technicians.py          # NEW: profile + matcher
│   │   ├── maintenance/
│   │   │   ├── unified_writer.py   # NEW: single canonical writer
│   │   │   └── preventive_scheduler.py # NEW
│   │   └── contract_renew.py       # NEW
│   ├── dms/
│   │   ├── storage_paths.py        # NEW: centralized path resolver
│   │   ├── quotas.py               # NEW
│   │   ├── streaming_mime.py       # NEW: streaming validator
│   │   ├── antimalware.py          # NEW: ClamAV adapter + quarantine
│   │   ├── attachment_links.py     # NEW: typed FK helpers
│   │   └── orphan_cleanup.py       # NEW: scheduler job
│   ├── notifications/
│   │   ├── dispatcher.py           # NEW: notifications.dispatch()
│   │   ├── queue_worker.py         # NEW: per-channel worker
│   │   ├── templates.py            # NEW: email_templates resolver + interpolation
│   │   └── channels/
│   │       ├── email.py            # extended: reads from email_templates
│   │       ├── sms.py              # extended: vault credentials
│   │       ├── push.py             # extended
│   │       ├── inapp.py            # extended
│   │       └── webhook.py          # extended: routes through 023's dispatcher
│   └── auth/
│       └── approval_tokens.py      # NEW: HMAC issue/verify
├── routers/
│   ├── hr/
│   │   ├── pii_admin.py            # NEW: reveal/audit endpoints
│   │   └── salary_increments.py    # NEW: bulk endpoint
│   ├── payroll/
│   │   └── reversal.py             # NEW
│   ├── fsm/
│   │   ├── pricelists_admin.py     # NEW
│   │   ├── technicians_admin.py    # NEW
│   │   ├── service_orders.py       # extended: revenue/margin + zero-revenue close gate
│   │   └── contracts.py            # extended: renew + generate_contract_invoice
│   ├── dms/
│   │   ├── upload.py               # extended: streaming + quota + scan
│   │   ├── attachments_admin.py    # extended: quarantine, link CRUD
│   │   └── quotas_admin.py         # NEW
│   ├── notifications/
│   │   ├── queue_admin.py          # NEW: monitor + reprocess
│   │   └── templates_admin.py      # NEW: CRUD email_templates
│   └── auth/
│       └── approval_actions.py     # NEW: token-consuming endpoints
├── scripts/
│   ├── check_hr_pii_endpoints.py
│   ├── check_payroll_period_writers.py
│   ├── check_notifications_dispatch.py
│   ├── check_storage_paths.py
│   ├── check_hardcoded_email_bodies.py
│   ├── check_maintenance_writers.py
│   └── check_approval_tokens.py
└── locales/                        # i18n keys for new errors

frontend/
└── src/
    └── pages/
        ├── hr/
        │   └── PiiUnmaskAction.jsx
        ├── payroll/
        │   ├── PayrollReversal.jsx
        │   └── BulkSalaryIncrement.jsx
        ├── fsm/
        │   ├── ServicePricelists.jsx
        │   └── TechnicianProfileAdmin.jsx
        ├── dms/
        │   ├── QuotaMeter.jsx
        │   └── QuarantineAlerts.jsx
        └── notifications/
            ├── NotificationQueueMonitor.jsx
            └── EmailTemplateEditor.jsx
```

**Structure Decision**: Web application (backend + frontend). No mobile changes. Migrations live under `backend/alembic/versions/` and are mirrored in `backend/db_ddl/tenant_schema.py` and `backend/database.py` per Principle XXVIII (Schema Sync).

## Dependency on Features 022 and 023

This plan **strictly consumes** the following primitives. They MUST exist (or ship concurrently) before this feature can be merged:

**From feature 022:**
- `services/audit_writer.py::log_activity` (outbox-backed; safe inside `transactional()`).
- `services/audit_sanitizer.py::sanitize_for_audit`.
- `services/permissions/sensitive.py::require_sensitive_permission` (with startup discovery hook).
- `services/credentials_vault.py` (signing keys for approval tokens, ClamAV credentials, email/SMS provider secrets all live here; no other store).
- `services/account_classifier.py`.
- `JESource` enum + `gl.je_epsilon` + `fiscal.allow_drafts_in_closed_period` semantics in `gl_service`.
- `round_amount()` / `round_fx_rate()` helpers.

**From feature 023:**
- `services/sales/order_to_invoice.py` — the contract-invoice generator delegates to this for idempotent invoice creation from contract renewals.
- `services/sales/account_mapping.py::resolve` — the central account-mapping resolver (used here for service-order GL accounts and HR loan/advance mappings post-split).
- `services/webhooks/dispatcher` — DMS quarantine alerts and notification DLQ alerts emit via this dispatcher (channel `webhook` in `notifications.dispatch` routes here).
- `audit_writer` JE source enum extensions live in 022; `JESource.SERVICE_INVOICE` / `JESource.SERVICE_INVOICE_REVERSE` / `JESource.PAYROLL` / `JESource.PAYROLL_REVERSE` / `JESource.TICKET_ALLOWANCE` may need to be added (additive — does not break 023).

Every new audited write, every new sensitive endpoint, every new credential, and every new posted JE in this feature MUST route through those primitives. No parallel implementation is permitted.

## Post-Design Constitution Check

*Re-evaluated after Phase 1 artifacts (`data-model.md`, `contracts/`, `quickstart.md`) were written.*

| Gate | Status After Design |
|------|---------------------|
| Financial precision | PASS — all monetary fields confirmed `NUMERIC(18,4)`; payroll, margin, ticket allowance use `Decimal` with ROUND_HALF_UP via 022's helpers. |
| Tenant isolation | PASS — every new table has `tenant_id`; workers acquire connections via `get_db_connection(company_id)`; Redis keys namespaced; ClamAV scan results scoped per tenant. |
| GL integrity | PASS — payroll reversal, ticket allowance, service-order revenue/cost recognition all post via `gl_service` with `JESource` and `(source, source_id)` linkage. |
| Security boundary | PASS — new sensitive endpoints wrapped via 022's decorator; signing keys + provider credentials read only from 022's vault; approval tokens HMAC-signed with vault keys; ClamAV credentials from vault. |
| Regulatory settings | PASS — timezone, service-years policy, DMS quotas/retention, notification limits, FSM thresholds all configured. |
| Calculation centralization | PASS — single PII serializer, single period writer, single attendance link, single pricelist resolver, single coverage resolver, single margin calculator, single matcher, single unified maintenance writer, single dispatcher, single token helper. |
| Report consistency | PASS — payroll, service-order, and contract revenue flow through GL with `(source, source_id)` linkage; existing finance reports unaffected. |
| Concurrency | PASS — `FOR UPDATE SKIP LOCKED` workers, advisory lock for preventive scheduler, partial-unique-on-not-consumed for tokens, exclusion constraint for periods, attachment row lock for scan-result writes. |
| Query discipline | PASS — bulk INSERT for bulk salary increment, bounded batches for workers, partial indices, paginated activity feeds, scheduler scoped + paginated. |
| UI consistency | PASS — new screens follow standard primitives. |
| Schema sync | PASS — every migration paired with `tenant_schema.py` + `database.py` updates. |
| Artifact boundaries | PASS — no DDL in `data-model.md`. |
| Spec format | PASS — requirements + acceptance + edge cases; no user stories. |

**Post-Design Constitution Check: PASS — proceed to Phase 2 (`/speckit.tasks`).**

## Complexity Tracking

No principle is violated; nothing to justify here.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| (none) | — | — |
