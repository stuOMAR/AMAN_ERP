"""T6.4 — Tenant DDL package.

Single source of truth for the per-tenant CREATE TABLE / CREATE INDEX
DDL that was previously inlined in ``backend/database.py``.

Modules:
  * tenant_schema    — all ``get_*_tables_sql()`` functions.
  * tenant_runner    — orchestrator that applies the DDL to a fresh
                       tenant database (used by Alembic baseline and
                       by ``database.create_company_tables``).
"""
