"""system_completion sub-router — split from monolithic system_completion.py (T6.3).

Mounted under the parent router via system_completion/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response, Request
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

@router.post("/admin/backup", dependencies=[Depends(require_permission("admin"))],
             tags=["Backup"], response_model=Dict[str, Any])
def create_backup(request: Request, current_user: dict = Depends(get_current_user)):
    """إنشاء نسخة احتياطية لقاعدة بيانات الشركة (pg_dump)"""
    company_id = _u(current_user, "company_id")
    user_id = _u(current_user, "user_id")

    # SEC-FIX-021: Validate company_id before using in subprocess
    import re
    if not company_id or not re.match(r'^[a-f0-9]+$', company_id):
        raise HTTPException(**http_error(400, "invalid_company_id", request))

    from config import settings
    db_name = f"aman_{company_id}"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # SEC-FIX-022: Store backups outside the application directory
    backup_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "backups", company_id)
    os.makedirs(backup_dir, exist_ok=True)
    backup_file = os.path.join(backup_dir, f"{db_name}_{timestamp}.sql.gz")

    try:
        env = os.environ.copy()
        env["PGPASSWORD"] = settings.POSTGRES_PASSWORD

        cmd = [
            "pg_dump",
            "-h", settings.POSTGRES_HOST,
            "-p", str(settings.POSTGRES_PORT),
            "-U", settings.POSTGRES_USER,
            "-d", db_name,
            "--no-owner",
            "--no-privileges",
            "-Fc"  # Custom format (compressed)
        ]

        with open(backup_file, 'wb') as f:
            result = subprocess.run(cmd, env=env, stdout=f, stderr=subprocess.PIPE, timeout=300)

        if result.returncode != 0:
            error_msg = result.stderr.decode() if result.stderr else "Unknown error"
            # SEC-FIX-023: Log stderr server-side, don't leak to client
            logger.error(f"pg_dump failed for {db_name}: {error_msg}")
            raise HTTPException(**http_error(500, "backup_create_failed", request))

        file_size = os.path.getsize(backup_file)

        # Record in backup history
        with transactional(company_id) as db:
            db.execute(text("""
                INSERT INTO backup_history (
                    backup_type, file_name, file_size, file_path,
                    status, created_by
                ) VALUES ('full', :fn, :fs, :fp, 'completed', :uid)
            """), {
                "fn": os.path.basename(backup_file),
                "fs": file_size,
                "fp": backup_file,
                "uid": user_id
            })

            log_activity(db, user_id, _u(current_user, "username", ""),
                         "admin.backup.create", "backup",
                         os.path.basename(backup_file),
                         {"file_size_mb": round(file_size / (1024 * 1024), 2)})

        return {
            "message": i18n_message("backup_created_success", request),
            "file_name": os.path.basename(backup_file),
            "file_size_mb": round(file_size / (1024 * 1024), 2),
            "timestamp": timestamp
        }
    except HTTPException:
        raise
    except subprocess.TimeoutExpired:
        raise HTTPException(**http_error(500, "backup_timeout", request))
    except FileNotFoundError:
        raise HTTPException(**http_error(500, "pg_dump_not_available", request))
    except Exception as e:
        logger.error(f"Backup creation failed: {e}")
        raise HTTPException(**http_error(500, "backup_error", request))


@router.get("/admin/backups", dependencies=[Depends(require_permission("admin"))],
            tags=["Backup"], response_model=List[Dict[str, Any]])
def list_backups(current_user: dict = Depends(get_current_user)):
    """قائمة النسخ الاحتياطية"""
    company_id = _u(current_user, "company_id")
    with transactional(company_id) as db:
        try:
            rows = db.execute(text("""
                SELECT bh.*, cu.full_name as created_by_name
                FROM backup_history bh
                LEFT JOIN company_users cu ON cu.id = bh.created_by
                ORDER BY bh.id DESC
                LIMIT 50
            """)).fetchall()
            return [dict(r._mapping) for r in rows]
        except Exception:
            return []


@router.get("/admin/backup/{backup_id}/download",
            dependencies=[Depends(require_permission("admin"))], tags=["Backup"])
def download_backup(backup_id: int, request: Request, current_user: dict = Depends(get_current_user)):
    """تحميل نسخة احتياطية"""
    company_id = _u(current_user, "company_id")
    with transactional(company_id) as db:
        backup = db.execute(text(
            "SELECT * FROM backup_history WHERE id = :id"
        ), {"id": backup_id}).fetchone()

        if not backup:
            raise HTTPException(**http_error(404, "backup_not_found", request))

        if not os.path.exists(backup.file_path):
            raise HTTPException(**http_error(404, "backup_file_not_found", request))

        with open(backup.file_path, 'rb') as f:
            content = f.read()

        return Response(
            content=content,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename={backup.file_name}"}
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  7. PRINT TEMPLATE MANAGEMENT
#     إدارة قوالب الطباعة
# ═══════════════════════════════════════════════════════════════════════════════

