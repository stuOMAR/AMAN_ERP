"""
AMAN ERP - Treasury Router
إدارة الخزينة والمصروفات
"""

from fastapi import APIRouter, Depends, HTTPException, status
from utils.i18n import http_error, i18n_message
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import date
import logging

from decimal import Decimal, ROUND_HALF_UP

from database import get_db_connection
from routers.auth import get_current_user
from utils.permissions import branch_scope_filter, require_permission, require_sensitive_permission, require_module, validate_branch_access, validate_treasury_account_access, check_permission
from utils.audit import log_activity
from utils.fiscal_lock import check_fiscal_period_open
from utils.cache import cache
from utils.treasury_gl import ensure_treasury_gl_accounts
from utils.pii_encryption import encrypt_pii, decrypt_pii
from utils.masking import mask_pii
from utils.tx import transactional
from fastapi import Request
from schemas.treasury import TreasuryAccountCreate, TreasuryAccountResponse, TransactionCreate, TransactionResponse

_D2 = Decimal('0.01')
def _dec(v) -> Decimal:
    """Convert any numeric value to Decimal safely."""
    return Decimal(str(v)) if v is not None else Decimal('0')


def _money(value) -> str:
    return str(_dec(value).quantize(_D2, ROUND_HALF_UP))


def _amount_direction(value) -> str:
    return "negative" if _dec(value) < 0 else "non_negative"


def _resolve_exchange_rate(
    db,
    *,
    currency: Optional[str],
    base_currency: str,
    rate_date: Optional[date],
    request: Request,
) -> Decimal:
    """Resolve FX from backend tables; client-supplied rates are ignored."""
    source_currency = (currency or base_currency or "SAR").upper()
    company_base = (base_currency or "SAR").upper()
    if source_currency == company_base:
        return Decimal("1").quantize(Decimal("0.000001"), ROUND_HALF_UP)

    rate_row = db.execute(text("""
        SELECT rate
        FROM exchange_rates
        WHERE currency_id = (SELECT id FROM currencies WHERE UPPER(code) = UPPER(:code))
          AND rate_date <= COALESCE(:rate_date, CURRENT_DATE)
        ORDER BY rate_date DESC
        LIMIT 1
    """), {"code": source_currency, "rate_date": rate_date}).fetchone()

    rate = _dec(rate_row.rate) if rate_row else Decimal("0")
    if rate <= 0:
        current_row = db.execute(text("""
            SELECT current_rate
            FROM currencies
            WHERE UPPER(code) = UPPER(:code)
            LIMIT 1
        """), {"code": source_currency}).fetchone()
        rate = _dec(current_row.current_rate) if current_row else Decimal("0")

    if rate <= 0:
        raise HTTPException(**http_error(400, "no_exchange_rate_for_currency", request))
    return rate.quantize(Decimal("0.000001"), ROUND_HALF_UP)

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
        logger.info(f"Auto-created capital account {next_num} for {currency_code}")
    except Exception as e:
        logger.warning(f"Failed to auto-create capital account for {currency_code}: {e}")
        raise


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


def _has_treasury_bank_details_access(current_user) -> bool:
    if isinstance(current_user, dict):
        permissions = current_user.get("permissions", []) or []
        role = current_user.get("role", "")
    else:
        permissions = getattr(current_user, "permissions", []) or []
        role = getattr(current_user, "role", "") or ""
    if role in {"admin", "system_admin", "superuser", "owner", "ceo", "chairman"}:
        return True
    return "*" in permissions or check_permission(permissions, "treasury.bank_details.view")


def _mask_bank_details(record: Dict[str, Any], current_user) -> Dict[str, Any]:
    if _has_treasury_bank_details_access(current_user):
        record["bank_details_masked"] = False
        return record
    record["iban"] = mask_pii(record.get("iban"), visible_chars=4)
    record["account_number"] = mask_pii(record.get("account_number"), visible_chars=4)
    record["bank_details_masked"] = True
    return record


def _treasury_account_response(db, account_id: int, current_user) -> Optional[Dict[str, Any]]:
    row = db.execute(text("""
        SELECT ta.*, COALESCE(a.balance, 0) as current_balance,
               COALESCE(ta.current_balance, 0) as balance_in_currency,
               b.branch_name as branch_name
        FROM treasury_accounts ta
        LEFT JOIN accounts a ON ta.gl_account_id = a.id
        LEFT JOIN branches b ON ta.branch_id = b.id
        WHERE ta.id = :id
    """), {"id": account_id}).fetchone()
    if not row:
        return None

    out = dict(row._mapping)
    out["iban"] = decrypt_pii(out.get("iban"), tenant_id=current_user.company_id)
    out["account_number"] = decrypt_pii(out.get("account_number"), tenant_id=current_user.company_id)
    out["current_balance_direction"] = _amount_direction(out.get("current_balance"))
    out["balance_in_currency_direction"] = _amount_direction(out.get("balance_in_currency"))
    return _mask_bank_details(out, current_user)


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
def list_treasury_accounts(request: Request, branch_id: Optional[int] = None, current_user = Depends(get_current_user)):
    """عرض حسابات الخزينة والبنوك مع فلترة حسب الفرع"""
    if not current_user.company_id:
         raise HTTPException(**http_error(400, "company_required", request))
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
        rate_map = {r[0]: _dec(r[1]) for r in rate_rows}
        rate_map[base_currency] = Decimal("1")

        rows = []
        for row in result:
            d = dict(row._mapping)
            d["iban"]           = decrypt_pii(d.get("iban"),           tenant_id=tid)
            d["account_number"] = decrypt_pii(d.get("account_number"), tenant_id=tid)
            d = _mask_bank_details(d, current_user)

            # current_balance from accounts.balance is already in base currency
            # balance_in_currency from treasury_accounts.current_balance is in original currency
            acc_currency = d.get("currency", "") or ""
            raw_balance = _dec(d.get("current_balance", 0) or 0).quantize(_D2, ROUND_HALF_UP)
            balance_in_cur = _dec(d.get("balance_in_currency", 0) or 0).quantize(_D2, ROUND_HALF_UP)
            rate = rate_map.get(acc_currency, Decimal("1")).quantize(Decimal("0.000001"), ROUND_HALF_UP)

            d["current_balance"] = str(raw_balance)  # Already in base currency
            d["balance_in_currency"] = str(balance_in_cur)  # Original currency
            d["current_balance_direction"] = _amount_direction(raw_balance)
            d["balance_in_currency_direction"] = _amount_direction(balance_in_cur)
            d["exchange_rate"] = str(rate)
            d["base_currency"] = base_currency

            rows.append(d)
        return rows
    finally:
        db.close()


@router.get("/accounts/opening-balance-preview", dependencies=[Depends(require_permission("treasury.view"))], response_model=Dict[str, Any])
def preview_opening_balance(
    request: Request,
    opening_balance: Decimal = Decimal("0"),
    currency: Optional[str] = None,
    current_user=Depends(get_current_user),
):
    """Authoritative base-currency preview for a treasury opening balance."""
    if not current_user.company_id:
        raise HTTPException(**http_error(400, "company_required", request))
    db = get_db_connection(current_user.company_id)
    try:
        base_currency = db.execute(text(
            "SELECT code FROM currencies WHERE is_base = TRUE LIMIT 1"
        )).scalar() or "SAR"
        source_currency = (currency or base_currency).upper()
        rate = _resolve_exchange_rate(
            db,
            currency=source_currency,
            base_currency=base_currency,
            rate_date=date.today(),
            request=request,
        )
        amount = _dec(opening_balance)
        amount_base = (amount * rate).quantize(_D2, ROUND_HALF_UP)
        return {
            "currency": source_currency,
            "base_currency": base_currency,
            "opening_balance": _money(amount),
            "exchange_rate": str(rate.quantize(Decimal("0.000001"), ROUND_HALF_UP)),
            "opening_balance_base": str(amount_base),
            "opening_balance_base_direction": _amount_direction(amount_base),
        }
    except HTTPException:
        raise
    except Exception:
        logger.error("Treasury opening balance preview failed")
        raise HTTPException(**http_error(500, "internal_error", request))
    finally:
        db.close()

@router.get("/transactions", response_model=List[TransactionResponse], dependencies=[Depends(require_permission("treasury.view"))])
def list_transactions(
    request: Request,
    branch_id: Optional[int] = None,
    treasury_account_id: Optional[int] = None,
    limit: int = 50,
    current_user = Depends(get_current_user),
):
    """عرض سجل العمليات الأخيرة"""
    if not current_user.company_id:
         raise HTTPException(**http_error(400, "company_required", request))
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
        if treasury_account_id:
            validate_treasury_account_access(db, current_user, treasury_account_id, branch_id, request=request)
            query_str += " AND (t.treasury_id = :treasury_account_id OR t.target_treasury_id = :treasury_account_id)"
            params["treasury_account_id"] = treasury_account_id
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
    idempotency_key = request.headers.get("Idempotency-Key")
    with transactional(current_user.company_id) as db:
        if hasattr(account, 'branch_id') and account.branch_id:
            validate_branch_access(current_user, account.branch_id)
        from utils.accounting import get_base_currency
        base_currency = get_base_currency(db)

        if idempotency_key:
            existing_key = db.execute(text("""
                SELECT source, source_id
                FROM journal_entries
                WHERE idempotency_key = :key
                LIMIT 1
            """), {"key": idempotency_key}).fetchone()
            if existing_key and existing_key.source == "treasury_account_opening" and existing_key.source_id:
                existing_response = _treasury_account_response(db, int(existing_key.source_id), current_user)
                if existing_response:
                    return existing_response
            if existing_key:
                raise HTTPException(**http_error(409, "je_creation_conflict", request))

        # Check for duplicate treasury account name
        existing = db.execute(
            text("SELECT id FROM treasury_accounts WHERE name = :name AND is_active = TRUE"),
            {"name": account.name}
        ).fetchone()
        if existing:
            raise HTTPException(**http_error(400, "treasury_name_duplicate", request))

        # Check for duplicate bank account number (if provided)
        if account.account_type == 'bank' and account.account_number:
            existing_bank = db.execute(text(
                """
                SELECT id FROM treasury_accounts
                WHERE account_number = :account_number AND is_active = TRUE
                """
            ), {"account_number": encrypt_pii(account.account_number, tenant_id=current_user.company_id)}).fetchone()
            if existing_bank:
                raise HTTPException(**http_error(400, "treasury_iban_duplicate", request))

        # 1. Determine Parent Account from Chart of Accounts
        # 1101 = Cash & Equivalents
        # Also ensure standard treasury GL accounts (1205, 2105, 1210, 2110) exist
        ensure_treasury_gl_accounts(db, user_id=current_user.id, username=current_user.username, commit=False)
        parent_account = db.execute(text("SELECT id FROM accounts WHERE account_number = '1101'")).fetchone()
        if not parent_account:
            # Fallback: Check code column
            parent_account = db.execute(text("SELECT id FROM accounts WHERE account_code = '1101'")).fetchone()
            
        if not parent_account:
            raise HTTPException(**http_error(500, "main_cash_account_not_found", request))
        
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
                # gl_service will convert to base currency using the backend-resolved rate
                opening_balance = _dec(account.opening_balance).quantize(_D2, ROUND_HALF_UP)
                opening_exchange_rate = _resolve_exchange_rate(
                    db,
                    currency=account.currency,
                    base_currency=base_currency,
                    rate_date=date.today(),
                    request=request,
                )

                # Build journal lines — debit/credit in ORIGINAL currency
                # gl_service converts to base: debit_base = debit * exchange_rate
                je_lines = [
                    {
                        "account_id": gl_id,
                        "debit": opening_balance,  # Original currency
                        "credit": 0,
                        "currency": account.currency,
                        "exchange_rate": opening_exchange_rate,
                        "amount_currency": opening_balance,  # Original currency
                    },
                    {
                        "account_id": capital_gl_id,
                        "debit": 0,
                        "credit": opening_balance,  # Original currency
                        "currency": account.currency,
                        "exchange_rate": opening_exchange_rate,
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
                    exchange_rate=Decimal("1"),
                    source="treasury_account_opening",
                    source_id=new_treasury[0],
                    idempotency_key=idempotency_key,
                )

                # T1.3a: recompute current_balance now that the opening JE is posted
                from utils.treasury_balance import recalc_treasury_from_gl
                recalc_treasury_from_gl(db, new_treasury[0])

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

        return _treasury_account_response(db, new_treasury[0], current_user)

@router.put("/accounts/{id}", dependencies=[Depends(require_sensitive_permission("treasury.edit"))], response_model=Dict[str, Any])
def update_treasury_account(
    id: int,
    account: TreasuryAccountCreate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """تحديث حساب خزينة"""
    with transactional(current_user.company_id) as db:
        if account.branch_id:
            validate_branch_access(current_user, account.branch_id)
        # Check existence
        existing = db.execute(text("SELECT id, gl_account_id FROM treasury_accounts WHERE id = :id"), {"id": id}).fetchone()
        if not existing:
            raise HTTPException(**http_error(404, "treasury_account_not_found", request))
        
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
                raise HTTPException(**http_error(400, "treasury_iban_duplicate", request))
        
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

@router.delete("/accounts/{id}", dependencies=[Depends(require_sensitive_permission("treasury.delete"))], response_model=Dict[str, Any])
def delete_treasury_account(
    id: int,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """حذف حساب خزينة"""
    with transactional(current_user.company_id) as db:
        # Check existence
        account = db.execute(text("SELECT id, name, current_balance, gl_account_id FROM treasury_accounts WHERE id = :id"), 
                           {"id": id}).fetchone()
        if not account:
            raise HTTPException(**http_error(404, "treasury_account_not_found", request))
        
        # Check if account has balance
        if abs(_dec(account.current_balance)) > _D2:
            raise HTTPException(**http_error(400, "cannot_delete_treasury_with_balance", request))
        
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
        
        return {"message": i18n_message("treasury_account_deleted", request)}

@router.post("/transactions/expense", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_sensitive_permission("treasury.manage"))], response_model=Dict[str, Any])
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
        raise HTTPException(**http_error(400, "amount_must_be_positive", request))
    if not data.target_account_id:
        raise HTTPException(**http_error(400, "expense_account_required", request))

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
        cost_center_id=data.cost_center_id,
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

@router.post("/transactions/transfer", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_sensitive_permission("treasury.manage"))], response_model=Dict[str, Any])
def create_transfer(request: Request, data: TransactionCreate, current_user: dict = Depends(get_current_user)):
    """تحويل بين الخزائن/البنوك"""
    if data.transaction_type != 'transfer':
        raise HTTPException(**http_error(400, "invalid_transaction_type", request))
    
    # Validate amount
    if data.amount is None or data.amount <= 0:
        raise HTTPException(**http_error(400, "amount_must_be_positive", request))
    
    # Prevent self-transfer
    if data.treasury_id == data.target_treasury_id:
        raise HTTPException(**http_error(400, "cannot_transfer_same_account", request))
    
    if not data.target_treasury_id:
        raise HTTPException(**http_error(400, "receiving_account_required", request))

    # F-NEW-162 (R-MISSING-IDEMPOTENCY): treasury transfers post a JE AND
    # an audit row in treasury_transactions. Both stores expose
    # ``idempotency_key`` (the latter via Batch 10's alembic migration
    # 0030_audit_h_ddl_sync) so a network retry returns the same pair
    # rather than double-debiting the source treasury.
    idempotency_key = request.headers.get("Idempotency-Key")

    with transactional(current_user.company_id) as db:
        if idempotency_key:
            existing = db.execute(
                text(
                    "SELECT id, transaction_number FROM treasury_transactions "
                    "WHERE idempotency_key = :k LIMIT 1"
                ),
                {"k": idempotency_key},
            ).fetchone()
            if existing:
                return {
                    "success": True,
                    "message": i18n_message("transfer_successful", request),
                    "transaction_id": int(existing.id),
                    "idempotent": True,
                }
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

        from utils.accounting import get_base_currency
        base_currency = get_base_currency(db)
        source_rate = _resolve_exchange_rate(
            db,
            currency=source_currency,
            base_currency=base_currency,
            rate_date=data.transaction_date,
            request=request,
        )
        target_rate = _resolve_exchange_rate(
            db,
            currency=target_currency,
            base_currency=base_currency,
            rate_date=data.transaction_date,
            request=request,
        )
        amount_base = (_dec(data.amount) * source_rate).quantize(_D2, ROUND_HALF_UP)

        # Overdraft validation on source account
        new_balance = _dec(source.current_balance) - _dec(data.amount)
        if new_balance < 0:
            is_bank = source.account_type == 'bank'
            allow_od = source.allow_overdraft
            if not is_bank and not allow_od:
                raise HTTPException(**http_error(
                    400,
                    "insufficient_treasury_balance",
                    request,
                    available=_money(source.current_balance),
                    required=_money(data.amount),
                ))

        # 1. Create Journal Entry — GL-first
        check_fiscal_period_open(db, data.transaction_date)

        # Cross-currency: convert amount to target currency using backend rates.
        if source_currency != target_currency:
            target_amount = (amount_base / target_rate).quantize(_D2, ROUND_HALF_UP)
        else:
            target_amount = data.amount

        je_lines = [
            {
                "account_id": target_gl, "debit": _dec(target_amount), "credit": Decimal("0"),
                "currency": target_currency, "exchange_rate": target_rate, "description": "Transfer In",
                "cost_center_id": data.cost_center_id,
            },
            {
                "account_id": source_gl, "debit": Decimal("0"), "credit": _dec(data.amount),
                "currency": source_currency, "exchange_rate": source_rate, "description": "Transfer Out",
                "cost_center_id": data.cost_center_id,
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
            exchange_rate=source_rate,
            source="treasury_transfer",
            idempotency_key=idempotency_key,
        )

        # 2. Insert Transaction Log — with exchange_rate, currency, and idempotency_key
        trans_id = db.execute(text("""
            INSERT INTO treasury_transactions (
                transaction_number, transaction_date, transaction_type, amount, 
                treasury_id, target_treasury_id, description, reference_number,
                branch_id, created_by, exchange_rate, currency, idempotency_key
            ) VALUES (
                :num, :date, :type, :amount, :src, :dst, :desc, :ref,
                :branch_id, :uid, :exr, :cur, :idem
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
            "branch_id": branch_id,
            "uid": current_user.id,
            "exr": source_rate,
            "cur": source_currency,
            "idem": idempotency_key,
        }).scalar()
        
        # 3. Update Treasury Balances — T1.3a idempotent recompute (after GL entry posted)
        from utils.treasury_balance import recalc_treasury_from_gl
        recalc_treasury_from_gl(db, data.treasury_id)
        recalc_treasury_from_gl(db, data.target_treasury_id)

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


# ────────────────────────── Treasury Reports ──────────────────────────

@router.get("/reports/balances", dependencies=[Depends(require_permission("treasury.view"))], response_model=Dict[str, Any])
def get_treasury_balances_report(
    request: Request,
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

        # Batch-fetch point-in-time GL balances for all treasury GL accounts.
        gl_account_ids = [r.gl_account_id for r in rows if r.gl_account_id]
        gl_balances: dict = {}
        gl_currency_balances: dict = {}
        if gl_account_ids:
            gl_params = {"ids": gl_account_ids, "as_of_date": target_date}
            gl_branch_filter = branch_scope_filter(current_user, branch_id, "je.branch_id", gl_params)
            gl_rows = db.execute(text(f"""
                SELECT jl.account_id,
                       COALESCE(SUM(jl.debit), 0) - COALESCE(SUM(jl.credit), 0) AS gl_balance,
                       COALESCE(SUM(
                           CASE
                               WHEN jl.debit > 0 THEN COALESCE(jl.amount_currency, jl.debit)
                               WHEN jl.credit > 0 THEN -COALESCE(jl.amount_currency, jl.credit)
                               ELSE 0
                           END
                       ), 0) AS gl_balance_currency
                FROM journal_lines jl
                JOIN journal_entries je ON jl.journal_entry_id = je.id
                WHERE jl.account_id = ANY(:ids) AND je.status = 'posted'
                  AND je.entry_date <= :as_of_date
                {gl_branch_filter}
                GROUP BY jl.account_id
            """), gl_params).fetchall()
            for gr in gl_rows:
                gl_balances[gr.account_id] = _dec(gr.gl_balance)
                gl_currency_balances[gr.account_id] = _dec(gr.gl_balance_currency)

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
            if r.gl_account_id and r.gl_account_id in gl_balances:
                bal_base_raw = gl_balances[r.gl_account_id]
                bal = gl_currency_balances.get(r.gl_account_id, bal_base_raw)
            else:
                bal = _dec(r.current_balance or 0)
                bal_base_raw = None
            currency = r.currency or base_currency
            rate = fx_rates.get(currency, Decimal('1')) if currency != base_currency else Decimal('1')
            bal_base = (
                bal_base_raw if bal_base_raw is not None else (bal * rate)
            ).quantize(_D2, ROUND_HALF_UP)

            acc = {
                "id": r.id, "name": r.name, "name_en": r.name_en,
                "account_type": r.account_type, "currency": currency,
                "current_balance": str(bal.quantize(_D2, ROUND_HALF_UP)),
                "balance_in_currency": str(bal.quantize(_D2, ROUND_HALF_UP)),
                "balance_in_base": str(bal_base.quantize(_D2, ROUND_HALF_UP)),
                "gl_balance": str(gl_balances.get(r.gl_account_id, Decimal('0')).quantize(_D2, ROUND_HALF_UP)) if r.gl_account_id else None,
                "current_balance_direction": _amount_direction(bal),
                "balance_in_currency_direction": _amount_direction(bal),
                "balance_in_base_direction": _amount_direction(bal_base),
                "gl_balance_direction": _amount_direction(gl_balances.get(r.gl_account_id, Decimal('0'))) if r.gl_account_id else None,
                "exchange_rate": str(rate.quantize(Decimal("0.000001"), ROUND_HALF_UP)),
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
              AND tt.transaction_date <= :recent_as_of_date
            """ + f" {branch_filter}" + """
	            ORDER BY tt.transaction_date DESC, tt.created_at DESC LIMIT 10
	        """)
        recent_params = dict(params)
        recent_params["recent_as_of_date"] = target_date
        txns = db.execute(txn_q, recent_params).fetchall()
        recent = [{
            "id": t.id, "type": t.transaction_type, "amount": str(_dec(t.amount).quantize(_D2, ROUND_HALF_UP)),
            "description": t.description, "date": str(t.created_at)[:10],
            "account_name": t.account_name
        } for t in txns]

        return {
            "accounts": accounts,
            "summary": {
                "total_cash": str(total_cash.quantize(_D2, ROUND_HALF_UP)),
                "total_bank": str(total_bank.quantize(_D2, ROUND_HALF_UP)),
                "total_all": str(total_all.quantize(_D2, ROUND_HALF_UP)),
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
        raise HTTPException(**http_error(500, "internal_error", request))
    finally:
        db.close()


@router.get("/reports/cashflow", dependencies=[Depends(require_permission("treasury.view"))], response_model=Dict[str, Any])
def get_treasury_cashflow_report(
    request: Request,
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

        movement_cte = """
            WITH movements AS (
                SELECT tt.id, tt.transaction_type, tt.transaction_date, tt.amount,
                       tt.treasury_id AS treasury_id, 'inflow' AS direction
                FROM treasury_transactions tt
                WHERE tt.transaction_type IN ('receipt', 'deposit', 'transfer_in', 'pos_sale')
                UNION ALL
                SELECT tt.id, tt.transaction_type, tt.transaction_date, tt.amount,
                       tt.treasury_id AS treasury_id, 'outflow' AS direction
                FROM treasury_transactions tt
                WHERE tt.transaction_type IN ('expense', 'withdrawal', 'transfer_out', 'payment', 'transfer')
                UNION ALL
                SELECT tt.id, 'transfer_in' AS transaction_type, tt.transaction_date, tt.amount,
                       tt.target_treasury_id AS treasury_id, 'inflow' AS direction
                FROM treasury_transactions tt
                WHERE tt.transaction_type = 'transfer'
                  AND tt.target_treasury_id IS NOT NULL
            )
        """

        # Inflows (receipts, deposits, POS sales, and transfer target legs)
        inflow_q = text(f"""
            {movement_cte}
            SELECT COALESCE(SUM(tt.amount), 0) as total,
                   tt.transaction_type,
                   COUNT(*) as count
            FROM movements tt
            JOIN treasury_accounts ta ON ta.id = tt.treasury_id
            WHERE tt.direction = 'inflow'
              AND tt.transaction_date BETWEEN :start_date AND :end_date
              {branch_filter}
            GROUP BY tt.transaction_type
        """)
        inflows = db.execute(inflow_q, params).fetchall()

        # Outflows (expense, withdrawal, transfer out)
        outflow_q = text(f"""
            {movement_cte}
            SELECT COALESCE(SUM(tt.amount), 0) as total,
                   tt.transaction_type,
                   COUNT(*) as count
            FROM movements tt
            JOIN treasury_accounts ta ON ta.id = tt.treasury_id
            WHERE tt.direction = 'outflow'
              AND tt.transaction_date BETWEEN :start_date AND :end_date
              {branch_filter}
            GROUP BY tt.transaction_type
        """)
        outflows = db.execute(outflow_q, params).fetchall()

        # Daily trend
        daily_q = text(f"""
            {movement_cte}
            SELECT tt.transaction_date as day,
                   SUM(CASE WHEN tt.direction = 'inflow' THEN tt.amount ELSE 0 END) as inflow,
                   SUM(CASE WHEN tt.direction = 'outflow' THEN tt.amount ELSE 0 END) as outflow
            FROM movements tt
            JOIN treasury_accounts ta ON ta.id = tt.treasury_id
            WHERE tt.transaction_date BETWEEN :start_date AND :end_date
              {branch_filter}
            GROUP BY tt.transaction_date
            ORDER BY day
        """)
        daily = db.execute(daily_q, params).fetchall()

        # By account breakdown
        by_account_q = text(f"""
            {movement_cte}
            SELECT ta.id, ta.name, ta.account_type,
                   SUM(CASE WHEN tt.direction = 'inflow' THEN tt.amount ELSE 0 END) as inflow,
                   SUM(CASE WHEN tt.direction = 'outflow' THEN tt.amount ELSE 0 END) as outflow
            FROM movements tt
            JOIN treasury_accounts ta ON ta.id = tt.treasury_id
            WHERE tt.transaction_date BETWEEN :start_date AND :end_date
              {branch_filter}
            GROUP BY ta.id, ta.name, ta.account_type
            ORDER BY ta.name
        """)
        by_account = db.execute(by_account_q, params).fetchall()

        total_in = sum((_dec(r.total) for r in inflows), Decimal("0")).quantize(_D2, ROUND_HALF_UP)
        total_out = sum((_dec(r.total) for r in outflows), Decimal("0")).quantize(_D2, ROUND_HALF_UP)
        net_flow = (total_in - total_out).quantize(_D2, ROUND_HALF_UP)

        return {
            "inflows": [{"type": r.transaction_type, "total": _money(r.total), "count": r.count} for r in inflows],
            "outflows": [{"type": r.transaction_type, "total": _money(r.total), "count": r.count} for r in outflows],
            "total_inflow": str(total_in),
            "total_outflow": str(total_out),
            "net_flow": str((total_in - total_out).quantize(_D2, ROUND_HALF_UP)),
            "net_flow_direction": _amount_direction(net_flow),
            "daily_trend": [
                {
                    "date": str(d.day),
                    "inflow": _money(d.inflow),
                    "outflow": _money(d.outflow),
                    "net": _money(_dec(d.inflow) - _dec(d.outflow)),
                    "net_direction": _amount_direction(_dec(d.inflow) - _dec(d.outflow)),
                }
                for d in daily
            ],
            "by_account": [
                {
                    "id": a.id,
                    "name": a.name,
                    "type": a.account_type,
                    "inflow": _money(a.inflow),
                    "outflow": _money(a.outflow),
                    "net": _money(_dec(a.inflow) - _dec(a.outflow)),
                    "net_direction": _amount_direction(_dec(a.inflow) - _dec(a.outflow)),
                }
                for a in by_account
            ],
            "start_date": start_date,
            "end_date": end_date
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Treasury cashflow report error: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error", request))
    finally:
        db.close()
