"""T108: Namespaced cache key builder — report and dashboard keys.

Replaces ad-hoc cache key construction across report and dashboard services.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def report_key(company_id: str, report_code: str, params: dict[str, Any] | None = None,
               as_of_date: str | None = None) -> str:
    """Build a namespaced report cache key.

    Format: ``t:{tenant}:report:{code}:{params_hash}:{as_of}``
    """
    params_hash = _hash_params(params) if params else "default"
    as_of = as_of_date or "current"
    return f"t:{company_id}:report:{report_code}:{params_hash}:{as_of}"


def dashboard_key(company_id: str, role: str, widget: str,
                  params: dict[str, Any] | None = None) -> str:
    """Build a namespaced dashboard cache key.

    Format: ``t:{tenant}:dashboard:{role}:{widget}:{params_hash}``
    """
    params_hash = _hash_params(params) if params else "default"
    return f"t:{company_id}:dashboard:{role}:{widget}:{params_hash}"


def _hash_params(params: dict[str, Any]) -> str:
    """Deterministic short hash of params dict."""
    raw = json.dumps(params, sort_keys=True, default=str)
    return hashlib.md5(raw.encode()).hexdigest()[:12]
