# Implementation Plan: Reports/Search/Dashboard + Frontend/Architecture/Ops Maturity (R7 + R8)

**Branch**: `025-reports-frontend-ops-maturity` | **Date**: 2026-05-02 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/025-reports-frontend-ops-maturity/spec.md`

## Summary

Close R7 (financial-report correctness, MV-backed period stats and daily charts, Redis report cache + scoped invalidation + warm-up + observability headers, BRIN/composite indexes, `audit_logs` partitioning, GlobalSearch UI wiring, KPI alerts, reactive dashboard widgets, uniform health checks, OpenAPI coverage) and R8 (frontend `useApi` / `useDebounce` / `useExchangeRate` / `formatNumber` / router-navigation / central error handler / focus-visible / lazy / StrictMode / mobile tables / ErrorBoundary / print-media / i18n sweeps, Party-model unification phase 2, scheduled-job idempotency + monitoring UI + company-tz, scheduled-reports dedup, router→service→repository refactor + no-f-string-SQL gate, backup automation + restore API + playbook, full CI/CD gate matrix). This feature consumes contracts already shipped by features 022 / 023 / 024 (`account_classifications`, `require_sensitive_permission`, secret vault, audit outbox, JE source enum, Order→Invoice service, unified webhooks dispatcher, unified notifications dispatcher, `email_templates`, signed approval-action tokens) and does not redesign them. Technical approach: additive migrations (MVs, BRIN/composite indexes, `audit_logs` partitioning via attach/detach, new tables `kpi_definitions` / `kpi_evaluations` / `search_query_logs` / `scheduled_job_runs` / `backup_runs` / `break_glass_audit_log`), policy/config additions (cache backend selection, cache TTLs per report code, retention windows, KPI evaluation interval), one new health-aggregator endpoint, frontend hooks + lint rules + Vite config + bundle budget, ops automation (systemd unit + k8s CronJob + restore API), and CI gate scripts. No replacement of report engine, search backend, scheduler library, cache library, or React/Vite stack.

## Technical Context

**Language/Version**: Python 3.12 backend; React 18 / Vite frontend; existing mobile surface unchanged.
**Primary Dependencies** (consumed, not added): FastAPI, SQLAlchemy + raw SQL, Pydantic at API boundary, APScheduler, Redis, ClamAV (already integrated by feature 024), python-magic, i18next. New dev/CI artefacts only: stylelint focus-visible rule, vite-bundle-budget script, systemd unit / k8s CronJob YAML.
**Storage**: PostgreSQL 15 (per-tenant DBs); Redis (cache); S3-compatible object store for backup offsite copy (configurable provider; credentials in feature 022 vault).
**Testing**: Tests are NOT part of mandatory scope. CI gates (unit/contract/migrations dry-run/OpenAPI coverage/static checks) are required for the gate matrix; do not execute tests in this plan.
**Target Platform**: Linux server backend, browser frontend; ops automation runs on systemd hosts and k8s clusters.
**Project Type**: AMAN ERP web application — backend + frontend + ops.
**Performance Goals**: P95 financial report < 800ms at largest tenant size; period-stats latency −70% vs baseline; journal/account/date EXPLAIN buffer reads −50% vs baseline; GlobalSearch first-result < 250ms P95; dashboard widget updates < 5s after relevant write.
**Constraints**: Decimal/NUMERIC end-to-end (no float coercion in rollup); tenant-scoped cache keys (linter-enforced); fail-loud on Redis outage (no silent MemoryCache fallback in prod); `CREATE INDEX CONCURRENTLY` where supported; no online migration that locks `audit_logs` for more than the partition attach/detach window; account-sign rules read from `account_classifications` (feature 022), never from code prefixes; KPI/backup events route through feature 024 dispatcher; restore gated by HMAC-signed token from feature 022 vault.
**Scale/Scope**: Multi-tenant ERP; in-scope routers list derived from `git log` last-90-days churn (recorded in `research.md`).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Required Evidence | Status |
|------|-------------------|--------|
| Financial precision | Reports keep `Decimal` end-to-end; rollup type-coercion removed (FR-200); trial balance tolerance configurable (`reports.trial_balance.tolerance` default 0.01); contra accounts reflected via `account_classifications.normal_side` | PASS |
| Tenant isolation | All cache keys include `tenant_id` (linter `scripts/check_cache_keys.py`); MV definitions filter by `tenant_id` in primary index; KPI/search/backup tables carry `tenant_id`; `dashboard:{tenant}:{role}` WS channel | PASS |
| GL integrity | Income statement, balance sheet, trial balance derive from `journal_lines` / `account_classifications`; opening balances sourced from `je_source='opening_balance'` (feature 022 enum); no shadow ledger introduced | PASS |
| Security boundary | New endpoints declared with `require_sensitive_permission` (`reports.cache.refresh`, `ops.scheduler.admin`, `ops.restore`, `kpi.admin`); cache-required outage returns 503 not silent fallback; restore confirm token HMAC-signed via feature 022 vault | PASS |
| Regulatory settings | No statutory % / threshold introduced; backup retention / cache TTL / scheduler interval all configurable via `company_settings` | PASS |
| Calculation centralization | Sign logic centralised in `services/reports/sign_rules.py` reading classifier; period stats reader is one helper; `useExchangeRate` is the single FX consumer; FX cache is single source | PASS |
| Report consistency | All in-scope reports derive from GL (`journal_lines`) or documented GL-backed MVs (`mv_daily_financial_chart`, `mv_period_stats`); MV refresh / on-demand refresh both audited | PASS |
| Concurrency | No new mutating balance/state path. MV refresh uses `REFRESH MATERIALIZED VIEW CONCURRENTLY`. Scheduled jobs idempotent on `(job_id, scheduled_for, attempt)` UNIQUE | PASS |
| Query discipline | BRIN + composite indexes; baseline + post-change EXPLAIN required; partitioning of `audit_logs`; warm-up bounded; pagination preserved on every report endpoint | PASS |
| UI consistency | DataTable / inline errors / i18n / destructive confirmation already standard; this plan tightens (formatNumber, useApi, focus-visible, semantic forms, mobile-table, ErrorBoundary route preservation) | PASS |
| Schema sync | Every migration in this feature updates `database.py` / canonical DDL module in the same scope; covered by CI gate `scripts/check_schema_sync.py` | PASS |
| Artifact boundaries | `data-model.md` lists table names + critical fields only; no full DDL emitted | PASS |
| Spec format | No user stories generated; spec uses requirements / acceptance criteria / edge cases | PASS |

No violations. **Complexity Tracking** is empty.

### Post-Design Re-evaluation

After producing `research.md`, `data-model.md`, `contracts/*.yaml`, and `quickstart.md`, the gates above were re-evaluated. All thirteen gates remain **PASS**:

- The cache-backend policy (Redis required in production with circuit breaker), per-domain scoped invalidation, and the `tenant_id`-segment linter preserve **Tenant isolation**, **Cache discipline**, and **Defence in depth**.
- BRIN + composite indexes, monthly partitioning of `audit_logs`, and the MV refresh path keep **Query discipline** and **Concurrency** intact while reducing read cost.
- KPI definitions / evaluations, reactive dashboards, GlobalSearch registry, scheduler monitoring, restore confirm-token flow, backup automation, and the `/health/detailed` adapter aggregator are all additive and consume the contracts already shipped by features 022 / 023 / 024 — nothing is reimplemented (**Reuse**).
- All new DDL touched by migrations also lands in the canonical schema location (CI gate enforced) — **Schema sync** holds.
- `data-model.md` lists table names + critical fields only with no full DDL — **Artifact boundaries** holds.
- Spec contains requirements, acceptance criteria, edge cases, and assumptions but no user stories — **Spec format** holds.

No new constitutional violations introduced. **Complexity Tracking** remains empty.

## Design Artifact Rules

`data-model.md` lists entity/table names, critical fields, relationships, validation rules, and state transitions only. No full DDL.

## Project Structure

### Documentation (this feature)

```text
specs/025-reports-frontend-ops-maturity/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── reports-cache.yaml
│   ├── search-registry.yaml
│   ├── kpi-admin.yaml
│   ├── ops-scheduler.yaml
│   ├── ops-restore.yaml
│   ├── health-detailed.yaml
│   └── locale-defaults.yaml
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
backend/
├── alembic/versions/                       # new migrations: MVs, BRIN, composite indexes, audit_logs partitioning, kpi/search/scheduled_job_runs/backup_runs/break_glass tables, party phase 2
├── db_ddl/                                 # canonical DDL updates kept in sync per schema-sync gate
├── routers/
│   ├── reports.py                          # cache headers + on-demand refresh endpoint
│   ├── search.py                           # /search/registry + observability
│   ├── kpi.py                              # KPI admin endpoints
│   ├── ops_scheduler.py                    # scheduler monitoring + Run-now
│   ├── ops_restore.py                      # restore endpoint
│   ├── health.py                           # /health/detailed aggregator
│   └── locale.py                           # /locale/defaults
├── services/
│   ├── reports/
│   │   ├── sign_rules.py                   # classifier-driven sign helper
│   │   ├── period_stats_reader.py          # MV-backed reader
│   │   ├── trial_balance.py                # tolerance + contra fix
│   │   └── balance_sheet.py                # sign refactor
│   ├── cache/
│   │   ├── backend.py                      # backend selection + circuit breaker
│   │   ├── headers.py                      # X-Cache-Hit / X-Cache-TTL middleware
│   │   ├── invalidation.py                 # scoped invalidation registry
│   │   └── warmup.py                       # boot warm-up + audited refresh
│   ├── kpi/
│   │   ├── evaluator.py                    # idempotent on (kpi_id, window_start)
│   │   └── dispatch.py                     # adapter to feature 024 dispatcher
│   ├── dashboard/
│   │   └── ws_publisher.py                 # dashboard:{tenant}:{role}
│   ├── search/
│   │   └── registry.py                     # entity → label/route/icon
│   ├── parties/
│   │   └── unification_phase2.py           # legacy views over `parties`
│   ├── scheduler/
│   │   ├── idempotency.py                  # scheduled_job_runs writer
│   │   └── monitor.py                      # status reader for UI
│   └── ops/
│       ├── backup.py                       # backup orchestrator + offsite copy
│       └── restore.py                      # dry-run + confirm token + execute
├── adapters/
│   └── health.py                           # uniform health_check() registry
├── scripts/
│   ├── check_openapi_coverage.py           # extended
│   ├── check_sql_parameterization.py       # extended
│   ├── check_cache_keys.py                 # NEW (tenant prefix)
│   ├── check_schema_sync.py                # NEW (database.py vs migrations)
│   ├── check_frontend_number_format.py     # NEW (toFixed/parseFloat)
│   ├── check_frontend_window_location.py   # NEW (with allow-list)
│   ├── check_frontend_i18n_strings.py      # NEW (Arabic literals)
│   └── backup_postgres.sh                  # extended (offsite + retention guard)
└── workers/
    └── notifications_dispatcher_consumer/  # already provided by 024; no change

frontend/
├── src/
│   ├── hooks/
│   │   ├── useApi.js                       # {data, loading, error, refetch}
│   │   ├── useDebounce.js
│   │   └── useExchangeRate.js
│   ├── lib/
│   │   ├── formatNumber.js                 # ROUND_HALF_UP-aligned format
│   │   ├── apiClient.js                    # central error handler interceptor
│   │   └── routing/external-urls.ts        # window.location allow-list
│   ├── components/
│   │   ├── ErrorBoundary.jsx               # useNavigate + state preserve
│   │   ├── DataTable/                      # mobile-table strategy
│   │   └── primitives/                     # :focus-visible token
│   ├── pages/
│   │   ├── ops/Scheduler.jsx               # scheduler monitor UI
│   │   ├── reports/                        # cache header chip
│   │   └── search/GlobalSearch.jsx         # registry-driven, debounced
│   └── styles/
│       ├── tokens.css                      # --ring token
│       └── print.css                       # @media print isolation
├── vite.config.js                          # CSS splitting + bundle budget
├── vite-bundle-budget.json                 # NEW
└── .stylelintrc.cjs                        # focus-visible rule

ops/
├── systemd/aman-backup.service             # NEW
├── systemd/aman-backup.timer               # NEW
├── k8s/cronjob-backup.yaml                 # NEW
├── k8s/worker-deployment.yaml              # liveness + restartPolicy: always
└── docs/
    ├── RUNBOOK.md                          # restore section + scheduler policy
    ├── perf/index-baselines.md             # NEW (EXPLAIN before/after)
    ├── perf/period-stats-baseline.md       # NEW
    ├── partitioning-plan.md                # NEW
    ├── party-unification.md                # NEW (phase 2 plan)
    └── reports/trial-balance.md            # NEW (tolerance + contra docs)

.github/workflows/
├── ci.yml                                  # lint + type + unit + contract + migrations dry-run + OpenAPI coverage + bundle budget + SQL parameterization + cache-keys + i18n + frontend-number-format + window-location + schema-sync
└── break-glass.yml                         # required-reviewer + audit row writer
```

**Structure Decision**: Web application (backend + frontend) plus an `ops/` directory for systemd / k8s artefacts and runbooks. No mobile changes. Migrations live in `backend/alembic/versions/`; canonical DDL stays in sync via `scripts/check_schema_sync.py`.

## Complexity Tracking

> Empty — no constitutional violations.
