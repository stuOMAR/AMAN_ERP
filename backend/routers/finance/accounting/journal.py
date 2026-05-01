"""accounting sub-router — split from monolithic accounting.py (T6.3).

Mounted under the parent router via accounting/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Body, Request
from utils.i18n import http_error
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from sqlalchemy import text
from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
import logging
from datetime import date
from dateutil.relativedelta import relativedelta
from utils.cache import invalidate_company_cache
from decimal import Decimal, ROUND_HALF_UP
from utils.permissions import require_permission, validate_branch_access
from utils.audit import log_activity
from utils.accounting import get_base_currency
from services.gl_service import create_journal_entry as gl_create_journal_entry
from utils.fiscal_lock import check_fiscal_period_open
from schemas.accounting import AccountCreate, AccountUpdate, FiscalYearCreate, FiscalYearClose, FiscalYearReopen
from utils.cache import cache
from utils.limiter import limiter

logger = logging.getLogger(__name__)
_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')

def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')

router = APIRouter()

from .core import _D2, _D4, _dec

@router.post("/journal-entries", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("accounting.edit"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
async def create_journal_entry(
    request: Request,
    entry_data: dict,
    current_user: dict = Depends(get_current_user)
):
    """
    Create a new journal entry (Manual Entry)
    entry_data format:
    {
        "date": "2023-10-01",
        "description": "Opening Balance / Expense Payment",
        "reference": "REF123",
        "status": "posted" or "draft",   <-- NEW: defaults to "posted"
        "lines": [
            {"account_id": 1, "debit": 100, "credit": 0, "description": "Line desc", "cost_center_id": 5},
            {"account_id": 2, "debit": 0, "credit": 100, "description": "Line desc"}
        ]
    }
    Supports Idempotency-Key header to prevent duplicate entries on retries.
    """
    with transactional(current_user.company_id) as db:
        try:
            # Idempotency check (Constitution XXIII)
            idempotency_key = request.headers.get("Idempotency-Key")
            if idempotency_key:
                existing = db.execute(text("""
                    SELECT id, entry_number, status FROM journal_entries
                    WHERE idempotency_key = :key
                    LIMIT 1
                """), {"key": idempotency_key}).fetchone()
                if existing:
                    return {"success": True, "message": "قيد موجود مسبقاً (مفتاح تكرار)", "entry_number": existing.entry_number, "entry_id": existing.id, "status": existing.status, "idempotent": True}
    
            from services.gl_service import create_journal_entry as gl_create_journal_entry
    
            entry_status = entry_data.get("status", "posted")
    
            # Fiscal-period lock: block posting into a closed period.
            entry_date = entry_data.get("date")
            if not entry_date:
                raise HTTPException(status_code=400, detail="تاريخ القيد مطلوب")
            check_fiscal_period_open(db, entry_date)
    
            journal_id, entry_number = gl_create_journal_entry(
                db=db,
                company_id=current_user.company_id,
                date=entry_data.get("date"),
                description=entry_data.get("description", ""),
                lines=entry_data.get("lines", []),
                user_id=current_user.id,
                branch_id=entry_data.get("branch_id"),
                reference=entry_data.get("reference"),
                status=entry_status,
                currency=entry_data.get("currency"),
                exchange_rate=_dec(entry_data.get("exchange_rate", 1)),
                source="Manual",
                source_id=None,
                username=current_user.username,
                idempotency_key=idempotency_key,
            )
    
            invalidate_company_cache(str(current_user.company_id))
            
    
            # AUDIT LOG
            log_activity(
                db,
                user_id=current_user.id,
                username=current_user.username,
                action=f"accounting.journal.{'create' if entry_status == 'posted' else 'draft'}",
                resource_type="journal_entry",
                resource_id=entry_number,
                details={"description": entry_data["description"], "reference": entry_data.get("reference"), "status": entry_status},
                request=request,
                branch_id=entry_data.get("branch_id")
            )
    
            msg = "تم ترحيل القيد بنجاح" if entry_status == "posted" else "تم حفظ القيد كمسودة"
    
            # Notify admins on posted entries
            if entry_status == "posted":
                try:
                    db.execute(text("""
                        INSERT INTO notifications (user_id, type, title, message, link, is_read, created_at)
                        SELECT DISTINCT u.id, 'journal_entry', :title, :message, :link, FALSE, NOW()
                        FROM company_users u
                        WHERE u.is_active = TRUE AND u.role IN ('admin', 'superuser')
                        AND u.id != :current_uid
                    """), {
                        "title": "📝 تم ترحيل قيد يومية",
                        "message": f"تم ترحيل القيد {entry_number} — {entry_data.get('description', '')[:80]}",
                        "link": f"/accounting/journal/{journal_id}",
                        "current_uid": current_user.id
                    })
                    db.commit()
                except Exception:
                    pass
    
            return {"success": True, "message": msg, "entry_number": entry_number, "entry_id": journal_id, "status": entry_status}
            
        except HTTPException:
            raise
        except Exception as e:
            pass
            logger.error(f"Error creating journal: {str(e)}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))

# ============================================================
# Journal Entries Listing & Draft Workflow (ACC-002)
# ============================================================

@router.get("/journal-entries", dependencies=[Depends(require_permission("accounting.view"))], response_model=Dict[str, Any])
@limiter.limit("200/minute")
def list_journal_entries(
    request: Request,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    branch_id: Optional[int] = None,
    page: int = 1,
    limit: int = 50,
    current_user: dict = Depends(get_current_user)
):
    """قائمة القيود اليومية مع فلترة"""
    branch_id = validate_branch_access(current_user, branch_id)
    with transactional(current_user.company_id) as db:
        conditions = []
        params = {}

        # Branch filtering
        if branch_id:
            conditions.append("je.branch_id = :branch_id")
            params["branch_id"] = branch_id
        else:
            allowed_branches = getattr(current_user, 'allowed_branches', [])
            if allowed_branches and "*" not in getattr(current_user, 'permissions', []):
                conditions.append("je.branch_id = ANY(:allowed_branches)")
                params["allowed_branches"] = allowed_branches

        if search and search.strip() in ('draft', 'posted', 'voided'):
            conditions.append("je.status = :status_val")
            params["status_val"] = search.strip()

        if date_from:
            conditions.append("je.entry_date >= :date_from")
            params["date_from"] = date_from
        if date_to:
            conditions.append("je.entry_date <= :date_to")
            params["date_to"] = date_to

        if search:
            conditions.append("(je.entry_number ILIKE :search OR je.description ILIKE :search OR je.reference ILIKE :search)")
            params["search"] = f"%{search}%"

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # Count
        total = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT COUNT(*) FROM journal_entries je WHERE {where_clause}
        """), params).scalar()

        # Fetch
        offset = (page - 1) * limit
        params["limit"] = limit
        params["offset"] = offset

        rows = db.execute(text(  # noqa: sql-lint
            f"""
            SELECT je.*,
                   cu.username AS created_by_name,
                   COALESCE(SUM(jl.debit), 0) AS total_debit,
                   COALESCE(SUM(jl.credit), 0) AS total_credit,
                   COUNT(jl.id) AS line_count
            FROM journal_entries je
            LEFT JOIN company_users cu ON je.created_by = cu.id
            LEFT JOIN journal_lines jl ON jl.journal_entry_id = je.id
            WHERE {where_clause}
            GROUP BY je.id, cu.username
            ORDER BY je.entry_date DESC, je.id DESC
            LIMIT :limit OFFSET :offset
        """), params).fetchall()

        entries = []
        for r in rows:
            entries.append({
                "id": r.id,
                "entry_number": r.entry_number,
                "entry_date": str(r.entry_date),
                "description": r.description,
                "reference": r.reference,
                "status": r.status,
                "currency": r.currency,
                "exchange_rate": float(r.exchange_rate) if r.exchange_rate else 1.0,
                "total_debit": float(r.total_debit),
                "total_credit": float(r.total_credit),
                "line_count": r.line_count,
                "created_by": r.created_by,
                "created_by_name": r.created_by_name,
                "created_at": str(r.created_at) if r.created_at else None,
                "posted_at": str(r.posted_at) if r.posted_at else None,
            })

        return {
            "items": entries,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit
        }
@router.get("/journal-entries/{entry_id}", dependencies=[Depends(require_permission("accounting.view"))], response_model=Dict[str, Any])
@limiter.limit("200/minute")
def get_journal_entry(
    request: Request,
    entry_id: int,
    current_user: dict = Depends(get_current_user)
):
    """جلب تفاصيل قيد يومي"""
    with transactional(current_user.company_id) as db:
        entry = db.execute(text("""
            SELECT je.*, cu.username AS created_by_name
            FROM journal_entries je
            LEFT JOIN company_users cu ON je.created_by = cu.id
            WHERE je.id = :id
        """), {"id": entry_id}).fetchone()
        if not entry:
            raise HTTPException(status_code=404, detail="القيد غير موجود")

        # Branch access check
        if entry.branch_id:
            validate_branch_access(current_user, entry.branch_id)

        lines = db.execute(text("""
            SELECT jl.*, a.account_number, a.name AS account_name, a.name_en AS account_name_en
            FROM journal_lines jl
            JOIN accounts a ON jl.account_id = a.id
            WHERE jl.journal_entry_id = :id
            ORDER BY jl.id
        """), {"id": entry_id}).fetchall()

        return {
            "id": entry.id,
            "entry_number": entry.entry_number,
            "entry_date": str(entry.entry_date),
            "description": entry.description,
            "reference": entry.reference,
            "status": entry.status,
            "currency": entry.currency,
            "exchange_rate": float(entry.exchange_rate) if entry.exchange_rate else 1.0,
            "branch_id": entry.branch_id,
            "created_by": entry.created_by,
            "created_by_name": entry.created_by_name,
            "created_at": str(entry.created_at) if entry.created_at else None,
            "posted_at": str(entry.posted_at) if entry.posted_at else None,
            "lines": [{
                "id": l.id,
                "account_id": l.account_id,
                "account_number": l.account_number,
                "account_name": l.account_name,
                "account_name_en": l.account_name_en,
                "debit": float(l.debit),
                "credit": float(l.credit),
                "description": l.description,
                "currency": l.currency,
                "amount_currency": float(l.amount_currency) if l.amount_currency else 0,
                "cost_center_id": l.cost_center_id,
            } for l in lines]
        }
@router.post("/journal-entries/{entry_id}/post", dependencies=[Depends(require_permission("accounting.manage"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
async def post_journal_entry(
    entry_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """اعتماد وترحيل قيد مسودة"""
    with transactional(current_user.company_id) as db:
        try:
            entry = db.execute(text("SELECT * FROM journal_entries WHERE id = :id"), {"id": entry_id}).fetchone()
            if not entry:
                raise HTTPException(status_code=404, detail="القيد غير موجود")
            if entry.status != 'draft':
                raise HTTPException(status_code=400, detail=f"القيد بحالة '{entry.status}' ولا يمكن ترحيله")
    
            # Closed period check
            if entry.entry_date:
                closed_period = db.execute(text("""
                    SELECT 1 FROM fiscal_periods
                    WHERE :entry_date BETWEEN start_date AND end_date
                    AND is_closed = TRUE LIMIT 1
                """), {"entry_date": entry.entry_date}).fetchone()
                if closed_period:
                    raise HTTPException(status_code=400, detail="لا يمكن ترحيل قيود في فترة محاسبية مغلقة")
    
            # Get lines and update account balances
            lines = db.execute(text("""
                SELECT account_id, debit, credit, currency, amount_currency FROM journal_lines
                WHERE journal_entry_id = :id
            """), {"id": entry_id}).fetchall()
    
            # Get the exchange rate from the journal entry
            je_rate = _dec(entry.exchange_rate or 1)
    
            from utils.accounting import update_account_balance
            for line in lines:
                debit_base = _dec(line.debit)
                credit_base = _dec(line.credit)
                # Reverse the base amounts to get original currency amounts
                if je_rate != 0:
                    debit_curr = debit_base / je_rate
                    credit_curr = credit_base / je_rate
                else:
                    debit_curr = debit_base
                    credit_curr = credit_base
                update_account_balance(
                    db,
                    account_id=line.account_id,
                    debit_base=debit_base,
                    credit_base=credit_base,
                    debit_curr=debit_curr,
                    credit_curr=credit_curr,
                    currency=line.currency
                )
    
            # Update status to posted
            db.execute(text("""
                UPDATE journal_entries SET status = 'posted', posted_at = NOW()
                WHERE id = :id
            """), {"id": entry_id})
    
            invalidate_company_cache(str(current_user.company_id))
            
    
            log_activity(
                db,
                user_id=current_user.id,
                username=current_user.username,
                action="accounting.journal.post",
                resource_type="journal_entry",
                resource_id=entry.entry_number,
                details={"description": entry.description},
                request=request,
                branch_id=entry.branch_id
            )
    
            # Notify admins about posted journal entry
            try:
                db.execute(text("""
                    INSERT INTO notifications (user_id, type, title, message, link, is_read, created_at)
                    SELECT DISTINCT u.id, 'journal_entry', :title, :message, :link, FALSE, NOW()
                    FROM company_users u
                    WHERE u.is_active = TRUE AND u.role IN ('admin', 'superuser')
                    AND u.id != :current_uid
                """), {
                    "title": "📝 تم ترحيل قيد يومية",
                    "message": f"تم ترحيل القيد {entry.entry_number} — {entry.description[:80] if entry.description else ''}",
                    "link": f"/accounting/journal/{entry_id}",
                    "current_uid": current_user.id
                })
                db.commit()
            except Exception:
                pass
    
            return {"success": True, "message": "تم ترحيل القيد بنجاح", "entry_number": entry.entry_number}
        except HTTPException:
            raise
        except Exception as e:
            pass
            logger.error(f"Error posting journal entry: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
@router.post("/journal-entries/{entry_id}/void", dependencies=[Depends(require_permission("accounting.manage"))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
async def void_journal_entry(
    entry_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """
    إلغاء (عكس) قيد يومي منشور.
    ينشئ قيد عكسي بنفس المبالغ لإلغاء الأثر المحاسبي.
    """
    with transactional(current_user.company_id) as db:
        try:
            # 1. Get original entry
            original = db.execute(text("""
                SELECT * FROM journal_entries WHERE id = :id
            """), {"id": entry_id}).fetchone()
            
            if not original:
                raise HTTPException(status_code=404, detail="القيد غير موجود")
            
            if original.status == 'voided':
                raise HTTPException(status_code=400, detail="القيد ملغى بالفعل")
    
            # ACC-F4: source-doc-aware authorization.
            # A JE that was auto-generated by another module should only be
            # voidable by users who can also void that upstream document.
            # Admins (or `*` super-perm holders) bypass this additional check.
            user_perms = set(
                getattr(current_user, "permissions", None)
                or (current_user.get("permissions") if isinstance(current_user, dict) else [])
                or []
            )
            is_admin = (
                "*" in user_perms
                or getattr(current_user, "is_system_admin", False)
                or (isinstance(current_user, dict) and current_user.get("is_system_admin"))
            )
            _SOURCE_VOID_PERMS = {
                "sales_invoice": "sales.void_invoice",
                "sales_return": "sales.void_return",
                "purchase_invoice": "purchases.void_invoice",
                "purchase_return": "purchases.void_return",
                "payment": "payments.void",
                "receipt": "payments.void",
                "payroll": "hr.void_payroll",
                "eos": "hr.void_payroll",
                "loan": "hr.void_payroll",
                "asset_depreciation": "assets.void",
                "asset_disposal": "assets.void",
                "tax_payment": "tax.void",
                "zakat": "tax.void",
                "pos_order": "pos.void",
                "stock_adjustment": "inventory.void",
                "landed_cost": "inventory.void",
            }
            src = (original.source or "").strip().lower()
            required_src_perm = _SOURCE_VOID_PERMS.get(src)
            if (
                not is_admin
                and required_src_perm
                and required_src_perm not in user_perms
                and "accounting.admin" not in user_perms
            ):
                raise HTTPException(
                    status_code=403,
                    detail=f"لا تملك صلاحية إلغاء قيد صادر من المصدر: {src}",
                )
            
            # 2. Get original lines
            lines = db.execute(text("""
                SELECT account_id, debit, credit, description, amount_currency, currency, cost_center_id
                FROM journal_lines WHERE journal_entry_id = :id
            """), {"id": entry_id}).fetchall()
            
            if not lines:
                raise HTTPException(status_code=400, detail="القيد لا يحتوي على أسطر")
            
            # 3. Create reversal entry via centralized GL service
            # Fiscal-period lock: the reversal posts at today, so the current
            # period must be open.
            check_fiscal_period_open(db, date.today())
            rev_lines = []
            for line in lines:
                rev_lines.append({
                    "account_id": line.account_id,
                    "debit": _dec(line.credit or 0),
                    "credit": _dec(line.debit or 0),
                    "description": f"عكس: {line.description or ''}",
                    "amount_currency": _dec(line.amount_currency or 0),
                    "currency": line.currency,
                    "cost_center_id": line.cost_center_id,
                })
    
            rev_id, rev_entry_number = gl_create_journal_entry(
                db=db,
                company_id=current_user.company_id,
                date=str(date.today()),
                description=f"عكس قيد: {original.description}",
                lines=rev_lines,
                user_id=current_user.id,
                branch_id=original.branch_id,
                reference=original.entry_number,
                currency=original.currency,
                exchange_rate=_dec(original.exchange_rate or 1),
                source="journal_void",
                source_id=entry_id,
            )
            
            # 5. Mark original as voided
            db.execute(text("""
                UPDATE journal_entries SET status = 'voided' WHERE id = :id
            """), {"id": entry_id})
            
            
            log_activity(
                db,
                user_id=current_user.id,
                username=current_user.username,
                action="accounting.journal.void",
                resource_type="journal_entry",
                resource_id=str(entry_id),
                details={"original_entry": original.entry_number, "reversal_entry": rev_entry_number},
                request=request,
                branch_id=original.branch_id
            )
            
            return {
                "success": True, 
                "message": "تم إلغاء القيد بنجاح وإنشاء قيد عكسي",
                "reversal_entry_id": rev_id,
                "reversal_entry_number": rev_entry_number
            }
        except HTTPException:
            raise
        except Exception as e:
            pass
            logger.error(f"Error voiding journal entry: {str(e)}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
# ============================================================
# Fiscal Year Management & Year-End Closing (ACC-001)
# ============================================================

