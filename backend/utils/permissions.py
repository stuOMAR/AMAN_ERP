"""
AMAN ERP - Permission Utilities
Server-side permission enforcement for API endpoints.
PERM-001: Field-Level Permissions
PERM-002: Warehouse-Level Permissions
PERM-003: Cost-Center-Level Permissions
PERM-004: Permission Audit Logging
"""

from fastapi import Depends, HTTPException, status
from typing import List, Union, Any, Optional, Dict
import logging
import json

from routers.auth import get_current_user

logger = logging.getLogger(__name__)

# Permission aliases: if a user has the KEY permission, they implicitly also have the VALUE permissions.
# This bridges "umbrella" permissions to the specific ones actually checked by routers.
PERMISSION_ALIASES: Dict[str, List[str]] = {
    # inventory.* is an umbrella for stock + products
    "inventory.view":   ["stock.view", "products.view"],
    "inventory.delete": ["products.delete", "stock.adjustment"],
    "inventory.*":      ["stock.view", "stock.view_cost", "stock.adjustment", "stock.transfer",
                         "stock.manage", "stock.reports",
                         "products.view", "products.create", "products.edit", "products.delete"],
    # projects.manage covers all project CRUD
    "projects.manage":  ["projects.view", "projects.create", "projects.edit", "projects.delete"],
    # admin.users is an alias that grants user-related admin access
    "admin.users":      ["admin.roles", "settings.view", "settings.edit"],
    # admin.branches → branches.manage (fix inconsistency)
    "admin.branches":   ["branches.view", "branches.manage"],
    # sales aliases
    "sales.edit":       ["sales.create"],
    "sales.delete":     ["sales.create"],
    # buying.reports routes to buying.view
    "buying.reports":   ["buying.view"],
    # hr.reports routes to hr.view
    "hr.reports":       ["hr.view"],
    # hr.pii grants access to unmasked PII fields (IBAN, national ID, GOSI, etc.)
    "hr.manage":        ["hr.pii", "hr.view"],
    "hr.payroll":       ["hr.pii"],
    # reports.financial implies reports.view
    "reports.financial": ["reports.view"],
    # manufacturing.reports implies manufacturing.view
    "manufacturing.reports": ["manufacturing.view"],
    # notifications.send implies notifications.view
    "notifications.send": ["notifications.view"],
    # approvals edit is an alias for approvals.manage
    "approvals.manage": ["approvals.view", "approvals.create"],
    # accounting.manage implies view + edit
    "accounting.manage": ["accounting.view", "accounting.edit"],
    # treasury.manage implies view + create + edit
    "treasury.manage": ["treasury.view", "treasury.create", "treasury.edit"],
    # taxes.manage implies taxes.view
    "taxes.manage": ["taxes.view"],
    # settings.manage implies settings.view + settings.edit
    "settings.manage": ["settings.view", "settings.edit"],
    # === Duplicate-name aliases (same concept, different legacy name used by some routers/pages) ===
    # approvals.approve is the canonical key; frontend also uses `approvals.action`
    "approvals.approve": ["approvals.action"],
    # approvals.manage implies view + create + action
    "approvals.manage": ["approvals.view", "approvals.create", "approvals.action"],
    # products.create / delete used under stock.* aliases by ProductList UI
    "products.create": ["stock.create_product"],
    "products.delete": ["stock.delete_product"],
    # data_import.create is canonical; frontend uses `data_import.execute`
    "data_import.create": ["data_import.execute"],
    # sso.manage is canonical; sso router uses `auth.sso_manage`
    "sso.manage": ["auth.sso_manage"],
    # hr.leaves.manage implies view
    "hr.leaves.manage": ["hr.leaves.view"],
    # crm umbrella: manage implies view; execute implies view
    "crm.campaign_manage": ["crm.campaign_view"],
    "crm.campaign_execute": ["crm.campaign_view"],
    # projects granular aliases
    "projects.resource_manage": ["projects.resource_view"],
    "projects.time_approve": ["projects.time_view", "projects.time_log"],
    # inventory forecast manage implies view + generate
    "inventory.forecast_manage": ["inventory.forecast_view", "inventory.forecast_generate"],
    # inventory costing manage implies view
    "inventory.costing_manage": ["inventory.costing_view"],
    # manufacturing shopfloor/routing manage implies view
    "manufacturing.shopfloor_operate": ["manufacturing.shopfloor_view"],
    "manufacturing.routing_manage": ["manufacturing.routing_view"],
    # hr.performance manage implies view + review + self
    "hr.performance_manage": ["hr.performance_view", "hr.performance_review", "hr.performance_self"],
    # finance aliases
    "finance.subscription_manage": ["finance.subscription_view"],
    "finance.cashflow_manage": ["finance.cashflow_view", "finance.cashflow_generate"],
    # dashboard BI
    "dashboard.analytics_manage": ["dashboard.analytics_view"],
    # accounting journal entry: post/void imply create
    "accounting.post_journal_entry": ["accounting.create_journal_entry"],
    "accounting.void_journal_entry": ["accounting.create_journal_entry"],
    # accounting.manage covers all JE granular
    "accounting.manage": ["accounting.create_journal_entry", "accounting.post_journal_entry", "accounting.void_journal_entry"],
    # Blanket PO: manage implies view; release implies view
    "buying.blanket_manage": ["buying.blanket_view"],
    "buying.blanket_release": ["buying.blanket_view"],
    # Expenses policies: manage implies expense view
    "expenses.manage": ["expenses.view"],
    # Finance accounting depth: post implies read/view, read implies view
    "finance.accounting_post": ["finance.accounting_read", "finance.accounting_view"],
    "finance.accounting_read": ["finance.accounting_view"],
    # Finance bank-feed reconciliation: manage implies view
    "finance.reconciliation_manage": ["finance.reconciliation_view"],
    # === 2026-04-22 audit: umbrella & legacy aliases ===
    # sales.manage / buying.manage umbrellas used by frontend Settings tabs
    # T2.3 (2026-05-01): sales.manage now also implies the new sensitive sub-permissions
    # (void / approve_return / manage_credit_notes) so existing admin roles keep working.
    # NOTE: sales.create does NOT alias to these — that's the whole point of T2.3.
    "sales.manage":   ["sales.view", "sales.create", "sales.edit", "sales.delete",
                       "sales.void", "sales.approve_return", "sales.manage_credit_notes"],
    "buying.manage":  ["buying.view", "buying.create", "buying.edit", "buying.delete", "buying.approve", "buying.receive"],
    # costing.* legacy keys route to canonical inventory.costing_*
    "costing.view":   ["inventory.costing_view"],
    "costing.manage": ["inventory.costing_manage", "inventory.costing_view"],
}


def check_permission(user_permissions: list, required_permission: str) -> bool:
    """
    Check if user has the required permission.
    Supports:
    - Exact match: 'products.create'
    - Wildcard: '*' (full access)
    - Section wildcard: 'products.*'
    - Permission aliases (PERMISSION_ALIASES above)
    """
    if not user_permissions:
        return False
    
    # Full admin access
    if "*" in user_permissions:
        return True
    
    # Exact match
    if required_permission in user_permissions:
        return True
    
    # Section wildcard (e.g., 'products.*' matches 'products.create')
    req_parts = required_permission.split(".")
    if len(req_parts) >= 1:
        section_wildcard = f"{req_parts[0]}.*"
        if section_wildcard in user_permissions:
            return True

    # Alias expansion: check if any user permission is an alias that covers required_permission
    for user_perm in user_permissions:
        implied = PERMISSION_ALIASES.get(user_perm, [])
        if required_permission in implied:
            return True
    
    return False


def require_permission(permission: Union[str, List[str]]):
    """
    FastAPI dependency that checks if the current user has the required permission.
    Usage:
        @router.delete("/products/{id}", dependencies=[Depends(require_permission("products.delete"))])
        def delete_product(id: int, ...):
            ...
    
    Or for multiple permissions (user needs ANY of them):
        @router.post("/...", dependencies=[Depends(require_permission(["sales.create", "admin"]))])
    """
    async def permission_checker(current_user: Union[dict, Any] = Depends(get_current_user)):
        # Get user permissions
        if isinstance(current_user, dict):
            user_perms = current_user.get("permissions", [])
            username = current_user.get("username", "unknown")
        else:
            user_perms = getattr(current_user, 'permissions', []) or []
            username = getattr(current_user, 'username', 'unknown')
        
        # If permission is a string, convert to list
        required_perms = [permission] if isinstance(permission, str) else permission
        
        # Check if user has ANY of the required permissions
        has_permission = any(check_permission(user_perms, perm) for perm in required_perms)
        
        if not has_permission:
            logger.warning(f"🚫 Permission denied: User {username} tried to access {permission}")
            # PERM-004: Log denied access
            _log_permission_denied(current_user, permission)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"ليس لديك صلاحية لتنفيذ هذا الإجراء: {permission}"
            )
        
        return current_user
    
    return permission_checker


# ============ SEC-012: Sensitive-operation re-validation ============
# For financial operations (journal entries, payroll, invoice deletion, etc.)
# this dependency re-checks the DB to ensure the user is still active and has
# the required permission — mitigates JWT-cached permissions after revocation.
SENSITIVE_PERMISSIONS = {
    "accounting.manage", "accounting.edit",
    "treasury.manage", "treasury.edit",
    "sales.delete", "buying.delete",
    # T2.3 (2026-05-01): granular sensitive sales operations
    "sales.void", "sales.approve_return", "sales.manage_credit_notes",
    "hr.payroll", "hr.manage",
    "admin.users", "settings.manage",
}

def require_sensitive_permission(permission: Union[str, List[str]]):
    """Like require_permission but also re-validates against the DB."""
    async def _checker(current_user: Union[dict, Any] = Depends(get_current_user)):
        # First do the normal check
        if isinstance(current_user, dict):
            user_perms = current_user.get("permissions", [])
            username = current_user.get("username", "unknown")
            company_id = current_user.get("company_id")
            user_id = current_user.get("user_id")
        else:
            user_perms = getattr(current_user, 'permissions', []) or []
            username = getattr(current_user, 'username', 'unknown')
            company_id = getattr(current_user, 'company_id', None)
            user_id = getattr(current_user, 'id', None)

        required_perms = [permission] if isinstance(permission, str) else permission
        has_permission = any(check_permission(user_perms, perm) for perm in required_perms)
        if not has_permission:
            raise HTTPException(status_code=403, detail=f"ليس لديك صلاحية: {permission}")

        # Re-validate from DB for sensitive ops
        if company_id and user_id:
            try:
                from database import get_db_connection
                db = get_db_connection(company_id)
                row = db.execute(
                    __import__('sqlalchemy').text(
                        "SELECT is_active FROM company_users WHERE id = :uid"
                    ), {"uid": user_id}
                ).fetchone()
                if row and not row.is_active:
                    logger.warning(f"🔒 Sensitive op blocked: user {username} is deactivated (DB check)")
                    raise HTTPException(status_code=403, detail="تم تعطيل حسابك. يرجى التواصل مع المسؤول.")
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"DB re-validation error: {e}")
                # Fail open — if DB is unreachable, rely on JWT check above

        return current_user

    return _checker
# URL prefix → module key mapping for the 5 variable modules
_ROUTE_MODULE_MAP = {
    "/pos":           "pos",
    "/inventory":     "stock",
    "/manufacturing": "manufacturing",
    "/projects":      "projects",
    "/services":      "services",
}

def require_module(module_key: str):
    """
    FastAPI dependency that blocks access if the module is disabled for the company.
    Uses enabled_modules from the UserResponse (already fetched from system_companies).

    Usage:
        router = APIRouter(prefix="/pos", dependencies=[Depends(require_module("pos"))])
    Or per-endpoint:
        @router.get("/...", dependencies=[Depends(require_module("stock"))])
    """
    async def module_checker(current_user: Union[dict, Any] = Depends(get_current_user)):
        # System admins bypass module checks
        if isinstance(current_user, dict):
            role = current_user.get("role")
            enabled = current_user.get("enabled_modules", [])
            username = current_user.get("username", "unknown")
        else:
            role = getattr(current_user, "role", None)
            enabled = getattr(current_user, "enabled_modules", []) or []
            username = getattr(current_user, "username", "unknown")

        if role in ("system_admin", "superuser"):
            return current_user

        # If enabled_modules is empty/null, allow all (pre-setup state)
        if not enabled:
            return current_user

        if module_key not in enabled:
            logger.warning(f"🚫 Module disabled: User {username} tried to access module '{module_key}'")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"هذه الوحدة ({module_key}) غير مفعّلة لشركتك. يمكنك تفعيلها من إعدادات النشاط."
            )

        return current_user

    return module_checker


def validate_branch_access(current_user: dict, requested_branch_id: Union[int, None, str] = None) -> Union[int, None]:
    """
    Enforces branch access scope.
    """
    # Handle both dict and Pydantic model
    if isinstance(current_user, dict):
        allowed_branches = current_user.get("allowed_branches", [])
        role = current_user.get("role")
        permissions = current_user.get("permissions", [])
    else:
        allowed_branches = getattr(current_user, "allowed_branches", [])
        role = getattr(current_user, "role", None)
        permissions = getattr(current_user, "permissions", [])

    # CRITICAL FIX: Admins have full access regardless of allowed_branches
    if role in ['admin', 'system_admin', 'superuser'] or "*" in permissions:
        if not requested_branch_id or requested_branch_id == "":
            return None
        try:
            return int(requested_branch_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid branch ID")
    
    # If no restrictions, return as is (handling empty string/None)
    if not allowed_branches:
        if requested_branch_id == "": return None 
        return int(requested_branch_id) if requested_branch_id else None

    # Handle requested_branch_id
    if requested_branch_id in [None, ""]:
        # User requested ALL, but is restricted.
        if len(allowed_branches) == 1:
            return allowed_branches[0] # Auto-select the only allowed branch
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="يرجى تحديد الفرع (لديك صلاحية على فروع محددة فقط)"
            )
            
    # Cast to int for comparison
    try:
        rid = int(requested_branch_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid branch ID")

    if rid not in allowed_branches:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="ليس لديك صلاحية للوصول إلى بيانات هذا الفرع"
        )
    
    return rid


# ===================== PERM-001: Field-Level Permissions =====================

# Default hidden fields by role (can be overridden per company via DB)
DEFAULT_FIELD_RESTRICTIONS = {
    "salesperson": {
        "products": ["cost_price", "average_cost", "last_purchase_price"],
        "invoice_lines": ["cost_price", "profit_margin"],
        "inventory": ["unit_cost", "total_cost"],
    },
    "accountant": {
        "employees": ["salary", "bank_account", "iban", "gosi_number"],
        "payroll_entries": ["*"],  # Hide entire payroll details
    },
    "warehouse_keeper": {
        "products": ["cost_price", "average_cost", "last_purchase_price", "selling_price"],
        "invoices": ["*"],
    },
    # SEC-FIX RT-009: Additional role field restrictions
    "cashier": {
        "products": ["cost_price", "average_cost", "last_purchase_price", "profit_margin"],
        "invoice_lines": ["cost_price", "profit_margin"],
        "suppliers": ["*"],
        "purchase_orders": ["*"],
        "inventory": ["unit_cost", "total_cost"],
    },
    "inventory": {
        "products": ["selling_price", "profit_margin"],
        "invoices": ["*"],
        "journal_entries": ["*"],
        "employees": ["*"],
    },
    "user": {
        "products": ["cost_price", "average_cost", "last_purchase_price", "profit_margin"],
        "invoice_lines": ["cost_price", "profit_margin"],
        "inventory": ["unit_cost", "total_cost"],
        "journal_entries": ["*"],
        "employees": ["salary", "bank_account", "iban", "gosi_number"],
    },
}


def get_field_restrictions(current_user, company_conn=None) -> Dict[str, List[str]]:
    """
    PERM-001: Get field-level restrictions for current user.
    Returns dict of {resource: [hidden_fields]}
    """
    if isinstance(current_user, dict):
        role = current_user.get("role")
        permissions = current_user.get("permissions", [])
        user_id = current_user.get("id")
    else:
        role = getattr(current_user, "role", None)
        permissions = getattr(current_user, "permissions", [])
        user_id = getattr(current_user, "id", None)

    # Admins have no restrictions
    if role in ['admin', 'system_admin', 'superuser'] or "*" in (permissions or []):
        return {}

    restrictions = {}

    # Check DB for custom field restrictions (per-user or per-role)
    if company_conn and user_id:
        try:
            # Check user-specific restrictions first
            row = company_conn.execute(
                __import__('sqlalchemy', fromlist=['text']).text(
                    "SELECT field_restrictions FROM user_field_permissions WHERE user_id = :uid"
                ), {"uid": user_id}
            ).scalar()
            if row:
                return json.loads(row) if isinstance(row, str) else row
            
            # Fallback to role-based restrictions from DB
            if role:
                row = company_conn.execute(
                    __import__('sqlalchemy', fromlist=['text']).text(
                        "SELECT field_restrictions FROM role_field_permissions WHERE role_name = :role"
                    ), {"role": role}
                ).scalar()
                if row:
                    return json.loads(row) if isinstance(row, str) else row
        except Exception:
            pass  # Table might not exist yet

    # Fallback to default restrictions
    return DEFAULT_FIELD_RESTRICTIONS.get(role, {})


def filter_fields(data: Union[dict, list], resource: str, current_user, company_conn=None):
    """
    PERM-001: Filter out restricted fields from response data.
    Usage in endpoint:
        result = filter_fields(product_dict, "products", current_user, db)
    """
    restrictions = get_field_restrictions(current_user, company_conn)
    hidden_fields = restrictions.get(resource, [])

    if not hidden_fields:
        return data

    if hidden_fields == ["*"]:
        # Hide entire resource
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"ليس لديك صلاحية لعرض بيانات {resource}"
        )

    if isinstance(data, list):
        return [{k: v for k, v in item.items() if k not in hidden_fields}
                for item in data if isinstance(item, dict)]
    elif isinstance(data, dict):
        return {k: v for k, v in data.items() if k not in hidden_fields}

    return data


# ===================== PERM-002: Warehouse-Level Permissions =====================

def get_allowed_warehouses(current_user, company_conn=None) -> Optional[List[int]]:
    """
    PERM-002: Get list of warehouse IDs the user can access.
    Returns None if user has access to ALL warehouses (admin).
    Returns [] if user has NO warehouse access.
    Returns [1, 2, 3] if restricted to specific warehouses.
    """
    if isinstance(current_user, dict):
        role = current_user.get("role")
        permissions = current_user.get("permissions", [])
        user_id = current_user.get("id")
    else:
        role = getattr(current_user, "role", None)
        permissions = getattr(current_user, "permissions", [])
        user_id = getattr(current_user, "id", None)

    # Admins have access to all warehouses
    if role in ['admin', 'system_admin', 'superuser'] or "*" in (permissions or []):
        return None  # None = unrestricted

    if not company_conn or not user_id:
        return None

    try:
        from sqlalchemy import text
        rows = company_conn.execute(text(
            "SELECT warehouse_id FROM user_warehouses WHERE user_id = :uid"
        ), {"uid": user_id}).fetchall()

        if not rows:
            return None  # No restrictions defined = access all

        return [r[0] for r in rows]
    except Exception:
        return None  # Table might not exist yet


def build_warehouse_filter(current_user, company_conn=None, 
                           warehouse_column: str = "warehouse_id",
                           table_alias: str = "") -> tuple:
    """
    PERM-002: Build SQL filter clause for warehouse restriction.
    Returns (sql_clause, params_dict)
    Usage:
        wh_filter, wh_params = build_warehouse_filter(user, db, "inv.warehouse_id")
        query = f"SELECT * FROM inventory inv WHERE 1=1 {wh_filter}"
        result = db.execute(text(query), {**other_params, **wh_params})
    """
    allowed = get_allowed_warehouses(current_user, company_conn)
    if allowed is None:
        return "", {}

    if not allowed:
        return " AND 1=0", {}  # No access

    col = f"{table_alias}.{warehouse_column}" if table_alias else warehouse_column
    # Use parameterized query with IN clause
    param_names = [f"_wh_{i}" for i in range(len(allowed))]
    placeholders = ", ".join(f":{p}" for p in param_names)
    params = {p: int(v) for p, v in zip(param_names, allowed)}
    return f" AND {col} IN ({placeholders})", params


# ===================== PERM-003: Cost-Center-Level Permissions =====================

def get_allowed_cost_centers(current_user, company_conn=None) -> Optional[List[int]]:
    """
    PERM-003: Get list of cost center IDs the user can access.
    Returns None if unrestricted.
    """
    if isinstance(current_user, dict):
        role = current_user.get("role")
        permissions = current_user.get("permissions", [])
        user_id = current_user.get("id")
    else:
        role = getattr(current_user, "role", None)
        permissions = getattr(current_user, "permissions", [])
        user_id = getattr(current_user, "id", None)

    if role in ['admin', 'system_admin', 'superuser'] or "*" in (permissions or []):
        return None

    if not company_conn or not user_id:
        return None

    try:
        from sqlalchemy import text
        rows = company_conn.execute(text(
            "SELECT cost_center_id FROM user_cost_centers WHERE user_id = :uid"
        ), {"uid": user_id}).fetchall()

        if not rows:
            return None  # No restrictions = access all

        return [r[0] for r in rows]
    except Exception:
        return None


def build_cost_center_filter(current_user, company_conn=None,
                              cc_column: str = "cost_center_id",
                              table_alias: str = "") -> tuple:
    """
    PERM-003: Build SQL filter clause for cost center restriction.
    Returns (sql_clause, params_dict)
    """
    allowed = get_allowed_cost_centers(current_user, company_conn)
    if allowed is None:
        return "", {}

    if not allowed:
        return " AND 1=0", {}

    col = f"{table_alias}.{cc_column}" if table_alias else cc_column
    param_names = [f"_cc_{i}" for i in range(len(allowed))]
    placeholders = ", ".join(f":{p}" for p in param_names)
    params = {p: int(c) for p, c in zip(param_names, allowed)}
    return f" AND {col} IN ({placeholders})", params


# ===================== PERM-004: Permission Audit Logging =====================

def _log_permission_denied(current_user, permission):
    """Log permission denied events silently"""
    try:
        if isinstance(current_user, dict):
            company_id = current_user.get("company_id")
            user_id = current_user.get("id")
            username = current_user.get("username", "unknown")
        else:
            company_id = getattr(current_user, "company_id", None)
            user_id = getattr(current_user, "id", None)
            username = getattr(current_user, "username", "unknown")

        if not company_id:
            return

        from database import get_db_connection
        from utils.audit import log_activity
        db = get_db_connection(company_id)
        try:
            # T3.7 (audit #137): route through unified log_activity so the
            # permission-denied event participates in the hash chain rather
            # than bypassing it via a direct INSERT.
            log_activity(
                db,
                user_id=user_id,
                username=username,
                action="permission_denied",
                resource_type="security",
                resource_id=None,
                details={"denied_permission": str(permission)},
            )
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
        finally:
            db.close()
    except Exception:
        pass  # Never let audit logging break the app


def log_permission_change(company_conn, admin_user_id: int, admin_username: str,
                          target_user_id: int, change_type: str, details: dict):
    """
    PERM-004 / T3.7 (audit #137): Log permission changes via the unified
    log_activity helper so the entry is hash-chained.
    """
    try:
        from utils.audit import log_activity
        log_activity(
            company_conn,
            user_id=admin_user_id,
            username=admin_username,
            action=change_type,
            resource_type="permissions",
            resource_id=str(target_user_id),
            details=details,
        )
    except Exception as e:
        logger.warning(f"Failed to log permission change: {e}")


# ===================== T2.4: HR PII Masking =====================
# Audit #49 — HR financial PII (salary, IBAN, bank account, allowances, GOSI)
# must be hidden from `hr.view` users unless they also hold `hr.pii`.

EMPLOYEE_PII_FIELDS = (
    "salary", "housing_allowance", "transport_allowance", "other_allowances",
    "hourly_cost", "iban", "bank_account", "bank_account_number",
    "national_id", "gosi_number",
)

PAYROLL_PII_FIELDS = (
    "basic_salary", "housing_allowance", "transport_allowance", "other_allowances",
    "salary_components_earning", "salary_components_deduction", "overtime_amount",
    "deductions", "gosi_employee_share", "violation_deduction", "loan_deduction",
    "net_salary", "net_pay", "gross_salary",
    "total_earnings", "total_allowances", "total_deductions",
)

# Mask sentinel returned in place of real values when caller lacks `hr.pii`.
PII_MASK = None  # explicit None preserves JSON-serializable schema


def has_pii_access(current_user: Any) -> bool:
    """Return True if user holds `hr.pii` (directly or via alias)."""
    if isinstance(current_user, dict):
        perms = current_user.get("permissions") or []
        role = current_user.get("role")
    else:
        perms = getattr(current_user, "permissions", []) or []
        role = getattr(current_user, "role", None)
    # System admins / GMs always see PII (they are the data owners).
    if role in ("admin", "system_admin", "gm"):
        return True
    return check_permission(list(perms), "hr.pii")


def mask_pii(record: Dict[str, Any], fields: tuple) -> Dict[str, Any]:
    """Return a copy of ``record`` with PII ``fields`` set to ``PII_MASK``."""
    if not isinstance(record, dict):
        return record
    out = dict(record)
    for f in fields:
        if f in out:
            out[f] = PII_MASK
    return out


def mask_pii_list(records: List[Dict[str, Any]], fields: tuple) -> List[Dict[str, Any]]:
    return [mask_pii(r, fields) for r in records]

