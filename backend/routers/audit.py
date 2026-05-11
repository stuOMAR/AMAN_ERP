"""
AMAN ERP - Audit Logs Router
API endpoints for viewing audit logs.
"""

from fastapi import Request, APIRouter, Depends, HTTPException
from sqlalchemy import text
from typing import Optional, List, Any
from datetime import datetime, date
from pydantic import BaseModel
import logging

from database import get_db_connection, engine
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import branch_scope_filter_from_scope, require_permission, require_module, resolve_branch_scope
from utils.tenant_isolation import resolve_target_company_id

router = APIRouter(prefix="/audit", tags=["Audit Logs"], dependencies=[Depends(require_module("audit"))])
logger = logging.getLogger(__name__)


class AuditLogResponse(BaseModel):
    id: int
    user_id: int
    username: str
    action: str
    resource_type: Optional[str]
    resource_id: Optional[str]
    details: Optional[dict]
    ip_address: Optional[str]
    created_at: datetime


@router.get("/logs", response_model=List[dict], dependencies=[Depends(require_permission("audit.view"))])
def list_audit_logs(request: Request, 
    skip: int = 0,
    limit: int = 50,
    action: Optional[str] = None,
    username: Optional[str] = None,
    resource_type: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    company_id: Optional[str] = None,
    include_archived: bool = False,
    current_user: Any = Depends(get_current_user)
):
    """عرض سجلات المراقبة مع فلترة"""
    # 1. Determine which DB to connect to
    target_company_id = resolve_target_company_id(company_id, current_user)
    
    # If system admin and no company_id provided, we query the SYSTEM ACTIVITY LOG
    is_system_view = getattr(current_user, 'role', None) == 'system_admin' and not target_company_id

    if is_system_view:
        db = engine.connect()
        try:
            query = """
                SELECT id, company_id, action_type as action, action_description as details_text, 
                       performed_by as username, ip_address, created_at, 'System' as resource_type,
                       NULL as resource_id, NULL as branch_id, NULL as branch_name
                FROM system_activity_log
                WHERE 1=1
            """
            params = {"limit": limit, "skip": skip}
            
            if action:
                query += " AND action_type ILIKE :action"
                params["action"] = f"%{action}%"
            
            if username:
                query += " AND performed_by ILIKE :username"
                params["username"] = f"%{username}%"

            if start_date:
                query += " AND created_at >= :start_date"
                params["start_date"] = start_date
            
            if end_date:
                query += " AND created_at <= :end_date"
                params["end_date"] = end_date

            query += " ORDER BY created_at DESC LIMIT :limit OFFSET :skip"
            result = db.execute(text(query), params).fetchall()
            
            logs = []
            for row in result:
                logs.append({
                    "id": row.id,
                    "user_id": 0,
                    "username": row.username,
                    "action": row.action,
                    "resource_type": "System",
                    "resource_id": row.company_id,
                    "details": {"description": row.details_text, "company_id": row.company_id},
                    "ip_address": row.ip_address,
                    "branch_id": None,
                    "branch_name": "System",
                    "created_at": row.created_at.isoformat() if row.created_at else None
                })
            return logs
        finally:
            db.close()

    if not target_company_id:
        raise HTTPException(**http_error(400, "company_id_missing_and_not_a_system_view", request))

    with transactional(target_company_id) as db:
        query = """
            SELECT al.id, al.user_id, al.username, al.action, al.resource_type, al.resource_id, 
                   al.details, al.ip_address, al.created_at, al.branch_id, b.branch_name
            FROM audit_logs al
            LEFT JOIN branches b ON al.branch_id = b.id
            WHERE 1=1
        """
        params = {"limit": limit, "skip": skip}
        
        # T017: Filter out archived entries by default (skip if column not yet added)
        # if not include_archived:
        #     query += " AND (al.is_archived IS NULL OR al.is_archived = FALSE)"
        
        branch_scope = resolve_branch_scope(current_user, branch_id)
        query += branch_scope_filter_from_scope(branch_scope, "al.branch_id", params)
            
        if action:
            query += " AND action ILIKE :action"
            params["action"] = f"%{action}%"
        
        if username:
            query += " AND username ILIKE :username"
            params["username"] = f"%{username}%"
        
        if resource_type:
            query += " AND resource_type = :resource_type"
            params["resource_type"] = resource_type
        
        if start_date:
            query += " AND created_at >= :start_date"
            params["start_date"] = start_date
        
        if end_date:
            query += " AND created_at <= :end_date"
            params["end_date"] = end_date
        
        query += " ORDER BY created_at DESC LIMIT :limit OFFSET :skip"
        result = db.execute(text(query), params).fetchall()
        
        logs = []
        for row in result:
            logs.append({
                "id": row.id,
                "user_id": row.user_id,
                "username": row.username,
                "action": row.action,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "details": row.details or {},
                "ip_address": row.ip_address,
                "branch_id": row.branch_id,
                "branch_name": row.branch_name,
                "created_at": row.created_at.isoformat() if row.created_at else None
            })
        
        return logs


@router.get("/logs/actions", response_model=List[str], dependencies=[Depends(require_permission("audit.view"))])
def list_available_actions(
    company_id: Optional[str] = None,
    current_user: Any = Depends(get_current_user)
):
    """جلب قائمة الأحداث المتاحة للفلترة"""
    target_company_id = resolve_target_company_id(company_id, current_user)
    
    if getattr(current_user, 'role', None) == 'system_admin' and not target_company_id:
        db = engine.connect()
        try:
            result = db.execute(text("SELECT DISTINCT action_type FROM system_activity_log ORDER BY action_type")).fetchall()
            return [row[0] for row in result]
        finally:
            db.close()

    if not target_company_id:
         return []

    with transactional(target_company_id) as db:
        result = db.execute(text("SELECT DISTINCT action FROM audit_logs ORDER BY action")).fetchall()
        return [row[0] for row in result]


@router.get("/logs/stats", response_model=dict, dependencies=[Depends(require_permission("audit.view"))])
def get_audit_stats(
    branch_id: Optional[int] = None,
    company_id: Optional[str] = None,
    current_user: Any = Depends(get_current_user)
):
    """إحصائيات سجلات المراقبة مع مراعاة الفرع والصلاحيات"""
    target_company_id = resolve_target_company_id(company_id, current_user)
    
    if getattr(current_user, 'role', None) == 'system_admin' and not target_company_id:
        db = engine.connect()
        try:
            where_clause = " WHERE 1=1"
            params = {}
            
            total = db.execute(text(f"SELECT COUNT(*) FROM system_activity_log {where_clause}"), params).scalar() or 0
            today_count = db.execute(text(f"SELECT COUNT(*) FROM system_activity_log {where_clause} AND DATE(created_at) = CURRENT_DATE"), params).scalar() or 0
            
            top_actions = db.execute(text(f"""
                SELECT action_type as action, COUNT(*) as count 
                FROM system_activity_log 
                {where_clause}
                GROUP BY action_type 
                ORDER BY count DESC 
                LIMIT 5
            """), params).fetchall()
            
            top_users = db.execute(text(f"""
                SELECT performed_by as username, COUNT(*) as count 
                FROM system_activity_log 
                {where_clause}
                GROUP BY performed_by 
                ORDER BY count DESC 
                LIMIT 5
            """), params).fetchall()
            
            return {
                "total_logs": total,
                "today_logs": today_count,
                "top_actions": [{"action": r[0], "count": r[1]} for r in top_actions],
                "top_users": [{"username": r[0], "count": r[1]} for r in top_users]
            }
        finally:
            db.close()

    if not target_company_id:
        return {"total_logs": 0, "today_logs": 0, "top_actions": [], "top_users": []}

    with transactional(target_company_id) as db:
        where_clause = " WHERE 1=1"
        params = {}
        branch_scope = resolve_branch_scope(current_user, branch_id)
        where_clause += f" {branch_scope_filter_from_scope(branch_scope, 'branch_id', params)}"

        # Total logs
        total = db.execute(text(f"SELECT COUNT(*) FROM audit_logs {where_clause}"), params).scalar() or 0
        
        # Today's logs
        today_count = db.execute(text(f"""
            SELECT COUNT(*) FROM audit_logs 
            {where_clause} AND DATE(created_at) = CURRENT_DATE
        """), params).scalar() or 0
        
        # Top actions
        top_actions = db.execute(text(f"""
            SELECT action, COUNT(*) as count 
            FROM audit_logs 
            {where_clause}
            GROUP BY action 
            ORDER BY count DESC 
            LIMIT 5
        """), params).fetchall()
        
        # Most active users
        top_users = db.execute(text(f"""
            SELECT username, COUNT(*) as count 
            FROM audit_logs 
            {where_clause}
            GROUP BY username 
            ORDER BY count DESC 
            LIMIT 5
        """), params).fetchall()
        
        return {
            "total_logs": total,
            "today_logs": today_count,
            "top_actions": [{"action": r[0], "count": r[1]} for r in top_actions],
            "top_users": [{"username": r[0], "count": r[1]} for r in top_users]
        }
