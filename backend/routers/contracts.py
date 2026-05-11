from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error, i18n_message
from sqlalchemy import text
from typing import List, Optional
from datetime import date, timedelta
from decimal import Decimal
import logging

from database import get_db_connection
from routers.auth import get_current_user, UserResponse
from utils.tx import transactional
from schemas.contracts import ContractCreate, ContractUpdate, ContractAmendmentCreate, ContractResponse
from utils.permissions import branch_scope_filter, require_permission
from utils.accounting import get_base_currency, compute_line_amounts, compute_invoice_totals
from utils.audit import log_activity
from utils.tax_precision import money_str
from services.tax_engine import resolve_line_tax

logger = logging.getLogger(__name__)


def _float(v) -> float:
    """Convert any numeric to float safely for legacy DB inserts."""
    return float(Decimal(str(v if v is not None else 0)))

router = APIRouter(prefix="/contracts", tags=["Contracts"])

@router.post("", response_model=ContractResponse, dependencies=[Depends(require_permission("contracts.create"))])
def create_contract(
    contract: ContractCreate,
    request: Request,
    current_user: UserResponse = Depends(get_current_user)
):
    """Create Contract."""
    with transactional(current_user.company_id) as db:
        try:
            # Validate dates
            if contract.start_date and contract.end_date and contract.end_date < contract.start_date:
                raise HTTPException(**http_error(400, "contract_end_before_start"))
    
            # Validate contract number uniqueness
            if contract.contract_number:
                existing = db.execute(
                    text("SELECT id FROM contracts WHERE contract_number = :num"),
                    {"num": contract.contract_number}
                ).fetchone()
                if existing:
                    raise HTTPException(**http_error(400, "contract_number_duplicate"))
    
            # Recalculate total_amount from items to prevent client manipulation
            calculated_total = Decimal('0')
            for item in contract.items:
                la = compute_line_amounts(item.quantity, item.unit_price, item.tax_rate)
                calculated_total += la['line_total']
            
            # Use calculated total (override client-provided total)
            final_total = calculated_total
    
            # Create Contract Header
            contract_id = db.execute(
                text("""
                    INSERT INTO contracts (
                        contract_number, party_id, contract_type, status, 
                        start_date, end_date, billing_interval, total_amount, 
                        currency, notes, created_by, created_at
                    ) VALUES (
                        :num, :pid, :ctype, 'active', :start, :end, :interval, :total,
                        :cur, :notes, :uid, CURRENT_TIMESTAMP
                    ) RETURNING id
                """),
                {
                    "num": contract.contract_number,
                    "pid": contract.party_id,
                    "ctype": contract.contract_type,
                    "start": contract.start_date,
                    "end": contract.end_date,
                    "interval": contract.billing_interval,
                    "total": final_total,
                    "cur": contract.currency,
                    "notes": contract.notes,
                    "uid": current_user.id
                }
            ).scalar()
    
            # Create Contract Items
            for item in contract.items:
                la = compute_line_amounts(item.quantity, item.unit_price, item.tax_rate)
                db.execute(
                    text("""
                        INSERT INTO contract_items (
                            contract_id, product_id, description, quantity, 
                            unit_price, tax_rate, total
                        ) VALUES (
                            :cid, :pid, :desc, :qty, :price, :tax, :total
                        )
                    """),
                    {
                        "cid": contract_id,
                        "pid": item.product_id,
                        "desc": item.description,
                        "qty": item.quantity,
                        "price": item.unit_price,
                        "tax": item.tax_rate,
                        "total": la["line_total"]
                    }
                )
            
    
            # Audit log
            log_activity(
                db, user_id=current_user.id, username=current_user.username,
                action="contract.create", resource_type="contracts",
                resource_id=str(contract_id),
                details={"contract_number": contract.contract_number, "total": money_str(final_total)},
                request=request
            )
    
            # Notify about new contract
            try:
                party_name = db.execute(text("SELECT name FROM parties WHERE id = :id"), {"id": contract.party_id}).scalar()
                db.execute(text("""
                    INSERT INTO notifications (user_id, type, title, message, link, is_read, created_at)
                    SELECT DISTINCT u.id, 'contract', :title, :message, :link, FALSE, NOW()
                    FROM company_users u
                    WHERE u.is_active = TRUE AND u.role IN ('admin', 'superuser')
                    AND u.id != :current_uid
                """), {
                    "title": i18n_message("notif_new_contract", request),
                    "message": i18n_message("contract_created_details", request),
                    "link": f"/contracts/{contract_id}",
                    "current_uid": current_user.id
                })
                db.commit()
            except Exception:
                pass
    
            return get_contract(contract_id, current_user)
        except HTTPException:
            pass
            raise
        except Exception as e:
            pass
            logger.error(f"Error creating contract: {e}")
            raise HTTPException(**http_error(500, "internal_error"))

@router.get("", response_model=List[ContractResponse], dependencies=[Depends(require_permission("contracts.view"))])
def list_contracts(
    branch_id: Optional[int] = None,
    current_user: UserResponse = Depends(get_current_user)
):
    """List Contracts."""
    with transactional(current_user.company_id) as db:
        query = """
            SELECT c.*, p.name as party_name 
            FROM contracts c
            JOIN parties p ON c.party_id = p.id
        """
        params = {}
        conditions = []
        branch_clause = branch_scope_filter(current_user, branch_id, "c.branch_id", params)
        if branch_clause:
            conditions.append(branch_clause[4:].strip() if branch_clause.startswith("AND ") else branch_clause.strip())
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY c.created_at DESC"
        contracts = db.execute(text(query), params).fetchall()
        
        if not contracts:
            return []

        # Batched item query — eliminates N+1 (T027)
        contract_ids = [c.id for c in contracts]
        all_items = db.execute(
            text("SELECT * FROM contract_items WHERE contract_id = ANY(:ids)"),
            {"ids": contract_ids}
        ).fetchall()

        # Group items by contract_id
        from collections import defaultdict
        items_by_contract = defaultdict(list)
        for item in all_items:
            items_by_contract[item.contract_id].append(dict(item._mapping))

        result = []
        for c in contracts:
            result.append({
                **c._mapping,
                "items": items_by_contract.get(c.id, [])
            })
        return result

@router.get("/alerts/expiring", dependencies=[Depends(require_permission("contracts.view"))])
def get_expiring_contracts(
    days: int = 30,
    current_user: UserResponse = Depends(get_current_user)
):
    """جلب العقود التي ستنتهي خلال فترة محددة (افتراضي 30 يوم)"""
    with transactional(current_user.company_id) as db:
        try:
            today = date.today()
            future_date = today + timedelta(days=days)
            
            contracts = db.execute(text("""
                SELECT c.*, p.name as party_name,
                       (c.end_date - CURRENT_DATE) as days_remaining
                FROM contracts c
                JOIN parties p ON c.party_id = p.id
                WHERE c.status = 'active' 
                  AND c.end_date IS NOT NULL
                  AND c.end_date BETWEEN :today AND :future
                ORDER BY c.end_date ASC
            """), {"today": today, "future": future_date}).fetchall()
            
            result = []
            for c in contracts:
                result.append({
                    "id": c.id,
                    "contract_number": c.contract_number,
                    "party_name": c.party_name,
                    "contract_type": c.contract_type,
                    "end_date": str(c.end_date),
                    "days_remaining": c.days_remaining,
                    "total_amount": float(c.total_amount or 0),
                    "billing_interval": c.billing_interval,
                    "currency": c.currency
                })
            
            return {
                "count": len(result),
                "contracts": result,
                "period_days": days
            }
        except Exception as e:
            logger.error(f"Error fetching expiring contracts: {e}")
            raise HTTPException(**http_error(500, "internal_error"))


@router.get("/stats/summary", dependencies=[Depends(require_permission("contracts.view"))])
def get_contracts_summary(
    current_user: UserResponse = Depends(get_current_user)
):
    """ملخص إحصائيات العقود"""
    with transactional(current_user.company_id) as db:
        try:
            stats = db.execute(text("""
                SELECT 
                    COUNT(*) as total_contracts,
                    COUNT(*) FILTER (WHERE status = 'active') as active_count,
                    COUNT(*) FILTER (WHERE status = 'expired') as expired_count,
                    COUNT(*) FILTER (WHERE status = 'cancelled') as cancelled_count,
                    COALESCE(SUM(total_amount) FILTER (WHERE status = 'active'), 0) as active_value,
                    COALESCE(SUM(total_amount), 0) as total_value,
                    COUNT(*) FILTER (WHERE status = 'active' AND end_date IS NOT NULL AND end_date <= CURRENT_DATE + INTERVAL '30 days') as expiring_soon
                FROM contracts
            """)).fetchone()
            
            return {
                "total_contracts": stats.total_contracts,
                "active_count": stats.active_count,
                "expired_count": stats.expired_count,
                "cancelled_count": stats.cancelled_count,
                "active_value": float(stats.active_value),
                "total_value": float(stats.total_value),
                "expiring_soon": stats.expiring_soon
            }
        except Exception as e:
            logger.error(f"Error fetching contract stats: {e}")
            raise HTTPException(**http_error(500, "internal_error"))


@router.get("/{contract_id}", response_model=ContractResponse, dependencies=[Depends(require_permission("contracts.view"))])
def get_contract(
    contract_id: int, 
    current_user: UserResponse = Depends(get_current_user)
):
    """Get Contract."""
    with transactional(current_user.company_id) as db:
        contract = db.execute(
            text("""
                SELECT c.*, p.name as party_name 
                FROM contracts c
                JOIN parties p ON c.party_id = p.id
                WHERE c.id = :id
            """),
            {"id": contract_id}
        ).fetchone()
        
        if not contract:
            raise HTTPException(**http_error(404, "contract_not_found"))
            
        items = db.execute(
            text("SELECT * FROM contract_items WHERE contract_id = :id"),
            {"id": contract_id}
        ).fetchall()
        
        return {
            **contract._mapping,
            "items": [dict(row._mapping) for row in items]
        }


@router.put("/{contract_id}", response_model=ContractResponse, dependencies=[Depends(require_permission("contracts.edit"))])
def update_contract(
    contract_id: int,
    data: ContractUpdate,
    request: Request,
    current_user: UserResponse = Depends(get_current_user)
):
    """Update Contract."""
    db = get_db_connection(current_user.company_id)
    trans = db.begin()
    try:
        existing = db.execute(text("SELECT * FROM contracts WHERE id = :id"), {"id": contract_id}).fetchone()
        if not existing:
            raise HTTPException(**http_error(404, "contract_not_found"))

        # Build dynamic SET clause from non-None fields (partial update)
        updatable_fields = {
            "party_id": data.party_id, "contract_type": data.contract_type,
            "start_date": data.start_date, "end_date": data.end_date,
            "billing_interval": data.billing_interval,
            "currency": data.currency, "notes": data.notes
        }
        set_parts = []
        params = {"id": contract_id}
        for field, value in updatable_fields.items():
            if value is not None:
                set_parts.append(f"{field} = :{field}")
                params[field] = value

        # If items provided, replace them and recalculate total (T026 + T028)
        if data.items is not None:
            db.execute(text("DELETE FROM contract_items WHERE contract_id = :id"), {"id": contract_id})
            calculated_total = Decimal('0')
            for item in data.items:
                la = compute_line_amounts(item.quantity, item.unit_price, item.tax_rate)
                calculated_total += la['line_total']
                db.execute(text("""
                    INSERT INTO contract_items (contract_id, product_id, description, quantity, unit_price, tax_rate, total)
                    VALUES (:cid, :pid, :desc, :qty, :price, :tax, :total)
                """), {
                    "cid": contract_id, "pid": item.product_id, "desc": item.description,
                    "qty": item.quantity, "price": item.unit_price, "tax": item.tax_rate, "total": la["line_total"]
                })
            set_parts.append("total_amount = :total_amount")
            params["total_amount"] = calculated_total

        if set_parts:
            set_parts.append("updated_at = CURRENT_TIMESTAMP")
            query = f"UPDATE contracts SET {', '.join(set_parts)} WHERE id = :id"
            db.execute(text(query), params)

        trans.commit()

        # Audit log
        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="contract.update", resource_type="contracts",
            resource_id=str(contract_id),
            details={"action": "update_contract"}, request=request
        )

        return get_contract(contract_id, current_user)
    except HTTPException:
        trans.rollback()
        raise
    except Exception as e:
        trans.rollback()
        logger.error(f"Error updating contract: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.post("/{contract_id}/renew", response_model=ContractResponse, dependencies=[Depends(require_permission("contracts.manage"))])
def renew_contract(
    contract_id: int,
    request: Request,
    current_user: UserResponse = Depends(get_current_user)
):
    """تجديد العقد - ينشئ فترة جديدة بناءً على فترة الفوترة"""
    with transactional(current_user.company_id) as db:
        try:
            contract = db.execute(
                text("SELECT * FROM contracts WHERE id = :id"),
                {"id": contract_id}
            ).fetchone()
            
            if not contract:
                raise HTTPException(**http_error(404, "contract_not_found"))
            
            if contract.status != 'active':
                raise HTTPException(**http_error(400, "only_active_contracts_renew"))
            
            from datetime import timedelta
            from dateutil.relativedelta import relativedelta
            
            old_end = contract.end_date
            interval = contract.billing_interval or 'monthly'
            
            # Calculate new dates based on billing interval
            if interval == 'monthly':
                delta = relativedelta(months=1)
            elif interval == 'quarterly':
                delta = relativedelta(months=3)
            elif interval == 'semi_annual':
                delta = relativedelta(months=6)
            elif interval == 'annual':
                delta = relativedelta(years=1)
            else:
                delta = relativedelta(months=1)
            
            new_start = old_end + timedelta(days=1)
            new_end = new_start + delta - timedelta(days=1)
            
            # Update contract dates
            db.execute(
                text("""
                    UPDATE contracts 
                    SET start_date = :start, end_date = :end, 
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                """),
                {"start": new_start, "end": new_end, "id": contract_id}
            )
            
    
            # Audit log
            log_activity(
                db, user_id=current_user.id, username=current_user.username,
                action="contract.renew", resource_type="contracts",
                resource_id=str(contract_id),
                details={"new_start": str(new_start), "new_end": str(new_end)},
                request=request
            )
    
            return get_contract(contract_id, current_user)
        except HTTPException:
            raise
        except Exception as e:
            pass
            logger.error(f"Error renewing contract: {e}")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/{contract_id}/generate-invoice", dependencies=[Depends(require_permission("contracts.manage"))])
def generate_contract_invoice(
    contract_id: int,
    request: Request,
    current_user: UserResponse = Depends(get_current_user)
):
    """إنشاء فاتورة من العقد"""
    with transactional(current_user.company_id) as db:
        try:
            contract = db.execute(
                text("SELECT * FROM contracts WHERE id = :id AND status = 'active'"),
                {"id": contract_id}
            ).fetchone()
            
            if not contract:
                raise HTTPException(**http_error(404, "contract_inactive_or_not_found"))
            
            items = db.execute(
                text("SELECT * FROM contract_items WHERE contract_id = :id"),
                {"id": contract_id}
            ).fetchall()
            
            if not items:
                raise HTTPException(**http_error(400, "contract_items_empty"))
            
            from datetime import date as dt_date
            from utils.accounting import generate_sequential_number
            
            inv_num = generate_sequential_number(db, f"INV-CTR-{dt_date.today().year}", "invoices", "invoice_number")
    
            # Get user's default branch for tax resolution
            user_branch = db.execute(text(
                "SELECT branch_id FROM user_branches WHERE user_id = :uid ORDER BY branch_id LIMIT 1"
            ), {"uid": current_user.id}).fetchone()
            _branch_id = user_branch.branch_id if user_branch else None

            # Centralized Decimal calculation (Constitution: no inline float math)
            line_dicts = []
            resolved_items = []
            for i in items:
                tax_info = resolve_line_tax(_branch_id, i.product_id, db, dt_date.today(), customer_id=contract.party_id) if _branch_id else {"tax_rate": Decimal(str(i.tax_rate or 0)), "tax_rate_id": None}
                line_dicts.append({"quantity": i.quantity, "unit_price": i.unit_price, "tax_rate": tax_info["tax_rate"]})
                resolved_items.append({"item": i, "tax_info": tax_info})
            totals = compute_invoice_totals(line_dicts)
            subtotal = totals["subtotal"]
            tax_total = totals["total_tax"]
            total = totals["grand_total"]
            
            inv_id = db.execute(text("""
                INSERT INTO invoices (
                    invoice_number, invoice_type, party_id, invoice_date, due_date,
                    subtotal, tax_amount, total, paid_amount, status, notes,
                    created_by, currency, exchange_rate
                ) VALUES (
                    :num, :type, :pid, CURRENT_DATE, CURRENT_DATE + 30,
                    :sub, :tax, :total, 0, 'unpaid', :notes,
                    :uid, :curr, 1.0
                ) RETURNING id
            """), {
                "num": inv_num,
                "type": 'sales' if contract.contract_type == 'sales' else 'purchase',
                "pid": contract.party_id,
                "sub": subtotal, "tax": tax_total, "total": total,
                "notes": f"فاتورة عقد #{contract.contract_number}",
                "uid": current_user.id,
                "curr": contract.currency or get_base_currency(db)
            }).scalar()
            
            for ri in resolved_items:
                item = ri["item"]
                tax_info = ri["tax_info"]
                la = compute_line_amounts(item.quantity, item.unit_price, tax_info["tax_rate"])
                db.execute(text("""
                    INSERT INTO invoice_lines (invoice_id, product_id, description, quantity, unit_price, tax_rate, tax_rate_id, total)
                    VALUES (:iid, :pid, :desc, :qty, :price, :tax, :tax_id, :total)
                """), {
                    "iid": inv_id, "pid": item.product_id, "desc": item.description,
                    "qty": item.quantity, "price": item.unit_price,
                    "tax": tax_info["tax_rate"], "tax_id": tax_info.get("tax_rate_id"),
                    "total": la["line_total"]
                })
            
    
            # Audit log
            log_activity(
                db, user_id=current_user.id, username=current_user.username,
                action="contract.generate_invoice", resource_type="contracts",
                resource_id=str(contract_id),
                details={"invoice_id": inv_id, "invoice_number": inv_num, "total": money_str(total)},
                request=request
            )
    
            return {"success": True, "invoice_id": inv_id, "invoice_number": inv_num, "total": money_str(total)}
        except HTTPException:
            raise
        except Exception as e:
            pass
            logger.error(f"Error generating contract invoice: {e}")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/{contract_id}/cancel", dependencies=[Depends(require_permission("contracts.manage"))])
def cancel_contract(
    contract_id: int,
    request: Request,
    current_user: UserResponse = Depends(get_current_user)
):
    """إلغاء عقد نشط"""
    with transactional(current_user.company_id) as db:
        try:
            contract = db.execute(
                text("SELECT * FROM contracts WHERE id = :id"),
                {"id": contract_id}
            ).fetchone()
            
            if not contract:
                raise HTTPException(**http_error(404, "contract_not_found"))
            
            if contract.status == 'cancelled':
                raise HTTPException(**http_error(400, "contract_already_cancelled"))
            
            db.execute(
                text("UPDATE contracts SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE id = :id"),
                {"id": contract_id}
            )
    
            # Audit log
            log_activity(
                db, user_id=current_user.id, username=current_user.username,
                action="contract.cancel", resource_type="contracts",
                resource_id=str(contract_id),
                details={"contract_number": contract.contract_number},
                request=request
            )
    
            return {"message": i18n_message("contract_cancelled_success"), "id": contract_id}
        except HTTPException:
            raise
        except Exception as e:
            pass
            logger.error(f"Error cancelling contract {contract_id}: {e}")
            raise HTTPException(**http_error(500, "internal_error"))


# ===================== C2: Contract Amendments =====================

@router.get("/{contract_id}/amendments", dependencies=[Depends(require_permission("contracts.view"))])
def list_amendments(contract_id: int, current_user=Depends(get_current_user)):
    """سجل تعديلات العقد"""
    with transactional(current_user.company_id) as db:
        rows = db.execute(text("""
            SELECT ca.*, u.full_name as approved_by_name
            FROM contract_amendments ca
            LEFT JOIN users u ON u.id = ca.approved_by
            WHERE ca.contract_id = :cid
            ORDER BY ca.created_at DESC
        """), {"cid": contract_id}).fetchall()
        return [dict(r._mapping) for r in rows]


@router.post("/{contract_id}/amendments", dependencies=[Depends(require_permission("contracts.edit"))])
def create_amendment(contract_id: int, amendment: ContractAmendmentCreate, request: Request, current_user=Depends(get_current_user)):
    """إنشاء تعديل عقد"""
    with transactional(current_user.company_id) as db:
        try:
            result = db.execute(text("""
                INSERT INTO contract_amendments (contract_id, amendment_type, old_value,
                    new_value, description, effective_date, approved_by)
                VALUES (:cid, :at, :ov, :nv, :desc, :ed, :ab)
                RETURNING id
            """), {
                "cid": contract_id, "at": amendment.amendment_type,
                "ov": amendment.old_value, "nv": amendment.new_value,
                "desc": amendment.description, "ed": amendment.effective_date,
                "ab": current_user.id
            })
            aid = result.fetchone()[0]
            log_activity(
                db, user_id=current_user.id, username=current_user.username,
                action="contract.amendment_create", resource_type="contract_amendment",
                resource_id=str(aid),
                details={"contract_id": contract_id, "type": amendment.amendment_type},
                request=request
            )
            return {"id": aid, "message": i18n_message("amendment_created_success")}
        except Exception as e:
            pass
            logger.error(f"Error creating amendment: {e}")
            raise HTTPException(**http_error(500, "internal_error"))


@router.get("/{contract_id}/kpis", dependencies=[Depends(require_permission("contracts.view"))])
def get_contract_kpis(contract_id: int, current_user=Depends(get_current_user)):
    """مؤشرات أداء العقد"""
    with transactional(current_user.company_id) as db:
        try:
            contract = db.execute(text("SELECT * FROM contracts WHERE id = :id"),
                                  {"id": contract_id}).fetchone()
            if not contract:
                raise HTTPException(**http_error(404, "contract_not_found"))
            c = dict(contract._mapping)
    
            # Amendment count
            amendments = db.execute(text(
                "SELECT COUNT(*) FROM contract_amendments WHERE contract_id = :cid"
            ), {"cid": contract_id}).scalar() or 0
    
            # Related invoices
            invoices = db.execute(text("""
                SELECT COUNT(*) as count, COALESCE(SUM(total), 0) as total,
                       COALESCE(SUM(total - COALESCE(paid_amount, 0)), 0) as outstanding
                FROM invoices WHERE contract_id = :cid
            """), {"cid": contract_id}).fetchone()
            inv = dict(invoices._mapping) if invoices else {}
    
            # Days remaining
            from datetime import date
            end_date = c.get("end_date")
            days_remaining = (end_date - date.today()).days if end_date else None
    
            total_value = float(c.get("total_amount") or c.get("value") or 0)
            invoiced = float(inv.get("total", 0))
            utilization = round(invoiced / total_value * 100, 2) if total_value > 0 else 0
    
            return {
                "contract_id": contract_id,
                "total_value": total_value,
                "invoiced_amount": invoiced,
                "outstanding_amount": float(inv.get("outstanding", 0)),
                "utilization_pct": utilization,
                "days_remaining": days_remaining,
                "invoice_count": int(inv.get("count", 0)),
                "amendment_count": amendments,
                "status": c.get("status")
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error fetching contract KPIs: {e}")
            raise HTTPException(**http_error(500, "internal_error"))


# ==========================================================================
# CON-F1: Contract Milestones (Phase-11 Sprint-4)
# ==========================================================================

@router.get(
    "/{contract_id}/milestones",
    dependencies=[Depends(require_permission("contracts.view"))],
)
def list_contract_milestones(contract_id: int, current_user=Depends(get_current_user)):
    """List milestones for a contract."""
    with transactional(current_user.company_id) as db:
        try:
            contract = db.execute(
                text("SELECT id FROM contracts WHERE id = :id"),
                {"id": contract_id},
            ).fetchone()
            if not contract:
                raise HTTPException(**http_error(404, "contract_not_found"))
    
            rows = db.execute(
                text(
                    """
                    SELECT id, contract_id, sequence, name, description, due_date,
                           amount, status, completed_at, billed_at, invoice_id,
                           notes, created_at, updated_at
                    FROM contract_milestones
                    WHERE contract_id = :cid
                    ORDER BY sequence, id
                    """
                ),
                {"cid": contract_id},
            ).fetchall()
            return [dict(r._mapping) for r in rows]
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error listing milestones: {e}")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post(
    "/{contract_id}/milestones",
    dependencies=[Depends(require_permission("contracts.edit"))],
)
def create_contract_milestone(
    contract_id: int,
    payload: dict,
    current_user=Depends(get_current_user),
):
    """Create a milestone for a contract."""
    with transactional(current_user.company_id) as db:
        try:
            contract = db.execute(
                text("SELECT id, status FROM contracts WHERE id = :id"),
                {"id": contract_id},
            ).fetchone()
            if not contract:
                raise HTTPException(**http_error(404, "contract_not_found"))
    
            name = (payload.get("name") or "").strip()
            if not name:
                raise HTTPException(**http_error(400, "milestone_name_required"))
            amount = _float(payload.get("amount") or 0)
            if amount < 0:
                raise HTTPException(**http_error(400, "milestone_amount_invalid"))
    
            row = db.execute(
                text(
                    """
                    INSERT INTO contract_milestones
                        (contract_id, sequence, name, description, due_date,
                         amount, status, notes, created_by)
                    VALUES
                        (:cid, :seq, :name, :desc, :due, :amt, 'pending',
                         :notes, :uid)
                    RETURNING id
                    """
                ),
                {
                    "cid": contract_id,
                    "seq": int(payload.get("sequence") or 1),
                    "name": name,
                    "desc": payload.get("description"),
                    "due": payload.get("due_date"),
                    "amt": amount,
                    "notes": payload.get("notes"),
                    "uid": current_user.id,
                },
            ).fetchone()
            return {"id": row.id, "status": "pending"}
        except HTTPException:
            pass
            raise
        except Exception as e:
            pass
            logger.error(f"Error creating milestone: {e}")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post(
    "/{contract_id}/milestones/{milestone_id}/complete",
    dependencies=[Depends(require_permission("contracts.edit"))],
)
def complete_contract_milestone(
    contract_id: int,
    milestone_id: int,
    current_user=Depends(get_current_user),
):
    """Mark a milestone as completed (ready to bill)."""
    with transactional(current_user.company_id) as db:
        try:
            ms = db.execute(
                text(
                    "SELECT id, status FROM contract_milestones "
                    "WHERE id = :mid AND contract_id = :cid"
                ),
                {"mid": milestone_id, "cid": contract_id},
            ).fetchone()
            if not ms:
                raise HTTPException(**http_error(404, "milestone_not_found"))
            if ms.status not in ("pending",):
                raise HTTPException(**http_error(400, "milestone_not_pending"))
            db.execute(
                text(
                    "UPDATE contract_milestones "
                    "SET status = 'completed', completed_at = CURRENT_TIMESTAMP, "
                    "    updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = :mid"
                ),
                {"mid": milestone_id},
            )
            return {"id": milestone_id, "status": "completed"}
        except HTTPException:
            pass
            raise
        except Exception as e:
            pass
            logger.error(f"Error completing milestone: {e}")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post(
    "/{contract_id}/milestones/{milestone_id}/bill",
    dependencies=[Depends(require_permission("contracts.manage"))],
)
def bill_contract_milestone(
    contract_id: int,
    milestone_id: int,
    current_user=Depends(get_current_user),
):
    """Generate an invoice for a completed milestone.

    Minimal implementation: creates a draft AR invoice for the milestone
    amount linked back via ``contract_milestones.invoice_id`` and flips the
    milestone to ``billed``. Accounting posting follows the standard invoice
    flow (invoice remains ``draft`` until posted through the regular
    approval path).
    """
    with transactional(current_user.company_id) as db:
        try:
            contract = db.execute(
                text(
                    "SELECT id, party_id, currency FROM contracts "
                    "WHERE id = :id"
                ),
                {"id": contract_id},
            ).fetchone()
            if not contract:
                raise HTTPException(**http_error(404, "contract_not_found"))
    
            ms = db.execute(
                text(
                    "SELECT id, name, amount, status FROM contract_milestones "
                    "WHERE id = :mid AND contract_id = :cid FOR UPDATE"
                ),
                {"mid": milestone_id, "cid": contract_id},
            ).fetchone()
            if not ms:
                raise HTTPException(**http_error(404, "milestone_not_found"))
            if ms.status != "completed":
                raise HTTPException(**http_error(400, "milestone_not_completed"))
    
            # Create minimal draft invoice
            inv = db.execute(
                text(
                    """
                    INSERT INTO invoices
                        (invoice_type, party_id, contract_id, invoice_date,
                         currency, subtotal, total, status, notes, created_by)
                    VALUES
                        ('sale', :pid, :cid, CURRENT_DATE, :cur,
                         :amt, :amt, 'draft', :notes, :uid)
                    RETURNING id
                    """
                ),
                {
                    "pid": contract.party_id,
                    "cid": contract_id,
                    "cur": contract.currency or "SAR",
                    "amt": _float(ms.amount or 0),
                    "notes": f"Milestone: {ms.name}",
                    "uid": current_user.id,
                },
            ).fetchone()
    
            db.execute(
                text(
                    "UPDATE contract_milestones "
                    "SET status = 'billed', billed_at = CURRENT_TIMESTAMP, "
                    "    invoice_id = :iid, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = :mid"
                ),
                {"iid": inv.id, "mid": milestone_id},
            )
            return {
                "id": milestone_id,
                "status": "billed",
                "invoice_id": inv.id,
            }
        except HTTPException:
            pass
            raise
        except Exception as e:
            pass
            logger.error(f"Error billing milestone: {e}")
            raise HTTPException(**http_error(500, "internal_error"))
