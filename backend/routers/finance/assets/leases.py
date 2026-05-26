"""assets sub-router — split from monolithic assets.py (T6.3).

Mounted under the parent router via assets/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error, i18n_message
from sqlalchemy import text
from typing import Any, Dict, Optional
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import logging
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import require_permission
from utils.fiscal_lock import check_fiscal_period_open
from utils.tax_precision import require_idempotency_key
from schemas.assets import (
    LeasePaymentCreate,
    LeaseContractCreate,
)

logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')

def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')

router = APIRouter()

from .core import _D2, _D4, _dec  # noqa: E402

@router.get("/leases", dependencies=[Depends(require_permission("assets.view"))], response_model=Dict[str, Any])
def list_lease_contracts(
    status: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """عقود الإيجار IFRS 16"""
    with transactional(current_user.company_id) as conn:
        q = """
            SELECT lc.*, a.name as asset_name, a.code as asset_code
            FROM lease_contracts lc
            LEFT JOIN assets a ON a.id = lc.asset_id
            WHERE 1=1
        """
        params = {}
        if status:
            q += " AND lc.status = :st"
            params["st"] = status
        if branch_id:
            q += " AND a.branch_id = :branch_id"
            params["branch_id"] = branch_id
        q += " ORDER BY lc.end_date ASC"
        rows = conn.execute(text(q), params).fetchall()

        total_rou = Decimal('0')
        total_liability = Decimal('0')
        res_rows = []
        for r in rows:
            d = dict(r._mapping)
            total_rou += _dec(d.get("right_of_use_value"))
            total_liability += _dec(d.get("lease_liability"))
            # Serialize Decimal fields strictly as string to prevent drift
            d["right_of_use_value"] = str(d["right_of_use_value"]) if d.get("right_of_use_value") is not None else "0"
            d["lease_liability"] = str(d["lease_liability"]) if d.get("lease_liability") is not None else "0"
            res_rows.append(d)

        return {
            "data": res_rows,
            "summary": {
                "total_rou": str(total_rou.quantize(_D2, ROUND_HALF_UP)),
                "total_liability": str(total_liability.quantize(_D2, ROUND_HALF_UP))
            }
        }


@router.post("/leases", dependencies=[Depends(require_permission("assets.create"))], response_model=Dict[str, Any])
def create_lease_contract(request: Request, lease: LeaseContractCreate, current_user: dict = Depends(get_current_user)):
    """إنشاء عقد إيجار IFRS 16 مع قيد محاسبي الاعتراف الأولي"""
    idempotency_key = require_idempotency_key(request, operation="asset lease contract")
    with transactional(current_user.company_id) as conn:
        try:
            existing = conn.execute(text("""
                SELECT id, right_of_use_value
                FROM lease_contracts
                WHERE asset_id IS NOT DISTINCT FROM :aid
                  AND start_date = :sd
                  AND end_date = :ed
                  AND lessor_name IS NOT DISTINCT FROM :ln
                  AND monthly_payment = :mp
                LIMIT 1
            """), {
                "aid": lease.asset_id,
                "sd": lease.start_date,
                "ed": lease.end_date,
                "ln": lease.lessor_name,
                "mp": _dec(lease.monthly_payment).quantize(_D2, ROUND_HALF_UP),
            }).fetchone()
            if existing:
                return {
                    "id": existing.id,
                    "right_of_use_value": str(_dec(existing.right_of_use_value).quantize(_D2, ROUND_HALF_UP)),
                    "replayed": True,
                }

            # Calculate right-of-use value using present value of payments
            monthly = _dec(lease.monthly_payment).quantize(_D2, ROUND_HALF_UP)
            total = int(lease.total_payments)
            rate = (_dec(lease.discount_rate) / Decimal('100') / Decimal('12')).quantize(_D4, ROUND_HALF_UP)
            if rate > 0 and total > 0:
                one = Decimal('1')
                rou_value = (monthly * (one - (one + rate) ** (-total)) / rate).quantize(_D2, ROUND_HALF_UP)
            else:
                rou_value = (monthly * Decimal(total)).quantize(_D2, ROUND_HALF_UP)
    
            result = conn.execute(text("""
                INSERT INTO lease_contracts (asset_id, description, lessor_name, lease_type,
                    start_date, end_date, monthly_payment, total_payments, discount_rate,
                    right_of_use_value, lease_liability, accumulated_depreciation, status)
                VALUES (:aid, :desc, :ln, :lt, :sd, :ed, :mp, :tp, :dr, :rou, :ll, 0, :st)
                RETURNING id
            """), {
                "aid": lease.asset_id, "desc": lease.description,
                "ln": lease.lessor_name, "lt": lease.lease_type,
                "sd": lease.start_date.isoformat(), "ed": lease.end_date.isoformat(),
                "mp": monthly, "tp": total, "dr": _dec(lease.discount_rate).quantize(_D4, ROUND_HALF_UP),
                "rou": rou_value, "ll": rou_value, "st": lease.status
            })
            lid = result.fetchone()[0]
    
            # IFRS 16 Initial Recognition Journal Entry:
            # Dr. Right-of-Use Asset (1600) / Cr. Lease Liability (2300)
            journal_entry_id = None
            if rou_value > 0:
                rou_acc = conn.execute(text(
                    "SELECT id FROM accounts WHERE account_code IN ('1600','1610','1500') AND is_active = TRUE ORDER BY account_code LIMIT 1"
                )).fetchone()
                liability_acc = conn.execute(text(
                    "SELECT id FROM accounts WHERE account_code IN ('2300','2310','2200') AND is_active = TRUE ORDER BY account_code LIMIT 1"
                )).fetchone()
    
                if rou_acc and liability_acc:
                    check_fiscal_period_open(conn, lease.start_date)
                    
                    je_lines = [
                        {
                            "account_id": rou_acc.id, "debit": rou_value, "credit": 0,
                            "description": f"أصل حق الاستخدام - {lease.description or ''}"
                        },
                        {
                            "account_id": liability_acc.id, "debit": 0, "credit": rou_value,
                            "description": f"التزام إيجار - {lease.description or ''}"
                        }
                    ]
                    
                    from services.gl_service import create_journal_entry as gl_create_journal_entry
                    from utils.accounting import get_base_currency
                    base_currency = get_base_currency(conn)
                    
                    journal_entry_id, entry_number = gl_create_journal_entry(
                        db=conn,
                        company_id=current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id,
                        date=lease.start_date,
                        description=f"اعتراف أولي بعقد إيجار IFRS 16 - {lease.description or ''} - {lease.lessor_name or ''}",
                        lines=je_lines,
                        user_id=current_user.get("id") if isinstance(current_user, dict) else current_user.id,
                        currency=base_currency,
                        exchange_rate=Decimal("1"),
                        source="lease_contract",
                        source_id=lid,
                        idempotency_key=f"{idempotency_key}:lease-contract:{lid}",
                    )
    
    
            # T030: Generate straight-line ROU depreciation schedule over lease term
            if rou_value > 0 and lease.asset_id:
                try:
                    lease_start = lease.start_date
                    lease_end = lease.end_date
                    lease_months = (lease_end.year - lease_start.year) * 12 + (lease_end.month - lease_start.month)
                    lease_years = max(1, (lease_months + 11) // 12)
                    annual_rou_dep = (rou_value / _dec(lease_years)).quantize(_D2, ROUND_HALF_UP)
                    accumulated = Decimal('0')
                    for i in range(1, lease_years + 1):
                        year = lease_start.year + i - 1
                        dep = annual_rou_dep
                        if accumulated + dep > rou_value:
                            dep = (rou_value - accumulated).quantize(_D2, ROUND_HALF_UP)
                        if dep <= 0:
                            break
                        accumulated = (accumulated + dep).quantize(_D2, ROUND_HALF_UP)
                        bv = (rou_value - accumulated).quantize(_D2, ROUND_HALF_UP)
                        conn.execute(text("""
                            INSERT INTO asset_depreciation_schedule (
                                asset_id, fiscal_year, amount, accumulated_amount, book_value, date
                            ) VALUES (:aid, :year, :amt, :acc, :bv, :date)
                        """), {
                            "aid": lease.asset_id, "year": year,
                            "amt": dep, "acc": accumulated, "bv": bv,
                            "date": date(year, 12, 31)
                        })
                    conn.commit()
                except Exception:
                    logger.warning("Failed to generate ROU depreciation schedule for lease %s", lid)
    
            return {
                "id": lid, "right_of_use_value": str(rou_value),
                "journal_entry_id": journal_entry_id,
                "message": i18n_message("asset_lease_created_success", request) + (" مع قيد محاسبي" if journal_entry_id else "")
            }
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.get("/leases/{lease_id}/schedule", dependencies=[Depends(require_permission("assets.view"))], response_model=Dict[str, Any])
def get_lease_schedule(lease_id: int, request: Request, current_user: dict = Depends(get_current_user)):
    """جدول استهلاك عقد الإيجار"""
    with transactional(current_user.company_id) as conn:
        row = conn.execute(text("SELECT * FROM lease_contracts WHERE id = :id"),
                           {"id": lease_id}).fetchone()
        if not row:
            raise HTTPException(**http_error(404, "lease_not_found", request))
        lc = dict(row._mapping)
        monthly = _dec(lc.get("monthly_payment", 0)).quantize(_D2, ROUND_HALF_UP)
        total = int(lc.get("total_payments", 0))
        rate = (_dec(lc.get("discount_rate", 5)) / Decimal('100') / Decimal('12')).quantize(_D4, ROUND_HALF_UP)
        balance = _dec(lc.get("lease_liability", 0)).quantize(_D2, ROUND_HALF_UP)
        schedule = []
        for i in range(1, total + 1):
            interest = (balance * rate).quantize(_D2, ROUND_HALF_UP)
            principal = (monthly - interest).quantize(_D2, ROUND_HALF_UP)
            balance = (balance - principal).quantize(_D2, ROUND_HALF_UP)
            schedule.append({
                # F-NEW-059 (R-FLOAT-MONEY, Req 8.5): emit Decimal as
                # canonical strings so the IFRS 16 schedule preview
                # preserves cent precision over the JSON boundary.
                "period": i,
                "payment": str(monthly),
                "interest": str(interest),
                "principal": str(principal),
                "balance": str(max(balance, Decimal('0'))),
            })
        return {"lease": lc, "schedule": schedule}


@router.post("/leases/{lease_id}/post-payment", dependencies=[Depends(require_permission("assets.create"))], response_model=Dict[str, Any])
def post_lease_payment(request: Request, lease_id: int, payment: LeasePaymentCreate, current_user: dict = Depends(get_current_user)):
    """Post IFRS 16 lease payment — splits into interest expense + principal reduction."""
    idempotency_key = require_idempotency_key(request, operation="asset lease payment")
    with transactional(current_user.company_id) as conn:
        try:
            row = conn.execute(text("SELECT * FROM lease_contracts WHERE id = :id FOR UPDATE"), {"id": lease_id}).fetchone()
            if not row:
                raise HTTPException(**http_error(404, "lease_not_found"))
            lc = dict(row._mapping)
    
            if lc.get("status") != "active":
                raise HTTPException(**http_error(400, "lease_not_active"))
    
            check_fiscal_period_open(conn, payment.payment_date)
    
            # Interest/principal split per IFRS 16
            balance = _dec(lc.get("lease_liability", 0)).quantize(_D2, ROUND_HALF_UP)
            monthly_rate = (_dec(lc.get("discount_rate", 5)) / Decimal('100') / Decimal('12')).quantize(_D4, ROUND_HALF_UP)
            interest = (balance * monthly_rate).quantize(_D2, ROUND_HALF_UP)
            principal = (_dec(payment.amount) - interest).quantize(_D2, ROUND_HALF_UP)
            if principal < 0:
                principal = Decimal('0')
                interest = _dec(payment.amount).quantize(_D2, ROUND_HALF_UP)
    
            new_balance = (balance - principal).quantize(_D2, ROUND_HALF_UP)
            if new_balance < 0:
                new_balance = Decimal('0')
    
            # Update lease liability
            conn.execute(text("""
                UPDATE lease_contracts
                SET lease_liability = :bal, updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """), {"bal": new_balance, "id": lease_id})
    
            # Journal Entry: Dr. Interest Expense + Dr. Lease Liability / Cr. Cash
            journal_entry_id = None
            try:
                from utils.accounting import get_base_currency
                interest_acc = conn.execute(text(
                    "SELECT id FROM accounts WHERE account_code IN ('5200','5210','5100') AND is_active = TRUE ORDER BY account_code LIMIT 1"
                )).fetchone()
                liability_acc = conn.execute(text(
                    "SELECT id FROM accounts WHERE account_code IN ('2300','2310','2200') AND is_active = TRUE ORDER BY account_code LIMIT 1"
                )).fetchone()
                cash_acc = conn.execute(text(
                    "SELECT id FROM accounts WHERE account_code IN ('1100','1110','1000') AND is_active = TRUE ORDER BY account_code LIMIT 1"
                )).fetchone()
    
                if interest_acc and liability_acc and cash_acc:
                    je_lines = []
                    if interest > 0:
                        je_lines.append({
                            "account_id": interest_acc.id, "debit": interest, "credit": 0,
                            "description": f"مصروف فائدة إيجار - عقد #{lease_id}"
                        })
                    if principal > 0:
                        je_lines.append({
                            "account_id": liability_acc.id, "debit": principal, "credit": 0,
                            "description": f"تخفيض التزام إيجار - عقد #{lease_id}"
                        })
                    je_lines.append({
                        "account_id": cash_acc.id, "debit": 0, "credit": _dec(payment.amount).quantize(_D2, ROUND_HALF_UP),
                        "description": f"دفعة إيجار - عقد #{lease_id}"
                    })
    
                    from services.gl_service import create_journal_entry as gl_create_journal_entry
                    base_currency = get_base_currency(conn)
                    journal_entry_id, _ = gl_create_journal_entry(
                        db=conn,
                        company_id=current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id,
                        date=payment.payment_date,
                        description=f"دفعة إيجار IFRS 16 - عقد #{lease_id}",
                        lines=je_lines,
                        user_id=current_user.get("id") if isinstance(current_user, dict) else current_user.id,
                        currency=base_currency,
                        exchange_rate=Decimal("1"),
                        source="lease_payment",
                        source_id=lease_id,
                        idempotency_key=f"{idempotency_key}:lease-payment:{lease_id}",
                    )
            except Exception:
                logger.warning("Failed to create GL entry for lease payment %s", lease_id)
    
            return {
                "lease_id": lease_id,
                # F-NEW-059: Decimal-string serialisation preserves the
                # IFRS 16 split precision at the wire boundary.
                "payment_amount": str(_dec(payment.amount).quantize(_D2, ROUND_HALF_UP)),
                "interest": str(interest),
                "principal": str(principal),
                "remaining_liability": str(new_balance),
                "journal_entry_id": journal_entry_id
            }
        except HTTPException:
            pass
            raise
        except Exception:
            pass
            logger.exception("Error posting lease payment")
            raise HTTPException(**http_error(500, "internal_error"))
