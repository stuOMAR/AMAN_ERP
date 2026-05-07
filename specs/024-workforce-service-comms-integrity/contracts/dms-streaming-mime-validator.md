# Contract: DMS Streaming MIME Validator

## Helper

`services/dms/streaming_mime.py::validate(stream, declared_mime, max_chunk_bytes=65536) -> ValidationResult`

`ValidationResult` fields: `actual_mime`, `category`, `passed: bool`, `reason`.

## Behavior

- Reads up to `max_chunk_bytes` from the upload stream WITHOUT persisting.
- Computes magic-bytes MIME via `python-magic` (libmagic).
- Compares against `declared_mime`:
  - Mismatched magic vs declared → reject.
  - Declared MIME's category not in `company_settings.dms.allowed_mime_groups` → reject.
- On reject: returns 415 BEFORE any disk write.
- On pass: returns the validated chunk + remainder to the caller for streaming persist.

## Errors

| Code | When |
|------|------|
| 415 `dms.mime_rejected` | Body: `{declared: '...', actual: '...', reason: 'magic_mismatch'\|'category_blocked'}`. |
| 422 `dms.mime_undetected` | Magic bytes inconclusive AND declared not in trust list. |
