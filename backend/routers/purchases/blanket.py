"""Purchases sub-router — split from monolithic purchases.py (T6.3).

This file is auto-generated when purchases.py was split. Endpoints here
are mounted under the parent /buying prefix via purchases/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
import logging

from utils.cache import invalidate_company_cache
from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.audit import log_activity
from utils.permissions import require_permission, require_module
from utils.accounting import get_mapped_account_id, generate_sequential_number, get_base_currency
from utils.fiscal_lock import check_fiscal_period_open
from services.gl_service import create_journal_entry as gl_create_journal_entry
from schemas.purchases import (
    PurchaseCreate, SupplierGroupCreate, POCreate, POReceiveRequest,
    SupplierPaymentCreate,
)
from schemas.blanket_po import BlanketPOCreate, ReleaseOrderCreate, PriceAmendRequest

_D2 = Decimal("0.01")
_D4 = Decimal("0.0001")
BLANKET_PO_STATUSES = {"draft", "active", "expired", "completed", "cancelled"}


def _dec(v) -> Decimal:
    """Convert any numeric value to Decimal safely."""
    return Decimal(str(v)) if v is not None else Decimal("0")


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/blanket", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("buying.blanket_manage"))], response_model=Dict[str, Any])
def create_blanket_po(payload: BlanketPOCreate, request: Request, current_user: dict = Depends(get_current_user)):
    """Create a new blanket purchase order."""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
        try:
            username = current_user.get("username", "unknown") if isinstance(current_user, dict) else getattr(current_user, "username", "unknown")
            user_id = current_user.get("id") if isinstance(current_user, dict) else getattr(current_user, "id", None)
    
            total_qty = _dec(payload.total_quantity)
            unit_price = _dec(payload.unit_price)
            total_amount = (total_qty * unit_price).quantize(_D4, ROUND_HALF_UP)
    
            agr_number = generate_sequential_number(db, f"BPO-{datetime.now().year}", "blanket_purchase_orders", "agreement_number")
    
            result = db.execute(text("""
                INSERT INTO blanket_purchase_orders
                    (supplier_id, agreement_number, total_quantity, unit_price, total_amount,
                     valid_from, valid_to, status, branch_id, currency, notes, created_by, party_site_id)
                VALUES (:supplier_id, :agr_num, :total_qty, :unit_price, :total_amount,
                        :valid_from, :valid_to, 'draft', :branch_id, :currency, :notes, :created_by, :party_site_id)
                RETURNING id
            """), {
                "supplier_id": payload.supplier_id,
                "agr_num": agr_number,
                "total_qty": str(total_qty),
                "unit_price": str(unit_price),
                "total_amount": str(total_amount),
                "valid_from": payload.valid_from,
                "valid_to": payload.valid_to,
                "branch_id": payload.branch_id,
                "currency": payload.currency or "SAR",
                "notes": payload.notes,
                "created_by": username,
                "party_site_id": payload.party_site_id,
            })
            bpo_id = result.fetchone()[0]
    
            log_activity(db, user_id=user_id, username=username, action="blanket_po_created",
                         resource_type="blanket_purchase_order", resource_id=str(bpo_id),
                         details={"agreement_number": agr_number, "supplier_id": payload.supplier_id},
                         request=request)
            return {"id": bpo_id, "agreement_number": agr_number, "message": i18n_message("blanket_po_created_success", request)}
        except HTTPException:
            raise
        except Exception as e:
            pass
            logger.error(f"Failed to create blanket PO: {e}")
            raise HTTPException(**http_error(500, "failed_to_create_blanket_po", request))
@router.get("/blanket", dependencies=[Depends(require_permission("buying.blanket_view"))], response_model=Dict[str, Any])
def list_blanket_pos(
    status_filter: Optional[str] = None,
    supplier_id: Optional[int] = None,
    branch_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(get_current_user),
):
    """List blanket purchase orders with remaining balance."""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
        conditions = []
        params = {"skip": skip, "limit": limit}

        if status_filter and status_filter in BLANKET_PO_STATUSES:
            conditions.append("b.status = :status")
            params["status"] = status_filter
        if supplier_id:
            conditions.append("b.supplier_id = :supplier_id")
            params["supplier_id"] = supplier_id
        if branch_id:
            conditions.append("b.branch_id = :branch_id")
            params["branch_id"] = branch_id

        where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        try:
            rows = db.execute(text(  # noqa: sql-lint
                f"""
                SELECT b.*, p.name AS supplier_name
                FROM blanket_purchase_orders b
                LEFT JOIN parties p ON p.id = b.supplier_id
                {where_clause}
                ORDER BY b.created_at DESC
                OFFSET :skip LIMIT :limit
            """), params).fetchall()
        except Exception as e:
            db.rollback()
            if "does not exist" in str(e):
                return {"blanket_pos": []}
            raise

        result = []
        for row in rows:
            d = dict(row._mapping)
            d["remaining_quantity"] = str(_dec(d["total_quantity"]) - _dec(d["released_quantity"]))
            d["remaining_amount"] = str(_dec(d["total_amount"]) - _dec(d["released_amount"]))
            result.append(d)

        return {"blanket_pos": result}
@router.get("/blanket/{bpo_id}", dependencies=[Depends(require_permission("buying.blanket_view"))], response_model=Dict[str, Any])
def get_blanket_po(request: Request, bpo_id: int, current_user: dict = Depends(get_current_user)):
    """Get blanket PO details with release orders."""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
        bpo = db.execute(text("""
            SELECT b.*, p.name AS supplier_name
            FROM blanket_purchase_orders b
            LEFT JOIN parties p ON p.id = b.supplier_id
            WHERE b.id = :id
        """), {"id": bpo_id}).fetchone()

        if not bpo:
            raise HTTPException(**http_error(404, "blanket_po_not_found", request))

        d = dict(bpo._mapping)
        d["remaining_quantity"] = str(_dec(d["total_quantity"]) - _dec(d["released_quantity"]))
        d["remaining_amount"] = str(_dec(d["total_amount"]) - _dec(d["released_amount"]))

        releases = db.execute(text("""
            SELECT r.*, po.po_number
            FROM blanket_po_release_orders r
            LEFT JOIN purchase_orders po ON po.id = r.purchase_order_id
            WHERE r.blanket_po_id = :bpo_id
            ORDER BY r.release_date DESC
        """), {"bpo_id": bpo_id}).fetchall()

        d["releases"] = [dict(r._mapping) for r in releases]
        return d
@router.put("/blanket/{bpo_id}/activate", dependencies=[Depends(require_permission("buying.blanket_manage"))], response_model=Dict[str, Any])
def activate_blanket_po(bpo_id: int, request: Request, current_user: dict = Depends(get_current_user)):
    """Activate a draft blanket PO."""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
        try:
            bpo = db.execute(text(
                "SELECT id, status FROM blanket_purchase_orders WHERE id = :id"
            ), {"id": bpo_id}).fetchone()
    
            if not bpo:
                raise HTTPException(**http_error(404, "blanket_po_not_found", request))
            if bpo._mapping["status"] != "draft":
                raise HTTPException(**http_error(400, "only_draft_blanket_pos_can_be_activated", request))
    
            db.execute(text(
                "UPDATE blanket_purchase_orders SET status = 'active', updated_at = NOW() WHERE id = :id"
            ), {"id": bpo_id})
    
            user_id = current_user.get("id") if isinstance(current_user, dict) else getattr(current_user, "id", None)
            username = current_user.get("username", "unknown") if isinstance(current_user, dict) else getattr(current_user, "username", "unknown")
            log_activity(db, user_id=user_id, username=username, action="blanket_po_activated",
                         resource_type="blanket_purchase_order", resource_id=str(bpo_id),
                         details={"blanket_po_id": bpo_id}, request=request)
            return {"message": i18n_message("blanket_po_activated_success", request)}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
@router.post("/blanket/{bpo_id}/release", dependencies=[Depends(require_permission("buying.blanket_release"))], response_model=Dict[str, Any])
def create_release_order(bpo_id: int, payload: ReleaseOrderCreate, request: Request, current_user: dict = Depends(get_current_user)):
    """Create a release order against a blanket PO. Validates remaining quantity and warns if exceeds."""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
        try:
            bpo = db.execute(text("""
                SELECT * FROM blanket_purchase_orders WHERE id = :id
            """), {"id": bpo_id}).fetchone()
    
            if not bpo:
                raise HTTPException(**http_error(404, "blanket_po_not_found", request))
    
            bpo_data = dict(bpo._mapping)
            if bpo_data["status"] != "active":
                raise HTTPException(**http_error(400, "blanket_po_must_be_active_to_release_orders", request))
    
            release_qty = _dec(payload.release_quantity)
            released_qty = _dec(bpo_data["released_quantity"])
            total_qty = _dec(bpo_data["total_quantity"])
            unit_price = _dec(bpo_data["unit_price"])
    
            remaining_qty = total_qty - released_qty
    
            if release_qty > remaining_qty:
                raise HTTPException(
                    status_code=400,
                    detail=f"Release quantity {str(release_qty)} exceeds remaining agreement quantity {str(remaining_qty)}"
                )
    
            release_amount = (release_qty * unit_price).quantize(_D4, ROUND_HALF_UP)
            release_dt = payload.release_date or date.today()
            username = current_user.get("username", "unknown") if isinstance(current_user, dict) else getattr(current_user, "username", "unknown")
            user_id = current_user.get("id") if isinstance(current_user, dict) else getattr(current_user, "id", None)
    
            result = db.execute(text("""
                INSERT INTO blanket_po_release_orders
                    (blanket_po_id, release_quantity, release_amount, release_date, created_by)
                VALUES (:bpo_id, :qty, :amount, :rel_date, :created_by)
                RETURNING id
            """), {
                "bpo_id": bpo_id,
                "qty": str(release_qty),
                "amount": str(release_amount),
                "rel_date": release_dt,
                "created_by": username,
            })
            release_id = result.fetchone()[0]
    
            # Update blanket PO consumed totals
            new_released_qty = released_qty + release_qty
            new_released_amt = _dec(bpo_data["released_amount"]) + release_amount
            new_status = "completed" if new_released_qty >= total_qty else "active"
    
            db.execute(text("""
                UPDATE blanket_purchase_orders
                SET released_quantity = :rel_qty, released_amount = :rel_amt,
                    status = :status, updated_at = NOW()
                WHERE id = :id
            """), {
                "rel_qty": str(new_released_qty),
                "rel_amt": str(new_released_amt),
                "status": new_status,
                "id": bpo_id,
            })
    
            log_activity(db, user_id=user_id, username=username, action="blanket_po_release",
                         resource_type="blanket_po_release_order", resource_id=str(release_id),
                         details={"blanket_po_id": bpo_id, "release_quantity": str(release_qty)},
                         request=request)
    
            response = {
                "id": release_id,
                "release_quantity": str(release_qty),
                "release_amount": str(release_amount),
                "remaining_quantity": str(total_qty - new_released_qty),
                "remaining_amount": str(_dec(bpo_data["total_amount"]) - new_released_amt),
                "message": i18n_message("release_order_created_success", request),
            }
            return response
        except HTTPException:
            raise
        except Exception as e:
            pass
            logger.error(f"Failed to create release order: {e}")
            raise HTTPException(**http_error(500, "failed_to_create_release_order", request))
@router.put("/blanket/{bpo_id}/amend-price", dependencies=[Depends(require_permission("buying.blanket_manage"))], response_model=Dict[str, Any])
def amend_blanket_po_price(bpo_id: int, payload: PriceAmendRequest, request: Request, current_user: dict = Depends(get_current_user)):
    """Amend the unit price of a blanket PO with effective date tracking."""
    company_id = current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id
    with transactional(company_id) as db:
        try:
            bpo = db.execute(text("""
                SELECT id, unit_price, total_quantity, released_quantity, released_amount,
                       price_amendment_history, status
                FROM blanket_purchase_orders WHERE id = :id
            """), {"id": bpo_id}).fetchone()
    
            if not bpo:
                raise HTTPException(**http_error(404, "blanket_po_not_found", request))
    
            bpo_data = dict(bpo._mapping)
            if bpo_data["status"] not in ("draft", "active"):
                raise HTTPException(**http_error(400, "cannot_amend_price_on_a_completedcancelledexpired_", request))
    
            old_price = _dec(bpo_data["unit_price"])
            new_price = _dec(payload.new_price)
            total_qty = _dec(bpo_data["total_quantity"])
            new_total_amount = (total_qty * new_price).quantize(_D4, ROUND_HALF_UP)
    
            # Append to price amendment history
            history = bpo_data.get("price_amendment_history") or []
            history.append({
                "effective_date": str(payload.effective_date),
                "old_price": str(old_price),
                "new_price": str(new_price),
                "reason": payload.reason,
                "amended_at": datetime.now().isoformat(),
            })
    
            import json
            db.execute(text("""
                UPDATE blanket_purchase_orders
                SET unit_price = :new_price, total_amount = :new_total,
                    price_amendment_history = :history::jsonb, updated_at = NOW()
                WHERE id = :id
            """), {
                "new_price": str(new_price),
                "new_total": str(new_total_amount),
                "history": json.dumps(history),
                "id": bpo_id,
            })
    
            user_id = current_user.get("id") if isinstance(current_user, dict) else getattr(current_user, "id", None)
            username = current_user.get("username", "unknown") if isinstance(current_user, dict) else getattr(current_user, "username", "unknown")
            log_activity(db, user_id=user_id, username=username, action="blanket_po_price_amended",
                         resource_type="blanket_purchase_order", resource_id=str(bpo_id),
                         details={"old_price": str(old_price), "new_price": str(new_price)},
                         request=request)
    
            return {
                "message": i18n_message("price_amended_success", request),
                "old_price": str(old_price),
                "new_price": str(new_price),
                "new_total_amount": str(new_total_amount),
                "remaining_amount": str(new_total_amount - _dec(bpo_data["released_amount"])),
            }
        except HTTPException:
            raise
        except Exception as e:
            pass
            logger.error(f"Failed to amend blanket PO price: {e}")
            raise HTTPException(**http_error(500, "failed_to_amend_price", request))
