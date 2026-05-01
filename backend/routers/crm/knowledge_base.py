"""crm sub-router — split from monolithic crm.py (T6.3).

Mounted under the parent router via crm/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel
import logging
from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import require_permission, require_module, validate_branch_access
from utils.accounting import generate_sequential_number
from utils.audit import log_activity
from utils.sql_builder import validate_update_keys
from services.notification_service import notification_service
from schemas.campaign import CampaignCreate, TrackingWebhookPayload

logger = logging.getLogger(__name__)

router = APIRouter()

from .core import ArticleCreate, ArticleUpdate

@router.get("/knowledge-base", dependencies=[Depends(require_permission("sales.view"))], response_model=List[Dict[str, Any]])
def list_articles(
    category: Optional[str] = None,
    search: Optional[str] = None,
    current_user=Depends(get_current_user)
):
    """List Articles."""
    db = get_db_connection(current_user.company_id)
    try:
        conditions = ["1=1"]
        params = {}
        if category:
            conditions.append("category = :cat")
            params["cat"] = category
        if search:
            conditions.append("(title ILIKE :q OR content ILIKE :q OR tags ILIKE :q)")
            params["q"] = f"%{search}%"

        rows = db.execute(text(f"""
            SELECT kb.*, u.full_name as author_name
            FROM crm_knowledge_base kb
            LEFT JOIN company_users u ON kb.created_by = u.id
            WHERE {' AND '.join(conditions)}
            ORDER BY kb.created_at DESC
        """), params).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


@router.get("/knowledge-base/{article_id}", dependencies=[Depends(require_permission("sales.view"))], response_model=Dict[str, Any])
def get_article(article_id: int, current_user=Depends(get_current_user)):
    """Get Article."""
    db = get_db_connection(current_user.company_id)
    try:
        # increment view count
        db.execute(text("UPDATE crm_knowledge_base SET views = COALESCE(views, 0) + 1 WHERE id = :id"), {"id": article_id})
        db.commit()
        row = db.execute(text("""
            SELECT kb.*, u.full_name as author_name
            FROM crm_knowledge_base kb LEFT JOIN company_users u ON kb.created_by = u.id
            WHERE kb.id = :id
        """), {"id": article_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="المقالة غير موجودة")
        return dict(row._mapping)
    finally:
        db.close()


@router.post("/knowledge-base", status_code=201, dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def create_article(data: ArticleCreate, request: Request, current_user=Depends(get_current_user)):
    """Create Article."""
    db = get_db_connection(current_user.company_id)
    try:
        aid = db.execute(text("""
            INSERT INTO crm_knowledge_base (title, category, content, tags, is_published, created_by)
            VALUES (:title, :cat, :content, :tags, :pub, :uid) RETURNING id
        """), {
            "title": data.title, "cat": data.category, "content": data.content,
            "tags": data.tags, "pub": data.is_published, "uid": current_user.id
        }).scalar()
        db.commit()
        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_create_article", resource_type="knowledge_article", resource_id=str(aid), details={"title": data.title, "category": data.category}, request=request)
        return {"id": aid, "message": "تم إنشاء المقالة"}
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating article: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.put("/knowledge-base/{article_id}", dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def update_article(article_id: int, data: ArticleUpdate, request: Request, current_user=Depends(get_current_user)):
    """Update Article."""
    db = get_db_connection(current_user.company_id)
    try:
        updates = {k: v for k, v in data.dict(exclude_unset=True).items() if v is not None}
        if not updates:
            raise HTTPException(**http_error(400, "no_data_to_update"))
        updates["id"] = article_id
        validate_update_keys(k for k in updates if k != "id")  # T2.2 defense-in-depth
        set_clause = ", ".join(f"{k} = :{k}" for k in updates if k != "id")
        db.execute(text(f"UPDATE crm_knowledge_base SET {set_clause}, updated_at = NOW() WHERE id = :id"), updates)
        db.commit()
        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_update_article", resource_type="knowledge_article", resource_id=str(article_id), details={"fields_updated": list(updates.keys())}, request=request)
        return {"message": "تم تحديث المقالة"}
    finally:
        db.close()


@router.delete("/knowledge-base/{article_id}", dependencies=[Depends(require_permission("sales.create"))], response_model=Dict[str, Any])
def delete_article(article_id: int, request: Request, current_user=Depends(get_current_user)):
    """Delete Article."""
    db = get_db_connection(current_user.company_id)
    try:
        db.execute(text("DELETE FROM crm_knowledge_base WHERE id = :id"), {"id": article_id})
        db.commit()
        log_activity(db, user_id=current_user.id, username=getattr(current_user, "username", ""), action="crm_delete_article", resource_type="knowledge_article", resource_id=str(article_id), details={}, request=request)
        return {"message": "تم حذف المقالة"}
    finally:
        db.close()


# ======================== CRM-006: Lead Scoring ========================

