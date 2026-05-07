# Quickstart — Feature 024 (R5 + R6)

This is the operational guide for bringing the HR/Payroll/PII + FSM/DMS/Notifications remediation up in a tenant database. Follow steps in order.

## 1. Prerequisites

- Features 022 and 023 deployed and green (audit outbox writer, sensitive-permission gate, vault, classifier, JESource enum, Order→Invoice service, account-mapping resolver, webhooks dispatcher).
- PostgreSQL extensions: `btree_gist` available (`CREATE EXTENSION IF NOT EXISTS btree_gist;` runs in 024b).
- ClamAV daemon reachable via Unix socket or TCP. Credentials in 022's vault under `clamav.endpoint` (host/port or socket path) and optional `clamav.auth`.
- SMTP / SMS / push provider credentials in 022's vault.

## 2. Migration order

```
024a_hr_pii_encryption.py
024b_payroll_period_overlap.py
024c_payroll_period_reversal_state.py
024d_payslip_uniqueness.py
024e_acc_map_loans_advances_split.py
024f_bank_codes.py
024g_payroll_entries_period_id_align.py
024h_service_pricelists.py
024i_service_contracts_extension.py
024j_service_orders_extension.py
024k_technicians_profile.py
024l_maintenance_plans.py
024m_dms_attachment_links.py
024n_documents_scan_state.py
024o_storage_quotas.py
024p_notifications_queue.py
024q_email_templates_finalize.py
024r_approval_tokens.py
```

Run via tenant migration runner: `python -m backend.db_ddl.tenant_runner --upgrade head`.

## 3. Settings seed (per tenant, after migrations)

```sql
INSERT INTO company_settings (key, value) VALUES
  ('hr.salary_encryption_enabled', 'true'),
  ('hr.service_years_policy', 'months_precise'),
  ('company_timezone', 'Asia/Riyadh'),
  ('payroll.allow_backdated_increment', 'false'),
  ('fsm.auto_assign_threshold', '0.75'),
  ('fsm.zero_revenue_approval_required', 'true'),
  ('dms.tenant_quota_mb', '51200'),
  ('dms.user_quota_mb', '2048'),
  ('dms.orphan_retention_days', '30'),
  ('dms.storage_root', '/var/aman/dms'),
  ('dms.scan_max_pending_minutes', '30'),
  ('dms.scan_engine', 'clamav'),
  ('dms.allowed_mime_groups', '["image/*","application/pdf","application/zip","application/vnd.openxmlformats-officedocument*","text/plain","text/csv"]'),
  ('notifications.max_attempts', '5'),
  ('notifications.dedupe_window_seconds', '300'),
  ('notifications.default_locale', 'en'),
  ('auth.approval_token_ttl_minutes', '1440')
ON CONFLICT (key) DO NOTHING;
```

PII encryption backfill: 024a runs `python -m backend.scripts.encrypt_existing_pii --tenant=<id>` post-migration to encrypt pre-existing salary/IBAN/etc.

Bank codes seed: loaded automatically by 024f from `backend/db_ddl/seed_bank_codes.json`.

## 4. Startup banner expectations

Backend startup MUST log:

```
[startup] sensitive permission discovery: hr.pii ✓, payroll.reverse ✓, hr.salary.write ✓, contract.renew ✓, dms.audit_admin ✓
[startup] notifications workers: email ✓, sms ✓, push ✓, in_app ✓, webhook ✓
[startup] schedulers: preventive_maintenance ✓, dms_orphan_cleanup ✓, dms_av_scanner ✓, payroll_subscription ✓, ticket_allowance_accrual ✓, approval_token_sweeper ✓
[startup] clamav endpoint reachable: <socket-or-host:port> ✓
[startup] btree_gist: ✓
[startup] vault keys present: approval_token_signing_key (kid=1) ✓, dek_pii_<tenant> ✓
```

If `dms.scan_engine='none'`, log `WARN: dms anti-malware disabled (dev only)`.

## 5. Smoke checks

1. **HR PII default mask**:
   - `GET /api/hr/employees/{id}` as user without `hr.pii` → returns `"salary": "****"`, `"iban": "****"`, etc.

2. **HR PII unmask**:
   - `GET /api/hr/employees/{id}/pii` as user with `hr.pii` → returns plaintext; audit row with `action='hr.pii.read'`.

3. **Payroll period overlap**:
   - Create period `2026-06-01..2026-06-30`.
   - Try to create period `2026-06-15..2026-07-15` → HTTP 409 `payroll.period_overlap`.

4. **Payroll reversal**:
   - Lock a period.
   - `POST /api/payroll/periods/{id}/reverse` → state `reversed`, GL inverse posted, compensating bank rows present.
   - Re-call → idempotent replay (no duplicate JE).

5. **Bulk salary increment**:
   - Submit 3 rows; one with `effective_from` inside locked period.
   - Without `allow_backdated`: that row returns `salary.backdated_blocked`; others `updated`.

6. **Service pricelist precedence**:
   - Tenant pricelist for item X = 100; customer pricelist = 90; contract pricelist = 80.
   - Resolve with all three contexts → returns 80, level=`contract`.

7. **Contract renew → invoice via 023**:
   - Contract with `renew_policy='auto_with_invoice'` near end_date.
   - `POST /renew` → new contract row + Order→Invoice generates contract invoice (idempotent).

8. **DMS quota 413**:
   - Tenant at 99.9% of quota; upload 100MB → HTTP 413 `dms.quota_exceeded`.

9. **DMS quarantine**:
   - Upload EICAR test string → ClamAV worker transitions document to `quarantined`; download attempts return 451.

10. **Notifications dedupe**:
    - Call `notifications.dispatch(...)` twice with same payload within dedupe window → second call returns existing queue row.

11. **Approval-token replay**:
    - Issue token for `service_order.close_zero_revenue`.
    - Consume → action succeeds.
    - Replay same token → HTTP 409 `approval_token.consumed`.
    - Wait past TTL with new token → HTTP 410 `approval_token.expired`.

## 6. CI lint runs

Add to existing CI lint stage:

```
python scripts/check_hr_pii_endpoints.py
python scripts/check_payroll_period_writers.py
python scripts/check_notifications_dispatch.py
python scripts/check_storage_paths.py
python scripts/check_hardcoded_email_bodies.py
python scripts/check_maintenance_writers.py
python scripts/check_approval_tokens.py
python scripts/check_attachment_links.py
python scripts/check_hardcoded_bank_codes.py
```

Each must exit 0 before merge.

## 7. Rollback notes

- Migrations 024a..024r are reversible per Alembic discipline; salary backfill keeps a side table (`employees_salary_backfill_<ts>`) for one release for emergency restore.
- ClamAV outage: set `dms.scan_engine='none'` to allow uploads (warning logged); files remain in `pending_scan` pending re-enable. Do NOT auto-mark as `clean`.
- Notifications worker deadletter inflation: pause channel via `notifications.<channel>.paused = true` setting; admin reprocess endpoint moves rows back to `pending` after fix.
- Encryption key rotation: 022's vault rotation procedure; 024 PII reads carry `kid` so rotation is rolling.

## 8. Operational metrics (optional)

Recommended Prometheus counters/gauges (existing metrics infra):

- `aman_payroll_periods_overlap_rejected_total`
- `aman_payroll_reversal_total{result}`
- `aman_dms_documents_state{state}` (gauge by state)
- `aman_dms_scan_seconds` (histogram)
- `aman_notifications_queue_depth{channel,state}` (gauge)
- `aman_notifications_attempts_total{channel,result}`
- `aman_approval_tokens_total{result}`
- `aman_pii_unmask_total{field}`
