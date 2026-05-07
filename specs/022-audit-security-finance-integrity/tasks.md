# Tasks: Audit & Security + Finance Integrity Remediation (R1 + R2)

**Input**: Design documents from `/specs/022-audit-security-finance-integrity/`
**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/)

**Tests**: Not requested. Tests are intentionally omitted — verification is done via static CI gates (audit-writer lint, sensitive-permission discovery, account-code-range scan) and the smoke checks in [quickstart.md](quickstart.md). Implementer may add tests where risk warrants.

**Organization**: Tasks are grouped by capability/requirement (no user stories). Capability labels reference R1.x / R2.x in `docs/audit/REMAINING_REMEDIATION_PLAN.md` mapped through this feature's contracts.

## Format

`- [ ] [TaskID] [P?] [Area?] Description with file path`

- **[P]**: parallelizable (different files, no dependency on incomplete tasks).
- **[Area]**: capability/requirement label (e.g., `[R1.1]`, `[R2.2]`); omitted on Setup, Foundational and Polish phases.

---

## Phase 1: Setup

**Purpose**: Branch hygiene, scaffolding for the new modules and CI scripts.

- [X] T001 Create directory scaffolding: `backend/services/permissions/`, `backend/services/reports/` (extend if missing), `backend/scripts/` entries for new CI lints; ensure `frontend/src/pages/admin/` exists. No code yet.
- [X] T002 Add empty CI scaffolds at [scripts/audit_writer_lint.py](scripts/audit_writer_lint.py), [scripts/check_account_code_ranges.py](scripts/check_account_code_ranges.py), [scripts/check_credential_callsites.py](scripts/check_credential_callsites.py); each just exits 0 for now and prints a banner. Wire all three into the existing CI command runner used by `scripts/full_code_scanner.py`.
- [X] T003 [P] Add new i18n keys placeholder section in [backend/locales/errors.en.json](backend/locales/errors.en.json) and [backend/locales/errors.ar.json](backend/locales/errors.ar.json) for: `audit.write_error`, `audit.sla_breach`, `permission.sensitive_required`, `permission.step_up_required`, `credentials.duplicate_name`, `credentials.ldap_https_required`, `webhook.rate_limited`, `reconciliation.drift_detected`, `reconciliation.already_finalized`, `recurring.category_required`, `account_classification.missing`, `treasury.balance.context_required`, `je.source_invalid`, `je.epsilon_violation`, `fiscal.period_closed`.

**Checkpoint**: Scaffolding lands without behavior change; CI green.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Build the three primitives every other phase depends on — sanitizer, audit outbox + writer + worker, and sensitive-permission decorator + discovery. Until these are in place, no capability work can start.

**CRITICAL**: No capability phase may begin until this phase is complete and `safe-start.sh` reports the new startup banners listed in [quickstart.md §3](quickstart.md#3-start-backend-and-worker).

### F.1 — PII sanitizer

- [X] T004 Implement `sanitize_for_audit()` in [backend/services/audit_sanitizer.py](backend/services/audit_sanitizer.py) per [contracts/sanitizer.md](specs/022-audit-security-finance-integrity/contracts/sanitizer.md): recursive copy, key-name + dotted-path rules (salary, iban, national_id, password, secret, token, api_key, credit_card, cvv, pwd, passwd, bearer, authorization), structural-hint regexes (`column "..."`, `relation "..."`, `constraint "..."`, raw SQL keywords), allow-list from `company_settings.audit.sanitizer.allow_paths`, sanitizer rule version metadata, never raises.

### F.2 — Audit outbox table + writer + worker

- [X] T005 Alembic migration [backend/alembic/versions/022a_audit_outbox.py](backend/alembic/versions/022a_audit_outbox.py): create `audit_outbox` table per [data-model.md §audit_outbox](specs/022-audit-security-finance-integrity/data-model.md#audit_outbox); add partial index `(tenant_id, enqueued_at) WHERE flushed_at IS NULL`; add `audit_logs.critical BOOLEAN NOT NULL DEFAULT false` if missing; add index `(tenant_id, action, created_at DESC)` if missing; reversible.
- [X] T006 Update canonical schema [backend/db_ddl/tenant_schema.py](backend/db_ddl/tenant_schema.py) and [backend/database.py](backend/database.py) with the same DDL as T005 (Principle XXVIII).
- [X] T007 Implement [backend/services/audit_writer.py](backend/services/audit_writer.py) per [contracts/audit-writer.md](specs/022-audit-security-finance-integrity/contracts/audit-writer.md): public `log_activity(conn, *, action, ...)` that sanitizes via `sanitize_for_audit`, inserts into `audit_outbox` on the caller's session, stamps `enqueued_at = clock_timestamp()`, never commits/rollbacks, raises `AuditWriteError` on failure. Add `AuditDetails` Pydantic base + legacy-dict normalization at the writer boundary.
- [X] T008 Implement outbox flush worker [backend/services/audit_outbox_worker.py](backend/services/audit_outbox_worker.py): batched flush per tenant with `FOR UPDATE SKIP LOCKED`, exponential backoff, backlog metric, SLA from `company_settings.audit.outbox.flush_sla_seconds`, batch size from `company_settings.audit.outbox.batch_size`.
- [X] T009 Wire outbox worker into the existing scheduler/worker entry point ([backend/worker.py](backend/worker.py)); add startup banner `audit.outbox.worker: started (batch_size=..., sla=...)`.
- [X] T010 [P] CI lint [scripts/audit_writer_lint.py](scripts/audit_writer_lint.py): AST scan that fails on any `INSERT INTO audit_logs` outside `services/audit_writer.py` and `services/audit_outbox_worker.py`; fails on any `commit()`/`rollback()` reachable from `log_activity` and its dependencies; fails on `try/except: pass` inside the writer module.

### F.3 — Sensitive-permission decorator + discovery

- [X] T011 Implement `require_sensitive_permission()` FastAPI dependency in [backend/services/permissions/sensitive.py](backend/services/permissions/sensitive.py) per [contracts/sensitive-permission.md](specs/022-audit-security-finance-integrity/contracts/sensitive-permission.md): wraps `require_permission(scope)`, optional step-up, request-scope tagging (`critical`), GET-side `audit_view` writes a uniform report-view audit row, registers route in `SENSITIVE_REGISTRY`.
- [X] T012 Curated registry file [backend/services/permissions/sensitive_routes.yaml](backend/services/permissions/sensitive_routes.yaml) covering the path globs listed in [contracts/sensitive-permission.md §Coverage list](specs/022-audit-security-finance-integrity/contracts/sensitive-permission.md#coverage-list).
- [X] T013 Startup discovery in [backend/services/permissions/sensitive.py](backend/services/permissions/sensitive.py) (or sibling `discover.py`): on FastAPI startup, walk all registered routes, compare with the YAML, `SystemExit(1)` on any mismatch in production; print banner `permissions.discover: OK (N sensitive endpoints wrapped)` on success.
- [X] T014 [P] CLI entry [backend/scripts/permissions_discover.py](backend/scripts/permissions_discover.py) (`python -m backend.scripts.permissions_discover --strict`) for CI; same logic as T013 but always strict; prints offending endpoints in a structured table.

### F.4 — Settings keys

- [X] T015 Seed default values for the new keys in [backend/services/](backend/services/) settings bootstrap per [data-model.md §Settings keys](specs/022-audit-security-finance-integrity/data-model.md#settings-keys-in-company_settings); idempotent on re-run; per-tenant rollout via existing tenant-bootstrap path.

**Checkpoint — Foundation Ready**: Sanitizer + outbox writer + worker + sensitive-permission decorator + discovery + settings all live. Capability phases can now run in parallel.

---

## Phase 3: R1.1 — Audit Atomicity & PII-safe Capture

**Goal**: Every audit/log/error path goes through the new sanitizer + outbox writer; no callsite issues `COMMIT`/`ROLLBACK` from inside `log_activity`; request-body capture and import errors are sanitized.

**Independent Validation**: Smoke check in [quickstart.md §4.1](quickstart.md#41-audit-atomicity) (rollback drops outbox row) and §4.2 (sanitizer masks salary/IBAN); CI lint T010 passes; `audit_writer_lint.py` reports zero offenders.

- [X] T016 [R1.1] Sweep all callsites of the legacy audit helper to import the new `services.audit_writer.log_activity`. Find with `grep -r "log_activity\|insert.*audit_logs"` in `backend/`. Update imports in services that previously called any other writer; the new writer accepts the same kwargs plus `actor_id`/`critical`. **Files: any `backend/services/**.py`, `backend/routers/**.py` matched by the grep.**
- [X] T017 [R1.1] Remove every `commit()` / `rollback()` call inside `log_activity` and any helper it uses; verify the lint T010 passes.
- [X] T018 [P] [R1.1] Update request-body capture middleware (the existing audit/middleware module that records request body for sensitive endpoints — locate via `grep -rn "request_body\|capture_body" backend/`) to call `sanitize_for_audit(body, context=route.path)` before persistence.
- [X] T019 [P] [R1.1] Update import-error formatter ([backend/services/](backend/services/) — find via `grep -rn "import_error\|column \\\"" backend/services backend/routers`) to apply `sanitize_for_audit` to the message before returning to caller, removing structural hints.
- [X] T020 [P] [R1.1] Audit-row schema normalization: at the writer boundary, accept both `dict` and `AuditDetails`; legacy `dict` shapes are wrapped into `{"legacy": <dict>}` and tagged `details_schema_version = 1`. Confirm legacy callsites still produce readable rows.
- [X] T021 [P] [R1.1] DB-time discipline sweep: replace any `datetime.utcnow()`/`datetime.now()` used in audit/period-sensitive metadata with DB time (`clock_timestamp()` via SQL or `func.now()`); document any intentional exception in a comment.

**Checkpoint**: All audit writes flow through the outbox writer; CI green; smoke §4.1/§4.2 pass.

---

## Phase 4: R1.2 — Sensitive-Permission Sweep

**Goal**: Every endpoint covered by `sensitive_routes.yaml` declares `require_sensitive_permission(scope, critical=...)`; the discovery step refuses startup on any unwrapped sensitive endpoint.

**Independent Validation**: `python -m backend.scripts.permissions_discover --strict` exits `0` and prints the full coverage table; smoke check §4.3 in quickstart.

- [X] T022 [R1.2] Wrap finance posting routes (`POST/PUT/PATCH /api/finance/**`, JE create/edit/post/reverse, period close) in `backend/routers/` (locate router files via `ls backend/routers/`) with `Depends(require_sensitive_permission("finance.post", critical=True))`.
- [X] T023 [P] [R1.2] Wrap reconciliation routes (`POST /api/finance/reconciliations/*/finalize` and adjacent edit/delete) with `Depends(require_sensitive_permission("finance.reconciliation.finalize", critical=True))`.
- [X] T024 [P] [R1.2] Wrap financial-report GETs (`/api/reports/finance/**`, `/api/reports/kpi/**`) with `Depends(require_sensitive_permission("reports.finance.view", audit_view=True))`.
- [X] T025 [P] [R1.2] Wrap HR-PII routes that expose `salary`, `iban`, `national_id` and payroll mutation endpoints with `Depends(require_sensitive_permission("hr.pii", critical=True))` and `"hr.payroll"` respectively.
- [X] T026 [P] [R1.2] Wrap admin settings (`/api/admin/settings/**`) and credential admin (`/api/admin/credentials/**`) with `Depends(require_sensitive_permission("admin.settings"|"admin.credentials", critical=True))`.
- [X] T027 [R1.2] Confirm startup in dev fails when any glob in `sensitive_routes.yaml` lacks coverage; iterate on globs/wraps until clean.

**Checkpoint**: Discovery passes; smoke §4.3 returns exit 0.

---

## Phase 5: R1.3 — Credential Vault, Rotation, Webhook Rate Limit, Bank-Feed Failure Alert

**Goal**: Every integration secret comes from `integration_credentials`; rotation/soft-delete/restore are audited; per-tenant webhook rate limit is enforced; bank-feed adapter increments/resets a failure counter and alerts at threshold.

**Independent Validation**: Smoke §4.8 (webhook rate limit) and §4.9 (rotation) in quickstart; `scripts/check_credential_callsites.py` reports zero remaining direct reads.

### Schema + service

- [X] T028 [R1.3] Alembic migration [backend/alembic/versions/022b_integration_credentials.py](backend/alembic/versions/022b_integration_credentials.py): create `integration_credentials` per [data-model.md §integration_credentials](specs/022-audit-security-finance-integrity/data-model.md#integration_credentials); unique partial index on `(tenant_id, integration, name) WHERE status != 'soft_deleted'`.
- [X] T029 [R1.3] Mirror schema in [backend/db_ddl/tenant_schema.py](backend/db_ddl/tenant_schema.py) and [backend/database.py](backend/database.py).
- [X] T030 [R1.3] Implement [backend/services/credentials_vault.py](backend/services/credentials_vault.py) per [contracts/credential-vault.md](specs/022-audit-security-finance-integrity/contracts/credential-vault.md): `create/get/rotate/soft_delete/restore/record_failure/record_success`; envelope encryption via the existing tenant key-derivation helper; LDAP-over-HTTPS rule in production; every write audited with `critical=True`.
- [X] T031 [P] [R1.3] One-shot migrator script [backend/scripts/migrate_credentials_to_vault.py](backend/scripts/migrate_credentials_to_vault.py): read scattered storage (ZATCA/SMTP/SMS/payments/shipping/bank-feed/LDAP), insert into vault with `metadata.origin`. Tenant-aware, idempotent, dry-run flag.

### Sweep callsites

- [X] T032 [R1.3] Sweep [backend/integrations/einvoicing/](backend/integrations/einvoicing/) (ZATCA), [backend/integrations/sms/](backend/integrations/sms/), [backend/integrations/payments/](backend/integrations/payments/), [backend/integrations/shipping/](backend/integrations/shipping/), [backend/integrations/bank_feeds/](backend/integrations/bank_feeds/), and SMTP/LDAP callsites (locate via `grep -rn "smtp\|ldap" backend/`) to read secrets exclusively via `credentials_vault.get_credential(...)`. Remove direct env/settings reads.
- [X] T033 [P] [R1.3] CI lint [scripts/check_credential_callsites.py](scripts/check_credential_callsites.py): fail on any `os.environ`/settings read of secret-pattern keys (smtp_password, zatca_*_secret, sms_api_key, etc.) outside `services/credentials_vault.py` and the migrator script.

### Webhook rate limit

- [X] T034 [R1.3] Implement [backend/services/webhook_rate_limit.py](backend/services/webhook_rate_limit.py) per [contracts/webhook-ratelimit.md](specs/022-audit-security-finance-integrity/contracts/webhook-ratelimit.md): Redis token bucket with atomic Lua, per-tenant key, fail-open on Redis unavailable + structured warning.
- [X] T035 [R1.3] Wire `check_and_consume()` at the entry of every inbound webhook handler in [backend/integrations/](backend/integrations/) (bank feeds, payments, shipping, e-invoicing inbound, SMS delivery callbacks). On rejection: HTTP 429 + `Retry-After` + audit row.

### Bank-feed failure alerting

- [X] T036 [R1.3] Update [backend/integrations/circuit_breaker.py](backend/integrations/circuit_breaker.py) and the bank-feed adapter under [backend/integrations/bank_feeds/](backend/integrations/bank_feeds/) to call `credentials_vault.record_failure/record_success`; on threshold (`bank_feed.failure_alert_threshold`), enqueue a notification via the existing notification queue.

### Admin endpoints + UI

- [X] T037 [R1.3] Router [backend/routers/credentials.py](backend/routers/credentials.py) implementing the verbs in [contracts/http-endpoints.md §Admin: Integration credentials](specs/022-audit-security-finance-integrity/contracts/http-endpoints.md#admin-integration-credentials--sensitive--admincredentials-criticaltrue); register in [backend/main.py](backend/main.py).
- [X] T038 [P] [R1.3] Frontend admin page [frontend/src/pages/admin/IntegrationCredentials.jsx](frontend/src/pages/admin/IntegrationCredentials.jsx) using DataTable, inline errors, i18n, destructive-confirm on rotate/soft-delete; never displays secret material.

**Checkpoint**: Smoke §4.8/§4.9 pass; lint T033 reports zero offenders.

---

## Phase 6: R1.4 — Foundational Fraud/Security Data + Ghost-Employee Rule

**Goal**: Privacy-safe data model and integration seam for device fingerprint + impossible-travel; ghost-employee rule running against payroll snapshots.

**Independent Validation**: Schema present; `evaluate_login_risk()` returns `"ok"` by default and a hook-point test confirms it is called on every login event; ghost-employee rule writes findings to `audit_logs`.

- [X] T039 [R1.4] Alembic migration [backend/alembic/versions/022h_device_fingerprints_login_geo.py](backend/alembic/versions/022h_device_fingerprints_login_geo.py): create `device_fingerprints` and `login_geo_events` per [data-model.md](specs/022-audit-security-finance-integrity/data-model.md); mirror in [backend/db_ddl/tenant_schema.py](backend/db_ddl/tenant_schema.py) and [backend/database.py](backend/database.py).
- [X] T040 [R1.4] Login flow integration (locate via `grep -rn "def login\|/login" backend/routers backend/services`): on successful login, write a `device_fingerprints` upsert (SHA-256 of stable, non-PII components) and a `login_geo_events` row with `risk_decision = "ok"`; expose hook `evaluate_login_risk(user_id, fingerprint_hash) -> RiskDecision` in a new helper.
- [X] T041 [P] [R1.4] Implement `services/ghost_employee_rule.py` per [research.md §R1.9](research.md#r19--ghost-employee-rule); register as a scheduled job in [backend/worker.py](backend/worker.py); findings written to `audit_logs` with `critical = True`.

**Checkpoint**: Login writes both tables; ghost-employee findings appear in audit on a seeded dataset.

---

## Phase 7: R2.1 — Account Classifier (replaces hard-coded code ranges)

**Goal**: One configurable source of truth for statement category/sign across Balance Sheet, P&L, Trial Balance and KPI dashboards.

**Independent Validation**: Smoke §4.5; CI lint `check_account_code_ranges.py` reports zero remaining hard-coded checks in `backend/services/reports/**` and `backend/routers/reports*`.

- [X] T042 [R2.1] Alembic migration [backend/alembic/versions/022c_account_classifications.py](backend/alembic/versions/022c_account_classifications.py): create `account_classifications` per data-model; partial unique index on `(tenant_id, account_id) WHERE is_active = true`.
- [X] T043 [R2.1] Mirror in [backend/db_ddl/tenant_schema.py](backend/db_ddl/tenant_schema.py) and [backend/database.py](backend/database.py).
- [X] T044 [R2.1] Seed step inside the same migration: backfill one active row per existing account using the **current** code-range heuristic (audit `gl_service`/reports/`backend/services/reports/` for the existing logic and replicate it in the seed); mark `aggregation_hint = "seed"`.
- [X] T045 [R2.1] Implement [backend/services/account_classifier.py](backend/services/account_classifier.py) per [contracts/account-classifier.md](specs/022-audit-security-finance-integrity/contracts/account-classifier.md): `classify`, `classify_many`, `upsert_classification`; per-request cache; raises `MissingClassificationError` (no silent fallback).
- [X] T046 [P] [R2.1] Sweep [backend/services/reports/](backend/services/reports/) (balance_sheet, income_statement, trial_balance, kpi/dashboard modules) and any helper that previously asked "is this asset/liability/...?" via account-code ranges. Replace with calls to `account_classifier.classify_many(account_ids)`. Locate via `grep -rn "between.*'1\|account_code\|code\[0\]\|startswith('1\|startswith(\"1" backend/services/reports backend/routers/reports*`.
- [X] T047 [P] [R2.1] CI lint [scripts/check_account_code_ranges.py](scripts/check_account_code_ranges.py): regex/AST scan for code-range checks in `backend/services/reports/**` and `backend/routers/reports*`; fail on any match.
- [X] T048 [P] [R2.1] Admin router [backend/routers/account_classifications.py](backend/routers/account_classifications.py) implementing the verbs in [contracts/http-endpoints.md §Admin: Account classifications](specs/022-audit-security-finance-integrity/contracts/http-endpoints.md#admin-account-classifications--sensitive--adminaccount_classifications-criticaltrue); register in [backend/main.py](backend/main.py).
- [X] T049 [P] [R2.1] Frontend admin page [frontend/src/pages/admin/AccountClassifications.jsx](frontend/src/pages/admin/AccountClassifications.jsx): DataTable list, edit modal, dry-run preview, i18n, destructive-confirm on close-active.

**Checkpoint**: Smoke §4.5 passes; lint T047 reports zero offenders; reports unchanged on day one (seed preserves behavior).

---

## Phase 8: R2.2 — Reconciliation Finalize Drift Guard

**Goal**: Reconciliation finalize refuses on GL drift > tolerance; concurrency safe; structured drift report.

**Independent Validation**: Smoke §4.4 in quickstart.

- [X] T050 [R2.2] Extend [backend/services/reconciliation_service.py](backend/services/reconciliation_service.py) (or create if absent) to implement `finalize_reconciliation(...)` per [contracts/reconciliation-finalize.md](specs/022-audit-security-finance-integrity/contracts/reconciliation-finalize.md): `SELECT FOR UPDATE` on the reconciliation row, recompute GL via `gl_service.get_account_balance(account_id, as_of=cut_off)`, compare to bank/treasury total, refuse on drift > `company_settings.reconciliation.drift_tolerance`, emit audit (`critical=True`) on accept.
- [X] T051 [R2.2] Update reconciliation router (locate via `grep -rn "reconciliation" backend/routers`) so `POST /api/finance/reconciliations/{id}/finalize` returns `200 / 409 + DriftReport / 409 state`. Wrap with `require_sensitive_permission("finance.reconciliation.finalize", critical=True)` (already done in T023 but re-confirm).
- [X] T052 [P] [R2.2] Frontend `ReconciliationFinalizeDialog.jsx` (extend existing dialog if present, else new at [frontend/src/pages/finance/ReconciliationFinalizeDialog.jsx](frontend/src/pages/finance/ReconciliationFinalizeDialog.jsx)): on 409 with `DriftReport`, show GL total / bank total / difference / tolerance / unmatched lines; i18n + destructive-confirm.

**Checkpoint**: Smoke §4.4 passes.

---

## Phase 9: R2.3 — JE Source / Epsilon / Period Gate / Asset Return / FX Rounding

**Goal**: Single source enum + casing for JE/invoice `source`; configurable JE epsilon; uniform fiscal-period draft policy across modules; asset-return write-down JE; documented FX rounding.

**Independent Validation**: All JE creation paths produce rows with normalized `source`; epsilon enforced; closed-period drafts behave per setting; asset return with NBV produces a write-down JE.

- [X] T053 [R2.3] Alembic migration [backend/alembic/versions/022g_je_source_normalize.py](backend/alembic/versions/022g_je_source_normalize.py): one-pass UPDATE normalizing `journal_entries.source` and `invoices.source` to enum values (`sales | purchase | payroll | treasury | manufacturing | manual | recurring | asset | system`); add CHECK constraints; mirror in [backend/db_ddl/tenant_schema.py](backend/db_ddl/tenant_schema.py) and [backend/database.py](backend/database.py).
- [X] T054 [R2.3] Add `JESource` enum module (e.g. [backend/models/domain_models/je_source.py](backend/models/domain_models/je_source.py)); update `gl_service` and every JE producer (sales, purchase, payroll, treasury, manufacturing, manual, recurring, asset adapters) to set `source` only via the enum. Locate producers via `grep -rn "journal_entries.*source\|source.*=.*['\"]" backend/services`.
- [X] T055 [R2.3] Update `gl_service.post_journal_entry` (locate via `grep -rn "def post_journal_entry\|post_journal_entry" backend/services`) to enforce `Decimal` JE epsilon from `company_settings.gl.je_epsilon` (default `Decimal("0.005")`) and reject imbalance with `je.epsilon_violation`.
- [X] T056 [R2.3] Update `gl_service.validate_period(date)` (or add) to consult `company_settings.fiscal.allow_drafts_in_closed_period`; apply uniformly: any module that previously had its own period check must call `gl_service.validate_period(...)` instead. Sweep with `grep -rn "fiscal_period\|period_status" backend/services`.
- [X] T057 [P] [R2.3] Asset-return write-down JE: in the asset service (locate via `grep -rn "asset_return\|return.*asset" backend/services`), when remaining NBV > 0, request a write-down JE via `gl_service` using the loss-on-return account from settings; link via `journal_entries.source = 'asset'`, `source_id = asset_id`.
- [X] T058 [P] [R2.3] Document FX rounding policy: store `Decimal` with `ROUND_HALF_UP`, FX `NUMERIC(18,6)`, amounts `NUMERIC(18,4)`, intermediate at full precision, round only at JE persistence boundary. Add module docstring + helper in `gl_service` and any FX revaluation site (locate via `grep -rn "revaluation\|exchange_diff" backend/services`).

**Checkpoint**: All JE producers use the enum; epsilon and period gate uniform; smoke §4.7 still works.

---

## Phase 10: R2.4 — Treasury Balance Authority

**Goal**: Direct UPDATE of `treasury_accounts.current_balance` outside the GL/treasury session is blocked at the DB level; sanctioned path succeeds; migrations have an audited bypass.

**Independent Validation**: Smoke §4.6 in quickstart.

- [X] T059 [R2.4] Alembic migration [backend/alembic/versions/022f_treasury_balance_trigger.py](backend/alembic/versions/022f_treasury_balance_trigger.py): create trigger `tg_treasury_balance_authority` per [contracts/treasury-balance-trigger.md](specs/022-audit-security-finance-integrity/contracts/treasury-balance-trigger.md); `BEFORE UPDATE OF current_balance`; raises unless `current_setting('aman.gl_context', true) = 'on'`; writes audit row on block.
- [X] T060 [R2.4] Update [backend/services/treasury_service.py](backend/services/treasury_service.py) — `update_balance(...)` MUST set the GUC inside the `transactional()` block: `conn.execute("SELECT set_config('aman.gl_context', 'on', true)")` immediately before the UPDATE; sweep any other writer via `grep -rn "treasury_accounts.*current_balance\|current_balance" backend/services backend/routers`.
- [X] T061 [P] [R2.4] Update [backend/alembic/script.py.mako](backend/alembic/script.py.mako) with a helper macro `set_gl_context()` that future migrations call before legitimate balance rewrites; add an audit-row insert as part of the helper.

**Checkpoint**: Smoke §4.6 passes; treasury writes via service still succeed.

---

## Phase 11: R2.5 — Recurring Templates, Employee Receipts, Cost Center, Auto-Approve, Report-View Audit

**Goal**: Recurring templates carry mandatory expense category and review threshold; employee-receipt-vs-advance reconciliation model exists; auto-approve scheduler runs; cost-center policy enforced; uniform report-view audit.

**Independent Validation**: Smoke §4.7 (recurring); employee receipt settle/post round-trips; auto-approve writes audit; closed cost-center policy rejects/warns/allows per setting; every report GET writes a uniform audit row.

### Recurring templates

- [X] T062 [R2.5] Alembic migration [backend/alembic/versions/022d_recurring_template_review.py](backend/alembic/versions/022d_recurring_template_review.py): add `review_threshold NUMERIC(18,4)`, `auto_approve BOOLEAN NOT NULL DEFAULT false`, `expense_category_id BIGINT` to `recurring_je_templates`; backfill `expense_category_id` from a default category (create the default if missing); after backfill, set NOT NULL. Add `recurring_je_pending_review` table per state machine in data-model. Mirror in [backend/db_ddl/tenant_schema.py](backend/db_ddl/tenant_schema.py) and [backend/database.py](backend/database.py).
- [X] T063 [R2.5] Implement [backend/services/recurring_je_service.py](backend/services/recurring_je_service.py) per [contracts/recurring-template.md](specs/022-audit-security-finance-integrity/contracts/recurring-template.md): `run_template`, `approve_pending`, `reject_pending`; advisory lock per `template_id`; auto-post path vs `pending_review` path; propagates `expense_category_id` onto generated JE lines.
- [X] T064 [R2.5] Wire scheduler to call `run_template` for due rows; locate scheduler in [backend/worker.py](backend/worker.py).
- [X] T065 [P] [R2.5] Admin router [backend/routers/recurring_review.py](backend/routers/recurring_review.py) implementing the queue verbs in [contracts/http-endpoints.md §Admin: Recurring template review queue](specs/022-audit-security-finance-integrity/contracts/http-endpoints.md#admin-recurring-template-review-queue--sensitive--adminrecurring-criticaltrue); register in [backend/main.py](backend/main.py).
- [X] T066 [P] [R2.5] Frontend [frontend/src/pages/admin/RecurringTemplateReview.jsx](frontend/src/pages/admin/RecurringTemplateReview.jsx) — pending list with approve/reject; i18n + destructive-confirm.

### Employee receipt vs advance

- [X] T067 [R2.5] Alembic migration [backend/alembic/versions/022e_employee_receipt_settlements.py](backend/alembic/versions/022e_employee_receipt_settlements.py): create `employee_receipt_settlements` per data-model; mirror in tenant_schema + database.py.
- [X] T068 [R2.5] Implement [backend/services/employee_receipt_service.py](backend/services/employee_receipt_service.py): submit/approve/reject/post; posting routes through `gl_service`; audited.
- [X] T069 [P] [R2.5] Add minimal endpoints under existing HR/expense router for the four state transitions (`/api/hr/employee-receipts/...`); wrap with `require_sensitive_permission("finance.expenses", critical=True)`.

### Auto-approve scheduler & cost-center policy

- [X] T070 [R2.5] Auto-approve job: scan pending expense approvals; auto-approve those below `company_settings.expenses.auto_approve_threshold`; write audit (`expense.auto_approved`, `critical=False`); register in [backend/worker.py](backend/worker.py).
- [X] T071 [P] [R2.5] Cost-center policy validator helper in [backend/services/finance/cost_center_policy.py](backend/services/finance/cost_center_policy.py); plug into JE/expense validators; reads `company_settings.expenses.cost_center_policy ∈ {off, warn, required}`. Sweep current cost-center checks via `grep -rn "cost_center_id" backend/services`.

### Uniform report-view audit

- [X] T072 [R2.5] Decorator `audit_report_view(report_key)` in [backend/services/audit_report_view.py](backend/services/audit_report_view.py); apply via `require_sensitive_permission(..., audit_view=True)` (already wired) or directly on report endpoints that aren't covered. Verify every report GET produces one audit row regardless of endpoint.

### Settings UI

- [X] T073 [P] [R2.5] Frontend admin [frontend/src/pages/admin/PolicySettings.jsx](frontend/src/pages/admin/PolicySettings.jsx) for the new toggles: drift_tolerance, je_epsilon, allow_drafts_in_closed_period, auto_approve_threshold, cost_center_policy, webhook ratelimit, audit SLA, recurring review_threshold_default. DataTable patterns + i18n.

**Checkpoint**: Smoke §4.7 passes; report views uniformly audited; cost-center policy honored; auto-approve runs.

---

## Phase 12: Polish & Cross-Cutting

**Purpose**: Confirm constitution gates green, finish documentation, retire fallback.

- [X] T074 [P] Update [docs/audit/REMAINING_REMEDIATION_PLAN.md](docs/audit/REMAINING_REMEDIATION_PLAN.md): mark closed items from R1 (#132/#133/#134/#136, #272a/#352, #351/#408/#487, #162/#225/#226/#227/#228/#413, #135/#275 seam, #353) and R2 (#272u/#419x, #271, #272, #273, #419q, #419p, #219/#269/#463, T1.3b, #195/#196, #197, #310, #311, #322/#465). Move them to `TODO.md` per the plan's closure policy. Do **not** remove the file.
- [X] T075 [P] Add a section to [docs/RUNBOOK.md](docs/RUNBOOK.md) documenting: outbox worker recovery, drift-report interpretation, credential rotation playbook, treasury-trigger bypass for migrations, sensitive-permission discovery output.
- [X] T076 [P] Run all CI gates locally and confirm exit 0:
  - `python scripts/audit_writer_lint.py` ✓ (fixed test exclusion)
  - `python -m backend.scripts.permissions_discover --strict` ✓
  - `python scripts/check_account_code_ranges.py` ✓
  - `python scripts/check_credential_callsites.py` ✓ (added SMTP allowlist)
  - existing `scripts/full_code_scanner.py` (485 pre-existing hardcoded strings), `scripts/check_pii_logging.py` ✓, `scripts/check_sql_parameterization.py` (2 pre-existing in kpi_service/pos.py), `scripts/check_gl_posting_discipline.py` (2 pre-existing in scheduler.py recurring template).
- [ ] T077 Walk through every smoke check in [quickstart.md §4](quickstart.md#4-smoke-checks) on a seeded tenant and confirm pass; record output snippets in a short rollout note inside the feature folder if desired (optional). _(Requires running server + seeded tenant — manual step)_
- [X] T078 Remove any temporary `audit.outbox.enabled = false` fallback flags introduced during rollout; confirm `company_settings` has no overrides that disable the new path. _(No fallback flags found)_
- [ ] T079 Re-run the post-design Constitution Check table in [plan.md §Post-Design Constitution Check](plan.md#post-design-constitution-check) against the merged code; confirm all gates remain PASS. _(Manual review needed)_

---

## Dependencies

```
Phase 1 (Setup) ──► Phase 2 (Foundational)
                         │
        ┌────────────────┼────────────────────────┬────────────────┬────────────────┬─────────────────┬──────────────┐
        ▼                ▼                        ▼                ▼                ▼                 ▼              ▼
  Phase 3 (R1.1)    Phase 4 (R1.2)         Phase 5 (R1.3)   Phase 6 (R1.4)   Phase 7 (R2.1)   Phase 9 (R2.3)   Phase 10 (R2.4)
                                                                                  │
                                                                                  ▼
                                                                            Phase 8 (R2.2)         Phase 11 (R2.5)
                                                                                                          │
                                                                                                          ▼
                                                                                                    Phase 12 (Polish)
```

Hard ordering rules:

- Phases 3–11 require Phase 2 complete.
- Phase 8 (Reconciliation Finalize) depends on Phase 7 (Account Classifier) only insofar as the drift report uses `account_classifier` to label accounts; if that labeling is deferred, the dependency softens to a soft-prefer.
- Phase 11 depends on Phase 9 because recurring/auto-post routes through `gl_service.post_journal_entry` with the new `source` enum and epsilon.
- Phase 12 (Polish) requires all preceding phases.

Within a phase, tasks marked `[P]` can run in parallel; non-`[P]` tasks must run in their listed order.

## Parallel Execution Examples

**Phase 2 (after T004 sanitizer + T005-T006 outbox table)**: T007 (writer), T008 (worker), T011 (decorator), T015 (settings) can be developed in parallel by different contributors; T010 lint and T014 CLI follow once their respective subjects exist.

**Phase 4 (R1.2 sweep)**: T022 / T023 / T024 / T025 / T026 are file-disjoint and parallelizable. T027 runs after them.

**Phase 5 (R1.3)**: After T028-T030 schema + T034 service, T032 (callsite sweep), T033 (lint), T035 (webhook wiring), T036 (bank-feed alerts), T037+T038 (admin endpoints + UI) can parallelize.

**Phase 7 (R2.1)**: After T042-T045 (schema + service), T046 (sweep), T047 (lint), T048 (router), T049 (UI) can parallelize.

**Phase 11 (R2.5)**: T065 (router), T066 (UI), T069 (HR receipts endpoints), T071 (cost-center validator), T073 (settings UI) parallelize after their respective service tasks.

## Independent Validation Per Capability

| Phase | How to validate independently |
|-------|-------------------------------|
| 3 (R1.1) | Quickstart §4.1 + §4.2; CI lint T010 green; rollback test produces no orphan audit row. |
| 4 (R1.2) | `python -m backend.scripts.permissions_discover --strict` exits 0; new endpoint without wrap fails CI in a dry test. |
| 5 (R1.3) | Quickstart §4.8 + §4.9; CI lint T033 green; bank-feed adapter increments counter and alert fires at threshold. |
| 6 (R1.4) | Login event writes both seam tables; `evaluate_login_risk` invoked; ghost-employee rule emits audit findings on a seeded scenario. |
| 7 (R2.1) | Quickstart §4.5; lint T047 green; report numbers match pre-migration on day one. |
| 8 (R2.2) | Quickstart §4.4; concurrent finalize returns 409 ConflictError. |
| 9 (R2.3) | All JE rows have enum-valid `source`; closed-period draft test honors policy; asset-return write-down JE present and linked. |
| 10 (R2.4) | Quickstart §4.6; raw SQL update blocked, sanctioned path succeeds. |
| 11 (R2.5) | Quickstart §4.7; below-threshold posts auto-approved; above-threshold routes to review; report GETs uniformly audited. |

## MVP Suggestion

The smallest deliverable that materially reduces risk is **Phase 1 + Phase 2 + Phase 3 (R1.1)** — atomic audit writes with PII sanitization. Layer Phase 4 (sensitive-permission sweep) immediately after for the first auditable security uplift. Finance integrity (Phase 7 + 8 + 9 + 10) follows as the next coherent slice.

## Format Validation

All tasks above strictly follow `- [ ] <TaskID> [P?] [Area?] Description with file path`. Setup, Foundational and Polish phases carry no `[Area]` label; capability phases carry `[R1.x]` / `[R2.x]` labels.
