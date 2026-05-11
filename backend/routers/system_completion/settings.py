"""system_completion sub-router — split from monolithic system_completion.py (T6.3).

Mounted under the parent router via system_completion/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime, date
from pydantic import BaseModel
from decimal import Decimal, ROUND_HALF_UP
import io
import csv
import json
import logging
import subprocess
import os
from database import get_db_connection, engine as system_engine
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import require_permission, validate_branch_access
from utils.audit import log_activity
from utils.accounting import get_mapped_account_id, get_base_currency
from utils.fiscal_lock import create_fiscal_lock_table, check_fiscal_period_open
from utils.duplicate_detection import find_duplicate_parties, find_duplicate_products
from services.gl_service import create_journal_entry

logger = logging.getLogger(__name__)

def _u(current_user, key, default=None):
    if isinstance(current_user, dict):
        return current_user.get(key, default)
    return getattr(current_user, key, default)

router = APIRouter()

from .core import PrintTemplateCreate

@router.get("/settings/print-templates", dependencies=[Depends(require_permission("settings.view"))],
            tags=["Print Templates"], response_model=List[Dict[str, Any]])
def list_print_templates(template_type: Optional[str] = None,
                         current_user: dict = Depends(get_current_user)):
    """List Print Templates."""
    company_id = _u(current_user, "company_id")
    with transactional(company_id) as db:
        try:
            query = "SELECT * FROM print_templates WHERE 1=1"
            params = {}
            if template_type:
                query += " AND template_type = :tt"
                params["tt"] = template_type
            query += " ORDER BY is_default DESC, template_type, name"
    
            rows = db.execute(text(query), params).fetchall()
            return [dict(r._mapping) for r in rows]
        except Exception:
            return []


@router.post("/settings/print-templates", dependencies=[Depends(require_permission("settings.manage"))],
             tags=["Print Templates"], response_model=Dict[str, Any])
def create_print_template(body: PrintTemplateCreate, current_user: dict = Depends(get_current_user)):
    """Create Print Template."""
    company_id = _u(current_user, "company_id")
    user_id = _u(current_user, "user_id")
    with transactional(company_id) as db:
        try:
            # If default, unset other defaults of same type
            if body.is_default:
                db.execute(text("""
                    UPDATE print_templates SET is_default = false
                    WHERE template_type = :tt
                """), {"tt": body.template_type})
    
            result = db.execute(text("""
                INSERT INTO print_templates (
                    template_type, name, html_template, css_styles,
                    header_html, footer_html, is_default,
                    paper_size, orientation, created_by
                ) VALUES (:tt, :name, :html, :css, :header, :footer, :default,
                          :paper, :orient, :uid)
                RETURNING id
            """), {
                "tt": body.template_type, "name": body.name,
                "html": body.html_template, "css": body.css_styles,
                "header": body.header_html, "footer": body.footer_html,
                "default": body.is_default, "paper": body.paper_size,
                "orient": body.orientation, "uid": user_id
            })
            tmpl_id = result.fetchone()[0]
    
            return {"id": tmpl_id, "message": i18n_message("print_template_created", request)}
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.get("/settings/print-templates/{template_id}",
            dependencies=[Depends(require_permission("settings.view"))], tags=["Print Templates"], response_model=Dict[str, Any])
def get_print_template(template_id: int, current_user: dict = Depends(get_current_user)):
    """Get Print Template."""
    company_id = _u(current_user, "company_id")
    with transactional(company_id) as db:
        row = db.execute(text("SELECT * FROM print_templates WHERE id = :id"), {"id": template_id}).fetchone()
        if not row:
            raise HTTPException(**http_error(404, "template_not_found"))
        return dict(row._mapping)


@router.put("/settings/print-templates/{template_id}",
            dependencies=[Depends(require_permission("settings.manage"))], tags=["Print Templates"], response_model=Dict[str, Any])
def update_print_template(template_id: int, body: PrintTemplateCreate,
                          current_user: dict = Depends(get_current_user)):
    """Update Print Template."""
    company_id = _u(current_user, "company_id")
    with transactional(company_id) as db:
        if body.is_default:
            db.execute(text("""
                UPDATE print_templates SET is_default = false
                WHERE template_type = :tt AND id != :id
            """), {"tt": body.template_type, "id": template_id})

        db.execute(text("""
            UPDATE print_templates SET
                name = :name, html_template = :html, css_styles = :css,
                header_html = :header, footer_html = :footer,
                is_default = :default, paper_size = :paper,
                orientation = :orient, updated_at = CURRENT_TIMESTAMP
            WHERE id = :id
        """), {
            "name": body.name, "html": body.html_template,
            "css": body.css_styles, "header": body.header_html,
            "footer": body.footer_html, "default": body.is_default,
            "paper": body.paper_size, "orient": body.orientation,
            "id": template_id
        })

        return {"message": i18n_message("template_updated_msg", request)}
