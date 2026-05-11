"""
AMAN ERP — SSO/LDAP Router
Endpoints for SSO configuration management and SSO authentication flows.
"""

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

from config import settings
from database import get_system_db, get_db_connection
from schemas.sso import (
    SsoConfigCreate, SsoConfigUpdate, SsoConfigRead,
    GroupRoleMappingCreate, GroupRoleMappingRead,
    LdapTestRequest, SamlMetadataResponse, SsoLoginRequest,
)
from routers.auth import get_current_user
from services import sso_service
from utils.permissions import require_permission
from utils.cache import cache
from utils.i18n import http_error

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/sso", tags=["SSO/LDAP"])


# ---------------------------------------------------------------------------
# Helpers — resolve company_id from the current user
# ---------------------------------------------------------------------------

def _get_company_id_from_user(current_user) -> str:
    cid = getattr(current_user, "company_id", None)
    if not cid:
        raise HTTPException(**http_error(400, ("company_id_not_available", request)))
    return cid


def _resolve_company_id_public(company_id: Optional[str], company_code: Optional[str]) -> str:
    """Resolve a company_id from either an explicit param or a company_code lookup."""
    if company_id:
        return company_id
    if company_code:
        db = get_system_db()
        row = db.execute(
            text("SELECT id FROM system_companies WHERE id = :code AND status = 'active'"),
            {"code": company_code.strip()},
        ).fetchone()
        if not row:
            raise HTTPException(**http_error(404, ("sso_company_not_found", request)))
        return row[0]
    raise HTTPException(**http_error(400, ("sso_company_id_required", request)))


# ---------------------------------------------------------------------------
# Admin endpoints (require sso.manage)
# ---------------------------------------------------------------------------

@router.get("/config", response_model=List[SsoConfigRead],
            dependencies=[Depends(require_permission("sso.manage"))])
async def list_sso_configs(request: Request, current_user=Depends(get_current_user)):
    """List Sso Configs."""
    company_id = _get_company_id_from_user(current_user)
    try:
        configs = sso_service.get_sso_configs(company_id)
        return configs
    except (OperationalError, ProgrammingError):
        logger.exception("SSO config listing failed for company %s due to DB/schema issue", company_id)
        raise HTTPException(**http_error(500, "sso_database_not_ready", request))
    except Exception:
        logger.exception("Unexpected SSO config listing failure for company %s", company_id)
        raise HTTPException(**http_error(500, "sso_config_load_failed", request))


@router.post("/config", response_model=SsoConfigRead, status_code=201,
             dependencies=[Depends(require_permission("sso.manage"))])
async def create_sso_config(body: SsoConfigCreate, request: Request, current_user=Depends(get_current_user)):
    """Create Sso Config."""
    company_id = _get_company_id_from_user(current_user)
    try:
        result = sso_service.create_sso_config(body.model_dump(), company_id)
        return result
    except (OperationalError, ProgrammingError):
        logger.exception("SSO config creation failed for company %s due to DB/schema issue", company_id)
        raise HTTPException(**http_error(500, "sso_database_not_ready", request))


@router.put("/config/{config_id}", response_model=SsoConfigRead,
            dependencies=[Depends(require_permission("sso.manage"))])
async def update_sso_config(config_id: int, body: SsoConfigUpdate, request: Request, current_user=Depends(get_current_user)):
    """Update Sso Config."""
    company_id = _get_company_id_from_user(current_user)
    try:
        existing = sso_service.get_sso_config_by_id(config_id, company_id)
    except (OperationalError, ProgrammingError):
        logger.exception("SSO config fetch/update precheck failed for company %s", company_id)
        raise HTTPException(**http_error(500, "sso_database_not_ready", request))
    if not existing:
        raise HTTPException(**http_error(404, ("sso_config_not_found", request)))
    try:
        result = sso_service.update_sso_config(config_id, body.model_dump(exclude_unset=True), company_id)
        return result
    except (OperationalError, ProgrammingError):
        logger.exception("SSO config update failed for company %s", company_id)
        raise HTTPException(**http_error(500, "sso_database_not_ready", request))


@router.delete("/config/{config_id}", status_code=200,
               dependencies=[Depends(require_permission("sso.manage"))], response_model=Dict[str, Any])
async def deactivate_sso_config(config_id: int, request: Request, current_user=Depends(get_current_user)):
    """Deactivate Sso Config."""
    company_id = _get_company_id_from_user(current_user)
    try:
        success = sso_service.deactivate_sso_config(config_id, company_id)
    except (OperationalError, ProgrammingError):
        logger.exception("SSO config deactivation failed for company %s", company_id)
        raise HTTPException(**http_error(500, "sso_database_not_ready", request))
    if not success:
        raise HTTPException(**http_error(404, ("sso_config_not_found", request)))
    return {"detail": "SSO configuration deactivated"}


# ---------------------------------------------------------------------------
# Group-role mappings (require sso.manage)
# ---------------------------------------------------------------------------

@router.get("/mappings", response_model=List[GroupRoleMappingRead],
            dependencies=[Depends(require_permission("sso.manage"))])
async def list_mappings(request: Request, sso_configuration_id: Optional[int] = None, current_user=Depends(get_current_user)):
    """List Mappings."""
    company_id = _get_company_id_from_user(current_user)
    try:
        return sso_service.get_group_role_mappings(company_id, sso_configuration_id)
    except (OperationalError, ProgrammingError):
        logger.exception("SSO mappings listing failed for company %s", company_id)
        raise HTTPException(**http_error(500, "sso_database_not_ready", request))


@router.post("/mappings", response_model=GroupRoleMappingRead, status_code=201,
             dependencies=[Depends(require_permission("sso.manage"))])
async def create_mapping(body: GroupRoleMappingCreate, request: Request, current_user=Depends(get_current_user)):
    """Create Mapping."""
    company_id = _get_company_id_from_user(current_user)
    try:
        return sso_service.create_group_role_mapping(body.model_dump(), company_id)
    except (OperationalError, ProgrammingError):
        logger.exception("SSO mapping creation failed for company %s", company_id)
        raise HTTPException(**http_error(500, "sso_database_not_ready", request))


# ---------------------------------------------------------------------------
# LDAP test connection (admin)
# ---------------------------------------------------------------------------

@router.post("/ldap/test",
             dependencies=[Depends(require_permission("sso.manage"))], response_model=Dict[str, Any])
async def test_ldap(body: LdapTestRequest):
    """Test LDAP."""
    result = sso_service.test_ldap_connection(
        ldap_host=body.ldap_host,
        ldap_port=body.ldap_port,
        ldap_base_dn=body.ldap_base_dn,
        ldap_bind_dn=body.ldap_bind_dn,
        ldap_bind_password=body.ldap_bind_password,
        ldap_use_tls=body.ldap_use_tls,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


# ---------------------------------------------------------------------------
# Public endpoints — SAML metadata, ACS callback, SSO login initiation
# ---------------------------------------------------------------------------

@router.get("/providers", response_model=List[Dict[str, Any]])
async def list_active_providers(
    company_id: Optional[str] = None,
    company_code: Optional[str] = None,
):
    """
    Public endpoint — returns active SSO providers for the login page.
    Called before authentication, so company_id must be supplied as a query param.
    Returns an empty list if the company is not found or SSO is not configured.
    """
    try:
        cid = _resolve_company_id_public(company_id, company_code)
    except HTTPException:
        return []
    try:
        return sso_service.get_active_sso_configs(cid)
    except (OperationalError, ProgrammingError):
        # sso_configurations table may not exist on older tenant DBs
        return []
    except Exception:
        return []


@router.get("/saml/metadata", response_model=Dict[str, Any])
async def saml_metadata(
    company_id: Optional[str] = None,
    company_code: Optional[str] = None,
):
    """Return SAML SP metadata XML."""
    cid = _resolve_company_id_public(company_id, company_code)
    configs = sso_service.get_sso_configs(cid)
    saml_cfg = next((c for c in configs if c["provider_type"] == "saml" and c.get("is_active")), None)
    if not saml_cfg:
        raise HTTPException(**http_error(404, ("sso_no_saml_config", request)))
    metadata_xml = sso_service.get_saml_sp_metadata(cid, saml_cfg)
    base_url = settings.FRONTEND_URL.rstrip("/")
    sp_entity_id = f"{base_url}/api/auth/sso/saml/metadata?company_id={cid}"
    acs_url = f"{base_url}/api/auth/sso/saml/acs"
    return SamlMetadataResponse(entity_id=sp_entity_id, acs_url=acs_url, metadata_xml=metadata_xml)


@router.post("/saml/acs")
async def saml_acs(request: Request, response: Response):
    """
    SAML Assertion Consumer Service — receives the POST from the IdP.
    Provisions the user, issues a one-time SSO ticket, and redirects the
    browser to the frontend with `?sso_ticket=...`. The frontend then calls
    `/auth/sso/exchange` to retrieve the access/refresh tokens.

    This ticket-exchange pattern avoids setting bearer tokens in URL fragments
    or query strings, and does not require server-side cookie plumbing that
    the auth router currently does not provide.
    """
    from routers.auth import create_access_token, create_refresh_token

    form = await request.form()
    saml_response = form.get("SAMLResponse")
    relay_state = form.get("RelayState", "")
    if not saml_response:
        raise HTTPException(**http_error(400, ("sso_missing_saml_response", request)))

    # SEC-FIX: Look up server-side state by relay token instead of parsing URI
    if not relay_state:
        raise HTTPException(**http_error(400, ("sso_missing_relay_state", request)))
    state_data = cache.get(f"saml_state:{relay_state}")
    if not state_data:
        raise HTTPException(**http_error(400, ("sso_invalid_relay_state", request)))
    company_id = state_data["company_id"]
    sso_config_id_str = str(state_data["sso_config_id"])
    # Delete used state token to prevent replay
    cache.delete(f"saml_state:{relay_state}")

    sso_config = sso_service.get_sso_config_by_id(int(sso_config_id_str), company_id)
    if not sso_config or sso_config["provider_type"] != "saml":
        raise HTTPException(**http_error(400, ("sso_invalid_config", request)))

    try:
        assertion = sso_service.saml_process_acs(
            {"SAMLResponse": saml_response},
            sso_config,
            company_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    # Map groups → role
    role_name = sso_service.map_groups_to_role(sso_config["id"], assertion.get("groups", []), company_id)

    # Provision / update user
    name_id = assertion["name_id"]
    attrs = assertion.get("attributes", {})
    display_name = (attrs.get("displayName") or attrs.get("cn") or [name_id])[0] if isinstance(
        attrs.get("displayName", attrs.get("cn")), list
    ) else name_id
    email = (attrs.get("email") or attrs.get("mail") or [name_id])[0] if isinstance(
        attrs.get("email", attrs.get("mail")), list
    ) else name_id

    user_info = sso_service.provision_or_update_user(
        company_id=company_id,
        username=name_id,
        display_name=display_name,
        email=email,
        role_name=role_name,
    )

    # Build token
    auth_payload = _build_auth_payload(user_info, company_id)
    access_token = create_access_token(auth_payload)
    refresh_token = create_refresh_token(auth_payload)

    # One-time ticket stored in short-lived cache; frontend exchanges it
    ticket = str(uuid.uuid4())
    cache.set(
        f"sso_ticket:{ticket}",
        {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": {
                "username": user_info["username"],
                "role": user_info.get("role"),
                "company_id": company_id,
                "permissions": user_info.get("permissions", []),
            },
        },
        expire=120,  # 2 minutes max
    )

    from fastapi.responses import RedirectResponse
    return RedirectResponse(
        url=f"{settings.FRONTEND_URL}/sso/callback?sso_ticket={ticket}",
        status_code=302,
    )


@router.post("/exchange", response_model=Dict[str, Any])
async def sso_exchange(payload: dict):
    """
    Exchange a one-time SSO ticket (issued by /saml/acs) for access & refresh
    tokens. Ticket is invalidated immediately after exchange.
    """
    ticket = (payload or {}).get("ticket")
    if not ticket:
        raise HTTPException(**http_error(400, ("sso_missing_ticket", request)))
    data = cache.get(f"sso_ticket:{ticket}")
    if not data:
        raise HTTPException(**http_error(400, ("sso_invalid_ticket", request)))
    cache.delete(f"sso_ticket:{ticket}")
    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "token_type": "bearer",
        "user": data["user"],
    }


@router.post("/login", response_model=Dict[str, Any])
async def sso_login(body: SsoLoginRequest, response: Response):
    """
    Initiate SSO login.
    - SAML: returns {"redirect_url": "..."} for frontend to redirect.
    - LDAP: performs direct auth and returns tokens.
    """
    from routers.auth import create_access_token, create_refresh_token

    # Look up SSO config — we need the company_id. The schema doesn't carry it,
    # so we look across system_companies for who owns this config.
    # For now, company_id is required in the request body or we derive from context.
    company_id = getattr(body, "company_id", None)
    if not company_id:
        # Try to find which company has this SSO config
        company_id = _find_company_for_sso_config(body.sso_configuration_id)
    if not company_id:
        raise HTTPException(**http_error(400, ("sso_cannot_determine_company", request)))

    sso_config = sso_service.get_sso_config_by_id(body.sso_configuration_id, company_id)
    if not sso_config or not sso_config.get("is_active"):
        raise HTTPException(**http_error(404, ("sso_config_inactive", request)))

    if sso_config["provider_type"] == "saml":
        # Return redirect URL for SAML
        redirect_url = sso_service.saml_initiate_login(sso_config, company_id)
        # SEC-FIX: Store state server-side instead of exposing company_id:config_id in RelayState
        state_token = str(uuid.uuid4())
        cache.set(f"saml_state:{state_token}", {
            "company_id": company_id,
            "sso_config_id": sso_config["id"],
        }, expire=300)  # 5-minute TTL
        separator = "&" if "?" in redirect_url else "?"
        redirect_url += f"{separator}RelayState={state_token}"
        return {"redirect_url": redirect_url}

    elif sso_config["provider_type"] == "ldap":
        if not body.username or not body.password:
            raise HTTPException(**http_error(400, ("sso_ldap_credentials_required", request)))
        try:
            ldap_result = sso_service.ldap_authenticate(sso_config, body.username, body.password)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc))
        except ConnectionError:
            # IdP down — check fallback admin
            raise HTTPException(**http_error(503, "ldap_server_unreachable_use_local_login_if_you_are", request))

        # Map groups → role
        role_name = sso_service.map_groups_to_role(
            sso_config["id"], ldap_result.get("groups", []), company_id
        )

        user_info = sso_service.provision_or_update_user(
            company_id=company_id,
            username=ldap_result["username"],
            display_name=ldap_result.get("display_name", ""),
            email=ldap_result.get("email", ""),
            role_name=role_name,
        )

        auth_payload = _build_auth_payload(user_info, company_id)
        access_token = create_access_token(auth_payload)
        refresh_token = create_refresh_token(auth_payload)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": {
                "username": user_info["username"],
                "role": user_info["role"],
                "company_id": company_id,
                "permissions": user_info.get("permissions", []),
            },
        }

    raise HTTPException(status_code=400, detail=i18n_message("sso_unsupported_provider", request))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_auth_payload(user_info: dict, company_id: str) -> dict:
    """Build the JWT payload dict, matching the shape used in auth.py login."""
    perms = user_info.get("permissions", [])
    if isinstance(perms, dict) and perms.get("all") is True:
        perms = ["*"]
    elif not isinstance(perms, list):
        perms = []

    role = user_info.get("role", "user")
    if role in ("admin", "system_admin", "superuser"):
        perms = ["*"]

    # Fetch enabled_modules from system_companies
    enabled_modules = []
    try:
        db = get_system_db()
        row = db.execute(
            text("SELECT enabled_modules FROM system_companies WHERE id = :id"),
            {"id": company_id},
        ).fetchone()
        if row and row[0]:
            enabled_modules = row[0] if isinstance(row[0], list) else json.loads(row[0]) if isinstance(row[0], str) else []
    except Exception:
        pass

    # Fetch allowed branches
    allowed_branches = []
    try:
        with get_db_connection(company_id) as conn:
            branch_rows = conn.execute(
                text("SELECT branch_id FROM user_branches WHERE user_id = :uid"),
                {"uid": user_info["id"]},
            ).fetchall()
            allowed_branches = [r[0] for r in branch_rows] if branch_rows else []
    except Exception:
        pass

    return {
        "sub": user_info["username"],
        "user_id": user_info["id"],
        "company_id": company_id,
        "role": role,
        "permissions": perms,
        "enabled_modules": enabled_modules,
        "allowed_branches": allowed_branches,
        "type": "company_user",
    }


def _find_company_for_sso_config(sso_config_id: int) -> Optional[str]:
    """Search across companies to find who owns this SSO config. Brute-force fallback."""
    db = get_system_db()
    companies = db.execute(
        text("SELECT id FROM system_companies WHERE status = 'active'")
    ).fetchall()
    for (cid,) in companies:
        try:
            cfg = sso_service.get_sso_config_by_id(sso_config_id, cid)
            if cfg:
                return cid
        except Exception:
            continue
    return None
