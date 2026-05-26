"""core sub-router — split from monolithic core.py (T6.3).

Mounted under the parent router via core/__init__.py.
"""
import logging
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from sqlalchemy import text
from routers.auth import get_current_user
from utils.permissions import require_permission
from database import get_db_connection
from utils.audit import log_activity
from schemas import UserResponse

logger = logging.getLogger(__name__)

router = APIRouter()

from .core import QCResultRecord  # noqa: E402

@router.post("/qc-checks/{qc_id}/record-result", dependencies=[Depends(require_permission("manufacturing.manage"))], response_model=Dict[str, Any])
def record_qc_result(
    qc_id: int,
    res: QCResultRecord,
    request: Request,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    تسجيل نتيجة فحص الجودة.
    إذا كانت النتيجة 'fail' وإجراء الفشل 'stop' → يُوقف أمر الإنتاج تلقائياً.
    """
    conn = get_db_connection(current_user.company_id)
    try:
        if res.result not in ("pass", "fail", "warning"):
            raise HTTPException(**http_error(400, "qc_result_invalid", request))

        qc = conn.execute(text("SELECT * FROM mfg_qc_checks WHERE id=:id AND is_deleted = false"), {"id": qc_id}).fetchone()
        if not qc:
            raise HTTPException(**http_error(404, "quality_check_not_found"))

        # Branch validation via production order
        from utils.permissions import validate_branch_access
        po = conn.execute(text("SELECT branch_id FROM production_orders WHERE id = :id"), {"id": qc.production_order_id}).fetchone()
        if po and po.branch_id:
            validate_branch_access(current_user, po.branch_id)

        conn.execute(text("""
            UPDATE mfg_qc_checks
            SET actual_value = :val, result = :result, notes = COALESCE(:notes, notes),
                checked_by = :uid, checked_at = NOW(), updated_at = NOW()
            WHERE id = :id
        """), {
            "val": res.actual_value, "result": res.result,
            "notes": res.notes, "uid": current_user.id, "id": qc_id
        })

        action_taken = None

        # If failed with "stop" action → mark order as needing QC review in notes
        if res.result == "fail" and qc.failure_action == "stop":
            conn.execute(text("""
                UPDATE production_orders
                SET notes = COALESCE(notes,'') || ' | [QC-STOP] فشل فحص: ' || :check_name,
                    updated_at = NOW()
                WHERE id = :oid
            """), {"check_name": qc.check_name, "oid": qc.production_order_id})
            action_taken = "qc_stop_flagged"

        conn.commit()

        log_activity(conn, user_id=current_user.id, username=current_user.username,
                     action="record_qc_result", resource_type="mfg_qc_checks",
                     resource_id=str(qc_id), details={"result": res.result},
                     request=request)
        return {
            "success": True,
            "result": res.result,
            "action_taken": action_taken,
            "message": (
                "تم تعليم أمر الإنتاج بفشل فحص الجودة — يستلزم مراجعة" if action_taken == "qc_stop_flagged"
                else f"تم تسجيل نتيجة الفحص: {res.result}"
            )
        }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error recording QC result: {e}")
        raise HTTPException(**http_error(500, "qc_record_failed", request))
    finally:
        conn.close()


@router.get("/qc-checks/failures", dependencies=[Depends(require_permission("manufacturing.view"))], response_model=List[Dict[str, Any]])
def get_qc_failures(current_user: UserResponse = Depends(get_current_user)):
    """قائمة فحوصات الجودة الفاشلة والمعلقة"""
    conn = get_db_connection(current_user.company_id)
    try:
        rows = conn.execute(text("""
            SELECT q.*, po.order_number, p.product_name,
                   u.full_name as checked_by_name
            FROM mfg_qc_checks q
            JOIN production_orders po ON q.production_order_id = po.id
            JOIN products p ON po.product_id = p.id
            LEFT JOIN company_users u ON q.checked_by = u.id
            WHERE q.result IN ('fail', 'pending') AND q.is_deleted = false
            ORDER BY q.created_at DESC
        """)).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
#  ACTUAL MANUFACTURING COSTING & VARIANCE ANALYSIS
#  التكلفة الفعلية للتصنيع — تحليل الانحرافات
# ═══════════════════════════════════════════════════════════════════════════════

