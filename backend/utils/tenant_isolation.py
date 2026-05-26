"""Tenant isolation helper — closes SEC-C1 (cross-tenant privilege escalation).

Use `resolve_target_company_id()` in any endpoint that previously accepted an
optional `company_id` query parameter. It enforces that only `system_admin`
may target a tenant other than their own; all other callers are pinned to the
company_id embedded in their JWT, regardless of what they send.
"""

from typing import Any, Optional

from fastapi import HTTPException

from utils.i18n import http_error


def resolve_target_company_id(
    requested_company_id: Optional[str],
    current_user: Any,
    request: Any = None,
) -> str:
    """Resolve the effective tenant for an authenticated request.

    Rules:
      * If the caller is a `system_admin`, they MAY target any tenant they pass;
        if they pass nothing and have no own tenant, return an empty string to
        signal a system-wide view (the caller must handle this case).
        If they pass nothing but have their own tenant, return that.
      * All other callers are pinned to `current_user.company_id`. If they
        supplied a different `company_id`, return 403. If they supplied the
        same value or nothing, accept the tenant from JWT.

    Raises:
      HTTPException 400 when no tenant can be resolved for a non-superuser.
      HTTPException 403 on any cross-tenant attempt by a non-superuser.
    """
    own = getattr(current_user, "company_id", None)
    role = getattr(current_user, "role", None)

    if role == "system_admin":
        # system_admin may target any tenant, or fall through to system-wide view.
        return requested_company_id or own or ""

    if requested_company_id and requested_company_id != own:
        raise HTTPException(**http_error(403, "cross_tenant_access_forbidden", request))

    if not own:
        raise HTTPException(**http_error(400, "company_id_missing", request))
    return own
