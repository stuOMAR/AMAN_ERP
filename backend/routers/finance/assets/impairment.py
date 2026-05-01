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

from .core import _D2, _D4, _dec

@router.get("/{asset_id}/impairments", dependencies=[Depends(require_permission("assets.view"))], response_model=List[Dict[str, Any]])
def list_asset_impairments(asset_id: int, current_user: dict = Depends(get_current_user)):
    """سجل اختبارات الانخفاض"""
    with transactional(current_user.company_id) as conn:
        rows = conn.execute(text("""
            SELECT * FROM asset_impairments WHERE asset_id = :aid ORDER BY test_date DESC
        """), {"aid": asset_id}).fetchall()
        return [dict(r._mapping) for r in rows]


@router.post("/{asset_id}/impairment-test", dependencies=[Depends(require_permission("assets.create"))], response_model=Dict[str, Any])
def run_impairment_test(asset_id: int, test_data: ImpairmentTestInput, current_user: dict = Depends(get_current_user)):
    """إجراء اختبار انخفاض القيمة IAS 36 مع قيد محاسبي تلقائي"""
    with transactional(current_user.company_id) as conn:
        try:
            asset = conn.execute(text("SELECT * FROM assets WHERE id = :id"), {"id": asset_id}).fetchone()
            if not asset:
                raise HTTPException(404, "Asset not found")
            asset = dict(asset._mapping)
    
            carrying = _dec(asset.get("current_value") or asset.get("cost", 0)).quantize(_D2, ROUND_HALF_UP)
            recoverable = _dec(test_data.recoverable_amount).quantize(_D2, ROUND_HALF_UP)
            impairment_loss = max(carrying - recoverable, Decimal('0')).quantize(_D2, ROUND_HALF_UP)
    
            result = conn.execute(text("""
                INSERT INTO asset_impairments (asset_id, test_date, carrying_amount,
                    recoverable_amount, impairment_loss, reason)
                VALUES (:aid, :td, :ca, :ra, :il, :r)
                RETURNING id
            """), {
                "aid": asset_id, "td": (test_data.test_date or date.today()).isoformat(),
                "ca": carrying, "ra": recoverable, "il": impairment_loss,
                "r": test_data.reason or test_data.notes
            })
            imp_id = result.fetchone()[0]
    
            journal_entry_id = None
            if impairment_loss > 0:
                new_value = recoverable
                conn.execute(text("UPDATE assets SET current_value = :v WHERE id = :id"),
                             {"v": new_value, "id": asset_id})
    
                # Create journal entry: Dr. Impairment Loss (6800) / Cr. Accumulated Impairment (1699)
                imp_loss_acc = conn.execute(text(
                    "SELECT id FROM accounts WHERE account_code IN ('6800','6810','5800') AND is_active = TRUE ORDER BY account_code LIMIT 1"
                )).fetchone()
                acc_imp_acc = conn.execute(text(
                    "SELECT id FROM accounts WHERE account_code IN ('1699','1690','1680') AND is_active = TRUE ORDER BY account_code LIMIT 1"
                )).fetchone()
    
                if imp_loss_acc and acc_imp_acc:
                    check_fiscal_period_open(conn, date.today())
                    
                    je_lines = [
                        {
                            "account_id": imp_loss_acc.id, "debit": impairment_loss, "credit": 0,
                            "description": f"خسارة انخفاض قيمة - {asset.get('name', '')}"
                        },
                        {
                            "account_id": acc_imp_acc.id, "debit": 0, "credit": impairment_loss,
                            "description": f"مجمع انخفاض قيمة - {asset.get('name', '')}"
                        }
                    ]
                    
                    from services.gl_service import create_journal_entry as gl_create_journal_entry
                    from utils.accounting import get_base_currency
                    
                    je_id, entry_number = gl_create_journal_entry(
                        db=conn,
                        company_id=current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id,
                        date=date.today(),
                        description=f"خسارة انخفاض قيمة الأصل: {asset.get('name', '')} (IAS 36)",
                        lines=je_lines,
                        user_id=current_user.get("id") if isinstance(current_user, dict) else current_user.id,
                        currency=get_base_currency(conn),
                        exchange_rate=Decimal("1"),
                        source="asset_impairment",
                        source_id=imp_id
                    )
                    journal_entry_id = je_id
    
            return {
                "id": imp_id,
                "carrying_amount": carrying,
                "recoverable_amount": recoverable,
                "impairment_loss": impairment_loss,
                "impaired": impairment_loss > 0,
                "journal_entry_id": journal_entry_id,
                "message": "تم إجراء اختبار الانخفاض" + (" - تم تسجيل خسارة انخفاض وقيد محاسبي" if impairment_loss > 0 else " - لا يوجد انخفاض")
            }
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
