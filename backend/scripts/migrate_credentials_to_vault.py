"""
One-shot migrator: move scattered integration secrets into the credential vault.

Usage::

    python -m backend.scripts.migrate_credentials_to_vault --tenant <id|all>

For now this is a skeleton.  Once all adapters read from the vault, flip the
--execute flag to actually move the rows.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import List

from sqlalchemy import text

logger = logging.getLogger(__name__)

# ── migration source descriptors ──────────────────────────────────────────────

class _MigrationSource:
    """Describes one scattered storage location we migrate from."""

    def __init__(self, integration: str, name: str, table: str, column: str,
                 where: str = "", metadata_columns: list[str] | None = None):
        self.integration = integration
        self.name = name
        self.table = table
        self.column = column
        self.where = where
        self.metadata_columns = metadata_columns or []

    def __repr__(self):
        return f"<MigrationSource {self.integration}/{self.name} from {self.table}.{self.column}>"


_SOURCES: list[_MigrationSource] = [
    _MigrationSource("smtp", "primary-smtp", "company_settings", "setting_value",
                     where="setting_key = 'smtp_password'"),
    _MigrationSource("sms", "primary-sms", "company_settings", "setting_value",
                     where="setting_key = 'sms_api_key'"),
    _MigrationSource("zatca", "csid-secret", "company_settings", "setting_value",
                     where="setting_key LIKE 'zatca_%_secret'"),
    _MigrationSource("payments", "gateway-secret", "company_settings", "setting_value",
                     where="setting_key = 'payment_secret'"),
    _MigrationSource("bank", "feed-api-key", "company_settings", "setting_value",
                     where="setting_key LIKE 'bank_feed_%'"),
    _MigrationSource("ldap", "bind-password", "company_settings", "setting_value",
                     where="setting_key = 'ldap_password'"),
    _MigrationSource("shipping", "api-key", "company_settings", "setting_value",
                     where="setting_key = 'shipping_api_key'"),
]


# ── per-tenant migration ─────────────────────────────────────────────────────

def _iter_tenant_ids() -> List[str]:
    """Return all active tenant company_ids."""
    from database import engine as sys_engine
    with sys_engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT company_id FROM system_companies "
            "WHERE status = 'active' AND database_name IS NOT NULL"
        )).fetchall()
        return [r[0] for r in rows]


def _migrate_tenant(company_id: str, *, execute: bool = False) -> dict:
    """Migrate all known secrets for one tenant into the vault.

    Returns a summary dict.
    """
    from database import db_connection

    summary = {"company_id": company_id, "migrated": 0, "skipped": 0, "errors": 0}

    with db_connection(company_id) as conn:
        # Ensure the vault table exists.
        exists = conn.execute(
            text("SELECT to_regclass('integration_credentials')")
        ).scalar()
        if not exists:
            logger.warning("Tenant %s: integration_credentials table missing — skipping", company_id)
            return summary

        for src in _SOURCES:
            try:
                where_clause = f"WHERE {src.where}" if src.where else ""
                rows = conn.execute(text(f"""
                    SELECT setting_key, setting_value
                      FROM {src.table}
                      {where_clause}
                """)).fetchall()

                for row in rows:
                    secret_val = row.setting_value
                    if not secret_val:
                        summary["skipped"] += 1
                        continue

                    # Check if already in vault
                    already = conn.execute(text("""
                        SELECT 1 FROM integration_credentials
                         WHERE tenant_id = 0
                           AND integration = :integ
                           AND name = :name
                           AND status != 'soft_deleted'
                    """), {"integ": src.integration, "name": src.name}).scalar()

                    if already:
                        summary["skipped"] += 1
                        continue

                    if execute:
                        conn.execute(text("""
                            INSERT INTO integration_credentials
                                (tenant_id, integration, name, secret_ciphertext,
                                 key_version, metadata, status, created_by)
                            VALUES
                                (0, :integ, :name,
                                 :ct, 1,
                                 CAST(:meta AS JSONB), 'active', NULL)
                        """), {
                            "integ": src.integration,
                            "name": src.name,
                            "ct": secret_val.encode("utf-8"),
                            "meta": json.dumps({"origin": src.table, "origin_key": row.setting_key}),
                        })
                        summary["migrated"] += 1
                        logger.info(
                            "  %s/%s → vault (from %s.%s)",
                            src.integration, src.name, src.table, row.setting_key,
                        )
                    else:
                        summary["migrated"] += 1
                        logger.debug(
                            "  [dry-run] %s/%s would be migrated from %s.%s",
                            src.integration, src.name, src.table, row.setting_key,
                        )

            except Exception as exc:
                summary["errors"] += 1
                logger.error("  Error migrating %s/%s: %s", src.integration, src.name, exc)

        if execute:
            conn.commit()

    return summary


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migrate scattered integration secrets into the credential vault.",
    )
    parser.add_argument(
        "--tenant", required=True,
        help="Tenant company_id to migrate, or 'all' for every active tenant.",
    )
    parser.add_argument(
        "--execute", action="store_true", default=False,
        help="Actually perform the migration (default is dry-run).",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", default=False,
    )
    args = parser.parse_args(argv)

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(message)s")

    if args.tenant == "all":
        tenant_ids = _iter_tenant_ids()
    else:
        tenant_ids = [args.tenant]

    logger.info("Migrating %d tenant(s) — execute=%s", len(tenant_ids), args.execute)

    total = {"migrated": 0, "skipped": 0, "errors": 0}
    for tid in tenant_ids:
        logger.info("Tenant %s …", tid)
        summary = _migrate_tenant(tid, execute=args.execute)
        for k in total:
            total[k] += summary[k]

    logger.info("Done: %s", total)
    return 0 if total["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
