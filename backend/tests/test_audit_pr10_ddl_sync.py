"""Audit PR 10 (Batch 10) — DDL/Alembic sync.

Closes F-NEW-019 (treasury_transactions.idempotency_key),
F-NEW-020 (bank_statements.source_hash),
F-NEW-021 (zatca_outbox.last_idempotency_key),
F-NEW-022 (zatca_csid table).

The High-tier remediation rules (R-DDL-MISSING-COLUMN, R-DDL-TABLE-MISSING)
require the columns/tables to be declared both in:

  1. ``backend/db_ddl/tenant_schema.py`` — the source of truth that
     ``tenant_runner.apply_tenant_schema`` runs for every freshly
     provisioned tenant DB; AND
  2. an Alembic migration on the production chain — so existing tenants
     that are upgraded (``alembic upgrade head``) converge to the same
     shape.

These are static-source assertions only — no database fixture is needed,
matching the rest of the ``test_audit_pr*`` family. They will fail loudly
if a future refactor accidentally drops the column / table again.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TENANT_SCHEMA_PY = REPO_ROOT / "backend/db_ddl/tenant_schema.py"
TENANT_RUNNER_PY = REPO_ROOT / "backend/db_ddl/tenant_runner.py"
ALEMBIC_DIR = REPO_ROOT / "backend/alembic/versions"
NEW_MIGRATION = ALEMBIC_DIR / "0030_audit_h_ddl_sync.py"
LEGACY_CSID_MIGRATION = ALEMBIC_DIR / "0015_zatca_csid.py"


# ── Sanity: the new migration file exists and is on the production chain ──


def test_new_migration_file_exists():
    assert NEW_MIGRATION.is_file(), (
        "Batch 10 must add backend/alembic/versions/0030_audit_h_ddl_sync.py"
    )


def test_new_migration_chains_to_current_head():
    """The new migration must extend the current head so a fresh
    ``alembic upgrade head`` picks it up.
    """
    src = NEW_MIGRATION.read_text(encoding="utf-8")
    assert re.search(
        r'^revision\s*=\s*"0030_audit_h_ddl_sync"\s*$',
        src,
        re.MULTILINE,
    ), "new migration must advertise revision='0030_audit_h_ddl_sync'"
    assert re.search(
        r'^down_revision\s*=\s*"029b_invoice_idempotency_unique_key"\s*$',
        src,
        re.MULTILINE,
    ), (
        "new migration must chain off the current head "
        "029b_invoice_idempotency_unique_key"
    )


def test_new_migration_is_idempotent():
    """Every CREATE/ALTER must be IF NOT EXISTS so the migration is safe
    to re-run on tenants already provisioned through the 0015 branch.
    """
    src = NEW_MIGRATION.read_text(encoding="utf-8")
    # Every CREATE TABLE in the new migration uses IF NOT EXISTS.
    for m in re.finditer(r"\bCREATE\s+TABLE\b(?!\s+IF\s+NOT\s+EXISTS)", src, re.IGNORECASE):
        assert False, (
            "non-idempotent CREATE TABLE in 0030 migration at offset "
            f"{m.start()}"
        )
    # Every ADD COLUMN uses IF NOT EXISTS.
    for m in re.finditer(r"\bADD\s+COLUMN\b(?!\s+IF\s+NOT\s+EXISTS)", src, re.IGNORECASE):
        assert False, (
            "non-idempotent ADD COLUMN in 0030 migration at offset "
            f"{m.start()}"
        )


def test_legacy_zatca_csid_migration_still_present():
    """The original 0015 branch starter was already on disk; Batch 10
    must NOT delete it — it remains the canonical migration for tenants
    that were on the 0015 branch when this batch ships.
    """
    assert LEGACY_CSID_MIGRATION.is_file(), (
        "0015_zatca_csid.py must remain on disk; Batch 10 only adds the new "
        "0030 migration."
    )


# ── F-NEW-019: treasury_transactions.idempotency_key ─────────────────────


def test_alembic_adds_treasury_transactions_idempotency_key():
    src = NEW_MIGRATION.read_text(encoding="utf-8")
    # Column ADD
    assert re.search(
        r"ALTER\s+TABLE\s+treasury_transactions\s+"
        r"ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+idempotency_key\s+VARCHAR",
        src,
        re.IGNORECASE,
    ), "F-NEW-019: missing ALTER TABLE treasury_transactions ADD idempotency_key"
    # Partial unique index
    assert re.search(
        r"CREATE\s+UNIQUE\s+INDEX\s+IF\s+NOT\s+EXISTS\s+"
        r"uq_treasury_transactions_idempotency",
        src,
        re.IGNORECASE,
    ), "F-NEW-019: missing partial unique index on idempotency_key"


def test_tenant_schema_declares_treasury_transactions_idempotency_key():
    src = TENANT_SCHEMA_PY.read_text(encoding="utf-8")
    assert re.search(
        r"ALTER\s+TABLE\s+treasury_transactions\s+"
        r"ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+idempotency_key",
        src,
        re.IGNORECASE,
    ), (
        "F-NEW-019: tenant_schema.py must mirror the alembic ADD COLUMN so "
        "newly-provisioned tenants converge."
    )


# ── F-NEW-020: bank_statements.source_hash ───────────────────────────────


def test_alembic_adds_bank_statements_source_hash():
    src = NEW_MIGRATION.read_text(encoding="utf-8")
    assert re.search(
        r"ALTER\s+TABLE\s+bank_statements\s+"
        r"ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+source_hash\s+VARCHAR",
        src,
        re.IGNORECASE,
    ), "F-NEW-020: missing ALTER TABLE bank_statements ADD source_hash"
    assert re.search(
        r"CREATE\s+UNIQUE\s+INDEX\s+IF\s+NOT\s+EXISTS\s+"
        r"uq_bank_statements_source_hash",
        src,
        re.IGNORECASE,
    ), "F-NEW-020: missing partial unique index on (bank_account_id, source_hash)"


def test_tenant_schema_declares_bank_statements_source_hash():
    src = TENANT_SCHEMA_PY.read_text(encoding="utf-8")
    assert re.search(
        r"ALTER\s+TABLE\s+bank_statements\s+"
        r"ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+source_hash",
        src,
        re.IGNORECASE,
    ), (
        "F-NEW-020: tenant_schema.py must mirror the alembic ADD COLUMN."
    )


# ── F-NEW-021: zatca_outbox.last_idempotency_key ─────────────────────────


def test_alembic_adds_zatca_outbox_last_idempotency_key():
    src = NEW_MIGRATION.read_text(encoding="utf-8")
    assert re.search(
        r"ALTER\s+TABLE\s+zatca_outbox\s+"
        r"ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+last_idempotency_key\s+VARCHAR",
        src,
        re.IGNORECASE,
    ), "F-NEW-021: missing ALTER TABLE zatca_outbox ADD last_idempotency_key"


def test_tenant_schema_declares_zatca_outbox_last_idempotency_key():
    src = TENANT_SCHEMA_PY.read_text(encoding="utf-8")
    assert re.search(
        r"ALTER\s+TABLE\s+zatca_outbox\s+"
        r"ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+last_idempotency_key",
        src,
        re.IGNORECASE,
    ), "F-NEW-021: tenant_schema.py must mirror the alembic ADD COLUMN."


# ── F-NEW-022: zatca_csid table ──────────────────────────────────────────


def test_alembic_creates_zatca_csid_table():
    src = NEW_MIGRATION.read_text(encoding="utf-8")
    assert re.search(
        r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+zatca_csid\s*\(",
        src,
        re.IGNORECASE,
    ), "F-NEW-022: 0030 migration must (re)declare zatca_csid"
    # The CSID rotation invariant — only one ACTIVE per environment.
    assert re.search(
        r"uq_zatca_csid_active",
        src,
        re.IGNORECASE,
    ), "F-NEW-022: missing unique-active partial index on zatca_csid"


def test_tenant_schema_declares_zatca_csid_table():
    src = TENANT_SCHEMA_PY.read_text(encoding="utf-8")
    assert re.search(
        r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+zatca_csid\s*\(",
        src,
        re.IGNORECASE,
    ), (
        "F-NEW-022: tenant_schema.py must declare zatca_csid so new tenants "
        "get the CSID lifecycle table at provisioning time, not via a "
        "separate migration branch."
    )


def test_audit_h_block_wired_into_runner():
    """The new ``get_audit_h_ddl_sync_sql()`` block must appear in
    ``tenant_runner._ordered_sql_blocks`` so newly-provisioned tenants
    actually receive the new DDL.
    """
    src = TENANT_RUNNER_PY.read_text(encoding="utf-8")
    assert "get_audit_h_ddl_sync_sql" in src, (
        "tenant_runner must import the new audit_h_ddl_sync helper"
    )
    assert re.search(
        r"get_audit_h_ddl_sync_sql\s*\(\s*\)",
        src,
    ), "tenant_runner._ordered_sql_blocks must invoke get_audit_h_ddl_sync_sql()"


def test_helper_function_is_callable_and_returns_expected_ddl():
    """Smoke-check the helper actually returns SQL containing all four
    fixes. This is cheaper than running alembic."""
    from db_ddl.tenant_schema import get_audit_h_ddl_sync_sql

    sql = get_audit_h_ddl_sync_sql()
    assert "treasury_transactions" in sql and "idempotency_key" in sql
    assert "bank_statements" in sql and "source_hash" in sql
    assert "zatca_outbox" in sql and "last_idempotency_key" in sql
    assert "zatca_csid" in sql and "uq_zatca_csid_active" in sql
