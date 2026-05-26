"""Email templates admin endpoints.

GET    /notifications/templates       — list templates
POST   /notifications/templates       — create template
PUT    /notifications/templates/{id}  — update template
DELETE /notifications/templates/{id}  — delete template
"""
from __future__ import annotations

from fastapi import Request, APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from database import get_db_connection
from services.permissions.sensitive import require_sensitive_permission
from utils.i18n import http_error, i18n_message

router = APIRouter(prefix="/templates", tags=["Email Templates"])


class TemplateCreate(BaseModel):
    code: str
    locale: str = "en"
    subject: Optional[str] = None
    body_html: Optional[str] = None
    body_text: Optional[str] = None


def _get_tenant_id(current_user) -> str:
    return str(
        current_user.get("company_id")
        if isinstance(current_user, dict)
        else getattr(current_user, "company_id", 0)
    )


@router.get("")
def list_templates(
    limit: int = Query(25, ge=1, le=100),
    current_user=Depends(require_sensitive_permission("email_templates.admin")),
):
    """List all email templates."""
    tenant_id = _get_tenant_id(current_user)
    conn = get_db_connection(tenant_id)
    try:
        from sqlalchemy import text
        rows = conn.execute(
            text("""
                SELECT id,
                       COALESCE(code, template_name) AS code,
                       COALESCE(locale, 'en') AS locale,
                       subject,
                       COALESCE(version, 1) AS version,
                       created_at
                FROM email_templates
                WHERE tenant_id = :tnt
                ORDER BY COALESCE(code, template_name), COALESCE(locale, 'en')
                LIMIT :limit
            """),
            {"tnt": str(tenant_id), "limit": limit},
        ).fetchall()

        return [
            {
                "id": r[0], "code": r[1], "locale": r[2],
                "subject": r[3], "version": r[4],
                "created_at": r[5].isoformat() if r[5] else None,
            }
            for r in rows
        ]
    finally:
        conn.close()


@router.post("")
def create_template(
    request: Request,
    body: TemplateCreate,
    current_user=Depends(require_sensitive_permission("email_templates.admin")),
):
    """Create an email template."""
    tenant_id = _get_tenant_id(current_user)
    conn = get_db_connection(tenant_id)
    try:
        from sqlalchemy import text
        row = conn.execute(
            text("""
                INSERT INTO email_templates
                    (tenant_id, template_name, code, locale, subject, body, body_html, body_text, version)
                VALUES (:tnt, :code, :code, :locale, :subject, COALESCE(:text, :html), :html, :text, 1)
                RETURNING id
            """),
            {
                "tnt": str(tenant_id), "code": body.code, "locale": body.locale,
                "subject": body.subject, "html": body.body_html, "text": body.body_text,
            },
        ).fetchone()
        conn.commit()
        return {"id": row[0], "code": body.code, "locale": body.locale}
    except Exception:
        raise HTTPException(status_code=400, detail=i18n_message("internal_error", request) if request else "Internal error")
    finally:
        conn.close()


@router.put("/{template_id}")
def update_template(request: Request, 
    template_id: int,
    body: TemplateCreate,
    current_user=Depends(require_sensitive_permission("email_templates.admin")),
):
    """Update an email template."""
    tenant_id = _get_tenant_id(current_user)
    conn = get_db_connection(tenant_id)
    try:
        from sqlalchemy import text
        result = conn.execute(
            text("""
                UPDATE email_templates
                SET template_name = :code,
                    code = :code,
                    locale = :locale,
                    subject = :subject,
                    body = COALESCE(:text, :html),
                    body_html = :html,
                    body_text = :text,
                    version = version + 1, updated_at = now()
                WHERE id = :tid AND tenant_id = :tnt
            """),
            {
                "tid": template_id, "tnt": str(tenant_id),
                "code": body.code, "locale": body.locale,
                "subject": body.subject, "html": body.body_html, "text": body.body_text,
            },
        )
        if result.rowcount == 0:
            raise HTTPException(**http_error(404, "template_not_found", request))
        conn.commit()
        return {"updated": True, "id": template_id}
    finally:
        conn.close()


@router.delete("/{template_id}")
def delete_template(request: Request, 
    template_id: int,
    current_user=Depends(require_sensitive_permission("email_templates.admin")),
):
    """Delete an email template."""
    tenant_id = _get_tenant_id(current_user)
    conn = get_db_connection(tenant_id)
    try:
        from sqlalchemy import text
        result = conn.execute(
            text("""
                DELETE FROM email_templates
                WHERE id = :tid AND tenant_id = :tnt
            """),
            {"tid": template_id, "tnt": str(tenant_id)},
        )
        if result.rowcount == 0:
            raise HTTPException(**http_error(404, "template_not_found", request))
        conn.commit()
        return {"deleted": True, "id": template_id}
    finally:
        conn.close()
