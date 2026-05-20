"""
AMAN ERP - PII / Secret Masking Utilities
=========================================

Two helpers for two different audiences:

- ``mask_pii(value, visible_chars=4)`` — for displaying PII to a user that
  partially trusts the value (e.g. last 4 digits of a tax id in a UI).
- ``redact_token(value, head=4)`` — for log records and adapter responses
  that must never echo a raw secret. Shows at most the first ``head``
  characters and replaces the remainder with ``****``. Empty inputs become
  the literal ``"<empty>"`` so log lines stay grep-friendly.

Both helpers are pure-Python and side-effect-free; they NEVER raise on
``None`` so call sites can wrap untrusted values without try/except.
"""
from __future__ import annotations

from typing import Optional


def mask_pii(value: str, visible_chars: int = 4) -> str:
    """
    Mask a PII string, showing only the last `visible_chars` characters.

    Args:
        value: The sensitive value to mask.
        visible_chars: Number of trailing characters to keep visible.

    Returns:
        Masked string with asterisks replacing hidden characters,
        or the original value if it's None/empty or shorter than visible_chars.

    Examples:
        mask_pii("SA1234567890123456") → "**************3456"
        mask_pii("1234567890")         → "******7890"
        mask_pii(None)                 → None
        mask_pii("123")               → "123"
    """
    if not value:
        return value
    value_str = str(value)
    if len(value_str) <= visible_chars:
        return value_str
    masked_len = len(value_str) - visible_chars
    return "*" * masked_len + value_str[-visible_chars:]


def redact_token(value: Optional[str], head: int = 4) -> str:
    """Return a log-safe representation of a secret token.

    Args:
        value: The secret string (Bearer token, API key, OTP, CSR, etc.).
        head: Number of leading characters to keep visible.

    Returns:
        ``"<empty>"`` when the input is falsy, ``"****"`` when the token is
        too short to safely show any prefix, otherwise ``"<head>…****"``.

    Examples:
        redact_token("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc")  → "eyJh…****"
        redact_token("abc")                                      → "****"
        redact_token(None)                                       → "<empty>"
        redact_token("", head=2)                                 → "<empty>"

    Notes:
        - The helper never raises and never echoes the suffix of the secret.
        - Use this in ``logger.warning("...%s", redact_token(token))``,
          NOT for any code path that needs to use the value (it is lossy).
    """
    if not value:
        return "<empty>"
    s = str(value)
    if len(s) <= head:
        return "****"
    return f"{s[:head]}\u2026****"
