"""
Request-body capture middleware for sensitive routes.

Intercepts POST/PUT/PATCH requests on routes marked as sensitive
(via ``require_sensitive_permission``) and sanitises the body before
any audit persistence.

This is an ASGI middleware injected in ``main.py``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from services.audit_sanitizer import sanitize_for_audit

logger = logging.getLogger(__name__)

# Paths that always have their bodies captured (sensitive routes).
_SENSITIVE_PREFIXES = (
    "/api/finance/",
    "/api/admin/credentials",
    "/api/admin/settings",
    "/api/admin/account-classifications",
    "/api/hr/payroll",
    "/api/hr/employees",
)


class AuditBodyCaptureMiddleware(BaseHTTPMiddleware):
    """Attach a sanitised body snapshot to ``request.state`` for audit use."""

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        method = request.method.upper()

        if method in ("POST", "PUT", "PATCH") and any(
            path.startswith(p) for p in _SENSITIVE_PREFIXES
        ):
            try:
                body_bytes = await request.body()
                if body_bytes:
                    body: Any = None
                    ct = request.headers.get("content-type", "")
                    if "application/json" in ct:
                        body = json.loads(body_bytes)
                    else:
                        body = body_bytes.decode("utf-8", errors="replace")

                    # Sanitise before attaching to request state.
                    request.state.audit_body = sanitize_for_audit(
                        body, context=f"{method} {path}"
                    )

                    # Re-expose the body for downstream handlers.
                    async def _receive():
                        return {"type": "http.request", "body": body_bytes}

                    request._receive = _receive
            except Exception:
                logger.debug("audit body capture failed for %s", path, exc_info=True)

        response = await call_next(request)
        return response
