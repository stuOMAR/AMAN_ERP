"""T262: Scheduler timezone helper — applies company timezone to scheduled tasks."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def get_company_timezone(db: Any) -> str:
    """Read the company timezone from settings.

    Returns timezone string like 'Asia/Riyadh'.
    """
    from sqlalchemy import text

    try:
        result = db.execute(
            text("SELECT setting_value FROM company_settings WHERE setting_key = 'company_timezone'")
        )
        row = result.fetchone()
        return row[0] if row else "UTC"
    except Exception:
        return "UTC"


def now_in_company_tz(tz_name: str = "UTC") -> datetime:
    """Get current time in the company's timezone."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz_name))
    except Exception:
        return datetime.now(timezone.utc)


def is_business_hours(tz_name: str = "UTC", start_hour: int = 8, end_hour: int = 18) -> bool:
    """Check if current time is within business hours in the company timezone."""
    now = now_in_company_tz(tz_name)
    return start_hour <= now.hour < end_hour
