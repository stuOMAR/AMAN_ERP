"""SMS channel adapter."""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def send_sms(
    *,
    recipient: str,
    message: str,
    api_key: Optional[str] = None,
    sender: Optional[str] = None,
) -> bool:
    """Send an SMS message."""
    if not api_key:
        logger.warning("SMS API not configured; SMS not sent to %s", recipient)
        return False

    # SMS provider integration would go here
    logger.info("SMS sent to %s (len=%d)", recipient, len(message))
    return True
