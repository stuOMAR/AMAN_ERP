"""Email Templates CRUD Router — T4.11

Allows administrators to view, create, update, and delete email templates
stored in the ``email_templates`` table so that notification content can be
customised without code changes.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from typing import Any, Dict, List, Optional

from database import get_db_connection
from routers.auth import get_current_user
from utils.permissions import require_permission

router = APIRouter(prefix="/email-templates", tags=["Email Templates"])


class EmailTemplateBase(BaseModel):
    template_name: str
    subject: Optional[str] = None
    body: Optional[str] = None
    variables: Optional[dict] = None
    is_active: bool = True


class EmailTemplateCreate(EmailTemplateBase):
    pass


class EmailTemplateUpdate(BaseModel):
    subject: Optional[str] = None
    body: Optional[str] = None
    variables: Optional[dict] = None
    is_active: Optional[bool] = None


@router.get("", dependencies=[Depends(require_permission(["settings.view", "admin"]))], response_model=List[Dict[str, Any]])
async def list_email_templates(current_user=Depends(get_current_user)):
    """List all email templates."""
    company_id = getattr(current_user, "company_id", None)
    if not company_id:
        return []
    db = get_db_connection(company_id)
    try:
        rows = db.execute(
            text(
                "SELECT id, template_name, subject, variables, is_active, created_at "
                "FROM email_templates ORDER BY template_name"
            )
        ).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


@router.get("/{template_id}", dependencies=[Depends(require_permission(["settings.view", "admin"]))], response_model=Dict[str, Any])
async def get_email_template(template_id: int, current_user=Depends(get_current_user)):
    """Return a single email template including its body."""
    company_id = getattr(current_user, "company_id", None)
    if not company_id:
        raise HTTPException(400, "company_id required")
    db = get_db_connection(company_id)
    try:
        row = db.execute(
            text(
                "SELECT id, template_name, subject, body, variables, is_active, created_at "
                "FROM email_templates WHERE id = :id LIMIT 1"
            ),
            {"id": template_id},
        ).fetchone()
        if not row:
            raise HTTPException(404, "Template not found")
        return dict(row._mapping)
    finally:
        db.close()


@router.post("", dependencies=[Depends(require_permission(["settings.edit", "admin"]))], response_model=Dict[str, Any])
async def create_email_template(data: EmailTemplateCreate, current_user=Depends(get_current_user)):
    """Create a new email template."""
    import json
    company_id = getattr(current_user, "company_id", None)
    if not company_id:
        raise HTTPException(400, "company_id required")
    db = get_db_connection(company_id)
    try:
        existing = db.execute(
            text(
                "SELECT id FROM email_templates WHERE template_name = :name LIMIT 1"
            ),
            {"name": data.template_name},
        ).fetchone()
        if existing:
            raise HTTPException(409, f"Template '{data.template_name}' already exists")
        row = db.execute(
            text(
                "INSERT INTO email_templates (template_name, subject, body, variables, is_active) "
                "VALUES (:name, :subject, :body, :vars::jsonb, :active) RETURNING id"
            ),
            {
                "name": data.template_name,
                "subject": data.subject,
                "body": data.body,
                "vars": json.dumps(data.variables or {}),
                "active": data.is_active,
            },
        ).fetchone()
        db.commit()
        return {"id": row[0], "template_name": data.template_name}
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, f"Error creating template: {exc}") from exc
    finally:
        db.close()


@router.put("/{template_id}", dependencies=[Depends(require_permission(["settings.edit", "admin"]))], response_model=Dict[str, Any])
async def update_email_template(
    template_id: int,
    data: EmailTemplateUpdate,
    current_user=Depends(get_current_user),
):
    """Update an existing email template (partial update)."""
    import json
    company_id = getattr(current_user, "company_id", None)
    if not company_id:
        raise HTTPException(400, "company_id required")
    db = get_db_connection(company_id)
    try:
        existing = db.execute(
            text("SELECT id FROM email_templates WHERE id = :id LIMIT 1"),
            {"id": template_id},
        ).fetchone()
        if not existing:
            raise HTTPException(404, "Template not found")

        # Build partial UPDATE
        fields = []
        params: dict = {"id": template_id}
        if data.subject is not None:
            fields.append("subject = :subject")
            params["subject"] = data.subject
        if data.body is not None:
            fields.append("body = :body")
            params["body"] = data.body
        if data.variables is not None:
            fields.append("variables = :vars::jsonb")
            params["vars"] = json.dumps(data.variables)
        if data.is_active is not None:
            fields.append("is_active = :active")
            params["active"] = data.is_active
        if not fields:
            return {"detail": "Nothing to update"}
        db.execute(
            text(f"UPDATE email_templates SET {', '.join(fields)} WHERE id = :id"),
            params,
        )
        db.commit()
        return {"detail": "Updated"}
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, f"Error updating template: {exc}") from exc
    finally:
        db.close()


@router.delete("/{template_id}", dependencies=[Depends(require_permission(["settings.edit", "admin"]))], response_model=Dict[str, Any])
async def delete_email_template(template_id: int, current_user=Depends(get_current_user)):
    """Soft-delete: deactivate a template rather than removing the row."""
    company_id = getattr(current_user, "company_id", None)
    if not company_id:
        raise HTTPException(400, "company_id required")
    db = get_db_connection(company_id)
    try:
        result = db.execute(
            text(
                "UPDATE email_templates SET is_active = FALSE WHERE id = :id"
            ),
            {"id": template_id},
        )
        db.commit()
        if result.rowcount == 0:
            raise HTTPException(404, "Template not found")
        return {"detail": "Template deactivated"}
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, f"Error deleting template: {exc}") from exc
    finally:
        db.close()
