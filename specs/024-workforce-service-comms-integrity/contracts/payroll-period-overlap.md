# Contract: Payroll Period Overlap Prevention

## Purpose
Database-enforced guarantee that two non-reversed `payroll_periods` for the same tenant cannot overlap.

## Mechanism

`EXCLUDE USING gist (tenant_id WITH =, tstzrange(start_date, end_date, '[]') WITH &&) WHERE (state <> 'reversed')`

Requires `btree_gist` extension (created in migration 024b).

## Helper

`services/payroll/period_writer.py::create_period(tenant_id, start_date, end_date)` is the only writer.

## Errors

| Code | When |
|------|------|
| 409 `payroll.period_overlap` | INSERT/UPDATE violates the exclusion constraint. Body: `{conflicting_period_id, conflicting_range}`. |
| 422 `payroll.invalid_range` | `end_date < start_date`. |
