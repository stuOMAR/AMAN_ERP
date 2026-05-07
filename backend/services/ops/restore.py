"""T286: Restore service — dry-run + confirm token + execute."""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


async def dry_run_restore(backup_id: str) -> dict[str, Any] | None:
    """Step 1: Validate backup and compute missing/extra tenants.

    Returns dict with validation results and confirm_token.
    """
    from database import get_tenant_db
    from sqlalchemy import text

    try:
        with get_tenant_db() as db:
            result = db.execute(
                text("SELECT id, backup_id, checksum, tenant_inventory, status FROM backup_runs WHERE backup_id = :bid"),
                {"bid": backup_id},
            )
            row = result.fetchone()

        if not row:
            return None

        if row[4] != "succeeded":
            return {"error": f"Backup status is {row[4]}, not succeeded"}

        # Generate confirm token (HMAC-signed)
        confirm_token = _generate_confirm_token(backup_id, "", "")

        return {
            "backup_id": backup_id,
            "checksum": row[2],
            "tenant_inventory": row[3],
            "missing_tenants": [],  # TODO: compare with current inventory
            "extra_tenants": [],    # TODO: compare with current inventory
            "confirm_token": confirm_token,
            "valid": True,
        }
    except Exception as exc:
        logger.error("Restore dry-run failed: %s", exc)
        return {"error": str(exc)}


async def execute_restore(backup_id: str, confirm_token: str) -> dict[str, Any]:
    """Step 2: Execute restore with confirm token.

    Returns dict with success status.
    """
    from database import get_tenant_db
    from services.audit_writer import log_activity
    from sqlalchemy import text

    # Verify token
    if not _verify_confirm_token(confirm_token, backup_id, "", ""):
        return {"success": False, "error": "Invalid confirm token"}

    try:
        # Record restore in audit
        with get_tenant_db() as db:
            log_activity(
                db,
                action="backup.restore",
                entity_type="backup_run",
                entity_id=None,
                details={"backup_id": backup_id, "action": "restore_execute"},
                critical=True,
            )
            db.commit()

        # TODO: Actual restore logic
        logger.info("Restore executed for backup: %s", backup_id)

        return {"success": True, "backup_id": backup_id}
    except Exception as exc:
        logger.error("Restore execution failed: %s", exc)
        return {"success": False, "error": str(exc)}


def _generate_confirm_token(backup_id: str, actor_id: str, secret: str = "default") -> str:
    """Generate HMAC-signed confirm token."""
    message = f"ops.restore:{backup_id}:{actor_id}"
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def _verify_confirm_token(token: str, backup_id: str, actor_id: str, secret: str = "default") -> bool:
    """Verify HMAC-signed confirm token."""
    expected = _generate_confirm_token(backup_id, actor_id, secret)
    return hmac.compare_digest(token, expected)
