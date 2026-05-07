# Contract: ZATCA Outbox

**Module**: `services/einvoicing/outbox.py` (writer + worker).
**Table**: `zatca_outbox`.
**Endpoints**: `GET /einvoicing/outbox?state=...` (sensitive read), `POST /einvoicing/outbox/{id}/reprocess` (sensitive write).

## Purpose

Decouple invoice posting from the ZATCA round-trip. Guarantee at-least-once submission with bounded retries, structured failure handling, and a manual reprocess path. Operators see status; engineers see error history; auditors see a permanent record per invoice.

## Writer

Called inline by the invoice state machine on `draft → posted` (when ZATCA is enabled for the tenant):

```
outbox.enqueue(invoice, idempotency_key=invoice.id)
```

Insert is `ON CONFLICT (tenant_id, invoice_id) DO NOTHING` — re-posts and reversals do not duplicate rows.

## Worker

Loop:

1. `SELECT id FROM zatca_outbox WHERE tenant_id=? AND state='pending' AND next_attempt_at <= now() FOR UPDATE SKIP LOCKED LIMIT 25`.
2. For each: `UPDATE state='submitting'`, attempt `submit(invoice)`:
   - Build UBL via `ubl_builder` (profile = `zatca.profile`).
   - Sign via `ubl_signer` using vault credentials.
   - POST to ZATCA endpoint.
   - On HTTP 2xx with `cleared_reference` → state `cleared`.
   - On HTTP 2xx with `reported_reference` → state `reported`.
   - On retryable error → state `failed`, `attempts++`, `next_attempt_at = now + backoff(attempts)`.
   - When `attempts ≥ zatca.outbox_max_attempts` → state `dead_letter`, audit-write, alert.
3. Cache `signed_xml` on success for re-print/audit.

## Backoff

`backoff(n) = min(base × 2^(n-1), cap) × jitter(0.5..1.5)` seconds, where base=30, cap=1800.

## Reprocess endpoint

Resets state to `pending`, `attempts=0`, `next_attempt_at=now()`. Auditable as `einvoicing.outbox.reprocessed`.

## Errors

- `409 einvoicing.outbox.already_terminal` if reprocess called on `cleared`/`reported` (use admin override flag if truly needed).
- `503 einvoicing.outbox.signing_unavailable` when vault returns no credentials.

## Concurrency

`FOR UPDATE SKIP LOCKED` enables N workers per tenant safely. The unique `(tenant_id, invoice_id)` enforces single row per invoice.

## Audit

- `einvoicing.outbox.submitted`, `.cleared`, `.reported`, `.failed`, `.dead_letter`, `.reprocessed`.
