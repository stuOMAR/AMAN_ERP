"""
AMAN ERP — Admin Credentials Router
Admin integration-credential management endpoints.

Sensitive: admin.credentials, critical=True
Contract: specs/022-audit-security-finance-integrity/contracts/http-endpoints.md
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from database import get_db_connection
from routers.auth import get_current_user
from services.permissions.sensitive import require_sensitive_permission
from utils.audit import log_activity
from utils.tx import transactional

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/credentials", tags=["Admin Credentials"])


# ── Schemas ────────────────────────────────────────────────────────────────────


class CredentialCreate(BaseModel):
    integration: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    secret: str = Field(..., min_length=1)
    metadata: Optional[dict] = None
    expires_at: Optional[datetime] = None


class CredentialRotate(BaseModel):
    new_secret: str = Field(..., min_length=1)
    grace_seconds: int = Field(300, ge=0)


class CredentialResponse(BaseModel):
    id: int
    integration: str
    name: str
    status: str
    metadata: Optional[dict] = None
    expires_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=List[Dict[str, Any]],
    dependencies=[Depends(require_sensitive_permission("admin.credentials", critical=True))],
)
def list_credentials(
    include_deleted: bool = False,
    current_user: dict = Depends(get_current_user),
):
    """List integration credentials (secrets never returned)."""
    conn = get_db_connection(current_user["company_id"])
    try:
        query = """
            SELECT id, integration, name, status, metadata, expires_at, created_at, updated_at
              FROM integration_credentials
             WHERE tenant_id = :tnt
        """
        params: dict = {"tnt": current_user.get("tenant_id") or current_user.get("company_id")}
        if not include_deleted:
            query += " AND status != 'soft_deleted'"
        query += " ORDER BY id DESC"
        rows = conn.execute(text(query), params).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        conn.close()


@router.post(
    "",
    response_model=Dict[str, Any],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_sensitive_permission("admin.credentials", critical=True))],
)
def create_credential(
    payload: CredentialCreate,
    current_user: dict = Depends(get_current_user),
):
    """Create a new integration credential."""
    conn = get_db_connection(current_user["company_id"])
    try:
        # Duplicate name guard
        existing = conn.execute(
            text("""
                SELECT 1 FROM integration_credentials
                 WHERE tenant_id = :tnt AND name = :name AND status != 'soft_deleted'
            """),
            {"tnt": current_user.get("tenant_id") or current_user.get("company_id"), "name": payload.name},
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="duplicate_name")

        import json as _json

        metadata_json = _json.dumps(payload.metadata) if payload.metadata else "{}"

        # Encrypt secret via vault
        try:
            from services.credentials_vault import create_credential as vault_create

            result = vault_create(
                tenant_id=int(current_user.get("tenant_id") or current_user.get("company_id", 0)),
                integration=payload.integration,
                name=payload.name,
                secret=payload.secret,
                metadata=payload.metadata,
                expires_at=payload.expires_at,
                actor_id=current_user.get("id"),
            )
            return {
                "id": result.id if hasattr(result, "id") else result,
                "integration": payload.integration,
                "name": payload.name,
                "status": "active",
            }
        except ImportError:
            # Fallback: direct insert (no encryption — dev only)
            row = conn.execute(
                text("""
                    INSERT INTO integration_credentials
                        (tenant_id, integration, name, secret_hash, status, metadata, expires_at, created_at, updated_at)
                    VALUES (:tnt, :integ, :name, :secret, 'active',
                            CAST(:meta AS JSONB), :exp, now(), now())
                    RETURNING id
                """),
                {
                    "tnt": current_user.get("tenant_id") or current_user.get("company_id"),
                    "integ": payload.integration,
                    "name": payload.name,
                    "secret": payload.secret,  # NOTE: should be hashed in production
                    "meta": metadata_json,
                    "exp": payload.expires_at,
                },
            ).fetchone()

            cred_id = row[0]
            log_activity(
                conn,
                action="credential.create",
                entity_type="integration_credential",
                entity_id=cred_id,
                actor_id=current_user.get("id"),
                details={"integration": payload.integration, "name": payload.name},
                critical=True,
            )
            conn.commit()

            return {
                "id": cred_id,
                "integration": payload.integration,
                "name": payload.name,
                "status": "active",
            }
    except HTTPException:
        raise
    finally:
        conn.close()


@router.get(
    "/{credential_id}",
    response_model=Dict[str, Any],
    dependencies=[Depends(require_sensitive_permission("admin.credentials", critical=True))],
)
def get_credential(
    credential_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Get credential detail (no secret)."""
    conn = get_db_connection(current_user["company_id"])
    try:
        row = conn.execute(
            text("""
                SELECT id, integration, name, status, metadata, expires_at, created_at, updated_at
                  FROM integration_credentials
                 WHERE id = :cid
                   AND tenant_id = :tnt
                   AND status != 'soft_deleted'
            """),
            {"cid": credential_id, "tnt": current_user.get("tenant_id") or current_user.get("company_id")},
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="not_found")
        return dict(row._mapping)
    finally:
        conn.close()


@router.post(
    "/{credential_id}/rotate",
    response_model=Dict[str, Any],
    dependencies=[Depends(require_sensitive_permission("admin.credentials", critical=True))],
)
def rotate_credential(
    credential_id: int,
    payload: CredentialRotate,
    current_user: dict = Depends(get_current_user),
):
    """Rotate a credential's secret."""
    conn = get_db_connection(current_user["company_id"])
    try:
        row = conn.execute(
            text("SELECT 1 FROM integration_credentials WHERE id = :cid AND tenant_id = :tnt"),
            {"cid": credential_id, "tnt": current_user.get("tenant_id") or current_user.get("company_id")},
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="not_found")

        try:
            from services.credentials_vault import rotate_credential as vault_rotate

            result = vault_rotate(
                tenant_id=int(current_user.get("tenant_id") or current_user.get("company_id", 0)),
                credential_id=credential_id,
                new_secret=payload.new_secret,
                grace_seconds=payload.grace_seconds,
                actor_id=current_user.get("id"),
            )
            return {
                "id": credential_id,
                "status": "rotating",
                "grace_seconds": payload.grace_seconds,
            }
        except ImportError:
            conn.execute(
                text("""
                    UPDATE integration_credentials
                       SET secret_hash = :secret, status = 'rotating', updated_at = now()
                     WHERE id = :cid
                """),
                {"secret": payload.new_secret, "cid": credential_id},
            )
            log_activity(
                conn,
                action="credential.rotate",
                entity_type="integration_credential",
                entity_id=credential_id,
                actor_id=current_user.get("id"),
                details={"grace_seconds": payload.grace_seconds},
                critical=True,
            )
            conn.commit()
            return {"id": credential_id, "status": "rotating", "grace_seconds": payload.grace_seconds}
    except HTTPException:
        raise
    finally:
        conn.close()


@router.post(
    "/{credential_id}/soft-delete",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_sensitive_permission("admin.credentials", critical=True))],
)
def soft_delete_credential(
    credential_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Soft-delete a credential."""
    conn = get_db_connection(current_user["company_id"])
    try:
        row = conn.execute(
            text("SELECT 1 FROM integration_credentials WHERE id = :cid AND tenant_id = :tnt"),
            {"cid": credential_id, "tnt": current_user.get("tenant_id") or current_user.get("company_id")},
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="not_found")

        conn.execute(
            text("""
                UPDATE integration_credentials
                   SET status = 'soft_deleted', updated_at = now()
                 WHERE id = :cid
            """),
            {"cid": credential_id},
        )
        log_activity(
            conn,
            action="credential.soft_delete",
            entity_type="integration_credential",
            entity_id=credential_id,
            actor_id=current_user.get("id"),
            details=None,
            critical=True,
        )
        conn.commit()
    except HTTPException:
        raise
    finally:
        conn.close()


@router.post(
    "/{credential_id}/restore",
    response_model=Dict[str, Any],
    dependencies=[Depends(require_sensitive_permission("admin.credentials", critical=True))],
)
def restore_credential(
    credential_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Restore a soft-deleted credential."""
    conn = get_db_connection(current_user["company_id"])
    try:
        row = conn.execute(
            text("""
                SELECT id, status FROM integration_credentials
                 WHERE id = :cid AND tenant_id = :tnt
            """),
            {"cid": credential_id, "tnt": current_user.get("tenant_id") or current_user.get("company_id")},
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="not_found")
        if dict(row._mapping).get("status") != "soft_deleted":
            raise HTTPException(status_code=400, detail="Credential is not soft-deleted")

        conn.execute(
            text("""
                UPDATE integration_credentials
                   SET status = 'active', updated_at = now()
                 WHERE id = :cid
            """),
            {"cid": credential_id},
        )
        log_activity(
            conn,
            action="credential.restore",
            entity_type="integration_credential",
            entity_id=credential_id,
            actor_id=current_user.get("id"),
            details=None,
            critical=True,
        )
        conn.commit()
        return {"id": credential_id, "status": "active"}
    except HTTPException:
        raise
    finally:
        conn.close()
