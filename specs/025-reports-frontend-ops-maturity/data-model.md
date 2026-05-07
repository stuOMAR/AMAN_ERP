# Phase 1 — Data Model: Reports + Frontend/Ops Maturity (R7 + R8)

**Date**: 2026-05-02
**Branch**: `025-reports-frontend-ops-maturity`

> Per the constitution and AMAN ERP rule: this document mentions table names + critical fields + relationships + validation rules + state transitions only. **No full DDL.**

---

## A. Materialized Views (new)

### `mv_daily_financial_chart`

- **Purpose**: Per-day revenue / expense / cash position per tenant + company; powers the dashboard daily chart.
- **Critical columns**: `tenant_id`, `company_id`, `date`, `revenue NUMERIC`, `expense NUMERIC`, `cash_position NUMERIC`, `refreshed_at`.
- **Source**: GL — `journal_lines` joined with `accounts` and `account_classifications` (feature 022).
- **Indexes**: unique `(tenant_id, company_id, date)` (concurrent refresh requirement).
- **Refresh**: `REFRESH MATERIALIZED VIEW CONCURRENTLY` on schedule (`reports.mv.refresh_interval_minutes` default 15) and on demand.

### `mv_period_stats`

- **Purpose**: Per-period totals replacing the per-request `calculate_period_stats` helper.
- **Critical columns**: `tenant_id`, `company_id`, `period_id`, `period_start`, `period_end`, `revenue`, `expense`, `gross_profit`, `operating_margin`, `cash_in`, `cash_out`, `refreshed_at`.
- **Source**: GL — `journal_lines` aggregated by classifier category over the fiscal period.
- **Indexes**: unique `(tenant_id, company_id, period_id)`.

---

## B. New Tables

### `kpi_definitions`

- **Critical columns**: `id`, `tenant_id`, `kpi_code` (unique per tenant), `metric_source` (enum: `report_key | classifier_category`), `metric_reference` (text — report code or classifier category), `threshold_value NUMERIC`, `comparison_op` (enum: `lt | lte | gt | gte | eq`), `channels JSONB` (list from `email | sms | push | in_app | webhook`), `evaluation_interval_minutes INT`, `is_active BOOL`, `created_by`, `audit fields`.
- **Validation**: `evaluation_interval_minutes ≥ 5`; `channels` must be a non-empty subset of allowed channels; `kpi_code` is `[a-z0-9_]+`.
- **Relationships**: `tenant_id` references `tenants`; `created_by` references `users`.
- **State transitions**: `is_active=true` ↔ `is_active=false` (toggle audited).

### `kpi_evaluations`

- **Critical columns**: `id`, `kpi_id`, `tenant_id`, `evaluation_window_start TIMESTAMPTZ`, `evaluation_window_end TIMESTAMPTZ`, `value NUMERIC`, `breached BOOL`, `notified_at TIMESTAMPTZ NULL`, `created_at`.
- **Validation**: UNIQUE `(kpi_id, evaluation_window_start)` — idempotency guarantee.
- **Relationships**: `kpi_id → kpi_definitions`.
- **State transitions**: `breached=true && notified_at IS NULL` → dispatcher fires → `notified_at` set.

### `search_query_logs`

- **Critical columns**: `id`, `tenant_id`, `actor_id`, `query`, `result_count INT`, `latency_ms INT`, `entity_hits JSONB` (`{customer:3, invoice:5, ...}`), `created_at`.
- **Validation**: `result_count ≥ 0`; `latency_ms ≥ 0`; `query` length ≤ 256.
- **Retention**: configurable `search.query_logs_retention_days` (default 90); cleanup scheduler.

### `scheduled_job_runs`

- **Critical columns**: `id`, `job_id` (string identifier of the scheduler job), `scheduled_for TIMESTAMPTZ`, `attempt INT DEFAULT 1`, `status` (enum: `running | succeeded | failed | idempotent_skip`), `started_at`, `finished_at`, `error TEXT NULL`, `tenant_id NULL` (nullable for cross-tenant jobs).
- **Validation**: UNIQUE `(job_id, scheduled_for, attempt)`; `attempt ≥ 1`.
- **State transitions**: `running → succeeded | failed`; `idempotent_skip` is a terminal initial state.

### `backup_runs`

- **Critical columns**: `id`, `backup_id` (UUID), `started_at`, `finished_at`, `size_bytes BIGINT`, `checksum TEXT`, `offsite_uri TEXT NULL`, `status` (enum: `running | succeeded | failed | offsite_failed`), `tenant_inventory JSONB` (list of tenant DBs included), `created_by`.
- **Validation**: `checksum` non-null on `succeeded`; `offsite_uri` non-null on `succeeded` (post-upload).
- **Retention**: `backup.retention_days` with `backup.min_retained` floor.

### `break_glass_audit_log`

- **Critical columns**: `id`, `actor_id`, `pr_id` TEXT, `gates_skipped JSONB` (list of gate names), `reason TEXT`, `secondary_reviewer_id`, `created_at`.
- **Validation**: `gates_skipped` non-empty; `secondary_reviewer_id IS NOT NULL`.

---

## C. Partitioned Tables

### `audit_logs` (partitioned by RANGE on `created_at`, monthly)

- **Migration sketch**: rename existing `audit_logs` → `audit_logs_legacy_<yyyymm>`; create new partitioned `audit_logs` with the same column set; ATTACH the legacy table as the historical partition; CREATE the current and the next month's partitions.
- **Retention**: monthly scheduler creates the next-next month's partition in advance and DETACHes / DROPs partitions older than `audit.retention_months` (default 36).
- **Indexes**: BRIN on `created_at` per partition; B-tree on `(tenant_id, actor_id, created_at)` per partition.
- **Critical columns retained**: `id`, `tenant_id`, `actor_id`, `entity_type`, `entity_id`, `action`, `details JSONB`, `created_at`.

---

## D. Indexes (additive)

| Table | Index | Purpose |
|---|---|---|
| `audit_logs` | BRIN(`created_at`) | Time-range scans on append-mostly data |
| `journal_lines` | BRIN(`posting_date`) | Time-range scans for reports |
| `journal_lines` | BTREE(`tenant_id, account_id, posting_date`) | journal/account/date report ORDER BY |
| `journal_entries` | BTREE(`tenant_id, source, source_id`) | source-traceability lookups (consumes feature 022 JESource enum) |
| `inventory_transactions` | BRIN(`transaction_date`) | Inventory time-range scans |
| `inventory_transactions` | BTREE(`tenant_id, item_id, transaction_date`) | Item activity report |

> Migrations use `CREATE INDEX CONCURRENTLY`. Baseline + post-change `EXPLAIN (BUFFERS)` recorded under `docs/perf/index-baselines.md`.

---

## E. Party-Model Phase 2

### `parties` (existing — extended consumer)

- Single source of truth for customer / supplier / employee identity.
- **Critical columns**: `id`, `tenant_id`, `legal_name`, `display_name`, `tax_number NULL`, `country`, `audit fields`.

### `party_roles` (existing — extended consumer)

- **Critical columns**: `id`, `party_id`, `role` (enum: `customer | supplier | employee`), `legacy_id NULLABLE`, `started_at`, `ended_at NULL`, `metadata JSONB`.
- **Validation**: UNIQUE `(party_id, role)` while `ended_at IS NULL`.
- **State transitions**: per-role activation / deactivation captured by `started_at` / `ended_at`.

### Legacy views (transition aids — read-only)

- `customers` → view over `parties` JOIN `party_roles` WHERE `role='customer'`.
- `suppliers` → view over `parties` JOIN `party_roles` WHERE `role='supplier'`.
- `employees` → view over `parties` JOIN `party_roles` WHERE `role='employee'`.
- Writes go through `services/parties/unification_phase2.py`. Legacy direct inserts gated by a deprecation warning + audit until cutover; then removed in a follow-up release.

---

## F. Cache & Settings (additive — no new tables)

The following are added to `company_settings` (existing JSONB store from feature 022):

| Key | Type | Default | Purpose |
|---|---|---|---|
| `cache.backend` | enum `redis|memory` | `redis` | Backend selection |
| `cache.circuit_breaker.failures` | int | 5 | Open the breaker after N consecutive failures |
| `cache.circuit_breaker.cool_down_seconds` | int | 30 | Cool-down before re-probe |
| `reports.mv.refresh_interval_minutes` | int | 15 | MV refresh cadence |
| `reports.cache.ttl[<code>]` | map<int> | per-code | Per-report cache TTL |
| `reports.warmup_keys` | list<str> | curated | Keys warmed on boot |
| `reports.kpi.evaluation_interval_minutes` | int | 15 | KPI evaluator cadence |
| `reports.income_statement.include_headers` | bool | `true` | Header rows on income statement |
| `reports.trial_balance.tolerance` | numeric | 0.01 | Trial balance balance tolerance |
| `audit.retention_months` | int | 36 | Partition retention |
| `search.autocomplete_debounce_ms` | int | 300 | UI debounce |
| `search.query_logs_retention_days` | int | 90 | Search-log retention |
| `fx.cache_ttl_minutes` | int | 30 | FX cache TTL |
| `fx.stale_tolerance_minutes` | int | 120 | Acceptable stale window for `useExchangeRate` |
| `backup.local_time` | string `HH:MM` | `02:00` | Daily backup time |
| `backup.retention_days` | int | 30 | Retention floor |
| `backup.min_retained` | int | 3 | Minimum backups never deleted |
| `backup.max_consecutive_failures` | int | 3 | Dead-letter threshold |
| `backup.offsite_provider` | enum | `s3` | Provider key (vault holds creds) |

All settings are tenant-scoped where applicable.

---

## G. Relationships Diagram (textual)

```
account_classifications  ──▶  mv_period_stats / mv_daily_financial_chart
account_classifications  ──▶  services/reports/sign_rules.py  ──▶  income_statement / balance_sheet / trial_balance / KPI evaluator
journal_lines + journal_entries  ──▶  MVs + reports
kpi_definitions  1───*  kpi_evaluations
search_query_logs  *───  per-query observability
scheduled_job_runs  ──▶  services/scheduler/idempotency.py
backup_runs  ──▶  services/ops/backup.py + restore.py
audit_logs (partitioned)  ──▶  consumed by all writers via feature 022 outbox
parties + party_roles  ──▶  legacy views customers/suppliers/employees
```

---

## H. Validation & State Summary

- All cache keys MUST include `tenant_id` segment (linter-enforced).
- All MVs MUST be filterable by `tenant_id` (primary index includes `tenant_id`).
- KPI evaluation rows are append-only; updates only to `notified_at` after dispatch.
- `scheduled_job_runs` enforces idempotency via UNIQUE `(job_id, scheduled_for, attempt)`.
- `backup_runs` MUST refuse retention deletion below `backup.min_retained`.
- Partition retention scheduler MUST refuse to drop partitions when the resulting count would fall below the configured retention window.
- Party-roles UNIQUE `(party_id, role)` while `ended_at IS NULL` prevents duplicate active roles.
