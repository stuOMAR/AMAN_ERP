# Quickstart: Reports + Frontend/Ops Maturity (R7 + R8)

**Branch**: `025-reports-frontend-ops-maturity` | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

This is an operator-and-implementer quickstart. It describes how to verify each major outcome of features R7 + R8 in the running system, and what configuration must be in place. It does not duplicate the spec; treat it as a smoke checklist.

## 1. Prerequisites (already shipped by 022 / 023 / 024)

- `account_classifications` populated for every tenant.
- `require_sensitive_permission` decorator and the secret vault in feature 022.
- Order→Invoice service and JESource enum from feature 023.
- Unified notifications dispatcher and `email_templates` from feature 024.
- HMAC-signed approval token helper from feature 022 vault.

## 2. Configure once per environment

Set the following under `company_settings` (or env, where noted):

```ini
# Cache
cache.backend = redis              # production
cache.circuit_breaker.failures = 5
cache.circuit_breaker.cool_down_seconds = 30

# Reports
reports.mv.refresh_interval_minutes = 15
reports.income_statement.include_headers = true
reports.trial_balance.tolerance = 0.01
reports.kpi.evaluation_interval_minutes = 15
reports.warmup_keys = ["coa:summary", "kpi:operating_margin", "dashboard:home"]

# Audit retention
audit.retention_months = 36

# Search
search.autocomplete_debounce_ms = 300
search.query_logs_retention_days = 90

# FX
fx.cache_ttl_minutes = 30
fx.stale_tolerance_minutes = 120

# Backup
backup.local_time = 02:00
backup.retention_days = 30
backup.min_retained = 3
backup.max_consecutive_failures = 3
backup.offsite_provider = s3       # creds in vault: ops.backup.s3.*
```

## 3. Migrations to apply (in order)

1. New tables: `kpi_definitions`, `kpi_evaluations`, `search_query_logs`, `scheduled_job_runs`, `backup_runs`, `break_glass_audit_log`.
2. MVs: `mv_daily_financial_chart`, `mv_period_stats` + unique indexes.
3. BRIN indexes: `audit_logs(created_at)`, `journal_lines(posting_date)`, `inventory_transactions(transaction_date)`.
4. Composite indexes per data-model §D.
5. `audit_logs` partitioning (rename → create partitioned → attach legacy → create current + next month).
6. Party-role views (`customers` / `suppliers` / `employees` as views over `parties` + `party_roles`).
7. `database.py` / canonical DDL updates kept in sync (CI gate `check_schema_sync.py`).

## 4. R7 verification

### Reports correctness

```bash
# Income statement should include header rows
curl -sS .../reports/income_statement?period_id=$P | jq '.rows[] | select(.is_header==true)'

# Trial balance tolerance
curl -sS .../reports/trial_balance?period_id=$P | jq '{balanced, tolerance: .tolerance, drift: .total_drift}'

# Contra accounts: a contra-revenue should reduce revenue, not add to it
curl -sS .../reports/income_statement?period_id=$P | jq '.totals.revenue_net'
```

### MV-backed period stats

```bash
# Should be a single MV select; check timing
time curl -sS .../reports/period_stats?period_id=$P > /dev/null
```

### Cache observability + outage policy

```bash
# Headers present
curl -sS -D - .../reports/income_statement?period_id=$P | grep -i '^x-cache-'

# Simulate Redis outage (in non-prod): cache-required endpoints return 503
sudo systemctl stop redis
curl -sS -o /dev/null -w '%{http_code}\n' .../reports/income_statement?period_id=$P  # expects 503
```

### KPI alert end-to-end

```bash
# Create a KPI breaching threshold immediately
curl -sS -X POST .../kpi/definitions -d @kpi_def.json
# Wait one cycle and confirm a notification was dispatched (feature 024 queue)
curl -sS .../kpi/evaluations?kpi_id=$KPI | jq '.[0] | {breached, notified_at}'
```

### GlobalSearch UI wiring

- Open the app, focus the GlobalSearch input.
- Type "AC" — autocomplete fires after 300ms idle.
- Click a result — navigation uses `useNavigate` (no full page reload).
- Confirm `search_query_logs` has a row.

### `/health/detailed`

```bash
curl -sS .../health/detailed | jq '{status, adapters: (.adapters | keys)}'
```

### Index baselines

- Run the queries listed in `docs/perf/index-baselines.md` before/after; buffer reads must drop ≥ 50% on the journal/account/date report.

### `audit_logs` partitioning

```sql
SELECT relname FROM pg_class
 WHERE relname LIKE 'audit_logs_%'
 ORDER BY relname;
```

## 5. R8 verification

### Frontend sweeps (CI gates)

Run locally before pushing:

```bash
python scripts/check_frontend_number_format.py
python scripts/check_frontend_window_location.py
python scripts/check_frontend_i18n_strings.py
python scripts/check_sql_parameterization.py
python scripts/check_cache_keys.py
python scripts/check_schema_sync.py
python scripts/check_openapi_coverage.py
```

All must report zero violations in scope.

### Bundle budget

```bash
cd frontend && npm run build
node scripts/bundle-budget.js   # fails if > vite-bundle-budget.json
```

### Scheduler monitoring UI

- Sign in as a user with `ops.scheduler.admin`.
- Open the Scheduler page; expect last/next-run rows for every job.
- Click "Run now" — confirm a `scheduled_job_runs` row with a fresh `attempt`.

### Idempotency clash

```bash
# Trigger the same job twice for the same scheduled_for
# Second insert must be absorbed as idempotent_skip
```

### Backup automation

```bash
# Manual run on a non-prod host
sudo systemctl start aman-backup.service
journalctl -u aman-backup.service -e
psql -c "SELECT status, size_bytes, offsite_uri FROM backup_runs ORDER BY started_at DESC LIMIT 1;"
```

### Restore (dry-run + execute)

```bash
# Step 1
curl -sS -X POST .../ops/restore/dry-run -d '{"backup_id":"<id>"}' | jq
# Step 2 (use the returned confirm_token)
curl -sS -X POST .../ops/restore -d '{"backup_id":"<id>","confirm_token":"<t>"}'
# Audit row must exist:
psql -c "SELECT * FROM audit_logs WHERE entity_type='backup_run' ORDER BY created_at DESC LIMIT 5;"
```

### Party phase 2 read parity

```bash
# Both should return matching projections during transition
psql -c "SELECT count(*) FROM customers;"
psql -c "SELECT count(*) FROM parties p JOIN party_roles r ON r.party_id=p.id WHERE r.role='customer' AND r.ended_at IS NULL;"
```

### CI/CD gate matrix

A PR that intentionally violates each gate should fail CI:

- introduce a `parseFloat(x)` in a screen → fails number-format gate.
- introduce `f"SELECT ... {var}"` in a router → fails SQL-parameterization gate.
- omit a `summary` on a new endpoint → fails OpenAPI coverage gate.
- add a cache key without `tenant_id` → fails cache-keys gate.
- diverge `database.py` from migration head → fails schema-sync gate.
- exceed bundle budget → fails bundle gate.

## 6. Rollback notes

- Cache backend can be flipped to `memory` only in dev/test.
- Each migration is reversible via `alembic downgrade -1` except the `audit_logs` partition cutover, which is reversible only by re-attaching the legacy table (documented in `docs/partitioning-plan.md`).
- Party views can be dropped to revert to legacy table reads; writes through the unified service must be paused first.
- Backup automation can be stopped via `systemctl disable aman-backup.timer` or by removing the k8s CronJob; backups already in offsite storage remain.

## 7. Out of scope for this verification

- HR/Payroll, FSM/DMS/Notifications (features 024).
- Sales/POS/ZATCA/Inventory (features 023).
- Settings JSONB typed model and tax-group junction (deferred).
