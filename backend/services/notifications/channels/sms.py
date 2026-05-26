"""SMS channel adapter."""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def mask_phone(phone: str) -> str:
    """Mask phone number for PII safety."""
    if not phone:
        return "***"
    phone_str = str(phone)
    if len(phone_str) <= 4:
        return "****"
    return phone_str[:3] + "*" * (len(phone_str) - 6) + phone_str[-3:]


def send_sms(
    *,
    recipient: str,
    message: str,
    api_key: Optional[str] = None,
    sender: Optional[str] = None,
) -> bool:
    """Send an SMS message."""
    masked_recipient = mask_phone(recipient)
    if not api_key:
        logger.warning("SMS API not configured; SMS not sent to %s", masked_recipient)
        return False

    logger.warning("SMS provider integration is not implemented; SMS not sent to %s", masked_recipient)
    return False
