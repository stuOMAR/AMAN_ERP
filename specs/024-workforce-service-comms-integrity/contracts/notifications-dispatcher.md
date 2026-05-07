# Contract: Notifications Dispatcher

## Helper

`services/notifications/dispatcher.py::dispatch(event_type, channel, recipient, template_code=None, payload=None, locale=None, idempotency_key=None, tenant_id=None) -> NotificationQueueRow`

## Behavior

1. Compute `idempotency_key` if not provided:
   ```
   idempotency_key = sha256(f"{tenant_id}|{event_type}|{recipient}|{channel}|{template_code}|{json_canonical(payload)}")[:32]
   ```
2. Look up existing row in dedupe window (`company_settings.notifications.dedupe_window_seconds`, default 300):
   - If row exists in `state IN ('pending','sending')`: return it (no new insert).
   - Else: insert new row with `state='pending'`, `attempts=0`, `next_attempt_at=now()`.
3. Resolve `locale`: explicit > recipient's user locale > `company_settings.notifications.default_locale` (default `en`).

## Worker

`services/notifications/queue_worker.py::run(channel, batch_size=100)`

```sql
SELECT id, ... FROM notifications_queue
WHERE channel=$1 AND state='pending' AND next_attempt_at<=now()
ORDER BY next_attempt_at
LIMIT $2 FOR UPDATE SKIP LOCKED;
```

For each claimed row:
- Mark `state='sending'`, `claimed_at=now()`.
- Resolve template (channel `email`/`sms`): `services/notifications/templates.py::render(code, locale, payload)` (sandboxed Jinja2).
- Call channel adapter (provider credentials from 022's vault).
- On success: `state='sent'`, `sent_at=now()`.
- On transient error: `attempts+=1`; if `attempts >= notifications.max_attempts`: `state='dead_letter'`, `dlq_at=now()`, dispatch DLQ alarm via webhook channel; else `state='pending'`, `next_attempt_at = now() + min(2^attempts * 30s, 3600s) * jitter(0.8..1.2)`.
- On permanent error (provider 4xx with non-retryable code): straight to `dead_letter`.

## Channel Adapters

- `email` — reads `email_templates` (see `email-templates.md`); SMTP credentials from vault.
- `sms` — provider credentials from vault.
- `push` — APNs/FCM credentials from vault.
- `in_app` — writes to `in_app_notifications` (existing table); no provider call.
- `webhook` — delegates to 023's `services/webhooks/dispatcher` (consumes its retry/signing).

## CI Lint

`scripts/check_notifications_dispatch.py` — forbid `send_email(...)`/`send_sms(...)`/`send_push(...)` callsites outside `services/notifications/dispatcher.py` and channel adapters.

## Endpoints (admin)

- `GET /api/admin/notifications/queue?state=&channel=&...` — paginated.
- `POST /api/admin/notifications/queue/{id}/reprocess` — moves `dead_letter` back to `pending` with `attempts=0`.
- `GET /api/admin/notifications/queue/dlq` — DLQ view.

## Errors

| Code | When |
|------|------|
| 409 `notifications.duplicate_in_window` | Returned with existing id; HTTP 200 with `idempotent_replay=true`. |
| 422 `notifications.template_missing` | Channel requires template and `(code, locale)` not found and fallback locale also missing. |
| 422 `notifications.invalid_recipient` | Recipient format check fails for channel. |
