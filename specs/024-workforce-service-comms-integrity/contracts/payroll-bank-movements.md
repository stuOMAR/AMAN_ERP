# Contract: Payroll → Bank Movements

## Purpose
Every payslip paid via WPS produces exactly one `bank_transactions` row, idempotently, in the same `transactional()` as WPS file commit.

## Helper

`services/payroll/bank_movements.py::record_payroll_bank_movements(period_id, run_id) -> [bank_transaction_id]`

## Behavior

- Reads payslips for `(period_id, run_id)`.
- Inserts one row per payslip with:
  - `source='payroll_run'`, `source_id=run_id`
  - `external_ref='<wps_file_id>:<payslip_id>'`
  - `direction='debit'`, `amount=payslip.net_pay`, `currency=payslip.currency`
  - `bank_account_id=run.disbursement_bank_account_id`
  - `posted_at=now()`
- Idempotent on partial unique `(tenant_id, source, source_id, external_ref) WHERE source='payroll_run'`. Re-call returns existing ids.

## Errors

| Code | When |
|------|------|
| 409 `payroll.bank_movements_already_recorded` | Returned only when explicit `strict=true` is passed and rows already exist. |
| 422 `payroll.run_not_committed` | Run state is not `wps_committed`. |
