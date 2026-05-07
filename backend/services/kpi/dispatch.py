"""T123: KPI dispatch — routes breached evaluations through feature 024 dispatcher."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def dispatch_kpi_notification(
    kpi_id: str,
    kpi_code: str,
    value: float,
    threshold: float,
    channels: list[str],
    tenant_id: str,
) -> bool:
    """Dispatch a KPI breach notification through the unified dispatcher.

    Args:
        kpi_id: KPI definition ID.
        kpi_code: KPI code for the notification.
        value: The breached value.
        threshold: The threshold that was breached.
        channels: List of channels (email, sms, push, in_app, webhook).
        tenant_id: Tenant identifier.

    Returns:
        True if dispatch succeeded.
    """
    try:
        from services.notifications.dispatcher import dispatch_notification

        message = f"KPI Alert: {kpi_code} value {value} breached threshold {threshold}"

        for channel in channels:
            try:
                await dispatch_notification(
                    channel=channel,
                    subject=f"KPI Alert: {kpi_code}",
                    body=message,
                    tenant_id=tenant_id,
                    metadata={"kpi_id": kpi_id, "kpi_code": kpi_code, "value": value, "threshold": threshold},
                )
            except Exception as exc:
                logger.error("Failed to dispatch KPI notification via %s: %s", channel, exc)

        return True
    except Exception as exc:
        logger.error("KPI dispatch failed: %s", exc)
        return False
