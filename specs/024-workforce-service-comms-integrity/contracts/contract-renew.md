# Contract: Service Contract Renew

## Endpoint

`POST /api/fsm/service-contracts/{id}/renew`

## Permission
`require_permission('service_contracts.write')` plus `require_sensitive_permission('contract.renew')` for `auto_with_invoice`.

## Helper

`services/fsm/contract_renew.py::renew_contract(contract_id, as_of=today) -> RenewResult`

## Behavior

1. Validates current contract is in `active` state and within renewal window (`end_date - lead_days <= as_of <= end_date + grace_days`).
2. Creates new `service_contracts` row with:
   - Same coverage, pricing strategy, schedule, customer.
   - `start_date = old.end_date + 1 day`, `end_date = start_date + duration`.
   - `previous_contract_id = old.id`.
   - Initial state `active`.
3. Sets `old.auto_renewed_to_id = new.id`.
4. If `renew_policy='auto_with_invoice'`: calls 023's `services/sales/order_to_invoice.create_invoice_from_order` with a synthesized contract-renewal sales order (idempotent via `(tenant_id, 'contract_renewal', new_contract_id)`).
5. If `renew_policy='auto_no_invoice'`: skips invoice generation; user invoices later.
6. If `renew_policy='manual'`: returns 409 unless explicit user-confirmed flag in request.
7. Audit `service_contract.renewed`.

## Idempotency

Header `Idempotency-Key` honored; default key formula `sha256(contract_id|new_start_date)`.

## Errors

| Code | When |
|------|------|
| 409 `contract.not_renewable` | Outside renewal window. |
| 409 `contract.already_renewed` | `auto_renewed_to_id IS NOT NULL`. |
| 422 `contract.invoice_mapping_missing` | Auto-with-invoice requested but mapping unresolved. |
