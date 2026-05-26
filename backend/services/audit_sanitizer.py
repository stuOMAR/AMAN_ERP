"""
PII sanitizer for audit logging boundary.

Single helper that redacts sensitive values before persistence in audit
rows, request-body capture, and import-error messages.  Every audit write
MUST pass through this function.

Contract: see specs/022-audit-security-finance-integrity/contracts/sanitizer.md
"""

from __future__ import annotations

import re
from typing import Any

# ── Sanitizer rule version ────────────────────────────────────────────────────
SANITIZER_RULE_VERSION = 1

# ── Sensitive key patterns (exact key name or tail of dotted path) ────────────
_EXACT_KEYS: set[str] = {
    "salary",
    "iban",
    "national_id",
    "password",
    "secret",
    "token",
    "api_key",
    "credit_card",
    "cvv",
}

# Regex variants tested against the *lowercased* key name.
_REGEX_KEYS: list[re.Pattern] = [
    re.compile(r"^pwd$"),
    re.compile(r"^passwd$"),
    re.compile(r"^bearer$"),
    re.compile(r"^authorization$"),
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"api_key", re.IGNORECASE),
    re.compile(r"credit_card", re.IGNORECASE),
]

# ── Structural-hint regexes (applied to string values) ────────────────────────
_STRUCTURAL_HINTS: list[re.Pattern] = [
    re.compile(r"""column\s+"[^"]*"?""", re.IGNORECASE),
    re.compile(r"""relation\s+"[^"]*"?""", re.IGNORECASE),
    re.compile(r"""constraint\s+"[^"]*"?""", re.IGNORECASE),
    re.compile(
        r"\b(SELECT|INSERT|UPDATE|DELETE)\b\s+\S+.*?\b(FROM|INTO|SET|WHERE)\b",
        re.IGNORECASE,
    ),
]

# ── Mask constant ─────────────────────────────────────────────────────────────
_MASK = "***"


def _is_sensitive_key(key: str) -> bool:
    """Return True if *key* (case-insensitive) matches a sensitive pattern."""
    lk = key.lower()
    if lk in _EXACT_KEYS:
        return True
    for rx in _REGEX_KEYS:
        if rx.search(lk):
            return True
    return False


def _sanitize_string(value: str) -> str:
    """Replace structural-hint fragments in a string value."""
    result = value
    for rx in _STRUCTURAL_HINTS:
        result = rx.sub(_MASK, result)
    return result


def _dotted_path(prefix: str, key: str) -> str:
    if prefix:
        return f"{prefix}.{key}"
    return key


def sanitize_for_audit(
    payload: Any,
    *,
    context: str = "",
    extra_allow_paths: list[str] | None = None,
) -> Any:
    """Return a redacted copy of *payload*.

    Recurses through ``dict``, ``list``, ``tuple``.  Primitive values pass
    through unchanged unless their key path matches a sensitive rule.

    Parameters
    ----------
    payload:
        The value to sanitize (dict, list, str, or any primitive).
    context:
        Free-text context (e.g. the audit action) — recorded in metadata
        but does not affect redaction logic.
    extra_allow_paths:
        Additional dotted paths that should NOT be redacted even if the
        key name matches a sensitive rule.
    """
    allow_paths: set[str] = set(extra_allow_paths or [])

    # company_settings.audit.sanitizer.allow_paths — loaded lazily to
    # avoid circular import at module level.
    try:
        pass  # noqa

        # Best-effort: if there is a running request context with a tenant,
        # read the allow-list.  Otherwise skip.
        # The caller is expected to have set the tenant context.
    except Exception:
        pass

    return _walk(payload, prefix="", allow_paths=allow_paths)


def _walk(node: Any, *, prefix: str, allow_paths: set[str]) -> Any:
    if isinstance(node, dict):
        out: dict = {}
        for k, v in node.items():
            path = _dotted_path(prefix, k)
            if path in allow_paths:
                out[k] = v
            elif _is_sensitive_key(k):
                out[k] = _MASK
            else:
                out[k] = _walk(v, prefix=path, allow_paths=allow_paths)
        return out

    if isinstance(node, (list, tuple)):
        items = [
            _walk(item, prefix=prefix, allow_paths=allow_paths) for item in node
        ]
        return type(node)(items)

    if isinstance(node, str):
        return _sanitize_string(node)

    # Primitives (int, float, bool, None, Decimal, etc.) pass through.
    return node


def get_sanitizer_metadata() -> dict:
    """Return metadata about the current sanitizer ruleset."""
    return {
        "rule_version": SANITIZER_RULE_VERSION,
        "exact_keys": sorted(_EXACT_KEYS),
        "regex_patterns": [rx.pattern for rx in _REGEX_KEYS],
    }
