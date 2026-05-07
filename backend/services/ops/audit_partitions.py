"""T161/T162: Audit partitioning — per-partition index creation + maintenance."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


def create_partition_indexes(db: Any, partition_name: str) -> None:
    """Create BRIN + B-tree indexes on a new partition.

    Args:
        db: Database connection.
        partition_name: Name of the partition table.
    """
    from sqlalchemy import text

    try:
        db.execute(text(f"""
            CREATE INDEX IF NOT EXISTS idx_{partition_name}_created_at_brin
                ON {partition_name} USING BRIN (created_at)
        """))
        db.execute(text(f"""
            CREATE INDEX IF NOT EXISTS idx_{partition_name}_tenant_actor_date
                ON {partition_name} (tenant_id, actor_id, created_at)
        """))
        db.commit()
        logger.info("Created indexes on partition: %s", partition_name)
    except Exception as exc:
        logger.error("Failed to create indexes on %s: %s", partition_name, exc)


async def audit_partition_maintenance(tenant_id: str | None = None) -> dict[str, Any]:
    """Monthly maintenance: pre-create next partition, drop old ones.

    Returns dict with maintenance results.
    """
    from database import get_tenant_db
    from services.scheduler import idempotent_run
    from sqlalchemy import text

    results = {"created": 0, "dropped": 0, "errors": []}
    now = datetime.utcnow()

    # Read retention setting
    retention_months = 36
    try:
        with get_tenant_db(tenant_id) as db:
            row = db.execute(
                text("SELECT setting_value FROM company_settings WHERE setting_key = 'audit.retention_months'")
            ).fetchone()
            if row:
                retention_months = int(row[0])
    except Exception:
        pass

    job_id = "audit_partition_maintenance"
    scheduled_for = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    try:
        with idempotent_run(job_id, scheduled_for=scheduled_for, tenant_id=tenant_id):
            with get_tenant_db(tenant_id) as db:
                # Pre-create next-next month partition
                next_month = now.replace(day=1) + timedelta(days=32)
                next_month = next_month.replace(day=1)
                next_next_month = next_month + timedelta(days=32)
                next_next_month = next_next_month.replace(day=1)

                partition_name = f"audit_logs_{next_next_month.strftime('%Y_%m')}"
                start_date = next_next_month.strftime('%Y-%m-01')
                end_date_month = next_next_month.replace(day=28) + timedelta(days=4)
                end_date = end_date_month.replace(day=1).strftime('%Y-%m-01')

                try:
                    db.execute(text(f"""
                        CREATE TABLE IF NOT EXISTS {partition_name}
                        PARTITION OF audit_logs
                        FOR VALUES FROM ('{start_date}') TO ('{end_date}')
                    """))
                    db.commit()
                    create_partition_indexes(db, partition_name)
                    results["created"] += 1
                    logger.info("Created partition: %s", partition_name)
                except Exception as exc:
                    results["errors"].append(f"Create {partition_name}: {exc}")

                # Drop partitions older than retention
                cutoff = now - timedelta(days=retention_months * 30)
                cutoff_str = cutoff.strftime('%Y_%m')

                # Find old partitions
                old_partitions = db.execute(text("""
                    SELECT tablename FROM pg_tables
                    WHERE tablename LIKE 'audit_logs_2%'
                    AND tablename < :cutoff
                    ORDER BY tablename
                """), {"cutoff": f"audit_logs_{cutoff_str}"}).fetchall()

                # Refusal floor: don't drop if remaining < retention window
                total_partitions = db.execute(text("""
                    SELECT count(*) FROM pg_tables WHERE tablename LIKE 'audit_logs_%'
                """)).scalar() or 0

                for (pname,) in old_partitions:
                    if total_partitions - results["dropped"] <= retention_months:
                        logger.warning("Refusing to drop %s: remaining count below retention window", pname)
                        break
                    try:
                        db.execute(text(f"DROP TABLE IF EXISTS {pname}"))
                        db.commit()
                        results["dropped"] += 1
                        logger.info("Dropped old partition: %s", pname)
                    except Exception as exc:
                        results["errors"].append(f"Drop {pname}: {exc}")

    except Exception as exc:
        results["errors"].append(f"Maintenance: {exc}")

    return results
