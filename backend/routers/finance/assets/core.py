"""assets sub-router — split from monolithic assets.py (T6.3).

Mounted under the parent router via assets/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pydantic import BaseModel
import logging
from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import branch_scope_filter_from_scope, require_permission, resolve_branch_scope, validate_branch_access, require_module
from utils.accounting import get_mapped_account_id
from utils.fiscal_lock import check_fiscal_period_open
from schemas.assets import (
    AssetCreate, AssetUpdate, AssetDisposal, LeasePaymentCreate,
    AssetTransferCreate, AssetRevaluationCreate, MaintenanceComplete,
    LeaseContractCreate, DecliningBalanceInput, UnitsOfProductionInput,
    InsuranceCreate, MaintenanceCreate, AssetQRUpdate, ImpairmentTestInput,
)

logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')

def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')

router = APIRouter()

def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal("0")

# ============================================================
# ❗️ IMPORTANT: Static routes MUST come before /{asset_id}
#   to prevent FastAPI from treating 'transfers'/'revaluations'
#   as an integer path parameter (causing 422 errors).
# ============================================================

# ---------- ASSET-002: Asset Transfers (STATIC - must be before /{asset_id}) ----------

class DepreciationRunInput(BaseModel):
    through_date: Optional[date] = None
    asset_id: Optional[int] = None


@router.get("/", dependencies=[Depends(require_permission("assets.view"))], response_model=List[Dict[str, Any]])
def list_assets(
    branch_id: Optional[int] = None,
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """List Assets."""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    
    with transactional(current_user.company_id) as conn:
        params = {}
        query = "SELECT * FROM assets WHERE 1=1"
        query += f" {branch_scope_filter_from_scope(branch_scope, 'branch_id', params)}"
        if status:
            query += " AND status = :status"
            params["status"] = status
            
        query += " ORDER BY created_at DESC"
        
        assets = conn.execute(text(query), params).fetchall()
        return [dict(row._mapping) for row in assets]

@router.post("/", dependencies=[Depends(require_permission("assets.create"))], response_model=Dict[str, Any])
def create_asset(asset: AssetCreate, current_user: dict = Depends(get_current_user)):
    """Create Asset."""
    conn = get_db_connection(current_user.company_id)
    trans = conn.begin()
    try:
        # Insert Asset
        result = conn.execute(text("""
            INSERT INTO assets (
                company_id, branch_id, name, code, type, purchase_date, 
                cost, residual_value, life_years, depreciation_method, currency
            ) VALUES (
                :cid, :bid, :name, :code, :type, :pdate, 
                :cost, :res_val, :life, :method, :currency
            ) RETURNING id
        """), {
            "cid": current_user.company_id,
            "bid": asset.branch_id,
            "name": asset.name,
            "code": asset.code,
            "type": asset.type,
            "pdate": asset.purchase_date,
            "cost": asset.cost,
            "res_val": asset.residual_value,
            "life": asset.life_years,
            "method": asset.depreciation_method,
            "currency": asset.currency
        }).fetchone()
        
        asset_id = result.id
        
        # Calculate Depreciation Schedule (Straight Line)
        if asset.life_years > 0 and asset.depreciation_method == 'straight_line':
            depreciable_amount = (_dec(asset.cost) - _dec(asset.residual_value)).quantize(_D2, ROUND_HALF_UP)
            annual_depreciation = (depreciable_amount / _dec(asset.life_years)).quantize(_D4, ROUND_HALF_UP)
            
            # Partial first year based on purchase month
            current_accumulated = Decimal('0')
            purchase_year = asset.purchase_date.year
            purchase_month = asset.purchase_date.month
            
            # Calculate first year fraction (remaining months / 12)
            remaining_months_first_year = 12 - purchase_month + 1  # Include purchase month
            first_year_fraction = _dec(remaining_months_first_year) / Decimal('12')
            first_year_amount = (annual_depreciation * first_year_fraction).quantize(_D2, ROUND_HALF_UP)
            
            total_years = asset.life_years
            # If partial first year, we need an extra year at the end for the remainder
            has_partial_first_year = purchase_month > 1
            schedule_years = total_years + (1 if has_partial_first_year else 0)
            
            for i in range(1, schedule_years + 1):
                if i == 1:
                    # First year — partial (or full if purchased in January)
                    year = purchase_year
                    amount = first_year_amount
                elif i == schedule_years and has_partial_first_year:
                    # Last year — remainder from first year's partial amount
                    year = purchase_year + i - 1
                    amount = (depreciable_amount - current_accumulated).quantize(_D2, ROUND_HALF_UP)
                else:
                    # Full intermediate years
                    year = purchase_year + i - 1
                    amount = annual_depreciation.quantize(_D2, ROUND_HALF_UP)
                
                # Safety: ensure we don't exceed depreciable amount
                if current_accumulated + amount > depreciable_amount:
                    amount = (depreciable_amount - current_accumulated).quantize(_D2, ROUND_HALF_UP)
                if amount <= 0:
                    break
                
                current_accumulated = (current_accumulated + amount).quantize(_D2, ROUND_HALF_UP)
                book_val = (_dec(asset.cost) - current_accumulated).quantize(_D2, ROUND_HALF_UP)
                
                conn.execute(text("""
                    INSERT INTO asset_depreciation_schedule (
                        asset_id, fiscal_year, amount, accumulated_amount, book_value, date
                    ) VALUES (
                        :aid, :year, :amt, :acc, :bv, :date
                    )
                """), {
                    "aid": asset_id,
                    "year": year,
                    "amt": amount,
                    "acc": current_accumulated,
                    "bv": book_val,
                    "date": date(year, 12, 31)
                })

        # Declining Balance schedule (T029)
        elif asset.life_years > 0 and asset.depreciation_method == 'declining_balance':
            cost = _dec(asset.cost)
            residual = _dec(asset.residual_value)
            life = asset.life_years
            rate = Decimal('2') / _dec(life)  # Double-declining default
            book_value = cost
            current_accumulated = Decimal('0')
            purchase_year = asset.purchase_date.year

            for i in range(1, life + 1):
                dep = (book_value * rate).quantize(_D2, ROUND_HALF_UP)
                if book_value - dep < residual:
                    dep = (book_value - residual).quantize(_D2, ROUND_HALF_UP)
                if dep <= 0:
                    break
                book_value = (book_value - dep).quantize(_D2, ROUND_HALF_UP)
                current_accumulated = (current_accumulated + dep).quantize(_D2, ROUND_HALF_UP)
                year = purchase_year + i - 1

                conn.execute(text("""
                    INSERT INTO asset_depreciation_schedule (
                        asset_id, fiscal_year, amount, accumulated_amount, book_value, date
                    ) VALUES (:aid, :year, :amt, :acc, :bv, :date)
                """), {
                    "aid": asset_id, "year": year, "amt": dep,
                    "acc": current_accumulated, "bv": book_value,
                    "date": date(year, 12, 31)
                })
                if book_value <= residual:
                    break

        # Sum-of-Years' Digits schedule (T029)
        elif asset.life_years > 0 and asset.depreciation_method == 'sum_of_years':
            cost = _dec(asset.cost)
            residual = _dec(asset.residual_value)
            life = asset.life_years
            depreciable = cost - residual
            syd = _dec(life * (life + 1)) / Decimal('2')
            current_accumulated = Decimal('0')
            purchase_year = asset.purchase_date.year

            for i in range(1, life + 1):
                fraction = _dec(life - i + 1) / syd
                dep = (depreciable * fraction).quantize(_D2, ROUND_HALF_UP)
                # Safety cap
                if current_accumulated + dep > depreciable:
                    dep = (depreciable - current_accumulated).quantize(_D2, ROUND_HALF_UP)
                if dep <= 0:
                    break
                current_accumulated = (current_accumulated + dep).quantize(_D2, ROUND_HALF_UP)
                book_value = (cost - current_accumulated).quantize(_D2, ROUND_HALF_UP)
                year = purchase_year + i - 1

                conn.execute(text("""
                    INSERT INTO asset_depreciation_schedule (
                        asset_id, fiscal_year, amount, accumulated_amount, book_value, date
                    ) VALUES (:aid, :year, :amt, :acc, :bv, :date)
                """), {
                    "aid": asset_id, "year": year, "amt": dep,
                    "acc": current_accumulated, "bv": book_value,
                    "date": date(year, 12, 31)
                })
        
        trans.commit()
        return {"id": asset_id, "message": "Asset created successfully"}
    except HTTPException:
        trans.rollback()
        raise
    except Exception:
        trans.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        conn.close()


# ===================== B6: IFRS 16 Lease Contracts =====================

@router.get("/{asset_id}", dependencies=[Depends(require_permission("assets.view"))], response_model=Dict[str, Any])
def get_asset(asset_id: int, current_user: dict = Depends(get_current_user)):
    """Get Asset."""
    with transactional(current_user.company_id) as conn:
        asset = conn.execute(text("SELECT * FROM assets WHERE id = :id"), {"id": asset_id}).fetchone()
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")
            
        schedule = conn.execute(text("""
            SELECT * FROM asset_depreciation_schedule 
            WHERE asset_id = :id 
            ORDER BY fiscal_year ASC
        """), {"id": asset_id}).fetchall()
        
        return {
            "asset": dict(asset._mapping),
            "schedule": [dict(row._mapping) for row in schedule]
        }

@router.put("/{asset_id}", dependencies=[Depends(require_permission("assets.manage"))], response_model=Dict[str, Any])
def update_asset(asset_id: int, data: AssetUpdate, current_user: dict = Depends(get_current_user)):
    """Update an existing asset (only if not disposed)"""
    conn = get_db_connection(current_user.company_id)
    trans = conn.begin()
    try:
        existing = conn.execute(text("SELECT * FROM assets WHERE id = :id"), {"id": asset_id}).fetchone()
        if not existing:
            raise HTTPException(**http_error(404, "asset_not_found"))
        if existing.status == 'disposed':
            raise HTTPException(status_code=400, detail="لا يمكن تعديل أصل مستبعد")
        
        allowed_fields = ['name', 'code', 'type', 'status', 'cost', 'residual_value', 'life_years', 
                         'location', 'branch_id', 'notes', 'purchase_date']
        updates = []
        params = {"id": asset_id}
        data_dict = data.model_dump(exclude_unset=True)
        for field in allowed_fields:
            if field in data_dict:
                updates.append(f"{field} = :{field}")
                params[field] = data_dict[field]
        
        if updates:
            conn.execute(text(f"UPDATE assets SET {', '.join(updates)} WHERE id = :id"), params)
            trans.commit()
        
        return {"message": "تم تحديث الأصل بنجاح"}
    except HTTPException:
        trans.rollback()
        raise
    except Exception:
        trans.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        conn.close()

@router.post("/{asset_id}/dispose", dependencies=[Depends(require_permission("assets.manage"))], response_model=Dict[str, Any])
def dispose_asset(asset_id: int, disposal: AssetDisposal, current_user: dict = Depends(get_current_user)):
    """استبعاد أصل ثابت مع معثرات محاسبية (إهلاك متراكم، ربح/خسارة)"""
    conn = get_db_connection(current_user.company_id)
    trans = conn.begin()
    try:
        from utils.accounting import get_base_currency
        base_currency = get_base_currency(conn)
        # 1. Get Asset & Accumulated Depreciation
        asset = conn.execute(text("SELECT * FROM assets WHERE id = :id FOR UPDATE"), {"id": asset_id}).fetchone()
        if not asset or asset.status == 'disposed':
            raise HTTPException(status_code=400, detail="الأصل غير موجود أو تم استبعاده مسبقاً")
            
        acc_depr_recorded = conn.execute(text("""
            SELECT COALESCE(SUM(amount), 0) FROM asset_depreciation_schedule 
            WHERE asset_id = :id AND posted = TRUE
        """), {"id": asset_id}).scalar()
        
        # 2. Update Asset Status
        conn.execute(text("UPDATE assets SET status = 'disposed', updated_at = NOW() WHERE id = :id"), {"id": asset_id})

        # T039: Cancel un-posted future depreciation entries
        conn.execute(text("""
            DELETE FROM asset_depreciation_schedule
            WHERE asset_id = :id AND posted = FALSE AND date > :disposal_date
        """), {"id": asset_id, "disposal_date": disposal.disposal_date})

        # T040: Calculate and insert pro-rata depreciation for disposal period
        last_posted = conn.execute(text("""
            SELECT date, accumulated_amount FROM asset_depreciation_schedule
            WHERE asset_id = :id AND posted = TRUE
            ORDER BY date DESC LIMIT 1
        """), {"id": asset_id}).fetchone()

        if last_posted and asset.life_years:
            last_dep_date = last_posted.date if hasattr(last_posted.date, 'year') else date.fromisoformat(str(last_posted.date))
            # Calculate months from last posted depreciation to disposal date
            months_elapsed = (disposal.disposal_date.year - last_dep_date.year) * 12 + (disposal.disposal_date.month - last_dep_date.month)
            if months_elapsed > 0:
                annual_dep = (_dec(asset.cost) - _dec(asset.residual_value or 0)) / _dec(asset.life_years)
                pro_rata = (annual_dep * _dec(months_elapsed) / Decimal('12')).quantize(_D2, ROUND_HALF_UP)
                if pro_rata > 0:
                    new_accumulated = (_dec(last_posted.accumulated_amount) + pro_rata).quantize(_D2, ROUND_HALF_UP)
                    new_bv = (_dec(asset.cost) - new_accumulated).quantize(_D2, ROUND_HALF_UP)
                    conn.execute(text("""
                        INSERT INTO asset_depreciation_schedule
                            (asset_id, fiscal_year, date, amount, accumulated_amount, book_value, posted)
                        VALUES (:aid, :year, :date, :amt, :acc, :bv, FALSE)
                    """), {
                        "aid": asset_id, "year": disposal.disposal_date.year,
                        "date": disposal.disposal_date, "amt": pro_rata,
                        "acc": new_accumulated, "bv": new_bv,
                    })
                    # Recalculate accumulated depreciation including pro-rata
                    acc_depr_recorded = _dec(acc_depr_recorded) + pro_rata
        
        # 3. GL Entry (Automated)
        acc_fixed_assets = get_mapped_account_id(conn, "acc_map_fixed_assets")
        acc_acc_depr = get_mapped_account_id(conn, "acc_map_acc_depr")
        acc_gain = get_mapped_account_id(conn, "acc_map_asset_gain")
        acc_loss = get_mapped_account_id(conn, "acc_map_asset_loss")
        acc_cash = get_mapped_account_id(conn, "acc_map_cash_main")
        if disposal.payment_method == 'bank':
            acc_cash = get_mapped_account_id(conn, "acc_map_bank")
            
        book_value = (_dec(asset.cost) - _dec(acc_depr_recorded)).quantize(_D2, ROUND_HALF_UP)
        gain_loss = (_dec(disposal.disposal_price) - book_value).quantize(_D2, ROUND_HALF_UP)
        
        # Use UUID OR simple generation
        ts = datetime.now().strftime('%Y%m%d%H%M%S')
        je_num = f"JE-ASSET-DISP-{asset_id}-{ts}"
        
        # Check if JE exists for this asset disposal (to avoid double posting)
        exists = conn.execute(text("SELECT 1 FROM journal_entries WHERE reference = :ref"), {"ref": f"ASSET-DISP-{asset_id}"}).fetchone()
        if exists:
             raise HTTPException(status_code=400, detail="تم ترحيل قيد استبعاد لهذا الأصل مسبقاً")

        check_fiscal_period_open(conn, disposal.disposal_date)
        
        je_lines = []
        if disposal.disposal_price > 0:
            je_lines.append({
                "account_id": acc_cash, "debit": _dec(disposal.disposal_price), "credit": 0,
                "description": 'ثمن بيع أصل'
            })
            
        if acc_depr_recorded > 0:
            je_lines.append({
                "account_id": acc_acc_depr, "debit": _dec(acc_depr_recorded), "credit": 0,
                "description": 'استبعاد إهلاك متراكم'
            })
            
        je_lines.append({
            "account_id": acc_fixed_assets, "debit": 0, "credit": _dec(asset.cost),
            "description": 'استبعاد تكلفة أصل تاريخية'
        })
        
        if gain_loss > 0:
            je_lines.append({
                "account_id": acc_gain, "debit": 0, "credit": _dec(gain_loss),
                "description": 'أرباح بيع أصول'
            })
        elif gain_loss < 0:
            je_lines.append({
                "account_id": acc_loss, "debit": abs(_dec(gain_loss)), "credit": 0,
                "description": 'خسائر بيع أصول'
            })
            
        from services.gl_service import create_journal_entry as gl_create_journal_entry
        je_id, je_num = gl_create_journal_entry(
            db=conn,
            company_id=current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id,
            date=disposal.disposal_date,
            description=f"استبعاد الأصل {asset.name} ({asset.code})",
            lines=je_lines,
            user_id=current_user.get("id") if isinstance(current_user, dict) else current_user.id,
            branch_id=asset.branch_id,
            reference=f"ASSET-DISP-{asset_id}",
            currency=asset.currency or base_currency,
            exchange_rate=Decimal("1"),
            source="asset_disposal",
            source_id=asset_id
        )
                         
        trans.commit()
        return {"id": asset_id, "status": "disposed", "journal_entry": je_num}
    except HTTPException:
        trans.rollback()
        raise
    except Exception:
        trans.rollback()
        logger.exception("Operation failed")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════
# GL-003: Asset Transfer Between Branches
# ═══════════════════════════════════════════════════════════

class AssetTransfer(BaseModel):
    to_branch_id: int
    notes: Optional[str] = None

class AssetRevaluation(BaseModel):
    new_value: Decimal
    reason: Optional[str] = "إعادة تقييم"


def create_asset_return_write_down(
    conn, asset_id: int, *, user_id: int, company_id: str
) -> tuple[int, str] | None:
    """Create a write-down JE when an asset is returned with remaining NBV.

    If NBV > 0, posts a JE that writes the asset down to zero:
      DR  Loss on asset return (from settings)
      CR  Fixed asset account

    Returns (je_id, entry_number) if a JE was posted, None if NBV is zero.
    Links via journal_entries.source = 'asset', source_id = asset_id.
    """
    from services.gl_service import create_journal_entry

    asset = conn.execute(
        text("SELECT id, cost FROM assets WHERE id = :id"), {"id": asset_id}
    ).fetchone()
    if not asset:
        return None

    acc_depr = conn.execute(text("""
        SELECT COALESCE(SUM(amount), 0) FROM asset_depreciation_schedule
        WHERE asset_id = :id AND posted = TRUE
    """), {"id": asset_id}).scalar() or 0

    nbv = (_dec(asset.cost) - _dec(acc_depr)).quantize(_D2, ROUND_HALF_UP)
    if nbv <= 0:
        return None

    acc_fixed = get_mapped_account_id(conn, "acc_map_fixed_assets")
    acc_loss = get_mapped_account_id(conn, "acc_map_asset_loss")
    if not acc_fixed or not acc_loss:
        return None

    je_id, je_num = create_journal_entry(
        conn,
        company_id=company_id,
        date=str(date.today()),
        description=f"Asset return write-down #{asset_id} (NBV={nbv})",
        lines=[
            {"account_id": acc_loss, "debit": float(nbv), "credit": 0,
             "description": "Loss on asset return"},
            {"account_id": acc_fixed, "debit": 0, "credit": float(nbv),
             "description": "Asset return write-down"},
        ],
        user_id=user_id,
        source="asset",
        source_id=asset_id,
        idempotency_key=f"asset_return_write_down:{asset_id}",
    )
    return je_id, je_num

