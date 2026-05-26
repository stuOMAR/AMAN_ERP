"""
AMAN ERP — Structured JSON Logging + Request-ID Middleware
OPS-001: Machine-readable logs for production, human-readable for development.
"""

import logging
import uuid
import time
import os
from contextvars import ContextVar
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# ── Context variable for request-scoped data ──────────────────────────────────
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


# ── Log injection sanitization ────────────────────────────────────────────────
import re  # noqa: E402

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitize_log_value(value: str) -> str:
    """Strip newlines, null bytes, and control characters from a log value."""
    value = value.replace("\n", " ").replace("\r", " ")
    return _CONTROL_CHAR_RE.sub("", value)


def _sanitize_extra_data(data: dict) -> dict:
    """Sanitize all string values in extra_data dict for log injection prevention."""
    sanitized = {}
    for key, value in data.items():
        if isinstance(value, str):
            sanitized[key] = _sanitize_log_value(value)
        else:
            sanitized[key] = value
    return sanitized


# ── JSON Formatter ────────────────────────────────────────────────────────────
class JSONFormatter(logging.Formatter):
    """Emit each log record as a single JSON line (ECS-like)."""

    def format(self, record: logging.LogRecord) -> str:
        import json
        from datetime import datetime, timezone

        payload = {
            "@timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get("-"),
        }
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "extra_data"):
            payload.update(_sanitize_extra_data(record.extra_data))
        return json.dumps(payload, ensure_ascii=False, default=str)


# ── Human-readable Formatter (dev) ───────────────────────────────────────────
class DevFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        rid = request_id_var.get("-")
        ts = self.formatTime(record, self.datefmt)
        msg = record.getMessage()
        base = f"{ts} [{rid[:8]}] {record.levelname:7s} {record.name} — {msg}"
        if record.exc_info and record.exc_info[0] is not None:
            base += "\n" + self.formatException(record.exc_info)
        return base


# ── Setup function (called once at startup) ──────────────────────────────────
def setup_logging():
    """Configure root logger based on APP_ENV."""
    env = os.environ.get("APP_ENV", "development")
    level = logging.DEBUG if env == "development" else logging.INFO

    handler = logging.StreamHandler()
    if env in ("production", "staging"):
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(DevFormatter(datefmt="%Y-%m-%d %H:%M:%S"))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Quiet noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


# ── Request-ID Middleware ─────────────────────────────────────────────────────
class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Assign a unique X-Request-ID to every request.
    - If the client/proxy already sends one, reuse it.
    - Log method, path, status, and duration automatically.
    """

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request_id_var.set(rid)

        logger = logging.getLogger("aman.http")
        start = time.monotonic()

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.monotonic() - start) * 1000, 2)
            logger.exception(
                "unhandled_exception method=%s path=%s duration_ms=%s",
                request.method,
                request.url.path,
                duration_ms,
            )
            raise

        duration_ms = round((time.monotonic() - start) * 1000, 2)
        response.headers["X-Request-ID"] = rid

        # Skip noisy health-check logs
        if request.url.path not in ("/health", "/api/health", "/metrics"):
            logger.info(
                "method=%s path=%s status=%s duration_ms=%s",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )

        return response
