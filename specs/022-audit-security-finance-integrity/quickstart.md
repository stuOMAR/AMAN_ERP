# Quickstart: Audit & Security + Finance Integrity Remediation

**Feature**: 022-audit-security-finance-integrity

This guide describes how an implementer brings the change set up locally and exercises the new contracts. It assumes the standard AMAN ERP dev environment (`safe-start.sh`, tenant DB, Redis up).

## 1. Apply migrations

```bash
cd backend
alembic upgrade head
```

The migrations introduced by this feature (in order):

1. `022a_audit_outbox` — creates `audit_outbox`, adds `audit_logs.critical`.
2. `022b_integration_credentials` — creates the unified vault.
3. `022c_account_classifications` — creates the table and seeds defaults from current code-range heuristics.
4. `022d_recurring_template_review` — adds `review_threshold`, `auto_approve`, `expense_category_id` (with backfill).
5. `022e_employee_receipt_settlements` — creates the new table.
6. `022f_treasury_balance_trigger` — installs the GL-context trigger on `treasury_accounts`.
7. `022g_je_source_normalize` — normalizes legacy `source` values + adds CHECK enum.
8. `022h_device_fingerprints_login_geo` — creates the two privacy-safe seam tables.

After upgrade, confirm `backend/db_ddl/tenant_schema.py` and `backend/database.py` reflect the same schema (the implementation tasks update them alongside each migration).

## 2. Configure settings

Insert/update the new keys in `company_settings` for the tenant under test. Defaults are documented in [data-model.md](data-model.md#settings-keys-in-company_settings); minimum required to verify behavior:

```sql
-- per tenant
INSERT INTO company_settings (key, value) VALUES
  ('reconciliation.drift_tolerance', '0.01'),
  ('gl.je_epsilon', '0.005'),
  ('fiscal.allow_drafts_in_closed_period', 'false'),
  ('expenses.cost_center_policy', 'warn'),
  ('webhook.ratelimit.max_requests', '120'),
  ('webhook.ratelimit.window_seconds', '60'),
  ('bank_feed.failure_alert_threshold', '3')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
```

## 3. Start backend and worker

```bash
./safe-start.sh
```

This brings up the API, the audit-outbox flush worker, and the recurring-JE/auto-approve scheduler. Confirm the startup log lists:

- `permissions.discover: OK (N sensitive endpoints wrapped)`
- `audit.outbox.worker: started (batch_size=200, sla=60s)`
- `treasury.trigger: tg_treasury_balance_authority installed`

## 4. Smoke checks

### 4.1 Audit atomicity

```python
from backend.database import transactional, get_db_connection
from backend.services.audit_writer import log_activity

with get_db_connection(tenant_id) as conn:
    with transactional(conn):
        log_activity(conn, action="smoke.test", entity_type="demo", entity_id=1, details={"k": "v"})
        raise RuntimeError("force rollback")
```

Expectation: no row appears in `audit_logs` for `smoke.test`. The same call without the `raise` produces a row within the configured SLA.

### 4.2 PII sanitizer

```python
from backend.services.audit_sanitizer import sanitize_for_audit

sanitize_for_audit(
    {"employee": {"salary": 10000, "iban": "SA00..."}},
    context="audit.test",
)
# -> {"employee": {"salary": "***", "iban": "***"}}
```

### 4.3 Sensitive-permission discovery

```bash
python -m backend.scripts.permissions_discover --strict
```

Expectation: exit code `0` and a printed table of every sensitive endpoint with its scope. Any unwrapped endpoint causes exit code `1` and is listed.

### 4.4 Reconciliation finalize drift guard

Create a reconciliation whose bank total is `1000.00` but whose linked GL account balance at cut-off is `999.50`. Call:

```http
POST /api/finance/reconciliations/{id}/finalize
```

Expectation: HTTP 409 with body containing `gl_total`, `bank_total`, `difference`, `tolerance`, `unmatched_lines`. State remains `draft`. Adjust the matching to bring drift inside tolerance and finalize again — HTTP 200.

### 4.5 Account classifier

```python
from backend.services.account_classifier import classify
classify(account_id)
# -> {"statement_category": "asset", "sign": +1, "aggregation_hint": None}
```

Change the classification via the admin endpoint and observe the next Balance Sheet run reflect the new category — without code changes.

### 4.6 Treasury balance authority

```sql
-- without GL context: must fail
UPDATE treasury_accounts SET current_balance = current_balance + 1 WHERE id = :id;
-- ERROR: treasury balance can only be modified through gl context

-- with GL context (set by official service):
SELECT set_config('aman.gl_context', 'on', true);
UPDATE treasury_accounts SET current_balance = current_balance + 1 WHERE id = :id;
-- OK
```

### 4.7 Recurring template review

Create a recurring template with `review_threshold = 1000`, `auto_approve = true`, amount `1500`. Trigger the scheduler. Expectation: a `pending_review` record is created; no JE is posted until the approver acts.

Set amount `500` instead — Expectation: JE posts immediately and is audited as auto-approved.

### 4.8 Webhook rate limit

Send 130 webhook requests in 60 seconds with default settings. Expectation: ~120 succeed, the rest receive HTTP 429, and an audit row is written for each rejection.

### 4.9 Credential rotation

Use the admin UI (or `POST /api/admin/credentials/{id}/rotate`) to rotate an SMTP credential. Expectation: a new `active` row, the old row moves to `rotating`, then ages to `soft_deleted` after grace; every step writes an audit row.

## 5. CI gates

These run in CI but can be invoked locally:

```bash
python scripts/audit_writer_lint.py
python -m backend.scripts.permissions_discover --strict
python scripts/check_account_code_ranges.py    # added by this feature
```

All three must exit `0` for the change set to land.

## 6. Rollback notes

- Migrations are designed to be reversible at the schema level; data backfills (source normalization, classification seed) preserve original values where reversible.
- The treasury trigger can be dropped with a single migration if a critical issue is found; the application path keeps working without it (it just loses defense-in-depth).
- The audit outbox can be drained synchronously by running the worker manually; if it must be disabled, set `audit.outbox.enabled = false` in `company_settings` and the writer will fall back to direct insert during the rollback window. (This fallback is intentionally last-resort and audited.)

## 7. What is **not** covered here

Tests are not written by this plan; the implementer adds them where risk warrants. End-to-end provider integrations for IP-geo / device-fingerprint heuristics are deliberately deferred; only the data model and the `evaluate_login_risk()` seam ship in this feature.
