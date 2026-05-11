"""
AMAN ERP - Companies Router
"""

from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Body
from utils.i18n import http_error
from sqlalchemy import text
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import (
    get_system_db, 
    generate_company_id,
    create_company_database,
    create_company_tables,
    initialize_company_default_data,
    get_db_connection
)
from schemas import CompanyCreateRequest, CompanyCreateResponse, CompanyListResponse, CompanyListItem, CompanyUpdateRequest
from utils.permissions import require_permission
from utils.limiter import limiter
from utils.audit import log_activity
from utils.sql_builder import validate_update_keys

router = APIRouter(prefix="/companies", tags=["Companies"])
logger = logging.getLogger(__name__)


def _cleanup_company_database(db_name: str, db_user: str) -> None:
    from database import _ddl_engine

    with _ddl_engine.connect() as ddl_conn:
        ddl_conn.execute(
            text("""
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = :db_name
                  AND pid <> pg_backend_pid()
            """),
            {"db_name": db_name},
        )
        ddl_conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        ddl_conn.execute(text(f'DROP USER IF EXISTS {db_user}'))


from fastapi import Request
from config import settings as _settings

_REGISTER_RATE_LIMIT = "100/hour" if _settings.APP_ENV == "development" else "3/hour"

@router.post("/register", response_model=CompanyCreateResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(_REGISTER_RATE_LIMIT)
async def register_new_company(request_body: CompanyCreateRequest, request: Request):
    """
    تسجيل شركة جديدة - company_id يُنشأ تلقائياً
    
    يتم تنفيذ:
    1. توليد company_id فريد (8 أحرف)
    2. إنشاء قاعدة بيانات PostgreSQL مستقلة
    3. إنشاء 91 جدول
    4. تهيئة البيانات الافتراضية
    5. إنشاء حساب المدير
    """
    db = get_system_db()
    
    try:
        # Check if email exists
        existing = db.execute(
            text("SELECT 1 FROM system_companies WHERE email = :email"),
            {"email": request_body.email}
        ).fetchone()
        
        if existing:
            raise HTTPException(**http_error(400, "email_already_used", request))
        
        # Generate unique company_id
        company_id = generate_company_id()
        max_attempts = 10
        attempts = 0
        
        while db.execute(
            text("SELECT 1 FROM system_companies WHERE id = :id"),
            {"id": company_id}
        ).fetchone() and attempts < max_attempts:
            company_id = generate_company_id()
            attempts += 1
        
        if attempts >= max_attempts:
            raise HTTPException(**http_error(500, "unique_id_generation_failed", request))
        
        logger.info(f"🆔 Generated company_id: {company_id}")
        
        # SEC-FIX-007: Validate identifiers before DDL operations
        from utils.sql_safety import validate_aman_identifier
        
        # Create database
        success, message, db_name, db_user = create_company_database(company_id, request_body.admin_password)
        
        if not success:
            raise HTTPException(**http_error(500, "database_creation_failed", request))
        
        # Validate generated identifiers
        validate_aman_identifier(db_name, "database name")
        validate_aman_identifier(db_user, "database user")
        
        try:
            # Create all 91 tables
            success, message = create_company_tables(company_id, request_body.currency)
            if not success:
                _cleanup_company_database(db_name, db_user)
                logger.error("Failed to create company tables: %s", message)
                raise HTTPException(**http_error(500, "tables_creation_failed", request))
            
            # Initialize default data
            success, message = initialize_company_default_data(
                company_id,
                request_body.admin_username,
                request_body.admin_email,
                request_body.admin_password,
                request_body.admin_full_name,
                request_body.timezone,
                request_body.currency,
                request_body.country
            )
            
            if not success:
                logger.warning(f"⚠️ Warning: {message}")
            
            # Fetch template modules
            enabled_modules = None
            industry_key = 'general'  # default
            if request_body.template_id:
                tpl = db.execute(
                    text("SELECT enabled_modules, key FROM industry_templates WHERE id = :id"),
                    {"id": request_body.template_id}
                ).fetchone()
                if tpl:
                    enabled_modules = tpl[0]
                    industry_key = tpl[1]
            
            if not enabled_modules:
                tpl = db.execute(text("SELECT enabled_modules FROM industry_templates WHERE key = 'general'")).fetchone()
                if tpl:
                    enabled_modules = tpl[0]
                industry_key = 'general'

            import json
            enabled_modules_json = json.dumps(enabled_modules) if enabled_modules else None

            # Register in system database
            db.execute(text("""
                INSERT INTO system_companies 
                (id, company_name, company_name_en, commercial_registry, tax_number, 
                 phone, email, address, database_name, database_user, currency, 
                 status, plan_type, template_id, enabled_modules, created_at, activated_at)
                VALUES 
                (:id, :name, :name_en, :registry, :tax, :phone, :email, :address, 
                 :db_name, :db_user, :currency, 'active', :plan, :tpl_id, :modules, :now, :now)
            """), {
                "id": company_id,
                "name": request_body.company_name,
                "name_en": request_body.company_name_en,
                "registry": request_body.commercial_registry,
                "tax": request_body.tax_number,
                "phone": request_body.phone,
                "email": request_body.email,
                "address": request_body.address,
                "db_name": db_name,
                "db_user": db_user,
                "currency": request_body.currency,
                "plan": request_body.plan_type,
                "tpl_id": request_body.template_id,
                "modules": enabled_modules_json,
                "now": datetime.now(timezone.utc)
            })

            
            db.commit()
            
            # ── زرع شجرة الحسابات المتخصصة حسب نوع النشاط ──
            try:
                from services.industry_coa_templates import seed_industry_coa
                company_db = get_db_connection(company_id)
                try:
                    coa_result = seed_industry_coa(company_db, industry_key, replace_existing=False)
                    logger.info(f"📊 COA seeded for '{industry_key}': core={coa_result['core']}, industry={coa_result['industry']}")
                    # NOTE: industry_type is intentionally NOT saved here.
                    # It will be set when the user completes the IndustrySetup wizard
                    # (via POST /settings/bulk), ensuring new companies always go through the wizard.
                    company_db.commit()
                finally:
                    company_db.close()
            except Exception as coa_err:
                logger.warning(f"⚠️ COA seeding during company creation skipped: {coa_err}")
            
            logger.info(f"✅ Created company: {request_body.company_name} (ID: {company_id})")
            
            # Audit log for company creation (system-level)
            try:
                sys_db = get_system_db()
                try:
                    sys_db.execute(text("""
                        INSERT INTO system_activity_log (company_id, action_type, action_description, performed_by, ip_address, created_at)
                        VALUES (:cid, :action, :desc, :user, :ip, NOW())
                    """), {
                        "cid": company_id,
                        "action": "company_created",
                        "desc": f"Company '{request_body.company_name}' created",
                        "user": request_body.admin_username,
                        "ip": request.client.host if request else None,
                    })
                    sys_db.commit()
                finally:
                    sys_db.close()
            except Exception:
                logger.warning("Failed to write company creation audit log")
            
            return CompanyCreateResponse(
                success=True,
                company_id=company_id,
                company_name=request_body.company_name,
                database_name=db_name,
                message=f"تم إنشاء الشركة بنجاح. معرف الشركة: {company_id}",
                admin_username=request_body.admin_username,
                created_at=datetime.now(timezone.utc)
            )
            
        except Exception:
            logger.exception("Error in register_new_company")
            
            # SEC-FIX-009/010: Don't write errors to file in web root, don't leak details to client
            db.rollback()
            try:
                _cleanup_company_database(db_name, db_user)
            except Exception as cleanup_err:
                logger.error(f"Failed to cleanup after company creation failure: {cleanup_err}")
            raise HTTPException(**http_error(500, "company_creation_failed", request))

    
    finally:
        db.close()


@router.get("/list", response_model=CompanyListResponse, dependencies=[Depends(require_permission("admin.companies"))])
def list_companies(
    skip: int = 0,
    limit: int = 100,
    status_filter: Optional[str] = None,
    search: Optional[str] = None
):
    """عرض قائمة الشركات مع دعم البحث والترقيم"""
    db = get_system_db()
    
    try:
        # Build filters
        base_query = "FROM system_companies WHERE 1=1"
        params = {"limit": limit, "skip": skip}
        
        if status_filter:
            base_query += " AND status = :status"
            params["status"] = status_filter
            
        if search:
            base_query += " AND (company_name ILIKE :search OR email ILIKE :search OR database_name ILIKE :search)"
            params["search"] = f"%{search}%"

        # 1. Total count query
        count_query = f"SELECT count(*) {base_query}"
        total = db.execute(text(count_query), params).scalar() or 0

        # 2. Data query
        query = f"SELECT id, company_name, database_name, email, status, plan_type, created_at {base_query}"
        query += " ORDER BY created_at DESC LIMIT :limit OFFSET :skip"
        
        result = db.execute(text(query), params).fetchall()
        
        companies = [
            CompanyListItem(
                id=row[0],
                company_name=row[1],
                database_name=row[2],
                email=row[3],
                status=row[4],
                plan_type=row[5],
                created_at=row[6]
            )
            for row in result
        ]
        
        return {
            "companies": companies,
            "total": total
        }
    finally:
        db.close()


from routers.auth import get_current_user
from utils.tx import transactional
from schemas import UserResponse


# ===================== Public Templates (MUST be before /{company_id}) =====================

@router.get("/public/templates", response_model=List[Dict[str, Any]])
def get_industry_templates():
    """عرض قوالب الأنشطة المتاحة للجمهور"""
    from database import get_system_db
    db = get_system_db()
    try:
        result = db.execute(text(
            "SELECT id, key, name, name_ar, icon, description, description_ar, enabled_modules "
            "FROM industry_templates ORDER BY id"
        )).fetchall()
        return [
            {
                "id": row[0],
                "key": row[1],
                "name": row[2],
                "name_ar": row[3],
                "icon": row[4],
                "description": row[5],
                "description_ar": row[6],
                "enabled_modules": row[7] if row[7] else []
            }
            for row in result
        ]
    except Exception as e:
        logger.error(f"Error in get_industry_templates: {str(e)}")
        return []
    finally:
        db.close()


# ===================== Enabled Modules Management (MUST be before /{company_id}) =====================

@router.get("/modules", response_model=Dict[str, Any])
def get_enabled_modules(current_user=Depends(get_current_user)):
    """الحصول على الوحدات المفعّلة"""
    # Read from system_companies (source of truth, same as login)
    db = get_system_db()
    try:
        row = db.execute(text(
            "SELECT enabled_modules FROM system_companies WHERE id = :cid"
        ), {"cid": current_user.company_id}).fetchone()
        if row and row[0]:
            import json
            modules = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            return modules
        return []
    except Exception as e:
        logger.error(f"Error getting modules: {e}")
        return []
    finally:
        db.close()


@router.put("/modules", dependencies=[Depends(require_permission("settings.manage"))], response_model=Dict[str, Any])
def update_enabled_modules(request: Request, modules: Any = Body(...), current_user=Depends(get_current_user)):
    """تحديث الوحدات المفعّلة — يقبل list أو dict"""
    import json

    def normalize_modules(raw: Any) -> List[str]:
        """Normalize incoming modules payload to a clean unique list of module keys."""
        if raw is None:
            return []

        value = raw
        if isinstance(value, str):
            # Stored DB value may be JSON string or comma-separated text.
            try:
                value = json.loads(value)
            except Exception:
                value = [p.strip() for p in value.split(",") if p and p.strip()]

        if isinstance(value, dict):
            if isinstance(value.get("enabled_modules"), list):
                value = value["enabled_modules"]
            else:
                # Fallback for payloads like {"sales": true, "hr": false}
                value = [k for k, v in value.items() if isinstance(v, bool) and v]

        if isinstance(value, (set, tuple)):
            value = list(value)

        if not isinstance(value, list):
            return []

        cleaned = [str(m).strip() for m in value if m is not None and str(m).strip()]
        # Preserve order while removing duplicates.
        return list(dict.fromkeys(cleaned))

    old_modules: List[str] = []
    new_modules: List[str] = normalize_modules(modules)
    modules_json = json.dumps(new_modules)
    
    # 1. تحديث في system_companies (المصدر الرئيسي — يقرأها Login و GET /modules)
    sys_db = get_system_db()
    try:
        current_row = sys_db.execute(text(
            "SELECT enabled_modules FROM system_companies WHERE id = :cid"
        ), {"cid": current_user.company_id}).fetchone()
        old_modules = normalize_modules(current_row[0] if current_row else None)

        sys_db.execute(text(
            "UPDATE system_companies SET enabled_modules = CAST(:m AS jsonb) WHERE id = :cid"
        ), {"m": modules_json, "cid": current_user.company_id})
        sys_db.commit()
    except Exception:
        sys_db.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        sys_db.close()
    
    # 2. نسخة احتياطية في company_settings (key-value)
    with transactional(current_user.company_id) as db:
        try:
            exists = db.execute(text(
                "SELECT 1 FROM company_settings WHERE setting_key = 'enabled_modules'"
            )).fetchone()
            if exists:
                db.execute(text(
                    "UPDATE company_settings SET setting_value = :m WHERE setting_key = 'enabled_modules'"
                ), {"m": modules_json})
            else:
                db.execute(text(
                    "INSERT INTO company_settings (setting_key, setting_value) VALUES ('enabled_modules', :m)"
                ), {"m": modules_json})
        except Exception as e:
            logger.warning(f"Failed to update company_settings.enabled_modules: {e}")
            pass
    
    # Audit log for module update
    try:
        added_modules = [m for m in new_modules if m not in old_modules]
        removed_modules = [m for m in old_modules if m not in new_modules]
        audit_db = get_db_connection(current_user.company_id)
        try:
            log_activity(audit_db, current_user.id, current_user.username, "update_modules",
                         resource_type="company", details={
                             "modules": new_modules,
                             "modules_added": added_modules,
                             "modules_removed": removed_modules,
                             "modules_before_count": len(old_modules),
                             "modules_after_count": len(new_modules),
                         })
            audit_db.commit()
        finally:
            audit_db.close()
    except Exception:
        logger.warning("Failed to write module update audit log")
    
    return {
        "message": i18n_message("modules_updated_success", request),
        "modules": new_modules,
        "modules_added": added_modules,
        "modules_removed": removed_modules,
    }


# ===================== Company Details (catch-all path param) =====================

@router.get("/{company_id}", response_model=Dict[str, Any])
def get_company(
    company_id: str,
    current_user: UserResponse = Depends(get_current_user)
):
    """عرض تفاصيل شركة - متاح للمدير أو للمستخدمين التابعين لنفس الشركة"""
    # If user is NOT system admin AND requesting a different company -> Forbidden
    if current_user.company_id != company_id:
        if current_user.role != "system_admin":
             raise HTTPException(**http_error(403, "access_denied"))

    db = get_system_db()
    
    try:
        result = db.execute(
            text("""
                SELECT id, company_name, company_name_en, email, phone, address,
                       commercial_registry, tax_number,
                       status, plan_type, currency, created_at, activated_at, logo_url
                FROM system_companies WHERE id = :id
            """),
            {"id": company_id}
        ).fetchone()
        
        if not result:
            raise HTTPException(**http_error(status.HTTP_404_NOT_FOUND, "company_not_found"))
        
        return {
            "id": result[0],
            "company_name": result[1],
            "company_name_en": result[2],
            "email": result[3],
            "phone": result[4],
            "address": result[5],
            "commercial_registry": result[6],
            "tax_number": result[7],
            "status": result[8],
            "plan_type": result[9],
            "currency": result[10],
            "created_at": result[11],
            "activated_at": result[12],
            "logo_url": result[13]
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception(f"Error in get_company {company_id}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
@router.put("/update/{company_id}", dependencies=[Depends(require_permission("settings.manage"))], response_model=Dict[str, Any])
def update_company(
    company_id: str,
    request: CompanyUpdateRequest,
    req: Request = None,
    current_user: UserResponse = Depends(get_current_user)
):
    """Update company details"""
    # Only System Admin OR Company Admin can update
    is_sys_admin = current_user.role == "system_admin"
    is_own_company = current_user.company_id == company_id
    
    # Check if user is an admin within their own company
    is_company_admin = current_user.role in ["company_admin", "admin", "superuser"]
    
    # Allow if System Admin OR (Own Company AND Company Admin)
    allowed = is_sys_admin or (is_own_company and is_company_admin)
    
    if not allowed:
        raise HTTPException(**http_error(403, "forbidden_admin_access_required"))

    db = get_system_db()
    try:
        # Check if company exists
        existing = db.execute(
            text("SELECT id FROM system_companies WHERE id = :id"),
            {"id": company_id}
        ).fetchone()
        
        if not existing:
            raise HTTPException(**http_error(404, "company_not_found"))

        # Prepare update query
        update_data = request.dict(exclude_unset=True)
        if not update_data:
            return {"success": True, "message": i18n_message("no_changes_provided", request)}

        validate_update_keys(update_data.keys())  # T2.2 defense-in-depth
        set_clause = ", ".join([f"{k} = :{k}" for k in update_data.keys()])
        update_data["id"] = company_id
        
        db.execute(
            text(f"UPDATE system_companies SET {set_clause} WHERE id = :id"),
            update_data
        )
        db.commit()
        
        # Audit log
        try:
            db.execute(text("""
                INSERT INTO system_activity_log (company_id, action_type, action_description, performed_by, ip_address, created_at)
                VALUES (:cid, :action, :desc, :user, :ip, NOW())
            """), {
                "cid": company_id,
                "action": "company_updated",
                "desc": f"Company updated: {', '.join(request.dict(exclude_unset=True).keys())}",
                "user": current_user.username,
                "ip": req.client.host if req else None,
            })
            db.commit()
        except Exception:
            logger.warning("Failed to write company update audit log")
        
        return {"success": True, "message": i18n_message("company_updated", request)}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        logger.exception(f"Error updating company {company_id}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()

@router.post("/upload-logo/{company_id}", dependencies=[Depends(require_permission("settings.edit"))], response_model=Dict[str, Any])
async def upload_company_logo(
    company_id: str,
    file: UploadFile = File(...),
    current_user: UserResponse = Depends(get_current_user)
):
    """رفع شعار الشركة"""
    from database import SessionLocal
    if current_user.company_id != company_id and current_user.role != "system_admin":
        raise HTTPException(**http_error(403, "forbidden"))

    from utils.sql_safety import (
        validate_file_size,
        validate_file_extension,
        validate_file_mime_and_signature,
        MAX_LOGO_SIZE,
        ALLOWED_IMAGE_EXTENSIONS,
    )

    content = await file.read()
    validate_file_extension(file.filename, ALLOWED_IMAGE_EXTENSIONS, "الشعار")
    validate_file_size(content, MAX_LOGO_SIZE, "الشعار")
    file_ext = validate_file_mime_and_signature(file.filename, file.content_type, content, "الشعار")
        
    filename = f"logo_{company_id}{file_ext}"
    uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads", "logos")
    os.makedirs(uploads_dir, exist_ok=True)
    file_path = os.path.join(uploads_dir, filename)

    try:
        with open(file_path, "wb") as buffer:
            buffer.write(content)
        
        # Save to company_settings
        from database import get_db_connection
        with transactional(company_id) as db:
            logo_url = f"/uploads/logos/{filename}"
            # Check if key exists
            exists = db.execute(text("SELECT 1 FROM company_settings WHERE setting_key = 'company_logo'")).fetchone()
            if exists:
                db.execute(text("UPDATE company_settings SET setting_value = :val WHERE setting_key = 'company_logo'"), {"val": logo_url})
            else:
                db.execute(text("INSERT INTO company_settings (setting_key, setting_value) VALUES ('company_logo', :val)"), {"val": logo_url})
            
            # Also update system_companies if possible (for global view)
            try:
                sys_db = SessionLocal()
                sys_db.execute(text("UPDATE system_companies SET logo_url = :url WHERE id = :id"), {"url": logo_url, "id": company_id})
                sys_db.commit()
                sys_db.close()
            except Exception:
                pass  # logo_url might not exist yet in system_companies

            # Commit to company db
            
            # Audit log
            try:
                log_activity(db, current_user.id, current_user.username, "upload_logo",
                             resource_type="company", resource_id=company_id,
                             details={"logo_url": logo_url})
            except Exception:
                logger.warning("Failed to write logo upload audit log")
            
            return {"success": True, "logo_url": logo_url}
            
    except Exception:
        logger.exception("Error uploading logo")
        raise HTTPException(**http_error(500, "internal_error"))

