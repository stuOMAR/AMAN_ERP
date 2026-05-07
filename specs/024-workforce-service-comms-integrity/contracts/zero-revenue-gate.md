# Contract: Zero-Revenue Service Order Close Gate

## Purpose
Prevent silently closing a service order with `revenue_total = 0` AND `cost_total > 0` (typically warranty / goodwill / bug-fix), unless explicitly approved.

## Hook

Called in service-order state machine on transition to `closed`.

## Behavior

When `company_settings.fsm.zero_revenue_approval_required = true` (default):

- If `revenue_total == 0 AND cost_total > 0`: transition rejected unless the request bears a valid signed `approval_token` (see `approval-tokens.md`) with `action='service_order.close_zero_revenue'` and `target_id=service_order_id`.
- If approved: transition proceeds; audit event records `closed_with_zero_revenue=true` + approver user id.
- If approval not required (setting `false`): no gate.

## Errors

| Code | When |
|------|------|
| 409 `service_order.zero_revenue_requires_approval` | No approval token present and revenue=0 with cost>0. |
| 410 `approval_token.expired` | Token past `expires_at`. |
| 409 `approval_token.consumed` | Token already used. |
| 401 `approval_token.invalid_signature` | HMAC mismatch. |
