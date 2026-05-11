"""
AMAN ERP — SSO/LDAP Service
Handles SAML SP flow, LDAP bind authentication, group→role mapping, and user provisioning.
"""

import logging
import os
from typing import Optional, Dict, Any, List

from sqlalchemy import text

from config import settings
from database import db_connection, hash_password

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SAML helpers
# ---------------------------------------------------------------------------

def _build_saml_settings(sso_config: Dict[str, Any], company_id: str) -> dict:
    """Build python3-saml settings dict from an SsoConfiguration row."""
    base_url = settings.FRONTEND_URL.rstrip("/")
    sp_entity_id = f"{base_url}/api/auth/sso/saml/metadata?company_id={company_id}"
    acs_url = f"{base_url}/api/auth/sso/saml/acs"

    saml_settings: dict = {
        "strict": True,
        "debug": settings.APP_ENV != "production",
        "sp": {
            "entityId": sp_entity_id,
            "assertionConsumerService": {
                "url": acs_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
        },
        "idp": {},
        "security": {
            "authnRequestsSigned": False,
            "wantAssertionsSigned": True,
            "wantNameIdEncrypted": False,
        },
    }

    if sso_config.get("metadata_url"):
        # Caller should pre-fetch and parse — we store metadata_xml after first fetch.
        pass

    if sso_config.get("metadata_xml"):
        try:
            from onelogin.saml2.idp_metadata_parser import OneLogin_Saml2_IdPMetadataParser
            idp_data = OneLogin_Saml2_IdPMetadataParser.parse(sso_config["metadata_xml"])
            saml_settings.update(idp_data)
        except Exception as exc:
            logger.error("Failed to parse IdP metadata XML: %s", exc)
            raise ValueError("Invalid IdP metadata XML") from exc

    return saml_settings


def saml_initiate_login(sso_config: Dict[str, Any], company_id: str) -> str:
    """
    Return the IdP redirect URL for an SP-initiated SAML login.
    """
    from onelogin.saml2.auth import OneLogin_Saml2_Auth

    saml_settings = _build_saml_settings(sso_config, company_id)
    # python3-saml requires a "request" dict — we build a minimal one.
    req = {
        "https": "on" if settings.APP_ENV == "production" else "off",
        "http_host": settings.FRONTEND_URL.split("//")[-1].split("/")[0],
        "script_name": "/api/auth/sso/saml/acs",
        "get_data": {},
        "post_data": {},
    }
    auth = OneLogin_Saml2_Auth(req, old_settings=saml_settings)
    redirect_url = auth.login()
    return redirect_url


def saml_process_acs(
    saml_response_post: Dict[str, str],
    sso_config: Dict[str, Any],
    company_id: str,
) -> Dict[str, Any]:
    """
    Process the SAML ACS POST callback.
    Returns dict with 'name_id', 'attributes', 'groups'.
    """
    from onelogin.saml2.auth import OneLogin_Saml2_Auth

    saml_settings = _build_saml_settings(sso_config, company_id)
    req = {
        "https": "on" if settings.APP_ENV == "production" else "off",
        "http_host": settings.FRONTEND_URL.split("//")[-1].split("/")[0],
        "script_name": "/api/auth/sso/saml/acs",
        "get_data": {},
        "post_data": saml_response_post,
    }
    auth = OneLogin_Saml2_Auth(req, old_settings=saml_settings)
    auth.process_response()
    errors = auth.get_errors()
    if errors:
        logger.error("SAML ACS errors: %s — reason: %s", errors, auth.get_last_error_reason())
        raise ValueError(f"SAML validation failed: {', '.join(errors)}")

    if not auth.is_authenticated():
        raise ValueError("SAML authentication failed")

    attrs = auth.get_attributes()
    groups: List[str] = attrs.get("groups", attrs.get("memberOf", []))
    return {
        "name_id": auth.get_nameid(),
        "attributes": attrs,
        "groups": groups,
    }


def get_saml_sp_metadata(company_id: str, sso_config: Dict[str, Any]) -> str:
    """Generate SP metadata XML."""
    from onelogin.saml2.auth import OneLogin_Saml2_Auth

    saml_settings = _build_saml_settings(sso_config, company_id)
    req = {
        "https": "on" if settings.APP_ENV == "production" else "off",
        "http_host": settings.FRONTEND_URL.split("//")[-1].split("/")[0],
        "script_name": "/api/auth/sso/saml/metadata",
        "get_data": {},
        "post_data": {},
    }
    auth = OneLogin_Saml2_Auth(req, old_settings=saml_settings)
    metadata = auth.get_settings().get_sp_metadata()
    if isinstance(metadata, bytes):
        metadata = metadata.decode("utf-8")
    return metadata


# ---------------------------------------------------------------------------
# LDAP helpers
# ---------------------------------------------------------------------------

def ldap_authenticate(
    sso_config: Dict[str, Any],
    username: str,
    password: str,
) -> Dict[str, Any]:
    """
    Bind-authenticate a user against the configured LDAP directory.
    Returns dict with 'dn', 'attributes', 'groups'.
    Raises ValueError on auth failure.
    """
    import ldap as ldap_lib

    host = sso_config["ldap_host"]
    port = sso_config.get("ldap_port") or 636
    base_dn = sso_config["ldap_base_dn"]
    bind_dn = sso_config.get("ldap_bind_dn")
    use_tls = sso_config.get("ldap_use_tls", True)

    uri = f"ldaps://{host}:{port}" if use_tls else f"ldap://{host}:{port}"

    conn = ldap_lib.initialize(uri)
    conn.set_option(ldap_lib.OPT_NETWORK_TIMEOUT, 10)
    conn.set_option(ldap_lib.OPT_REFERRALS, 0)
    if use_tls:
        conn.set_option(ldap_lib.OPT_X_TLS_REQUIRE_CERT, ldap_lib.OPT_X_TLS_DEMAND)
        ca_cert = os.environ.get("LDAP_CA_CERT_PATH")
        if ca_cert and os.path.exists(ca_cert):
            conn.set_option(ldap_lib.OPT_X_TLS_CACERTFILE, ca_cert)
        if not uri.startswith("ldaps://"):
            conn.start_tls_s()

    try:
        # Service-account bind to search for the user
        if bind_dn:
            # We do NOT store the service-account password — use the user's password for now.
            pass

        # Search for the user entry
        search_filter = f"(|(uid={ldap_lib.filter.escape_filter_chars(username)})" \
                        f"(sAMAccountName={ldap_lib.filter.escape_filter_chars(username)})" \
                        f"(mail={ldap_lib.filter.escape_filter_chars(username)}))"
        results = conn.search_s(base_dn, ldap_lib.SCOPE_SUBTREE, search_filter,
                                ["dn", "cn", "mail", "memberOf", "uid", "sAMAccountName"])

        if not results or not results[0][0]:
            raise ValueError("User not found in LDAP directory")

        user_dn = results[0][0]
        user_attrs = results[0][1]

        # Bind as the actual user to verify password
        conn.simple_bind_s(user_dn, password)

        groups: List[str] = []
        member_of = user_attrs.get("memberOf", [])
        for g in member_of:
            if isinstance(g, bytes):
                g = g.decode("utf-8")
            # Extract CN from DN (e.g. "CN=Finance,OU=Groups,DC=corp")
            if g.upper().startswith("CN="):
                groups.append(g.split(",")[0][3:])
            else:
                groups.append(g)

        display_name = ""
        cn = user_attrs.get("cn", [b""])
        if cn:
            display_name = cn[0].decode("utf-8") if isinstance(cn[0], bytes) else cn[0]

        email = ""
        mail = user_attrs.get("mail", [b""])
        if mail:
            email = mail[0].decode("utf-8") if isinstance(mail[0], bytes) else mail[0]

        return {
            "dn": user_dn,
            "username": username,
            "display_name": display_name,
            "email": email,
            "groups": groups,
            "attributes": {k: [v.decode("utf-8") if isinstance(v, bytes) else v for v in vs]
                           for k, vs in user_attrs.items()},
        }
    except ldap_lib.INVALID_CREDENTIALS:
        raise ValueError("Invalid LDAP credentials")
    except ldap_lib.SERVER_DOWN:
        raise ConnectionError("LDAP server unreachable")
    finally:
        try:
            conn.unbind_s()
        except Exception:
            pass


def test_ldap_connection(
    ldap_host: str,
    ldap_port: int,
    ldap_base_dn: str,
    ldap_bind_dn: str,
    ldap_bind_password: str,
    ldap_use_tls: bool = True,
) -> Dict[str, Any]:
    """
    Test LDAP connectivity — returns {"success": True/False, "message": "..."}.
    """
    import ldap as ldap_lib

    uri = f"ldaps://{ldap_host}:{ldap_port}" if ldap_use_tls else f"ldap://{ldap_host}:{ldap_port}"
    try:
        conn = ldap_lib.initialize(uri)
        conn.set_option(ldap_lib.OPT_NETWORK_TIMEOUT, 10)
        conn.set_option(ldap_lib.OPT_REFERRALS, 0)
        if ldap_use_tls:
            conn.set_option(ldap_lib.OPT_X_TLS_REQUIRE_CERT, ldap_lib.OPT_X_TLS_DEMAND)
            ca_cert = os.environ.get("LDAP_CA_CERT_PATH")
            if ca_cert and os.path.exists(ca_cert):
                conn.set_option(ldap_lib.OPT_X_TLS_CACERTFILE, ca_cert)
            if not uri.startswith("ldaps://"):
                conn.start_tls_s()
        conn.simple_bind_s(ldap_bind_dn, ldap_bind_password)
        # Quick search to confirm base_dn is valid
        conn.search_s(ldap_base_dn, ldap_lib.SCOPE_BASE, "(objectClass=*)", ["dn"])
        conn.unbind_s()
        return {"success": True, "message": i18n_message("ldap_connection_successful", request)}
    except ldap_lib.INVALID_CREDENTIALS:
        return {"success": False, "message": i18n_message("ldap_invalid_credentials", request)}
    except ldap_lib.SERVER_DOWN:
        return {"success": False, "message": i18n_message("ldap_server_unreachable", request)}
    except Exception:
        logger.exception("LDAP test connection failed")
        return {"success": False, "message": i18n_message("ldap_connection_failed", request)}


# ---------------------------------------------------------------------------
# Group → Role mapping
# ---------------------------------------------------------------------------

def map_groups_to_role(
    sso_config_id: int,
    external_groups: List[str],
    company_id: str,
) -> Optional[str]:
    """
    Given a list of IdP group names, look up the SsoGroupRoleMapping table
    and return the AMAN role_name for the first match.
    Returns None if no mapping matches.
    """
    if not external_groups:
        return None

    with db_connection(company_id) as conn:
        placeholders = ", ".join(f":g{i}" for i in range(len(external_groups)))
        params: Dict[str, Any] = {f"g{i}": g for i, g in enumerate(external_groups)}
        params["cfg_id"] = sso_config_id

        row = conn.execute(
            text(f"""
                SELECT r.role_name
                FROM sso_group_role_mappings m
                JOIN roles r ON r.id = m.aman_role_id
                WHERE m.sso_configuration_id = :cfg_id
                  AND m.external_group_name IN ({placeholders})
                ORDER BY m.id
                LIMIT 1
            """),
            params,
        ).fetchone()

    return row[0] if row else None


# ---------------------------------------------------------------------------
# User provisioning / lookup
# ---------------------------------------------------------------------------

def provision_or_update_user(
    company_id: str,
    username: str,
    display_name: str,
    email: str,
    role_name: Optional[str],
) -> Dict[str, Any]:
    """
    Find or create the company_users row for an SSO-authenticated user.
    Returns a dict matching the shape expected by auth token creation.
    """
    with db_connection(company_id) as conn:
        existing = conn.execute(
            text("""
                SELECT id, username, email, full_name, role, permissions, is_active
                FROM company_users
                WHERE username = :username AND is_active = true
            """),
            {"username": username},
        ).fetchone()

        if existing:
            user_id, uname, uemail, ufull, urole, uperms, uactive = existing
            # Update display name / email if changed
            if display_name and display_name != ufull:
                conn.execute(
                    text("UPDATE company_users SET full_name = :fn WHERE id = :uid"),
                    {"fn": display_name, "uid": user_id},
                )
            if email and email != uemail:
                conn.execute(
                    text("UPDATE company_users SET email = :em WHERE id = :uid"),
                    {"em": email, "uid": user_id},
                )
            # Optionally update role if mapping provides one and user isn't admin
            if role_name and urole not in ("admin", "system_admin", "superuser"):
                conn.execute(
                    text("UPDATE company_users SET role = :role WHERE id = :uid"),
                    {"role": role_name, "uid": user_id},
                )
                urole = role_name
            conn.commit()
            return {
                "id": user_id,
                "username": uname,
                "email": email or uemail,
                "full_name": display_name or ufull,
                "role": urole,
                "permissions": uperms,
                "is_active": uactive,
            }

        # New user — provision
        # Generate a random unusable password (SSO users don't use local passwords)
        import secrets
        random_pw = hash_password(secrets.token_urlsafe(32))
        resolved_role = role_name or "user"

        row = conn.execute(
            text("""
                INSERT INTO company_users (username, password, email, full_name, role, is_active, permissions)
                VALUES (:username, :password, :email, :full_name, :role, true, :permissions)
                RETURNING id
            """),
            {
                "username": username,
                "password": random_pw,
                "email": email or "",
                "full_name": display_name or username,
                "role": resolved_role,
                "permissions": "[]",
            },
        ).fetchone()
        conn.commit()

        return {
            "id": row[0],
            "username": username,
            "email": email or "",
            "full_name": display_name or username,
            "role": resolved_role,
            "permissions": [],
            "is_active": True,
        }


# ---------------------------------------------------------------------------
# Fallback-admin check
# ---------------------------------------------------------------------------

def is_fallback_admin(sso_config_id: int, user_id: int, company_id: str) -> bool:
    """Return True if user_id is registered as a fallback admin for this SSO config."""
    with db_connection(company_id) as conn:
        row = conn.execute(
            text("""
                SELECT 1 FROM sso_fallback_admins
                WHERE sso_configuration_id = :cfg AND user_id = :uid
                LIMIT 1
            """),
            {"cfg": sso_config_id, "uid": user_id},
        ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# SSO config CRUD (thin wrappers used by the router)
# ---------------------------------------------------------------------------

def get_sso_configs(company_id: str) -> List[Dict[str, Any]]:
    """Return all SSO configurations for the given company."""
    with db_connection(company_id) as conn:
        rows = conn.execute(
            text("SELECT * FROM sso_configurations ORDER BY id")
        ).fetchall()
        columns = [
            "id", "provider_type", "display_name", "metadata_url", "metadata_xml",
            "ldap_host", "ldap_port", "ldap_base_dn", "ldap_bind_dn", "ldap_use_tls",
            "is_active", "created_at", "updated_at", "created_by", "updated_by",
        ]
        return [dict(zip(columns, r)) for r in rows]


def get_sso_config_by_id(config_id: int, company_id: str) -> Optional[Dict[str, Any]]:
    with db_connection(company_id) as conn:
        row = conn.execute(
            text("SELECT * FROM sso_configurations WHERE id = :id"),
            {"id": config_id},
        ).fetchone()
        if not row:
            return None
        columns = [
            "id", "provider_type", "display_name", "metadata_url", "metadata_xml",
            "ldap_host", "ldap_port", "ldap_base_dn", "ldap_bind_dn", "ldap_use_tls",
            "is_active", "created_at", "updated_at", "created_by", "updated_by",
        ]
        return dict(zip(columns, row))


def create_sso_config(data: Dict[str, Any], company_id: str) -> Dict[str, Any]:
    with db_connection(company_id) as conn:
        row = conn.execute(
            text("""
                INSERT INTO sso_configurations
                    (provider_type, display_name, metadata_url, metadata_xml,
                     ldap_host, ldap_port, ldap_base_dn, ldap_bind_dn, ldap_use_tls, is_active)
                VALUES
                    (:provider_type, :display_name, :metadata_url, :metadata_xml,
                     :ldap_host, :ldap_port, :ldap_base_dn, :ldap_bind_dn, :ldap_use_tls, :is_active)
                RETURNING id
            """),
            {
                "provider_type": data["provider_type"],
                "display_name": data["display_name"],
                "metadata_url": data.get("metadata_url"),
                "metadata_xml": data.get("metadata_xml"),
                "ldap_host": data.get("ldap_host"),
                "ldap_port": data.get("ldap_port"),
                "ldap_base_dn": data.get("ldap_base_dn"),
                "ldap_bind_dn": data.get("ldap_bind_dn"),
                "ldap_use_tls": data.get("ldap_use_tls", True),
                "is_active": data.get("is_active", False),
            },
        ).fetchone()
        conn.commit()
        return get_sso_config_by_id(row[0], company_id)


def update_sso_config(config_id: int, data: Dict[str, Any], company_id: str) -> Optional[Dict[str, Any]]:
    # Build dynamic SET clause from non-None fields
    allowed = {
        "display_name", "metadata_url", "metadata_xml",
        "ldap_host", "ldap_port", "ldap_base_dn", "ldap_bind_dn", "ldap_use_tls", "is_active",
    }
    updates = {k: v for k, v in data.items() if k in allowed and v is not None}
    if not updates:
        return get_sso_config_by_id(config_id, company_id)

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["id"] = config_id

    with db_connection(company_id) as conn:
        conn.execute(text(f"UPDATE sso_configurations SET {set_clause} WHERE id = :id"), updates)
        conn.commit()
    return get_sso_config_by_id(config_id, company_id)


def deactivate_sso_config(config_id: int, company_id: str) -> bool:
    with db_connection(company_id) as conn:
        result = conn.execute(
            text("UPDATE sso_configurations SET is_active = false WHERE id = :id"),
            {"id": config_id},
        )
        conn.commit()
        return result.rowcount > 0


# ---------------------------------------------------------------------------
# Group-role mapping CRUD
# ---------------------------------------------------------------------------

def get_group_role_mappings(company_id: str, sso_config_id: Optional[int] = None) -> List[Dict[str, Any]]:
    with db_connection(company_id) as conn:
        query = "SELECT id, sso_configuration_id, external_group_name, aman_role_id, created_at FROM sso_group_role_mappings"
        params: Dict[str, Any] = {}
        if sso_config_id:
            query += " WHERE sso_configuration_id = :cfg_id"
            params["cfg_id"] = sso_config_id
        query += " ORDER BY id"
        rows = conn.execute(text(query), params).fetchall()
        return [
            {"id": r[0], "sso_configuration_id": r[1], "external_group_name": r[2], "aman_role_id": r[3], "created_at": r[4]}
            for r in rows
        ]


def create_group_role_mapping(data: Dict[str, Any], company_id: str) -> Dict[str, Any]:
    with db_connection(company_id) as conn:
        row = conn.execute(
            text("""
                INSERT INTO sso_group_role_mappings (sso_configuration_id, external_group_name, aman_role_id)
                VALUES (:sso_configuration_id, :external_group_name, :aman_role_id)
                RETURNING id, created_at
            """),
            {
                "sso_configuration_id": data["sso_configuration_id"],
                "external_group_name": data["external_group_name"],
                "aman_role_id": data["aman_role_id"],
            },
        ).fetchone()
        conn.commit()
        return {
            "id": row[0],
            "sso_configuration_id": data["sso_configuration_id"],
            "external_group_name": data["external_group_name"],
            "aman_role_id": data["aman_role_id"],
            "created_at": row[1],
        }


# ---------------------------------------------------------------------------
# Active SSO configs (public — used by Login page)
# ---------------------------------------------------------------------------

def get_active_sso_configs(company_id: str) -> List[Dict[str, Any]]:
    """Return minimal list of active SSO configs for the login page."""
    with db_connection(company_id) as conn:
        rows = conn.execute(
            text("""
                SELECT id, provider_type, display_name
                FROM sso_configurations
                WHERE is_active = true
                ORDER BY id
            """),
        ).fetchall()
        return [{"id": r[0], "provider_type": r[1], "display_name": r[2]} for r in rows]
