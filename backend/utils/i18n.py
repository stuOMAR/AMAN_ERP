"""Lightweight i18n helpers for backend HTTP errors.

This module provides a stable `http_error` helper used across routers.
The previous codebase referenced `utils.i18n` but the module was missing,
which prevented backend startup.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


LOCALE_FILE_EN = Path(__file__).resolve().parents[1] / "locales" / "errors.en.json"
LOCALE_FILE_AR = Path(__file__).resolve().parents[1] / "locales" / "errors.ar.json"


# Keep a minimal built-in fallback to avoid hard failures.
BUILTIN_MESSAGES = {
    "internal_error": "Internal server error",
    "invalid_data": "Invalid data",
    "no_data": "No data provided",
    "no_changes": "No changes detected",
    "no_data_to_update": "No data to update",
    "not_available": "Not available",
    "record_not_found": "Record not found",
    "match_not_found": "Match not found",
    "tolerance_not_found": "Tolerance not found",
    "match_approve_only_held": "Only held matches can be approved",
    "match_reject_only_held": "Only held matches can be rejected",
    "match_approved_with_exception": "Match approved with exception",
    "match_rejected": "Match rejected",
    "tolerance_updated": "Tolerance updated",
    "tolerance_created": "Tolerance created",
}


@lru_cache(maxsize=1)
def _load_messages() -> dict[str, dict[str, str]]:
    """Load locale messages from per-language JSON files once with safe fallback."""
    if not LOCALE_FILE_EN.exists():
        logger.warning("English i18n file not found at %s; using built-in messages", LOCALE_FILE_EN)
        return {"en": BUILTIN_MESSAGES, "ar": {}}

    try:
        en = json.loads(LOCALE_FILE_EN.read_text(encoding="utf-8"))
        ar = (
            json.loads(LOCALE_FILE_AR.read_text(encoding="utf-8"))
            if LOCALE_FILE_AR.exists()
            else {}
        )
        if not isinstance(en, dict) or not isinstance(ar, dict):
            raise ValueError("errors.<lang>.json files must contain JSON objects")
        merged_en = {**BUILTIN_MESSAGES, **en}
        return {"en": merged_en, "ar": ar}
    except Exception as exc:
        logger.exception(
            "Failed to load i18n locale files (%s, %s). Using fallback. Error: %s",
            LOCALE_FILE_EN,
            LOCALE_FILE_AR,
            exc,
        )
        return {"en": BUILTIN_MESSAGES, "ar": {}}


def _normalize_lang(lang: Any) -> str:
    """Normalize language values like 'ar-SA' to 'ar'. Can handle Request objects."""
    if lang is not None and not isinstance(lang, str):
        try:
            lang = getattr(getattr(lang, "state", None), "lang", None)
        except Exception:
            lang = None

    if not lang:
        return "en"
    return str(lang).split("-")[0].lower()


def _humanize_error_key(error_key: str) -> str:
    """Convert snake_case error keys into a readable fallback message."""
    cleaned = (error_key or "error").strip().replace("_", " ")
    if not cleaned:
        return "Error"
    return cleaned[0].upper() + cleaned[1:]


def i18n_message(message_key: str, lang: Any = None, **fmt: Any) -> str:
    """Resolve a message key to display text with safe fallback formatting."""
    messages = _load_messages()
    norm_lang = _normalize_lang(lang)
    lang_map = messages.get(norm_lang, {})
    en_map = messages.get("en", BUILTIN_MESSAGES)

    template = lang_map.get(message_key) or en_map.get(message_key)
    detail = template if template else _humanize_error_key(message_key)

    if fmt:
        try:
            detail = detail.format(**fmt)
        except Exception:
            pass
    return detail


def http_error(status_code: int, error_key: str, lang: str | None = None, **fmt: Any) -> dict[str, Any]:
    """Return kwargs compatible with `HTTPException(**http_error(...))`.

    Args:
        status_code: HTTP status code.
        error_key: Translation/message key used in routers.
        lang: Optional language (e.g., en, ar, ar-SA). Routers may also pass
            a Starlette/FastAPI ``Request`` object as ``lang`` and we will
            extract ``request.state.lang`` (set by ``AcceptLanguageMiddleware``).
        **fmt: Optional formatting fields for message templates.
    """
    # T9.4: allow callers to pass a Request directly for ergonomic use.
    if lang is not None and not isinstance(lang, str):
        try:
            lang = getattr(getattr(lang, "state", None), "lang", None)
        except Exception:
            lang = None
    detail = i18n_message(error_key, lang=lang, **fmt)

    return {
        "status_code": status_code,
        "detail": detail,
    }
