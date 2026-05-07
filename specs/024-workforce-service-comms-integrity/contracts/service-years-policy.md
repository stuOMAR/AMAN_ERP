# Contract: Service-Years Computation Policy

## Helper

`services/hr/service_years.py::compute_service_years(employee_id, as_of=today) -> Decimal`

## Behavior

Reads `company_settings.hr.service_years_policy`:

- `months_precise` (default):
  ```
  full_months = (as_of.year - hire.year) * 12 + (as_of.month - hire.month)
  if as_of.day < hire.day: full_months -= 1
  service_years = Decimal(full_months) / Decimal(12)  # ROUND_HALF_UP, 4 dp
  ```
- `days_365_25`:
  ```
  service_years = Decimal((as_of - hire).days) / Decimal('365.25')  # ROUND_HALF_UP, 4 dp
  ```

End-of-service indemnity, leave entitlement, and any service-year-driven calculation MUST call this helper.

## Errors

| Code | When |
|------|------|
| 422 `service_years.future_hire` | `hire_date > as_of`. |
| 422 `service_years.unknown_policy` | Setting value not in allowed enum. |
