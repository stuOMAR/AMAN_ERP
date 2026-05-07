# Phase 0 — Research: Reports + Frontend/Ops Maturity (R7 + R8)

**Date**: 2026-05-02
**Branch**: `025-reports-frontend-ops-maturity`
**Status**: All NEEDS CLARIFICATION resolved.

The spec contains no explicit `[NEEDS CLARIFICATION]` markers; this document captures the implicit decisions made when filling Technical Context and design choices that the implementation will rely on. Each entry uses Decision / Rationale / Alternatives.

---

## 1. Cache backend selection policy (Redis vs MemoryCache)

- **Decision**: Configuration setting `cache.backend` with values `redis | memory`. Production deployments MUST set `redis`. When `redis` is configured and Redis is unreachable, cache-required endpoints return HTTP 503 with code `cache.unavailable`; non-cache endpoints continue. A circuit breaker on the cache client (configurable `cache.circuit_breaker.failures` / `cool_down_seconds`) prevents thrashing. `memory` is permitted only for single-worker dev/test; selecting it in production raises a startup warning audit event.
- **Rationale**: Silent fallback to in-process MemoryCache across multiple workers produces stale, divergent reads. The remediation plan explicitly flags this as #145.
- **Alternatives considered**: (a) Always allow MemoryCache fallback — rejected (correctness). (b) Hard-fail on any Redis hiccup — rejected (overkill; circuit breaker provides resilience without silent divergence).

## 2. Materialized view refresh strategy

- **Decision**: `mv_daily_financial_chart` and `mv_period_stats` are refreshed by an APScheduler job every `reports.mv.refresh_interval_minutes` (default 15) using `REFRESH MATERIALIZED VIEW CONCURRENTLY`. An on-demand `POST /reports/cache/refresh` endpoint is gated by `require_sensitive_permission('reports.cache.refresh')`. On miss for a freshly-created period (data not yet in MV), readers fall back to live compute and trigger an async refresh.
- **Rationale**: Concurrent refresh keeps reads online; a 15-minute cadence balances staleness vs CPU; on-demand refresh covers operator-driven recompute.
- **Alternatives considered**: (a) Trigger-based incremental refresh — rejected (high write-path cost on `journal_lines`). (b) Cron-only without on-demand — rejected (operators need a "recompute now" path after corrections).

## 3. Cache key namespace and scoped invalidation

- **Decision**: Namespaced keys `report:{tenant}:{report_code}:{params_hash}:{as_of_date}`; dashboard keys `dashboard:{tenant}:{role}:{widget}:{params_hash}`. Per-domain invalidation registry maps a domain event (`coa.changed`, `role_dashboard.changed`, `je.posted`) to a key prefix list. The COA event evicts only `report:{tenant}:coa:*` and dashboard prefixes flagged as COA-dependent; `role_dashboards` change evicts only the affected role's keys. A linter `scripts/check_cache_keys.py` rejects any cache key without a `tenant_id` segment.
- **Rationale**: Mass-evict on every COA write was the documented anti-pattern (#272c, #354). A registry pattern keeps invalidation explicit and reviewable.
- **Alternatives considered**: (a) Namespace-version bump (e.g., `coa:v1` → `coa:v2`) — rejected (orphans live keys, unbounded memory). (b) TTL-only — rejected (unacceptable staleness on COA changes).

## 4. Cache observability headers

- **Decision**: A FastAPI middleware sets `X-Cache-Hit: true|false` and `X-Cache-TTL: <seconds-remaining>` on responses from cache-bearing endpoints. Endpoints opt in via a router decorator `@cache_observable(report_code, ttl_setting)`; the decorator wraps the cache client to read the per-key TTL via `TTL` and emits the header.
- **Rationale**: Observability without changing response bodies; per-key TTL is already known to the client.
- **Alternatives considered**: A response-wrapping JSON envelope — rejected (changes contract for every consumer).

## 5. BRIN + composite index plan

- **Decision**: BRIN indexes on append-mostly time-series columns: `audit_logs(created_at)`, `journal_lines(posting_date)`, `inventory_transactions(transaction_date)`. Composite B-tree indexes for join paths in journal/account/date and inventory time queries: `journal_lines(tenant_id, account_id, posting_date)`, `journal_entries(tenant_id, source, source_id)`, `inventory_transactions(tenant_id, item_id, transaction_date)`. Migrations use `CREATE INDEX CONCURRENTLY`. Baseline + post-change `EXPLAIN (BUFFERS)` recorded in `docs/perf/index-baselines.md`.
- **Rationale**: BRIN gives massive disk savings on append-mostly tables; composite indexes match the actual ORDER BY / WHERE shape of the highest-cost reports (#301, #462).
- **Alternatives considered**: GIN on `journal_lines` — rejected (write-amplification on a hot ledger). Partial indexes — kept as a future option once partitioning is in place.

## 6. `audit_logs` partitioning and retention

- **Decision**: Range-partition `audit_logs` by month on `created_at`. Migration: rename existing `audit_logs` → `audit_logs_legacy_<date>`, create new partitioned `audit_logs`, attach the legacy table as the historical partition, create the current and the next month's partitions in advance. A monthly scheduler creates `next-month + 1`'s partition and detaches partitions older than `audit.retention_months` (default 36); detached partitions are dropped.
- **Rationale**: Retention is mandatory for compliance and storage cost; partition attach/detach is online; pre-creating the next partition prevents first-write contention at month boundary (#302).
- **Alternatives considered**: Logical archival to a separate table — rejected (queries lose the unified view). Time-bucketed table-per-year — rejected (worse than monthly for retention granularity).

## 7. Scheduled-job idempotency layer

- **Decision**: New table `scheduled_job_runs(job_id, scheduled_for, attempt, status, started_at, finished_at, error, UNIQUE(job_id, scheduled_for, attempt))`. Critical jobs (closing payroll, FX import, ZATCA submit, backups) wrap their entry point with an idempotency context that inserts `(job_id, scheduled_for, attempt=1)`; a re-fire for the same `(job_id, scheduled_for)` is absorbed with status `idempotent_skip`. Admin "force re-run" increments `attempt`.
- **Rationale**: SQLAlchemyJobStore alone doesn't prevent in-flight double-fire (#140). Adding a defensive UNIQUE provides the missing guarantee without replacing the scheduler.
- **Alternatives considered**: Replace APScheduler with Celery beat — rejected (scope explosion, not warranted).

## 8. Scheduler monitoring UI

- **Decision**: Backend endpoint `GET /ops/scheduler/jobs` returning `(job_id, last_run, next_run, status, last_error)` with paging; `POST /ops/scheduler/jobs/{job_id}/run-now` gated by `require_sensitive_permission('ops.scheduler.admin')`, audited. Frontend page `pages/ops/Scheduler.jsx` consumes `useApi` and refreshes every 30s.
- **Rationale**: Operational visibility into scheduler is a known gap (#278).
- **Alternatives considered**: Reuse Flower (Celery) UI — rejected (we don't run Celery).

## 9. KPI evaluation engine

- **Decision**: New tables `kpi_definitions(kpi_code, metric_source, threshold_value, comparison_op, channels, evaluation_interval_minutes, is_active, tenant_id)` and `kpi_evaluations(kpi_id, evaluation_window_start, value, breached, notified_at)`. The evaluator job runs every `reports.kpi.evaluation_interval_minutes` (default 15) and computes the metric from either a report key (existing report registry) or a classifier reference (`account_classifications.category` totals from `mv_period_stats`). Idempotent on `(kpi_id, evaluation_window_start)`. Notifications dispatched via the feature 024 unified dispatcher.
- **Rationale**: The KPI alert path was missing (#119). Two metric source types cover all current dashboard KPIs without coupling to a specific report.
- **Alternatives considered**: A dedicated rule engine — rejected (complexity not justified for a small fixed set of KPIs).

## 10. Reactive dashboard widgets

- **Decision**: A WebSocket channel `dashboard:{tenant}:{role}` on the existing WS infra; backend services that produce dashboard-relevant changes (JE post, invoice post, payroll close, inventory write) emit a structured invalidation event `(widget_keys: [...])`. The frontend widget listens and calls `useApi.refetch()`. No payload of the actual data is pushed — only the invalidation key.
- **Rationale**: Pushing data risks tenant leakage and stale auth contexts; pushing invalidation keeps the auth boundary at the HTTP refetch.
- **Alternatives considered**: Server-Sent Events (SSE) — rejected (we already use WS for other surfaces). Polling — rejected (poor UX, wasteful).

## 11. GlobalSearch UI and observability

- **Decision**: `GET /search/registry` returns the registry of `(entity_code, label, route_template, icon)`; the frontend renders cross-entity results based on this metadata. Input is debounced 300ms (configurable `search.autocomplete_debounce_ms`); previous in-flight requests are cancelled. Each query writes a row in `search_query_logs(tenant_id, query, result_count, latency_ms, entity_hits, created_at)` for tuning. Navigation uses `useNavigate` with the route template; never `window.location`.
- **Rationale**: Frontend hard-codes were the documented gap (#239 / #482 / #483 / #395). A backend-served registry keeps deploys aligned.
- **Alternatives considered**: Hard-code the registry in the frontend bundle — rejected (deploys diverge).

## 12. `useExchangeRate` and FX cache

- **Decision**: `useExchangeRate(currency_code)` reads from a single FX cache (TTL `fx.cache_ttl_minutes`, default 30). FX provider outages return the last cached rate up to `fx.stale_tolerance_minutes`, then the hook surfaces `fx_stale=true` and widgets render a tooltip "Rates may be stale". Never returns the literal `1.0` placeholder.
- **Rationale**: Live FX is mandatory for multi-currency dashboards (#345 / #346 / #259). Stale-tolerance prevents UX flapping.
- **Alternatives considered**: Per-component fetch — rejected (N×stampede on dashboards).

## 13. Frontend `useApi` hook contract

- **Decision**: `useApi(endpoint, {params, deps, suspense=false})` returns `{data, loading, error, refetch, abort}`. Errors are mapped by the central interceptor in `apiClient` (backend `error.code` → i18n key). Requests are aborted on unmount or on `deps` change.
- **Rationale**: One contract enables the full migration sweep (#262, #341 / #361 / #366).
- **Alternatives considered**: SWR / React Query — rejected (introducing a new dep is broader than this remediation).

## 14. CSS splitting + bundle budget

- **Decision**: Vite config uses route-level dynamic imports for heavy components and produces per-route CSS chunks. A `vite-bundle-budget.json` pins the initial route bundle size (set after a baseline measurement); CI gate fails on regression > 5%.
- **Rationale**: Bundle size is invisible without enforcement (#265, #266).
- **Alternatives considered**: Webpack analyzer-only — rejected (informational, not enforcing).

## 15. StrictMode re-enable feature flag

- **Decision**: A build-time flag `STRICT_MODE_PARTIAL=true|false` allows partial enable on a route allow-list during transition. Once the warning catalogue is empty, the flag is removed and `<StrictMode>` wraps the entire app.
- **Rationale**: Re-enabling globally without a transition path risks regressing pages that still have double-effect bugs (#272 / #343 / #365).
- **Alternatives considered**: Hard re-enable — rejected (timing risk).

## 16. ErrorBoundary route preservation

- **Decision**: `ErrorBoundary` uses `useNavigate` and stores `location.state.from = previousSafeRoute`. "Try again" navigates back to that route with state intact. If no safe route exists, fallback is the role's home route from `/me`.
- **Rationale**: Boundary today drops users to the home page, losing context (#362).
- **Alternatives considered**: Reset boundary in place — rejected (a render-error in the same route loops).

## 17. Party unification phase 2

- **Decision**: A `parties` table and a `party_roles` table already exist from feature 022's groundwork; this feature extends `party_roles` with `customer | supplier | employee` rows and migrates per-entity in three phases (customer → supplier → employee). Legacy `customers` / `suppliers` / `employees` tables become views over `parties` + `party_roles` during the transition. Conflict resolution policy documented in `docs/party-unification.md`; default is "keep both as roles on the same party with conflict report".
- **Rationale**: One source of truth for cross-module master data is a constitutional principle (XXI) and a known gap (#176).
- **Alternatives considered**: Big-bang cutover — rejected (rollback impossible). Per-tenant opt-in — rejected (violates uniform data model).

## 18. Backup automation and offsite copy

- **Decision**: `ops/systemd/aman-backup.timer` runs daily at `backup.local_time` (default 02:00 server time). Runs `scripts/backup_postgres.sh` (extended) which produces a `pg_dump` per tenant DB, uploads to an S3-compatible target (provider configurable; credentials in feature 022 vault), enforces retention `backup.retention_days` (default 30) with a `backup.min_retained` floor (default 3) that refuses to delete the last good backups. k8s deployments use a CronJob with the same script. Success / failure events route through the feature 024 dispatcher; failure beyond `backup.max_consecutive_failures` is a dead-letter alert.
- **Rationale**: #180 / #500 / #272i.
- **Alternatives considered**: WAL archiving (PITR) — kept as a future enhancement; this feature establishes daily logical dumps as the floor.

## 19. Restore API and confirm token

- **Decision**: `POST /ops/restore` accepts `{backup_id, confirm_token}`, gated by `require_sensitive_permission('ops.restore')`, audited. The confirm token is HMAC-signed via feature 022 vault keys with claims `(action='ops.restore', backup_id, actor_id, exp)`. Step 1: dry-run validates checksum + tenant inventory. Step 2: explicit confirm token executes restore. Audit captures actor, target, dry-run result, outcome.
- **Rationale**: Restore is a high-blast-radius operation (#272i).
- **Alternatives considered**: CLI-only restore — rejected (no audit, no permission check). One-step API — rejected (operator footgun).

## 20. Router → service → repository refactor scope

- **Decision**: Target list = top 10 routers by `git log --since="90 days ago" --pretty=format: --name-only -- backend/routers/ | sort | uniq -c | sort -rn | head -10`. Recorded in `docs/refactor-target-routers.md` at implementation time. Each target router gets a service layer + repository layer; SQL is parameter-bound; DTO models live in `schemas/`. Static check `scripts/check_sql_parameterization.py` is extended to fail on any new `f"... {var} ..."` SQL in the touched files.
- **Rationale**: Refactor where churn is highest (#489 / #490 / #409–#414).
- **Alternatives considered**: Refactor all routers — rejected (scope explosion).

## 21. CI/CD gate matrix

- **Decision**: Gates required on PR-to-`main`:
  1. Lint (ruff, eslint, stylelint).
  2. Type (mypy, tsc).
  3. Unit (pytest, vitest).
  4. Contract (OpenAPI schema diff).
  5. Migrations dry-run (`alembic upgrade head` against an empty DB + `downgrade -1` round-trip).
  6. OpenAPI coverage (`scripts/check_openapi_coverage.py`).
  7. SQL parameterization (`scripts/check_sql_parameterization.py`).
  8. Cache keys (`scripts/check_cache_keys.py`).
  9. Schema sync (`scripts/check_schema_sync.py`).
  10. Frontend number-format (`scripts/check_frontend_number_format.py`).
  11. Frontend `window.location` allow-list (`scripts/check_frontend_window_location.py`).
  12. Frontend i18n hard-coded strings (`scripts/check_frontend_i18n_strings.py`).
  13. Frontend bundle-size budget (`vite-bundle-budget.json`).
- Break-glass merge requires two reviewers + a `break_glass_audit_log` row.
- **Rationale**: #499.
- **Alternatives considered**: Allow gates as warnings — rejected (drift is guaranteed).

## 22. Health adapter contract

- **Decision**: Each adapter exposes `health_check() -> {status: ok|degraded|down, latency_ms, last_success_at, last_error}`. `/health/detailed` aggregates and returns per-adapter + aggregate. A critical-adapter list (`db`, `redis`, `worker`) maps to overall `down`; non-critical adapters can be `degraded` without taking the system down.
- **Rationale**: Uniform health surface for monitoring/runbook (#324 / #325).
- **Alternatives considered**: One huge OpenAPI schema per adapter — rejected (overkill).

## 23. Test posture

- **Decision**: Tests are NOT generated by this plan. CI gates test commands run only existing tests; no new test files unless the user explicitly requests them later. Risk-focused test additions (e.g., scoped invalidation behaviour, sign-rule correctness, scheduled-job idempotency) are deferred to `/speckit.tasks` and only included if the user opts in.
- **Rationale**: Constitution (Workflow rule 6) and the user's standing operating instruction.

## 24. Schema sync checker

- **Decision**: `scripts/check_schema_sync.py` parses migration head + canonical DDL module(s) under `backend/db_ddl/` and reports any column / table / index defined in only one place. CI fails on mismatch.
- **Rationale**: Constitutional principle XXVIII; eliminates the recurring DDL/ORM drift seen in #419.
- **Alternatives considered**: Manual review checklist — rejected (drift returns within weeks).

## 25. Refactor target routers — discovery method

- **Decision**: At implementation time, run the documented `git log` query to produce the list. The discovery is part of the first task in `tasks.md`; no list is hard-coded into the plan.
- **Rationale**: Churn changes; a static list ages poorly.
