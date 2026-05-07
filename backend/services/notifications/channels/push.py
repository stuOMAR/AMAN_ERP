"""Push notification channel adapter."""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def send_push(
    *,
    recipient: str,
    title: str,
    body: str,
    api_key: Optional[str] = None,
    project_id: Optional[str] = None,
) -> bool:
    """Send a push notification."""
    if not api_key:
        logger.warning("Push API not configured; push not sent to %s", recipient)
        return False

    # Push provider integration would go here
    logger.info("Push sent to %s: %s", recipient, title)
    return True
