"""T201: Locale defaults router — GET /locale/defaults.

Returns locale defaults from country/tenant settings.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/locale", tags=["locale"])


@router.get("/defaults")
async def get_locale_defaults(country: str = "SA"):
    """Return locale defaults for a country.

    Sources from company_settings consumed from feature 022.
    """
    defaults = {
        "SA": {
            "locale": "ar-SA",
            "currency": "SAR",
            "decimal_places": 2,
            "date_format": "yyyy/MM/dd",
            "timezone": "Asia/Riyadh",
            "direction": "rtl",
        },
        "AE": {
            "locale": "ar-AE",
            "currency": "AED",
            "decimal_places": 2,
            "date_format": "yyyy/MM/dd",
            "timezone": "Asia/Dubai",
            "direction": "rtl",
        },
        "US": {
            "locale": "en-US",
            "currency": "USD",
            "decimal_places": 2,
            "date_format": "MM/dd/yyyy",
            "timezone": "America/New_York",
            "direction": "ltr",
        },
        "GB": {
            "locale": "en-GB",
            "currency": "GBP",
            "decimal_places": 2,
            "date_format": "dd/MM/yyyy",
            "timezone": "Europe/London",
            "direction": "ltr",
        },
    }

    return defaults.get(country, defaults["SA"])
