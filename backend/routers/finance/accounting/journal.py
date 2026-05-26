"""accounting sub-router — split from monolithic accounting.py (T6.3).

Mounted under the parent router via accounting/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Body, Request
from utils.i18n import http_error, i18n_message
from pydantic import BaseModel
from typing import Any, Dict, Optional
from sqlalchemy import text
from routers.auth import get_current_user
from utils.tx import transactional
import logging
from datetime import date
from utils.cache import invalidate_aggregates
from decimal import Decimal, ROUND_HALF_UP
from utils.permissions import branch_scope_filter, require_permission, require_sensitive_permission, validate_branch_access
from utils.audit import log_activity
from utils.idempotency import find_je_by_idempotency_key
from services.gl_service import (
    create_journal_entry as gl_create_journal_entry,
    reverse_journal_entry as gl_reverse_journal_entry,
    post_draft_journal_entry as gl_post_draft_journal_entry,
)
from utils.fiscal_lock import check_fiscal_period_open
from utils.limiter import limiter

logger = logging.getLogger(__name__)
_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')

def _dec(v) -> Decimal:
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return Decimal("0")
    return Decimal(str(v)) if v is not None else Decimal('0')

router = APIRouter()

from .core import _D2, _D4, _dec  # noqa: E402

@router.post("/journal-entries", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_sensitive_permission("accounting.edit", critical=True))], response_model=Dict[str, Any])
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
                    return {"success": True, "message": i18n_message("journal_entry_already_exists", request), "entry_number": existing.entry_number, "entry_id": existing.id, "status": existing.status, "idempotent": True}
    
            entry_status = entry_data.get("status", "posted")
    
            # Fiscal-period lock: block posting into a closed period.
            entry_date = entry_data.get("date")
            if not entry_date:
                raise HTTPException(**http_error(400, "journal_date_required", request))
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
    
            # T12 — scoped invalidation: a posted JE only affects accounting
            # aggregates (reports, dashboard, trial balance, COA balances).
            invalidate_aggregates(str(current_user.company_id),
                                  "reports", "dashboard", "trial_balance",
                                  "chart_of_accounts")
            
    
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
                        "title": i18n_message("notif_journal_posted", request),
                        "message": i18n_message("journal_entry_posted_details", request),
                        "link": f"/accounting/journal/{journal_id}",
                        "current_uid": current_user.id
                    })
                except Exception:
                    pass
    
            return {"success": True, "message": msg, "entry_number": entry_number, "entry_id": journal_id, "status": entry_status}
            
        except HTTPException:
            raise
        except Exception as e:
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
    page = max(1, int(page or 1))
    limit = min(200, max(1, int(limit or 50)))
    with transactional(current_user.company_id) as db:
        conditions = []
        params = {}

        branch_clause = branch_scope_filter(current_user, branch_id, "je.branch_id", params)
        if branch_clause:
            conditions.append(branch_clause[4:].strip() if branch_clause.startswith("AND ") else branch_clause.strip())

        if search and search.strip() in ('draft', 'posted', 'void', 'voided'):
            conditions.append("je.status = :status_val")
            params["status_val"] = 'void' if search.strip() == 'voided' else search.strip()

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
        total = db.execute(text(  # noqa
            f"""
            SELECT COUNT(*) FROM journal_entries je WHERE {where_clause}
        """), params).scalar()

        # Fetch
        offset = (page - 1) * limit
        params["limit"] = limit
        params["offset"] = offset

        rows = db.execute(text(  # noqa
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
                "exchange_rate": str(_dec(r.exchange_rate or 1).quantize(_D4, ROUND_HALF_UP)),
                "total_debit": str(_dec(r.total_debit).quantize(_D2, ROUND_HALF_UP)),
                "total_credit": str(_dec(r.total_credit).quantize(_D2, ROUND_HALF_UP)),
                "line_count": r.line_count,
                "created_by": r.created_by,
                "created_by_name": r.created_by_name,
                "created_at": str(r.created_at) if r.created_at else None,
                "posted_at": str(r.posted_at) if r.posted_at else None,
                "source": r.source,
                "source_id": r.source_id,
            })

        return {
            "items": entries,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit
        }


@router.post("/journal-entries/preview", dependencies=[Depends(require_permission("accounting.view"))], response_model=Dict[str, Any])
@limiter.limit("200/minute")
def preview_journal_entry(
    request: Request,
    entry_data: dict = Body(...),
    current_user: dict = Depends(get_current_user)
):
    """Backend-authoritative journal line totals for draft UI previews."""
    lines = entry_data.get("lines", [])
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    invalid_both_count = 0
    negative_count = 0

    for line in lines:
        debit = _dec(line.get("debit", 0)).quantize(_D2, ROUND_HALF_UP)
        credit = _dec(line.get("credit", 0)).quantize(_D2, ROUND_HALF_UP)
        if debit < 0 or credit < 0:
            negative_count += 1
        if debit > 0 and credit > 0:
            invalid_both_count += 1
        total_debit += debit
        total_credit += credit

    difference = (total_debit - total_credit).quantize(_D2, ROUND_HALF_UP)
    return {
        "total_debit": str(total_debit.quantize(_D2, ROUND_HALF_UP)),
        "total_credit": str(total_credit.quantize(_D2, ROUND_HALF_UP)),
        "difference": str(difference.copy_abs()),
        "is_balanced": difference.copy_abs() < _D2,
        "has_amount": total_debit > 0 or total_credit > 0,
        "has_debit": total_debit > 0,
        "has_credit": total_credit > 0,
        "invalid_both_count": invalid_both_count,
        "negative_count": negative_count,
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
            raise HTTPException(**http_error(404, "journal_entry_not_found", request))

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
        total_debit = sum((_dec(line.debit) for line in lines), Decimal("0")).quantize(_D2, ROUND_HALF_UP)
        total_credit = sum((_dec(line.credit) for line in lines), Decimal("0")).quantize(_D2, ROUND_HALF_UP)

        return {
            "id": entry.id,
            "entry_number": entry.entry_number,
            "entry_date": str(entry.entry_date),
            "description": entry.description,
            "reference": entry.reference,
            "status": entry.status,
            "currency": entry.currency,
            "exchange_rate": str(_dec(entry.exchange_rate or 1).quantize(_D4, ROUND_HALF_UP)),
            "branch_id": entry.branch_id,
            "created_by": entry.created_by,
            "created_by_name": entry.created_by_name,
            "created_at": str(entry.created_at) if entry.created_at else None,
            "posted_at": str(entry.posted_at) if entry.posted_at else None,
            "source": entry.source,
            "source_id": entry.source_id,
            "total_debit": str(total_debit),
            "total_credit": str(total_credit),
            "lines": [{
                "id": line.id,
                "account_id": line.account_id,
                "account_number": line.account_number,
                "account_name": line.account_name,
                "account_name_en": line.account_name_en,
                "debit": str(_dec(line.debit).quantize(_D2, ROUND_HALF_UP)),
                "credit": str(_dec(line.credit).quantize(_D2, ROUND_HALF_UP)),
                "description": line.description,
                "currency": line.currency,
                "amount_currency": str(_dec(line.amount_currency).quantize(_D2, ROUND_HALF_UP)) if line.amount_currency else "0.00",
                "cost_center_id": line.cost_center_id,
            } for line in lines]
        }
@router.post("/journal-entries/{entry_id}/post", dependencies=[Depends(require_sensitive_permission("accounting.manage", critical=True))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
async def post_journal_entry(
    entry_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """اعتماد وترحيل قيد مسودة"""
    with transactional(current_user.company_id) as db:
        try:
            # F-NEW-041 (R-MISSING-IDEMPOTENCY) — PR16-fix:
            #
            # The previous implementation read ``Idempotency-Key`` and
            # called ``find_je_by_idempotency_key`` *before* posting,
            # but never wrote the key onto the row. ``post_draft_journal_entry``
            # only flips status; the next replay therefore saw the row
            # already in ``posted`` and returned 400 ``status_invalid``
            # rather than echoing the prior result. We now persist the
            # key on ``journal_entries.idempotency_key`` *as part of
            # the transition* so subsequent retries with the same key
            # short-circuit at the probe.
            idempotency_key = request.headers.get("Idempotency-Key")
            if idempotency_key:
                hit = find_je_by_idempotency_key(db, idempotency_key)
                if hit and int(hit[0]) == int(entry_id):
                    return {
                        "success": True,
                        "message": i18n_message("journal_entry_already_posted", request),
                        "entry_number": hit[1],
                        "idempotent": True,
                    }
            entry = db.execute(
                text(
                    "SELECT id, entry_number, status, branch_id, description, "
                    "idempotency_key "
                    "FROM journal_entries WHERE id = :id"
                ),
                {"id": entry_id},
            ).fetchone()
            if not entry:
                raise HTTPException(**http_error(404, "journal_entry_not_found", request))
            # If the row already carries this idempotency key (e.g. a
            # retry after a crash mid-post), echo the existing entry
            # rather than failing on the state guard.
            if (
                idempotency_key
                and entry.idempotency_key == idempotency_key
                and entry.status == "posted"
            ):
                return {
                    "success": True,
                    "message": i18n_message("journal_entry_already_posted", request),
                    "entry_number": entry.entry_number,
                    "idempotent": True,
                }
            if entry.status != 'draft':
                raise HTTPException(status_code=400, detail=i18n_message("journal_entry_status_invalid", request))

            # Persist the idempotency key *before* the state transition
            # so a crash-after-flip but pre-commit retry observes the
            # key on the next probe. The unique partial index on
            # ``journal_entries.idempotency_key`` (alembic 0030)
            # rejects collisions across rows, which is the desired
            # behaviour: two distinct JEs cannot share the same key.
            if idempotency_key and entry.idempotency_key != idempotency_key:
                db.execute(
                    text(
                        "UPDATE journal_entries "
                        "SET idempotency_key = :k "
                        "WHERE id = :id "
                        "  AND idempotency_key IS NULL"
                    ),
                    {"k": idempotency_key, "id": entry_id},
                )

            # Audit F-NEW-010: route through gl_service.post_draft_journal_entry
            # so balance writes go through the sanctioned path. The helper
            # itself runs SELECT ... FOR UPDATE on the row, re-checks the
            # fiscal period via utils.fiscal_lock.check_fiscal_period_open
            # (the canonical guard, per Phase 0 contradiction C-ARCH-002),
            # flips status to 'posted', and applies balances via
            # update_account_balance exactly once.
            gl_post_draft_journal_entry(
                db, je_id=entry_id, user_id=current_user.id, request=request
            )

            # T12 — scoped invalidation (post/unpost only affects accounting)
            invalidate_aggregates(str(current_user.company_id),
                                  "reports", "dashboard", "trial_balance",
                                  "chart_of_accounts")
            
    
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
                    "title": i18n_message("notif_journal_posted", request),
                    "message": i18n_message("journal_entry_posted_details", request),
                    "link": f"/accounting/journal/{entry_id}",
                    "current_uid": current_user.id
                })
            except Exception:
                pass
    
            return {"success": True, "message": i18n_message("journal_entry_posted", request), "entry_number": entry.entry_number}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error posting journal entry: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
@router.post("/journal-entries/{entry_id}/void", dependencies=[Depends(require_sensitive_permission("accounting.manage", critical=True))], response_model=Dict[str, Any])
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
            # F-NEW-043 (R-MISSING-IDEMPOTENCY): a retried /void must return
            # the same reversal JE rather than create a second one. The
            # reversal is keyed by the supplied Idempotency-Key, which we
            # forward to gl_create_journal_entry below.
            idempotency_key = request.headers.get("Idempotency-Key")
            if idempotency_key:
                hit = find_je_by_idempotency_key(db, idempotency_key)
                if hit:
                    return {
                        "success": True,
                        "message": i18n_message("journal_entry_cancelled_success", request),
                        "reversal_entry_id": hit[0],
                        "reversal_entry_number": hit[1],
                        "idempotent": True,
                    }
            # 1. Get original entry
            original = db.execute(text("""
                SELECT * FROM journal_entries WHERE id = :id
            """), {"id": entry_id}).fetchone()
            
            if not original:
                raise HTTPException(**http_error(404, "journal_entry_not_found", request))
            
            if original.status in ('void', 'voided'):
                raise HTTPException(**http_error(400, "journal_already_cancelled", request))

            if original.status == 'reversed':
                raise HTTPException(**http_error(400, "journal_entry_already_reversed", request))

            # Block voiding a reversal entry (to prevent infinite reversal chains)
            if (original.source or '').strip().lower() in ('reversal',):
                raise HTTPException(**http_error(400, "cannot_cancel_reversal", request))
    
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
            
            # 2. Get original lines (validated internally by gl_reverse_journal_entry)
            
            # 3. Create reversal via centralized GL service (Constitution §3: single writer)
            # gl_reverse_journal_entry creates the reversal AND marks original as 'reversed'
            check_fiscal_period_open(db, date.today())
            rev_id, rev_entry_number = gl_reverse_journal_entry(
                db=db,
                je_id=entry_id,
                user_id=current_user.id,
                company_id=current_user.company_id,
                reversal_date=str(date.today()),
                reason=f"Void: {original.description}",
                idempotency_key=idempotency_key,
            )
            
            
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
                "message": i18n_message("journal_entry_cancelled_success", request),
                "reversal_entry_id": rev_id,
                "reversal_entry_number": rev_entry_number
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error voiding journal entry: {str(e)}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
class ReverseJERequest(BaseModel):
    reversal_date: Optional[str] = None
    reason: Optional[str] = None


@router.post("/journal-entries/{entry_id}/reverse", dependencies=[Depends(require_sensitive_permission("accounting.manage", critical=True))], response_model=Dict[str, Any])
@limiter.limit("100/minute")
def reverse_journal_entry_endpoint(
    entry_id: int,
    request: Request,
    body: ReverseJERequest = Body(default_factory=ReverseJERequest),
    current_user: dict = Depends(get_current_user)
):
    """إنشاء قيد عكسي لقيد مرحَّل مع الاحتفاظ بالقيد الأصلي."""
    with transactional(current_user.company_id) as db:
        try:
            # F-NEW-044 (R-MISSING-IDEMPOTENCY): forward Idempotency-Key
            # to gl_reverse_journal_entry so retries return the same
            # reversal entry rather than failing with reversal_already_exists.
            idempotency_key = request.headers.get("Idempotency-Key")
            # Validate reversal date period is open
            reversal_date = body.reversal_date or str(date.today())
            check_fiscal_period_open(db, reversal_date)

            rev_id, rev_num = gl_reverse_journal_entry(
                db=db,
                je_id=entry_id,
                user_id=current_user.id,
                company_id=current_user.company_id,
                reversal_date=reversal_date,
                reason=body.reason,
                idempotency_key=idempotency_key,
            )

            log_activity(
                db,
                user_id=current_user.id,
                username=current_user.username,
                action="accounting.journal.reverse",
                resource_type="journal_entry",
                resource_id=str(entry_id),
                details={"reversal_entry_id": rev_id, "reversal_entry_number": rev_num, "reason": body.reason},
                request=request,
            )

            invalidate_aggregates(str(current_user.company_id),
                                  "reports", "dashboard", "trial_balance",
                                  "chart_of_accounts")

            return {
                "success": True,
                "message": i18n_message("reversal_entry_created", request),
                "reversal_entry_id": rev_id,
                "reversal_entry_number": rev_num,
            }
        except HTTPException:
            raise
        except Exception:
            logger.exception("Error reversing journal entry")
            raise HTTPException(**http_error(500, "internal_error"))


# ============================================================
# Fiscal Year Management & Year-End Closing (ACC-001)
# ============================================================
