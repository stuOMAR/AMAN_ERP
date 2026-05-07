# Contract: HTTP Endpoints (Feature 024)

> All endpoints declare `require_permission()`. Sensitive ones (marked **S**) additionally declare `require_sensitive_permission(<scope>)` per Principle IV. JSON only; Pydantic at boundaries; tenant resolved from session.

## HR / PII (R5)

| Method | Path | Permission | Notes |
|--------|------|------------|-------|
| GET | `/api/hr/employees/{id}` | `employees.read` | Returns masked PII by default. |
| GET | `/api/hr/employees/{id}/pii` | `employees.read` + **S** `hr.pii` | Returns unmasked PII; audited. |
| PATCH | `/api/hr/employees/{id}/pii` | `employees.write` + **S** `hr.pii` | Writes encrypted PII. |
| POST | `/api/hr/employees/bulk-salary-increment` | `employees.write` + **S** `hr.salary.write` | See `bulk-salary-increment.md`. |
| GET | `/api/hr/employees/{id}/salary-history` | `employees.read` + **S** `hr.pii` | Versioned. |

## Payroll (R5)

| Method | Path | Permission | Notes |
|--------|------|------------|-------|
| POST | `/api/payroll/periods` | `payroll.write` | Overlap-checked. |
| POST | `/api/payroll/periods/{id}/calculate` | `payroll.write` | `draft`→`calculated`. |
| POST | `/api/payroll/periods/{id}/lock` | `payroll.lock` | `calculated`→`locked`. |
| POST | `/api/payroll/periods/{id}/reverse` | **S** `payroll.reverse` | See `payroll-period-reversal.md`. |
| POST | `/api/payroll/runs/{id}/wps-commit` | `payroll.wps_commit` | Triggers `record_payroll_bank_movements`. |
| GET | `/api/payroll/periods/{id}/payslips` | `payroll.read` | Masked PII unless `hr.pii`. |

## Reference data (R5)

| Method | Path | Permission |
|--------|------|------------|
| GET / POST / PATCH | `/api/admin/bank-codes` | `bank_codes.admin` |

## FSM — pricing & contracts (R6)

| Method | Path | Permission | Notes |
|--------|------|------------|-------|
| GET / POST / PATCH | `/api/fsm/service-pricelists` | `service_pricelists.admin` | Scope-aware. |
| POST | `/api/fsm/pricelists/resolve` | `service_orders.read` | Returns price + level. |
| POST | `/api/fsm/service-contracts/{id}/renew` | `service_contracts.write` (+ **S** `contract.renew` for auto-with-invoice) | See `contract-renew.md`. |
| GET | `/api/fsm/service-contracts/{id}/coverage` | `service_contracts.read` | Returns parsed `coverage_rules`. |

## FSM — service orders & technicians (R6)

| Method | Path | Permission | Notes |
|--------|------|------------|-------|
| POST | `/api/fsm/service-orders` | `service_orders.write` | Auto-resolves price + technician. |
| POST | `/api/fsm/service-orders/{id}/close` | `service_orders.close` | Zero-revenue gate (may require approval token). |
| GET | `/api/fsm/service-orders/{id}/margin` | `service_orders.read` | Computed at close. |
| GET / POST / PATCH | `/api/fsm/technicians` | `technicians.admin` | Profile CRUD. |
| POST | `/api/fsm/technicians/match` | `service_orders.write` | Returns ranked matches for an order. |

## DMS (R6)

| Method | Path | Permission | Notes |
|--------|------|------------|-------|
| POST | `/api/dms/upload` | `dms.upload` | Streaming MIME → quota → persist as `pending_scan`. |
| GET | `/api/dms/{id}/download` | `dms.read` | Blocked if `pending_scan` (425) / `quarantined` (451). |
| POST | `/api/dms/attachments` | `dms.attach` | `link()` helper. |
| DELETE | `/api/dms/attachments/{id}` | `dms.attach` | `unlink()`. |
| GET | `/api/dms/quotas` | `dms.read` | Tenant + caller-user. |
| POST | `/api/admin/dms/quarantine/{id}/release` | **S** `dms.audit_admin` | Manual re-scan / restore. |

## Notifications (R6)

| Method | Path | Permission | Notes |
|--------|------|------------|-------|
| GET | `/api/admin/notifications/queue` | `notifications.read` | Paginated. |
| POST | `/api/admin/notifications/queue/{id}/reprocess` | `notifications.admin` | DLQ → pending. |
| GET | `/api/admin/notifications/queue/dlq` | `notifications.read` | DLQ view. |
| GET / POST / PATCH | `/api/admin/email-templates` | `email_templates.admin` | Versioned. |

## Approval actions (R6)

| Method | Path | Permission | Notes |
|--------|------|------------|-------|
| (Internal) | (issued from server) | (issuer permission depends on action) | Tokens carry HMAC; consumed at action endpoint. |
| POST | `/api/approvals/consume/{action}` | (action-specific) | Verifies + consumes token; performs action. |

## Standard error envelope

```json
{"code": "string", "message_en": "...", "message_ar": "...", "details": {...}}
```

All endpoints return localized messages from `backend/locales/errors.{en,ar}.json`.
