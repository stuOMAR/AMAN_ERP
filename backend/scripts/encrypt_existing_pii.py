#!/usr/bin/env python3
"""Backfill script: encrypt existing plaintext PII in employees table.

Usage:
    python -m backend.scripts.encrypt_existing_pii --tenant=<id>

Reads existing plaintext salary, iban, national_id, passport_number,
bank_account_number, gosi_number values and writes encrypted BYTEA to
the corresponding *_encrypted columns. Creates a side-table
`employees_salary_backfill_<timestamp>` for one release safety.

Designed to be run once per tenant after migration 024a.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

from sqlalchemy import text

logger = logging.getLogger(__name__)


def _get_db(tenant_id: str):
    from database import db_connection
    return db_connection(tenant_id)


def encrypt_existing_pii(tenant_id: int) -> dict:
    """Encrypt all existing plaintext PII fields for a tenant.

    Returns dict with counts of encrypted fields.
    """
    from services.hr.pii import PII_FIELDS, encrypt_pii

    tid = str(tenant_id)
    stats = {f: 0 for f in PII_FIELDS}
    stats["errors"] = 0

    # Map PII field → (plaintext column, encrypted column)
    field_map = {
        "salary": ("salary", "salary_encrypted"),
        "iban": ("iban", "iban_encrypted"),
        "national_id": ("national_id", "national_id_encrypted"),
        "passport_number": ("passport_number", "passport_number_encrypted"),
        "bank_account_number": ("bank_account_number", "bank_account_number_encrypted"),
        "gosi_number": ("gosi_number", "gosi_number_encrypted"),
    }

    with _get_db(tid) as conn:
        # Create safety side-table
        ts = int(time.time())
        side_table = f"employees_salary_backfill_{ts}"
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {side_table} AS
            SELECT id, salary, iban, national_id, passport_number,
                   bank_account_number, gosi_number, now() AS backed_up_at
            FROM employees
            WHERE tenant_id = :tid
              AND (salary IS NOT NULL OR iban IS NOT NULL
                   OR national_id IS NOT NULL OR passport_number IS NOT NULL
                   OR bank_account_number IS NOT NULL OR gosi_number IS NOT NULL)
        """), {"tid": tenant_id})
        logger.info("Created side-table %s", side_table)

        # Fetch employees with plaintext PII
        rows = conn.execute(text("""
            SELECT id, salary, iban, national_id, passport_number,
                   bank_account_number, gosi_number
            FROM employees
            WHERE tenant_id = :tid
        """), {"tid": tenant_id}).fetchall()

        for row in rows:
            emp_id = row[0]
            updates = {}
            for i, field in enumerate(PII_FIELDS, start=1):
                plaintext_col, encrypted_col = field_map[field]
                plaintext_val = row[i]
                if plaintext_val is not None and str(plaintext_val).strip():
                    try:
                        encrypted = encrypt_pii(field, str(plaintext_val), tenant_id=tid)
                        updates[encrypted_col] = encrypted
                        stats[field] += 1
                    except Exception as e:
                        logger.error("Failed to encrypt %s for employee %d: %s", field, emp_id, e)
                        stats["errors"] += 1

            if updates:
                set_clauses = ", ".join(f"{col} = :{col}" for col in updates)
                params = {"eid": emp_id, "tid": tenant_id}
                params.update({col: val for col, val in updates.items()})
                conn.execute(
                    text(f"UPDATE employees SET {set_clauses} WHERE id = :eid AND tenant_id = :tid"),
                    params,
                )

        conn.commit()

    logger.info("PII encryption complete for tenant %d: %s", tenant_id, stats)
    return stats


def main():
    parser = argparse.ArgumentParser(description="Encrypt existing PII for a tenant")
    parser.add_argument("--tenant", type=int, required=True, help="Tenant ID")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    stats = encrypt_existing_pii(args.tenant)
    print(f"Done: {stats}")
    if stats["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
