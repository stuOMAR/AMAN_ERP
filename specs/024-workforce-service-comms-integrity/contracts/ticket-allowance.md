# Contract: Ticket Allowance

## Purpose
Monthly accrual + periodic pay-out of employee ticket (travel) allowance.

## Helpers

`services/hr/ticket_allowance.py::accrue_monthly(as_of_date)` — scheduler entry-point per tenant.
`services/hr/ticket_allowance.py::pay_out(employee_id, as_of_date)` — pay-out flow.

## Accrual Behavior

- For each active employee with `ticket_allowance_amount > 0`:
  - Monthly accrual = `ticket_allowance_amount / ticket_allowance_frequency_months`.
  - Posts JE via `gl_service` under `JESource.TICKET_ALLOWANCE`:
    - DR: payroll expense (mapping `acc_map_payroll.ticket_allowance_expense`)
    - CR: ticket allowance liability (`acc_map_payroll.ticket_allowance_account_id`)
  - Idempotent on `(tenant_id, source='ticket_allowance', source_id=f'{employee_id}:{as_of_year_month}')`.

## Pay-out Behavior

- When `(today - last_paid_at).months >= frequency_months` OR explicit pay-out call:
  - Reverses accumulated liability (DR liability, CR cash/clearing).
  - Sets `ticket_allowance_last_paid_at = today`.

## Errors

| Code | When |
|------|------|
| 409 `ticket_allowance.already_accrued` | Idempotent replay (returns existing JE). |
| 422 `ticket_allowance.no_mapping` | `acc_map_payroll.ticket_allowance_*` missing. |
