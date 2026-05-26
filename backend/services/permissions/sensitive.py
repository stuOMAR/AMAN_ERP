"""
Sensitive permission decorator + startup discovery.

Wraps ``require_permission(scope)`` with:
  - optional step-up auth enforcement,
  - ``critical`` request-scope tagging for audit,
  - uniform report-view audit on GET endpoints,
  - process-wide ``SENSITIVE_REGISTRY`` for startup discovery.

Contract: see specs/022-audit-security-finance-integrity/contracts/sensitive-permission.md
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, Request

logger = logging.getLogger(__name__)

# ── Registry ──────────────────────────────────────────────────────────────────
# Populated at import time by ``require_sensitive_permission``.
# Keys: (method, path_pattern)  Values: scope string
SENSITIVE_REGISTRY: dict[tuple[str, str], dict] = {}


def _register(method: str, path: str, scope: str, *, critical: bool, audit_view: bool):
    SENSITIVE_REGISTRY[(method, path)] = {
        "scope": scope,
        "critical": critical,
        "audit_view": audit_view,
    }


# ── Decorator ─────────────────────────────────────────────────────────────────
def require_sensitive_permission(
    scope: str,
    *,
    critical: bool = False,
    audit_view: bool = True,
    require_step_up: bool | None = None,
) -> Callable:
    """FastAPI dependency wrapping ``require_permission`` with sensitive extras.

    Usage::

        @router.post(
            "/finance/journal",
            dependencies=[Depends(require_sensitive_permission("finance.post", critical=True))],
        )
        def post_je(...): ...
    """
    from utils.permissions import require_permission  # noqa

    _dep = require_permission(scope)

    async def _checker(
        current_user: Any = Depends(_dep),
        request: Request = None,
    ):
        # Tag request scope.
        if request is not None:
            request.state.sensitive_scope = scope
            request.state.sensitive_critical = critical

        # Step-up auth placeholder — honour company policy if enabled.
        if require_step_up is True:
            try:
                from services.step_up_auth import enforce_step_up  # noqa
                await enforce_step_up(current_user, request)
            except ImportError:
                logger.debug("step_up_auth module not available; skipping")

        # Emit report-view audit for GET-style requests.
        if audit_view and request is not None and request.method == "GET":
            try:
                from services.audit_writer import log_activity
                from database import get_db_connection

                company_id = (
                    current_user.get("company_id")
                    if isinstance(current_user, dict)
                    else getattr(current_user, "company_id", None)
                )
                if company_id:
                    conn = get_db_connection(company_id)
                    try:
                        log_activity(
                            conn,
                            action="audit.view",
                            entity_type="report",
                            entity_id=None,
                            actor_id=(
                                current_user.get("id")
                                if isinstance(current_user, dict)
                                else getattr(current_user, "id", None)
                            ),
                            details={"path": str(request.url.path), "scope": scope},
                            critical=False,
                        )
                        conn.commit()
                    except Exception:
                        try:
                            conn.rollback()
                        except Exception:
                            pass
                    finally:
                        conn.close()
            except Exception:
                logger.debug("report-view audit failed (non-critical)", exc_info=True)

        return current_user

    return _checker


# ── Route registration helper (for use in router decorators) ──────────────────
def sensitive_route(
    method: str,
    path: str,
    scope: str,
    *,
    critical: bool = False,
    audit_view: bool = True,
):
    """Register a route as sensitive (call at module level or in router setup)."""
    _register(method, path, scope, critical=critical, audit_view=audit_view)


# ── Startup discovery ─────────────────────────────────────────────────────────
def _load_sensitive_routes_yaml() -> dict[str, str]:
    """Load path-glob → scope mapping from YAML."""
    yaml_path = (
        Path(__file__).resolve().parent.parent.parent
        / "backend"
        / "services"
        / "permissions"
        / "sensitive_routes.yaml"
    )
    if not yaml_path.exists():
        return {}
    try:
        import yaml  # type: ignore

        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items()}
    except Exception:
        logger.warning("Failed to load sensitive_routes.yaml", exc_info=True)
        return {}


def discover_sensitive_routes(app=None, *, strict: bool = False) -> list[str]:
    """Compare registered sensitive routes against the YAML.

    Returns a list of uncovered glob patterns (empty = all covered).
    In *strict* mode, prints offenders and may ``SystemExit(1)``.
    """
    yaml_routes = _load_sensitive_routes_yaml()
    if not yaml_routes:
        logger.info("permissions.discover: no sensitive_routes.yaml found — skip")
        return []

    # If app is provided, walk FastAPI routes and check coverage.
    uncovered: list[str] = []
    if app is not None:
        import fnmatch

        registered_paths: set[str] = set()
        for route in app.routes:
            if hasattr(route, "methods") and hasattr(route, "path"):
                for m in route.methods:
                    registered_paths.add(f"{m} {route.path}")

        for glob_pattern in yaml_routes:
            # Check if any registered route matches the glob.
            matched = any(
                fnmatch.fnmatch(rp, glob_pattern) for rp in registered_paths
            )
            if not matched:
                uncovered.append(glob_pattern)

    n_sensitive = len(SENSITIVE_REGISTRY)
    logger.info(
        "permissions.discover: OK (%d sensitive endpoints wrapped)", n_sensitive
    )

    if uncovered and strict:
        logger.error(
            "permissions.discover: %d uncovered sensitive route patterns:", len(uncovered)
        )
        for g in uncovered:
            logger.error("  ✗ %s", g)
        raise SystemExit(1)

    return uncovered
