from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List
import logging
from routers.auth import get_current_user
from utils.permissions import require_permission
from utils.audit import log_activity
from utils.limiter import limiter
from schemas import CurrencyCreate, CurrencyResponse, ExchangeRateCreate, ExchangeRateResponse

logger = logging.getLogger(__name__)
from schemas.currencies import RevaluationRequest

router = APIRouter(
    prefix="/accounting/currencies",
    tags=["accounting"]
)


def compute_fx_revaluation_diff(
    fc_balance: float,
    bc_balance: float,
    new_rate: float,
    *,
    account_type: str = "asset",
) -> dict:
    """T3.5 (audit #16): pure helper for FX-revaluation diff math.

    Both ``fc_balance`` and ``bc_balance`` MUST be expressed in the
    asset-positive convention (i.e. ``SUM(debit - credit)`` of the
    relevant amount column). For a liability/equity/revenue account
    this means a natural credit balance is represented as a negative
    number — that is exactly what makes the rest of the math work
    uniformly across all account types.

    Returns a dict with keys:
      * ``target_bc``   — fc_balance × new_rate
      * ``diff``        — target_bc − bc_balance (asset-positive)
      * ``side``        — ``'gain'`` if natural balance grew in BC,
                          ``'loss'`` if it shrank, ``None`` if no JE
      * ``natural_old`` / ``natural_new`` — magnitudes after applying
                          the account's normal-balance sign (positive
                          = credit balance for liabilities). Returned
                          for logging/test diagnostics only.
    """
    diff = round(float(fc_balance) * float(new_rate) - float(bc_balance), 4)
    target_bc = round(float(fc_balance) * float(new_rate), 4)

    credit_normal = (account_type or "asset").lower() in {
        "liability",
        "equity",
        "revenue",
        "income",
    }
    natural_old = -bc_balance if credit_normal else bc_balance
    natural_new = -target_bc if credit_normal else target_bc

    if abs(diff) < 0.01:
        side = None
    elif credit_normal:
        # Liability/equity/revenue: bc_balance is negative for a
        # natural credit balance. ``diff < 0`` means the balance
        # became MORE negative (we owe more BC) ⇒ loss.
        side = "loss" if diff < 0 else "gain"
    else:
        # Asset/expense: ``diff > 0`` means the asset grew in BC ⇒ gain.
        side = "gain" if diff > 0 else "loss"

    return {
        "target_bc": target_bc,
        "diff": diff,
        "side": side,
        "natural_old": natural_old,
        "natural_new": natural_new,
    }


@router.get("/", response_model=List[CurrencyResponse])
@limiter.limit("200/minute")
def list_currencies(
    request: Request,
    current_user = Depends(get_current_user),
):
    """List all configured currencies"""
    from database import get_db_connection, get_currency_tables_sql
    db = get_db_connection(current_user.company_id)
    try:
        try:
            result = db.execute(text("SELECT * FROM currencies ORDER BY is_base DESC, code ASC"))
            return result.mappings().all()
        except Exception as e:
            db.rollback()
            if "currencies" in str(e).lower() and "does not exist" in str(e).lower():
                # Auto-create missing currency tables
                db.execute(text(get_currency_tables_sql()))
                db.commit()

                # Fetch TRUE company currency from system database
                from database import get_system_db
                sys_db = get_system_db()
                try:
                    true_currency = sys_db.execute(
                        text("SELECT currency FROM system_companies WHERE id = :id"),
                        {"id": current_user.company_id}
                    ).scalar()
                    default_currency = true_currency if true_currency else "SAR"
                except Exception:
                    default_currency = "SAR"
                finally:
                    sys_db.close()

                # Initialize with company default currency
                db.execute(text("""
                    INSERT INTO currencies (code, name, symbol, is_base, current_rate)
                    VALUES (:code, :name, :symbol, TRUE, 1.0)
                    ON CONFLICT (code) DO UPDATE SET is_base = TRUE
                """), {"code": default_currency, "name": default_currency, "symbol": default_currency})
                
                # Correction Logic: If 'SAR' exists but it's NOT the company currency, remove it or demote it.
                if default_currency != 'SAR':
                     # Remove SAR if it was wrongly added as base
                     db.execute(text("DELETE FROM currencies WHERE code = :code AND is_base = TRUE"), {"code": "SAR"})
                     
                db.commit()
                result = db.execute(text("SELECT * FROM currencies ORDER BY is_base DESC, code ASC"))
                return result.mappings().all()
            raise e
    finally:
        db.close()

@router.post("/", response_model=CurrencyResponse)
@limiter.limit("100/minute")
def create_currency(
    request: Request,
    currency: CurrencyCreate,
    current_user: Any = Depends(require_permission(["accounting.manage", "currencies.manage"]))
):
    """Add a new currency"""
    from database import get_db_connection
    db = get_db_connection(current_user.company_id)
    try:
        # Validate currency code format (ISO 4217: 3 uppercase letters)
        import re
        if not re.match(r'^[A-Z]{3}$', currency.code):
            raise HTTPException(status_code=400, detail="كود العملة يجب أن يكون 3 أحرف إنجليزية كبيرة (مثال: USD, EUR, SAR)")

        # Check if exists
        existing = db.execute(text("SELECT 1 FROM currencies WHERE code = :code"), {"code": currency.code}).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="Currency code already exists")

        # If is_base is True, unset other base currencies
        if currency.is_base:
            db.execute(text("UPDATE currencies SET is_base = FALSE"))

        query = text("""
            INSERT INTO currencies (code, name, name_en, symbol, is_base, current_rate, is_active)
            VALUES (:code, :name, :name_en, :symbol, :is_base, :current_rate, :is_active)
            RETURNING *
        """)
        result = db.execute(query, currency.model_dump()).mappings().fetchone()
        db.commit()
        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="create_currency", resource_type="currency",
                     resource_id=str(result["id"]),
                     details={"code": currency.code}, request=request)
        return result
    finally:
        db.close()

@router.put("/{currency_id}", response_model=CurrencyResponse)
@limiter.limit("100/minute")
def update_currency(
    request: Request,
    currency_id: int,
    currency: CurrencyCreate,
    current_user: Any = Depends(require_permission(["accounting.manage", "currencies.manage"]))
):
    """Update currency details"""
    from database import get_db_connection
    db = get_db_connection(current_user.company_id)
    try:
        # If setting as base, unset others
        if currency.is_base:
            db.execute(text("UPDATE currencies SET is_base = FALSE WHERE id != :id"), {"id": currency_id})
            # Base currency rate must be 1
            currency.current_rate = 1.0
        
        query = text("""
            UPDATE currencies 
            SET code=:code, name=:name, name_en=:name_en, symbol=:symbol, 
                is_base=:is_base, current_rate=:current_rate, is_active=:is_active,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=:id
            RETURNING *
        """)
        params = currency.model_dump()
        params["id"] = currency_id
        
        result = db.execute(query, params).mappings().fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Currency not found")
            
        db.commit()
        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="update_currency", resource_type="currency",
                     resource_id=str(currency_id),
                     details={"code": currency.code}, request=request)
        return result
    finally:
        db.close()

@router.delete("/{currency_id}", response_model=Dict[str, Any])
@limiter.limit("100/minute")
def delete_currency(
    request: Request,
    currency_id: int,
    current_user: Any = Depends(require_permission(["accounting.manage", "currencies.manage"]))
):
    """Delete a currency"""
    from database import get_db_connection
    db = get_db_connection(current_user.company_id)
    try:
        # Don't delete base currency
        check = db.execute(text("SELECT is_base, code FROM currencies WHERE id = :id"), {"id": currency_id}).fetchone()
        if not check:
            raise HTTPException(status_code=404, detail="العملة غير موجودة")
        if check.is_base:
            raise HTTPException(status_code=400, detail="Cannot delete base currency")

        # Check if currency is used in any transactions
        code = check.code
        usage_checks = [
            ("journal_entries", "SELECT 1 FROM journal_entries WHERE currency = :code LIMIT 1"),
            ("invoices", "SELECT 1 FROM invoices WHERE currency = :code LIMIT 1"),
            ("payment_vouchers", "SELECT 1 FROM payment_vouchers WHERE currency = :code LIMIT 1"),
            ("treasury_accounts", "SELECT 1 FROM treasury_accounts WHERE currency = :code LIMIT 1"),
            ("accounts", "SELECT 1 FROM accounts WHERE currency = :code LIMIT 1"),
        ]
        for table_name, check_query in usage_checks:
            try:
                used = db.execute(text(check_query), {"code": code}).fetchone()
                if used:
                    raise HTTPException(status_code=400, detail=f"لا يمكن حذف العملة لأنها مستخدمة في {table_name}")
            except HTTPException:
                raise
            except Exception:
                pass  # Table may not exist yet

        db.execute(text("DELETE FROM currencies WHERE id = :id"), {"id": currency_id})
        db.commit()
        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="delete_currency", resource_type="currency",
                     resource_id=str(currency_id),
                     details={"code": code}, request=request)
        return {"message": "Currency deleted"}
    finally:
        db.close()

@router.post("/rates", response_model=ExchangeRateResponse)
@limiter.limit("100/minute")
def add_exchange_rate(
    request: Request,
    rate_data: ExchangeRateCreate,
    current_user: Any = Depends(require_permission(["accounting.manage", "currencies.manage"]))
):
    """Record a historical exchange rate"""
    from database import get_db_connection
    db = get_db_connection(current_user.company_id)
    try:
        # Validate exchange rate
        if rate_data.rate is None or rate_data.rate <= 0:
            raise HTTPException(**http_error(400, "exchange_rate_must_be_positive"))

        # Check currency exists
        curr = db.execute(text("SELECT code FROM currencies WHERE id = :id"), {"id": rate_data.currency_id}).fetchone()
        if not curr:
            raise HTTPException(status_code=404, detail="Currency not found")

        # Insert or Update (Upsert)
        query = text("""
            INSERT INTO exchange_rates (currency_id, rate_date, rate, source, created_by)
            VALUES (:currency_id, :rate_date, :rate, :source, :user_id)
            ON CONFLICT (currency_id, rate_date) 
            DO UPDATE SET rate = :rate, source = :source, created_at = CURRENT_TIMESTAMP
            RETURNING *
        """)
        params = rate_data.model_dump()
        params["user_id"] = current_user.id
        
        result = db.execute(query, params).mappings().fetchone()
        
        # Also update current rate in currencies table
        db.execute(text("UPDATE currencies SET current_rate = :rate WHERE id = :id"), 
                {"rate": rate_data.rate, "id": rate_data.currency_id})
        
        db.commit()
        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="add_exchange_rate", resource_type="exchange_rate",
                     resource_id=str(result["id"]),
                     details={"currency_id": rate_data.currency_id, "rate": float(rate_data.rate)}, request=request)
        return result
    finally:
        db.close()

@router.get("/{currency_id}/rates", response_model=List[ExchangeRateResponse])
@limiter.limit("200/minute")
def get_rate_history(
    request: Request,
    currency_id: int,
    limit: int = 30,
    current_user: Any = Depends(require_permission(["accounting.view", "currencies.view"]))
):
    """Get exchange rate history"""
    from database import get_db_connection
    db = get_db_connection(current_user.company_id)
    try:
        query = text("""
            SELECT * FROM exchange_rates
            WHERE currency_id = :id
            ORDER BY rate_date DESC
            LIMIT :limit
        """)
        result = db.execute(query, {"id": currency_id, "limit": limit})
        return result.mappings().all()
    finally:
        db.close()


# T8.4 — single source of truth for "what's today's rate for currency X vs base"
# used by every frontend form (sales/buying invoices, journal entries, treasury
# transfers, recurring templates) so the rate isn't hard-coded to 1.0.
@router.get("/current", response_model=Dict[str, Any])
@limiter.limit("300/minute")
def get_current_rate(
    request: Request,
    code: str,
    current_user = Depends(get_current_user),
):
    """Return today's effective rate for ``code`` vs the company base currency.

    Lookup order: latest exchange_rates row whose ``rate_date`` ≤ today.
    Falls back to the currency's own ``exchange_rate`` column (legacy field)
    and finally to 1.0 when ``code`` is the base currency itself.
    """
    code = (code or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail=http_error("currency_code_required"))

    from database import get_db_connection
    db = get_db_connection(current_user.company_id)
    try:
        cur = db.execute(
            text(
                "SELECT id, code, name, name_ar, symbol, is_base, "
                "       coalesce(exchange_rate, 1.0) AS legacy_rate "
                "FROM currencies WHERE upper(code) = :c LIMIT 1"
            ),
            {"c": code},
        ).mappings().first()
        if not cur:
            raise HTTPException(status_code=404, detail=http_error("currency_not_found"))

        if cur["is_base"]:
            return {
                "code": cur["code"],
                "rate": 1.0,
                "is_base": True,
                "rate_date": None,
                "source": "base",
            }

        # Latest exchange_rates row for that currency, dated on/before today.
        latest = db.execute(
            text(
                "SELECT rate, rate_date FROM exchange_rates "
                "WHERE currency_id = :id AND rate_date <= CURRENT_DATE "
                "ORDER BY rate_date DESC LIMIT 1"
            ),
            {"id": cur["id"]},
        ).mappings().first()

        if latest and latest["rate"]:
            return {
                "code": cur["code"],
                "rate": float(latest["rate"]),
                "is_base": False,
                "rate_date": latest["rate_date"].isoformat() if latest["rate_date"] else None,
                "source": "exchange_rates",
            }

        return {
            "code": cur["code"],
            "rate": float(cur["legacy_rate"] or 1.0),
            "is_base": False,
            "rate_date": None,
            "source": "currencies.exchange_rate",
        }
    finally:
        db.close()


@router.post("/revaluate", response_model=Dict[str, Any])
@limiter.limit("100/minute")
def create_revaluation(
    request: Request,
    req: RevaluationRequest,
    current_user: Any = Depends(require_permission(["accounting.manage", "currencies.manage"]))
):
    """
    Calculate and book Unrealized FX Gains/Losses for a specific currency.
    Compares (Account Balance in FC * New Rate) vs (Account Balance in BC from GL).
    """
    from database import get_db_connection
    db = get_db_connection(current_user.company_id)
    try:
        # Validate new rate
        if req.new_rate is None or req.new_rate <= 0:
            raise HTTPException(status_code=400, detail="سعر الصرف الجديد يجب أن يكون أكبر من صفر")

        # 1. Get Currency Info
        currency = db.execute(text("SELECT * FROM currencies WHERE id = :id"), {"id": req.currency_id}).fetchone()
        if not currency:
            raise HTTPException(status_code=404, detail="Currency not found")
        
        code = currency.code

        # Check for duplicate revaluation on same date and currency
        # FIX (T1.2): use source+source_id+entry_date (the actual entry_number is JE-XXXXX,
        # so the prior `entry_number LIKE 'REV-%'` check NEVER matched).
        existing_reval = db.execute(text("""
            SELECT id FROM journal_entries
            WHERE source = 'currency_revaluation'
              AND source_id = :currency_id
              AND entry_date = :rate_date
              AND status = 'posted'
        """), {"currency_id": req.currency_id, "rate_date": req.rate_date}).fetchone()
        if existing_reval:
            raise HTTPException(status_code=400, detail=f"تم إجراء إعادة تقييم لهذه العملة ({code}) بنفس التاريخ. يرجى إلغاء السابقة أولاً.")

        # 2. Get all accounts with this currency
        accounts = db.execute(text("SELECT id, name, balance FROM accounts WHERE currency = :code"), {"code": code}).fetchall()
        
        if not accounts:
            return {"message": "No accounts found with this currency", "entries_created": 0}

        # 3. Get GL Account IDs for Unrealized Gain/Loss
        # FIX (T1.2): resolve via (a) company_settings mapping (acc_map_ufx_gain/loss),
        # then (b) legacy account_code lookup, then (c) numeric COA code, then (d) name match.
        from utils.accounting import get_mapped_account_id

        def _resolve_ufx(side: str):
            """side ∈ {'gain', 'loss'}"""
            mapping_key = f"acc_map_ufx_{side}"
            aid = get_mapped_account_id(db, mapping_key)
            if aid:
                return aid
            legacy_code = "UFX-GAIN" if side == "gain" else "UFX-LOSS"
            numeric_code = "42021" if side == "gain" else "71011"
            name_pattern = "%Unrealized%FX%Gain%" if side == "gain" else "%Unrealized%FX%Loss%"
            row = db.execute(text("""
                SELECT id FROM accounts
                WHERE account_code = :legacy
                   OR account_code = :numeric
                   OR account_number = :numeric
                   OR name_en ILIKE :name_pat
                ORDER BY (account_code = :legacy) DESC, (account_code = :numeric) DESC
                LIMIT 1
            """), {"legacy": legacy_code, "numeric": numeric_code, "name_pat": name_pattern}).fetchone()
            return row.id if row else None

        gain_id = _resolve_ufx("gain")
        loss_id = _resolve_ufx("loss")

        if not gain_id or not loss_id:
            raise HTTPException(
                status_code=422,
                detail=(
                    "حسابات فروقات العملة غير المحققة (UFX-GAIN / UFX-LOSS) غير موجودة في شجرة الحسابات. "
                    "يرجى إنشاء الحسابين 42021 (Unrealized FX Gains) و 71011 (Unrealized FX Losses) "
                    "أو ربطهما عبر إعدادات الشركة (acc_map_ufx_gain, acc_map_ufx_loss)."
                ),
            )

        # 4. Prepare Journal Entry
        journal_entry_lines = []

        for acc in accounts:
            # T3.5 (audit #16): the FC balance must use the SAME sign
            # convention as the BC balance so the comparison
            # `target_bc_value vs bc_balance` is apples-to-apples for
            # both debit-normal accounts (assets, expenses) and
            # credit-normal accounts (liabilities, equity, revenue).
            #
            # Both queries below use the asset-positive convention
            # (debit − credit). For a liability account that means
            # both fc_balance and bc_balance come out NEGATIVE for a
            # natural credit balance, so `diff = target_bc − bc` keeps
            # the correct sign and the gain/loss arms below produce
            # the right JE direction:
            #   * liability + rate ↑ ⇒ owe more in BC ⇒ Cr liability,
            #     Dr Loss (diff < 0).
            #   * asset     + rate ↑ ⇒ worth more in BC ⇒ Dr asset,
            #     Cr Gain   (diff > 0).
            # The `account_type` is captured for traceability/logging
            # but the math does not need to branch on it.
            acc_type_row = db.execute(
                text("SELECT account_type FROM accounts WHERE id = :aid"),
                {"aid": acc.id},
            ).fetchone()
            acc_type = (acc_type_row.account_type if acc_type_row else 'asset') or 'asset'

            # Calculate Foreign Currency Balance from Journal Lines.
            # `amount_currency` is stored as a non-negative magnitude;
            # the debit/credit columns carry the direction.
            fc_balance_row = db.execute(text("""
                SELECT COALESCE(SUM(
                    CASE WHEN debit  > 0 THEN  COALESCE(amount_currency, 0)
                         WHEN credit > 0 THEN -COALESCE(amount_currency, 0)
                         ELSE 0 END
                ), 0) as fc_balance
                FROM journal_lines
                WHERE account_id = :aid
            """), {"aid": acc.id}).fetchone()
            fc_balance = float(fc_balance_row.fc_balance)

            if abs(fc_balance) < 0.01:
                continue

            # Calculate Current Base Currency Balance (Book Value)
            bc_balance_row = db.execute(text("""
                SELECT COALESCE(SUM(debit - credit), 0) as balance 
                FROM journal_lines 
                WHERE account_id = :aid
            """), {"aid": acc.id}).fetchone()
            
            bc_balance = float(bc_balance_row.balance)
            reval = compute_fx_revaluation_diff(
                fc_balance=fc_balance,
                bc_balance=bc_balance,
                new_rate=float(req.new_rate),
                account_type=acc_type,
            )
            diff = reval["diff"]

            if reval["side"] is None:
                continue

            if reval["side"] == "gain" and not (
                (acc_type or "asset").lower() in {"liability", "equity", "revenue", "income"}
            ):
                # Asset / expense gained value in BC.
                journal_entry_lines.append({"account_id": acc.id, "debit": diff, "credit": 0, "desc": f"Revaluation {code} @ {req.new_rate}"})
                journal_entry_lines.append({"account_id": gain_id, "debit": 0, "credit": diff, "desc": f"Unrealized Gain - {acc.name}"})
            elif reval["side"] == "loss" and not (
                (acc_type or "asset").lower() in {"liability", "equity", "revenue", "income"}
            ):
                # Asset / expense lost value in BC.
                abs_diff = abs(diff)
                journal_entry_lines.append({"account_id": acc.id, "debit": 0, "credit": abs_diff, "desc": f"Revaluation {code} @ {req.new_rate}"})
                journal_entry_lines.append({"account_id": loss_id, "debit": abs_diff, "credit": 0, "desc": f"Unrealized Loss - {acc.name}"})
            elif reval["side"] == "loss":
                # Liability/equity/revenue: rate hike means we owe MORE in BC.
                # Increase the credit-normal account (credit) and book a Loss (debit).
                abs_diff = abs(diff)
                journal_entry_lines.append({"account_id": acc.id, "debit": 0, "credit": abs_diff, "desc": f"Revaluation {code} @ {req.new_rate}"})
                journal_entry_lines.append({"account_id": loss_id, "debit": abs_diff, "credit": 0, "desc": f"Unrealized Loss - {acc.name}"})
            else:
                # Liability/equity/revenue gain: rate fell, we owe less ⇒ debit
                # the liability (reduce it) and credit Gain.
                abs_diff = abs(diff)
                journal_entry_lines.append({"account_id": acc.id, "debit": abs_diff, "credit": 0, "desc": f"Revaluation {code} @ {req.new_rate}"})
                journal_entry_lines.append({"account_id": gain_id, "debit": 0, "credit": abs_diff, "desc": f"Unrealized Gain - {acc.name}"})

        if not journal_entry_lines:
            return {"message": "No revaluation needed", "entries_created": 0}

        # 5. FIN-001: Create Journal Entry via centralized GL service
        try:
            from services.gl_service import create_journal_entry as gl_create_journal_entry
            from utils.fiscal_lock import check_fiscal_period_open

            # Fiscal-period lock: block posting into a closed period.
            check_fiscal_period_open(db, str(req.rate_date))

            gl_lines = []
            for line in journal_entry_lines:
                gl_lines.append({
                    "account_id": line["account_id"],
                    "debit": line["debit"],
                    "credit": line["credit"],
                    "description": line["desc"],
                })

            je_id, entry_num = gl_create_journal_entry(
                db=db,
                company_id=current_user.company_id,
                date=str(req.rate_date),
                description=req.description or f"Currency Revaluation {code} to {req.new_rate}",
                lines=gl_lines,
                user_id=current_user.id,
                branch_id=getattr(current_user, 'branch_id', None),
                reference=f"REV-{code}",
                source="currency_revaluation",
                source_id=req.currency_id,
            )
            
            # Update currency current_rate
            db.execute(text("UPDATE currencies SET current_rate = :rate WHERE id = :id"),
                       {"rate": req.new_rate, "id": req.currency_id})
                
            db.commit()
            
            log_activity(db, user_id=current_user.id, username=current_user.username,
                         action="currency_revaluation", resource_type="currency",
                         resource_id=str(req.currency_id),
                         details={"new_rate": float(req.new_rate), "je_id": je_id, "lines": len(journal_entry_lines)}, request=request)
            
            return {
                "message": "Revaluation completed successfully",
                "journal_entry_id": je_id,
                "entry_number": entry_num,
                "lines_count": len(journal_entry_lines),
                "total_impact": sum(l['debit'] for l in journal_entry_lines) / 2
            }
        except HTTPException:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            logger.exception("Error during currency revaluation")
            raise HTTPException(status_code=500, detail="خطأ أثناء إعادة التقييم")
    finally:
        db.close()
