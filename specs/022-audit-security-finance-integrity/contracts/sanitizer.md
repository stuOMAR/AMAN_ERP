# Contract: PII Sanitizer (`services/audit_sanitizer.py`)

**Feature**: 022-audit-security-finance-integrity

## Public interface

```python
def sanitize_for_audit(
    payload: Any,
    *,
    context: str,
    extra_allow_paths: list[str] | None = None,
) -> Any: ...
```

## Behavior

- MUST return a redacted **copy** (no in-place mutation).
- MUST recurse through `dict`, `list`, `tuple`; primitive values pass through unchanged unless their key path matches a sensitive rule.
- MUST mask values whose dotted path or key name matches the sensitive set: `salary`, `iban`, `national_id`, `password`, `secret`, `token`, `api_key`, `credit_card`, `cvv`, plus regex variants (`pwd`, `passwd`, `bearer`, `authorization`).
- MUST replace structural-hint fragments in strings: `column "..."`, `relation "..."`, `constraint "..."`, raw SQL snippets (`SELECT|INSERT|UPDATE|DELETE` followed by SQL keywords).
- MUST honor `company_settings.audit.sanitizer.allow_paths` and `extra_allow_paths` to permit specific dotted paths.
- MUST log the sanitizer rule version applied (kept in metadata, not in payload).
- MUST NOT raise on unexpected types; falls back to `repr()` and masks.

## Mask format

- Default mask: the literal string `"***"`.
- For numeric salary fields: `"***"` (do not preserve magnitude).
- For IBAN: `"***"` (do not preserve last digits).

## Used by

- `services/audit_writer.log_activity()` (mandatory).
- Request-body capture middleware (mandatory for sensitive routes).
- Import-error formatter (mandatory before returning errors to the caller).

## Forbidden patterns

- Per-callsite ad-hoc redaction. All sanitization MUST go through this single helper.
