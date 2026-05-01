"""Reports sub-router — split from monolithic reports.py (T6.3).

Mounted under the parent /reports prefix via reports/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from utils.i18n import http_error
from sqlalchemy import text
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import require_permission, validate_branch_access
from utils.cache import cached
from services.sales_service import get_sales_total, get_gl_profit_breakdown

logger = logging.getLogger(__name__)
router = APIRouter()

class CustomReportConfig(BaseModel):
    source: Optional[str] = None  # 'sales', 'purchases', 'inventory', 'projects'
    table_name: Optional[str] = None  # alias for source (frontend compatibility)
    columns: List[str]
    filters: Optional[Dict[str, Any]] = {}
    sort_by: Optional[str] = None
    sort_order: Optional[str] = "desc"

    model_config = {"extra": "ignore"}

    @property
    def resolved_source(self) -> str:
        """Return source, falling back to table_name"""
        return self.source or self.table_name or "sales"

class CustomReportCreate(BaseModel):
    report_name: str
    description: Optional[str] = None
    config: CustomReportConfig

@router.post("/custom/preview", dependencies=[Depends(require_permission("reports.view"))], response_model=Dict[str, Any])
async def preview_custom_report(
    config: CustomReportConfig,
    current_user: dict = Depends(get_current_user)
):
    """معاينة تقرير مخصص بناءً على التكوين"""
    db = get_db_connection(current_user.company_id)
    try:
        data = _generate_custom_report_data(db, config, current_user.id)
        return data
    except Exception as e:
        logger.error(f"Error previewing report: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()

@router.post("/custom", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("reports.create"))], response_model=Dict[str, Any])
async def create_custom_report(
    report: CustomReportCreate,
    current_user: dict = Depends(get_current_user)
):
    """حفظ تقرير مخصص"""
    db = get_db_connection(current_user.company_id)
    try:
        report_id = db.execute(text("""
            INSERT INTO custom_reports (
                report_name, description, config, created_by
            ) VALUES (:name, :desc, :config, :uid)
            RETURNING id
        """), {
            "name": report.report_name,
            "desc": report.description,
            "config": report.config.json(),
            "uid": current_user.id
        }).scalar()
        
        db.commit()
        return {"success": True, "id": report_id, "message": "تم حفظ التقرير بنجاح"}
    except Exception as e:
        db.rollback()
        logger.error(f"Error saving report: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()

@router.get("/custom", dependencies=[Depends(require_permission("reports.view"))], response_model=List[Dict[str, Any]])
async def list_custom_reports(current_user: dict = Depends(get_current_user)):
    """جلب قائمة التقارير المخصصة المحفوظة"""
    db = get_db_connection(current_user.company_id)
    try:
        reports = db.execute(text("""
            SELECT cr.*, u.full_name as created_by_name
            FROM custom_reports cr
            LEFT JOIN company_users u ON cr.created_by = u.id
            ORDER BY cr.created_at DESC
        """)).fetchall()
        return [dict(r._mapping) for r in reports]
    finally:
        db.close()

@router.get("/custom/{report_id}", dependencies=[Depends(require_permission("reports.view"))], response_model=Dict[str, Any])
async def get_custom_report(report_id: int, current_user: dict = Depends(get_current_user)):
    """تشغيل تقرير مخصص محفوظ"""
    db = get_db_connection(current_user.company_id)
    try:
        report = db.execute(text("SELECT * FROM custom_reports WHERE id = :id"), {"id": report_id}).fetchone()
        if not report:
            raise HTTPException(status_code=404, detail="التقرير غير موجود")
            
        config_dict = report.config if isinstance(report.config, dict) else json.loads(report.config)
        config = CustomReportConfig(**config_dict)
        
        data = _generate_custom_report_data(db, config, current_user.id)
        return {"report": dict(report._mapping), "results": data}
    except Exception as e:
        logger.error(f"Error executing saved report: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()

@router.delete("/custom/{report_id}", dependencies=[Depends(require_permission("reports.delete"))], response_model=Dict[str, Any])
async def delete_custom_report(report_id: int, current_user: dict = Depends(get_current_user)):
    """حذف تقرير مخصص"""
    db = get_db_connection(current_user.company_id)
    try:
        db.execute(text("DELETE FROM custom_reports WHERE id = :id"), {"id": report_id})
        db.commit()
        return {"success": True, "message": "تم حذف التقرير"}
    finally:
        db.close()

def _generate_custom_report_data(db, config: CustomReportConfig, user_id: int):
    """Engine to build dynamic SQL based on config"""
    
    # 1. Source Mapping
    source_map = {
        "sales": {
            "table": "invoices",
            "alias": "i",
            "joins": "LEFT JOIN parties p ON i.party_id = p.id",
            "where": "i.invoice_type = 'sales' AND i.status != 'cancelled'",
            "columns": {
                "invoice_number": "i.invoice_number",
                "date": "i.invoice_date",
                "customer": "p.name",
                "total": "i.total",
                "paid": "i.paid_amount",
                "status": "i.status",
                "branch_id": "i.branch_id"
            }
        },
        "purchases": {
            "table": "invoices",
            "alias": "i",
            "joins": "LEFT JOIN parties p ON i.party_id = p.id",
            "where": "i.invoice_type = 'purchase' AND i.status != 'cancelled'",
            "columns": {
                "invoice_number": "i.invoice_number",
                "date": "i.invoice_date",
                "supplier": "p.name",
                "total": "i.total",
                "paid": "i.paid_amount",
                "status": "i.status"
            }
        },
        "inventory": {
            "table": "products",
            "alias": "p",
            "joins": "LEFT JOIN inventory inv ON p.id = inv.product_id LEFT JOIN warehouses w ON inv.warehouse_id = w.id",
            "where": "1=1",
            "columns": {
                "sku": "p.sku",
                "product_name": "p.product_name",
                "warehouse": "w.warehouse_name",
                "quantity": "inv.quantity",
                "cost_price": "p.cost_price",
                "selling_price": "p.selling_price"
            }
        },
         "projects": {
            "table": "projects",
            "alias": "p",
            "joins": "LEFT JOIN customers c ON p.customer_id = c.id LEFT JOIN employees e ON p.manager_id = e.id",
            "where": "1=1",
            "columns": {
                "id": "p.id",
                "code": "p.project_code",
                "project_name": "p.project_name",
                "customer": "c.customer_name",
                "manager": "CONCAT(e.first_name, ' ', e.last_name)",
                "manager_id": "p.manager_id",
                "status": "p.status",
                "progress": "p.progress_percentage",
                "start_date": "p.start_date",
                "end_date": "p.end_date",
                "budget": "p.budget"
            }
        },
        "tasks": {
            "table": "tasks",
            "alias": "t",
            "joins": "LEFT JOIN projects p ON t.project_id = p.id",
            "where": "1=1",
            "columns": {
                "id": "t.id",
                "task_name": "t.task_name",
                "project_id": "t.project_id",
                "status": "t.status",
                "start_date": "t.start_date",
                "end_date": "t.end_date",
                "planned_hours": "t.planned_hours",
                "actual_hours": "t.actual_hours"
            }
        },
        "sales_invoices": {
            "table": "invoices",
            "alias": "i",
            "joins": "LEFT JOIN parties p ON i.party_id = p.id",
            "where": "i.invoice_type = 'sales' AND i.status != 'cancelled'",
            "columns": {
                "id": "i.id",
                "invoice_number": "i.invoice_number",
                "invoice_date": "i.invoice_date",
                "date": "i.invoice_date",
                "customer_id": "i.party_id",
                "customer": "p.name",
                "total_amount": "i.total",
                "total": "i.total",
                "status": "i.status"
            }
        },
        "expenses": {
            "table": "expenses",
            "alias": "ex",
            "joins": "",
            "where": "1=1",
            "columns": {
                "id": "ex.id",
                "expense_date": "ex.expense_date",
                "amount": "ex.amount",
                "category": "ex.category",
                "description": "ex.description",
                "project_id": "ex.project_id"
            }
        },
        "customers": {
            "table": "parties",
            "alias": "p",
            "joins": "",
            "where": "p.party_type = 'customer'",
            "columns": {
                "id": "p.id",
                "name": "p.name",
                "email": "p.email",
                "phone": "p.phone",
                "city": "p.city"
            }
        }
    }
    
    src = source_map.get(config.resolved_source)
    if not src:
        raise ValueError(f"Invalid Data Source: {config.resolved_source}")
        
    # 2. Build Query
    select_cols = []
    for col in config.columns:
        if col in src["columns"]:
            select_cols.append(f"{src['columns'][col]} as {col}")
    
    if not select_cols:
        select_cols = ["*"] # Fallback
        
    query = f"SELECT {', '.join(select_cols)} FROM {src['table']} {src['alias']} {src['joins']} WHERE {src['where']}"
    
    # 3. Apply Filters
    params = {}
    if config.filters:
        for key, value in config.filters.items():
            if key in src["columns"] and value:
                valid_key = key.replace(" ", "_") # Safety
                query += f" AND {src['columns'][key]} = :{valid_key}"
                params[valid_key] = value
                
            # Date Range special handling
            if key == "date_from" and "date" in src["columns"]:
                 query += f" AND {src['columns']['date']} >= :date_from"
                 params["date_from"] = value
            if key == "date_to" and "date" in src["columns"]:
                 query += f" AND {src['columns']['date']} <= :date_to"
                 params["date_to"] = value

    # 4. Sorting
    if config.sort_by and config.sort_by in src["columns"]:
        order = "DESC" if config.sort_order == "desc" else "ASC"
        query += f" ORDER BY {src['columns'][config.sort_by]} {order}"
    
    # Execute
    result = db.execute(text(query), params).fetchall()
    return [dict(r._mapping) for r in result]


# ═══════════════════════════════════════════════════════════
# RPT-103: Detailed P&L by Product/Customer/Category
# تقرير أرباح وخسائر تفصيلي
# ═══════════════════════════════════════════════════════════

