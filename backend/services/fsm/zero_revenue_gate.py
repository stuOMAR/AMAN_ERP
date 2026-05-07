"""Zero-revenue gate — requires explicit approval for zero-revenue service orders.

Contract: see specs/024-workforce-service-comms-integrity/contracts/zero-revenue-gate.md

Invoked from service-order state machine on close. If revenue is zero and
the setting fsm.zero_revenue_approval_required is true, the order must have
an approval token before it can be closed.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


def check_zero_revenue_gate(
    conn: Any,
    *,
    tenant_id: int,
    service_order_id: int,
    approval_token: Optional[str] = None,
) -> dict:
    """Check if a zero-revenue service order can be closed.

    Returns dict with gate status. Raises if gate blocks the close.
    """
    # Check setting
    setting = conn.execute(
        text("""
            SELECT setting_value FROM company_settings
            WHERE setting_key = 'fsm.zero_revenue_approval_required'
        """),
    ).fetchone()

    if not setting or setting[0].lower() != "true":
        return {"gate_passed": True, "reason": "setting_disabled"}

    # Get order revenue
    order = conn.execute(
        text("""
            SELECT revenue_total FROM service_orders
            WHERE id = :oid AND tenant_id = :tid
        """),
        {"oid": service_order_id, "tid": tenant_id},
    ).fetchone()

    if order is None:
        raise LookupError("Service order not found")

    revenue = Decimal(str(order[0])) if order[0] else Decimal("0")

    if revenue > 0:
        return {"gate_passed": True, "reason": "has_revenue"}

    # Zero revenue — check approval token
    if not approval_token:
        raise ValueError("service_order.zero_revenue_requires_approval")

    # Validate approval token
    from services.auth.approval_tokens import validate_token
    token_valid = validate_token(
        conn,
        tenant_id=tenant_id,
        nonce=approval_token,
        action="service_order.zero_revenue_close",
        target_id=service_order_id,
    )

    if not token_valid:
        raise ValueError("approval_token.invalid_signature")

    return {"gate_passed": True, "reason": "approved_via_token"}
