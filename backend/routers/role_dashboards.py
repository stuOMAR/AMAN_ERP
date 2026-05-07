"""
AMAN ERP - Role-Based KPI Dashboards Router
لوحات تحكم وظيفية بمؤشرات أداء حسب الدور والقطاع

10 Role Endpoints + 1 Industry Endpoint + 1 Auto-Route Endpoint
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Dict, Any, Optional
from datetime import date
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.permissions import require_permission, resolve_branch_scope
from utils.cache import cached
from utils.currency_display import convert_dashboard_payload_to_display, resolve_display_currency
from services.kpi_service import (
    resolve_period, get_executive_kpis, get_financial_kpis,
    get_sales_kpis, get_procurement_kpis, get_warehouse_kpis,
    get_hr_kpis, get_manufacturing_kpis, get_projects_kpis,
    get_pos_kpis, get_crm_kpis
)
from services.industry_kpi_service import get_industry_kpis

router = APIRouter(prefix="/dashboard/role", tags=["Role Dashboards"])
logger = logging.getLogger(__name__)


def _get_company_id(user):
    cid = getattr(user, "company_id", None)
    if cid is None and isinstance(user, dict):
        cid = user.get("company_id")
    if not cid:
        raise HTTPException(status_code=400, detail="Company ID missing")
    return cid


def _get_user_role(user) -> str:
    role = getattr(user, "role", None)
    if role is None and isinstance(user, dict):
        role = user.get("role", "viewer")
    return str(role or "viewer")


def _dashboard_branch_arg(current_user, branch_id):
    scope = resolve_branch_scope(current_user, branch_id)
    return scope["branch_id"] if scope["branch_id"] is not None else scope["branch_ids"]


def _branch_arg_from_scope(scope: dict):
    return scope["branch_id"] if scope["branch_id"] is not None else scope["branch_ids"]


# ═══════════════════════════════════════════════════════════════════════════════
# Auto-Route: Returns the appropriate dashboard for the current user's role
# ═══════════════════════════════════════════════════════════════════════════════

ROLE_DASHBOARD_MAP = {
    "admin": "executive",
    "system_admin": "executive",
    "superuser": "executive",
    "ceo": "executive",
    "manager": "executive",
    "finance_manager": "financial",
    "chief_accountant": "financial",
    "accountant": "financial",
    "branch_accountant": "financial",
    "accounts_receivable": "sales",
    "accounts_payable": "procurement",
    "treasury_officer": "financial",
    "tax_accountant": "financial",
    "cost_accountant": "financial",
    "auditor": "financial",
    "branch_manager": "executive",
    "sales": "sales",
    "purchasing": "procurement",
    "inventory": "warehouse",
    "hr_manager": "hr",
    "cashier": "pos",
    "manufacturing_user": "manufacturing",
    "project_manager": "projects",
    "viewer": "executive",
}


@router.get("/auto",
            response_model=Dict[str, Any],
            dependencies=[Depends(require_permission("dashboard.view"))],
            summary="Auto-detect dashboard by user role")
@cached("role_dashboard_auto", expire=120)
def get_auto_dashboard(
    period: str = Query("mtd", description="Period: today|wtd|mtd|qtd|ytd|custom"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    لوحة التحكم التلقائية — تكتشف دور المستخدم وتعيد اللوحة المناسبة.
    Auto-detect the user's role and return the matching dashboard.
    """
    role = _get_user_role(current_user)
    dashboard_type = ROLE_DASHBOARD_MAP.get(role, "executive")

    # Dispatch to the right handler
    handlers = {
        "executive": get_executive_kpis,
        "financial": get_financial_kpis,
        "sales": get_sales_kpis,
        "procurement": get_procurement_kpis,
        "warehouse": get_warehouse_kpis,
        "hr": get_hr_kpis,
        "manufacturing": get_manufacturing_kpis,
        "projects": get_projects_kpis,
        "pos": get_pos_kpis,
        "crm": get_crm_kpis,
    }

    handler = handlers.get(dashboard_type, get_executive_kpis)
    return _execute_dashboard(handler, current_user, period, start_date, end_date, branch_id)


# ═══════════════════════════════════════════════════════════════════════════════
# Executive Dashboard (CEO / Admin / Superuser)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/executive",
            response_model=Dict[str, Any],
            dependencies=[Depends(require_permission(["dashboard.executive", "dashboard.view"]))],
            summary="Executive Dashboard — CEO KPIs")
@cached("role_dashboard_exec", expire=120)
def get_executive_dashboard(
    period: str = Query("mtd"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """لوحة تحكم المدير التنفيذي — مؤشرات أداء شاملة للإدارة العليا"""
    _require_roles(current_user, ["admin", "superuser", "system_admin", "ceo", "manager", "branch_manager"])
    return _execute_dashboard(get_executive_kpis, current_user, period, start_date, end_date, branch_id)


# ═══════════════════════════════════════════════════════════════════════════════
# Financial Dashboard (CFO / Accountant)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/financial",
            response_model=Dict[str, Any],
            dependencies=[Depends(require_permission(["dashboard.financial", "accounting.view"]))],
            summary="Financial Dashboard — CFO KPIs")
@cached("role_dashboard_fin", expire=120)
def get_financial_dashboard(
    period: str = Query("mtd"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """لوحة تحكم المدير المالي — نسب مالية وسيولة وميزانيات"""
    _require_roles(current_user, [
        "admin", "superuser", "system_admin", "ceo", "manager", "finance_manager",
        "chief_accountant", "accountant", "branch_accountant", "treasury_officer",
        "tax_accountant", "cost_accountant", "auditor",
    ])
    return _execute_dashboard(get_financial_kpis, current_user, period, start_date, end_date, branch_id)


# ═══════════════════════════════════════════════════════════════════════════════
# Sales Dashboard
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/sales",
            response_model=Dict[str, Any],
            dependencies=[Depends(require_permission(["dashboard.sales", "sales.view"]))],
            summary="Sales Dashboard — Sales Manager KPIs")
@cached("role_dashboard_sales", expire=120)
def get_sales_dashboard(
    period: str = Query("mtd"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """لوحة تحكم المبيعات — إيرادات وتحويل ومتأخرات"""
    _require_roles(current_user, ["admin", "superuser", "system_admin", "manager", "branch_manager", "sales", "accounts_receivable"])
    return _execute_dashboard(get_sales_kpis, current_user, period, start_date, end_date, branch_id)


# ═══════════════════════════════════════════════════════════════════════════════
# Procurement Dashboard
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/procurement",
            response_model=Dict[str, Any],
            dependencies=[Depends(require_permission(["dashboard.procurement", "buying.view"]))],
            summary="Procurement Dashboard — Purchase Manager KPIs")
@cached("role_dashboard_proc", expire=120)
def get_procurement_dashboard(
    period: str = Query("mtd"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """لوحة تحكم المشتريات — أوامر شراء وموردين"""
    _require_roles(current_user, ["admin", "superuser", "system_admin", "manager", "branch_manager", "purchasing", "accounts_payable"])
    return _execute_dashboard(get_procurement_kpis, current_user, period, start_date, end_date, branch_id)


# ═══════════════════════════════════════════════════════════════════════════════
# Warehouse Dashboard
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/warehouse",
            response_model=Dict[str, Any],
            dependencies=[Depends(require_permission(["dashboard.warehouse", "stock.view", "inventory.view"]))],
            summary="Warehouse Dashboard — Inventory Manager KPIs")
@cached("role_dashboard_wh", expire=120)
def get_warehouse_dashboard(
    period: str = Query("mtd"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """لوحة تحكم المخازن — مخزون ودوران ونفاد"""
    _require_roles(current_user, ["admin", "superuser", "system_admin", "manager", "inventory"])
    return _execute_dashboard(get_warehouse_kpis, current_user, period, start_date, end_date, branch_id)


# ═══════════════════════════════════════════════════════════════════════════════
# HR Dashboard
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/hr",
            response_model=Dict[str, Any],
            dependencies=[Depends(require_permission(["dashboard.hr", "hr.view"]))],
            summary="HR Dashboard — HR Manager KPIs")
@cached("role_dashboard_hr", expire=120)
def get_hr_dashboard(
    period: str = Query("mtd"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """لوحة تحكم الموارد البشرية — سعودة وحضور ورواتب"""
    _require_roles(current_user, ["admin", "superuser", "system_admin", "manager", "hr_manager"])
    return _execute_dashboard(get_hr_kpis, current_user, period, start_date, end_date, branch_id)


# ═══════════════════════════════════════════════════════════════════════════════
# Manufacturing Dashboard
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/manufacturing",
            response_model=Dict[str, Any],
            dependencies=[Depends(require_permission(["dashboard.manufacturing", "manufacturing.view"]))],
            summary="Manufacturing Dashboard — Production KPIs")
@cached("role_dashboard_mfg", expire=120)
def get_manufacturing_dashboard(
    period: str = Query("mtd"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """لوحة تحكم التصنيع — OEE وإنتاج وتكلفة"""
    _require_roles(current_user, ["admin", "superuser", "system_admin", "manager", "manufacturing_user"])
    return _execute_dashboard(get_manufacturing_kpis, current_user, period, start_date, end_date, branch_id)


# ═══════════════════════════════════════════════════════════════════════════════
# Projects Dashboard
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/projects",
            response_model=Dict[str, Any],
            dependencies=[Depends(require_permission(["dashboard.projects", "projects.view"]))],
            summary="Projects Dashboard — Project Manager KPIs")
@cached("role_dashboard_proj", expire=120)
def get_projects_dashboard(
    period: str = Query("mtd"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """لوحة تحكم المشاريع — EVM ومخاطر وموارد"""
    _require_roles(current_user, ["admin", "superuser", "system_admin", "manager", "project_manager"])
    return _execute_dashboard(get_projects_kpis, current_user, period, start_date, end_date, branch_id)


# ═══════════════════════════════════════════════════════════════════════════════
# POS Dashboard
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/pos",
            response_model=Dict[str, Any],
            dependencies=[Depends(require_permission(["dashboard.pos", "pos.view"]))],
            summary="POS Dashboard — Cashier KPIs")
@cached("role_dashboard_pos", expire=60)
def get_pos_dashboard(
    period: str = Query("today"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """لوحة تحكم نقاط البيع — مبيعات اليوم وعمليات"""
    _require_roles(current_user, ["admin", "superuser", "system_admin", "manager", "cashier", "sales"])
    return _execute_dashboard(get_pos_kpis, current_user, period, start_date, end_date, branch_id)


# ═══════════════════════════════════════════════════════════════════════════════
# CRM Dashboard
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/crm",
            response_model=Dict[str, Any],
            dependencies=[Depends(require_permission(["dashboard.crm", "sales.view"]))],
            summary="CRM Dashboard — Sales Rep KPIs")
@cached("role_dashboard_crm", expire=120)
def get_crm_dashboard(
    period: str = Query("mtd"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """لوحة تحكم إدارة العلاقات — فرص وتذاكر وحملات"""
    _require_roles(current_user, ["admin", "superuser", "system_admin", "manager", "sales"])
    return _execute_dashboard(get_crm_kpis, current_user, period, start_date, end_date, branch_id)


# ═══════════════════════════════════════════════════════════════════════════════
# Industry Dashboard (auto-detected from company settings)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/industry",
            response_model=Dict[str, Any],
            dependencies=[Depends(require_permission(["dashboard.industry", "dashboard.view"]))],
            summary="Industry KPIs — auto-detected by company sector")
@cached("role_dashboard_industry", expire=300)
def get_industry_dashboard(
    period: str = Query("mtd"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """لوحة مؤشرات القطاع — تُكتشف تلقائياً حسب نوع الشركة"""
    company_id = _get_company_id(current_user)
    branch_scope = resolve_branch_scope(current_user, branch_id)
    branch_id = _branch_arg_from_scope(branch_scope)
    s, e = resolve_period(period, start_date, end_date)

    db = get_db_connection(company_id)
    try:
        display_meta = resolve_display_currency(db, branch_scope)
        result = get_industry_kpis(db, company_id, s, e, branch_id)
        result["period"] = {"type": period, "start": str(s), "end": str(e)}
        return convert_dashboard_payload_to_display(result, display_meta)
    except Exception as ex:
        logger.error(f"Industry dashboard error: {ex}")
        raise HTTPException(status_code=500, detail="Error loading industry dashboard")
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Combined Dashboard (Role + Industry in one call)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/combined",
            response_model=Dict[str, Any],
            dependencies=[Depends(require_permission("dashboard.view"))],
            summary="Combined Role + Industry Dashboard")
@cached("role_dashboard_combined", expire=120)
def get_combined_dashboard(
    period: str = Query("mtd"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    لوحة مدمجة — مؤشرات الدور الوظيفي + مؤشرات القطاع في استدعاء واحد.
    Combined dashboard: Role KPIs + Industry KPIs in a single call.
    """
    company_id = _get_company_id(current_user)
    role = _get_user_role(current_user)
    dashboard_type = ROLE_DASHBOARD_MAP.get(role, "executive")
    branch_scope = resolve_branch_scope(current_user, branch_id)
    branch_id = _branch_arg_from_scope(branch_scope)
    s, e = resolve_period(period, start_date, end_date)

    handlers = {
        "executive": get_executive_kpis,
        "financial": get_financial_kpis,
        "sales": get_sales_kpis,
        "procurement": get_procurement_kpis,
        "warehouse": get_warehouse_kpis,
        "hr": get_hr_kpis,
        "manufacturing": get_manufacturing_kpis,
        "projects": get_projects_kpis,
        "pos": get_pos_kpis,
        "crm": get_crm_kpis,
    }

    db = get_db_connection(company_id)
    try:
        display_meta = resolve_display_currency(db, branch_scope)
        # Role KPIs
        handler = handlers.get(dashboard_type, get_executive_kpis)
        role_data = handler(db, s, e, branch_id)

        # Industry KPIs
        industry_data = get_industry_kpis(db, company_id, s, e, branch_id)

        return convert_dashboard_payload_to_display({
            "role": role_data.get("role", dashboard_type),
            "industry": industry_data.get("industry", "general"),
            "period": {"type": period, "start": str(s), "end": str(e)},
            "role_kpis": role_data.get("kpis", []),
            "role_charts": role_data.get("charts", []),
            "role_alerts": role_data.get("alerts", []),
            "industry_kpis": industry_data.get("kpis", []),
            "industry_charts": industry_data.get("charts", []),
            "industry_alerts": industry_data.get("alerts", []),
        }, display_meta)
    except Exception as ex:
        logger.error(f"Combined dashboard error: {ex}")
        raise HTTPException(status_code=500, detail="Error loading combined dashboard")
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Available Dashboards (for frontend navigation)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/available",
            response_model=Dict[str, Any],
            dependencies=[Depends(require_permission("dashboard.view"))],
            summary="List dashboards available to current user")
def get_available_dashboards(
    current_user: dict = Depends(get_current_user)
):
    """قائمة اللوحات المتاحة للمستخدم الحالي حسب صلاحياته"""
    role = _get_user_role(current_user)
    permissions = []
    if isinstance(current_user, dict):
        permissions = current_user.get("permissions", [])
    else:
        permissions = getattr(current_user, "permissions", [])

    has_all = "*" in permissions

    dashboards = []

    if has_all or role in ("admin", "superuser", "system_admin", "ceo", "manager", "branch_manager"):
        dashboards.append({"key": "executive", "label": "Executive Dashboard",
                            "label_ar": "لوحة المدير التنفيذي", "icon": "Crown", "path": "/dashboard/role/executive"})
    if has_all or "dashboard.financial" in permissions or "accounting.view" in permissions or "accounting.*" in permissions or role in {
        "finance_manager", "chief_accountant", "accountant", "branch_accountant",
        "treasury_officer", "tax_accountant", "cost_accountant", "auditor",
    }:
        dashboards.append({"key": "financial", "label": "Financial Dashboard",
                            "label_ar": "لوحة المدير المالي", "icon": "Calculator", "path": "/dashboard/role/financial"})
    if has_all or "sales.view" in permissions or "sales.*" in permissions or role in {"sales", "accounts_receivable", "branch_manager"}:
        dashboards.append({"key": "sales", "label": "Sales Dashboard",
                            "label_ar": "لوحة المبيعات", "icon": "TrendingUp", "path": "/dashboard/role/sales"})
    if has_all or "buying.view" in permissions or "buying.*" in permissions or role in {"purchasing", "accounts_payable", "branch_manager"}:
        dashboards.append({"key": "procurement", "label": "Procurement Dashboard",
                            "label_ar": "لوحة المشتريات", "icon": "ShoppingCart", "path": "/dashboard/role/procurement"})
    if has_all or "stock.view" in permissions or "inventory.*" in permissions or role == "inventory":
        dashboards.append({"key": "warehouse", "label": "Warehouse Dashboard",
                            "label_ar": "لوحة المخازن", "icon": "Warehouse", "path": "/dashboard/role/warehouse"})
    if has_all or "hr.view" in permissions or "hr.*" in permissions or role == "hr_manager":
        dashboards.append({"key": "hr", "label": "HR Dashboard",
                            "label_ar": "لوحة الموارد البشرية", "icon": "Users", "path": "/dashboard/role/hr"})
    if has_all or "manufacturing.view" in permissions or "manufacturing.*" in permissions or role == "manufacturing_user":
        dashboards.append({"key": "manufacturing", "label": "Manufacturing Dashboard",
                            "label_ar": "لوحة التصنيع", "icon": "Factory", "path": "/dashboard/role/manufacturing"})
    if has_all or "projects.view" in permissions or "projects.*" in permissions or role == "project_manager":
        dashboards.append({"key": "projects", "label": "Projects Dashboard",
                            "label_ar": "لوحة المشاريع", "icon": "FolderKanban", "path": "/dashboard/role/projects"})
    if has_all or "pos.view" in permissions or "pos.*" in permissions or role == "cashier":
        dashboards.append({"key": "pos", "label": "POS Dashboard",
                            "label_ar": "لوحة نقاط البيع", "icon": "Monitor", "path": "/dashboard/role/pos"})
    if has_all or "sales.view" in permissions or role == "sales":
        dashboards.append({"key": "crm", "label": "CRM Dashboard",
                            "label_ar": "لوحة العلاقات", "icon": "Handshake", "path": "/dashboard/role/crm"})

    # Always add industry
    dashboards.append({"key": "industry", "label": "Industry KPIs",
                        "label_ar": "مؤشرات القطاع", "icon": "BarChart3", "path": "/dashboard/role/industry"})

    # Determine default dashboard for this user
    default_key = ROLE_DASHBOARD_MAP.get(role, "executive")

    return {
        "dashboards": dashboards,
        "default": default_key,
        "role": role,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Internal Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _require_roles(user, allowed_roles: list):
    """Check if user's role is in the allowed list. Admin/superuser always pass."""
    role = _get_user_role(user)
    permissions = []
    if isinstance(user, dict):
        permissions = user.get("permissions", [])
    else:
        permissions = getattr(user, "permissions", [])

    # Wildcard permission holders bypass role check
    if "*" in permissions:
        return

    if role not in allowed_roles:
        raise HTTPException(
            status_code=403,
            detail=f"Access denied. Required roles: {', '.join(allowed_roles)}"
        )


def _execute_dashboard(handler, current_user, period: str,
                       start_date, end_date, branch_id):
    """Execute a dashboard handler with proper DB lifecycle."""
    company_id = _get_company_id(current_user)
    branch_scope = resolve_branch_scope(current_user, branch_id)
    branch_id = _branch_arg_from_scope(branch_scope)
    s, e = resolve_period(period, start_date, end_date)

    db = get_db_connection(company_id)
    try:
        display_meta = resolve_display_currency(db, branch_scope)
        result = handler(db, s, e, branch_id)
        result["period"] = {"type": period, "start": str(s), "end": str(e)}
        return convert_dashboard_payload_to_display(result, display_meta)
    except HTTPException:
        raise
    except Exception as ex:
        logger.error(f"Dashboard error ({handler.__name__}): {ex}")
        raise HTTPException(status_code=500, detail="Error loading dashboard data")
    finally:
        db.close()
