# Contract: Email Templates

## Table

`email_templates(tenant_id, code, locale, subject, body_html, body_text, version, active)` with unique `(tenant_id, code, locale)`.

## Resolver

`services/notifications/templates.py::render(code, locale, payload) -> RenderedMessage`

`RenderedMessage` fields: `subject`, `html`, `text`.

## Locale Fallback

1. Exact `(tenant_id, code, locale, active=true)`.
2. `(tenant_id, code, company_settings.notifications.default_locale, active=true)`.
3. `(tenant_id, code, 'en', active=true)`.
4. Else 422 `notifications.template_missing`.

## Interpolation

Sandboxed Jinja2 (`SandboxedEnvironment`) with:
- No filesystem access.
- No `import`, `extends`, `include`.
- Filters whitelisted: `default`, `escape`, `lower`, `upper`, `title`, `truncate`, `format_currency` (custom, uses `Decimal`), `format_date` (uses `company_timezone`).
- All payload values escaped by default in HTML.

## Validation

- For each `code` flagged as transactional, both `en` and `ar` rows MUST exist before `active=true` for either; CI lint `scripts/check_hardcoded_email_bodies.py` ensures no inline transactional bodies and that all transactional codes have both locales.
- `version` increments on every update; old versions retained for audit.

## Admin Endpoints

`GET/POST/PATCH /api/admin/email-templates` (gated by `email_templates.admin`).

## Errors

| Code | When |
|------|------|
| 422 `template.invalid_jinja` | Render syntax error. |
| 422 `template.missing_required_locale` | Activating a transactional template without ar+en. |
