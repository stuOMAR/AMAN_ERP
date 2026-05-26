"""Push notification channel adapter."""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def mask_token(token: str) -> str:
    """Mask push token for safety."""
    if not token:
        return "***"
    token_str = str(token)
    if len(token_str) <= 8:
        return "****"
    return token_str[:4] + "..." + token_str[-4:]


def send_push(
    *,
    recipient: str,
    title: str,
    body: str,
    api_key: Optional[str] = None,
    project_id: Optional[str] = None,
) -> bool:
    """Send a push notification."""
    masked_recipient = mask_token(recipient)
    if not api_key:
        logger.warning("Push API not configured; push not sent to %s", masked_recipient)
        return False

    logger.warning("Push provider integration is not implemented; push not sent to %s", masked_recipient)
    return False
