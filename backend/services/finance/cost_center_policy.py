"""
Cost-center policy validator.

Reads `company_settings.expenses.cost_center_policy` and enforces
the configured level (off / warn / required) against a given
cost_center_id.

Used by expense and JE routers before posting.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text

logger = logging.getLogger(__name__)

# ── Result type ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PolicyResult:
    action: Literal["allow", "warn", "reject"]
    message: str


# ── Policy reader ──────────────────────────────────────────────────────────────


def _read_policy(conn) -> str:
    """Return the cost_center_policy string from company_settings (default 'off')."""
    row = conn.execute(
        text("""
            SELECT setting_value
              FROM company_settings
             WHERE setting_key = 'expenses.cost_center_policy'
             LIMIT 1
        """)
    ).fetchone()
    value = (row[0] if row else "off") or "off"
    return value.lower().strip()


# ── Public API ─────────────────────────────────────────────────────────────────


def validate_cost_center(cost_center_id: int | None, *, tenant_id: int) -> PolicyResult:
    """Validate *cost_center_id* against the tenant's policy.

    Intended to be called inside a transactional block that already has
    a connection set for the target tenant.

    Returns a `PolicyResult` whose ``action`` is one of:
      * ``allow``  — no objection
      * ``warn``   — cost center is missing but the policy is only `warn`
      * ``reject`` — cost center is required by policy and missing
    """
    # Lazy import to avoid circular deps at module level
    from database import get_db_connection

    conn = get_db_connection(str(tenant_id))
    try:
        return _validate(cost_center_id, conn)
    finally:
        conn.close()


def check_cost_center_requirement(cost_center_id: int | None, conn) -> str:
    """Convenience helper — returns one of ``"allow"`` / ``"warn"`` / ``"reject"``.

    Suitable for embedding directly in router validation flows that
    already hold a connection.
    """
    result = _validate(cost_center_id, conn)
    return result.action


def _validate(cost_center_id: int | None, conn) -> PolicyResult:
    policy = _read_policy(conn)

    if policy == "off":
        return PolicyResult(action="allow", message="Cost center policy is disabled")

    if cost_center_id is not None:
        # Ensure the cost center exists and is active
        row = conn.execute(
            text("SELECT 1 FROM cost_centers WHERE id = :cid AND is_active = TRUE"),
            {"cid": cost_center_id},
        ).fetchone()
        if row:
            return PolicyResult(action="allow", message="Cost center is valid")

        return PolicyResult(
            action="reject",
            message=f"Cost center {cost_center_id} does not exist or is inactive",
        )

    # cost_center_id is None
    if policy == "warn":
        return PolicyResult(
            action="warn",
            message="Cost center is recommended but not required — proceeding with a warning",
        )

    if policy == "required":
        return PolicyResult(
            action="reject",
            message="Cost center is required by company policy",
        )

    # Unknown policy value — treat as off
    logger.warning("Unknown cost_center_policy value: %s — treating as 'off'", policy)
    return PolicyResult(action="allow", message="Unknown policy value, defaulting to allow")
