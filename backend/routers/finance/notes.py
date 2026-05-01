"""أوراق القبض والدفع - Notes Receivable & Payable"""
from decimal import Decimal, ROUND_HALF_UP
from fastapi import APIRouter, Depends, HTTPException
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import date, timedelta
from pydantic import BaseModel

from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import require_permission, validate_branch_access, require_module
from utils.accounting import get_base_currency
from utils.fiscal_lock import check_fiscal_period_open
from utils.audit import log_activity
from utils.treasury_gl import ensure_treasury_gl_accounts
import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notes", tags=["Notes Receivable/Payable"], dependencies=[Depends(require_module("treasury"))])

_D2 = Decimal('0.01')


def _dec(v):
    return Decimal(str(v or 0))


# ─── Schemas ───

class NoteReceivableCreate(BaseModel):
    note_number: str
    drawer_name: Optional[str] = None
    bank_name: Optional[str] = None
    amount: float
    currency: Optional[str] = None
    exchange_rate: Optional[float] = 1.0
    issue_date: Optional[str] = None
    due_date: str
    maturity_date: Optional[str] = None
    party_id: Optional[int] = None
    treasury_account_id: Optional[int] = None
    notes: Optional[str] = None
    branch_id: Optional[int] = None


class NotePayableCreate(BaseModel):
    note_number: str
    beneficiary_name: Optional[str] = None
    bank_name: Optional[str] = None
    amount: float
    currency: Optional[str] = None
    exchange_rate: Optional[float] = 1.0
    issue_date: Optional[str] = None
    due_date: str
    maturity_date: Optional[str] = None
    party_id: Optional[int] = None
    treasury_account_id: Optional[int] = None
    notes: Optional[str] = None
    branch_id: Optional[int] = None


# ─── Helper: ensure GL accounts ───

def _ensure_notes_accounts(db):
    """Ensure accounts 1210 (Notes Receivable) and 2110 (Notes Payable) exist."""
    for code, name, name_en, acc_type in [
        ('1210', 'أوراق قبض', 'Notes Receivable', 'asset'),
        ('2110', 'أوراق دفع', 'Notes Payable', 'liability'),
    ]:
        existing = db.execute(text(
            "SELECT id FROM accounts WHERE account_code = :code"
        ), {"code": code}).fetchone()
        if not existing:
            parent_code = code[:2] + '00'
            parent = db.execute(text(
                "SELECT id FROM accounts WHERE account_code = :code"
            ), {"code": parent_code}).fetchone()
            db.execute(text("""
                INSERT INTO accounts (account_number, account_code, name, name_en, account_type, parent_id, is_active, currency)
                VALUES (:code, :code, :name, :name_en, :type, :pid, TRUE, :currency)
                ON CONFLICT (account_number) DO NOTHING
            """), {"code": code, "name": name, "name_en": name_en, "type": acc_type,
                   "pid": parent.id if parent else None, "currency": get_base_currency(db)})
            db.commit()


# ══════════════════════════════════════
#  NOTES RECEIVABLE (أوراق القبض)
# ══════════════════════════════════════

@router.get("/receivable", dependencies=[Depends(require_permission("treasury.view"))], response_model=List[Dict[str, Any]])
def list_notes_receivable(
    status_filter: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    # Validate branch access
    branch_id = validate_branch_access(current_user, branch_id)
    
    with transactional(current_user.company_id) as db:
        query = """
            SELECT n.*, p.name as party_name, t.name as treasury_name
            FROM notes_receivable n
            LEFT JOIN parties p ON n.party_id = p.id
            LEFT JOIN treasury_accounts t ON n.treasury_account_id = t.id
            WHERE 1=1
        """
        params = {}
        if status_filter:
            query += " AND n.status = :st"
            params["st"] = status_filter
        if branch_id:
            query += " AND n.branch_id = :bid"
            params["bid"] = branch_id
        query += " ORDER BY n.due_date ASC, n.id DESC"
        rows = db.execute(text(query), params).fetchall()
        return [dict(r._mapping) for r in rows]


@router.get("/receivable/summary/stats", dependencies=[Depends(require_permission("treasury.view"))], response_model=Dict[str, Any])
def receivable_stats(branch_id: Optional[int] = None, current_user: dict = Depends(get_current_user)):
    # Validate branch access
    branch_id = validate_branch_access(current_user, branch_id)
    
    with transactional(current_user.company_id) as db:
        base = "FROM notes_receivable WHERE 1=1"
        params = {}
        if branch_id:
            base += " AND branch_id = :bid"
            params["bid"] = branch_id
        
        pending = db.execute(text(f"SELECT COUNT(*), COALESCE(SUM(amount),0) {base} AND status='pending'"), params).fetchone()
        collected = db.execute(text(f"SELECT COUNT(*), COALESCE(SUM(amount),0) {base} AND status='collected'"), params).fetchone()
        protested = db.execute(text(f"SELECT COUNT(*), COALESCE(SUM(amount),0) {base} AND status='protested'"), params).fetchone()
        today = date.today().isoformat()
        overdue = db.execute(text(f"SELECT COUNT(*), COALESCE(SUM(amount),0) {base} AND status='pending' AND due_date < :today"), {**params, "today": today}).fetchone()
        
        return {
            "pending": {"count": pending[0], "total": float(_dec(pending[1]).quantize(_D2, ROUND_HALF_UP))},
            "collected": {"count": collected[0], "total": float(_dec(collected[1]).quantize(_D2, ROUND_HALF_UP))},
            "protested": {"count": protested[0], "total": float(_dec(protested[1]).quantize(_D2, ROUND_HALF_UP))},
            "overdue": {"count": overdue[0], "total": float(_dec(overdue[1]).quantize(_D2, ROUND_HALF_UP))},
        }


@router.get("/receivable/{note_id}", dependencies=[Depends(require_permission("treasury.view"))], response_model=Dict[str, Any])
def get_note_receivable(note_id: int, current_user: dict = Depends(get_current_user)):
    with transactional(current_user.company_id) as db:
        row = db.execute(text("""
            SELECT n.*, p.name as party_name, t.name as treasury_name
            FROM notes_receivable n
            LEFT JOIN parties p ON n.party_id = p.id
            LEFT JOIN treasury_accounts t ON n.treasury_account_id = t.id
            WHERE n.id = :id
        """), {"id": note_id}).fetchone()
        if not row:
            raise HTTPException(**http_error(404, "sheet_not_found"))
        
        # Validate branch access
        validate_branch_access(current_user, row.branch_id)
        
        return dict(row._mapping)


@router.post("/receivable", status_code=201, dependencies=[Depends(require_permission("treasury.create"))], response_model=Dict[str, Any])
def create_note_receivable(data: NoteReceivableCreate, current_user: dict = Depends(get_current_user)):
    """إنشاء ورقة قبض + قيد: مدين 1210 / دائن حساب العميل"""
    # Validate branch access
    validate_branch_access(current_user, data.branch_id)
    
    with transactional(current_user.company_id) as db:
        try:
            ensure_treasury_gl_accounts(db, user_id=current_user.id, username=current_user.username)
            
            nr_account = db.execute(text("SELECT id FROM accounts WHERE account_code = '1210'")).fetchone()
            ar_account = db.execute(text(
                "SELECT id FROM accounts WHERE account_code IN ('1201', '1200') AND is_active = TRUE ORDER BY account_code LIMIT 1"
            )).fetchone()
            if not nr_account:
                raise HTTPException(status_code=500, detail="حساب أوراق القبض 1210 غير موجود")
            if not ar_account:
                raise HTTPException(status_code=500, detail="حساب العملاء (1200/1201) غير موجود")
    
            # Create journal entry
            check_fiscal_period_open(db, data.issue_date or date.today().isoformat())
    
            # Build and validate journal lines
            amt = float(_dec(data.amount).quantize(_D2, ROUND_HALF_UP))
            je_lines = [
                {"account_id": nr_account.id, "debit": amt, "credit": 0, "description": f"ورقة قبض {data.note_number}", "currency": data.currency},
                {"account_id": ar_account.id, "debit": 0, "credit": amt, "description": f"ورقة قبض {data.note_number}", "currency": data.currency},
            ]
            
            from services.gl_service import create_journal_entry as gl_create_journal_entry
            je_id, _ = gl_create_journal_entry(
                db=db,
                company_id=current_user.company_id,
                date=data.issue_date or date.today().isoformat(),
                description=f"ورقة قبض - {data.note_number} - {data.drawer_name or ''}",
                lines=je_lines,
                user_id=current_user.id,
                branch_id=data.branch_id,
                source="note_receivable"
            )
    
            note_id = db.execute(text("""
                INSERT INTO notes_receivable (
                    note_number, drawer_name, bank_name, amount, currency,
                    issue_date, due_date, maturity_date, party_id, treasury_account_id,
                    journal_entry_id, status, notes, branch_id, created_by, exchange_rate
                ) VALUES (
                    :num, :drawer, :bank, :amt, :cur,
                    :issue, :due, :mat, :pid, :tid,
                    :je, 'pending', :notes, :bid, :uid, :exchange_rate
                ) RETURNING id
            """), {
                "num": data.note_number, "drawer": data.drawer_name, "bank": data.bank_name,
                "amt": amt, "cur": data.currency,
                "issue": data.issue_date, "due": data.due_date, "mat": data.maturity_date or data.due_date,
                "pid": data.party_id, "tid": data.treasury_account_id,
                "je": je_id, "notes": data.notes, "bid": data.branch_id, "uid": current_user.id,
                "exchange_rate": float(_dec(data.exchange_rate or 1)),
            }).scalar()
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="notes.receivable.create",
                         resource_type="note_receivable", resource_id=str(note_id),
                         details={"note_number": data.note_number, "amount": amt},
                         branch_id=data.branch_id)
            return {"id": note_id, "journal_entry_id": je_id, "message": "تم إنشاء ورقة القبض بنجاح"}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/receivable/{note_id}/collect", dependencies=[Depends(require_permission("treasury.create"))], response_model=Dict[str, Any])
def collect_note_receivable(note_id: int, data: dict = None,
                            current_user: dict = Depends(get_current_user)):
    """تحصيل ورقة قبض: مدين البنك / دائن 1210"""
    if data is None:
        data = {}
    collection_date = data.get("collection_date")
    treasury_account_id = data.get("treasury_account_id")
    if treasury_account_id:
        treasury_account_id = int(treasury_account_id)
    with transactional(current_user.company_id) as db:
        try:
            note = db.execute(text("SELECT * FROM notes_receivable WHERE id = :id FOR UPDATE"), {"id": note_id}).fetchone()
            if not note:
                raise HTTPException(**http_error(404, "sheet_not_found"))
                
            # Validate branch access
            validate_branch_access(current_user, note.branch_id)
            
            if note.status != 'pending':
                raise HTTPException(status_code=400, detail="لا يمكن تحصيل ورقة غير معلقة")
    
            tid = treasury_account_id or note.treasury_account_id
            if not tid:
                raise HTTPException(**http_error(400, "treasury_or_bank_required"))
    
            treasury = db.execute(text("SELECT gl_account_id FROM treasury_accounts WHERE id = :id"), {"id": tid}).fetchone()
            if not treasury:
                raise HTTPException(**http_error(404, "treasury_account_not_found"))
    
            nr_account = db.execute(text("SELECT id FROM accounts WHERE account_code = '1210'")).fetchone()
            coll_date = collection_date or date.today().isoformat()
    
            check_fiscal_period_open(db, coll_date)
    
            # Build and validate journal lines
            amt = float(_dec(note.amount).quantize(_D2, ROUND_HALF_UP))
            je_lines = [
                {"account_id": treasury.gl_account_id, "debit": amt, "credit": 0, "description": f"تحصيل ورقة {note.note_number}", "currency": note.currency},
                {"account_id": nr_account.id, "debit": 0, "credit": amt, "description": f"تحصيل ورقة {note.note_number}", "currency": note.currency},
            ]
    
            from services.gl_service import create_journal_entry as gl_create_journal_entry
            je_id, _ = gl_create_journal_entry(
                db=db,
                company_id=current_user.company_id,
                date=coll_date,
                description=f"تحصيل ورقة قبض {note.note_number}",
                lines=je_lines,
                user_id=current_user.id,
                branch_id=note.branch_id,
                source="note_collection",
                source_id=note_id
            )
    
            # Update treasury balance — T1.3a idempotent recompute
            from utils.treasury_balance import recalc_treasury_from_gl
            recalc_treasury_from_gl(db, tid)
    
            db.execute(text("""
                UPDATE notes_receivable 
                SET status = 'collected', collection_date = :date, collection_journal_id = :je, 
                    treasury_account_id = :tid, updated_at = NOW()
                WHERE id = :id
            """), {"date": coll_date, "je": je_id, "tid": tid, "id": note_id})
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="notes.receivable.collect",
                         resource_type="note_receivable", resource_id=str(note_id),
                         details={"note_number": note.note_number, "amount": amt},
                         branch_id=note.branch_id)
            return {"message": "تم تحصيل ورقة القبض بنجاح", "journal_entry_id": je_id}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/receivable/{note_id}/protest", dependencies=[Depends(require_permission("treasury.create"))], response_model=Dict[str, Any])
def protest_note_receivable(note_id: int, data: dict = None,
                            current_user: dict = Depends(get_current_user)):
    """رفض / بروتستو ورقة قبض: عكس القيد"""
    if data is None:
        data = {}
    protest_date = data.get("protest_date")
    reason = data.get("reason")
    with transactional(current_user.company_id) as db:
        try:
            note = db.execute(text("SELECT * FROM notes_receivable WHERE id = :id FOR UPDATE"), {"id": note_id}).fetchone()
            if not note:
                raise HTTPException(**http_error(404, "sheet_not_found"))
                
            # Validate branch access
            validate_branch_access(current_user, note.branch_id)
            
            if note.status != 'pending':
                raise HTTPException(status_code=400, detail="لا يمكن رفض ورقة غير معلقة")
    
            nr_account = db.execute(text("SELECT id FROM accounts WHERE account_code = '1210'")).fetchone()
            ar_account = db.execute(text(
                "SELECT id FROM accounts WHERE account_code IN ('1201', '1200') AND is_active = TRUE ORDER BY account_code LIMIT 1"
            )).fetchone()
            if not nr_account or not ar_account:
                raise HTTPException(status_code=500, detail="حسابات أوراق القبض أو العملاء غير موجودة")
            pdate = protest_date or date.today().isoformat()
    
            check_fiscal_period_open(db, pdate)
    
            # Build and validate journal lines
            amt = float(_dec(note.amount).quantize(_D2, ROUND_HALF_UP))
            je_lines = [
                {"account_id": ar_account.id, "debit": amt, "credit": 0, "description": f"رفض ورقة {note.note_number}", "currency": note.currency},
                {"account_id": nr_account.id, "debit": 0, "credit": amt, "description": f"رفض ورقة {note.note_number}", "currency": note.currency},
            ]
    
            from services.gl_service import create_journal_entry as gl_create_journal_entry
            je_id, _ = gl_create_journal_entry(
                db=db,
                company_id=current_user.company_id,
                date=pdate,
                description=f"رفض ورقة قبض {note.note_number} - {reason or ''}",
                lines=je_lines,
                user_id=current_user.id,
                branch_id=note.branch_id,
                source="note_protest",
                source_id=note_id
            )
    
            db.execute(text("""
                UPDATE notes_receivable
                SET status = 'protested', protest_date = :date, protest_reason = :reason,
                    protest_journal_id = :je, updated_at = NOW()
                WHERE id = :id
            """), {"date": pdate, "reason": reason, "je": je_id, "id": note_id})
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="notes.receivable.protest",
                         resource_type="note_receivable", resource_id=str(note_id),
                         details={"note_number": note.note_number, "reason": reason},
                         branch_id=note.branch_id)
            return {"message": "تم رفض ورقة القبض", "journal_entry_id": je_id}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ══════════════════════════════════════
#  NOTES PAYABLE (أوراق الدفع)
# ══════════════════════════════════════

@router.get("/payable", dependencies=[Depends(require_permission("treasury.view"))], response_model=List[Dict[str, Any]])
def list_notes_payable(
    status_filter: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    # Validate branch access
    branch_id = validate_branch_access(current_user, branch_id)
    
    with transactional(current_user.company_id) as db:
        query = """
            SELECT n.*, p.name as party_name, t.name as treasury_name
            FROM notes_payable n
            LEFT JOIN parties p ON n.party_id = p.id
            LEFT JOIN treasury_accounts t ON n.treasury_account_id = t.id
            WHERE 1=1
        """
        params = {}
        if status_filter:
            query += " AND n.status = :st"
            params["st"] = status_filter
        if branch_id:
            query += " AND n.branch_id = :bid"
            params["bid"] = branch_id
        query += " ORDER BY n.due_date ASC, n.id DESC"
        rows = db.execute(text(query), params).fetchall()
        return [dict(r._mapping) for r in rows]


@router.get("/payable/summary/stats", dependencies=[Depends(require_permission("treasury.view"))], response_model=Dict[str, Any])
def payable_stats(branch_id: Optional[int] = None, current_user: dict = Depends(get_current_user)):
    # Validate branch access
    branch_id = validate_branch_access(current_user, branch_id)
    
    with transactional(current_user.company_id) as db:
        base = "FROM notes_payable WHERE 1=1"
        params = {}
        if branch_id:
            base += " AND branch_id = :bid"
            params["bid"] = branch_id

        issued = db.execute(text(f"SELECT COUNT(*), COALESCE(SUM(amount),0) {base} AND status='issued'"), params).fetchone()
        paid = db.execute(text(f"SELECT COUNT(*), COALESCE(SUM(amount),0) {base} AND status='paid'"), params).fetchone()
        protested = db.execute(text(f"SELECT COUNT(*), COALESCE(SUM(amount),0) {base} AND status='protested'"), params).fetchone()
        today = date.today().isoformat()
        overdue = db.execute(text(f"SELECT COUNT(*), COALESCE(SUM(amount),0) {base} AND status='issued' AND due_date < :today"), {**params, "today": today}).fetchone()

        return {
            "issued": {"count": issued[0], "total": float(_dec(issued[1]).quantize(_D2, ROUND_HALF_UP))},
            "paid": {"count": paid[0], "total": float(_dec(paid[1]).quantize(_D2, ROUND_HALF_UP))},
            "protested": {"count": protested[0], "total": float(_dec(protested[1]).quantize(_D2, ROUND_HALF_UP))},
            "overdue": {"count": overdue[0], "total": float(_dec(overdue[1]).quantize(_D2, ROUND_HALF_UP))},
        }


@router.get("/payable/{note_id}", dependencies=[Depends(require_permission("treasury.view"))], response_model=Dict[str, Any])
def get_note_payable(note_id: int, current_user: dict = Depends(get_current_user)):
    with transactional(current_user.company_id) as db:
        row = db.execute(text("""
            SELECT n.*, p.name as party_name, t.name as treasury_name
            FROM notes_payable n
            LEFT JOIN parties p ON n.party_id = p.id
            LEFT JOIN treasury_accounts t ON n.treasury_account_id = t.id
            WHERE n.id = :id
        """), {"id": note_id}).fetchone()
        if not row:
            raise HTTPException(**http_error(404, "sheet_not_found"))
            
        # Validate branch access
        validate_branch_access(current_user, row.branch_id)
        
        return dict(row._mapping)


@router.post("/payable", status_code=201, dependencies=[Depends(require_permission("treasury.create"))], response_model=Dict[str, Any])
def create_note_payable(data: NotePayableCreate, current_user: dict = Depends(get_current_user)):
    """إنشاء ورقة دفع + قيد: مدين حساب المورد / دائن 2110"""
    # Validate branch access
    validate_branch_access(current_user, data.branch_id)
    
    with transactional(current_user.company_id) as db:
        try:
            ensure_treasury_gl_accounts(db, user_id=current_user.id, username=current_user.username)
    
            np_account = db.execute(text("SELECT id FROM accounts WHERE account_code = '2110'")).fetchone()
            ap_account = db.execute(text(
                "SELECT id FROM accounts WHERE account_code IN ('2101', '2100') AND is_active = TRUE ORDER BY account_code LIMIT 1"
            )).fetchone()
            if not np_account:
                raise HTTPException(status_code=500, detail="حساب أوراق الدفع 2110 غير موجود")
            if not ap_account:
                raise HTTPException(status_code=500, detail="حساب الموردين (2100/2101) غير موجود")
    
            check_fiscal_period_open(db, data.issue_date or date.today().isoformat())
    
            # Build and validate journal lines
            amt = float(_dec(data.amount).quantize(_D2, ROUND_HALF_UP))
            je_lines = [
                {"account_id": ap_account.id, "debit": amt, "credit": 0, "description": f"ورقة دفع {data.note_number}", "currency": data.currency},
                {"account_id": np_account.id, "debit": 0, "credit": amt, "description": f"ورقة دفع {data.note_number}", "currency": data.currency},
            ]
    
            from services.gl_service import create_journal_entry as gl_create_journal_entry
            je_id, _ = gl_create_journal_entry(
                db=db,
                company_id=current_user.company_id,
                date=data.issue_date or date.today().isoformat(),
                description=f"ورقة دفع - {data.note_number} - {data.beneficiary_name or ''}",
                lines=je_lines,
                user_id=current_user.id,
                branch_id=data.branch_id,
                source="note_payable"
            )
    
            note_id = db.execute(text("""
                INSERT INTO notes_payable (
                    note_number, beneficiary_name, bank_name, amount, currency,
                    issue_date, due_date, maturity_date, party_id, treasury_account_id,
                    journal_entry_id, status, notes, branch_id, created_by, exchange_rate
                ) VALUES (
                    :num, :bene, :bank, :amt, :cur,
                    :issue, :due, :mat, :pid, :tid,
                    :je, 'issued', :notes, :bid, :uid, :exchange_rate
                ) RETURNING id
            """), {
                "num": data.note_number, "bene": data.beneficiary_name, "bank": data.bank_name,
                "amt": amt, "cur": data.currency,
                "issue": data.issue_date, "due": data.due_date, "mat": data.maturity_date or data.due_date,
                "pid": data.party_id, "tid": data.treasury_account_id,
                "je": je_id, "notes": data.notes, "bid": data.branch_id, "uid": current_user.id,
                "exchange_rate": float(_dec(data.exchange_rate or 1)),
            }).scalar()
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="notes.payable.create",
                         resource_type="note_payable", resource_id=str(note_id),
                         details={"note_number": data.note_number, "amount": amt},
                         branch_id=data.branch_id)
            return {"id": note_id, "journal_entry_id": je_id, "message": "تم إنشاء ورقة الدفع بنجاح"}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/payable/{note_id}/pay", dependencies=[Depends(require_permission("treasury.create"))], response_model=Dict[str, Any])
def pay_note_payable(note_id: int, data: dict = None,
                     current_user: dict = Depends(get_current_user)):
    """سداد ورقة دفع: مدين 2110 / دائن البنك"""
    if data is None:
        data = {}
    payment_date = data.get("payment_date")
    treasury_account_id = data.get("treasury_account_id")
    if treasury_account_id:
        treasury_account_id = int(treasury_account_id)
    with transactional(current_user.company_id) as db:
        try:
            note = db.execute(text("SELECT * FROM notes_payable WHERE id = :id FOR UPDATE"), {"id": note_id}).fetchone()
            if not note:
                raise HTTPException(**http_error(404, "sheet_not_found"))
                
            # Validate branch access
            validate_branch_access(current_user, note.branch_id)
            
            if note.status != 'issued':
                raise HTTPException(status_code=400, detail="لا يمكن سداد ورقة غير صادرة")
    
            tid = treasury_account_id or note.treasury_account_id
            if not tid:
                raise HTTPException(**http_error(400, "treasury_or_bank_required"))
    
            treasury = db.execute(text("SELECT gl_account_id FROM treasury_accounts WHERE id = :id"), {"id": tid}).fetchone()
            if not treasury:
                raise HTTPException(**http_error(404, "treasury_account_not_found"))
    
            np_account = db.execute(text("SELECT id FROM accounts WHERE account_code = '2110'")).fetchone()
            pay_date = payment_date or date.today().isoformat()
    
            check_fiscal_period_open(db, pay_date)
    
            # Build and validate journal lines
            amt = float(_dec(note.amount).quantize(_D2, ROUND_HALF_UP))
            je_lines = [
                {"account_id": np_account.id, "debit": amt, "credit": 0, "description": f"سداد ورقة {note.note_number}", "currency": note.currency},
                {"account_id": treasury.gl_account_id, "debit": 0, "credit": amt, "description": f"سداد ورقة {note.note_number}", "currency": note.currency},
            ]
    
            from services.gl_service import create_journal_entry as gl_create_journal_entry
            je_id, _ = gl_create_journal_entry(
                db=db,
                company_id=current_user.company_id,
                date=pay_date,
                description=f"سداد ورقة دفع {note.note_number}",
                lines=je_lines,
                user_id=current_user.id,
                branch_id=note.branch_id,
                source="note_payment",
                source_id=note_id
            )
    
            # Update treasury balance — T1.3a idempotent recompute
            from utils.treasury_balance import recalc_treasury_from_gl
            recalc_treasury_from_gl(db, tid)
    
            db.execute(text("""
                UPDATE notes_payable 
                SET status = 'paid', payment_date = :date, payment_journal_id = :je,
                    treasury_account_id = :tid, updated_at = NOW()
                WHERE id = :id
            """), {"date": pay_date, "je": je_id, "tid": tid, "id": note_id})
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="notes.payable.pay",
                         resource_type="note_payable", resource_id=str(note_id),
                         details={"note_number": note.note_number, "amount": amt},
                         branch_id=note.branch_id)
            return {"message": "تم سداد ورقة الدفع بنجاح", "journal_entry_id": je_id}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/payable/{note_id}/protest", dependencies=[Depends(require_permission("treasury.create"))], response_model=Dict[str, Any])
def protest_note_payable(note_id: int, data: dict = None,
                         current_user: dict = Depends(get_current_user)):
    """رفض / بروتستو ورقة دفع: عكس القيد"""
    if data is None:
        data = {}
    protest_date = data.get("protest_date")
    reason = data.get("reason")
    with transactional(current_user.company_id) as db:
        try:
            note = db.execute(text("SELECT * FROM notes_payable WHERE id = :id FOR UPDATE"), {"id": note_id}).fetchone()
            if not note:
                raise HTTPException(**http_error(404, "sheet_not_found"))
                
            # Validate branch access
            validate_branch_access(current_user, note.branch_id)
            
            if note.status != 'issued':
                raise HTTPException(status_code=400, detail="لا يمكن رفض ورقة غير صادرة")
    
            np_account = db.execute(text("SELECT id FROM accounts WHERE account_code = '2110'")).fetchone()
            ap_account = db.execute(text(
                "SELECT id FROM accounts WHERE account_code IN ('2101', '2100') AND is_active = TRUE ORDER BY account_code LIMIT 1"
            )).fetchone()
            if not np_account or not ap_account:
                raise HTTPException(status_code=500, detail="حسابات أوراق الدفع أو الموردين غير موجودة")
            pdate = protest_date or date.today().isoformat()
    
            check_fiscal_period_open(db, pdate)
    
            # Build and validate journal lines
            amt = float(_dec(note.amount).quantize(_D2, ROUND_HALF_UP))
            je_lines = [
                {"account_id": np_account.id, "debit": amt, "credit": 0, "description": f"رفض ورقة {note.note_number}", "currency": note.currency},
                {"account_id": ap_account.id, "debit": 0, "credit": amt, "description": f"رفض ورقة {note.note_number}", "currency": note.currency},
            ]
    
            from services.gl_service import create_journal_entry as gl_create_journal_entry
            je_id, _ = gl_create_journal_entry(
                db=db,
                company_id=current_user.company_id,
                date=pdate,
                description=f"رفض ورقة دفع {note.note_number} - {reason or ''}",
                lines=je_lines,
                user_id=current_user.id,
                branch_id=note.branch_id,
                source="note_protest",
                source_id=note_id
            )
    
            db.execute(text("""
                UPDATE notes_payable
                SET status = 'protested', protest_date = :date, protest_reason = :reason,
                    protest_journal_id = :je, updated_at = NOW()
                WHERE id = :id
            """), {"date": pdate, "reason": reason, "je": je_id, "id": note_id})
    
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="notes.payable.protest",
                         resource_type="note_payable", resource_id=str(note_id),
                         details={"note_number": note.note_number, "reason": reason},
                         branch_id=note.branch_id)
            return {"message": "تم رفض ورقة الدفع", "journal_entry_id": je_id}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ─── Due Alerts (for both types) ───

@router.get("/due-alerts", dependencies=[Depends(require_permission("treasury.view"))], response_model=Dict[str, Any])
def notes_due_alerts(days_ahead: int = 7, current_user: dict = Depends(get_current_user)):
    """إشعارات الاستحقاق القادم"""
    with transactional(current_user.company_id) as db:
        cutoff = (date.today() + timedelta(days=days_ahead)).isoformat()
        today = date.today().isoformat()

        # Branch filtering
        branch_filter = ""
        params = {"cutoff": cutoff}
        user_role = current_user.role if hasattr(current_user, 'role') else current_user.get("role")
        user_branches = current_user.allowed_branches if hasattr(current_user, 'allowed_branches') else current_user.get("allowed_branches")
        if user_role != "admin" and user_branches:
             branch_filter = " AND n.branch_id = ANY(:branches)"
             params["branches"] = user_branches

        receivable_due = db.execute(text(f"""
            SELECT n.id, n.note_number, n.drawer_name as name, n.amount, n.currency, n.due_date,
                   'receivable' as type, p.name as party_name
            FROM notes_receivable n
            LEFT JOIN parties p ON n.party_id = p.id
            WHERE n.status = 'pending' AND n.due_date <= :cutoff {branch_filter}
            ORDER BY n.due_date
        """), params).fetchall()

        payable_due = db.execute(text(f"""
            SELECT n.id, n.note_number, n.beneficiary_name as name, n.amount, n.currency, n.due_date,
                   'payable' as type, p.name as party_name
            FROM notes_payable n
            LEFT JOIN parties p ON n.party_id = p.id
            WHERE n.status = 'issued' AND n.due_date <= :cutoff {branch_filter}
            ORDER BY n.due_date
        """), params).fetchall()

        alerts = []
        for row in receivable_due:
            d = dict(row._mapping)
            d["is_overdue"] = str(d["due_date"]) < today
            alerts.append(d)
        for row in payable_due:
            d = dict(row._mapping)
            d["is_overdue"] = str(d["due_date"]) < today
            alerts.append(d)

        alerts.sort(key=lambda x: str(x.get("due_date", "")))
        return alerts
