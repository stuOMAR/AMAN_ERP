# AMAN ERP Agent Guide

This file is the working contract for coding agents in this repository. The
full engineering and product constitution lives in
`docs/SYSTEM_CONSTITUTION.md`; read it before making non-trivial changes.

Rules marked `[CRITICAL]` in the constitution are non-negotiable. Treat a
violation as a critical defect, even if nearby legacy code is weaker.

## Project Shape

- Backend: FastAPI, Python 3.12, SQLAlchemy, SQL-first queries, PostgreSQL.
- Frontend: React 18, Vite, i18next Arabic/English, RTL support.
- Mobile: React Native.
- Tenancy: one PostgreSQL database per company, named `aman_{company_id}`.
- Main domains: accounting, treasury, sales, purchases, inventory, HR, POS,
  audit, permissions, reports, compliance, and integrations.

## Source Of Truth

- Tenant schema baseline: `backend/db_ddl/tenant_schema.py`.
- Alembic migrations: `backend/alembic/versions/`.
- System database bootstrapping and shared DB utilities: `backend/database.py`.
- FastAPI app and router registration: `backend/main.py`.
- Backend routers: `backend/routers/`.
- Backend business logic: `backend/services/`.
- Backend schemas: `backend/schemas/`.
- Backend i18n: `backend/locales/errors.en.json` and
  `backend/locales/errors.ar.json`.
- Frontend API clients: `frontend/src/services/`.
- Frontend tests: `frontend/src/tests/`.
- Frontend style guide: `docs/FRONTEND_STYLE_GUIDE.md`.

## Non-Negotiable Guardrails

- Do not use `float`, `double`, or JavaScript `Number` for monetary values.
  Use `Decimal` in Python and string/fixed-point handling in JavaScript.
- Preserve tenant isolation. Tenant operations must route through the
  company-specific database connection.
- Journal entries must stay balanced. Use the GL service; direct journal
  inserts are forbidden for business transactions.
- Every protected endpoint needs the appropriate permission/module/branch
  guard. Public endpoints such as login, refresh, health, and development docs
  are explicit exceptions only.
- Never log or return secrets, tokens, credentials, private keys, or raw
  exception details.
- SQL must be parameterized. Do not interpolate untrusted input into SQL.
- Frontend must not duplicate monetary, tax, discount, FX, inventory-cost, or
  payroll calculations. The backend is the calculation source of truth.
- Schema changes must update both `backend/alembic/versions/` and
  `backend/db_ddl/tenant_schema.py`. Update `backend/database.py` too when the
  changed object is bootstrapped there.
- Do not expand existing legacy violations. If touching a violating area, fix
  it when low risk; otherwise isolate the new behavior and document remaining
  debt.

## Common Commands

```bash
# Start local app
./start-local.sh

# Stop local app
./stop-local.sh

# Docker development stack
docker compose up -d

# Backend tests
cd backend && python -m pytest tests/ -q

# Targeted backend test
cd backend && python -m pytest tests/path_or_test.py -q

# Frontend tests
cd frontend && npm test

# Frontend build
cd frontend && npm run build

# Alembic tenant migration
cd backend && python -m alembic -c alembic.ini -x company=<company_id> upgrade head
```

## Change Discipline

- Keep edits focused. Do not reformat large unrelated files.
- Read nearby code and tests before editing.
- Prefer existing local helpers, services, validators, permission decorators,
  and API client patterns.
- Add or update tests for behavior changes, especially accounting, compliance,
  permissions, migrations, idempotency, and tenant isolation.
- New user-facing text must be translated in both Arabic and English locale
  files.
- New list endpoints must paginate, default to 25 rows, and cap at 100 unless
  streaming/export behavior is explicitly implemented.
- New high-cardinality filters need indexes.
- Use soft-delete and audit columns for business entities unless a documented
  exception applies.

## Final Response Checklist

When finishing a coding task, report:

- Files changed.
- Tests or builds run.
- Constitution-sensitive areas touched, if any.
- Tests not run and why, if applicable.
