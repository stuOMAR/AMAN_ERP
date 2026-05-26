from fastapi import APIRouter, Depends, HTTPException, Request, Header
from utils.i18n import http_error, i18n_message
from sqlalchemy import text
from typing import List, Optional
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import logging

from database import get_db_connection
from routers.auth import get_current_user, UserResponse
from utils.tx import transactional
from schemas.contracts import (
    ContractBillingCyclePreviewRequest,
    ContractCreate,
    ContractInvoiceGenerateRequest,
    ContractUpdate,
    ContractAmendmentCreate,
    ContractResponse,
)
from utils.permissions import branch_scope_filter, require_permission, validate_branch_access
from utils.accounting import get_base_currency, compute_line_amounts, compute_invoice_totals
from utils.audit import log_activity
from utils.tax_precision import money_str, rate_str, require_idempotency_key
from services.tax_engine import resolve_line_tax_group

logger = logging.getLogger(__name__)


_D2 = Decimal("0.01")
_D4 = Decimal("0.0001")


def _dec(v) -> Decimal:
    return Decimal(str(v if v is not None else 0))

router = APIRouter(prefix="/contracts", tags=["Contracts"])


def _default_branch_id(db) -> Optional[int]:
    return db.execute(text("""
        SELECT id
        FROM branches
        WHERE is_default = TRUE
          AND is_active = TRUE
        LIMIT 1
    """)).scalar()


def _contract_line_amount(db, *, branch_id: int, party_id: int, item, as_of_date) -> dict:
    taxes = resolve_line_tax_group(branch_id, item.product_id, db, as_of_date, customer_id=party_id)
    tax_rate = sum((t["tax_rate"] for t in taxes), Decimal("0"))
    return {
        "tax_rate": tax_rate,
        "tax_rate_id": taxes[0]["tax_rate_id"] if len(taxes) == 1 else None,
        "amounts": compute_line_amounts(item.quantity, item.unit_price, tax_rate),
    }


def _line_preview_payload(index: int, item, tax_rate: Decimal, amounts: dict) -> dict:
    return {
        "index": index,
        "product_id": item.product_id,
        "description": item.description,
        "quantity": str(_dec(item.quantity).quantize(_D4, ROUND_HALF_UP)),
        "unit_price": money_str(item.unit_price),
        "tax_rate": rate_str(tax_rate),
        "subtotal": money_str(amounts["subtotal"]),
        "tax_amount": money_str(amounts["tax_amount"]),
        "line_total": money_str(amounts["line_total"]),
    }


def _calculate_contract_preview(db, *, branch_id: int, party_id: int, items, as_of_date) -> dict:
    saved_items = []
    preview_lines = []
    total_lines = []

    for index, item in enumerate(items):
        line = _contract_line_amount(
            db,
            branch_id=branch_id,
            party_id=party_id,
            item=item,
            as_of_date=as_of_date,
        )
        amounts = line["amounts"]
        tax_rate = line["tax_rate"]
        saved_items.append({
            "item": item,
            "tax_rate": tax_rate,
            "tax_rate_id": line["tax_rate_id"],
            "total": amounts["line_total"],
        })
        total_lines.append({
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "tax_rate": tax_rate,
        })
        preview_lines.append(_line_preview_payload(index, item, tax_rate, amounts))

    totals = compute_invoice_totals(total_lines)
    return {
        "saved_items": saved_items,
        "lines": preview_lines,
        "subtotal": totals["subtotal"],
        "tax_amount": totals["total_tax"],
        "grand_total": totals["grand_total"],
    }


def _interval_months(interval: str | None) -> int:
    return {
        "monthly": 1,
        "quarterly": 3,
        "semi_annual": 6,
        "semiannual": 6,
        "annual": 12,
        "yearly": 12,
    }.get((interval or "monthly").lower(), 1)


def _add_months(d: date, months: int) -> date:
    year = d.year + ((d.month - 1 + months) // 12)
    month = ((d.month - 1 + months) % 12) + 1
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    last_day = (next_month - timedelta(days=1)).day
    return date(year, month, min(d.day, last_day))


def _billing_period_end(start: date, interval: str | None) -> date:
    return _add_months(start, _interval_months(interval)) - timedelta(days=1)


def _recognition_schedule(amount: Decimal, billing_start: date, interval: str | None) -> list[dict]:
    months = _interval_months(interval)
    if months <= 0:
        months = 1

    monthly_amount = (amount / Decimal(str(months))).quantize(_D2, ROUND_HALF_UP)
    last_amount = (amount - (monthly_amount * Decimal(str(months - 1)))).quantize(_D2, ROUND_HALF_UP)
    rows = []
    recognition_date = date(billing_start.year, billing_start.month, 1)

    for index in range(months):
        rows.append({
            "recognition_date": str(recognition_date),
            "amount": money_str(last_amount if index == months - 1 else monthly_amount),
        })
        recognition_date = _add_months(recognition_date, 1)
    return rows


def _serialize_contract_billing_preview(contract, preview: dict, billing_start: date) -> dict:
    billing_end = _billing_period_end(billing_start, contract.billing_interval)
    return {
        "contract_id": contract.id,
        "billing_period_start": str(billing_start),
        "billing_period_end": str(billing_end),
        "currency": contract.currency or "SAR",
        "invoice": {
            "subtotal": money_str(preview["subtotal"]),
            "tax_amount": money_str(preview["tax_amount"]),
            "grand_total": money_str(preview["grand_total"]),
        },
        "lines": preview["lines"],
        "revenue_recognition_schedule": _recognition_schedule(
            preview["subtotal"],
            billing_start,
            contract.billing_interval,
        ),
    }


def _assert_submitted_total_matches(submitted, calculated: Decimal, request: Request) -> None:
    if submitted is None:
        raise HTTPException(**http_error(422, "submitted_grand_total_mismatch", request))
    if abs(_dec(submitted) - calculated) > _D2:
        raise HTTPException(**http_error(422, "submitted_grand_total_mismatch", request))

@router.post("", response_model=ContractResponse, dependencies=[Depends(require_permission("contracts.create"))])
def create_contract(
    contract: ContractCreate,
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key", max_length=64),
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
            
            # Idempotency pre-check
            if idempotency_key:
                existing_idem = db.execute(text("""
                    SELECT id FROM contracts WHERE idempotency_key = :key LIMIT 1
                """), {"key": idempotency_key}).fetchone()
                if existing_idem:
                    return get_contract(existing_idem.id, current_user)
            
            # Validate branch access
            branch_id = validate_branch_access(current_user, getattr(contract, 'branch_id', None))
            if branch_id is None:
                branch_id = validate_branch_access(current_user, _default_branch_id(db), request)
            if branch_id is None:
                raise HTTPException(**http_error(400, "branch_required", request))
    
            preview = _calculate_contract_preview(
                db,
                branch_id=branch_id,
                party_id=contract.party_id,
                items=contract.items,
                as_of_date=contract.start_date,
            )
            final_total = preview["grand_total"]
    
            # Create Contract Header
            contract_id = db.execute(
                text("""
                    INSERT INTO contracts (
                        contract_number, party_id, contract_type, status, 
                        start_date, end_date, billing_interval, total_amount, 
                        currency, notes, created_by, created_at,
                        branch_id, idempotency_key
                    ) VALUES (
                        :num, :pid, :ctype, 'active', :start, :end, :interval, :total,
                        :cur, :notes, :uid, CURRENT_TIMESTAMP,
                        :bid, :idem_key
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
                    "uid": current_user.id,
                    "bid": branch_id,
                    "idem_key": idempotency_key
                }
            ).scalar()
    
            # Create Contract Items
            for saved in preview["saved_items"]:
                item = saved["item"]
                db.execute(
                    text("""
                        INSERT INTO contract_items (
                            contract_id, product_id, description, quantity, 
                            unit_price, tax_rate, tax_rate_id, total
                        ) VALUES (
                            :cid, :pid, :desc, :qty, :price, :tax, :tax_id, :total
                        )
                    """),
                    {
                        "cid": contract_id,
                        "pid": item.product_id,
                        "desc": item.description,
                        "qty": item.quantity,
                        "price": item.unit_price,
                        "tax": saved["tax_rate"],
                        "tax_id": saved["tax_rate_id"],
                        "total": saved["total"]
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
                db.execute(text("SELECT name FROM parties WHERE id = :id"), {"id": contract.party_id}).scalar()
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


@router.post("/preview", dependencies=[Depends(require_permission("contracts.view"))])
def preview_contract(
    contract: ContractCreate,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
):
    """Preview contract totals without saving the contract."""
    with transactional(current_user.company_id) as db:
        try:
            branch_id = validate_branch_access(current_user, getattr(contract, "branch_id", None))
            if branch_id is None:
                branch_id = validate_branch_access(current_user, _default_branch_id(db), request)
            if branch_id is None:
                raise HTTPException(**http_error(400, "branch_required", request))

            preview = _calculate_contract_preview(
                db,
                branch_id=branch_id,
                party_id=contract.party_id,
                items=contract.items,
                as_of_date=contract.start_date,
            )
            return {
                "subtotal": money_str(preview["subtotal"]),
                "tax_amount": money_str(preview["tax_amount"]),
                "grand_total": money_str(preview["grand_total"]),
                "lines": preview["lines"],
                "currency": contract.currency or get_base_currency(db),
            }
        except HTTPException:
            raise
        except Exception:
            logger.exception("Error previewing contract")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/billing-cycle/preview", dependencies=[Depends(require_permission("contracts.view"))])
def preview_contract_billing_cycle(
    preview_request: ContractBillingCyclePreviewRequest,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
):
    """Preview the next contract billing cycle and revenue recognition schedule."""
    with transactional(current_user.company_id) as db:
        try:
            contract = db.execute(
                text("SELECT * FROM contracts WHERE id = :id AND status = 'active'"),
                {"id": preview_request.contract_id},
            ).fetchone()
            if not contract:
                raise HTTPException(**http_error(404, "contract_inactive_or_not_found"))
            if contract.branch_id is not None:
                validate_branch_access(current_user, contract.branch_id, request)

            items = db.execute(
                text("SELECT * FROM contract_items WHERE contract_id = :id"),
                {"id": preview_request.contract_id},
            ).fetchall()
            if not items:
                raise HTTPException(**http_error(400, "contract_items_empty"))

            branch_id = contract.branch_id or _default_branch_id(db)
            branch_id = validate_branch_access(current_user, branch_id, request)
            if branch_id is None:
                raise HTTPException(**http_error(400, "branch_required", request))

            billing_start = preview_request.billing_start or contract.next_billing_date or date.today()
            cycles = []
            for _ in range(preview_request.cycles):
                preview = _calculate_contract_preview(
                    db,
                    branch_id=branch_id,
                    party_id=contract.party_id,
                    items=items,
                    as_of_date=billing_start,
                )
                cycles.append(_serialize_contract_billing_preview(contract, preview, billing_start))
                billing_start = _billing_period_end(billing_start, contract.billing_interval) + timedelta(days=1)
            return cycles[0] if preview_request.cycles == 1 else {"contract_id": contract.id, "cycles": cycles}
        except HTTPException:
            raise
        except Exception:
            logger.exception("Error previewing contract billing cycle")
            raise HTTPException(**http_error(500, "internal_error"))

@router.get("", response_model=List[ContractResponse], dependencies=[Depends(require_permission("contracts.view"))])
def list_contracts(
    branch_id: Optional[int] = None,
    search: Optional[str] = None,
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
        if search:
            conditions.append("""(
                c.contract_number ILIKE :search
                OR c.contract_type ILIKE :search
                OR c.status ILIKE :search
                OR c.notes ILIKE :search
                OR p.name ILIKE :search
            )""")
            params["search"] = f"%{search}%"
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
            c_items = items_by_contract.get(c.id, [])
            line_dicts = [{"quantity": i["quantity"], "unit_price": i["unit_price"], "tax_rate": i.get("tax_rate") or 0} for i in c_items]
            totals = compute_invoice_totals(line_dicts)
            result.append({
                **c._mapping,
                "items": c_items,
                "subtotal": totals["subtotal"],
                "tax_amount": totals["total_tax"]
            })
        return result

@router.get("/alerts/expiring", dependencies=[Depends(require_permission("contracts.view"))])
def get_expiring_contracts(
    days: int = 30,
    branch_id: Optional[int] = None,
    current_user: UserResponse = Depends(get_current_user)
):
    """جلب العقود التي ستنتهي خلال فترة محددة (افتراضي 30 يوم)"""
    with transactional(current_user.company_id) as db:
        try:
            today = date.today()
            future_date = today + timedelta(days=days)
            
            params = {"today": today, "future": future_date}
            branch_clause = branch_scope_filter(current_user, branch_id, "c.branch_id", params)
            contracts = db.execute(text(f"""
                SELECT c.*, p.name as party_name,
                       (c.end_date - CURRENT_DATE) as days_remaining
                FROM contracts c
                JOIN parties p ON c.party_id = p.id
                WHERE c.status = 'active' 
                  AND c.end_date IS NOT NULL
                  AND c.end_date BETWEEN :today AND :future
                  {branch_clause}
                ORDER BY c.end_date ASC
            """), params).fetchall()
            
            result = []
            for c in contracts:
                result.append({
                    "id": c.id,
                    "contract_number": c.contract_number,
                    "party_name": c.party_name,
                    "contract_type": c.contract_type,
                    "end_date": str(c.end_date),
                    "days_remaining": c.days_remaining,
                    "total_amount": money_str(c.total_amount or 0),
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
    branch_id: Optional[int] = None,
    current_user: UserResponse = Depends(get_current_user)
):
    """ملخص إحصائيات العقود"""
    with transactional(current_user.company_id) as db:
        try:
            params = {}
            branch_clause = branch_scope_filter(current_user, branch_id, "branch_id", params)
            where_clause = f"WHERE {branch_clause[4:].strip()}" if branch_clause else ""
            stats = db.execute(text(f"""
                SELECT 
                    COUNT(*) as total_contracts,
                    COUNT(*) FILTER (WHERE status = 'active') as active_count,
                    COUNT(*) FILTER (WHERE status = 'expired') as expired_count,
                    COUNT(*) FILTER (WHERE status = 'cancelled') as cancelled_count,
                    COALESCE(SUM(total_amount) FILTER (WHERE status = 'active'), 0) as active_value,
                    COALESCE(SUM(total_amount), 0) as total_value,
                    COUNT(*) FILTER (WHERE status = 'active' AND end_date IS NOT NULL AND end_date <= CURRENT_DATE + INTERVAL '30 days') as expiring_soon
                FROM contracts
                {where_clause}
            """), params).fetchone()
            
            return {
                "total_contracts": stats.total_contracts,
                "active_count": stats.active_count,
                "expired_count": stats.expired_count,
                "cancelled_count": stats.cancelled_count,
                "active_value": money_str(stats.active_value),
                "total_value": money_str(stats.total_value),
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
        if contract.branch_id is not None:
            validate_branch_access(current_user, contract.branch_id)
            
        items = db.execute(
            text("SELECT * FROM contract_items WHERE contract_id = :id"),
            {"id": contract_id}
        ).fetchall()
        
        line_dicts = [{"quantity": i.quantity, "unit_price": i.unit_price, "tax_rate": i.tax_rate or 0} for i in items]
        totals = compute_invoice_totals(line_dicts)
        
        return {
            **contract._mapping,
            "items": [dict(row._mapping) for row in items],
            "subtotal": totals["subtotal"],
            "tax_amount": totals["total_tax"]
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

        # Validate branch access if attempting to change branch
        if data.branch_id is not None:
            validate_branch_access(current_user, data.branch_id)
        
        if existing.branch_id is not None:
            validate_branch_access(current_user, existing.branch_id)

        # Build dynamic SET clause from non-None fields (partial update)
        updatable_fields = {
            "party_id": data.party_id, "contract_type": data.contract_type,
            "start_date": data.start_date, "end_date": data.end_date,
            "billing_interval": data.billing_interval,
            "currency": data.currency, "notes": data.notes,
            "branch_id": data.branch_id
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
            effective_branch_id = data.branch_id if data.branch_id is not None else existing.branch_id
            effective_branch_id = validate_branch_access(current_user, effective_branch_id)
            if effective_branch_id is None:
                effective_branch_id = validate_branch_access(current_user, _default_branch_id(db), request)
            if effective_branch_id is None:
                raise HTTPException(**http_error(400, "branch_required", request))

            calculated_total = Decimal('0')
            for item in data.items:
                line = _contract_line_amount(
                    db,
                    branch_id=effective_branch_id,
                    party_id=data.party_id if data.party_id is not None else existing.party_id,
                    item=item,
                    as_of_date=data.start_date if data.start_date is not None else existing.start_date,
                )
                la = line["amounts"]
                calculated_total += la['line_total']
                db.execute(text("""
                    INSERT INTO contract_items (contract_id, product_id, description, quantity, unit_price, tax_rate, tax_rate_id, total)
                    VALUES (:cid, :pid, :desc, :qty, :price, :tax, :tax_id, :total)
                """), {
                    "cid": contract_id, "pid": item.product_id, "desc": item.description,
                    "qty": item.quantity, "price": item.unit_price,
                    "tax": line["tax_rate"], "tax_id": line["tax_rate_id"],
                    "total": la["line_total"]
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
    idempotency_key = require_idempotency_key(request, operation="contract renewal")
    with transactional(current_user.company_id) as db:
        try:
            replay = db.execute(
                text("""
                    SELECT id
                    FROM contracts
                    WHERE id = :id
                      AND renewal_idempotency_key = :key
                    LIMIT 1
                """),
                {"id": contract_id, "key": idempotency_key},
            ).fetchone()
            if replay:
                return get_contract(contract_id, current_user)

            duplicate_key = db.execute(
                text("""
                    SELECT id
                    FROM contracts
                    WHERE renewal_idempotency_key = :key
                      AND id <> :id
                    LIMIT 1
                """),
                {"id": contract_id, "key": idempotency_key},
            ).fetchone()
            if duplicate_key:
                raise HTTPException(**http_error(409, "duplicate_idempotency_key", request))

            contract = db.execute(
                text("SELECT * FROM contracts WHERE id = :id"),
                {"id": contract_id}
            ).fetchone()
            
            if not contract:
                raise HTTPException(**http_error(404, "contract_not_found"))
            
            if contract.status != 'active':
                raise HTTPException(**http_error(400, "only_active_contracts_renew"))
            if contract.branch_id is not None:
                validate_branch_access(current_user, contract.branch_id, request)
            if contract.end_date is None:
                raise HTTPException(**http_error(400, "contract_end_date_required", request))
            
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
            elif interval in ('annual', 'yearly'):
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
                        renewal_idempotency_key = :idem_key,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                """),
                {
                    "start": new_start,
                    "end": new_end,
                    "id": contract_id,
                    "idem_key": idempotency_key,
                }
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
    body: Optional[ContractInvoiceGenerateRequest] = None,
    current_user: UserResponse = Depends(get_current_user)
):
    """إنشاء فاتورة من العقد"""
    idempotency_key = require_idempotency_key(request, operation="contract invoice generation")
    with transactional(current_user.company_id) as db:
        try:
            replay = db.execute(
                text("""
                    SELECT id, invoice_number, total
                    FROM invoices
                    WHERE idempotency_key = :key
                    LIMIT 1
                """),
                {"key": idempotency_key},
            ).fetchone()
            if replay:
                return {
                    "success": True,
                    "invoice_id": replay.id,
                    "invoice_number": replay.invoice_number,
                    "total": money_str(replay.total),
                    "duplicate": True,
                }

            contract = db.execute(
                text("SELECT * FROM contracts WHERE id = :id AND status = 'active'"),
                {"id": contract_id}
            ).fetchone()
            
            if not contract:
                raise HTTPException(**http_error(404, "contract_inactive_or_not_found"))
            if contract.branch_id is not None:
                validate_branch_access(current_user, contract.branch_id, request)
            
            items = db.execute(
                text("SELECT * FROM contract_items WHERE contract_id = :id"),
                {"id": contract_id}
            ).fetchall()
            
            if not items:
                raise HTTPException(**http_error(400, "contract_items_empty"))
            
            from datetime import date as dt_date
            from utils.accounting import generate_sequential_number
    
            # Get an authorized branch for tax resolution
            user_branch = db.execute(text(
                "SELECT branch_id FROM user_branches WHERE user_id = :uid ORDER BY branch_id LIMIT 1"
            ), {"uid": current_user.id}).fetchone()
            _branch_id = contract.branch_id or (user_branch.branch_id if user_branch else None) or _default_branch_id(db)
            _branch_id = validate_branch_access(current_user, _branch_id, request)
            if _branch_id is None:
                raise HTTPException(**http_error(400, "branch_required", request))
            billing_start = body.billing_start if body and body.billing_start else contract.next_billing_date or dt_date.today()
            billing_end = _billing_period_end(billing_start, contract.billing_interval)
            inv_num = generate_sequential_number(
                db, f"INV-CTR-{billing_start.year}", "invoices", "invoice_number", branch_id=_branch_id
            )

            preview = _calculate_contract_preview(
                db,
                branch_id=_branch_id,
                party_id=contract.party_id,
                items=items,
                as_of_date=billing_start,
            )
            subtotal = preview["subtotal"]
            tax_total = preview["tax_amount"]
            total = preview["grand_total"]
            _assert_submitted_total_matches(
                body.submitted_grand_total if body else None,
                total,
                request,
            )
            
            inv_id = db.execute(text("""
                INSERT INTO invoices (
                    invoice_number, invoice_type, party_id, contract_id, invoice_date, due_date,
                    subtotal, tax_amount, total, paid_amount, status, notes,
                    branch_id, created_by, currency, exchange_rate, idempotency_key
                ) VALUES (
                    :num, :type, :pid, :contract_id, :invoice_date, :due_date,
                    :sub, :tax, :total, 0, 'unpaid', :notes,
                    :branch_id, :uid, :curr, :exchange_rate, :idem_key
                ) RETURNING id
            """), {
                "num": inv_num,
                "type": "purchase" if contract.contract_type == "purchase" else "sales",
                "pid": contract.party_id,
                "contract_id": contract_id,
                "invoice_date": billing_start,
                "due_date": billing_end,
                "sub": subtotal, "tax": tax_total, "total": total,
                "notes": f"فاتورة عقد #{contract.contract_number}",
                "branch_id": _branch_id,
                "uid": current_user.id,
                "curr": contract.currency or get_base_currency(db),
                "exchange_rate": Decimal("1"),
                "idem_key": idempotency_key,
            }).scalar()
            
            for saved in preview["saved_items"]:
                item = saved["item"]
                db.execute(text("""
                    INSERT INTO invoice_lines (invoice_id, product_id, description, quantity, unit_price, tax_rate, tax_rate_id, total)
                    VALUES (:iid, :pid, :desc, :qty, :price, :tax, :tax_id, :total)
                """), {
                    "iid": inv_id, "pid": item.product_id, "desc": item.description,
                    "qty": item.quantity, "price": item.unit_price,
                    "tax": saved["tax_rate"], "tax_id": saved["tax_rate_id"],
                    "total": saved["total"]
                })

            db.execute(
                text("""
                    UPDATE contracts
                    SET next_billing_date = :next_billing_date,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                """),
                {
                    "next_billing_date": billing_end + timedelta(days=1),
                    "id": contract_id,
                },
            )
            
    
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
        except Exception:
            logger.exception("Error generating contract invoice")
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
            if contract.branch_id is not None:
                validate_branch_access(current_user, contract.branch_id, request)
            
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
    
            total_value = _dec(c.get("total_amount") or c.get("value") or 0)
            invoiced = _dec(inv.get("total", 0))
            utilization = (
                (invoiced / total_value * Decimal("100")).quantize(_D2, ROUND_HALF_UP)
                if total_value > 0
                else Decimal("0")
            )
    
            return {
                "contract_id": contract_id,
                "total_value": money_str(total_value),
                "invoiced_amount": money_str(invoiced),
                "outstanding_amount": money_str(inv.get("outstanding", 0)),
                "utilization_pct": rate_str(utilization),
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
            amount = _dec(payload.get("amount") or 0)
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
    request: Request,
    current_user=Depends(get_current_user),
):
    """Generate an invoice for a completed milestone.

    Minimal implementation: creates a draft AR invoice for the milestone
    amount linked back via ``contract_milestones.invoice_id`` and flips the
    milestone to ``billed``. Accounting posting follows the standard invoice
    flow (invoice remains ``draft`` until posted through the regular
    approval path).
    """
    idempotency_key = require_idempotency_key(request, operation="contract milestone billing")
    with transactional(current_user.company_id) as db:
        try:
            replay = db.execute(
                text("""
                    SELECT id, invoice_number
                    FROM invoices
                    WHERE idempotency_key = :key
                    LIMIT 1
                """),
                {"key": idempotency_key},
            ).fetchone()
            if replay:
                return {
                    "id": milestone_id,
                    "status": "billed",
                    "invoice_id": replay.id,
                    "invoice_number": replay.invoice_number,
                    "duplicate": True,
                }

            contract = db.execute(
                text(
                    "SELECT id, party_id, currency, branch_id FROM contracts "
                    "WHERE id = :id"
                ),
                {"id": contract_id},
            ).fetchone()
            if not contract:
                raise HTTPException(**http_error(404, "contract_not_found"))
            if contract.branch_id is not None:
                validate_branch_access(current_user, contract.branch_id, request)
    
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
            from utils.accounting import generate_sequential_number
            invoice_date = date.today()
            inv_num = generate_sequential_number(
                db,
                f"INV-CTR-MS-{invoice_date.year}",
                "invoices",
                "invoice_number",
                branch_id=contract.branch_id,
            )
            amount = _dec(ms.amount or 0).quantize(_D2, ROUND_HALF_UP)
            inv = db.execute(
                text(
                    """
                    INSERT INTO invoices
                        (invoice_number, invoice_type, party_id, contract_id, invoice_date,
                         due_date, currency, subtotal, tax_amount, total, paid_amount,
                         status, notes, branch_id, created_by, idempotency_key)
                    VALUES
                        (:num, 'sales', :pid, :cid, :invoice_date,
                         :due_date, :cur, :amt, 0, :amt, 0,
                         'draft', :notes, :branch_id, :uid, :idem_key)
                    RETURNING id
                    """
                ),
                {
                    "num": inv_num,
                    "pid": contract.party_id,
                    "cid": contract_id,
                    "invoice_date": invoice_date,
                    "due_date": invoice_date + timedelta(days=30),
                    "cur": contract.currency or "SAR",
                    "amt": amount,
                    "notes": f"Milestone: {ms.name}",
                    "branch_id": contract.branch_id,
                    "uid": current_user.id,
                    "idem_key": idempotency_key,
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
                "invoice_number": inv_num,
            }
        except HTTPException:
            pass
            raise
        except Exception as e:
            pass
            logger.error(f"Error billing milestone: {e}")
            raise HTTPException(**http_error(500, "internal_error"))
