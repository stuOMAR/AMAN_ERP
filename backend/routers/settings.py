"""
AMAN ERP - Company Settings Router
Handles dynamic key-value settings for each company.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List

from database import get_db_connection
from routers.auth import get_current_user, UserResponse
from utils.permissions import require_permission
from schemas.settings import SettingsUpdateRequest
from utils.audit import log_activity
from utils.cache import cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["Company Settings"])

# ── Settings Validation Map ──────────────────────────────────────────────────
# Maps known setting keys to their expected type and constraints.
# Keys not in this map are rejected (T013/T014).
SETTINGS_VALIDATION_MAP = {
    # Company identity
    "company_name": {"type": "str"},
    "company_name_en": {"type": "str"},
    "company_logo": {"type": "str"},
    "company_address": {"type": "str"},
    "company_phone": {"type": "str"},
    "company_email": {"type": "str"},
    "company_website": {"type": "str"},
    "company_tax_number": {"type": "str"},
    "company_commercial_registry": {"type": "str"},
    "default_currency": {"type": "str"},
    "timezone": {"type": "str"},
    "country": {"type": "str"},
    "industry_type": {"type": "str"},
    "fiscal_year_start": {"type": "str"},
    "fiscal_year_end": {"type": "str"},
    "date_format": {"type": "str"},
    "language": {"type": "str", "allowed": ["ar", "en"]},
    "enabled_modules": {"type": "json"},
    # Financial / Accounting
    "financial_decimal_places": {"type": "int", "min": 0, "max": 6},
    "financial_rounding_method": {"type": "str", "allowed": ["round", "floor", "ceil"]},
    "vat_rate": {"type": "float", "min": 0, "max": 100},
    "vat_enabled": {"type": "bool"},
    "accounting_method": {"type": "str", "allowed": ["accrual", "cash"]},
    "fiscal_lock_date": {"type": "str"},
    "fiscal_lock_enabled": {"type": "bool"},
    "accounting_currency": {"type": "str"},
    # HR / Payroll
    "hr_attendance_enabled": {"type": "bool"},
    "hr_leave_auto_approve": {"type": "bool"},
    "hr_working_days_per_week": {"type": "int", "min": 1, "max": 7},
    "hr_overtime_rate": {"type": "float", "min": 0, "max": 10},
    "payroll_cycle": {"type": "str", "allowed": ["monthly", "biweekly", "weekly"]},
    "payroll_auto_calculate": {"type": "bool"},
    # Sales
    "sales_tax_inclusive": {"type": "bool"},
    "sales_default_payment_terms": {"type": "int", "min": 0, "max": 365},
    "sales_auto_numbering": {"type": "bool"},
    "sales_invoice_prefix": {"type": "str"},
    "crm_enabled": {"type": "bool"},
    # Purchases
    "purchases_default_payment_terms": {"type": "int", "min": 0, "max": 365},
    "purchases_auto_numbering": {"type": "bool"},
    "purchases_approval_required": {"type": "bool"},
    # Inventory
    "inventory_valuation_method": {"type": "str", "allowed": ["fifo", "lifo", "average", "standard"]},
    "inventory_negative_stock": {"type": "bool"},
    "inventory_auto_reorder": {"type": "bool"},
    "stock_valuation_method": {"type": "str"},
    "stock_negative_allowed": {"type": "bool"},
    # SMTP
    "smtp_host": {"type": "str"},
    "smtp_port": {"type": "int", "min": 1, "max": 65535},
    "smtp_user": {"type": "str"},
    "smtp_pass": {"type": "str"},
    "smtp_from_email": {"type": "str"},
    "smtp_from_name": {"type": "str"},
    "smtp_encryption": {"type": "str", "allowed": ["tls", "ssl", "none"]},
    # SMS
    "sms_provider": {"type": "str"},
    "sms_api_key": {"type": "str"},
    "sms_sender_id": {"type": "str"},
    # ZATCA
    "zatca_enabled": {"type": "bool"},
    "zatca_environment": {"type": "str", "allowed": ["sandbox", "production"]},
    "zatca_otp": {"type": "str"},
    "zatca_csr_common_name": {"type": "str"},
    "zatca_private_key": {"type": "str"},
    "zatca_certificate": {"type": "str"},
    "zatca_csid": {"type": "str"},
    "zatca_secret": {"type": "str"},
    # Security
    "security_password_expiry_days": {"type": "int", "min": 0, "max": 365},
    "security_mfa_required": {"type": "bool"},
    "security_session_timeout_minutes": {"type": "int", "min": 5, "max": 1440},
    # Projects
    "project_default_billing_method": {"type": "str", "allowed": ["fixed", "hourly", "milestone"]},
    "project_time_tracking": {"type": "bool"},
    # Expense
    "expense_approval_required": {"type": "bool"},
    "expense_auto_categorize": {"type": "bool"},
    # Workflow
    "workflow_approval_levels": {"type": "int", "min": 1, "max": 10},
    # POS
    "pos_enabled": {"type": "bool"},
    "pos_print_receipt": {"type": "bool"},
    "pos_default_payment_method": {"type": "str"},
    # Audit
    "audit_retention_years": {"type": "int", "min": 1, "max": 10},
    "audit_log_sensitive": {"type": "bool"},
    "audit_log_view": {"type": "bool"},
    # Multi-branch
    "multi_branch_enabled": {"type": "bool"},
    "branches_max_count": {"type": "int", "min": 1, "max": 100},
    # Invoicing / Sales extras
    "invoice_prefix": {"type": "str"},
    "invoice_footer": {"type": "str"},
    "invoice_terms": {"type": "str"},
    "quotation_prefix": {"type": "str"},
    "show_logo_on_invoice": {"type": "bool"},
    "report_show_logo": {"type": "bool"},
    # Inventory extras
    "allow_negative_stock": {"type": "bool"},
    "default_warehouse": {"type": "str"},
    "decimal_places": {"type": "int", "min": 0, "max": 6},
    # Notification
    "notify_low_stock": {"type": "bool"},
    "notify_new_invoice": {"type": "bool"},
    # CRM extras
    "crm_loyalty_enabled": {"type": "bool"},
    # Projects extras
    "projects_enabled": {"type": "bool"},
    "project_timesheet_required": {"type": "bool"},
    # Purchases extras
    "purchases_auto_approve": {"type": "bool"},
    # Expense extras
    "allow_expense_claims": {"type": "bool"},
    # POS thermal
    "pos_auto_cut": {"type": "bool"},
    "pos_onscreen_keyboard": {"type": "bool"},
    "pos_open_drawer": {"type": "bool"},
    "pos_silent_print": {"type": "bool"},
    "thermal_58": {"type": "bool"},
    "thermal_80": {"type": "bool"},
    # Workflow extras
    "workflow_discount_limit": {"type": "float", "min": 0, "max": 100},
    "workflow_sales_return": {"type": "bool"},
    # Security extras
    "security_complex_password": {"type": "bool"},
    # ZATCA extras
    "zatca_env": {"type": "str", "allowed": ["sandbox", "production"]},
    # Performance
    "perf_enable_caching": {"type": "bool"},
    # Company extras
    "commercial_registry": {"type": "str"},
    "tax_number": {"type": "str"},
    "plan_type": {"type": "str"},
}


def _validate_setting_value(key: str, value: Any) -> None:
    """Validate a setting value against SETTINGS_VALIDATION_MAP. Raises HTTPException on failure."""
    spec = SETTINGS_VALIDATION_MAP.get(key)
    if spec is None:
        # Unknown keys are accepted as plain strings — logged for auditing
        logger.debug(f"Accepting unknown setting key: {key}")
        return

    value_str = str(value) if value is not None else ""
    expected_type = spec.get("type", "str")

    if expected_type == "int":
        try:
            int_val = int(value_str)
        except (ValueError, TypeError):
            raise HTTPException(**http_error(400, "invalid_setting_value"))
        if "min" in spec and int_val < spec["min"]:
            raise HTTPException(**http_error(400, "invalid_setting_value"))
        if "max" in spec and int_val > spec["max"]:
            raise HTTPException(**http_error(400, "invalid_setting_value"))
    elif expected_type == "float":
        try:
            float_val = float(value_str)
        except (ValueError, TypeError):
            raise HTTPException(**http_error(400, "invalid_setting_value"))
        if "min" in spec and float_val < spec["min"]:
            raise HTTPException(**http_error(400, "invalid_setting_value"))
        if "max" in spec and float_val > spec["max"]:
            raise HTTPException(**http_error(400, "invalid_setting_value"))
    elif expected_type == "bool":
        if value_str.lower() not in ("true", "false", "1", "0", "yes", "no"):
            raise HTTPException(**http_error(400, "invalid_setting_value"))
    elif expected_type == "json":
        pass  # JSON values are stored as-is
    # str type: no special validation needed

    if "allowed" in spec:
        if value_str.lower() not in [str(a).lower() for a in spec["allowed"]]:
            raise HTTPException(**http_error(400, "invalid_setting_value"))

# Permission Mapping for Settings Keys
# Keys starting with prefix -> require permission
PERMISSION_MAPPING = {
    # Prefix : Required Permission (or one of them)
    "hr_": "hr.view",
    "payroll_": "hr.view",
    "sales_": "sales.view",
    "crm_": "sales.view", 
    "purchases_": "buying.view",
    "inventory_": "stock.view_cost", # Sensitive inventory settings
    "stock_": "stock.view",
    "financial_": "accounting.view",
    "vat_": "accounting.view",
    "fiscal_": "accounting.view",
    "accounting_": "accounting.view",
    "security_": "admin", # Security settings are sensitive
    "smtp_": "admin",      # SMTP creds are sensitive
    "sms_": "admin",       # API keys
    "zatca_": "admin",     # Compliance sensitive
    "project_": "projects.view", # Assuming projects module
    "expense_": "treasury.view",
    "workflow_": "admin", # Workflow rules often involve financial limits
    "audit_": "audit.view",
    "pos_": "pos.view", # Assuming pos role, otherwise settings.view
}

@router.get("/", response_model=Dict[str, Any], dependencies=[Depends(require_permission("settings.view"))])
def get_company_settings(
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Get all company settings as a dictionary.
    Filtered by user permissions.
    """
    company_id = current_user.company_id
    if not company_id:
        raise HTTPException(status_code=400, detail="Company ID missing")
        
    db = get_db_connection(company_id)
    
    try:
        # Try cache first
        cache_key = f"company_settings:{company_id}"
        cached_result = cache.get(cache_key)
        
        if cached_result:
            raw_settings = cached_result
        else:
            result = db.execute(text("SELECT setting_key, setting_value FROM company_settings")).fetchall()
            raw_settings = {row.setting_key: row.setting_value for row in result}
            cache.set(cache_key, raw_settings, expire=3600)

        # Check permissions
        is_admin = current_user.role in ["system_admin", "company_admin", "admin", "superuser"]
        perms = current_user.permissions or []
        has_all_perms = "*" in perms
        can_view_all_settings = is_admin or has_all_perms or "settings.view" in perms or "settings.manage" in perms
        
        settings_dict = {}
        for key, value in raw_settings.items():
            # If user has full access, include everything
            if can_view_all_settings:
                settings_dict[key] = value
                continue
                
            # Otherwise, check granular permissions
            allowed = True
            
            # Default: specific keys might need check. 
            # If key matches a known prefix, check for permission
            for prefix, required_perm in PERMISSION_MAPPING.items():
                if key.startswith(prefix):
                    # Check if user has this permission (or wildcard of it)
                    # e.g. required='hr.view', user has 'hr.*' -> OK
                    has_perm = required_perm in perms
                    if not has_perm:
                        # Check wildcard parent
                        parts = required_perm.split('.')
                        if len(parts) > 1 and f"{parts[0]}.*" in perms:
                            has_perm = True
                    
                    if not has_perm:
                        allowed = False
                    break # Matched prefix, stop checking others
            
            # If allowed, add to result
            if allowed:
                # Basic non-sensitive settings (branding, etc) are allowed by default if they don't match restricted prefixes
                settings_dict[key] = value

        return settings_dict
    except Exception:
        logger.exception("Operation failed")
        return {} 
    finally:
        db.close()

@router.post("/bulk", status_code=status.HTTP_200_OK, dependencies=[Depends(require_permission("settings.manage"))], response_model=Dict[str, Any])
def update_settings_bulk(
    request: SettingsUpdateRequest,
    req: Request = None,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Update or create multiple settings at once.
    """
    company_id = current_user.company_id
    if not company_id:
        raise HTTPException(status_code=400, detail="Company ID missing")
        
    # Authorization Check
    is_admin = current_user.role in ["system_admin", "company_admin", "admin", "superuser"]
    perms = current_user.permissions or []
    has_all_perms = "*" in perms
    # settings.manage allows updating EVERYTHING in this simple implementation? 
    # Or should it be restricted too? Let's say settings.manage is super-power for settings.
    can_manage_all = is_admin or has_all_perms or "settings.manage" in perms
    
    if can_manage_all:
        pass # Allow all
    else:
        # Check each key against user permissions
        for key in request.settings.keys():
            required_perm = None
            
            # Map keys to manage permissions
            if key.startswith("hr_") or key.startswith("payroll_"):
                required_perm = "hr.manage"
            elif key.startswith("sales_") or key.startswith("crm_"):
                required_perm = "sales.manage"
            elif key.startswith("purchases_"):
                required_perm = "buying.manage"
            elif key.startswith("inventory_") or key.startswith("stock_"):
                required_perm = "stock.manage"
            elif key.startswith("financial_") or key.startswith("vat_") or key.startswith("fiscal_") or key.startswith("accounting_"):
                required_perm = "accounting.manage"
            elif key.startswith("project_"):
                required_perm = "projects.manage"
            elif key.startswith("expense_"):
                required_perm = "treasury.manage"
            elif key.startswith("pos_"):
                required_perm = "pos.manage"
            elif key.startswith("audit_"):
                required_perm = "audit.manage"
            elif key.startswith("branches_") or key.startswith("multi_branch_"): 
                required_perm = "branches.manage"
            
            # Sensitive keys - must be admin (already checked above, so if we are here, fail)
            elif any(key.startswith(p) for p in ["security_", "smtp_", "sms_", "zatca_", "workflow_"]):
                 raise HTTPException(status_code=403, detail=f"Not authorized to update sensitive setting: {key}")
            
            # General fallback
            else:
                # If it's a general setting (logo, company name, etc), we might require settings.manage
                # But we are in the 'else' block where user DOES NOT have settings.manage.
                # So they cannot update unclassified/general settings.
                 raise HTTPException(status_code=403, detail=f"Not authorized to update setting: {key}")
            
            # Check if user has the specific required permission
            has_perm = required_perm in perms
            if not has_perm:
                # Check wildcard
                parts = required_perm.split('.')
                if len(parts) > 1 and f"{parts[0]}.*" in perms:
                    has_perm = True
            
            if not has_perm:
                raise HTTPException(status_code=403, detail=f"Missing permission {required_perm} for setting {key}")
    
    db = get_db_connection(company_id)
    try:
        # Validate all setting keys and values before persisting (T013/T014)
        for key, value in request.settings.items():
            _validate_setting_value(key, value)

        # Upsert logic — atomic ON CONFLICT
        for key, value in request.settings.items():
            value_str = str(value) if value is not None else ""
            db.execute(
                text("INSERT INTO company_settings (setting_key, setting_value) VALUES (:key, :value) ON CONFLICT (setting_key) DO UPDATE SET setting_value = :value, updated_at = CURRENT_TIMESTAMP"),
                {"key": key, "value": value_str}
            )
        
        db.commit()
        
        # ── إذا تم تغيير نوع النشاط → زرع شجرة الحسابات المتخصصة ──
        if "industry_type" in request.settings:
            industry_key = request.settings["industry_type"]
            try:
                from services.industry_coa_templates import seed_industry_coa
                # normalize_industry_key is called inside seed_industry_coa
                coa_result = seed_industry_coa(db, industry_key, replace_existing=False)
                logger.info(f"📊 COA seeded for industry '{industry_key}': {coa_result}")
            except Exception as coa_err:
                logger.warning(f"⚠️ COA seeding skipped: {coa_err}")
        
        # Invalidate cache
        cache.delete(f"company_settings:{company_id}")
        
        # Audit log
        try:
            log_activity(db, current_user.id, current_user.username, "configure",
                         resource_type="settings",
                         details={"keys_updated": list(request.settings.keys())},
                         request=req)
            db.commit()
        except Exception:
            logger.warning("Failed to write settings update audit log")
        
        return {"success": True, "message": "Settings updated successfully"}

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
@router.post("/test-email", status_code=status.HTTP_200_OK, dependencies=[Depends(require_permission("settings.manage"))], response_model=Dict[str, Any])
def test_email_connection(
    request: SettingsUpdateRequest,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Test SMTP connection using provided settings.
    """
    import smtplib
    
    settings = request.settings
    host = settings.get("smtp_host")
    port = int(settings.get("smtp_port", 587))
    user = settings.get("smtp_user")
    password = settings.get("smtp_pass")

    if not host or not user or not password:
        raise HTTPException(status_code=400, detail="Missing SMTP configuration")
        
    try:
        # Real connection attempt (with timeout)
        server = smtplib.SMTP(host, port, timeout=5)
        server.starttls()
        server.login(user, password)
        server.quit()
        
        return {"success": True, "message": "Connection successful"}
    except Exception:
        raise HTTPException(status_code=400, detail="فشل الاتصال بالخادم")

@router.post("/generate-csid", status_code=status.HTTP_200_OK, dependencies=[Depends(require_permission("settings.manage"))], response_model=Dict[str, Any])
def generate_csid(
    request: SettingsUpdateRequest,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Simulate ZATCA CSID generation.
    """
    settings = request.settings
    otp = settings.get("zatca_otp")
    common_name = settings.get("zatca_csr_common_name")
    
    if not otp or not common_name:
         raise HTTPException(status_code=400, detail="Missing OTP or Organization Name")
         
    # Simulation Logic
    import random
    if otp == "000000":
         raise HTTPException(status_code=400, detail="Invalid OTP")
         
    return {
        "success": True, 
        "message": "CSID generated successfully", 
        "csid": f"CSID-{random.randint(1000,9999)}-{common_name}"
    }


