"""Preventive maintenance scheduler — APScheduler job for auto-generating work orders.

Contract: see specs/024-workforce-service-comms-integrity/contracts/preventive-maintenance-scheduler.md
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


def run_preventive_scheduler(conn: Any, *, tenant_id: int) -> dict:
    """Run the preventive maintenance scheduler for a tenant.

    Checks all active maintenance_plans and creates work orders for due items.
    Uses advisory lock to prevent concurrent execution.
    """
    # Acquire advisory lock
    lock = conn.execute(
        text("SELECT pg_advisory_lock(:lock_id)"),
        {"lock_id": tenant_id + 9000000},  # Unique lock namespace
    ).scalar()

    if not lock:
        return {"skipped": True, "reason": "lock_not_acquired"}

    try:
        today = date.today()
        created = 0

        plans = conn.execute(
            text("""
                SELECT id, title, asset_id, cadence, next_due_at, assigned_technician_id
                FROM maintenance_plans
                WHERE tenant_id = :tnt AND is_active = true
                  AND next_due_at <= :today
            """),
            {"tnt": tenant_id, "today": today},
        ).fetchall()

        for plan in plans:
            plan_id = plan[0]
            cadence = json.loads(plan[3]) if plan[3] else {}

            # Check for duplicate window
            existing = conn.execute(
                text("""
                    SELECT 1 FROM service_orders
                    WHERE tenant_id = :tnt AND source = 'preventive'
                      AND title LIKE :title_pattern
                      AND created_at::date = :today
                    LIMIT 1
                """),
                {"tnt": tenant_id, "title_pattern": f"%{plan[1]}%", "today": today},
            ).fetchone()

            if existing:
                continue

            # Create work order
            conn.execute(
                text("""
                    INSERT INTO service_orders
                        (tenant_id, kind, source, title, asset_id,
                         assigned_technician_id, status, created_at)
                    VALUES
                        (:tnt, 'maintenance', 'preventive', :title, :asset,
                         :tech, 'open', now())
                """),
                {
                    "tnt": tenant_id, "title": f"Preventive: {plan[1]}",
                    "asset": plan[2], "tech": plan[5],
                },
            )

            # Update next_due_at based on cadence
            interval_days = cadence.get("interval_days", 30)
            conn.execute(
                text("""
                    UPDATE maintenance_plans
                    SET next_due_at = next_due_at + (:days || ' days')::interval,
                        updated_at = now()
                    WHERE id = :pid
                """),
                {"days": interval_days, "pid": plan_id},
            )

            created += 1

        conn.commit()

        return {
            "tenant_id": tenant_id,
            "plans_checked": len(plans),
            "work_orders_created": created,
        }

    finally:
        conn.execute(text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": tenant_id + 9000000})
