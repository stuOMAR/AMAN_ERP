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
from utils.permissions import require_permission, validate_branch_access, require_module
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

from .core import AssetTransfer, _D2, _D4, _dec

@router.get("/transfers", dependencies=[Depends(require_permission("assets.view"))], response_model=List[Dict[str, Any]])
def list_asset_transfers(status: Optional[str] = None, branch_id: Optional[int] = None, current_user: dict = Depends(get_current_user)):
    """List Asset Transfers."""
    with transactional(current_user.company_id) as conn:
        q = "SELECT * FROM asset_transfers WHERE 1=1"
        params = {}
        if status:
            q += " AND status = :status"
            params["status"] = status
        if branch_id:
            q += " AND (from_branch_id = :branch_id OR to_branch_id = :branch_id)"
            params["branch_id"] = branch_id
        q += " ORDER BY created_at DESC"
        rows = conn.execute(text(q), params).fetchall()
        return [dict(r._mapping) for r in rows]


@router.post("/transfers", dependencies=[Depends(require_permission("assets.create"))], response_model=Dict[str, Any])
def create_asset_transfer(data: AssetTransferCreate, current_user: dict = Depends(get_current_user)):
    """Create Asset Transfer."""
    with transactional(current_user.company_id) as conn:
        try:
            asset = conn.execute(text("SELECT * FROM assets WHERE id = :id"), {"id": data.asset_id}).fetchone()
            if not asset:
                raise HTTPException(**http_error(404, "asset_not_found", request))
            dep_sum = conn.execute(text(
                "SELECT COALESCE(SUM(amount),0) FROM asset_depreciation_schedule WHERE asset_id = :id AND posted = true"
            ), {"id": data.asset_id}).scalar()
            book_value = (_dec(asset.cost) - _dec(dep_sum or 0)).quantize(_D2, ROUND_HALF_UP)
    
            result = conn.execute(text("""
                INSERT INTO asset_transfers (asset_id, from_branch_id, to_branch_id, transfer_date,
                    reason, book_value_at_transfer, status, created_by)
                VALUES (:aid, :from, :to, :date, :reason, :bv, 'pending', :uid)
                RETURNING *
            """), {
                "aid": data.asset_id, "from": asset.branch_id,
                "to": data.to_branch_id, "date": (data.transfer_date or date.today()).isoformat(),
                "reason": data.reason, "bv": book_value, "uid": current_user.id,
            }).fetchone()
            return dict(result._mapping)
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.put("/transfers/{transfer_id}/approve", dependencies=[Depends(require_permission("assets.create"))], response_model=Dict[str, Any])
def approve_transfer(transfer_id: int, current_user: dict = Depends(get_current_user)):
    """Approve Transfer."""
    with transactional(current_user.company_id) as conn:
        try:
            t = conn.execute(text("SELECT * FROM asset_transfers WHERE id = :id"), {"id": transfer_id}).fetchone()
            if not t or t.status != 'pending':
                raise HTTPException(**http_error(404, "pending_transfer_not_found", request))
            conn.execute(text("UPDATE asset_transfers SET status = 'approved', approved_by = :uid WHERE id = :id"),
                         {"uid": current_user.id, "id": transfer_id})
            conn.execute(text("UPDATE assets SET branch_id = :bid WHERE id = :aid"),
                         {"bid": t.to_branch_id, "aid": t.asset_id})
            return {"message": i18n_message(("asset_transfer_approved", request))}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ---------- ASSET-003: Asset Revaluations (STATIC - must be before /{asset_id}) ----------

@router.post("/{asset_id}/transfer", dependencies=[Depends(require_permission("assets.manage"))], response_model=Dict[str, Any])
def transfer_asset(asset_id: int, transfer: AssetTransfer, current_user: dict = Depends(get_current_user)):
    """نقل أصل بين فروع مع قيد محاسبي تلقائي عبر الحساب البيني"""
    conn = get_db_connection(current_user.company_id)
    trans = conn.begin()
    try:
        from utils.accounting import get_base_currency

        asset = conn.execute(text("SELECT * FROM assets WHERE id = :id FOR UPDATE"), {"id": asset_id}).fetchone()
        if not asset:
            raise HTTPException(**http_error(404, "asset_not_found"))
        if asset.status == 'disposed':
            raise HTTPException(**http_error(400, "asset_cannot_transfer_disposed", request))

        from_branch_id = asset.branch_id
        if from_branch_id == transfer.to_branch_id:
            raise HTTPException(**http_error(400, "asset_source_dest_branch_same", request))

        base_currency = get_base_currency(conn)
        acc_fixed = get_mapped_account_id(conn, "acc_map_fixed_assets")
        acc_inter = get_mapped_account_id(conn, "acc_map_intercompany")
        if not acc_inter:
            raise HTTPException(**http_error(400, "intercompany_account_not_configured", request))

        cost = _dec(asset.cost).quantize(_D2, ROUND_HALF_UP)

        check_fiscal_period_open(conn, date.today())
        # Create 2 JEs — one for sending branch, one for receiving
        for je_type, branch_id, lines in [
            ("SEND", from_branch_id, [
                (acc_inter, cost, 0, f"نقل أصل #{asset_id} إلى فرع {transfer.to_branch_id}"),
                (acc_fixed, 0, cost, f"إخراج أصل #{asset_id}")
            ]),
            ("RECV", transfer.to_branch_id, [
                (acc_fixed, cost, 0, f"استقبال أصل #{asset_id}"),
                (acc_inter, 0, cost, f"نقل أصل #{asset_id} من فرع {from_branch_id}")
            ]),
        ]:
            je_lines_formatted = [
                {
                    "account_id": row[0],
                    "debit": _dec(row[1]).quantize(_D2, ROUND_HALF_UP),
                    "credit": _dec(row[2]).quantize(_D2, ROUND_HALF_UP),
                    "description": row[3]
                }
                for row in lines
            ]
            
            from services.gl_service import create_journal_entry as gl_create_journal_entry
            from utils.accounting import get_base_currency
            
            base_currency = get_base_currency(conn)
            
            je_id, je_num = gl_create_journal_entry(
                db=conn,
                company_id=current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id,
                date=date.today(),
                description=f"نقل أصل #{asset_id} — {je_type}",
                lines=je_lines_formatted,
                user_id=current_user.get("id") if isinstance(current_user, dict) else current_user.id,
                branch_id=branch_id,
                reference=f"ASSET-XFER-{asset_id}-{je_type}",
                currency=base_currency,
                exchange_rate=Decimal("1"),
                source="asset_transfer",
                source_id=asset_id
            )

        # Update asset branch
        conn.execute(text("UPDATE assets SET branch_id = :br, updated_at = NOW() WHERE id = :id"),
                     {"br": transfer.to_branch_id, "id": asset_id})
        trans.commit()
        return {"success": True, "asset_id": asset_id, "from_branch": from_branch_id, "to_branch": transfer.to_branch_id}
    except HTTPException:
        trans.rollback()
        raise
    except Exception:
        trans.rollback()
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════
# GL-007: Asset Revaluation
# ═══════════════════════════════════════════════════════════

