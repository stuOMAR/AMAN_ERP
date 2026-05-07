# Contract: Bulk Salary Increment

## Endpoint

`POST /api/hr/employees/bulk-salary-increment`

## Permission
`require_sensitive_permission('hr.salary.write')`

## Request

```json
{
  "rows": [
    {"employee_id": 123, "new_salary": "8500.0000", "effective_from": "2026-06-01", "change_reason": "annual_review"}
  ],
  "allow_backdated": false,
  "atomic": false,
  "dry_run": false
}
```

## Response

```json
{
  "outcomes": [
    {"employee_id": 123, "result": "updated", "history_id": 9001}
  ],
  "summary": {"updated": 1, "skipped": 0, "errors": 0}
}
```

## Behavior

- Per-row outcome: `updated` | `skipped` (no change) | `error` (with code + message).
- `effective_from` falling within an existing locked payroll period is rejected per row unless `allow_backdated=true` AND caller has `payroll.allow_backdated` permission.
- Each `updated` row writes `employee_salary_history` and updates `employees.salary` (encrypted).
- `dry_run=true` returns outcomes without persisting.
- `atomic=true` wraps all rows in one `transactional()`; default `false` commits per row to support large batches.
- Audit: one batch envelope event + per-row events.

## Errors (per-row)

| Code | When |
|------|------|
| `salary.unchanged` | `new_salary` equals current. |
| `salary.backdated_blocked` | `effective_from` < latest locked period for employee and `allow_backdated=false`. |
| `salary.invalid_employee` | Employee not found / inactive. |
| `salary.invalid_amount` | `new_salary` ≤ 0 or wrong precision. |
