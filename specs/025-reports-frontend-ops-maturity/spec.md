# Feature Specification: Reports/Search/Dashboard + Frontend/Architecture/Ops Maturity (R7 + R8)

**Feature Branch**: `025-reports-frontend-ops-maturity`
**Created**: 2026-05-02
**Status**: Draft
**Input**: User description: "do R7 — Reports/Search/Dashboard and R8 — Frontend/Architecture/Ops Cleanup on one speckit; the coder is cheaper than you, so spec everything well"

## Scope & Functional Flows *(mandatory)*

### Problem / Goal

Two adjacent maturity tracks remain open after batch B41 and after features 022 / 023 / 024:

- **R7 — Reporting / Search / Dashboard lane**: financial and operational reports still recompute heavy aggregates per request, period statistics are recomputed instead of reading from materialized views, the dashboard mixes static numbers with stale exchange rates, the Redis cache silently degrades to an in-process MemoryCache that diverges across workers, the cache layer has no hit/miss telemetry, large time-series tables (`audit_logs`, `journal_lines`, `inventory_transactions`) lack BRIN indexes / partitioning, the income statement and trial balance still mishandle header rows / opening balances / contra accounts, the KPI dashboard does not honour `account_type` sign rules, the GlobalSearch UI is not wired to the unified backend search, and OpenAPI descriptions / health-metrics adapters are still partial.
- **R8 — Frontend / Architecture / Ops lane**: the frontend still uses raw `fetchData/setLoading` patterns instead of a `useApi` hook, scattered `parseFloat` / `.toFixed(2)` / `exchange_rate: 1.0` instead of project formatters, `window.location` instead of router navigation, no `useDebounce`, no central error handler, missing `:focus-visible` rings, missing image alts, no `React.lazy` on heavy components, StrictMode disabled, mobile tables not responsive, ErrorBoundary loses route state, thermal-printer styles bleed into screen, partial i18n on error strings, partial Party-model unification phase 2, scheduled-job idempotency / monitoring UI / company-timezone handling, repeated f-string SQL in routers (DTO / service / repository pattern incomplete), and ops items (backup automation via systemd / k8s, restore playbook, supervisor / restart policy for the worker, CI/CD gates, scheduled-reports table dedup).

These two lanes are coupled: dashboard widgets depend on report MVs and on the frontend `useApi` migration; GlobalSearch UI depends on the backend unified-search endpoint plus a debounce hook plus router navigation; cache observability needs frontend cache headers and an admin monitoring screen; backup / restore automation needs both an ops playbook and a restore API. Shipping them as one coordinated change set avoids a third round-trip for cross-cutting plumbing (cache observability, account-type sign rules consumed by reports + dashboard, scheduled-job monitoring UI consumed by reports + ops).

The outcome must:

- Make **financial reports correct first, fast second**: header rows included where they belong, contra accounts reflected with proper sign, opening balances distributed correctly, trial-balance tolerance documented, balance-sheet sign logic refactored against `account_classifications` from feature 022.
- Make **dashboard / KPI numbers live**: widgets bound to reactive WebSocket events, `useExchangeRate` hook for live FX, KPI alerts wired to the scheduler + notification queue from feature 024.
- Make **reports affordable**: materialized views for daily financial charts, period-stats MV / cache warm-up, Redis-backed report cache with scoped invalidation, BRIN indexes on time-series, composite indexes for journal/account/date reports, partitioning plan for `audit_logs` / `journal_lines` (design + first table).
- Make **caching observable**: `X-Cache-Hit` / `X-Cache-TTL` response headers, scoped invalidation for `role_dashboards` / `chart_of_accounts`, fail-loud policy when Redis is unreachable instead of silent fallback to MemoryCache, cache warm-up on boot.
- Wire **GlobalSearch UI** to the unified backend search (autocomplete, cross-entity, page metadata) with debounced input.
- Deliver **frontend utility sweeps**: `formatNumber()` / `useExchangeRate` / `useApi` / `useDebounce` / router navigation / central error handler / focus rings / alt sweep / `React.lazy` / StrictMode re-enable / mobile-table strategy / ErrorBoundary route-state preservation / print-media isolation / i18n completion.
- Deliver **architecture cleanup**: Party-model unification phase 2, router → service → repository / DTO refactor for the highest-churn routers, removal of f-string SQL, idempotency keys for critical scheduled jobs, jobs monitoring UI / endpoint, company-timezone in scheduled tasks, dedup of scheduled-reports router/table.
- Deliver **ops automation**: backup via systemd timer + k8s CronJob with retention, restore API + playbook gated by sensitive permission, supervisor / restart policy for the background worker, CI/CD gates (lint / type / unit / contract / migrations dry-run / OpenAPI coverage), unified health/metrics adapters, OpenAPI description completion.

This feature consumes contracts shipped by 022 / 023 / 024 (audit outbox, PII sanitizer, `require_sensitive_permission`, secret vault, account classification, JE source enum, fiscal-period policy, Order→Invoice service, unified webhooks dispatcher, unified notifications dispatcher, `email_templates` table, signed approval-action tokens). It MUST NOT re-implement those contracts; it MUST consume them.

### In Scope

**R7 — Reports / Search / Dashboard**

- **Financial report correctness** (#403, #318, #321 / #405, #404, #272z, #419r):
  - Income statement MUST include header rows where they aggregate child accounts; behaviour controlled by `reports.income_statement.include_headers` (default `true`).
  - Balance-sheet sign logic refactored to read `account_classifications.normal_side` (debit / credit) from feature 022 instead of hard-coded ranges; assets / liabilities / equity / revenue / expense signs derived from the classifier, not from account-code prefixes.
  - Trial balance: documented tolerance policy (`reports.trial_balance.tolerance` default `0.01`), opening balance distribution corrected for accounts with reversed normal side (contra-asset, contra-revenue), opening balance source-of-truth is `journal_lines` filtered by `je_source='opening_balance'`.
  - Rollup type-coercion removed: aggregations MUST keep `Decimal` end-to-end; no implicit float coercion in pivot helpers.
  - KPI dashboard widgets MUST honour `account_type.normal_side` for sign (e.g., revenue shown positive, expense shown positive, contra-revenue subtracted).
- **Materialized views & cache** (#117, #118, #461 / #220, #319, #147, #354, #272c):
  - `mv_daily_financial_chart` — daily revenue / expense / cash position per `(tenant_id, company_id, date)`; refreshed by scheduler every `reports.mv.refresh_interval_minutes` (default 15) and on demand via `POST /reports/cache/refresh` (sensitive permission).
  - `mv_period_stats` — period totals replacing per-request `calculate_period_stats`; the Python helper becomes a thin reader over the MV.
  - Redis-backed report cache for non-MV reports: keys namespaced as `report:{tenant}:{report_code}:{params_hash}:{as_of_date}`, TTL configurable per report code (`reports.cache.ttl[<code>]`), default 300s.
  - Scoped invalidation: `chart_of_accounts` change invalidates only `report:{tenant}:coa:*` and dashboard-key prefixes that reference COA; `role_dashboards` change invalidates only the affected role's dashboards, not all dashboards.
  - Cache warm-up on boot: a bounded list of report codes / dashboard keys configured under `reports.warmup_keys` is warmed sequentially with a per-key timeout; failures are logged and don't block boot.
- **Cache observability & policy** (#270, #145):
  - All cache-bearing endpoints MUST emit `X-Cache-Hit: true|false` and `X-Cache-TTL: <seconds-remaining>` response headers.
  - Cache backend selection is explicit: `cache.backend = redis | memory`. When `redis`, a Redis outage MUST fail loudly (HTTP 503 with code `cache.unavailable`) for cache-required reports; never silently fall back to MemoryCache for cross-worker correctness.
  - `MemoryCache` is permitted only for single-worker dev / test mode; enabling it in production raises a startup warning audit event.
- **Indexing & partitioning** (#301, #302, #462):
  - BRIN indexes on `audit_logs(created_at)`, `journal_lines(posting_date)`, `inventory_transactions(transaction_date)`; verified via `EXPLAIN (BUFFERS)` baseline before/after on representative queries.
  - Composite indexes for journal/account/date reports: `journal_lines(tenant_id, account_id, posting_date)`, `journal_entries(tenant_id, source, source_id)`, `inventory_transactions(tenant_id, item_id, transaction_date)`.
  - Partitioning plan documented in `docs/partitioning-plan.md` and the first partitioned table (`audit_logs` by month) implemented with retention policy `audit.retention_months` (default 36); the legacy table is renamed and a partitioned table replaces it via attach/detach migration.
- **GlobalSearch UI wiring** (#239 / #482 / #483, #331, #395, #503):
  - GlobalSearch UI calls the existing unified search endpoint, supports cross-entity results, emits page metadata from a backend `GET /search/registry` (entity → display label / route template / icon) instead of a static frontend list.
  - Autocomplete with debounce (300ms default, configurable `search.autocomplete_debounce_ms`).
  - Result observability: each search records a row in `search_query_logs` (entity hit counts, latency_ms, result_count) for tuning.
- **KPI alerts & live dashboard** (#116, #119):
  - KPI definitions in `kpi_definitions` table reference an account classifier or a report key, threshold, comparison operator, and notification channels.
  - The scheduler evaluates KPI alerts on `reports.kpi.evaluation_interval_minutes` (default 15) and dispatches via the unified notifications dispatcher from feature 024.
  - Static dashboard widgets converted to reactive bindings: a WebSocket channel `dashboard:{tenant}:{role}` emits invalidation events; the frontend rebinds the relevant widget instead of polling.
- **Live exchange rate widgets** (#345 / #346, #259):
  - `useExchangeRate(currency_code)` hook reads from a single FX cache (TTL configurable, default 30 minutes) backed by the existing FX service; never returns the literal `1.0` placeholder.
  - Dashboard widgets that quote multi-currency totals MUST consume `useExchangeRate`; static values audited and removed.
- **Health / metrics adapters & OpenAPI** (#324 / #325, #419u):
  - All adapters (Redis, RQ/Celery worker, Postgres, ZATCA outbox, notifications queue, DMS storage, ClamAV, FX provider) expose a uniform `health_check()` returning `{status, latency_ms, last_success_at, last_error}`; `/health/detailed` aggregates.
  - OpenAPI: every router endpoint MUST have a `summary`, `description`, `response_model`, `responses` for non-200 codes used; a CI check (`scripts/check_openapi_coverage.py`) gates merges.

**R8 — Frontend / Architecture / Ops Cleanup**

- **Frontend utility sweeps**:
  - **#257** — replace `.toFixed(2)` / `parseFloat` with `formatNumber()` and `parseDecimal()` helpers; static check `scripts/check_frontend_number_format.py` reports zero violations in scope.
  - **#258** — `GET /locale/defaults` endpoint and Register / Onboarding / Branches consume it; no hard-coded locale defaults remain in those screens.
  - **#259** — `useExchangeRate` hook (see R7) replaces every `exchange_rate: 1.0`.
  - **#260** — replace `window.location` (assignments / `href = ...`) with `useNavigate()` / `<Navigate>`; allowed exceptions documented (e.g., external download URLs).
  - **#261** — `useDebounce` hook applied to every search / filter input field (300ms default).
  - **#262** — `useApi` hook migration: all data-fetching screens use `useApi(endpoint, options)` returning `{data, loading, error, refetch}`; manual `fetchData / setLoading` removed in scope.
  - **#263** — central error handler: `apiClient` interceptor maps backend `error.code` → user-facing i18n message; silent `catch (e) {}` removed.
  - **#265** — Vite config splits CSS per route bundle; verified by build output size budget (`vite-bundle-budget.json`).
  - **#266** — barrel exports decomposed into per-module imports for tree-shakable libraries; bundle size budget enforces no regression.
  - **#268** — `:focus-visible` rings on every primitive (button, input, link) using a single `--ring` CSS token; lint rule via stylelint.
  - **#270 (frontend alts)** — `alt` sweep: every `<img>` has a meaningful `alt`; decorative images use `alt=""` + `aria-hidden`.
  - **#271** — `React.lazy` + Suspense on heavy components (charts, editors, large modals); loading fallback uses skeleton.
  - **#272 / #343 / #365** — re-enable `<StrictMode>` after fixing the warnings catalogued in those refs (effects, deprecated lifecycles, key collisions).
  - **#339** — mobile table strategy: collapse to card list under `--breakpoint-md`; sticky-header with horizontal scroll fallback.
  - **#341 / #361 / #366** — finish per-page useApi migration for the remaining pages and ensure cleanup-on-unmount.
  - **#342** — semantic forms: `<form onSubmit>`, labelled fields, required attributes, `aria-describedby` for errors.
  - **#362** — `ErrorBoundary` uses `useNavigate` and preserves the previous route in state to allow "Try again" without losing context.
  - **#363** — thermal-printer styles wrapped in `@media print` and a print-only class; no bleed into screen layout.
  - **#419n** — i18n: every Arabic-only error string migrated to the `i18n` resource bundles with `en/ar` locales; static check reports zero remaining hard-coded localized errors.
- **Architecture cleanup**:
  - **#176** — Party model unification phase 2: customers + suppliers + employees converge on `parties` with role-typed records; legacy tables remain as views during the transition; one migration per entity.
  - **#138** — review and tune `misfire_grace_time` for every long-running scheduled job; document the policy in `docs/scheduler-policy.md`.
  - **#140** — idempotency keys on critical scheduled jobs (closing payroll, FX import, ZATCA submit, backups) layered over the existing SQLAlchemyJobStore (`scheduled_job_runs(idempotency_key UNIQUE)`).
  - **#143** — supervisor / restart policy for the background worker (systemd unit / k8s liveness probe + `restartPolicy: always`); documented in `docs/RUNBOOK.md`.
  - **#278** — admin UI / endpoint to monitor scheduled jobs (last run, next run, status, last error, manual run trigger); gated by sensitive permission `ops.scheduler.admin`.
  - **#279** — every scheduled task that depends on "today" / "now" reads company timezone from settings (continuation of feature 024 R5 work, applied to non-payroll schedulers).
  - **#419b** — dedup the duplicated scheduled-reports router/table; pick one canonical path, migrate data, drop the duplicate.
  - **#489 / #490 / #409–#414** — refactor the highest-churn routers into `router → service → repository` with explicit DTOs; remove `f"... {var} ..."` SQL in favour of bound parameters; static check `scripts/check_sql_parameterization.py` extended to fail on any new f-string SQL.
- **Ops automation**:
  - **#272i** — restore API: `POST /ops/restore` accepts a backup id, runs validation + dry-run, requires `require_sensitive_permission('ops.restore')`, audited; companion playbook `docs/RUNBOOK.md#restore`.
  - **#180 / #500** — backup automation: systemd timer `aman-backup.timer` (daily) + k8s CronJob, retention `backup.retention_days` (default 30), offsite copy via configurable provider (S3-compatible by default), success / failure events through unified notifications.
  - **#499** — CI/CD gates: lint, type-check (mypy/ts), unit, contract (OpenAPI), migrations dry-run (alembic upgrade head against an empty DB + `downgrade -1` round-trip), OpenAPI coverage check, frontend bundle-size budget, no-f-string-SQL check; all required to pass before merge to `main`.

### Out of Scope

- HR / Payroll / PII items (#190 / #434 family — owned by feature 024 R5).
- FSM / DMS / Notifications items (#213 / #214 / #423 / #90 family — owned by feature 024 R6).
- Sales / POS / ZATCA / Inventory / Manufacturing items (R3 + R4 — owned by feature 023).
- Settings JSONB typed-model migration (#178), tax-group junction (#179) — explicitly deferred (same as 023 / 024).
- Replacing the report engine, the GL posting service, or the search backend itself. This feature consumes them; it does not redesign them.
- A new analytics / BI product (e.g., star schema, cube, OLAP). Out of scope.
- Replacing Redis or the cache library; only the policy, observability, and invalidation behaviour change.
- Migrating away from React / Vite or introducing SSR. Only frontend hygiene and code-splitting changes are in scope.
- Full multi-tenant data partitioning re-design beyond the partitioning of `audit_logs` (and a documented plan for `journal_lines`).

### Functional Flow Summary

- **Flow-200 (Financial Report Read)**: A caller requests a financial report. The handler resolves classification via `account_classifications`, applies sign rules, returns the result, and emits `X-Cache-Hit` / `X-Cache-TTL`. For MV-backed reports, the read is a single SELECT against the MV.
- **Flow-201 (Period Stats Read)**: Period stats reads `mv_period_stats` for the requested `(tenant, company, period)`; on MV miss (recently created period not yet refreshed) the reader falls back to the live computation and triggers an asynchronous refresh.
- **Flow-202 (Report Cache Refresh)**: An admin or scheduler calls `POST /reports/cache/refresh` (or the periodic job runs); affected MVs are refreshed (`REFRESH MATERIALIZED VIEW CONCURRENTLY`); audit row recorded; failure rolls back and emits an alert.
- **Flow-203 (Cache Invalidation Scoped)**: A change to `chart_of_accounts` or `role_dashboards` triggers a scoped invalidation that deletes only the keys whose namespace matches the affected scope, not the whole cache namespace.
- **Flow-204 (Cache Outage)**: When `cache.backend=redis` and Redis is down, cache-required endpoints return HTTP 503 with code `cache.unavailable`; non-cache endpoints continue. A startup probe writes the chosen backend into the health endpoint.
- **Flow-205 (KPI Alert)**: The KPI evaluator reads `kpi_definitions`, evaluates each against the latest period stats, and dispatches via `notifications.dispatch` from feature 024 when the threshold is breached. Idempotent on `(kpi_id, evaluation_window_start)`.
- **Flow-206 (Dashboard Live Update)**: A relevant write (e.g., posting a JE) emits a server-side event; the dashboard WS channel publishes an invalidation; the frontend widget refetches via `useApi.refetch()`.
- **Flow-207 (GlobalSearch)**: A user types a query; the input is debounced; the request hits `GET /search?q=...`; the frontend renders cross-entity results using metadata from `GET /search/registry`; a click navigates via `useNavigate` to the entity route template.
- **Flow-208 (BRIN / Composite Index Plan Apply)**: The migration creates indexes `CONCURRENTLY` where supported; a baseline EXPLAIN report is captured before and after under `docs/perf/index-baselines.md`.
- **Flow-209 (audit_logs Partitioning)**: The legacy `audit_logs` table is renamed; a partitioned table is created; existing data is attached as the historical partition; new writes go to the current monthly partition; the retention scheduler drops partitions older than `audit.retention_months`.
- **Flow-210 (Health Aggregation)**: `/health/detailed` aggregates each adapter's `health_check()`; degraded subsystems mark the overall status `degraded` (not `down`) unless a critical adapter fails.
- **Flow-300 (Frontend Data Read via useApi)**: A component calls `useApi('/customers', {params})`. The hook returns `{data, loading, error, refetch}`; errors are mapped by the central error handler; the component renders skeletons during loading.
- **Flow-301 (Router Navigation)**: An action that previously called `window.location.assign(...)` now calls `navigate(path, {state})`; back/forward preserves state; ErrorBoundary `Try again` returns to the previous path.
- **Flow-302 (Debounced Search)**: A search input fires after 300ms idle; the prior in-flight request is cancelled; the latest result wins.
- **Flow-303 (Format / FX)**: A money cell formats via `formatNumber(value, currency)` using `useExchangeRate(currency)` for cross-currency display; never `value.toFixed(2)`.
- **Flow-304 (Lazy Heavy Component)**: A heavy chart imports via `React.lazy(() => import('./HeavyChart'))` wrapped in `<Suspense fallback={<Skeleton/>}>`; verified by the bundle-size budget.
- **Flow-305 (Print Mode)**: `@media print` activates thermal-printer styles only when printing; screen layout is unaffected.
- **Flow-310 (Scheduler Job Run)**: A scheduled job runs with an idempotency key `(job_id, scheduled_for)`; double-fire is absorbed via the unique constraint on `scheduled_job_runs`.
- **Flow-311 (Scheduler Monitoring)**: An admin opens the jobs UI; the page lists each job with last run, next run, status, last error; a `Run now` button is gated by sensitive permission.
- **Flow-312 (Backup Run)**: The systemd timer (or k8s CronJob) invokes `scripts/backup_postgres.sh`; on success, an offsite copy is uploaded; a notification is dispatched via the unified queue; failures escalate to the dead-letter alert.
- **Flow-313 (Restore)**: An admin triggers `POST /ops/restore` with a backup id; the API validates checksum + dry-run, asks for an explicit confirm token (HMAC-signed via feature 022 vault), then executes; audit captures the actor, target, and outcome.
- **Flow-314 (Party Unification)**: Reads of customers / suppliers / employees go through the party service; legacy tables remain as views during the transition; cutover migrations move per-entity in three phases; rollback path documented.
- **Flow-315 (Router → Service → Repository)**: A refactored router endpoint delegates to a service which delegates to a repository; SQL is parameter-bound; DTO models live in `schemas/`; static check fails the build on f-string SQL.

### Acceptance Criteria

1. **Given** a caller requests the income statement for a period that contains both leaf accounts and header accounts, **When** `reports.income_statement.include_headers=true`, **Then** header rows appear with aggregated totals over their children and the report total equals the sum of leaf rows.
2. **Given** a contra-revenue account exists, **When** the income statement / KPI dashboard renders, **Then** the contra-revenue value reduces revenue (correct sign per `account_classifications.normal_side`) instead of being added.
3. **Given** trial balance over a period with `tolerance=0.01`, **When** the sum of debits and credits differs by ≤ 0.01, **Then** the report is reported as balanced; differences greater than tolerance return a structured warning row that lists offending accounts.
4. **Given** the daily financial chart, **When** the user requests data for the current month, **Then** the response is a single SELECT against `mv_daily_financial_chart` and `X-Cache-Hit: true` is set on subsequent requests within TTL.
5. **Given** the configured cache backend is Redis and Redis is unreachable, **When** a cache-required report is requested, **Then** the response is HTTP 503 with code `cache.unavailable`; the same request to a non-cache endpoint succeeds.
6. **Given** a write to `chart_of_accounts`, **When** scoped invalidation runs, **Then** only keys under the COA namespace and dashboard keys that reference COA are evicted; unrelated cache keys remain.
7. **Given** the BRIN / composite index migration ran, **When** the standard "journal by account/date" report executes against a representative dataset, **Then** the EXPLAIN buffer reads decrease by ≥ 50% versus baseline (recorded in `docs/perf/index-baselines.md`).
8. **Given** `audit_logs` is partitioned by month with retention 36, **When** the retention scheduler runs at month-end, **Then** partitions older than 36 months are detached and dropped; an audit summary records counts.
9. **Given** the GlobalSearch input, **When** a user types "AC", **Then** an autocomplete request fires after 300ms idle, returns cross-entity results, and a click navigates to the entity route via `useNavigate` (not `window.location`).
10. **Given** a KPI definition with threshold "operating_margin < 5%", **When** the evaluator runs and the latest period violates it, **Then** the unified notifications dispatcher emits the alert and the same window does not re-fire (idempotent on `(kpi_id, window_start)`).
11. **Given** a JE is posted, **When** the relevant dashboard widget is open, **Then** it refetches within 5 seconds via the WS channel without a full page reload.
12. **Given** a multi-currency dashboard widget, **When** rendering, **Then** it consumes `useExchangeRate(currency)` from the FX cache; no `exchange_rate: 1.0` literal remains in the in-scope screens (verified by static check).
13. **Given** any router endpoint, **When** the OpenAPI coverage check runs in CI, **Then** every endpoint has a `summary`, `description`, and `response_model` (or `responses`); missing items fail the build.
14. **Given** every adapter has a `health_check()`, **When** `/health/detailed` is requested, **Then** the response includes `{status, latency_ms, last_success_at, last_error}` for each adapter and an aggregate status.
15. **Given** the in-scope frontend pages, **When** the static check `check_frontend_number_format.py` runs, **Then** it reports zero `.toFixed(2)` / `parseFloat` violations.
16. **Given** the in-scope screens, **When** a search-or-filter input is present, **Then** it uses `useDebounce` and cancels previous in-flight requests on the next keystroke.
17. **Given** a network error on any data-fetching screen, **When** the central error handler runs, **Then** the user sees an i18n message keyed by `error.code` and the error is reported (not silently swallowed).
18. **Given** the app build, **When** `vite build` completes, **Then** route-level CSS chunks exist and the bundle-size budget passes.
19. **Given** every primitive component, **When** it receives keyboard focus, **Then** a visible `:focus-visible` ring is rendered (verified by stylelint rule + a Playwright smoke).
20. **Given** `<StrictMode>` is re-enabled, **When** the app boots in development, **Then** zero deprecated-lifecycle / double-invoke warnings appear in the console for the in-scope screens.
21. **Given** an `ErrorBoundary` catches a render error, **When** the user clicks "Try again", **Then** the previous route's state is preserved; the user is not redirected to the home page unless they choose to.
22. **Given** the unified party service is in place, **When** a caller reads a customer / supplier / employee, **Then** the legacy view returns the same projection and writes go through the unified service.
23. **Given** a critical scheduled job (closing payroll, FX import, ZATCA submit, backup), **When** it is triggered twice for the same `(job_id, scheduled_for)`, **Then** the second run is absorbed by the unique constraint on `scheduled_job_runs` and recorded as `idempotent_skip`.
24. **Given** an admin opens the scheduler UI, **When** they click "Run now" on a job, **Then** the action is gated by `ops.scheduler.admin`, audited, and the job runs out-of-band without disrupting the next scheduled run.
25. **Given** a scheduled task computes "today" and the company timezone is `Asia/Riyadh`, **When** it runs at 00:30 UTC (03:30 local), **Then** "today" is the local date.
26. **Given** the duplicated scheduled-reports table/router, **When** the dedup migration runs, **Then** one canonical path remains, data is migrated 1:1, and the legacy path returns HTTP 410 Gone.
27. **Given** the in-scope routers, **When** the `check_sql_parameterization.py` static check runs, **Then** it reports zero f-string SQL strings.
28. **Given** the backup automation is configured, **When** the daily timer fires, **Then** a database dump is produced, an offsite copy is uploaded, retention is enforced, and the unified notifications dispatcher emits success or dead-letter on failure.
29. **Given** an admin invokes `POST /ops/restore` with a valid backup id and confirm token, **When** dry-run validation passes, **Then** the restore proceeds and is fully audited; an invalid or expired confirm token returns HTTP 400 with code `auth.token_invalid`.
30. **Given** a CI run on a PR, **When** any of the gates (lint / type / unit / contract / migrations dry-run / OpenAPI coverage / bundle budget / SQL parameterization) fails, **Then** the PR cannot merge to `main`.

### Edge Cases

- Income statement with a header row whose children span both revenue and contra-revenue: header total uses signed sum per child classification, not absolute sum.
- Trial-balance opening balance for a contra-asset: opening balance is read with the contra sign reversed; documented in `docs/reports/trial-balance.md`.
- MV refresh fails mid-cycle: `REFRESH ... CONCURRENTLY` retains the previous snapshot; failure raises an alert; reads continue against the previous snapshot.
- MV miss for a freshly-created period: reader falls back to live compute and triggers an async refresh; subsequent reads hit the MV.
- Cache key collision across tenants: keys MUST include `tenant_id`; static linter prevents tenant-less cache keys (`scripts/check_cache_keys.py`).
- Redis flapping (intermittent): circuit breaker on the cache client opens after `cache.circuit_breaker.failures` consecutive failures and stays open for `cache.circuit_breaker.cool_down_seconds`; closed-state probes resume.
- BRIN on a heavily-updated table: documented expectation that BRIN is best for append-mostly tables; `journal_lines` qualifies, `customers` would not.
- Partitioning rollover at month boundary: a pre-create scheduler creates next month's partition in advance to prevent first-write contention.
- GlobalSearch with empty registry on a cold deploy: returns 503 with code `search.registry_empty` and a structured remediation note (run the registry seed script).
- KPI alert on a metric whose data is not yet available: evaluator marks the run `skipped_no_data`; never emits a false alarm.
- FX provider outage: `useExchangeRate` returns the last cached value for `fx.stale_tolerance_minutes`, then surfaces a `fx_stale=true` flag; widgets render a tooltip "Rates may be stale".
- Frontend route navigation for an external URL: documented exception list under `frontend/src/routing/external-urls.ts`; lint rule allows `window.location.assign` only for entries on that list.
- StrictMode re-enable surfaces a previously-hidden double-effect bug: scope blocked until that bug is fixed; partial enablement allowed via a feature flag during transition.
- ErrorBoundary triggered during navigation: the boundary captures `location.state.from` (the previous safe route) and offers it as the recovery target; if no safe route, it offers the role's home.
- Party unification phase 2 over a record present in two legacy tables (e.g., a customer who is also an employee): merge resolution policy in `docs/party-unification.md`; default is "keep both as roles on the same party with conflict report".
- Scheduled job idempotency clash where the same `(job_id, scheduled_for)` is intentionally re-run by an admin: the admin "force re-run" path uses a separate counter `(job_id, scheduled_for, attempt)` and is audited.
- Backup retention deleting the last good backup due to misconfiguration: minimum-retention guard refuses to delete if remaining backups < `backup.min_retained` (default 3).
- Restore on a tenant database that was created after the backup was taken: dry-run flags missing tenant; restore is blocked until the operator chooses "include new tenants empty" or "abort".
- CI gate failure on a hot-fix branch: a documented `--break-glass` path requires two reviewers and writes a `break_glass_audit_log` row; never silent.

## Requirements *(mandatory)*

### Functional Requirements

**R7 — Reports / Search / Dashboard**

- **FR-200**: System MUST compute report sign and sign-aware aggregations from `account_classifications.normal_side` (not from account-code prefixes) and MUST surface header rows in the income statement when configured.
- **FR-201**: System MUST provide `mv_daily_financial_chart` and `mv_period_stats` materialized views, scheduled refreshes, and an admin-gated on-demand refresh endpoint; the legacy `calculate_period_stats` becomes a thin reader over the MV.
- **FR-202**: System MUST provide a Redis-backed report cache with namespaced keys, per-report TTLs, scoped invalidation for COA / role-dashboards, and warm-up of a configured key list on boot.
- **FR-203**: System MUST emit `X-Cache-Hit` and `X-Cache-TTL` response headers on all cache-bearing endpoints and MUST fail loudly (HTTP 503 `cache.unavailable`) when the configured Redis backend is unreachable.
- **FR-204**: System MUST add BRIN indexes on time-series columns and composite indexes for journal/account/date and inventory time queries; baseline and post-change EXPLAIN buffers MUST be recorded.
- **FR-205**: System MUST partition `audit_logs` by month with a retention scheduler honouring `audit.retention_months` and MUST publish a partitioning plan for `journal_lines`.
- **FR-206**: System MUST wire GlobalSearch UI to the unified backend search with debounced autocomplete, cross-entity results, page metadata sourced from `GET /search/registry`, and per-query observability into `search_query_logs`.
- **FR-207**: System MUST evaluate KPI alerts on schedule, dispatch via the unified notifications dispatcher (feature 024), and be idempotent on `(kpi_id, evaluation_window_start)`.
- **FR-208**: System MUST replace static dashboard widgets with reactive bindings driven by a per-tenant/per-role WebSocket channel and MUST replace placeholder exchange rates with `useExchangeRate(currency)` reading from the FX cache.
- **FR-209**: System MUST expose uniform `health_check()` on every adapter, aggregate at `/health/detailed`, and gate merges on a CI OpenAPI coverage check that requires `summary`, `description`, and `response_model`/`responses` on every endpoint.

**R8 — Frontend / Architecture / Ops**

- **FR-300**: System MUST replace `.toFixed(2)` / `parseFloat` with `formatNumber()` / `parseDecimal()` across in-scope screens and MUST gate this in CI via a static check.
- **FR-301**: System MUST provide a `GET /locale/defaults` endpoint and consume it from Register / Onboarding / Branches.
- **FR-302**: System MUST replace `exchange_rate: 1.0` with `useExchangeRate` in all in-scope screens.
- **FR-303**: System MUST replace `window.location` (assignments / `href`) with `useNavigate` / `<Navigate>`, with a documented exception list for true external URLs.
- **FR-304**: System MUST provide a `useDebounce` hook (300ms default) and apply it to every search/filter input in scope.
- **FR-305**: System MUST migrate in-scope data-fetching screens to a `useApi` hook returning `{data, loading, error, refetch}`; manual `fetchData/setLoading` removed.
- **FR-306**: System MUST provide a central error handler in the API client that maps backend `error.code` to i18n messages; `catch (e) {}` silent paths removed in scope.
- **FR-307**: System MUST split CSS per route bundle in Vite and enforce a bundle-size budget in CI.
- **FR-308**: System MUST decompose barrel exports for tree-shakable libraries to keep bundle size within budget.
- **FR-309**: System MUST add `:focus-visible` rings on all primitives via a single CSS token; stylelint rule enforces this.
- **FR-310**: System MUST add meaningful `alt` text to all `<img>` and `alt=""` + `aria-hidden` to decorative images in scope.
- **FR-311**: System MUST `React.lazy` heavy components with `<Suspense>` skeleton fallbacks.
- **FR-312**: System MUST re-enable `<StrictMode>` after fixing the catalogued warnings (#272 / #343 / #365), with a feature-flag fallback for partial enablement.
- **FR-313**: System MUST provide a mobile-table strategy (card list under `--breakpoint-md` with sticky header / horizontal scroll fallback).
- **FR-314**: System MUST refactor `ErrorBoundary` to use `useNavigate` and preserve previous route state for "Try again".
- **FR-315**: System MUST isolate thermal-printer styles under `@media print`; no bleed into screen layout.
- **FR-316**: System MUST migrate Arabic-only error strings to `i18n` resource bundles (`en/ar`); a static check reports zero remaining hard-coded localized errors in scope.
- **FR-317**: System MUST progress Party-model unification phase 2 (customers + suppliers + employees as roles on `parties`) with legacy views during transition and per-entity cutover migrations.
- **FR-318**: System MUST tune `misfire_grace_time` per long-running scheduled job and document the policy.
- **FR-319**: System MUST add idempotency keys on critical scheduled jobs (closing payroll, FX import, ZATCA submit, backups) backed by a unique constraint on `scheduled_job_runs`.
- **FR-320**: System MUST run the background worker under a supervisor / restart policy (systemd / k8s liveness + restart) and document it in `RUNBOOK.md`.
- **FR-321**: System MUST provide an admin scheduler-monitoring UI / endpoint gated by `ops.scheduler.admin`, exposing last run, next run, status, last error, and an audited "Run now".
- **FR-322**: System MUST use company timezone in scheduled tasks for "today" / "now" derivations beyond the payroll scope already covered by feature 024.
- **FR-323**: System MUST dedup the duplicated scheduled-reports router/table; legacy path returns HTTP 410 Gone after migration.
- **FR-324**: System MUST refactor in-scope highest-churn routers into `router → service → repository` with explicit DTOs and remove f-string SQL; CI gate enforces the SQL parameterization rule.
- **FR-325**: System MUST automate database backups via systemd timer + k8s CronJob with offsite copy and retention; success/failure events flow through the unified notifications dispatcher.
- **FR-326**: System MUST provide `POST /ops/restore` gated by `ops.restore` with HMAC-signed confirm token (feature 022 vault), dry-run validation, full audit, and a documented playbook.
- **FR-327**: System MUST enforce CI/CD gates: lint, type, unit, contract (OpenAPI), migrations dry-run (`upgrade head` + `downgrade -1`), OpenAPI coverage, bundle-size budget, SQL parameterization, frontend number-format, focus-visible stylelint, i18n hard-coded check.

### Key Entities *(include if feature involves data)*

- **`account_classifications`** (consumed from feature 022): `normal_side`, `category`, `is_contra` — drives report sign rules.
- **`mv_daily_financial_chart`** (new MV): per-day revenue / expense / cash position by `(tenant_id, company_id, date)`.
- **`mv_period_stats`** (new MV): per-period totals replacing the per-request helper.
- **`kpi_definitions`**: `kpi_code`, `metric_source` (report key or classifier reference), `threshold`, `comparison_op`, `channels`, `evaluation_interval_minutes`, `is_active`.
- **`kpi_evaluations`**: `kpi_id`, `evaluation_window_start`, `value`, `breached`, `notified_at`.
- **`search_query_logs`**: `tenant_id`, `query`, `result_count`, `latency_ms`, `entity_hits jsonb`, `created_at`.
- **`scheduled_job_runs`**: `job_id`, `scheduled_for`, `attempt`, `status`, `started_at`, `finished_at`, `error`, **UNIQUE(`job_id`, `scheduled_for`, `attempt`)**.
- **`audit_logs` (partitioned)**: monthly partitions, retention scheduler.
- **`parties` + `party_roles`** (consumed/extended from feature 022 R5 transition): unified entity for customers / suppliers / employees with role rows.
- **`backup_runs`**: `backup_id`, `started_at`, `finished_at`, `size_bytes`, `checksum`, `offsite_uri`, `status`.
- **`break_glass_audit_log`**: `actor_id`, `pr_id`, `gate_skipped`, `reason`, `created_at`.

**Data Documentation Rule**: Mention table names and critical fields only. Do not include full DDL unless explicitly requested.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-200**: 95% of standard financial reports respond in under 800ms at the dataset size of the largest production tenant (P95 measured over a 7-day window after rollout).
- **SC-201**: Period-stats endpoint latency drops by ≥ 70% versus the per-request helper baseline (recorded in `docs/perf/period-stats-baseline.md`).
- **SC-202**: Cache hit rate on the configured warm-up keys is ≥ 85% during business hours (08:00–18:00 local) within two weeks of rollout.
- **SC-203**: Zero silent fallbacks to MemoryCache observed in production logs; every `cache.unavailable` event is surfaced and tracked.
- **SC-204**: Buffer reads on the journal/account/date report drop by ≥ 50% post-index migration on representative production-sized data.
- **SC-205**: `audit_logs` partition retention scheduler removes data older than the configured retention window with 100% accuracy; no rows older than retention remain after a monthly run.
- **SC-206**: GlobalSearch returns the first result in under 250ms P95 for queries of 3+ characters.
- **SC-207**: KPI alerts fire within the configured evaluation window with zero duplicate dispatches in steady state.
- **SC-208**: 100% of in-scope dashboard widgets are reactive; no manual reload required to reflect a relevant write within 5 seconds.
- **SC-209**: 100% of in-scope endpoints pass the OpenAPI coverage check (summary + description + response model).
- **SC-300**: 100% of in-scope screens use `useApi`; the static check reports zero `fetchData/setLoading` patterns in scope.
- **SC-301**: Frontend bundle size on the main route is ≤ the budget defined in `vite-bundle-budget.json` (initial budget set after a baseline measurement, then enforced).
- **SC-302**: Zero `.toFixed(2)` / `parseFloat` violations in scope (static check).
- **SC-303**: Zero `window.location` violations in scope outside the documented external-URL exception list.
- **SC-304**: Lighthouse accessibility score on key pages improves by ≥ 10 points versus baseline.
- **SC-305**: Zero hard-coded Arabic-only error strings in scope (static check).
- **SC-306**: Zero f-string SQL strings in scope (static check).
- **SC-307**: 100% of critical scheduled jobs are idempotent on `(job_id, scheduled_for)`; a controlled double-fire test in staging produces exactly one effective run.
- **SC-308**: 100% of scheduled reports use the canonical router/table after migration; the legacy path returns 410.
- **SC-309**: Daily backup success rate ≥ 99% over a 30-day window; offsite copy success rate ≥ 99%; restore dry-run succeeds against the latest backup at least weekly.
- **SC-310**: 100% of merges to `main` pass all CI/CD gates; break-glass merges produce an audit row with two reviewers recorded.

## Assumptions

- Feature 022's `account_classifications`, `require_sensitive_permission`, secret vault, audit outbox, and PII sanitizer are in place and stable; this feature consumes them.
- Feature 023's Order→Invoice service, JE source enum, and unified webhooks dispatcher are in place; this feature consumes them.
- Feature 024's unified notifications dispatcher and `email_templates` are in place; KPI alerts and backup events route through the dispatcher.
- The deployment supports Redis (production) and a documented dev-only MemoryCache; a true Redis cluster is not required for this feature, only a reachable Redis endpoint.
- The PostgreSQL version supports `REFRESH MATERIALIZED VIEW CONCURRENTLY`, BRIN indexes, and partition attach/detach (PG ≥ 13).
- Scheduler is APScheduler (or equivalent already in the codebase); idempotency is layered on top via `scheduled_job_runs` rather than replacing the scheduler.
- The frontend is React + Vite; CSS splitting and `React.lazy` are supported by the current toolchain without an SSR introduction.
- The unified backend search endpoint exists and is stable; this feature only adds the registry, observability, and the UI wiring.
- Backup target storage (S3-compatible) credentials are managed via the feature 022 vault; offsite copy provider is configurable.
- CI provider supports parallel jobs and required-status-check gating on the protected branch.
- Production traffic permits running BRIN / partition migrations during a maintenance window; `CREATE INDEX CONCURRENTLY` is used wherever possible.
- The Party-model unification phase 2 is delivered as legacy views over the new tables during the transition; downstream readers are not forced to migrate within this feature.
- The "highest-churn routers" target list is derived from `git log` activity over the last 90 days; the actual list is recorded in the implementation plan.
