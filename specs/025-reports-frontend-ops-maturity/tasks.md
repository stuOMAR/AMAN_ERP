# Tasks: Reports + Frontend/Ops Maturity (R7 + R8)

**Feature**: `025-reports-frontend-ops-maturity`
**Branch**: `025-reports-frontend-ops-maturity`
**Inputs consumed**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: NOT generated. Per the constitution (Workflow rule 6) and the user's standing operating instruction, tests are optional unless explicitly requested. None requested for this feature. CI gates run only existing tests.

**Organization**: Tasks are grouped by requirement/capability. No user stories exist. Each capability is independently verifiable per the criteria in `spec.md` and the quickstart.

**Format**: `- [ ] [TaskID] [P?] [Area] Description with file path`

- `[P]` — Parallelizable (different files, no incomplete dependency).
- `[Area]` — `[FR-xxx]` requirement label, or `[Setup]` / `[Foundational]` / `[Polish]`.

**Consumed contracts** (do NOT reimplement):
- `account_classifications`, `require_sensitive_permission`, secret vault, audit outbox, JESource enum (feature 022).
- Order→Invoice service, unified webhooks dispatcher (feature 023).
- Unified notifications dispatcher, `email_templates`, signed approval-action tokens (feature 024).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Repository / tooling preparation. No business logic yet.

- [x] T001 [Setup] Confirm branch `025-reports-frontend-ops-maturity` is checked out and clean; resolve any rebase against `main` that affects features 022/023/024 contracts.
- [x] T002 [Setup] Run the router-churn discovery query and write the top-10 list to `docs/refactor-target-routers.md`: `git log --since="90 days ago" --pretty=format: --name-only -- backend/routers/ | sort | uniq -c | sort -rn | head -10`.
- [x] T003 [Setup] Add bundle-budget baseline by running `cd frontend && npm run build` once, then create `frontend/vite-bundle-budget.json` with the measured initial-route bundle size + 5% headroom.
- [x] T004 [Setup] [P] Create `docs/perf/index-baselines.md` skeleton listing the queries that will be re-EXPLAINed before/after R7 indexes (income statement, trial balance, journal/account/date, inventory item activity).
- [x] T005 [Setup] [P] Add new settings keys (with defaults) to the canonical settings registry in `backend/services/settings/registry.py` per [data-model.md](data-model.md) §F.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Cross-cutting infrastructure every capability depends on.

**CRITICAL**: No capability phase begins until this phase is complete.

- [x] T010 [Foundational] Add CI scripts that capabilities will rely on as gates (skeletons + zero-violation pass on current `main`):
  - [x] T010a [Foundational] [P] `scripts/check_cache_keys.py` — fails on any cache key without a `tenant_id` segment.
  - [x] T010b [Foundational] [P] `scripts/check_schema_sync.py` — diffs Alembic head vs `backend/db_ddl/` canonical modules.
  - [x] T010c [Foundational] [P] `scripts/check_frontend_number_format.py` — fails on `.toFixed(`, `parseFloat(` outside `frontend/src/utils/format.js`.
  - [x] T010d [Foundational] [P] `scripts/check_frontend_window_location.py` — fails on `window.location` outside the documented allow-list.
  - [x] T010e [Foundational] [P] `scripts/check_frontend_i18n_strings.py` — fails on hard-coded user-visible strings (extends existing `hardcoded_strings.json` baseline).
- [x] T011 [Foundational] Add `.github/workflows/ci.yml` gate matrix wiring per research §21 (lint, type, unit, contract, migrations dry-run, OpenAPI coverage, all `scripts/check_*.py`, frontend bundle budget). All gates required on PR-to-`main`.
- [x] T012 [Foundational] Add `break_glass_audit_log` migration in `backend/alembic/versions/` and the canonical DDL in `backend/db_ddl/break_glass_audit_log.py`. Document the break-glass merge SOP in `docs/RUNBOOK.md`.
- [x] T013 [Foundational] Implement the cache observability middleware framework in `backend/middleware/cache_observability.py` exposing `@cache_observable(report_code, ttl_setting)` decorator and the `X-Cache-Hit` / `X-Cache-TTL` headers. No endpoint adoption yet; that happens per capability.
- [x] T014 [Foundational] Implement the cache invalidation registry in `backend/services/cache/invalidation.py`: `register(domain_event, [key_prefix, ...])`, `evict(domain_event)`, plus emission helpers `emit_coa_changed()`, `emit_role_dashboard_changed()`, `emit_je_posted()`. Wire `services/accounts/*` writers and `services/dashboards/*` writers to call the emitters; remove the existing mass-evict calls flagged in research §3.
- [x] T015 [Foundational] Implement the Redis circuit breaker + outage policy in `backend/services/cache/client.py`: read `cache.backend`, `cache.circuit_breaker.failures`, `cache.circuit_breaker.cool_down_seconds`; raise structured `CacheUnavailable` (-> HTTP 503 `cache.unavailable`) on cache-required endpoints; emit a startup audit event if `cache.backend=memory` is detected in production.
- [x] T016 [Foundational] Implement the scheduler idempotency layer in `backend/services/scheduler/idempotency.py` using `scheduled_job_runs` UNIQUE `(job_id, scheduled_for, attempt)`. Add migration + DDL for `scheduled_job_runs`. Provide a context manager `with idempotent_run(job_id, scheduled_for): ...` to wrap critical jobs (closing payroll, FX import, ZATCA submit, backups).

**Checkpoint**: Foundational layer ready — capability phases can begin in parallel.

---

## Phase 3: Capability 1 — Reports Cache + MVs + Indexes (FR-200, FR-201, FR-202, FR-203)

**Goal**: Reports return from MVs and namespaced cache; cache-required endpoints fail loudly on Redis outage; on-demand refresh + warm-up are operator-controllable; query plans drop ≥ 50% buffer reads on the journal/account/date report.

**Independent Validation**: Quickstart §4 "Reports correctness", "MV-backed period stats", "Cache observability + outage policy", "Index baselines".

- [x] T100 [FR-200] Migration in `backend/alembic/versions/` creating MVs `mv_daily_financial_chart` and `mv_period_stats` per [data-model.md](data-model.md) §A; canonical DDL in `backend/db_ddl/reports_mvs.py`.
- [x] T101 [FR-200] [P] Migration adding BRIN indexes `audit_logs(created_at)`, `journal_lines(posting_date)`, `inventory_transactions(transaction_date)` using `CREATE INDEX CONCURRENTLY`; canonical DDL updates in the corresponding `backend/db_ddl/*.py` modules.
- [x] T102 [FR-200] [P] Migration adding composite indexes `journal_lines(tenant_id, account_id, posting_date)`, `journal_entries(tenant_id, source, source_id)`, `inventory_transactions(tenant_id, item_id, transaction_date)`; canonical DDL updates.
- [x] T103 [FR-200] [P] Add APScheduler job `reports_mv_refresh` (interval = `reports.mv.refresh_interval_minutes`) in `backend/services/reports/mv_refresh.py` running `REFRESH MATERIALIZED VIEW CONCURRENTLY`; wraps with `idempotent_run`.
- [x] T104 [FR-200] Refactor `backend/services/reports/period_stats.py` (formerly `calculate_period_stats`) to read from `mv_period_stats` first, with a documented live-compute fallback for newly-created periods that triggers an async refresh.
- [x] T105 [FR-201] Implement `POST /reports/cache/refresh` per [contracts/reports-cache.yaml](contracts/reports-cache.yaml) in `backend/routers/reports.py`; gated by `require_sensitive_permission('reports.cache.refresh')`; supports `scope=all|mv_only|warmup_only` and `report_codes`.
- [x] T106 [FR-201] [P] Implement cache warm-up at startup in `backend/services/cache/warmup.py` reading `reports.warmup_keys` and pre-populating; bounded by per-key timeout.
- [x] T107 [FR-202] Adopt `@cache_observable` (T013) on every cache-bearing report endpoint in `backend/routers/reports.py` and `backend/routers/dashboards.py`; verify headers via `quickstart.md` §4.
- [x] T108 [FR-202] [P] Replace ad-hoc cache key construction across `backend/services/reports/*.py` and `backend/services/dashboards/*.py` with the namespaced builder in `backend/services/cache/keys.py` (`report_key(...)`, `dashboard_key(...)`); ensure linter T010a passes.
- [x] T109 [FR-203] Refactor balance-sheet sign logic in `backend/services/reports/balance_sheet.py` and trial-balance + income-statement sign logic in their respective service modules to consume `account_classifications` (feature 022). Remove all account-code range branching.
- [x] T110 [FR-203] [P] Income statement: include header rows (`is_header=true`) per `reports.income_statement.include_headers` setting, in `backend/services/reports/income_statement.py`.
- [x] T111 [FR-203] [P] Trial balance: apply `reports.trial_balance.tolerance` and report `total_drift` in payload, in `backend/services/reports/trial_balance.py`.
- [x] T112 [FR-203] [P] Trial balance: fix opening-balance distribution for accounts with reverse-sign behaviour, in the same module; verify against the audit case in `docs/audit/REMAINING_REMEDIATION_PLAN.md` #272z.
- [x] T113 [FR-203] [P] Remove type coercion in rollup helpers in `backend/services/reports/rollup.py`; ensure all monetary values are `Decimal`.
- [x] T114 [FR-200] Run EXPLAIN (BUFFERS) before/after on the queries listed in `docs/perf/index-baselines.md`; record results; the journal/account/date report MUST drop ≥ 50% buffer reads.

**Capability 1 Checkpoint**: Quickstart §4 "Reports correctness", "Cache observability + outage policy", "Index baselines" pass.

---

## Phase 4: Capability 2 — KPI Alerts + Reactive Dashboards (FR-204, FR-205)

**Goal**: KPI breaches notify via the unified dispatcher; dashboard widgets refetch on invalidation events without polling.

**Independent Validation**: Quickstart §4 "KPI alert end-to-end" and dashboard auto-refresh observed when a JE posts.

- [x] T120 [FR-204] Migration + canonical DDL for `kpi_definitions` and `kpi_evaluations` per [data-model.md](data-model.md) §B.
- [x] T121 [FR-204] CRUD endpoints per [contracts/kpi-admin.yaml](contracts/kpi-admin.yaml) in `backend/routers/kpi.py`; gated by `require_sensitive_permission('kpi.admin')`.
- [x] T122 [FR-204] [P] KPI evaluator job in `backend/services/kpi/evaluator.py` running every `reports.kpi.evaluation_interval_minutes`; supports `metric_source ∈ {report_key, classifier_category}`; idempotent on `(kpi_id, evaluation_window_start)` via `idempotent_run`.
- [x] T123 [FR-204] Dispatch breached evaluations through the feature 024 unified notifications dispatcher (channels from `kpi_definitions.channels`); set `kpi_evaluations.notified_at` after dispatch.
- [x] T124 [FR-204] [P] Frontend KPI admin page in `frontend/src/pages/Reports/KpiAdmin.jsx` consuming the contract.
- [x] T125 [FR-205] Backend WS channel `dashboard:{tenant}:{role}` in `backend/services/dashboards/realtime.py`; emit `{widget_keys: [...]}` invalidation events from the cache invalidation registry (T014) for `je_posted`, `invoice_posted`, `payroll_closed`, `inventory_changed`.
- [x] T126 [FR-205] [P] Frontend hook `frontend/src/hooks/useDashboardChannel.js` subscribing to the WS channel and triggering `useApi.refetch()` on matching `widget_keys`; wire into existing dashboard widgets in `frontend/src/pages/Dashboard/`.
- [x] T127 [FR-205] [P] KPI dashboard widget reads `account_type` sign from `account_classifications` in `frontend/src/pages/Dashboard/widgets/KpiCards.jsx`.

**Capability 2 Checkpoint**: A KPI breach triggers a notification within one cycle; dashboard widget refetches when a JE is posted.

---

## Phase 5: Capability 3 — GlobalSearch UI + Registry + Logs (FR-206, FR-207)

**Goal**: Cross-entity search powered by a backend-served registry; observable via `search_query_logs`.

**Independent Validation**: Quickstart §4 "GlobalSearch UI wiring".

- [x] T140 [FR-206] Migration + canonical DDL for `search_query_logs` per [data-model.md](data-model.md) §B.
- [x] T141 [FR-206] Implement `GET /search/registry` per [contracts/search-registry.yaml](contracts/search-registry.yaml) in `backend/routers/search.py`; registry source = `backend/services/search/registry.py` (data-driven list with per-entity `permissions_required`).
- [x] T142 [FR-206] [P] Add `search_query_logs` writer in `backend/services/search/logging.py` invoked by the existing `GET /search` endpoint with `tenant_id`, `actor_id`, `query`, `result_count`, `latency_ms`, `entity_hits`. Add a cleanup scheduler honoring `search.query_logs_retention_days`.
- [x] T143 [FR-207] Replace the static frontend search registry with a fetch from `/search/registry` on app boot in `frontend/src/services/searchRegistry.js`; cache in localStorage with version key.
- [x] T144 [FR-207] [P] Refactor `frontend/src/components/GlobalSearch/GlobalSearch.jsx` to: debounce input by `search.autocomplete_debounce_ms` (default 300ms) using `useDebounce`; cancel in-flight requests on input change; render results via the registry; navigate using `useNavigate` and the `route_template` (no `window.location`).
- [x] T145 [FR-207] [P] Replace any remaining hard-coded "GlobalSearch page metadata" lists across `frontend/src/pages/**` with a registry consumer hook `useSearchRegistry()`.

**Capability 3 Checkpoint**: Typing in GlobalSearch produces results across entities; `search_query_logs` row written; click navigates without reload.

---

## Phase 6: Capability 4 — Audit Partitioning + Retention (FR-208)

**Goal**: `audit_logs` is monthly-partitioned with retention `audit.retention_months`; the system never blocks a write at month boundary.

**Independent Validation**: Quickstart §4 "audit_logs partitioning".

- [x] T160 [FR-208] Migration in `backend/alembic/versions/` and canonical DDL in `backend/db_ddl/audit_logs.py` to partition `audit_logs` by RANGE on `created_at` per [data-model.md](data-model.md) §C: rename existing table → `audit_logs_legacy_<yyyymm>`, create new partitioned `audit_logs`, ATTACH legacy as historical partition, CREATE current + next month partitions, recreate per-partition indexes.
- [x] T161 [FR-208] [P] Per-partition index creation helper in `backend/services/ops/audit_partitions.py` (BRIN on `created_at`, BTREE on `(tenant_id, actor_id, created_at)`).
- [x] T162 [FR-208] APScheduler job `audit_partition_maintenance` (monthly) in the same module: pre-creates next-next month partition, DETACHes + DROPs partitions older than `audit.retention_months` with a refusal floor (do not drop if remaining count < retention window).
- [x] T163 [FR-208] [P] Document the rollback path (re-attach legacy + read-from-legacy) in `docs/partitioning-plan.md`.

**Capability 4 Checkpoint**: Partition list shows current + next month; maintenance job runs idempotently; legacy partition still queryable.

---

## Phase 7: Capability 5 — Health/Detailed + Adapter Contract (FR-209)

**Goal**: One uniform health surface for every adapter, suitable for monitoring and runbook.

**Independent Validation**: Quickstart §4 "/health/detailed".

- [x] T170 [FR-209] Define the adapter health contract in `backend/services/health/adapter.py`: `health_check() -> {status, latency_ms, last_success_at, last_error}`.
- [x] T171 [FR-209] [P] Implement adapter health for each existing adapter: `db`, `redis`, `worker`, `zatca`, `notifications`, `dms`, `clamav`, `fx`, `search` — each in its own service module under `backend/services/<adapter>/health.py`.
- [x] T172 [FR-209] Implement `GET /health/detailed` per [contracts/health-detailed.yaml](contracts/health-detailed.yaml) in `backend/routers/health.py`; aggregate adapters; map critical adapters (`db`, `redis`, `worker`) to overall `down` per research §22.

**Capability 5 Checkpoint**: `/health/detailed` returns the documented schema with one entry per adapter; flipping a non-critical adapter to `down` yields aggregate `degraded`.

---

## Phase 8: Capability 6 — Frontend Utility Sweeps + Locale Defaults (FR-300 .. FR-308)

**Goal**: One way to format numbers, navigate, debounce, fetch, and pick locale defaults — frontend-wide.

**Independent Validation**: Quickstart §5 "Frontend sweeps (CI gates)" all green; gate-violation PRs (Quickstart §5 last subsection) all fail CI.

- [x] T200 [FR-300] Create / canonicalize `frontend/src/utils/format.js` exporting `formatNumber(value, {locale, fractionDigits})`, `formatCurrency`, `formatDate`. Sweep `frontend/src/**/*.{js,jsx}` replacing `.toFixed(N)` and `parseFloat(...)` call sites with `formatNumber` (display) and `Number()` / `Decimal` paths (parsing). The CI gate T010c MUST pass post-sweep.
- [x] T201 [FR-301] Implement `GET /locale/defaults` per [contracts/locale-defaults.yaml](contracts/locale-defaults.yaml) in `backend/routers/locale.py`; data source = country / tenant defaults table consumed from feature 022's settings.
- [x] T202 [FR-301] [P] Wire Register / Onboarding / Branches screens (`frontend/src/pages/Auth/Register.jsx`, `frontend/src/pages/Onboarding/*`, `frontend/src/pages/Branches/*`) to `/locale/defaults` instead of hard-coded values.
- [x] T203 [FR-302] Implement `frontend/src/hooks/useExchangeRate.js` per research §12; reads `fx.cache_ttl_minutes` and `fx.stale_tolerance_minutes`; never returns `1.0` placeholder; surfaces `fx_stale=true` after tolerance.
- [x] T204 [FR-302] [P] Sweep `frontend/src/**/*.{js,jsx}` replacing `exchange_rate: 1.0` and ad-hoc rate fetches with `useExchangeRate(currency_code)`.
- [x] T205 [FR-303] Sweep `frontend/src/**/*.{js,jsx}` replacing `window.location.href = ...` and `window.location.assign(...)` with `useNavigate()` from React Router; document the allow-list of legitimate cases (full reload after logout, OAuth redirect) in `frontend/src/utils/navigation-allowlist.md`. CI gate T010d MUST pass post-sweep.
- [x] T206 [FR-304] Implement `frontend/src/hooks/useDebounce.js`; replace ad-hoc setTimeout debouncing in `GlobalSearch`, list filter inputs, and any reachable form filter input across `frontend/src/pages/**`.
- [x] T207 [FR-305] Implement the central error handler in `frontend/src/services/apiClient.js`: map backend `error.code` to i18n keys via `frontend/src/i18n/error-codes.js`; surface a toast and bubble a typed error to callers; replace silent `.catch()` blocks across the codebase.
- [x] T208 [FR-306] Implement `frontend/src/hooks/useApi.js` per research §13: returns `{data, loading, error, refetch, abort}`; aborts on unmount and on `deps` change.
- [x] T209 [FR-306] [P] Migrate the 10 highest-traffic pages (driven by analytics or, in their absence, the page list in `docs/refactor-target-routers.md` mapped to their frontend routes) from `fetchData/setLoading` to `useApi`. List the migrated files in the PR description for trace.
- [x] T210 [FR-307] Add i18n keys (en + ar) for every backend `error.code` in `frontend/src/i18n/error-codes.js` and matching translation files; CI gate T010e MUST pass.
- [x] T211 [FR-308] [P] Sweep remaining hard-coded user-visible strings flagged in `hardcoded_strings.json` and `keys_to_translate.json`; remove the entries once translated.

**Capability 6 Checkpoint**: All five gates (T010a–T010e + bundle budget) green.

---

## Phase 9: Capability 7 — Frontend UX / Performance (FR-309 .. FR-318)

**Goal**: Lower bundle, accessible primitives, route-preserving error boundary, mobile-friendly tables, semantic forms, StrictMode-clean.

**Independent Validation**: Bundle budget gate green; visual smoke per `quickstart.md` §5.

- [x] T230 [FR-309] Add Vite config in `frontend/vite.config.js` for route-level dynamic imports + per-route CSS chunks. Verify chunks land per route via `npm run build && ls dist/assets`.
- [x] T231 [FR-309] [P] Convert heavy components in `frontend/src/pages/**` (charts, dashboards, large forms) to `React.lazy` + `Suspense` with skeleton fallbacks.
- [x] T232 [FR-310] Break barrel exports in `frontend/src/**/index.js` that re-export entire trees; replace with explicit named exports to restore tree-shaking.
- [x] T233 [FR-311] [P] Add `:focus-visible` ring styles to design-system primitives in `frontend/src/components/ui/**/*.{css,jsx}` (Button, Input, Select, Tab, Link).
- [x] T234 [FR-312] [P] Sweep image and icon usages in `frontend/src/**` adding meaningful `alt` (or empty for decorative) and `aria-label` where appropriate.
- [x] T235 [FR-313] Convert remaining ad-hoc form layouts in `frontend/src/pages/**` to semantic `<form>` + `<label htmlFor>` + `<fieldset>` per `frontend/src/components/Form/README.md`.
- [x] T236 [FR-314] Mobile-table strategy in `frontend/src/components/DataTable/MobileLayout.jsx`: collapses to card-list under `md` breakpoint; opt-in via prop. Apply to the 5 most-used tables.
- [x] T237 [FR-315] Refactor `frontend/src/components/ErrorBoundary.jsx` to use `useNavigate`, store `location.state.from = previousSafeRoute`, and "Try again" navigates back; fallback to role's home from `/me` if no safe route.
- [x] T238 [FR-316] [P] Move thermal printer styles into print media in `frontend/src/styles/print/thermal.css` and gate via `@media print and (max-width: 80mm)`.
- [x] T239 [FR-317] Re-enable React StrictMode in stages: build flag `STRICT_MODE_PARTIAL` in `frontend/src/main.jsx`; per-route allow-list in `frontend/src/router/strictModeRoutes.js`. Resolve double-effect warnings until empty, then remove the flag and wrap the entire app.
- [x] T240 [FR-318] [P] Translate remaining Arabic-only error messages flagged by T010e into both languages.

**Capability 7 Checkpoint**: Bundle budget green; StrictMode warning catalogue empty; ErrorBoundary preserves route on retry.

---

## Phase 10: Capability 8 — Scheduler Reliability + Monitoring (FR-319 .. FR-322)

**Goal**: Critical scheduled jobs are idempotent; operators see status and can trigger; misfires are bounded.

**Independent Validation**: Quickstart §5 "Scheduler monitoring UI", "Idempotency clash".

- [x] T260 [FR-319] Wrap critical jobs with `idempotent_run` (T016) in:
  - [x] T260a [FR-319] [P] Closing payroll job in `backend/services/payroll/closing_job.py`.
  - [x] T260b [FR-319] [P] FX import job in `backend/services/fx/import_job.py`.
  - [x] T260c [FR-319] [P] ZATCA submit job in `backend/services/zatca/submit_job.py`.
  - [x] T260d [FR-319] [P] Backup runner job (Phase 11 dependency).
  - [x] T260e [FR-319] [P] MV refresh job (T103) and KPI evaluator job (T122) — already covered, confirm wrapped.
- [x] T261 [FR-319] Review and adjust `misfire_grace_time` for long-running jobs in `backend/worker.py`; document the policy in `docs/RUNBOOK.md`.
- [x] T262 [FR-320] Apply company timezone to scheduled tasks where wall-clock matters (e.g., daily backups, monthly closes); helper `backend/services/scheduler/tz.py`.
- [x] T263 [FR-321] Implement `GET /ops/scheduler/jobs` and `POST /ops/scheduler/jobs/{job_id}/run-now` per [contracts/ops-scheduler.yaml](contracts/ops-scheduler.yaml) in `backend/routers/ops_scheduler.py`; gated by `require_sensitive_permission('ops.scheduler.admin')`; audited; `409` if a run for the same `(job_id, scheduled_for)` is already running.
- [x] T264 [FR-321] [P] Frontend page `frontend/src/pages/Ops/Scheduler.jsx` consuming `useApi`; auto-refresh every 30s; "Run now" button per row.
- [x] T265 [FR-322] [CLEANUP] Remove or merge the duplicate scheduled-reports table/router (audit ref #419b); document the chosen single path.

**Capability 8 Checkpoint**: Forced double-fire is absorbed (`idempotent_skip`); operator can list and trigger jobs.

---

## Phase 11: Capability 9 — Backup Automation + Restore + Party Phase 2 (FR-323, FR-324, FR-325)

**Goal**: Daily backups with offsite copy and retention floor; safe two-step restore; party model phase 2 transition online.

**Independent Validation**: Quickstart §5 "Backup automation", "Restore (dry-run + execute)", "Party phase 2 read parity".

- [x] T280 [FR-323] Migration + canonical DDL for `backup_runs` per [data-model.md](data-model.md) §B.
- [x] T281 [FR-323] Extend `scripts/backup_postgres.sh`: per-tenant `pg_dump`, checksum, upload to S3-compatible target (creds from feature 022 vault `ops.backup.s3.*`), record row in `backup_runs`, enforce `backup.retention_days` with `backup.min_retained` floor, dispatch success/failure via feature 024 dispatcher; dead-letter alert at `backup.max_consecutive_failures`.
- [x] T282 [FR-323] [P] Add `ops/systemd/aman-backup.service` and `ops/systemd/aman-backup.timer` (daily at `backup.local_time`); document install + uninstall in `docs/RUNBOOK.md`.
- [x] T283 [FR-323] [P] Add `ops/k8s/cronjob-backup.yaml` mirroring the systemd timer for k8s deployments.
- [x] T284 [FR-323] Wire the backup runner job into the scheduler with `idempotent_run` (T260d).
- [x] T285 [FR-324] Implement `GET /ops/backups`, `POST /ops/restore/dry-run`, `POST /ops/restore` per [contracts/ops-restore.yaml](contracts/ops-restore.yaml) in `backend/routers/ops_restore.py`; gated by `require_sensitive_permission('ops.restore')`; `confirm_token` is HMAC-signed via feature 022 vault keys (claims `action='ops.restore', backup_id, actor_id, exp`); every step audited.
- [x] T286 [FR-324] [P] Restore service in `backend/services/ops/restore.py`: validates checksum, computes `missing_tenants` / `extra_tenants` vs current inventory, executes restore on confirm; respects `include_new_tenants_empty`.
- [x] T287 [FR-325] Migration: extend `party_roles` with `customer | supplier | employee` rows where applicable; create read-only views `customers`, `suppliers`, `employees` over `parties` JOIN `party_roles` per [data-model.md](data-model.md) §E; canonical DDL in `backend/db_ddl/parties.py`.
- [x] T288 [FR-325] Service `backend/services/parties/unification_phase2.py` handling writes; legacy direct inserts gated by deprecation warning + audit until cutover. Document conflict resolution policy in `docs/party-unification.md`.
- [x] T289 [FR-325] [P] Audit + remove direct writes to legacy `customers` / `suppliers` / `employees` tables across `backend/routers/**` and `backend/services/**`; route through the unification service.

**Capability 9 Checkpoint**: A backup row appears with `succeeded` + `offsite_uri`; restore dry-run produces a confirm token; restore executes audited; legacy view counts match unified counts.

---

## Phase 12: Capability 10 — Architecture Refactor + CI Gates Hardening (FR-326, FR-327)

**Goal**: Top-churn routers move to service+repository+DTO pattern; CI catches regressions.

**Independent Validation**: Refactored routers contain no inline SQL; `scripts/check_sql_parameterization.py` passes on touched files; OpenAPI coverage 100% on touched routes.

- [x] T300 [FR-326] For each router in `docs/refactor-target-routers.md`:
  - [x] T300a [FR-326] [P] Extract a `services/<domain>.py` layer with input DTOs (in `backend/schemas/`) and output models.
  - [x] T300b [FR-326] [P] Extract a `repositories/<domain>.py` layer; all SQL is parameter-bound via SQLAlchemy text+params or ORM.
  - [x] T300c [FR-326] [P] Replace any `f"... {var} ..."` SQL with parameter-bound queries; extend `scripts/check_sql_parameterization.py` to cover the touched files.
  - [x] T300d [FR-326] [P] Add OpenAPI summaries / descriptions / response models on every endpoint; ensure `scripts/check_openapi_coverage.py` passes.
- [x] T301 [FR-326] [P] Replace duplicate `get_acc_id(code)` callsites with the central helper from feature 022 in `backend/services/accounts/lookup.py`.
- [x] T302 [FR-327] Confirm CI gate matrix (T011) is enforced on PR-to-`main` and that the break-glass merge SOP requires two reviewers + `break_glass_audit_log` row; verify on a test PR.
- [x] T303 [FR-327] [P] Ensure `scripts/check_schema_sync.py` (T010b) passes on `main` after every migration created in this feature.

**Capability 10 Checkpoint**: All target routers refactored; all CI gates green on `main`.

---

## Phase 13: Polish & Cross-Cutting Concerns

- [x] T400 [Polish] Update `backend/README.md` with the new modules, settings, and the report MV refresh / cache backend policy.
- [x] T401 [Polish] [P] Update `frontend/README.md` with the `useApi`, `useExchangeRate`, `useDebounce`, navigation, error-handler, format utility patterns and the bundle budget rule.
- [x] T402 [Polish] [P] Update `docs/RUNBOOK.md` sections: cache outage, MV refresh on demand, partition retention, scheduler force-run, backup install / failure handling, restore SOP, break-glass merge.
- [x] T403 [Polish] [P] Add a `docs/perf/index-baselines.md` "after" section with the post-T114 numbers.
- [x] T404 [Polish] Run quickstart end-to-end on a staging tenant; capture results in `docs/qa/025-quickstart-run.md`.
- [x] T405 [Polish] [P] Remove deprecated direct-write paths to legacy `customers` / `suppliers` / `employees` once the unification service is stable on staging (final cleanup of T289 leftovers).
- [x] T406 [Polish] Verify all CI gates green on a clean rebuild of `main` after merge.

---

## Dependencies

```text
Phase 1 (Setup)            ──▶  Phase 2 (Foundational)
Phase 2 (Foundational)     ──▶  Phase 3..12 (capabilities, parallel-safe between phases except Phase 11 backup runner depends on Phase 10 idempotency layer)
Phase 4 (KPI / Reactive)   ──▶  needs Phase 3 (cache invalidation registry already in Phase 2)
Phase 5 (GlobalSearch)     ──▶  needs Phase 8 (useDebounce, useApi) for frontend tasks; backend tasks independent
Phase 6 (Audit partition)  ──▶  independent of other capabilities
Phase 7 (Health)           ──▶  independent
Phase 8 (Frontend sweeps)  ──▶  prerequisites (no blocker), but Phase 9 UX uses utilities from Phase 8
Phase 9 (Frontend UX)      ──▶  depends on Phase 8 utilities
Phase 10 (Scheduler)       ──▶  needs T016 (foundational); Phase 11 backup wraps via T260d
Phase 11 (Backup/Restore/Party) ──▶  needs Phase 10 idempotency wrap and Phase 2 vault
Phase 12 (Refactor + CI)   ──▶  uses output of T002 router list; runs in parallel with capability work as files differ
Phase 13 (Polish)          ──▶  AFTER all capability checkpoints
```

## Parallel Execution Examples

- **Within Phase 3**: T101, T102, T103, T106, T108 can run in parallel (different files).
- **Within Phase 8**: T200, T203 (after sweep helpers), T205, T206, T207, T208 are independent file-set sweeps.
- **Within Phase 10**: T260a–T260e are independent (different job modules).
- **Across phases**: After Phase 2, a single team can run Capability 1 + Capability 5 (backend) + Capability 6 in parallel because they touch disjoint files.

## Implementation Strategy — MVP First

- **MVP scope (smallest shippable slice)**: Phase 1 + Phase 2 + Capability 1 (Phase 3) + Capability 4 (Phase 6) + Capability 5 (Phase 7).
  - Why: closes the highest-impact integrity gaps (cache outage policy, MV-backed reports, partitioned audit, unified health) without depending on frontend sweeps.
- **Increment 2**: Capability 2 (KPI + reactive) + Capability 3 (GlobalSearch + registry).
- **Increment 3**: Capability 6 (Frontend utility sweeps) + Capability 7 (Frontend UX).
- **Increment 4**: Capability 8 (Scheduler) + Capability 9 (Backup/Restore/Party phase 2).
- **Increment 5**: Capability 10 (Refactor + CI hardening).
- **Final**: Phase 13 polish.

## Format Validation

Every task above:

- starts with `- [ ]`,
- has a sequential `Tnnn` ID,
- carries a requirement label `[FR-xxx]` (or `[Setup]` / `[Foundational]` / `[Polish]` / `[CLEANUP]` for non-requirement scope),
- includes an exact file path or directory glob.

Test tasks are intentionally absent.
