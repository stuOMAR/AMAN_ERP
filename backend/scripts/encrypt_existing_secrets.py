#!/usr/bin/env python3
"""T2.5 — One-shot migration to encrypt plaintext secrets in company_settings.

Usage:
    cd backend && python -m scripts.encrypt_existing_secrets [--company COMPANY_ID]

Without ``--company``, the script discovers all tenant databases via
``system.companies`` and processes each in turn. Idempotent: rows that
already look like ciphertext are skipped.

Environment:
    FIELD_ENCRYPTION_KEY (preferred) or MASTER_SECRET — see
    backend/utils/field_encryption.py for details.
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import List

# Allow running as `python -m scripts.encrypt_existing_secrets` from /backend
sys.path.insert(0, ".")

from sqlalchemy import text  # noqa: E402

from database import get_db_connection  # noqa: E402
from utils.secret_settings import encrypt_existing_secrets  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("encrypt_existing_secrets")


def discover_companies() -> List[str]:
    """Read tenant ids from the `system` database `companies` table."""
    from config import settings  # noqa: E402

    sys_db_url = settings.DATABASE_URL  # 'system' DB URL
    from sqlalchemy import create_engine

    eng = create_engine(sys_db_url)
    with eng.connect() as conn:
        rows = conn.execute(text("SELECT id FROM companies WHERE is_active = true")).fetchall()
    return [r[0] for r in rows]


def run_for_company(company_id: str) -> None:
    log.info("→ company %s", company_id)
    db = get_db_connection(company_id)
    try:
        summary = encrypt_existing_secrets(db, tenant_id=company_id)
        db.commit()
        for k, action in summary.items():
            log.info("    %-25s %s", k, action)
    finally:
        db.close()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--company", help="Run for a single company id (default: all active)")
    args = p.parse_args()

    if args.company:
        targets = [args.company]
    else:
        targets = discover_companies()
        log.info("Discovered %d active companies", len(targets))

    for cid in targets:
        try:
            run_for_company(cid)
        except Exception as e:
            log.error("    FAILED: %s", e, exc_info=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
