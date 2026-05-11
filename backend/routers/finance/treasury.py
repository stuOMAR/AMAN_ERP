"""
AMAN ERP - Treasury Router
إدارة الخزينة والمصروفات
"""

from fastapi import APIRouter, Depends, HTTPException, status
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import date
import logging

from decimal import Decimal, ROUND_HALF_UP

from database import get_db_connection
from routers.auth import get_current_user
from utils.permissions import branch_scope_filter, require_permission, require_module, validate_branch_access, validate_treasury_account_access, check_permission
from utils.audit import log_activity
from utils.fiscal_lock import check_fiscal_period_open
from utils.cache import cache
from utils.treasury_gl import ensure_treasury_gl_accounts
from utils.pii_encryption import encrypt_pii, decrypt_pii
from fastapi import Request
from schemas.treasury import TreasuryAccountCreate, TreasuryAccountResponse, TransactionCreate, TransactionResponse

_D2 = Decimal('0.01')
def _dec(v) -> Decimal:
    """Convert any numeric value to Decimal safely."""
    return Decimal(str(v)) if v is not None else Decimal('0')

router = APIRouter(prefix="/treasury", tags=["Treasury & Expenses"], dependencies=[Depends(require_module("treasury"))])
logger = logging.getLogger(__name__)


def _auto_create_capital_account(db, currency_code: str, current_user):
    """إنشاء حساب رأس المال للعملة تلقائياً — يتخطى إذا كان موجوداً"""
    try:
        # Find parent capital account (31)
        parent = db.execute(text("""
            SELECT id FROM accounts WHERE account_number = '31' AND is_header = TRUE LIMIT 1
        """)).fetchone()
        if not parent:
            return
        parent_id = parent[0]

        # Check if capital account for this currency already exists
        existing_acc = db.execute(text("""
            SELECT id FROM accounts 
            WHERE parent_id = :pid AND currency = :curr AND account_type = 'equity' AND is_header = FALSE
            LIMIT 1
        """), {"pid": parent_id, "curr": currency_code}).fetchone()

        if existing_acc:
            logger.info(f"Capital account for {currency_code} already exists (id={existing_acc[0]}), skipping")
            return

        # Find next available number
        existing = db.execute(text("""
            SELECT account_number FROM accounts
            WHERE parent_id = :pid AND account_number ~ '^31[0-9]{2}$'
            ORDER BY account_number DESC LIMIT 1
        """), {"pid": parent_id}).fetchone()

        next_num = str(int(existing[0]) + 1) if existing else "3101"

        # Get currency name
        cur_row = db.execute(text("SELECT name FROM currencies WHERE code = :code"), {"code": currency_code}).fetchone()
        cur_name = cur_row[0] if cur_row else currency_code

        db.execute(text("""
            INSERT INTO accounts (account_number, account_code, name, name_en, account_type, parent_id, currency, is_header, is_active)
            VALUES (:num, :code, :name, :name_en, 'equity', :pid, :curr, FALSE, TRUE)
        """), {
            "num": next_num, "code": next_num,
            "name": f"رأس المال - {cur_name}",
            "name_en": f"Capital - {currency_code}",
            "pid": parent_id, "curr": currency_code,
        })
        db.commit()
        logger.info(f"Auto-created capital account {next_num} for {currency_code}")
    except Exception as e:
        logger.warning(f"Failed to auto-create capital account for {currency_code}: {e}")
        db.rollback()


def _is_branch_privileged(current_user) -> bool:
    role = (getattr(current_user, 'role', '') or '').strip().lower()
    permissions = getattr(current_user, 'permissions', []) or []
    return (
        role in {'admin', 'system_admin', 'superuser', 'manager', 'gm', 'ceo', 'owner', 'chairman'}
        or '*' in permissions
        or check_permission(permissions, 'admin.branches')
        or check_permission(permissions, 'branches.manage')
    )


def _normalized_allowed_branches(current_user) -> List[int]:
    branch_ids = []
    for branch_id in getattr(current_user, 'allowed_branches', []) or []:
        try:
            branch_ids.append(int(branch_id))
        except (TypeError, ValueError):
            continue
    return sorted(set(branch_ids))


def _treasury_account_scope(current_user, requested_branch_id: Optional[int] = None):
    if requested_branch_id not in (None, ''):
        return validate_branch_access(current_user, requested_branch_id), None
    if _is_branch_privileged(current_user):
        return None, None
    allowed_branches = _normalized_allowed_branches(current_user)
    if allowed_branches:
        return None, allowed_branches
    return None, []

# --- Endpoints ---

@router.get("/accounts", response_model=List[TreasuryAccountResponse], dependencies=[Depends(require_permission("treasury.view"))])
def list_treasury_accounts(branch_id: Optional[int] = None, current_user = Depends(get_current_user)):
    """عرض حسابات الخزينة والبنوك مع فلترة حسب الفرع"""
    if not current_user.company_id:
         raise HTTPException(**http_error(400, ("company_required", request)))
    branch_id, allowed_branch_ids = _treasury_account_scope(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        query = """
            SELECT 
                ta.id, ta.name, ta.name_en, ta.account_type, ta.currency, 
                ta.gl_account_id, ta.branch_id, ta.bank_name, ta.account_number, 
                ta.iban, ta.is_active, ta.allow_overdraft,
                COALESCE(a.balance, 0) as current_balance,
                COALESCE(ta.current_balance, 0) as balance_in_currency,
                b.branch_name as branch_name,
                COALESCE(c.current_rate, 1.0) as exchange_rate
            FROM treasury_accounts ta
            LEFT JOIN branches b ON ta.branch_id = b.id
            LEFT JOIN accounts a ON ta.gl_account_id = a.id
            LEFT JOIN currencies c ON ta.currency = c.code
            WHERE ta.is_active = TRUE
        """
        params = {}
        if branch_id:
            query += " AND ta.branch_id = :branch_id"
            params["branch_id"] = branch_id
        elif allowed_branch_ids is not None:
            if allowed_branch_ids:
                query += " AND ta.branch_id = ANY(:allowed_branches)"
                params["allowed_branches"] = allowed_branch_ids
            else:
                query += " AND 1=0"
        query += " ORDER BY ta.id"
        
        result = db.execute(text(query), params).fetchall()
        # T11 P1 #50/#56 — decrypt PII columns on read (legacy plaintext is
        # passed through unchanged by ``decrypt_pii``).
        tid = current_user.company_id

        # Get base currency and exchange rates for conversion
        base_cur_row = db.execute(text("SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1")).fetchone()
        base_currency = base_cur_row[0] if base_cur_row else "SAR"
        rate_rows = db.execute(text("SELECT code, current_rate FROM currencies WHERE is_active = TRUE")).fetchall()
        rate_map = {r[0]: float(r[1]) for r in rate_rows}
        rate_map[base_currency] = 1.0

        rows = []
        for row in result:
            d = dict(row._mapping)
            d["iban"]           = decrypt_pii(d.get("iban"),           tenant_id=tid)
            d["account_number"] = decrypt_pii(d.get("account_number"), tenant_id=tid)

            # current_balance from accounts.balance is already in base currency
            # balance_in_currency from treasury_accounts.current_balance is in original currency
            acc_currency = d.get("currency", "") or ""
            raw_balance = float(d.get("current_balance", 0) or 0)
            balance_in_cur = float(d.get("balance_in_currency", 0) or 0)
            rate = rate_map.get(acc_currency, 1.0)

            d["current_balance"] = raw_balance  # Already in base currency
            d["balance_in_currency"] = balance_in_cur  # Original currency
            d["exchange_rate"] = rate
            d["base_currency"] = base_currency

            rows.append(d)
        return rows
    finally:
        db.close()

@router.get("/transactions", response_model=List[TransactionResponse], dependencies=[Depends(require_permission("treasury.view"))])
def list_transactions(branch_id: Optional[int] = None, limit: int = 50, current_user = Depends(get_current_user)):
    """عرض سجل العمليات الأخيرة"""
    if not current_user.company_id:
         raise HTTPException(**http_error(400, ("company_required", request)))
    branch_id, allowed_branch_ids = _treasury_account_scope(current_user, branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        query_str = """
            SELECT 
                t.id, 
                t.transaction_number, 
                t.transaction_date, 
                t.transaction_type, 
                t.amount, 
                t.description, 
                to_char(t.created_at, 'YYYY-MM-DD HH24:MI:SS') as created_at,
                ta.name as treasury_name,
                COALESCE(ta_target.name, gl.name) as target_name,
                'posted' as status
            FROM treasury_transactions t
            LEFT JOIN treasury_accounts ta ON t.treasury_id = ta.id
            LEFT JOIN treasury_accounts ta_target ON t.target_treasury_id = ta_target.id
            LEFT JOIN accounts gl ON t.target_account_id = gl.id
            WHERE 1=1
        """
        params = {"limit": limit}
        if branch_id:
            query_str += " AND (ta.branch_id = :bid OR t.branch_id = :bid)"
            params["bid"] = branch_id
        elif allowed_branch_ids is not None:
            if allowed_branch_ids:
                query_str += " AND (ta.branch_id = ANY(:allowed_branches) OR t.branch_id = ANY(:allowed_branches))"
                params["allowed_branches"] = allowed_branch_ids
            else:
                query_str += " AND 1=0"
            
        query_str += " ORDER BY t.transaction_date DESC, t.id DESC LIMIT :limit"
        
        result = db.execute(text(query_str), params).fetchall()
        return [dict(row._mapping) for row in result]
    finally:
        db.close()

@router.post("/accounts", response_model=TreasuryAccountResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("treasury.create"))])
def create_treasury_account(request: Request, account: TreasuryAccountCreate, current_user: dict = Depends(get_current_user)):
    """
    إنشاء حساب خزينة جديد
    يقوم تلقائياً بإنشاء حساب في دليل الحسابات (GL Account) تحت الأصول المتداولة
    """
    if hasattr(account, 'branch_id') and account.branch_id:
        validate_branch_access(current_user, account.branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        from utils.accounting import get_base_currency
        base_currency = get_base_currency(db)
        # Check for duplicate treasury account name
        existing = db.execute(
            text("SELECT id FROM treasury_accounts WHERE name = :name AND is_active = TRUE"),
            {"name": account.name}
        ).fetchone()
        if existing:
            raise HTTPException(**http_error(400, ("treasury_name_duplicate", request)))

        # Check for duplicate bank account number (if provided)
        if account.account_type == 'bank' and account.account_number:
            existing_bank = db.execute(text(
                """
                SELECT id FROM treasury_accounts
                WHERE account_number = :account_number AND is_active = TRUE
                """
            ), {"account_number": encrypt_pii(account.account_number, tenant_id=current_user.company_id)}).fetchone()
            if existing_bank:
                raise HTTPException(**http_error(400, ("treasury_iban_duplicate", request)))

        # 1. Determine Parent Account from Chart of Accounts
        # 1101 = Cash & Equivalents
        # Also ensure standard treasury GL accounts (1205, 2105, 1210, 2110) exist
        ensure_treasury_gl_accounts(db, user_id=current_user.id, username=current_user.username)
        parent_account = db.execute(text("SELECT id FROM accounts WHERE account_number = '1101'")).fetchone()
        if not parent_account:
            # Fallback: Check code column
            parent_account = db.execute(text("SELECT id FROM accounts WHERE account_code = '1101'")).fetchone()
            
        if not parent_account:
            raise HTTPException(**http_error(500, ("main_cash_account_not_found", request)))
        
        parent_id = parent_account[0]
        
        # 2. Check if GL account already exists for this treasury name
        existing_gl = db.execute(text("""
            SELECT id FROM accounts 
            WHERE parent_id = :pid AND name = :name AND account_type = 'asset'
            LIMIT 1
        """), {"pid": parent_id, "name": account.name}).fetchone()
        
        if existing_gl:
            gl_id = existing_gl[0]
        else:
            # Generate Account Code — ensure uniqueness
            last_acc = db.execute(text("SELECT account_code FROM accounts WHERE parent_id = :pid ORDER BY account_code DESC LIMIT 1"), {"pid": parent_id}).fetchone()
            
            new_code = "1101001"
            if last_acc and last_acc[0]:
                last_code = last_acc[0]
                if last_code.isdigit():
                     new_code = str(int(last_code) + 1)
                else:
                     import random
                     new_code = f"1101{random.randint(100000, 999999)}"
            
            # Ensure code is unique
            while db.execute(text("SELECT 1 FROM accounts WHERE account_number = :code"), {"code": new_code}).fetchone():
                new_code = str(int(new_code) + 1)
            
            # Create GL Account
            gl_query = text("""
                INSERT INTO accounts (account_number, account_code, name, name_en, account_type, parent_id, currency, balance, is_active)
                VALUES (:num, :code, :name, :name_en, 'asset', :pid, :curr, 0, TRUE)
                RETURNING id
            """)
            gl_id = db.execute(gl_query, {
                "num": new_code,
                "code": new_code,
                "name": account.name,
                "name_en": account.name_en,
                "pid": parent_id,
                "curr": account.currency
            }).scalar()
        
        # Invalidate chart of accounts cache
        try:
            cache.delete(f"chart_of_accounts:{current_user.company_id}")
        except Exception:
            pass

        # 4. Create Treasury Account
        treasury_query = text("""
            INSERT INTO treasury_accounts (name, name_en, account_type, currency, bank_name, account_number, iban, gl_account_id, branch_id, allow_overdraft)
            VALUES (:name, :name_en, :type, :curr, :bank, :acc_num, :iban, :gl_id, :branch_id, :allow_overdraft)
            RETURNING id, name, name_en, account_type, currency, bank_name, account_number, iban, gl_account_id, current_balance, is_active, branch_id, allow_overdraft
        """)
        
        # T11 — encrypt PII before persistence
        _tid = current_user.company_id
        new_treasury = db.execute(treasury_query, {
            "name": account.name,
            "name_en": account.name_en,
            "type": account.account_type,
            "curr": account.currency,
            "bank": account.bank_name,
            "acc_num": encrypt_pii(account.account_number, tenant_id=_tid),
            "iban":    encrypt_pii(account.iban,           tenant_id=_tid),
            "gl_id": gl_id,
            "branch_id": account.branch_id,
            "allow_overdraft": account.allow_overdraft
        }).fetchone()
        
        # 5. Handle Opening Balance
        if account.opening_balance and account.opening_balance > 0:
            # Fiscal lock check before posting opening balance GL entry
            check_fiscal_period_open(db, date.today().isoformat())

            # T1.3a: Don't write current_balance manually here — it will be
            # recomputed from journal_lines after the JE below is posted.

            # Credit Capital — find currency-specific capital account
            # Try: 3101 (SAR), 3102 (EGP), 3103 (AED), etc.
            capital_acc = db.execute(text("""
                SELECT id FROM accounts 
                WHERE parent_id = (SELECT id FROM accounts WHERE account_number = '31' AND is_header = TRUE LIMIT 1)
                AND currency = :curr AND account_type = 'equity' AND is_header = FALSE
                LIMIT 1
            """), {"curr": account.currency}).fetchone()

            if not capital_acc:
                # Auto-create capital account for this currency
                _auto_create_capital_account(db, account.currency, current_user)
                capital_acc = db.execute(text("""
                    SELECT id FROM accounts 
                    WHERE parent_id = (SELECT id FROM accounts WHERE account_number = '31' AND is_header = TRUE LIMIT 1)
                    AND currency = :curr AND account_type = 'equity' AND is_header = FALSE
                    LIMIT 1
                """), {"curr": account.currency}).fetchone()

            capital_gl_id = capital_acc[0] if capital_acc else None
            
            if capital_gl_id:
                # opening_balance is in the account's original currency
                # gl_service will convert to base currency using exchange_rate
                opening_balance = float(account.opening_balance)
                exchange_rate = float(account.exchange_rate or 1)

                # Build journal lines — debit/credit in ORIGINAL currency
                # gl_service converts to base: debit_base = debit * exchange_rate
                je_lines = [
                    {
                        "account_id": gl_id,
                        "debit": opening_balance,  # Original currency
                        "credit": 0,
                        "currency": account.currency,
                        "exchange_rate": exchange_rate,
                        "amount_currency": opening_balance,  # Original currency
                    },
                    {
                        "account_id": capital_gl_id,
                        "debit": 0,
                        "credit": opening_balance,  # Original currency
                        "currency": account.currency,
                        "exchange_rate": exchange_rate,
                        "amount_currency": opening_balance,  # Original currency
                    },
                ]
                
                from services.gl_service import create_journal_entry as gl_create_journal_entry
                gl_create_journal_entry(
                    db=db,
                    company_id=current_user.company_id,
                    date=date.today().isoformat(),
                    description=f"Opening Balance - {account.name}",
                    lines=je_lines,
                    user_id=current_user.id,
                    branch_id=account.branch_id,
                    currency=base_currency,
                    exchange_rate=1.0,
                    source="treasury_account_opening",
                    source_id=new_treasury[0]
                )

                # T1.3a: recompute current_balance now that the opening JE is posted
                from utils.treasury_balance import recalc_treasury_from_gl
                recalc_treasury_from_gl(db, new_treasury[0])
        
        db.commit()

        # AUDIT LOG
        log_activity(
            db,
            user_id=current_user.id,
            username=current_user.username,
            action="treasury.account.create",
            resource_type="treasury_account",
            resource_id=str(new_treasury[0]),
            details={"name": account.name, "type": account.account_type, "opening_balance": account.opening_balance},
            request=request,
            branch_id=account.branch_id
        )

        # Refresh from DB to get updated balance from GL
        final_query = """
            SELECT ta.*, COALESCE(a.balance, 0) as current_balance, b.branch_name as branch_name
            FROM treasury_accounts ta
            LEFT JOIN accounts a ON ta.gl_account_id = a.id
            LEFT JOIN branches b ON ta.branch_id = b.id
            WHERE ta.id = :id
        """
        final_treasury = db.execute(text(final_query), {"id": new_treasury[0]}).fetchone()
        # T11 — return decrypted IBAN/account_number to caller (UI layer expects plaintext)
        out = dict(final_treasury._mapping)
        out["iban"]           = decrypt_pii(out.get("iban"),           tenant_id=current_user.company_id)
        out["account_number"] = decrypt_pii(out.get("account_number"), tenant_id=current_user.company_id)
        return out
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating treasury account: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()

@router.put("/accounts/{id}", dependencies=[Depends(require_permission("treasury.edit"))], response_model=Dict[str, Any])
def update_treasury_account(
    id: int,
    account: TreasuryAccountCreate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """تحديث حساب خزينة"""
    if account.branch_id:
        validate_branch_access(current_user, account.branch_id)
    db = get_db_connection(current_user.company_id)
    try:
        # Check existence
        existing = db.execute(text("SELECT id, gl_account_id FROM treasury_accounts WHERE id = :id"), {"id": id}).fetchone()
        if not existing:
            raise HTTPException(**http_error(404, "treasury_account_not_found"))
        
        old_gl_account_id = existing.gl_account_id

        # Check for duplicate name (excluding current account)
        dup = db.execute(text("SELECT id FROM treasury_accounts WHERE name = :name AND id != :id AND is_active = TRUE"), 
                        {"name": account.name, "id": id}).fetchone()
        if dup:
            raise HTTPException(**http_error(400, "treasury_account_name_duplicate", request))

        if account.account_type == 'bank' and account.account_number:
            dup_bank = db.execute(text("""
                SELECT id FROM treasury_accounts
                WHERE account_number = :account_number AND id != :id AND is_active = TRUE
            """), {
                "account_number": encrypt_pii(account.account_number, tenant_id=current_user.company_id),
                "id": id,
            }).fetchone()
            if dup_bank:
                raise HTTPException(**http_error(400, ("treasury_iban_duplicate", request)))
        
        # Update treasury account
        db.execute(text("""
            UPDATE treasury_accounts SET
                name = :name,
                name_en = :name_en,
                account_type = :type,
                currency = :curr,
                bank_name = :bank,
                account_number = :acc_num,
                iban = :iban,
                branch_id = :branch_id,
                allow_overdraft = :allow_overdraft,
                updated_at = NOW()
            WHERE id = :id
        """), {
            "id": id,
            "name": account.name,
            "name_en": account.name_en,
            "type": account.account_type,
            "curr": account.currency,
            "bank": account.bank_name,
            # T11 — encrypt PII on update
            "acc_num": encrypt_pii(account.account_number, tenant_id=current_user.company_id),
            "iban":    encrypt_pii(account.iban,           tenant_id=current_user.company_id),
            "branch_id": account.branch_id,
            "allow_overdraft": account.allow_overdraft
        })
        
        # Update linked GL account name
        if existing.gl_account_id:
            db.execute(text("""
                UPDATE accounts SET
                    name = :name,
                    name_en = :name_en,
                    currency = :curr
                WHERE id = :id
            """), {
                "id": existing.gl_account_id,
                "name": account.name,
                "name_en": account.name_en,
                "curr": account.currency
            })
        
        db.commit()
        
        # AUDIT LOG
        audit_details = {"name": account.name}
        # Track GL account linkage changes
        new_gl_account_id = existing.gl_account_id  # GL ID doesn't change in this endpoint, but track if it were
        if old_gl_account_id != new_gl_account_id:
            audit_details["gl_account_id_before"] = old_gl_account_id
            audit_details["gl_account_id_after"] = new_gl_account_id
        log_activity(
            db,
            user_id=current_user.id,
            username=current_user.username,
            action="treasury_account.update",
            resource_type="treasury_account",
            resource_id=str(id),
            details=audit_details,
            request=request,
            branch_id=account.branch_id
        )
        
        return {"id": id, "message": i18n_message("treasury_account_updated", request)}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating treasury account: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()

@router.delete("/accounts/{id}", dependencies=[Depends(require_permission("treasury.delete"))], response_model=Dict[str, Any])
def delete_treasury_account(
    id: int,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """حذف حساب خزينة"""
    db = get_db_connection(current_user.company_id)
    try:
        # Check existence
        account = db.execute(text("SELECT id, name, current_balance, gl_account_id FROM treasury_accounts WHERE id = :id"), 
                           {"id": id}).fetchone()
        if not account:
            raise HTTPException(**http_error(404, "treasury_account_not_found"))
        
        # Check if account has balance
        if account.current_balance and abs(account.current_balance) > 0.01:
            raise HTTPException(**http_error(400, ("cannot_delete_treasury_with_balance", request)))
        
        # Check if account has transactions
        usage = db.execute(text("""
            SELECT COUNT(*) FROM treasury_transactions WHERE treasury_id = :id OR target_treasury_id = :id
        """), {"id": id}).scalar()
        
        if usage and usage > 0:
            raise HTTPException(**http_error(400, "cannot_delete_treasury_with_transactions", request))
        
        # Delete treasury account (will be soft delete by setting is_active = FALSE)
        db.execute(text("UPDATE treasury_accounts SET is_active = FALSE WHERE id = :id"), {"id": id})
        
        # Optionally deactivate linked GL account
        if account.gl_account_id:
            db.execute(text("UPDATE accounts SET is_active = FALSE WHERE id = :id"), {"id": account.gl_account_id})
        
        db.commit()
        
        # AUDIT LOG
        log_activity(
            db,
            user_id=current_user.id,
            username=current_user.username,
            action="treasury_account.delete",
            resource_type="treasury_account",
            resource_id=str(id),
            details={"name": account.name},
            request=request,
            branch_id=None
        )
        
        return {"message": i18n_message(("treasury_account_deleted", request))}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting treasury account: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()

@router.post("/transactions/expense", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("treasury.manage"))], response_model=Dict[str, Any])
async def create_expense(request: Request, data: TransactionCreate, current_user: dict = Depends(get_current_user)):
    """تسجيل مصروف جديد عبر الخزينة.

    T3.11: this endpoint is now a thin compatibility shim that
    delegates to the unified expenses flow in
    ``routers.finance.expenses.create_expense``. It exists only so the
    legacy frontend ``treasury.js → createExpense`` and pre-existing
    integration tests keep working — the canonical path for new code
    is ``POST /expenses``.

    T10.1 P1 #68: this no longer auto-bypasses the approval workflow.
    The shim consults ``expense_policies`` for the same expense type
    and respects the policy's ``requires_approval`` /
    ``auto_approve_below`` thresholds — identical to ``POST /expenses``.
    """
    if data.transaction_type != 'expense':
        raise HTTPException(**http_error(400, "invalid_transaction_type", request))
    if data.amount is None or data.amount <= 0:
        raise HTTPException(**http_error(400, "amount_must_be_positive"))
    if not data.target_account_id:
        raise HTTPException(**http_error(400, ("expense_account_required", request)))

    from schemas.expenses import ExpenseCreate
    from routers.finance.expenses import create_expense as unified_create_expense
    from utils.tx import transactional as _tx
    from decimal import Decimal as _D

    # T10.1 P1 #68 — resolve approval requirement from active policies
    # before delegating, so the treasury entrypoint cannot bypass the
    # approval workflow.
    requires_approval = True
    try:
        with _tx(current_user.company_id) as _db:
            pol = _db.execute(text(
                "SELECT requires_approval, auto_approve_below "
                "FROM expense_policies "
                "WHERE is_active = TRUE AND COALESCE(is_deleted, FALSE) = FALSE "
                "ORDER BY id DESC LIMIT 1"
            )).fetchone()
            if pol is None:
                requires_approval = False  # no policy → preserve legacy behaviour
            else:
                base = bool(getattr(pol, "requires_approval", True))
                threshold = getattr(pol, "auto_approve_below", None)
                if base and threshold is not None and _D(str(data.amount)) < _D(str(threshold)):
                    requires_approval = False
                else:
                    requires_approval = base
    except Exception:
        requires_approval = True  # fail-safe: enforce approval on policy lookup error

    expense_payload = ExpenseCreate(
        expense_date=data.transaction_date,
        expense_type="other",
        amount=data.amount,
        description=data.description or "",
        category="general",
        payment_method="cash",
        treasury_id=data.treasury_id,
        expense_account_id=data.target_account_id,
        cost_center_id=None,
        project_id=None,
        branch_id=data.branch_id,
        receipt_number=data.reference_number,
        vendor_name=None,
        requires_approval=requires_approval,
    )

    result = await unified_create_expense(
        request=request, expense=expense_payload, current_user=current_user
    )

    return {
        "success": True,
        "message": i18n_message("expense_recorded", request),
        "transaction_id": result.get("id") if isinstance(result, dict) else None,
        "expense_id": result.get("id") if isinstance(result, dict) else None,
        "expense_number": result.get("expense_number") if isinstance(result, dict) else None,
    }

@router.post("/transactions/transfer", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("treasury.manage"))], response_model=Dict[str, Any])
def create_transfer(request: Request, data: TransactionCreate, current_user: dict = Depends(get_current_user)):
    """تحويل بين الخزائن/البنوك"""
    if data.transaction_type != 'transfer':
        raise HTTPException(**http_error(400, "invalid_transaction_type", request))
    
    # Validate amount
    if data.amount is None or data.amount <= 0:
        raise HTTPException(**http_error(400, "amount_must_be_positive"))
    
    # Prevent self-transfer
    if data.treasury_id == data.target_treasury_id:
        raise HTTPException(**http_error(400, ("cannot_transfer_same_account", request)))
    
    if not data.target_treasury_id:
        raise HTTPException(**http_error(400, "receiving_account_required", request))
        
    db = get_db_connection(current_user.company_id)
    try:
        import uuid
        trans_num = f"TRF-{str(uuid.uuid4())[:8].upper()}"
        validate_treasury_account_access(db, current_user, data.treasury_id)
        validate_treasury_account_access(db, current_user, data.target_treasury_id)
        
        # Get Source & Target Info — SELECT FOR UPDATE both rows to prevent concurrent balance drift
        # Lock in consistent order (lower id first) to prevent deadlocks
        first_id, second_id = sorted([data.treasury_id, data.target_treasury_id])
        db.execute(text("SELECT id FROM treasury_accounts WHERE id = :id FOR UPDATE"), {"id": first_id})
        db.execute(text("SELECT id FROM treasury_accounts WHERE id = :id FOR UPDATE"), {"id": second_id})

        source = db.execute(text("""
            SELECT gl_account_id, name, branch_id, currency, current_balance, account_type, allow_overdraft
            FROM treasury_accounts WHERE id = :id
        """), {"id": data.treasury_id}).fetchone()
        target = db.execute(text("SELECT gl_account_id, name, currency FROM treasury_accounts WHERE id = :id"), {"id": data.target_treasury_id}).fetchone()
        
        if not source or not target:
            raise HTTPException(**http_error(404, "source_or_dest_not_found", request))
            
        source_gl = source.gl_account_id
        source_name = source.name
        branch_id = source.branch_id
        source_currency = source.currency
        target_gl = target.gl_account_id
        target_name = target.name
        target_currency = target.currency
        
        exchange_rate = _dec(data.exchange_rate or 1)
        amount_base = (_dec(data.amount) * exchange_rate).quantize(_D2, ROUND_HALF_UP)

        # Overdraft validation on source account
        new_balance = _dec(source.current_balance) - _dec(data.amount)
        if new_balance < 0:
            is_bank = source.account_type == 'bank'
            allow_od = source.allow_overdraft
            if not is_bank and not allow_od:
                raise HTTPException(
                    status_code=400,
                    detail=f"رصيد حساب المصدر غير كافٍ. الرصيد الحالي: {float(source.current_balance):,.2f}"
                )

        # 1. Create Journal Entry — GL-first
        check_fiscal_period_open(db, data.transaction_date)

        # Cross-currency: convert amount to target currency before adding to target treasury
        if source_currency != target_currency and exchange_rate != Decimal('1'):
            target_rate_row = db.execute(text("SELECT current_rate FROM currencies WHERE code = :code"), {"code": target_currency}).fetchone()
            target_rate = _dec(target_rate_row.current_rate) if target_rate_row else Decimal('1')
            target_amount = ((_dec(data.amount) * exchange_rate) / target_rate).quantize(_D2, ROUND_HALF_UP) if target_rate else _dec(data.amount)
        else:
            target_amount = data.amount

        target_rate = (_dec(amount_base) / _dec(target_amount)) if _dec(target_amount) else Decimal('1')
        
        je_lines = [
            {
                "account_id": target_gl, "debit": float(target_amount), "credit": 0, 
                "currency": target_currency, "exchange_rate": float(target_rate), "description": "Transfer In"
            },
            {
                "account_id": source_gl, "debit": 0, "credit": float(data.amount), 
                "currency": source_currency, "exchange_rate": float(exchange_rate), "description": "Transfer Out"
            },
        ]

        from services.gl_service import create_journal_entry as gl_create_journal_entry
        je_id, _ = gl_create_journal_entry(
            db=db,
            company_id=current_user.company_id,
            date=data.transaction_date,
            description=f"Transfer: {source_name} -> {target_name} ({source_currency})",
            lines=je_lines,
            user_id=current_user.id,
            branch_id=branch_id,
            reference=trans_num,
            currency=source_currency,
            exchange_rate=float(exchange_rate),
            source="treasury_transfer",
        )

        # 2. Insert Transaction Log — with exchange_rate and currency
        trans_id = db.execute(text("""
            INSERT INTO treasury_transactions (
                transaction_number, transaction_date, transaction_type, amount, 
                treasury_id, target_treasury_id, description, reference_number,
                created_by, exchange_rate, currency
            ) VALUES (
                :num, :date, :type, :amount, :src, :dst, :desc, :ref,
                :uid, :exr, :cur
            ) RETURNING id
        """), {
            "num": trans_num,
            "date": data.transaction_date,
            "type": 'transfer',
            "amount": data.amount,
            "src": data.treasury_id,
            "dst": data.target_treasury_id,
            "desc": data.description or f"Transfer from {source_name} to {target_name}",
            "ref": data.reference_number,
            "uid": current_user.id,
            "exr": float(exchange_rate),
            "cur": source_currency,
        }).scalar()
        
        # 3. Update Treasury Balances — T1.3a idempotent recompute (after GL entry posted)
        from utils.treasury_balance import recalc_treasury_from_gl
        recalc_treasury_from_gl(db, data.treasury_id)
        recalc_treasury_from_gl(db, data.target_treasury_id)
        
        db.commit()

        # AUDIT LOG
        log_activity(
            db,
            user_id=current_user.id,
            username=current_user.username,
            action="treasury.transfer.create",
            resource_type="treasury_transaction",
            resource_id=str(trans_id),
            details={"amount": data.amount, "from": data.treasury_id, "to": data.target_treasury_id},
            request=request,
            branch_id=branch_id
        )

        return {"success": True, "message": i18n_message("transfer_successful", request), "transaction_id": trans_id}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Transfer Error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


# ────────────────────────── Treasury Reports ──────────────────────────

@router.get("/reports/balances", dependencies=[Depends(require_permission("treasury.view"))], response_model=Dict[str, Any])
def get_treasury_balances_report(
    branch_id: Optional[int] = None,
    as_of_date: Optional[str] = None,
    current_user=Depends(get_current_user)
):
    """تقرير أرصدة الخزينة — كل الصناديق والبنوك مع أرصدتها"""
    db = get_db_connection(current_user.company_id)
    try:
        target_date = as_of_date or date.today().isoformat()
        params = {}
        branch_filter = branch_scope_filter(current_user, branch_id, "ta.branch_id", params)

        # Get all treasury accounts with current balances
        q = text("""
            SELECT ta.id, ta.name, ta.name_en, ta.account_type, ta.currency,
                   ta.current_balance,
                   ta.gl_account_id, ta.branch_id,
                   COALESCE(b.branch_name, '') as branch_name
            FROM treasury_accounts ta
            LEFT JOIN branches b ON b.id = ta.branch_id
            WHERE ta.is_active = true
            """ + f" {branch_filter}" + """
            ORDER BY ta.account_type, ta.name
        """)
        rows = db.execute(q, params).fetchall()

        # T033: Batch-fetch GL balances for all treasury GL accounts
        gl_account_ids = [r.gl_account_id for r in rows if r.gl_account_id]
        gl_balances: dict = {}
        if gl_account_ids:
            gl_params = {"ids": gl_account_ids}
            gl_branch_filter = branch_scope_filter(current_user, branch_id, "je.branch_id", gl_params)
            gl_rows = db.execute(text(f"""
                SELECT jl.account_id,
                       COALESCE(SUM(jl.debit), 0) - COALESCE(SUM(jl.credit), 0) AS gl_balance
                FROM journal_lines jl
                JOIN journal_entries je ON jl.journal_entry_id = je.id
                WHERE jl.account_id = ANY(:ids) AND je.status = 'posted'
                {gl_branch_filter}
                GROUP BY jl.account_id
            """), gl_params).fetchall()
            for gr in gl_rows:
                gl_balances[gr.account_id] = _dec(gr.gl_balance)

        accounts = []
        total_cash = Decimal('0')
        total_bank = Decimal('0')
        total_all = Decimal('0')

        # Load base currency and exchange rates once
        base_currency = db.execute(text(
            "SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1"
        )).scalar() or "SAR"

        fx_rates: dict = {}
        try:
            rate_rows = db.execute(text(
                "SELECT code, current_rate FROM currencies WHERE is_active = true"
            )).fetchall()
            for rr in rate_rows:
                fx_rates[rr.code] = _dec(rr.current_rate or 1)
        except Exception:
            pass

        for r in rows:
            bal = _dec(r.current_balance or 0)
            currency = r.currency or base_currency
            rate = fx_rates.get(currency, Decimal('1')) if currency != base_currency else Decimal('1')
            bal_base = (bal * rate).quantize(_D2, ROUND_HALF_UP)

            acc = {
                "id": r.id, "name": r.name, "name_en": r.name_en,
                "account_type": r.account_type, "currency": currency,
                "current_balance": float(bal),
                "balance_in_currency": float(bal),
                "balance_in_base": float(bal_base),
                "gl_balance": float(gl_balances.get(r.gl_account_id, Decimal('0')).quantize(_D2, ROUND_HALF_UP)) if r.gl_account_id else None,
                "exchange_rate": float(rate),
                "base_currency": base_currency,
                "branch_name": r.branch_name
            }
            accounts.append(acc)
            if r.account_type == 'cash':
                total_cash += bal_base
            else:
                total_bank += bal_base
            total_all += bal_base

        # Recent transactions for context
        txn_q = text("""
            SELECT tt.id, tt.transaction_type, tt.amount, tt.description,
                   tt.created_at, ta.name as account_name
            FROM treasury_transactions tt
            JOIN treasury_accounts ta ON ta.id = tt.treasury_id
            WHERE 1=1
            """ + f" {branch_filter}" + """
            ORDER BY tt.created_at DESC LIMIT 10
        """)
        txns = db.execute(txn_q, params).fetchall()
        recent = [{
            "id": t.id, "type": t.transaction_type, "amount": float(t.amount),
            "description": t.description, "date": str(t.created_at)[:10],
            "account_name": t.account_name
        } for t in txns]

        return {
            "accounts": accounts,
            "summary": {
                "total_cash": float(total_cash),
                "total_bank": float(total_bank),
                "total_all": float(total_all),
                "cash_count": sum(1 for a in accounts if a["account_type"] == "cash"),
                "bank_count": sum(1 for a in accounts if a["account_type"] == "bank"),
            },
            "recent_transactions": recent,
            "as_of_date": target_date
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Treasury balances report error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.get("/reports/cashflow", dependencies=[Depends(require_permission("treasury.view"))], response_model=Dict[str, Any])
def get_treasury_cashflow_report(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user=Depends(get_current_user)
):
    """تقرير التدفقات النقدية للخزينة — التدفقات الداخلة والخارجة"""
    db = get_db_connection(current_user.company_id)
    try:
        from datetime import datetime
        if not start_date:
            start_date = (datetime.now().replace(day=1)).strftime('%Y-%m-%d')
        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')

        params = {"start_date": start_date, "end_date": end_date}
        branch_filter = branch_scope_filter(current_user, branch_id, "ta.branch_id", params)

        # Inflows (receipts, deposits, transfers in)
        inflow_q = text(f"""
            SELECT COALESCE(SUM(tt.amount), 0) as total,
                   tt.transaction_type,
                   COUNT(*) as count
            FROM treasury_transactions tt
            JOIN treasury_accounts ta ON ta.id = tt.treasury_id
            WHERE tt.transaction_type IN ('receipt', 'deposit', 'transfer_in', 'pos_sale')
              AND tt.created_at::date BETWEEN :start_date AND :end_date
              {branch_filter}
            GROUP BY tt.transaction_type
        """)
        inflows = db.execute(inflow_q, params).fetchall()

        # Outflows (expense, withdrawal, transfer out)
        outflow_q = text(f"""
            SELECT COALESCE(SUM(tt.amount), 0) as total,
                   tt.transaction_type,
                   COUNT(*) as count
            FROM treasury_transactions tt
            JOIN treasury_accounts ta ON ta.id = tt.treasury_id
            WHERE tt.transaction_type IN ('expense', 'withdrawal', 'transfer_out', 'payment')
              AND tt.created_at::date BETWEEN :start_date AND :end_date
              {branch_filter}
            GROUP BY tt.transaction_type
        """)
        outflows = db.execute(outflow_q, params).fetchall()

        # Daily trend
        daily_q = text(f"""
            SELECT tt.created_at::date as day,
                   SUM(CASE WHEN tt.transaction_type IN ('receipt','deposit','transfer_in','pos_sale') THEN tt.amount ELSE 0 END) as inflow,
                   SUM(CASE WHEN tt.transaction_type IN ('expense','withdrawal','transfer_out','payment') THEN tt.amount ELSE 0 END) as outflow
            FROM treasury_transactions tt
            JOIN treasury_accounts ta ON ta.id = tt.treasury_id
            WHERE tt.created_at::date BETWEEN :start_date AND :end_date
              {branch_filter}
            GROUP BY tt.created_at::date
            ORDER BY day
        """)
        daily = db.execute(daily_q, params).fetchall()

        # By account breakdown
        by_account_q = text(f"""
            SELECT ta.id, ta.name, ta.account_type,
                   SUM(CASE WHEN tt.transaction_type IN ('receipt','deposit','transfer_in','pos_sale') THEN tt.amount ELSE 0 END) as inflow,
                   SUM(CASE WHEN tt.transaction_type IN ('expense','withdrawal','transfer_out','payment') THEN tt.amount ELSE 0 END) as outflow
            FROM treasury_transactions tt
            JOIN treasury_accounts ta ON ta.id = tt.treasury_id
            WHERE tt.created_at::date BETWEEN :start_date AND :end_date
              {branch_filter}
            GROUP BY ta.id, ta.name, ta.account_type
            ORDER BY ta.name
        """)
        by_account = db.execute(by_account_q, params).fetchall()

        total_in = sum(float(r.total) for r in inflows)
        total_out = sum(float(r.total) for r in outflows)

        return {
            "inflows": [{"type": r.transaction_type, "total": float(r.total), "count": r.count} for r in inflows],
            "outflows": [{"type": r.transaction_type, "total": float(r.total), "count": r.count} for r in outflows],
            "total_inflow": total_in,
            "total_outflow": total_out,
            "net_flow": total_in - total_out,
            "daily_trend": [{"date": str(d.day), "inflow": float(d.inflow), "outflow": float(d.outflow)} for d in daily],
            "by_account": [{"id": a.id, "name": a.name, "type": a.account_type, "inflow": float(a.inflow), "outflow": float(a.outflow), "net": float(a.inflow) - float(a.outflow)} for a in by_account],
            "start_date": start_date,
            "end_date": end_date
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Treasury cashflow report error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()
