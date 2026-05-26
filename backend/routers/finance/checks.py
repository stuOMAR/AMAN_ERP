"""
Checks Management Router - TRS-001 & TRS-002
إدارة الشيكات تحت التحصيل والدفع
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from utils.i18n import http_error, i18n_message
from sqlalchemy import text
from routers.auth import get_current_user
from utils.tx import transactional
from utils.audit import log_activity
from utils.permissions import branch_scope_filter, require_permission, validate_branch_access, validate_treasury_account_access, require_module
from utils.accounting import get_base_currency
from utils.fiscal_lock import check_fiscal_period_open
from services.gl_service import create_journal_entry as gl_create_journal_entry
from utils.idempotency import find_je_by_idempotency_key, find_je_by_source
from utils.treasury_gl import ensure_treasury_gl_accounts
from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from typing import Any, Dict, List, Optional
import logging
logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')


def _dec(v):
    """Convert a value to Decimal safely (avoids float-binary noise)."""
    return Decimal(str(v or 0))

router = APIRouter(prefix="/checks", tags=["checks"], dependencies=[Depends(require_module("treasury"))])


def _ensure_checks_accounts(db):
    """Ensure accounts 1205 (Checks Receivable) and 2105 (Checks Payable) exist."""
    for code, nm, nm_en, acc_type, parent_prefix in [
        ('1205', 'شيكات تحت التحصيل', 'Checks Under Collection', 'asset', '12'),
        ('2105', 'شيكات تحت الدفع', 'Checks Payable', 'liability', '21'),
    ]:
        existing = db.execute(text(
            "SELECT id FROM accounts WHERE account_code = :code"
        ), {"code": code}).fetchone()
        if not existing:
            parent = db.execute(text(
                "SELECT id FROM accounts WHERE account_code = :code"
            ), {"code": parent_prefix + '00'}).fetchone()
            db.execute(text("""
                INSERT INTO accounts (account_number, account_code, name, name_en, account_type, parent_id, is_active, currency)
                VALUES (:code, :code, :name, :name_en, :type, :pid, TRUE, :currency)
                ON CONFLICT (account_number) DO NOTHING
            """), {"code": code, "name": nm, "name_en": nm_en, "type": acc_type,
                   "pid": parent.id if parent else None, "currency": get_base_currency(db)})
            db.commit()


# ============================================================
# TRS-001: شيكات تحت التحصيل - Checks Receivable
# ============================================================

@router.get("/receivable", dependencies=[Depends(require_permission("treasury.view"))], response_model=Dict[str, Any])
def list_checks_receivable(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = None,
    search: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user=Depends(get_current_user)
):
    """List all checks receivable with filters"""
    with transactional(current_user.company_id) as db:
        try:
            offset = (page - 1) * limit
            conditions = []
            params = {"limit": limit, "offset": offset}
    
            if status:
                conditions.append("cr.status = :status")
                params["status"] = status
            if search:
                conditions.append("(cr.check_number ILIKE :search OR cr.drawer_name ILIKE :search OR cr.bank_name ILIKE :search)")
                params["search"] = f"%{search}%"
            branch_clause = branch_scope_filter(current_user, branch_id, "cr.branch_id", params)
            if branch_clause:
                conditions.append(branch_clause[4:].strip() if branch_clause.startswith("AND ") else branch_clause.strip())
    
            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    
            total = db.execute(text(f"SELECT COUNT(*) FROM checks_receivable cr {where}"), params).scalar() or 0
    
            rows = db.execute(text(f"""
                SELECT cr.*, p.name as party_name, ta.name as treasury_name
                FROM checks_receivable cr
                LEFT JOIN parties p ON cr.party_id = p.id
                LEFT JOIN treasury_accounts ta ON cr.treasury_account_id = ta.id
                {where}
                ORDER BY cr.due_date ASC
                LIMIT :limit OFFSET :offset
            """), params).fetchall()
    
            items = []
            for r in rows:
                items.append({
                    "id": r.id, "check_number": r.check_number,
                    "drawer_name": r.drawer_name, "bank_name": r.bank_name,
                    "branch_name": r.branch_name, "amount": str(_dec(r.amount)),
                    "currency": r.currency,
                    "issue_date": str(r.issue_date) if r.issue_date else None,
                    "due_date": str(r.due_date) if r.due_date else None,
                    "collection_date": str(r.collection_date) if r.collection_date else None,
                    "bounce_date": str(r.bounce_date) if r.bounce_date else None,
                    "party_id": r.party_id, "party_name": r.party_name,
                    "treasury_account_id": r.treasury_account_id,
                    "treasury_name": r.treasury_name,
                    "status": r.status, "bounce_reason": r.bounce_reason,
                    "notes": r.notes, "created_at": str(r.created_at) if r.created_at else None,
                })
    
            return {"items": items, "total": total, "page": page}
        except Exception:
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.get("/receivable/summary/stats", dependencies=[Depends(require_permission("treasury.view"))], response_model=Dict[str, Any])
def checks_receivable_stats(branch_id: Optional[int] = None, current_user=Depends(get_current_user)):
    """Get summary stats for checks receivable"""
    with transactional(current_user.company_id) as db:
        try:
            params = {}
            cond = branch_scope_filter(current_user, branch_id, "branch_id", params)
            stats = db.execute(text(f"""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'pending') as pending_count,
                    COALESCE(SUM(amount) FILTER (WHERE status = 'pending'), 0) as pending_amount,
                    COUNT(*) FILTER (WHERE status = 'collected') as collected_count,
                    COALESCE(SUM(amount) FILTER (WHERE status = 'collected'), 0) as collected_amount,
                    COUNT(*) FILTER (WHERE status = 'bounced') as bounced_count,
                    COALESCE(SUM(amount) FILTER (WHERE status = 'bounced'), 0) as bounced_amount,
                    COUNT(*) FILTER (WHERE status = 'pending' AND due_date <= CURRENT_DATE) as overdue_count,
                    COALESCE(SUM(amount) FILTER (WHERE status = 'pending' AND due_date <= CURRENT_DATE), 0) as overdue_amount
                FROM checks_receivable WHERE 1=1 {cond}
            """), params).fetchone()
            return {
                "pending": {"count": stats.pending_count, "amount": str(_dec(stats.pending_amount))},
                "collected": {"count": stats.collected_count, "amount": str(_dec(stats.collected_amount))},
                "bounced": {"count": stats.bounced_count, "amount": str(_dec(stats.bounced_amount))},
                "overdue": {"count": stats.overdue_count, "amount": str(_dec(stats.overdue_amount))},
            }
        except Exception:
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.get("/receivable/{check_id}", dependencies=[Depends(require_permission("treasury.view"))], response_model=Dict[str, Any])
def get_check_receivable(check_id: int, current_user=Depends(get_current_user)):
    """Get single check receivable details"""
    with transactional(current_user.company_id) as db:
        try:
            r = db.execute(text("""
                SELECT cr.*, p.name as party_name, ta.name as treasury_name
                FROM checks_receivable cr
                LEFT JOIN parties p ON cr.party_id = p.id
                LEFT JOIN treasury_accounts ta ON cr.treasury_account_id = ta.id
                WHERE cr.id = :id
            """), {"id": check_id}).fetchone()
            if not r:
                raise HTTPException(**http_error(404, "check_not_found"))
            
            # Validate branch access
            validate_branch_access(current_user, r.branch_id)
            
            return {
                "id": r.id, "check_number": r.check_number,
                "drawer_name": r.drawer_name, "bank_name": r.bank_name,
                "branch_name": r.branch_name, "amount": str(_dec(r.amount)),
                "currency": r.currency,
                "issue_date": str(r.issue_date) if r.issue_date else None,
                "due_date": str(r.due_date) if r.due_date else None,
                "collection_date": str(r.collection_date) if r.collection_date else None,
                "bounce_date": str(r.bounce_date) if r.bounce_date else None,
                "party_id": r.party_id, "party_name": r.party_name,
                "treasury_account_id": r.treasury_account_id,
                "treasury_name": r.treasury_name,
                "status": r.status, "bounce_reason": r.bounce_reason,
                "notes": r.notes,
                "journal_entry_id": r.journal_entry_id,
                "collection_journal_id": r.collection_journal_id,
                "bounce_journal_id": r.bounce_journal_id,
            }
        except HTTPException:
            raise
        except Exception:
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/receivable", dependencies=[Depends(require_permission("treasury.create"))], response_model=Dict[str, Any])
def create_check_receivable(data: dict, request: Request, current_user=Depends(get_current_user)):
    """
    Create a new check receivable.
    On creation: Dr. Checks Under Collection (1205) / Cr. Accounts Receivable
    """
    with transactional(current_user.company_id) as db:
        try:
            branch_id = validate_branch_access(current_user, data.get("branch_id"))
            if data.get("treasury_account_id"):
                validate_treasury_account_access(db, current_user, data.get("treasury_account_id"), branch_id)
    
            required = ["check_number", "amount", "due_date"]
            for f in required:
                if not data.get(f):
                    raise HTTPException(**http_error(400, "required_field_missing", request))
    
            # T015: Duplicate check number warning per branch
            dup = db.execute(text("""
                SELECT id, status, amount FROM checks_receivable
                WHERE check_number = :cn AND branch_id IS NOT DISTINCT FROM :bid
            """), {"cn": data["check_number"], "bid": data.get("branch_id")}).fetchone()
            if dup:
                raise HTTPException(
                    409,
                    detail=f"شيك بنفس الرقم موجود مسبقاً (ID={dup.id}, الحالة={dup.status}, المبلغ={_dec(dup.amount).quantize(_D2, ROUND_HALF_UP)})"
                )
    
            _ensure_checks_accounts(db)
            # Also ensure all 4 treasury GL accounts exist (1205, 2105, 1210, 2110)
            # PR19-fix: commit=False — the surrounding transactional()
            # block owns commit/rollback. Without this flag the helper
            # auto-committed mid-flight, breaking atomicity for the
            # rest of the check-creation path.
            ensure_treasury_gl_accounts(
                db, user_id=current_user.id,
                username=current_user.username, commit=False,
            )
    
            amount = _dec(data["amount"]).quantize(_D2, ROUND_HALF_UP)
    
            checks_account = db.execute(text(
                "SELECT id FROM accounts WHERE account_code = '1205' LIMIT 1"
            )).fetchone()
    
            ar_account = db.execute(text(
                "SELECT id FROM accounts WHERE account_code IN ('1201', '1200') AND is_active = TRUE ORDER BY account_code LIMIT 1"
            )).fetchone()
    
            if not checks_account or not ar_account:
                raise HTTPException(**http_error(500, "check_accounts_not_found", request))
    
            check_fiscal_period_open(db, data.get("issue_date", str(date.today())))
            
            je_lines = [
                {"account_id": checks_account.id, "debit": _dec(amount), "credit": 0, "description": f"شيك تحت التحصيل {data['check_number']}"},
                {"account_id": ar_account.id, "debit": 0, "credit": _dec(amount), "description": f"شيك تحت التحصيل {data['check_number']}"},
            ]
    
            je_id, _ = gl_create_journal_entry(
                db=db,
                company_id=current_user.company_id,
                date=data.get("issue_date", str(date.today())),
                description=f"استلام شيك رقم {data['check_number']} - {data.get('drawer_name', '')}",
                lines=je_lines,
                user_id=current_user.id,
                branch_id=branch_id,
                source="check_receivable"
            )
    
            result = db.execute(text("""
                INSERT INTO checks_receivable (
                    check_number, drawer_name, bank_name, branch_name, amount, currency,
                    issue_date, due_date, party_id, treasury_account_id, receipt_id,
                    journal_entry_id, status, notes, branch_id, created_by, exchange_rate, party_site_id
                ) VALUES (
                    :check_number, :drawer_name, :bank_name, :branch_name, :amount, :currency,
                    :issue_date, :due_date, :party_id, :treasury_id, :receipt_id,
                    :je_id, 'pending', :notes, :branch_id, :user_id, :exchange_rate, :party_site_id
                ) RETURNING id
            """), {
                "check_number": data["check_number"],
                "drawer_name": data.get("drawer_name", ""),
                "bank_name": data.get("bank_name", ""),
                "branch_name": data.get("branch_name", ""),
                "amount": str(amount),
                "currency": data.get("currency", get_base_currency(db)),
                "issue_date": data.get("issue_date"),
                "due_date": data["due_date"],
                "party_id": data.get("party_id"),
                "treasury_id": data.get("treasury_account_id"),
                "receipt_id": data.get("receipt_id"),
                "je_id": je_id,
                "notes": data.get("notes", ""),
                "branch_id": branch_id,
                "user_id": current_user.id,
                "exchange_rate": str(_dec(data.get("exchange_rate", 1))),
                "party_site_id": data.get("party_site_id"),
            }).fetchone()
    
            log_activity(db, current_user.id, current_user.username, "create", "checks_receivable", str(result.id),
                         {"check_number": data["check_number"], "amount": str(amount)})
            return {"id": result.id, "message": i18n_message("check_registered", request)}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/receivable/{check_id}/collect", dependencies=[Depends(require_permission("treasury.create"))], response_model=Dict[str, Any])
def collect_check_receivable(check_id: int, data: dict, request: Request, current_user=Depends(get_current_user)):
    """
    Mark check as collected.
    GL: Dr. Bank (treasury) / Cr. Checks Under Collection (1205)
    """
    with transactional(current_user.company_id) as db:
        try:
            # F-NEW-085 (R-MISSING-IDEMPOTENCY) — PR16-fix: replay probe
            # before the state guard. The previous implementation
            # rejected retries with 400 ``check_not_pending`` because
            # the first call had already flipped the row to
            # ``collected``; a network retry then had no idempotent
            # surface. We probe both the header (header-based replay)
            # and ``(source='check_collection', source_id)`` (natural
            # anchor) so retries collapse even when the client forgets
            # to send Idempotency-Key.
            idempotency_key = request.headers.get("Idempotency-Key")
            prior = (
                find_je_by_idempotency_key(db, idempotency_key)
                if idempotency_key
                else None
            ) or find_je_by_source(
                db, source="check_collection", source_id=check_id
            )
            if prior is not None:
                return {
                    "message": i18n_message("check_collected_success", request),
                    "idempotent": True,
                    "journal_id": prior[0],
                    "entry_number": prior[1],
                }

            check = db.execute(text("SELECT * FROM checks_receivable WHERE id = :id FOR UPDATE"), {"id": check_id}).fetchone()
            if not check:
                raise HTTPException(**http_error(404, "check_not_found"))
                
            branch_id = validate_branch_access(current_user, check.branch_id)
            
            if check.status != 'pending':
                raise HTTPException(**http_error(400, "check_not_pending", request))
    
            collection_date = data.get("collection_date", str(date.today()))
            treasury_id = data.get("treasury_account_id") or check.treasury_account_id
    
            if not treasury_id:
                raise HTTPException(**http_error(400, "treasury_or_bank_required"))
    
            treasury = validate_treasury_account_access(db, current_user, treasury_id, branch_id)
    
            checks_account = db.execute(text("SELECT id FROM accounts WHERE account_code = '1205' LIMIT 1")).fetchone()
            if not checks_account:
                raise HTTPException(**http_error(500, "checks_receivable_account_not_found", request))
    
            amount = _dec(check.amount).quantize(_D2, ROUND_HALF_UP)
    
            check_fiscal_period_open(db, collection_date)
            
            je_lines = [
                {"account_id": treasury["gl_account_id"], "debit": _dec(amount), "credit": 0, "description": f"تحصيل شيك {check.check_number}"},
                {"account_id": checks_account.id, "debit": 0, "credit": _dec(amount), "description": f"تحصيل شيك {check.check_number}"},
            ]
            
            coll_je_id, _ = gl_create_journal_entry(
                db=db,
                company_id=current_user.company_id,
                date=collection_date,
                description=f"تحصيل شيك رقم {check.check_number}",
                lines=je_lines,
                user_id=current_user.id,
                branch_id=check.branch_id,
                source="check_collection",
                source_id=check_id,
                idempotency_key=idempotency_key,
            )
    
            # Update treasury balance — T1.3a idempotent recompute
            from utils.treasury_balance import recalc_treasury_from_gl
            recalc_treasury_from_gl(db, treasury_id)
    
            db.execute(text("""
                UPDATE checks_receivable SET status = 'collected', collection_date = :cdate,
                    collection_journal_id = :je_id, treasury_account_id = COALESCE(:treasury_id, treasury_account_id),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """), {"id": check_id, "cdate": collection_date, "je_id": coll_je_id, "treasury_id": treasury_id})
            log_activity(db, current_user.id, current_user.username, "collect", "checks_receivable", str(check_id),
                         {"collection_date": collection_date})
            return {"message": i18n_message("check_collected_success", request)}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/receivable/{check_id}/bounce", dependencies=[Depends(require_permission("treasury.create"))], response_model=Dict[str, Any])
def bounce_check_receivable(check_id: int, data: dict, request: Request, current_user=Depends(get_current_user)):
    """
    Mark check as bounced.
    If pending: Dr. AR / Cr. Checks Under Collection (reverse original)
    If collected: Dr. AR / Cr. Bank (reverse collection + original)
    """
    with transactional(current_user.company_id) as db:
        try:
            # F-NEW-085 (R-MISSING-IDEMPOTENCY) — PR16-fix: replay probe
            # before state guard so retries collapse to a 200 instead
            # of failing with check_cannot_bounce. We probe both by
            # Idempotency-Key header (header-based replay) and by
            # ``(source='check_bounce', source_id)`` (natural anchor)
            # because a bounce is a one-shot event per check.
            idempotency_key = request.headers.get("Idempotency-Key")
            prior = (
                find_je_by_idempotency_key(db, idempotency_key)
                if idempotency_key
                else None
            ) or find_je_by_source(
                db, source="check_bounce", source_id=check_id
            )
            if prior is not None:
                return {
                    "message": i18n_message("check_bounced_success", request),
                    "idempotent": True,
                    "journal_id": prior[0],
                    "entry_number": prior[1],
                }

            check = db.execute(text("SELECT * FROM checks_receivable WHERE id = :id FOR UPDATE"), {"id": check_id}).fetchone()
            if not check:
                raise HTTPException(**http_error(404, "check_not_found"))
                
            branch_id = validate_branch_access(current_user, check.branch_id)
            
            if check.status not in ('pending', 'collected'):
                raise HTTPException(**http_error(400, "check_cannot_bounce", request))
    
            bounce_reason = data.get("bounce_reason", "")
            bounce_date = data.get("bounce_date", str(date.today()))
            amount = _dec(check.amount).quantize(_D2, ROUND_HALF_UP)
    
            ar_account = db.execute(text(
                "SELECT id FROM accounts WHERE account_code IN ('1201', '1200') AND is_active = TRUE ORDER BY account_code LIMIT 1"
            )).fetchone()
            checks_account = db.execute(text("SELECT id FROM accounts WHERE account_code = '1205' LIMIT 1")).fetchone()
    
            if not ar_account:
                raise HTTPException(**http_error(500, "ar_account_not_found", request))
    
            check_fiscal_period_open(db, bounce_date)
            bounce_je_id = None
    
            if check.status == 'collected':
                treasury = validate_treasury_account_access(
                    db, current_user, check.treasury_account_id, branch_id
                ) if check.treasury_account_id else None
                if not treasury:
                    raise HTTPException(**http_error(400, "treasury_not_linked_to_check", request))
    
                je_lines = [
                    {"account_id": ar_account.id, "debit": _dec(amount), "credit": 0, "description": f"ارتجاع شيك {check.check_number}"},
                    {"account_id": treasury["gl_account_id"], "debit": 0, "credit": _dec(amount), "description": f"ارتجاع شيك {check.check_number}"},
                ]
                bounce_je_id, _ = gl_create_journal_entry(
                    db=db,
                    company_id=current_user.company_id,
                    date=bounce_date,
                    description=f"ارتجاع شيك رقم {check.check_number} - {bounce_reason}",
                    lines=je_lines,
                    user_id=current_user.id,
                    branch_id=check.branch_id,
                    source="check_bounce",
                    source_id=check_id,
                    idempotency_key=idempotency_key,
                )
    
                # Treasury balance decreases — T1.3a idempotent recompute
                from utils.treasury_balance import recalc_treasury_from_gl
                recalc_treasury_from_gl(db, check.treasury_account_id)
            else:
                if not checks_account:
                    raise HTTPException(**http_error(500, "checks_receivable_account_not_found", request))
    
                je_lines = [
                    {"account_id": ar_account.id, "debit": _dec(amount), "credit": 0, "description": f"ارتجاع شيك {check.check_number}"},
                    {"account_id": checks_account.id, "debit": 0, "credit": _dec(amount), "description": f"ارتجاع شيك {check.check_number}"},
                ]
                bounce_je_id, _ = gl_create_journal_entry(
                    db=db,
                    company_id=current_user.company_id,
                    date=bounce_date,
                    description=f"ارتجاع شيك رقم {check.check_number} - {bounce_reason}",
                    lines=je_lines,
                    user_id=current_user.id,
                    branch_id=check.branch_id,
                    source="check_bounce",
                    source_id=check_id,
                    idempotency_key=idempotency_key,
                )
    
            db.execute(text("""
                UPDATE checks_receivable SET status = 'bounced', bounce_date = :bdate,
                    bounce_reason = :reason, bounce_journal_id = :je_id, updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """), {"id": check_id, "bdate": bounce_date, "reason": bounce_reason, "je_id": bounce_je_id})
            log_activity(db, current_user.id, current_user.username, "bounce", "checks_receivable", str(check_id),
                         {"bounce_reason": bounce_reason})
            return {"message": i18n_message("check_bounced_success", request)}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/receivable/{check_id}/represent", dependencies=[Depends(require_permission("treasury.create"))], response_model=Dict[str, Any])
def represent_check_receivable(check_id: int, request: Request, data: dict = None, current_user=Depends(get_current_user)):
    """
    Re-present a bounced check receivable.
    Sets status back to 'pending', posts GL entry (Dr. 1205 / Cr. AR),
    increments re_presentation_count, stores re_presentation_journal_id.
    """
    if data is None:
        data = {}
    with transactional(current_user.company_id) as db:
        try:
            # F-NEW-085 (R-MISSING-IDEMPOTENCY) — PR16-fix: replay probe
            # before the state guard so a retry collapses to a 200
            # echo instead of 400 check_cannot_represent.
            idempotency_key = request.headers.get("Idempotency-Key")
            prior = (
                find_je_by_idempotency_key(db, idempotency_key)
                if idempotency_key
                else None
            ) or find_je_by_source(
                db, source="check_re_presentation", source_id=check_id
            )
            if prior is not None:
                return {
                    "message": i18n_message("check_represented_success", request),
                    "idempotent": True,
                    "journal_id": prior[0],
                    "entry_number": prior[1],
                }

            check = db.execute(text("SELECT * FROM checks_receivable WHERE id = :id FOR UPDATE"), {"id": check_id}).fetchone()
            if not check:
                raise HTTPException(**http_error(404, "check_not_found"))
    
            validate_branch_access(current_user, check.branch_id)
    
            if check.status != 'bounced':
                raise HTTPException(**http_error(400, "check_cannot_represent", request))
    
            represent_date = data.get("represent_date", str(date.today()))
            amount = _dec(check.amount).quantize(_D2, ROUND_HALF_UP)
    
            checks_account = db.execute(text("SELECT id FROM accounts WHERE account_code = '1205' LIMIT 1")).fetchone()
            ar_account = db.execute(text(
                "SELECT id FROM accounts WHERE account_code IN ('1201', '1200') AND is_active = TRUE ORDER BY account_code LIMIT 1"
            )).fetchone()
            if not checks_account or not ar_account:
                raise HTTPException(**http_error(500, "check_accounts_not_found", request))
    
            check_fiscal_period_open(db, represent_date)
    
            je_lines = [
                {"account_id": checks_account.id, "debit": _dec(amount), "credit": 0, "description": f"إعادة تقديم شيك {check.check_number}"},
                {"account_id": ar_account.id, "debit": 0, "credit": _dec(amount), "description": f"إعادة تقديم شيك {check.check_number}"},
            ]
    
            je_id, _ = gl_create_journal_entry(
                db=db,
                company_id=current_user.company_id,
                date=represent_date,
                description=f"إعادة تقديم شيك رقم {check.check_number}",
                lines=je_lines,
                user_id=current_user.id,
                branch_id=check.branch_id,
                source="check_re_presentation",
                source_id=check_id,
                idempotency_key=idempotency_key,
            )
    
            new_count = (check.re_presentation_count or 0) + 1
            db.execute(text("""
                UPDATE checks_receivable
                SET status = 'pending', re_presentation_date = :rdate,
                    re_presentation_count = :cnt, re_presentation_journal_id = :je_id,
                    bounce_date = NULL, bounce_reason = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """), {"id": check_id, "rdate": represent_date, "cnt": new_count, "je_id": je_id})
    
            log_activity(db, current_user.id, current_user.username, "represent", "checks_receivable", str(check_id),
                         {"re_presentation_count": new_count})
            return {"message": i18n_message("check_represented_success", request), "journal_entry_id": je_id}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ============================================================
# TRS-002: شيكات تحت الدفع - Checks Payable
# ============================================================

@router.get("/payable", dependencies=[Depends(require_permission("treasury.view"))], response_model=Dict[str, Any])
def list_checks_payable(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = None,
    search: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user=Depends(get_current_user)
):
    """List all checks payable with filters"""
    with transactional(current_user.company_id) as db:
        try:
            offset = (page - 1) * limit
            conditions = []
            params = {"limit": limit, "offset": offset}
    
            if status:
                conditions.append("cp.status = :status")
                params["status"] = status
            if search:
                conditions.append("(cp.check_number ILIKE :search OR cp.beneficiary_name ILIKE :search OR cp.bank_name ILIKE :search)")
                params["search"] = f"%{search}%"
            branch_clause = branch_scope_filter(current_user, branch_id, "cp.branch_id", params)
            if branch_clause:
                conditions.append(branch_clause[4:].strip() if branch_clause.startswith("AND ") else branch_clause.strip())
    
            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    
            total = db.execute(text(f"SELECT COUNT(*) FROM checks_payable cp {where}"), params).scalar() or 0
    
            rows = db.execute(text(f"""
                SELECT cp.*, p.name as party_name, ta.name as treasury_name
                FROM checks_payable cp
                LEFT JOIN parties p ON cp.party_id = p.id
                LEFT JOIN treasury_accounts ta ON cp.treasury_account_id = ta.id
                {where}
                ORDER BY cp.due_date ASC
                LIMIT :limit OFFSET :offset
            """), params).fetchall()
    
            items = []
            for r in rows:
                items.append({
                    "id": r.id, "check_number": r.check_number,
                    "beneficiary_name": r.beneficiary_name, "bank_name": r.bank_name,
                    "branch_name": r.branch_name, "amount": str(_dec(r.amount)),
                    "currency": r.currency,
                    "issue_date": str(r.issue_date) if r.issue_date else None,
                    "due_date": str(r.due_date) if r.due_date else None,
                    "clearance_date": str(r.clearance_date) if r.clearance_date else None,
                    "bounce_date": str(r.bounce_date) if r.bounce_date else None,
                    "party_id": r.party_id, "party_name": r.party_name,
                    "treasury_account_id": r.treasury_account_id,
                    "treasury_name": r.treasury_name,
                    "status": r.status, "bounce_reason": r.bounce_reason,
                    "notes": r.notes, "created_at": str(r.created_at) if r.created_at else None,
                })
    
            return {"items": items, "total": total, "page": page}
        except Exception:
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.get("/payable/summary/stats", dependencies=[Depends(require_permission("treasury.view"))], response_model=Dict[str, Any])
def checks_payable_stats(branch_id: Optional[int] = None, current_user=Depends(get_current_user)):
    """Get summary stats for checks payable"""
    with transactional(current_user.company_id) as db:
        try:
            params = {}
            cond = branch_scope_filter(current_user, branch_id, "branch_id", params)
            stats = db.execute(text(f"""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'issued') as issued_count,
                    COALESCE(SUM(amount) FILTER (WHERE status = 'issued'), 0) as issued_amount,
                    COUNT(*) FILTER (WHERE status = 'cleared') as cleared_count,
                    COALESCE(SUM(amount) FILTER (WHERE status = 'cleared'), 0) as cleared_amount,
                    COUNT(*) FILTER (WHERE status = 'bounced') as bounced_count,
                    COALESCE(SUM(amount) FILTER (WHERE status = 'bounced'), 0) as bounced_amount,
                    COUNT(*) FILTER (WHERE status = 'issued' AND due_date <= CURRENT_DATE) as overdue_count,
                    COALESCE(SUM(amount) FILTER (WHERE status = 'issued' AND due_date <= CURRENT_DATE), 0) as overdue_amount
                FROM checks_payable WHERE 1=1 {cond}
            """), params).fetchone()
            return {
                "issued": {"count": stats.issued_count, "amount": str(_dec(stats.issued_amount))},
                "cleared": {"count": stats.cleared_count, "amount": str(_dec(stats.cleared_amount))},
                "bounced": {"count": stats.bounced_count, "amount": str(_dec(stats.bounced_amount))},
                "overdue": {"count": stats.overdue_count, "amount": str(_dec(stats.overdue_amount))},
            }
        except Exception:
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.get("/payable/{check_id}", dependencies=[Depends(require_permission("treasury.view"))], response_model=Dict[str, Any])
def get_check_payable(check_id: int, current_user=Depends(get_current_user)):
    """Get single check payable details"""
    with transactional(current_user.company_id) as db:
        try:
            r = db.execute(text("""
                SELECT cp.*, p.name as party_name, ta.name as treasury_name
                FROM checks_payable cp
                LEFT JOIN parties p ON cp.party_id = p.id
                LEFT JOIN treasury_accounts ta ON cp.treasury_account_id = ta.id
                WHERE cp.id = :id
            """), {"id": check_id}).fetchone()
            if not r:
                raise HTTPException(**http_error(404, "check_not_found"))
                
            # Validate branch access
            validate_branch_access(current_user, r.branch_id)
            
            return {
                "id": r.id, "check_number": r.check_number,
                "beneficiary_name": r.beneficiary_name, "bank_name": r.bank_name,
                "branch_name": r.branch_name, "amount": str(_dec(r.amount)),
                "currency": r.currency,
                "issue_date": str(r.issue_date) if r.issue_date else None,
                "due_date": str(r.due_date) if r.due_date else None,
                "clearance_date": str(r.clearance_date) if r.clearance_date else None,
                "bounce_date": str(r.bounce_date) if r.bounce_date else None,
                "party_id": r.party_id, "party_name": r.party_name,
                "treasury_account_id": r.treasury_account_id,
                "treasury_name": r.treasury_name,
                "status": r.status, "bounce_reason": r.bounce_reason,
                "notes": r.notes,
                "journal_entry_id": r.journal_entry_id,
                "clearance_journal_id": r.clearance_journal_id,
                "bounce_journal_id": r.bounce_journal_id,
            }
        except HTTPException:
            raise
        except Exception:
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/payable", dependencies=[Depends(require_permission("treasury.create"))], response_model=Dict[str, Any])
def create_check_payable(data: dict, request: Request, current_user=Depends(get_current_user)):
    """
    Create a new check payable (issued check).
    GL: Dr. Accounts Payable / Cr. Checks Payable Account (2105)
    """
    with transactional(current_user.company_id) as db:
        try:
            branch_id = validate_branch_access(current_user, data.get("branch_id"))
            if data.get("treasury_account_id"):
                validate_treasury_account_access(db, current_user, data.get("treasury_account_id"), branch_id)
    
            required = ["check_number", "amount", "due_date", "issue_date"]
            for f in required:
                if not data.get(f):
                    raise HTTPException(**http_error(400, "required_field_missing", request))
    
            # --- T021: Duplicate check number warning ---
            dup = db.execute(text("""
                SELECT id, status, amount FROM checks_payable
                WHERE check_number = :cn AND branch_id IS NOT DISTINCT FROM :bid
                LIMIT 1
            """), {"cn": data["check_number"], "bid": data.get("branch_id")}).fetchone()
            if dup:
                raise HTTPException(**http_error(409, "payable_check_number_duplicate", request))
    
            _ensure_checks_accounts(db)
    
            amount = _dec(data["amount"]).quantize(_D2, ROUND_HALF_UP)
    
            checks_pay_account = db.execute(text(
                "SELECT id FROM accounts WHERE account_code = '2105' LIMIT 1"
            )).fetchone()
    
            ap_account = db.execute(text(
                "SELECT id FROM accounts WHERE account_code IN ('2101', '2100') AND is_active = TRUE ORDER BY account_code LIMIT 1"
            )).fetchone()
    
            if not checks_pay_account or not ap_account:
                raise HTTPException(**http_error(500, "check_payable_accounts_not_found", request))
    
            check_fiscal_period_open(db, data["issue_date"])
            
            je_lines = [
                {"account_id": ap_account.id, "debit": _dec(amount), "credit": 0, "description": f"شيك صادر {data['check_number']}"},
                {"account_id": checks_pay_account.id, "debit": 0, "credit": _dec(amount), "description": f"شيك صادر {data['check_number']}"},
            ]
    
            je_id, _ = gl_create_journal_entry(
                db=db,
                company_id=current_user.company_id,
                date=data["issue_date"],
                description=f"إصدار شيك رقم {data['check_number']} - {data.get('beneficiary_name', '')}",
                lines=je_lines,
                user_id=current_user.id,
                branch_id=branch_id,
                source="check_payable"
            )
    
            result = db.execute(text("""
                INSERT INTO checks_payable (
                    check_number, beneficiary_name, bank_name, branch_name, amount, currency,
                    issue_date, due_date, party_id, treasury_account_id, payment_voucher_id,
                    journal_entry_id, status, notes, branch_id, created_by, exchange_rate, party_site_id
                ) VALUES (
                    :check_number, :beneficiary_name, :bank_name, :branch_name, :amount, :currency,
                    :issue_date, :due_date, :party_id, :treasury_id, :payment_voucher_id,
                    :je_id, 'issued', :notes, :branch_id, :user_id, :exchange_rate, :party_site_id
                ) RETURNING id
            """), {
                "check_number": data["check_number"],
                "beneficiary_name": data.get("beneficiary_name", ""),
                "bank_name": data.get("bank_name", ""),
                "branch_name": data.get("branch_name", ""),
                "amount": str(amount),
                "currency": data.get("currency", get_base_currency(db)),
                "issue_date": data["issue_date"],
                "due_date": data["due_date"],
                "party_id": data.get("party_id"),
                "treasury_id": data.get("treasury_account_id"),
                "payment_voucher_id": data.get("payment_voucher_id"),
                "je_id": je_id,
                "notes": data.get("notes", ""),
                "branch_id": branch_id,
                "user_id": current_user.id,
                "exchange_rate": str(_dec(data.get("exchange_rate", 1))),
                "party_site_id": data.get("party_site_id"),
            }).fetchone()
    
            log_activity(db, current_user.id, current_user.username, "create", "checks_payable", str(result.id),
                         {"check_number": data["check_number"], "amount": str(amount)})
            return {"id": result.id, "message": i18n_message("check_registered", request)}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/payable/{check_id}/clear", dependencies=[Depends(require_permission("treasury.create"))], response_model=Dict[str, Any])
def clear_check_payable(check_id: int, data: dict, request: Request, current_user=Depends(get_current_user)):
    """
    Mark check as cleared (presented and paid by bank).
    GL: Dr. Checks Payable (2105) / Cr. Bank
    """
    with transactional(current_user.company_id) as db:
        try:
            # F-NEW-085 (R-MISSING-IDEMPOTENCY) — PR16-fix: replay probe
            # before state guard so retries echo a 200 instead of 400
            # check_not_issued.
            idempotency_key = request.headers.get("Idempotency-Key")
            prior = (
                find_je_by_idempotency_key(db, idempotency_key)
                if idempotency_key
                else None
            ) or find_je_by_source(
                db, source="check_clearance", source_id=check_id
            )
            if prior is not None:
                return {
                    "message": i18n_message("check_cleared_success", request),
                    "idempotent": True,
                    "journal_id": prior[0],
                    "entry_number": prior[1],
                }

            check = db.execute(text("SELECT * FROM checks_payable WHERE id = :id FOR UPDATE"), {"id": check_id}).fetchone()
            if not check:
                raise HTTPException(**http_error(404, "check_not_found"))
                
            branch_id = validate_branch_access(current_user, check.branch_id)
            
            if check.status != 'issued':
                raise HTTPException(**http_error(400, "check_not_issued", request))
    
            clearance_date = data.get("clearance_date", str(date.today()))
            treasury_id = data.get("treasury_account_id") or check.treasury_account_id
    
            if not treasury_id:
                raise HTTPException(**http_error(400, "treasury_or_bank_required"))
    
            treasury = validate_treasury_account_access(db, current_user, treasury_id, branch_id)
    
            checks_pay_account = db.execute(text("SELECT id FROM accounts WHERE account_code = '2105' LIMIT 1")).fetchone()
            if not checks_pay_account:
                raise HTTPException(**http_error(500, "checks_payable_account_not_found", request))
    
            amount = _dec(check.amount).quantize(_D2, ROUND_HALF_UP)
    
            check_fiscal_period_open(db, clearance_date)
            je_lines = [
                {
                    "account_id": checks_pay_account.id,
                    "debit": _dec(amount),
                    "credit": 0,
                    "description": f"صرف شيك {check.check_number}"
                },
                {
                    "account_id": treasury["gl_account_id"],
                    "debit": 0,
                    "credit": _dec(amount),
                    "description": f"صرف شيك {check.check_number}"
                },
            ]
    
            clear_je_id, _ = gl_create_journal_entry(
                db=db,
                company_id=current_user.company_id,
                date=clearance_date,
                description=f"صرف شيك رقم {check.check_number}",
                lines=je_lines,
                user_id=current_user.id,
                branch_id=check.branch_id,
                source="check_clearance",
                source_id=check_id,
                idempotency_key=idempotency_key,
            )
    
            # T1.3a idempotent recompute
            from utils.treasury_balance import recalc_treasury_from_gl
            recalc_treasury_from_gl(db, treasury_id)
    
            db.execute(text("""
                UPDATE checks_payable SET status = 'cleared', clearance_date = :cdate,
                    clearance_journal_id = :je_id, treasury_account_id = COALESCE(:treasury_id, treasury_account_id),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """), {"id": check_id, "cdate": clearance_date, "je_id": clear_je_id, "treasury_id": treasury_id})
            log_activity(db, current_user.id, current_user.username, "clear", "checks_payable", str(check_id),
                         {"clearance_date": clearance_date})
            return {"message": i18n_message("check_dispensed_success", request)}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/payable/{check_id}/bounce", dependencies=[Depends(require_permission("treasury.create"))], response_model=Dict[str, Any])
def bounce_check_payable(check_id: int, data: dict, request: Request, current_user=Depends(get_current_user)):
    """
    Mark issued check as bounced.
    GL: Dr. Checks Payable (2105) / Cr. Accounts Payable
    """
    with transactional(current_user.company_id) as db:
        try:
            # F-NEW-085 (R-MISSING-IDEMPOTENCY) — PR16-fix: replay probe
            # before state guard.
            idempotency_key = request.headers.get("Idempotency-Key")
            prior = (
                find_je_by_idempotency_key(db, idempotency_key)
                if idempotency_key
                else None
            ) or find_je_by_source(
                db, source="check_payable_bounce", source_id=check_id
            )
            if prior is not None:
                return {
                    "message": i18n_message("check_bounced_success", request),
                    "idempotent": True,
                    "journal_id": prior[0],
                    "entry_number": prior[1],
                }

            check = db.execute(text("SELECT * FROM checks_payable WHERE id = :id FOR UPDATE"), {"id": check_id}).fetchone()
            if not check:
                raise HTTPException(**http_error(404, "check_not_found"))
                
            branch_id = validate_branch_access(current_user, check.branch_id)
            
            if check.status not in ('issued', 'cleared'):
                raise HTTPException(**http_error(400, "check_cannot_bounce", request))
    
            bounce_reason = data.get("bounce_reason", "")
            bounce_date = data.get("bounce_date", str(date.today()))
            amount = _dec(check.amount).quantize(_D2, ROUND_HALF_UP)
    
            checks_pay_account = db.execute(text("SELECT id FROM accounts WHERE account_code = '2105' LIMIT 1")).fetchone()
            ap_account = db.execute(text(
                "SELECT id FROM accounts WHERE account_code IN ('2101', '2100') AND is_active = TRUE ORDER BY account_code LIMIT 1"
            )).fetchone()
    
            if not checks_pay_account or not ap_account:
                raise HTTPException(**http_error(500, "check_or_supplier_accounts_not_found", request))
    
            check_fiscal_period_open(db, bounce_date)
            bounce_je_id = None
    
            if check.status == 'cleared':
                # Cleared check bounced: reverse both issuance + clearance
                # Net reversal: Dr. Bank / Cr. AP
                treasury = validate_treasury_account_access(
                    db, current_user, check.treasury_account_id, branch_id
                ) if check.treasury_account_id else None
                if not treasury:
                    raise HTTPException(**http_error(400, "treasury_not_linked_to_check", request))
    
                je_lines = [
                    {
                        "account_id": treasury["gl_account_id"],
                        "debit": _dec(amount),
                        "credit": 0,
                        "description": f"ارتجاع شيك مصروف {check.check_number}"
                    },
                    {
                        "account_id": ap_account.id,
                        "debit": 0,
                        "credit": _dec(amount),
                        "description": f"ارتجاع شيك مصروف {check.check_number}"
                    },
                ]
    
                bounce_je_id, _ = gl_create_journal_entry(
                    db=db,
                    company_id=current_user.company_id,
                    date=bounce_date,
                    description=f"ارتجاع شيك صادر رقم {check.check_number} (مصروف سابقاً) - {bounce_reason}",
                    lines=je_lines,
                    user_id=current_user.id,
                    branch_id=check.branch_id,
                    source="check_payable_bounce",
                    source_id=check_id,
                    idempotency_key=idempotency_key,
                )
    
                # Treasury balance increases (money came back) — T1.3a idempotent recompute
                from utils.treasury_balance import recalc_treasury_from_gl
                recalc_treasury_from_gl(db, check.treasury_account_id)
            else:
                # Issued (not cleared) check bounced: reverse issuance only
                # Dr. 2105 / Cr. AP
                je_lines = [
                    {
                        "account_id": checks_pay_account.id,
                        "debit": _dec(amount),
                        "credit": 0,
                        "description": f"ارتجاع شيك صادر {check.check_number}"
                    },
                    {
                        "account_id": ap_account.id,
                        "debit": 0,
                        "credit": _dec(amount),
                        "description": f"ارتجاع شيك صادر {check.check_number}"
                    },
                ]
    
                bounce_je_id, _ = gl_create_journal_entry(
                    db=db,
                    company_id=current_user.company_id,
                    date=bounce_date,
                    description=f"ارتجاع شيك صادر رقم {check.check_number} - {bounce_reason}",
                    lines=je_lines,
                    user_id=current_user.id,
                    branch_id=check.branch_id,
                    source="check_payable_bounce",
                    source_id=check_id,
                    idempotency_key=idempotency_key,
                )
    
            db.execute(text("""
                UPDATE checks_payable SET status = 'bounced', bounce_date = :bdate,
                    bounce_reason = :reason, bounce_journal_id = :je_id, updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """), {"id": check_id, "bdate": bounce_date, "reason": bounce_reason, "je_id": bounce_je_id})
            log_activity(db, current_user.id, current_user.username, "bounce", "checks_payable", str(check_id),
                         {"bounce_reason": bounce_reason})
            return {"message": i18n_message("check_bounced_success", request)}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/payable/{check_id}/represent", dependencies=[Depends(require_permission("treasury.create"))], response_model=Dict[str, Any])
def represent_check_payable(check_id: int, request: Request, data: dict = {}, current_user=Depends(get_current_user)):
    """
    Re-present a bounced payable check.
    GL: Dr. Accounts Payable / Cr. Checks Payable (2105)
    Resets status to 'issued', increments re_presentation_count.
    """
    with transactional(current_user.company_id) as db:
        try:
            # F-NEW-085 (R-MISSING-IDEMPOTENCY) — PR16-fix: replay probe
            # before state guard.
            idempotency_key = request.headers.get("Idempotency-Key")
            prior = (
                find_je_by_idempotency_key(db, idempotency_key)
                if idempotency_key
                else None
            ) or find_je_by_source(
                db, source="check_payable_represent", source_id=check_id
            )
            if prior is not None:
                return {
                    "message": i18n_message("check_represented_success", request),
                    "idempotent": True,
                    "journal_id": prior[0],
                    "entry_number": prior[1],
                }

            check = db.execute(text("SELECT * FROM checks_payable WHERE id = :id FOR UPDATE"), {"id": check_id}).fetchone()
            if not check:
                raise HTTPException(**http_error(404, "check_not_found"))
    
            validate_branch_access(current_user, check.branch_id)
    
            if check.status != 'bounced':
                raise HTTPException(**http_error(400, "check_cannot_represent", request))
    
            represent_date = data.get("represent_date", str(date.today()))
            amount = _dec(check.amount).quantize(_D2, ROUND_HALF_UP)
    
            checks_pay_account = db.execute(text("SELECT id FROM accounts WHERE account_code = '2105' LIMIT 1")).fetchone()
            ap_account = db.execute(text(
                "SELECT id FROM accounts WHERE account_code IN ('2101', '2100') AND is_active = TRUE ORDER BY account_code LIMIT 1"
            )).fetchone()
    
            if not checks_pay_account or not ap_account:
                raise HTTPException(**http_error(500, "check_or_supplier_accounts_not_found", request))
    
            check_fiscal_period_open(db, represent_date)
    
            je_lines = [
                {"account_id": ap_account.id, "debit": _dec(amount), "credit": 0,
                 "description": f"إعادة تقديم شيك صادر {check.check_number}"},
                {"account_id": checks_pay_account.id, "debit": 0, "credit": _dec(amount),
                 "description": f"إعادة تقديم شيك صادر {check.check_number}"},
            ]
    
            re_je_id, _ = gl_create_journal_entry(
                db=db,
                company_id=current_user.company_id,
                date=represent_date,
                description=f"إعادة تقديم شيك صادر رقم {check.check_number}",
                lines=je_lines,
                user_id=current_user.id,
                branch_id=check.branch_id,
                source="check_payable_represent",
                source_id=check_id,
                idempotency_key=idempotency_key,
            )
    
            new_count = (check.re_presentation_count or 0) + 1
            db.execute(text("""
                UPDATE checks_payable
                SET status = 'issued',
                    bounce_date = NULL, bounce_reason = NULL, bounce_journal_id = NULL,
                    re_presentation_date = :rdate,
                    re_presentation_count = :rcount,
                    re_presentation_journal_id = :je_id,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """), {"id": check_id, "rdate": represent_date, "rcount": new_count, "je_id": re_je_id})
    
            log_activity(db, current_user.id, current_user.username, "represent", "checks_payable", str(check_id),
                         {"re_presentation_count": new_count, "represent_date": represent_date})
            return {"message": i18n_message("check_represented_success", request), "re_presentation_count": new_count}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ============================================================
# Due Checks Alerts (for both receivable and payable)
# ============================================================

@router.get("/due-alerts", dependencies=[Depends(require_permission("treasury.view"))], response_model=Dict[str, Any])
def get_due_checks_alerts(days_ahead: int = Query(7, ge=1, le=90), branch_id: Optional[int] = None,
                          current_user=Depends(get_current_user)):
    """Get checks due within the next N days"""
    with transactional(current_user.company_id) as db:
        try:
            params = {"days": days_ahead}
            cond = branch_scope_filter(current_user, branch_id, "branch_id", params)
    
            receivable = db.execute(text(f"""
                SELECT id, check_number, drawer_name as party, amount, due_date, 'receivable' as type
                FROM checks_receivable
                WHERE status = 'pending' AND due_date <= CURRENT_DATE + :days {cond}
                ORDER BY due_date
            """), params).fetchall()
    
            payable = db.execute(text(f"""
                SELECT id, check_number, beneficiary_name as party, amount, due_date, 'payable' as type
                FROM checks_payable
                WHERE status = 'issued' AND due_date <= CURRENT_DATE + :days {cond}
                ORDER BY due_date
            """), params).fetchall()
    
            alerts = []
            for r in receivable:
                alerts.append({
                    "id": r.id, "check_number": r.check_number, "party": r.party,
                    "amount": str(_dec(r.amount)), "due_date": str(r.due_date),
                    "type": "receivable", "is_overdue": r.due_date <= date.today()
                })
            for r in payable:
                alerts.append({
                    "id": r.id, "check_number": r.check_number, "party": r.party,
                    "amount": str(_dec(r.amount)), "due_date": str(r.due_date),
                    "type": "payable", "is_overdue": r.due_date <= date.today()
                })
    
            alerts.sort(key=lambda x: x["due_date"])
            return {"alerts": alerts, "total": len(alerts)}
        except Exception:
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))

# ============================================================
# Checks Aging Report (تقرير أعمار الشيكات)
# ============================================================

@router.get("/aging", dependencies=[Depends(require_permission("treasury.view"))], response_model=Dict[str, Any])
def checks_aging_report(
    check_type: Optional[str] = None,  # 'receivable', 'payable', or None for both
    branch_id: Optional[int] = None,
    current_user=Depends(get_current_user)
):
    """تقرير أعمار الشيكات — تصنيف حسب تاريخ الاستحقاق (0-30, 31-60, 61-90, 90+)"""
    with transactional(current_user.company_id) as db:
        try:
            params = {}
            cond = branch_scope_filter(current_user, branch_id, "branch_id", params)
    
            results = []
    
            if check_type in (None, "receivable"):
                rows = db.execute(text(f"""
                    SELECT
                        cr.id, cr.check_number, cr.drawer_name AS party_name,
                        cr.bank_name, cr.amount, cr.currency,
                        cr.issue_date, cr.due_date, cr.status,
                        CURRENT_DATE - COALESCE(cr.due_date, cr.issue_date) AS days_old,
                        'receivable' AS check_type
                    FROM checks_receivable cr
                    WHERE cr.status IN ('pending', 'under_collection')
                    {cond}
                    ORDER BY days_old DESC
                """), params).fetchall()
    
                for r in rows:
                    days = int(r.days_old or 0)
                    if days > 90:
                        bucket = "90+"
                    elif days > 60:
                        bucket = "61-90"
                    elif days > 30:
                        bucket = "31-60"
                    else:
                        bucket = "0-30"
                    results.append({
                        "id": r.id, "check_number": r.check_number,
                        "party_name": r.party_name, "bank_name": r.bank_name,
                        "amount": str(_dec(r.amount)), "currency": r.currency or "",
                        "issue_date": str(r.issue_date) if r.issue_date else None,
                        "due_date": str(r.due_date) if r.due_date else None,
                        "status": r.status, "days_old": days, "bucket": bucket,
                        "check_type": "receivable",
                    })
    
            if check_type in (None, "payable"):
                rows = db.execute(text(f"""
                    SELECT
                        cp.id, cp.check_number, cp.beneficiary_name AS party_name,
                        cp.bank_name, cp.amount, cp.currency,
                        cp.issue_date, cp.due_date, cp.status,
                        CURRENT_DATE - COALESCE(cp.due_date, cp.issue_date) AS days_old,
                        'payable' AS check_type
                    FROM checks_payable cp
                    WHERE cp.status = 'issued'
                    {cond}
                    ORDER BY days_old DESC
                """), params).fetchall()
    
                for r in rows:
                    days = int(r.days_old or 0)
                    if days > 90:
                        bucket = "90+"
                    elif days > 60:
                        bucket = "61-90"
                    elif days > 30:
                        bucket = "31-60"
                    else:
                        bucket = "0-30"
                    results.append({
                        "id": r.id, "check_number": r.check_number,
                        "party_name": r.party_name, "bank_name": r.bank_name,
                        "amount": str(_dec(r.amount)), "currency": r.currency or "",
                        "issue_date": str(r.issue_date) if r.issue_date else None,
                        "due_date": str(r.due_date) if r.due_date else None,
                        "status": r.status, "days_old": days, "bucket": bucket,
                        "check_type": "payable",
                    })
    
            results.sort(key=lambda x: x["days_old"], reverse=True)
    
            # Build bucket summary using Decimal for accumulation
            buckets = {"0-30": {"receivable": _dec(0), "payable": _dec(0)}, "31-60": {"receivable": _dec(0), "payable": _dec(0)},
                       "61-90": {"receivable": _dec(0), "payable": _dec(0)}, "90+": {"receivable": _dec(0), "payable": _dec(0)}}
            for r in results:
                buckets[r["bucket"]][r["check_type"]] += _dec(r["amount"])
            # F-NEW-083 (R-FLOAT-MONEY, Req 8.5): emit Decimal as canonical
            # strings — both ``receivable`` and ``payable`` aggregates are
            # money axes that must preserve cent precision over the wire.
            bucket_summary = {k: {"receivable": str(v["receivable"]), "payable": str(v["payable"])} for k, v in buckets.items()}
    
            return {
                "checks": results,
                "total": len(results),
                "bucket_summary": bucket_summary,
            }
        except Exception:
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ===================== B3: Check Status Lifecycle Log =====================

@router.get("/status-log/{check_type}/{check_id}", dependencies=[Depends(require_permission("treasury.view"))], response_model=List[Dict[str, Any]])
def get_check_status_log(check_type: str, check_id: int, current_user=Depends(get_current_user)):
    """سجل دورة حياة الشيك"""
    with transactional(current_user.company_id) as conn:
        try:
            rows = conn.execute(text("""
                SELECT csl.*, u.full_name as changed_by_name
                FROM check_status_log csl
                LEFT JOIN users u ON u.id = csl.changed_by
                WHERE csl.check_type = :ct AND csl.check_id = :cid
                ORDER BY csl.changed_at DESC
            """), {"ct": check_type, "cid": check_id}).fetchall()
            return [dict(r._mapping) for r in rows]
        except Exception:
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.get("/status-log/summary", dependencies=[Depends(require_permission("treasury.view"))], response_model=List[Dict[str, Any]])
def check_status_summary(current_user=Depends(get_current_user)):
    """ملخص تغييرات حالة الشيكات"""
    with transactional(current_user.company_id) as conn:
        try:
            rows = conn.execute(text("""
                SELECT check_type, old_status, new_status, COUNT(*) as cnt
                FROM check_status_log
                WHERE changed_at >= NOW() - INTERVAL '30 days'
                GROUP BY check_type, old_status, new_status
                ORDER BY cnt DESC
            """)).fetchall()
            return [dict(r._mapping) for r in rows]
        except Exception:
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
