# Contract: Invoice State Machine

**Module**: `services/sales/invoice_state.py`
**Public function**: `transition(invoice, target_state, *, actor, reason=None) -> Invoice`

## Purpose

Be the **only** code path that writes `invoices.state`. Enforce legal transitions, attach side effects (GL, ZATCA outbox enqueue, audit, domain event), and provide deterministic concurrency semantics.

## Inputs

- `invoice` — current persisted invoice (with `state`).
- `target_state` — one of `posted, submitted, cleared, reported, reversed, cancelled`.
- `actor` — user context (id, name, ip, user_agent).
- `reason` — optional free text recorded in `invoices.state_reason`.

## Output

- The updated `invoice` (refreshed from DB) on success.
- Raises `InvalidInvoiceTransition(from, to)` if the transition is not in the legal map.
- Raises `StaleInvoiceState(expected, actual)` if a concurrent writer already advanced the state.
- Raises `FiscalPeriodLocked` if the transition is `posted` and the period is closed (and the closed-period drafts policy disallows it).

## Legal transitions

```
draft     → posted, cancelled
posted    → submitted, reversed, cancelled
submitted → cleared, reported, reversed
cleared   → reversed
reported  → reversed
reversed  → (terminal)
cancelled → (terminal)
```

## Behavior

1. Validate `(invoice.state, target_state) ∈ LEGAL_TRANSITIONS`.
2. Open `transactional()` if not already inside one.
3. `UPDATE invoices SET state = $target, state_reason = $reason, posted_at = ..., posted_by = ... WHERE id = $id AND state = $expected_current` — if zero rows affected, raise `StaleInvoiceState`.
4. Side effects per transition:
   - `draft → posted` → `gl_service.post(source=SALES_INVOICE, source_id=invoice.id, ...)`. Then if ZATCA enabled, insert `zatca_outbox` row. Set `posted_at`, `posted_by`.
   - `posted/cleared/reported → reversed` → `gl_service.reverse(source_je_id, source='sales_invoice_reverse', source_id=invoice.id)`. Mark related ZATCA outbox row terminal.
   - `posted → cancelled` → run inventory pre-flight (full-line); on success, `gl_service.reverse(...)` and write a `cancellation_audit` row. Reverse the linked sales order if not already reversed.
   - `draft → cancelled` → no GL action.
   - `submitted → cleared/reported` → set `cleared_reference` / `reported_reference` from outbox payload; emit domain event.
5. Emit `invoice.state_changed` domain event with `from_state, to_state, actor, reason, invoice_id`.
6. Audit-write via `audit_writer.log_activity` with sanitized payload.

## Lint enforcement

`scripts/check_invoice_state_writers.py` greps for `UPDATE invoices SET state` and fails CI if matched anywhere outside this module.

## Concurrency

The conditional UPDATE is the sole concurrency guard. Callers must NOT pre-read `state` and then UPDATE separately.

## Audit

- Activity type: `sales.invoice.state_changed`.
- Audited fields: `invoice_id, from_state, to_state, reason`.
