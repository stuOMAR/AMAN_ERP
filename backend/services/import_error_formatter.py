"""
Import-error formatter — sanitises structural hints from DB error messages
before they are returned to the caller or persisted.

Structural hints like ``column "salary"``, ``relation "employees"``, or
raw SQL fragments can leak schema details.  This formatter ensures they
are masked via ``sanitize_for_audit``.
"""

from __future__ import annotations

import logging
from services.audit_sanitizer import sanitize_for_audit

logger = logging.getLogger(__name__)


def format_import_error(raw_error: str, *, context: str = "import") -> str:
    """Return a sanitised version of *raw_error* safe for user display."""
    sanitized = sanitize_for_audit(raw_error, context=context)
    if isinstance(sanitized, str):
        return sanitized
    return str(sanitized)


def format_db_error_message(raw: str, *, context: str = "db_error") -> str:
    """Sanitise a database error string that may contain structural hints."""
    return format_import_error(raw, context=context)
