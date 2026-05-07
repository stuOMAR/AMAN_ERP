# Implementation Plan: Audit & Security + Finance Integrity Remediation (R1 + R2)

**Branch**: `022-audit-security-finance-integrity` | **Date**: 2026-05-02 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/022-audit-security-finance-integrity/spec.md`

## Summary

Deliver R1 (Audit & Security) and R2 (Finance Integrity) from `docs/audit/REMAINING_REMEDIATION_PLAN.md` as one coordinated change set. The plan introduces:

- a transaction-safe audit writer backed by an `audit_outbox` flushed by a worker, plus a single `sanitize_for_audit()` boundary used by audit, request-body capture, and import errors;
- a single `require_sensitive_permission()` decorator with startup discovery that fails the build when any HR-PII / finance-posting / reconciliation / report-view / credential / settings endpoint is unwrapped;
- a unified `integration_credentials` vault (ZATCA, SMTP, SMS, payments, shipping, bank feed, LDAP) with rotation, soft-delete, audit, and per-tenant inbound-webhook rate limiting;
- finance-integrity contracts: reconciliation `finalize` with GL drift guard, configurable JE epsilon, normalized `source` casing, fiscal-period draft policy, asset-return write-down JE, multi-currency revaluation rounding policy;
- a configurable `account_classifications` table replacing hard-coded account-code-range checks in Balance Sheet, P&L, Trial Balance and KPI dashboards;
- a DB-level trigger asserting the GL/treasury session context before any `treasury_accounts.current_balance` mutation, with an audited migration bypass;
- recurring-template review threshold + mandatory expense-category link, employee-receipt-vs-advance reconciliation, auto-approve-below-threshold scheduler, configurable cost-center policy, uniform report-view audit.

The technical approach favors small, sequenced migrations and pure-additive contracts so existing modules continue to compile while we sweep callsites onto the new helpers.

## Technical Context

**Language/Version**: Python 3.12 (FastAPI), JavaScript (React 18 / Vite) for the small admin screens added by this feature.
**Primary Dependencies**: FastAPI, SQLAlchemy + raw SQL, Pydantic at API boundary, APScheduler / existing worker, Redis (rate limit + cache), PostgreSQL `pgcrypto` / existing tenant key derivation for credential encryption, existing `transactional()` helper, existing `gl_service`.
**Storage**: PostgreSQL 15, one DB per tenant. New tables: `audit_outbox`, `integration_credentials`, `device_fingerprints`, `login_geo_events`, `account_classifications`, `employee_receipt_settlements`. Extensions to existing tables: `recurring_je_templates` (review_threshold, auto_approve, expense_category_id), `audit_logs` (indices + `critical` flag if missing), `journal_entries`/`invoices` (`source` normalization).
**Testing**: Tests are not required by this plan; the user explicitly asked for an exhaustive spec/plan but did not request tests. CI gates here are static / discovery-based (sensitive-permission coverage, no direct `INSERT INTO audit_logs`, no `COMMIT`/`ROLLBACK` in `log_activity`). Tests may be added by the implementer if risk warrants.
**Target Platform**: Linux server backend; browser frontend admin screens; existing mobile surface unaffected.
**Project Type**: AMAN ERP web application (backend + frontend; no mobile changes).
**Performance Goals**: Audit outbox flush 99% within 60s under normal load; reconciliation finalize drift check ≤ 2s for typical periods; account-classifier lookup O(1) with per-request cache; webhook rate-limit decision ≤ 5ms (Redis token bucket).
**Constraints**: Decimal/NUMERIC for all money; tenant isolation via `get_db_connection(company_id)`; GL postings only via `gl_service`; every new endpoint declares `require_permission()` and (for sensitive surfaces) `require_sensitive_permission()`; every schema change ships a migration **and** updates `backend/database.py` / `backend/db_ddl/tenant_schema.py`.
**Scale/Scope**: Multi-tenant; ~7 new tables, ~3 modified tables, ~1 helper module + 1 worker job, ~6 service modules touched (audit, permissions, credentials, reconciliation, reports/classifier, treasury, recurring). Frontend touch is limited to ~5 admin screens.

## Constitution Check

*Initial pass — pre-research. Re-evaluated after Phase 1 design (see end of section).*

| Gate | Required Evidence | Status |
|------|-------------------|--------|
| Financial precision | All amounts (JE epsilon, reconciliation drift, recurring threshold, revaluation precision) declared as `NUMERIC` / `Decimal` with explicit ROUND_HALF_UP policy | PASS |
| Tenant isolation | All new tables carry `tenant_id` (or live in tenant DB); all access via `get_db_connection(company_id)`; outbox worker scoped per tenant | PASS |
| GL integrity | Reconciliation finalize, asset-return write-down JE, recurring JE post all route through `gl_service`; treasury balance trigger enforces GL session context | PASS |
| Security boundary | New decorator `require_sensitive_permission()` augments existing `require_permission()`; unwrapped sensitive endpoints fail startup; credential vault audited end-to-end | PASS |
| Regulatory settings | JE epsilon, fiscal-period draft policy, recurring-review threshold, cost-center policy, webhook rate limits, audit SLA all sourced from `company_settings` | PASS |
| Calculation centralization | New `account_classifier` is the single source for statement category/sign; reconciliation drift check lives in reconciliation service; sanitizer is a single helper module | PASS |
| Report consistency | Reports stop using hard-coded code ranges and switch to classifier; uniform report-view audit policy ensures parity across endpoints | PASS |
| Concurrency | Reconciliation finalize uses `SELECT FOR UPDATE` on the reconciliation row; recurring-template scheduler uses advisory lock per tenant; outbox flush uses `FOR UPDATE SKIP LOCKED` | PASS |
| Query discipline | Outbox flush bounded by batch size + index on `(tenant_id, enqueued_at) WHERE flushed_at IS NULL`; classifier cached per request; no unbounded scans introduced | PASS |
| UI consistency | New admin screens reuse DataTable, inline error, i18n, and destructive-confirm patterns | PASS |
| Schema sync | Every new/changed table ships an Alembic migration **and** updates `backend/database.py` / `backend/db_ddl/tenant_schema.py` in the same task | PASS |
| Artifact boundaries | `data-model.md` lists tables and critical fields only — no full DDL | PASS |
| Spec format | Spec uses requirements + acceptance criteria + edge cases; no user stories | PASS |

**Initial Constitution Check: PASS — proceed to Phase 0.**

## Design Artifact Rules

`data-model.md` lists table names, critical fields, relationships, validation rules and state transitions only. No full DDL is generated; the actual DDL is produced by Alembic migrations and the canonical `tenant_schema.py` updates during implementation.

## Project Structure

### Documentation (this feature)

```text
specs/022-audit-security-finance-integrity/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── audit-writer.md
│   ├── sanitizer.md
│   ├── sensitive-permission.md
│   ├── credential-vault.md
│   ├── webhook-ratelimit.md
│   ├── reconciliation-finalize.md
│   ├── account-classifier.md
│   ├── treasury-balance-trigger.md
│   ├── recurring-template.md
│   └── http-endpoints.md
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
backend/
├── alembic/versions/
│   ├── 022a_audit_outbox.py
│   ├── 022b_integration_credentials.py
│   ├── 022c_account_classifications.py
│   ├── 022d_recurring_template_review.py
│   ├── 022e_employee_receipt_settlements.py
│   ├── 022f_treasury_balance_trigger.py
│   ├── 022g_je_source_normalize.py
│   └── 022h_device_fingerprints_login_geo.py
├── db_ddl/
│   └── tenant_schema.py            # extended with all new tables/columns
├── database.py                     # synced with the tenant_schema additions
├── models/
│   └── domain_models/
│       ├── audit_outbox.py
│       ├── integration_credentials.py
│       ├── account_classifications.py
│       ├── recurring_je_template.py        # extended
│       ├── employee_receipt_settlement.py
│       ├── device_fingerprint.py
│       └── login_geo_event.py
├── services/
│   ├── audit_writer.py             # NEW: outbox-backed log_activity
│   ├── audit_sanitizer.py          # NEW: sanitize_for_audit()
│   ├── audit_outbox_worker.py      # NEW: flush worker
│   ├── permissions/
│   │   └── sensitive.py            # NEW: require_sensitive_permission + discovery
│   ├── credentials_vault.py        # NEW: unified credential CRUD/rotation
│   ├── webhook_rate_limit.py       # NEW: per-tenant token bucket
│   ├── reconciliation_service.py   # extended: finalize GL drift guard
│   ├── account_classifier.py       # NEW: classifier replacing code ranges
│   ├── treasury_service.py         # extended: session-context flag for trigger
│   ├── recurring_je_service.py     # extended: review threshold + auto-approve
│   ├── employee_receipt_service.py # NEW
│   ├── ghost_employee_rule.py      # NEW: payroll snapshot rule
│   └── reports/
│       └── classifier_adapter.py   # report-side wiring to account_classifier
├── routers/
│   ├── credentials.py              # NEW admin endpoints
│   ├── account_classifications.py  # NEW admin endpoints
│   └── (existing routers updated to use require_sensitive_permission)
├── scripts/
│   └── audit_writer_lint.py        # CI: forbid direct INSERT INTO audit_logs / commits inside log_activity
└── locales/                        # i18n keys for new errors

frontend/
└── src/
    └── pages/
        ├── admin/
        │   ├── IntegrationCredentials.jsx
        │   ├── AccountClassifications.jsx
        │   ├── RecurringTemplateReview.jsx
        │   └── PolicySettings.jsx
        └── finance/
            └── ReconciliationFinalizeDialog.jsx  # extended drift-report UI
```

**Structure Decision**: Web application (backend + frontend). Backend changes dominate; frontend is limited to small admin screens. No mobile changes. Migrations live under `backend/alembic/versions/` and are mirrored in `backend/db_ddl/tenant_schema.py` and `backend/database.py` per Principle XXVIII (Schema Sync).

## Post-Design Constitution Check

*Re-evaluated after Phase 1 artifacts (`data-model.md`, `contracts/`, `quickstart.md`) were written.*

| Gate | Status After Design |
|------|---------------------|
| Financial precision | PASS — all monetary fields confirmed `NUMERIC(18,4)` or `NUMERIC(18,6)` for FX; epsilons and thresholds pulled from `company_settings`. |
| Tenant isolation | PASS — every new table has `tenant_id`; outbox flush uses `get_db_connection(company_id)`; credential vault keyed per tenant. |
| GL integrity | PASS — reconciliation finalize, asset-return JE, recurring JE post via `gl_service`; trigger enforces context for treasury balance. |
| Security boundary | PASS — `require_sensitive_permission` discovery enforced at startup; credential vault writes audited; LDAP-over-HTTPS enforced in production policy. |
| Regulatory settings | PASS — no hard-coded thresholds; classifier replaces hard-coded account-code ranges. |
| Calculation centralization | PASS — single sanitizer, single classifier, single audit writer. |
| Report consistency | PASS — Balance Sheet / P&L / Trial Balance / KPI route through classifier; uniform report-view audit policy in place. |
| Concurrency | PASS — reconciliation finalize and outbox flush use proper locks. |
| Query discipline | PASS — bounded batch sizes; partial index on outbox; classifier cached. |
| UI consistency | PASS — admin screens follow DataTable / inline-error / i18n / destructive-confirm rules. |
| Schema sync | PASS — every migration paired with `tenant_schema.py` + `database.py` updates. |
| Artifact boundaries | PASS — no DDL in `data-model.md`. |
| Spec format | PASS — requirements + acceptance + edge cases; no user stories. |

**Post-Design Constitution Check: PASS — proceed to Phase 2 (`/speckit.tasks`).**

## Complexity Tracking

No principle is violated; nothing to justify here.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| (none) | — | — |
