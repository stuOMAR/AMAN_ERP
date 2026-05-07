# Contract: HR PII Gate

## Purpose
Single canonical gate for reads/writes of sensitive HR fields (salary, IBAN, national_id, passport_number, bank_account_number, gosi_number).

## Helper

`services/hr/pii.py`

```
hr_pii_serializer.dump(employee, request_user) -> dict
hr_pii_serializer.unmask_field(field_name, employee_id, request_user) -> str  # raises 403 without hr.pii
encrypt_pii(field_name, plaintext) -> bytes
decrypt_pii(field_name, ciphertext) -> str
```

## Behavior

- Default response: every PII column returned as `"****"` plus `"<field>_masked": true`.
- When the request bears `hr.pii` sensitive permission AND the endpoint declares `require_sensitive_permission('hr.pii')`, the serializer emits plaintext.
- Audit: every unmasked emit calls `audit_writer.log_activity(action='hr.pii.read', target=employee_id, fields_unmasked=[...])` after `sanitize_for_audit`.
- Encryption: `encrypt_pii` uses 022's vault DEK per tenant; `decrypt_pii` is the only path to plaintext at rest.

## Errors

| Code | When |
|------|------|
| 403 `pii.forbidden` | No `hr.pii` permission. |
| 422 `pii.invalid_field` | Unknown PII field name. |

## CI Lint
`scripts/check_hr_pii_endpoints.py` — every router emitting `EmployeeOut` (or sub-fields containing PII) must declare `require_sensitive_permission('hr.pii')` OR pass through the masking serializer.
