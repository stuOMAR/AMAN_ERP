from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from typing import Any, Dict, List
from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from schemas import BranchCreate, BranchResponse
from utils.permissions import require_permission
from utils.audit import log_activity
from utils.i18n import http_error
import logging
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/branches",
    tags=["branches"]
)

@router.get("", response_model=List[BranchResponse], dependencies=[Depends(require_permission("branches.view"))])
def list_branches(
    request: Request,
    current_user = Depends(get_current_user)
):
    """List all branches for the current company"""
    company_id = getattr(current_user, 'company_id', None) or (current_user.get('company_id') if isinstance(current_user, dict) else None)
    if not company_id:
        if getattr(current_user, 'role', None) == 'system_admin' or (isinstance(current_user, dict) and current_user.get('role') == 'system_admin'):
            return []
        raise HTTPException(**http_error(400, "user_not_associated_with_any_company", request))
        
    with transactional(company_id) as conn:
        try:
            # Robust user info extraction
            if isinstance(current_user, dict):
                user_id = current_user.get('id')
                user_role = current_user.get('role', 'user')
            else:
                user_id = getattr(current_user, 'id', None)
                user_role = getattr(current_user, 'role', 'user')
    
            if user_role in ['admin', 'superuser', 'system_admin']:
                query = text("""
                    SELECT id, branch_code, branch_name, branch_name_en, address, 
                           city, country, country_code, default_currency, phone, email, is_active, is_default, created_at
                    FROM branches
                    ORDER BY id
                """)
                result = conn.execute(query).fetchall()
            else:
                # Filter by allowed branches
                query = text("""
                    SELECT b.id, b.branch_code, b.branch_name, b.branch_name_en, b.address, 
                           b.city, b.country, b.country_code, b.default_currency, b.phone, b.email, b.is_active, b.is_default, b.created_at
                    FROM branches b
                    JOIN user_branches ub ON b.id = ub.branch_id
                    WHERE ub.user_id = :uid
                    ORDER BY b.id
                """)
                result = conn.execute(query, {"uid": user_id}).fetchall()
                
                if not result:
                    return []
            
            branches = []
            for row in result:
                branches.append({
                    "id": row.id,
                    "branch_code": row.branch_code,
                    "branch_name": row.branch_name,
                    "branch_name_en": row.branch_name_en,
                    "address": row.address,
                    "city": row.city,
                    "country": row.country,
                    "country_code": getattr(row, 'country_code', None),
                    "default_currency": getattr(row, 'default_currency', None),
                    "phone": row.phone,
                    "email": row.email,
                    "is_active": row.is_active,
                    "is_default": row.is_default,
                    "created_at": row.created_at
                })
            return branches
        except Exception:
            logger.exception("Operation failed")
            raise HTTPException(**http_error(500, "internal_error", request))

@router.post("", response_model=BranchResponse)
def create_branch(
    request: Request,
    branch: BranchCreate,
    current_user = Depends(require_permission("branches.manage"))
):
    """Create a new branch"""
    with transactional(current_user.company_id) as conn:
        try:
            # Validate country_code — required for tax calculation
            if not branch.country_code or not branch.country_code.strip():
                raise HTTPException(**http_error(400, "branch_country_code_required", request))
    
            # Check if this is the first branch
            count_res = conn.execute(text("SELECT COUNT(*) FROM branches")).scalar()
            is_first = (count_res == 0)
            
            # Auto-generate branch code if empty
            if not branch.branch_code or not branch.branch_code.strip():
                max_code = conn.execute(text(
                    "SELECT MAX(CAST(SUBSTRING(branch_code FROM '[0-9]+') AS INT)) FROM branches WHERE branch_code ~ '^BR-[0-9]+$'"
                )).scalar() or 0
                branch.branch_code = f"BR-{str(max_code + 1).zfill(3)}"
            
            # Check duplicate code
            existing = conn.execute(
                text("SELECT 1 FROM branches WHERE branch_code = :code"),
                {"code": branch.branch_code}
            ).fetchone()
            if existing:
                raise HTTPException(**http_error(400, "branch_code_already_exists", request))
            
            query = text("""
                INSERT INTO branches (
                    branch_code, branch_name, branch_name_en, address, 
                    city, country, country_code, default_currency, phone, email, is_active, is_default
                ) VALUES (
                    :code, :name, :name_en, :address, 
                    :city, :country, :country_code, :default_currency, :phone, :email, :active, :is_default
                ) RETURNING id, created_at, is_default
            """)
            
            params = {
                "code": branch.branch_code,
                "name": branch.branch_name,
                "name_en": branch.branch_name_en,
                "address": branch.address,
                "city": branch.city,
                "country": branch.country,
                "country_code": branch.country_code,
                "default_currency": branch.default_currency,
                "phone": branch.phone,
                "email": branch.email,
                "active": branch.is_active,
                "is_default": is_first  # Make first branch default
            }
            
            result = conn.execute(query, params).fetchone()
            branch_id = result.id
            
            # Auto-register currency if not already in currencies table
            if branch.default_currency and branch.default_currency.strip():
                try:
                    conn.execute(
                        text("""
                            INSERT INTO currencies (code, name, is_active)
                            VALUES (:code, :name, TRUE)
                            ON CONFLICT (code) DO NOTHING
                        """),
                        {"code": branch.default_currency.strip().upper(), "name": branch.default_currency.strip().upper()}
                    )
                except Exception:
                    pass
            
            # 2. Link creator to the branch in user_branches
            # Extract user_id robustly
            if isinstance(current_user, dict):
                user_id = current_user.get('id')
            else:
                user_id = getattr(current_user, 'id', None)
                
            if user_id:
                conn.execute(
                    text("INSERT INTO user_branches (user_id, branch_id) VALUES (:uid, :bid) ON CONFLICT DO NOTHING"),
                    {"uid": user_id, "bid": branch_id}
                )
                
            
            # Audit log
            if user_id:
                try:
                    username = current_user.get('username', '') if isinstance(current_user, dict) else getattr(current_user, 'username', '')
                    log_activity(conn, user_id, username, "create",
                                 resource_type="branch", resource_id=str(branch_id),
                                 details={"branch_code": branch.branch_code, "branch_name": branch.branch_name},
                                 branch_id=branch_id)
                except Exception:
                    logger.warning("Failed to write branch create audit log")
            
            # Construct response
            response_data = branch.model_dump()
            response_data["id"] = branch_id
            response_data["created_at"] = result.created_at
            response_data["is_default"] = result.is_default
            
            return response_data
            
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Operation failed")
            raise HTTPException(**http_error(500, "internal_error", request))

@router.put("/{branch_id}", response_model=BranchResponse)
def update_branch(
    request: Request,
    branch_id: int,
    branch: BranchCreate,
    current_user = Depends(require_permission("branches.manage"))
):
    """Update a branch"""
    with transactional(current_user.company_id) as conn:
        try:
            # Check existence
            existing = conn.execute(
                text("SELECT 1 FROM branches WHERE id = :id"),
                {"id": branch_id}
            ).fetchone()
            
            if not existing:
                raise HTTPException(**http_error(404, "branch_not_found", request))
    
            # Validate country_code — required for tax calculation
            if not branch.country_code or not branch.country_code.strip():
                raise HTTPException(**http_error(400, "branch_country_code_required", request))
    
            # Check duplicate code if changed
            if branch.branch_code:
                duplicate = conn.execute(
                    text("SELECT 1 FROM branches WHERE branch_code = :code AND id != :id"),
                    {"code": branch.branch_code, "id": branch_id}
                ).fetchone()
                if duplicate:
                    raise HTTPException(**http_error(400, "branch_code_already_used_by_another_branch", request))
    
            query = text("""
                UPDATE branches SET
                    branch_code = :code,
                    branch_name = :name,
                    branch_name_en = :name_en,
                    address = :address,
                    city = :city,
                    country = :country,
                    country_code = :country_code,
                    default_currency = :default_currency,
                    phone = :phone,
                    email = :email,
                    is_active = :active
                WHERE id = :id
                RETURNING id, created_at, is_default
            """)
            
            params = {
                "id": branch_id,
                "code": branch.branch_code,
                "name": branch.branch_name,
                "name_en": branch.branch_name_en,
                "address": branch.address,
                "city": branch.city,
                "country": branch.country,
                "country_code": branch.country_code,
                "default_currency": branch.default_currency,
                "phone": branch.phone,
                "email": branch.email,
                "active": branch.is_active
            }
            
            result = conn.execute(query, params).fetchone()
            
            # Auto-register currency if not already in currencies table
            if branch.default_currency and branch.default_currency.strip():
                try:
                    conn.execute(
                        text("""
                            INSERT INTO currencies (code, name, is_active)
                            VALUES (:code, :name, TRUE)
                            ON CONFLICT (code) DO NOTHING
                        """),
                        {"code": branch.default_currency.strip().upper(), "name": branch.default_currency.strip().upper()}
                    )
                except Exception:
                    pass
            
            # Audit log
            try:
                user_id = current_user.get('id') if isinstance(current_user, dict) else getattr(current_user, 'id', None)
                username = current_user.get('username', '') if isinstance(current_user, dict) else getattr(current_user, 'username', '')
                if user_id:
                    log_activity(conn, user_id, username, "update",
                                 resource_type="branch", resource_id=str(branch_id),
                                 details={"branch_code": branch.branch_code, "branch_name": branch.branch_name},
                                 branch_id=branch_id)
            except Exception:
                logger.warning("Failed to write branch update audit log")
            
            response_data = branch.model_dump()
            response_data["id"] = result.id
            response_data["created_at"] = result.created_at
            response_data["is_default"] = result.is_default
            
            return response_data
            
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Operation failed")
            raise HTTPException(**http_error(500, "internal_error", request))

@router.delete("/{branch_id}", response_model=Dict[str, Any])
def delete_branch(
    request: Request,
    branch_id: int,
    current_user = Depends(require_permission("branches.manage"))
):
    """Delete a branch (soft delete or check dependencies)"""
    conn = get_db_connection(current_user.company_id)
    try:
        # Start transaction
        # Check if default
        check = conn.execute(
            text("SELECT is_default, is_active FROM branches WHERE id = :id"),
            {"id": branch_id}
        ).fetchone()
        
        if not check:
            raise HTTPException(**http_error(404, "branch_not_found", request))
            
        if check.is_default:
            raise HTTPException(**http_error(400, "cannot_delete_the_default_branch", request))
            
        if check.is_active:
            raise HTTPException(**http_error(400, "cannot_delete_active_branch", request))
        
        # T011: Check for dependent records across all tables with branch_id FK
        fk_query = text("""
            SELECT conname, conrelid::regclass::text AS tbl,
                   (SELECT string_agg(a.attname, ',')
                    FROM pg_attribute a
                    WHERE a.attrelid = conrelid AND a.attnum = ANY(conkey)) AS col
            FROM pg_constraint
            WHERE confrelid = 'branches'::regclass
              AND contype = 'f'
              AND conrelid::regclass::text NOT IN (
                  'user_branches', 'audit_logs', 'audit_logs_archive'
              )
        """)
        fk_tables = conn.execute(fk_query).fetchall()
        for fk in fk_tables:
            col = fk.col or 'branch_id'
            # Build WHERE clause for single or composite FK
            where_clause = ' AND '.join(f'{c} = :bid' for c in col.split(','))
            count = conn.execute(
                text(f'SELECT COUNT(*) FROM {fk.tbl} WHERE {where_clause}'),
                {"bid": branch_id}
            ).scalar() or 0
            if count > 0:
                raise HTTPException(**http_error(400, "branch_has_linked_records", request, count=count))
        
        # Clean up user_branches and detach audit_logs before deleting
        conn.execute(text("DELETE FROM user_branches WHERE branch_id = :bid"), {"bid": branch_id})
        
        # Disable trigger temporarily to allow orphaning the logs securely
        conn.execute(text("ALTER TABLE audit_logs DISABLE TRIGGER audit_logs_no_update"))
        conn.execute(text("UPDATE audit_logs SET branch_id = NULL WHERE branch_id = :bid"), {"bid": branch_id})
        conn.execute(text("ALTER TABLE audit_logs ENABLE TRIGGER audit_logs_no_update"))
            
        conn.execute(
            text("DELETE FROM branches WHERE id = :id"),
            {"id": branch_id}
        )
        
        # Audit log
        try:
            user_id = current_user.get('id') if isinstance(current_user, dict) else getattr(current_user, 'id', None)
            username = current_user.get('username', '') if isinstance(current_user, dict) else getattr(current_user, 'username', '')
            if user_id:
                log_activity(conn, user_id, username, "delete",
                             resource_type="branch", resource_id=str(branch_id),
                             details={"branch_id": branch_id})
        except Exception:
            logger.warning("Failed to write branch delete audit log")
        
        conn.commit()
        return {"success": True, "message": i18n_message("branch_deleted", request)}
        
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        # Postgres Foreign Key violation will raise IntegrityError
        if "foreign key constraint" in str(e).lower():
            raise HTTPException(**http_error(400, "cannot_delete_branch_because_it_is_used_by_other_r", request))
        logger.exception("Operation failed")
        raise HTTPException(**http_error(500, "internal_error", request))
    finally:
        conn.close()
