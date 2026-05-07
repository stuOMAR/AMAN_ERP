"""T11 — One-shot PII backfill: walk every tenant DB and re-write
plaintext rows using :func:`utils.pii_encryption.encrypt_pii`.

Idempotent: rows already containing ciphertext (per
:func:`field_encryption.is_encrypted`) are skipped.

Usage::

    python -m scripts.encrypt_existing_pii          # dry-run
    python -m scripts.encrypt_existing_pii --apply  # commit changes

The DDL widening (``ALTER COLUMN ... TYPE TEXT``) lives in
``backend/db_ddl/tenant_schema.py`` under the ``do_pii_widen`` block and
runs automatically on every tenant init — this script is only for the
data migration of pre-existing rows.

Operator notes:
  * ``FIELD_ENCRYPTION_KEY`` (or ``MASTER_SECRET``) must be set, otherwise
    ``utils.field_encryption`` raises and we abort early.
  * Run during a maintenance window — write traffic on the affected
    tables during the migration is safe (encryption is idempotent on a
    per-row basis) but adds noise.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

# Allow ``python scripts/encrypt_existing_pii.py`` from the repo root.
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
BACKEND = os.path.join(ROOT, "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from sqlalchemy import text  # noqa: E402

from database import _get_all_company_db_names, _get_company_engine_for_db  # noqa: E402
from utils.field_encryption import is_encrypted  # noqa: E402
from utils.pii_encryption import PII_FIELDS, encrypt_pii  # noqa: E402

logger = logging.getLogger(__name__)


def _row_iter(conn, table: str, columns):
    cols = ", ".join(["id", *columns])
    return conn.execute(text(f"SELECT {cols} FROM {table}")).fetchall()


def _migrate_table(eng, tenant_id: str, table: str, columns, *, apply: bool) -> tuple[int, int]:
    """Return ``(scanned, updated)`` counts for the given table."""
    scanned = updated = 0
    # Probe table existence first — tenants may pre-date the table.
    with eng.connect() as conn:
        exists = conn.execute(text(
            "SELECT 1 FROM information_schema.tables WHERE table_name=:t LIMIT 1"
        ), {"t": table}).fetchone()
        if not exists:
            return 0, 0
        rows = _row_iter(conn, table, columns)

    for r in rows:
        scanned += 1
        new_vals = {}
        for col in columns:
            v = getattr(r, col, None)
            if not v or is_encrypted(v):
                continue
            new_vals[col] = encrypt_pii(v, tenant_id=tenant_id)
        if not new_vals:
            continue
        updated += 1
        if not apply:
            continue
        with eng.begin() as conn:
            assigns = ", ".join(f"{c} = :{c}" for c in new_vals)
            conn.execute(text(f"UPDATE {table} SET {assigns} WHERE id = :id"),
                         {**new_vals, "id": r.id})
    return scanned, updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Commit the migration; default is dry-run.")
    parser.add_argument("--tenant", help="Restrict to a single tenant DB name.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not (os.getenv("FIELD_ENCRYPTION_KEY") or os.getenv("MASTER_SECRET")):
        logger.error("FIELD_ENCRYPTION_KEY (or MASTER_SECRET) not set — aborting")
        return 2

    db_names = ([args.tenant] if args.tenant else _get_all_company_db_names())
    total_scanned = total_updated = 0
    for db_name in db_names:
        try:
            eng = _get_company_engine_for_db(db_name)
        except Exception as e:
            logger.warning("[%s] cannot open engine: %s", db_name, e)
            continue
        # The HKDF salt is the company_id string. We use the db_name as a
        # stable proxy here — secret_settings.py uses the same convention.
        tenant_id = db_name
        for table, columns in PII_FIELDS.items():
            try:
                scanned, updated = _migrate_table(
                    eng, tenant_id, table, columns, apply=args.apply,
                )
            except Exception as e:
                logger.error("[%s.%s] migration failed: %s", db_name, table, e)
                continue
            if scanned:
                logger.info("[%s] %-25s scanned=%d updated=%d",
                            db_name, table, scanned, updated)
            total_scanned += scanned
            total_updated += updated

    mode = "APPLIED" if args.apply else "DRY-RUN"
    logger.info("Done (%s). scanned=%d updated=%d", mode, total_scanned, total_updated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
