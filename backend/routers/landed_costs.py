"""
AMAN ERP — Landed Costs Router
التكاليف المُضافة (الشحن، الجمارك، التأمين) وتوزيعها على أصناف الشراء
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error, i18n_message
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field
from decimal import Decimal, ROUND_HALF_UP
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import branch_scope_filter_from_scope, require_permission, require_module, resolve_branch_scope, validate_branch_access
from utils.audit import log_activity
from utils.accounting import (
    generate_sequential_number, get_mapped_account_id,
    get_base_currency
)
from utils.fiscal_lock import check_fiscal_period_open
from services.gl_service import create_journal_entry as gl_create_journal_entry

router = APIRouter(prefix="/purchases/landed-costs", tags=["Landed Costs"], dependencies=[Depends(require_module("buying"))])
logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')
_D6 = Decimal('0.000001')


def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')


def _u(current_user, key, default=None):
    """Safely get attribute from dict or Pydantic model."""
    if isinstance(current_user, dict):
        return current_user.get(key, default)
    return getattr(current_user, key, default)


# ─── Schemas ───────────────────────────────────────────────────────────────────

class LandedCostItemCreate(BaseModel):
    cost_type: str  # freight, customs, insurance, handling, other
    description: Optional[str] = None
    amount: Decimal = Field(..., gt=0)
    vendor_id: Optional[int] = None
    invoice_ref: Optional[str] = None

class LandedCostCreate(BaseModel):
    purchase_order_id: Optional[int] = None
    grn_id: Optional[int] = None
    reference: Optional[str] = None
    lc_date: Optional[str] = None
    currency: Optional[str] = None
    exchange_rate: Optional[Decimal] = None
    allocation_method: str = "by_value"  # by_value, by_quantity, by_weight, equal
    notes: Optional[str] = None
    cost_items: List[LandedCostItemCreate] = Field(default_factory=list)


# ─── LIST ──────────────────────────────────────────────────────────────────────

@router.get("", dependencies=[Depends(require_permission("buying.view"))], response_model=List[Dict[str, Any]])
def list_landed_costs(
    status_filter: Optional[str] = None,
    branch_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """List Landed Costs."""
    company_id = _u(current_user, "company_id")
    branch_scope = resolve_branch_scope(current_user, branch_id)
    with transactional(company_id) as db:
        query = """
            SELECT lc.*, po.po_number,
                   cu.full_name as created_by_name
            FROM landed_costs lc
            LEFT JOIN purchase_orders po ON po.id = lc.purchase_order_id
            LEFT JOIN company_users cu ON cu.id = lc.created_by
            WHERE 1=1
        """
        params = {}
        if status_filter:
            query += " AND lc.status = :st"
            params["st"] = status_filter
        query += branch_scope_filter_from_scope(branch_scope, "lc.branch_id", params)

        query += " ORDER BY lc.id DESC"
        rows = db.execute(text(query), params).fetchall()
        return [dict(r._mapping) for r in rows]


# ─── GET ONE ───────────────────────────────────────────────────────────────────

@router.get("/{lc_id}", dependencies=[Depends(require_permission("buying.view"))], response_model=Dict[str, Any])
def get_landed_cost(lc_id: int, request: Request, current_user: dict = Depends(get_current_user)):
    """Get Landed Cost."""
    company_id = _u(current_user, "company_id")
    with transactional(company_id) as db:
        lc = db.execute(text("""
            SELECT lc.*, po.po_number
            FROM landed_costs lc
            LEFT JOIN purchase_orders po ON po.id = lc.purchase_order_id
            WHERE lc.id = :id
        """), {"id": lc_id}).fetchone()
        if not lc:
            raise HTTPException(**http_error(404, "landed_cost_not_found", request))

        validate_branch_access(current_user, lc._mapping.get("branch_id"))

        items = db.execute(text("""
            SELECT lci.*, p.name as vendor_name
            FROM landed_cost_items lci
            LEFT JOIN parties p ON p.id = lci.vendor_id
            WHERE lci.landed_cost_id = :lcid
            ORDER BY lci.id
        """), {"lcid": lc_id}).fetchall()

        allocations = db.execute(text("""
            SELECT lca.*, pr.product_name, pr.sku
            FROM landed_cost_allocations lca
            LEFT JOIN products pr ON pr.id = lca.product_id
            WHERE lca.landed_cost_id = :lcid
            ORDER BY lca.id
        """), {"lcid": lc_id}).fetchall()

        result = dict(lc._mapping)
        result["cost_items"] = [dict(i._mapping) for i in items]
        result["allocations"] = [dict(a._mapping) for a in allocations]
        return result


# ─── CREATE ────────────────────────────────────────────────────────────────────

@router.post("", status_code=201, dependencies=[Depends(require_permission("buying.create"))], response_model=Dict[str, Any])
def create_landed_cost(body: LandedCostCreate, request: Request, current_user: dict = Depends(get_current_user)):
    """Create Landed Cost."""
    company_id = _u(current_user, "company_id")
    user_id = _u(current_user, "user_id") or _u(current_user, "id")
    with transactional(company_id) as db:
        try:
            if not body.cost_items:
                raise HTTPException(**http_error(400, "at_least_one_cost_required", request))
    
            year = datetime.now().year
            lc_number = generate_sequential_number(db, f"LC-{year}", "landed_costs", "lc_number")
            total = sum((_dec(item.amount) for item in body.cost_items), Decimal('0'))
            base_currency = get_base_currency(db)
            branch_id = None
            currency = body.currency or base_currency
            exchange_rate = _dec(1 if body.exchange_rate is None else body.exchange_rate)
            if body.purchase_order_id:
                po = db.execute(text("""
                    SELECT id, branch_id, currency, exchange_rate
                    FROM purchase_orders
                    WHERE id = :id
                    FOR UPDATE
                """), {"id": body.purchase_order_id}).fetchone()
                if not po:
                    raise HTTPException(**http_error(404, "linked_po_not_found", request))
                branch_id = validate_branch_access(current_user, po.branch_id)
                currency = body.currency or po.currency or base_currency
                _body_rate = body.exchange_rate
                _po_rate = getattr(po, "exchange_rate", None)
                if _body_rate is not None:
                    exchange_rate = _dec(_body_rate)
                elif _po_rate is not None:
                    exchange_rate = _dec(_po_rate)
                else:
                    exchange_rate = Decimal("1")
            if exchange_rate <= 0:
                raise HTTPException(**http_error(400, "exchange_rate_must_be_positive", request))
    
            result = db.execute(text("""
                INSERT INTO landed_costs (
                    lc_number, purchase_order_id, grn_id, reference,
                    lc_date, total_amount, allocation_method, notes,
                    status, created_by, branch_id, currency, exchange_rate
                ) VALUES (
                    :num, :poid, :grnid, :ref, :dt, :total, :method,
                    :notes, 'draft', :uid, :branch_id, :currency, :exchange_rate
                ) RETURNING id
            """), {
                "num": lc_number, "poid": body.purchase_order_id,
                "grnid": body.grn_id, "ref": body.reference,
                "dt": body.lc_date or datetime.now().date().isoformat(),
                "total": total, "method": body.allocation_method,
                "notes": body.notes, "uid": user_id,
                "branch_id": branch_id, "currency": currency,
                "exchange_rate": exchange_rate,
            })
            lc_id = result.fetchone()[0]
    
            for item in body.cost_items:
                db.execute(text("""
                    INSERT INTO landed_cost_items (
                        landed_cost_id, cost_type, description, amount,
                        vendor_id, invoice_ref
                    ) VALUES (:lcid, :ct, :desc, :amt, :vid, :iref)
                """), {
                    "lcid": lc_id, "ct": item.cost_type,
                    "desc": item.description, "amt": item.amount,
                    "vid": item.vendor_id, "iref": item.invoice_ref
                })
    
    
            log_activity(db, user_id=user_id,
                         username=_u(current_user, "username"),
                         action="landed_cost.create",
                         resource_type="landed_cost",
                         resource_id=lc_number,
                         details={"id": lc_id, "total": str(total)},
                         request=request)
    
            return {"id": lc_id, "lc_number": lc_number, "total_amount": total}
        except HTTPException:
            raise
        except Exception:
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ─── ALLOCATE & POST ──────────────────────────────────────────────────────────

@router.post("/{lc_id}/allocate", dependencies=[Depends(require_permission("buying.create"))], response_model=Dict[str, Any])
def allocate_landed_cost(lc_id: int, request: Request, current_user: dict = Depends(get_current_user)):
    """
    توزيع التكاليف المُضافة على أصناف أمر الشراء / استلام البضاعة
    Allocation methods:
    - by_value: بحسب قيمة كل صنف
    - by_quantity: بحسب الكمية
    - by_weight: بحسب الوزن
    - equal: بالتساوي
    """
    company_id = _u(current_user, "company_id")
    user_id = _u(current_user, "user_id") or _u(current_user, "id")
    with transactional(company_id) as db:
        try:
            lc = db.execute(text("SELECT * FROM landed_costs WHERE id = :id"), {"id": lc_id}).fetchone()
            if not lc:
                raise HTTPException(**http_error(404, "landed_cost_not_found", request))
            if lc.status == 'posted':
                raise HTTPException(**http_error(400, "landed_cost_already_posted", request))
    
            total_cost = _dec(lc.total_amount)
            exchange_rate = _dec(getattr(lc, "exchange_rate", None) or 1)
            if exchange_rate <= 0:
                raise HTTPException(**http_error(400, "exchange_rate_must_be_positive", request))
            method = lc.allocation_method
    
            # Get purchase order lines
            po_id = lc.purchase_order_id
            grn_id = lc.grn_id
    
            if po_id:
                po_lines = db.execute(text("""
	                    SELECT pol.id as line_id, pol.product_id,
	                           COALESCE(SUM(prl.quantity), 0) as quantity,
	                           COALESCE(SUM(prl.total_cost) / NULLIF(SUM(prl.quantity), 0), p.cost_price, 0) AS unit_price,
	                           COALESCE(SUM(prl.total_cost), 0) as line_total,
	                           p.product_name, 0 as weight_kg,
	                           COALESCE(SUM(prl.total_cost) / NULLIF(SUM(prl.quantity), 0), p.cost_price, 0) AS cost_price
	                    FROM purchase_order_lines pol
	                    JOIN products p ON p.id = pol.product_id
	                    JOIN po_receipt_lines prl ON prl.po_line_id = pol.id
	                    WHERE pol.po_id = :poid
	                    GROUP BY pol.id, pol.product_id, p.product_name, p.cost_price
	                    HAVING COALESCE(SUM(prl.quantity), 0) > 0
                """), {"poid": po_id}).fetchall()
            elif grn_id:
                po_lines = db.execute(text("""
                    SELECT gl.id as line_id, gl.product_id, gl.received_quantity as quantity,
                           p.cost_price as unit_price,
                           (gl.received_quantity * p.cost_price) as line_total,
                           p.product_name, 0 as weight_kg, p.cost_price
                    FROM grn_lines gl
                    JOIN products p ON p.id = gl.product_id
                    WHERE gl.grn_id = :grnid
                """), {"grnid": grn_id}).fetchall()
            else:
                raise HTTPException(**http_error(400, "must_link_to_po_or_receipt", request))
    
            if not po_lines:
                raise HTTPException(**http_error(400, "no_items_to_allocate", request))
    
            # Calculate allocation basis
            if method == 'by_value':
                total_basis = sum((_dec(l.line_total or 0) for l in po_lines), Decimal('0'))
            elif method == 'by_quantity':
                total_basis = sum((_dec(l.quantity or 0) for l in po_lines), Decimal('0'))
            elif method == 'by_weight':
                total_basis = sum((_dec(l.weight_kg or 0) * _dec(l.quantity or 0) for l in po_lines), Decimal('0'))
            else:  # equal
                total_basis = _dec(len(po_lines))
    
            if total_basis <= 0:
                raise HTTPException(**http_error(400, "allocation_basis_zero", request))
    
            # Delete old allocations
            db.execute(text("DELETE FROM landed_cost_allocations WHERE landed_cost_id = :lcid"), {"lcid": lc_id})
    
            allocations_data = []
            allocation_entries = []
            for line in po_lines:
                if method == 'by_value':
                    basis = _dec(line.line_total or 0)
                elif method == 'by_quantity':
                    basis = _dec(line.quantity or 0)
                elif method == 'by_weight':
                    basis = _dec(line.weight_kg or 0) * _dec(line.quantity or 0)
                else:
                    basis = Decimal('1')
    
                share = (basis / total_basis) * total_cost
                qty = _dec(line.quantity or 1)
                per_unit = share / qty if qty > 0 else Decimal('0')
                new_cost = (_dec(line.cost_price or 0) + per_unit).quantize(_D4, ROUND_HALF_UP)
    
                allocation_entries.append({
                    "line": line,
                    "basis": basis,
                    "share_raw": share,
                    "share": share.quantize(_D2, ROUND_HALF_UP),
                    "new_cost": new_cost,
                })
    
            # Largest-remainder rounding: ensure allocations sum exactly to total_cost
            allocated_sum = sum(e["share"] for e in allocation_entries)
            remainder = total_cost.quantize(_D2, ROUND_HALF_UP) - allocated_sum
            if remainder != 0 and allocation_entries:
                largest_idx = max(range(len(allocation_entries)), key=lambda i: allocation_entries[i]["share"])
                allocation_entries[largest_idx]["share"] += remainder
                # Recalculate new_cost for the adjusted line
                adj = allocation_entries[largest_idx]
                adj_qty = _dec(adj["line"].quantity or 1)
                adj_per_unit = adj["share"] / adj_qty if adj_qty > 0 else Decimal('0')
                adj["new_cost"] = (_dec(adj["line"].cost_price or 0) + adj_per_unit).quantize(_D4, ROUND_HALF_UP)
    
            for entry in allocation_entries:
                line = entry["line"]
                db.execute(text("""
                    INSERT INTO landed_cost_allocations (
                        landed_cost_id, product_id, po_line_id,
                        original_cost, allocated_amount, new_cost,
                        allocation_basis, allocation_share
                    ) VALUES (:lcid, :pid, :lid, :oc, :aa, :nc, :ab, :ash)
                """), {
                    "lcid": lc_id, "pid": line.product_id,
                    "lid": line.line_id,
                    "oc": _dec(line.cost_price or 0).quantize(_D4, ROUND_HALF_UP),
                    "aa": entry["share"],
                    "nc": entry["new_cost"],
                    "ab": entry["basis"].quantize(_D4, ROUND_HALF_UP),
                    "ash": (entry["basis"] / total_basis).quantize(_D6, ROUND_HALF_UP)
                })
    
                allocations_data.append({
                    "product_id": line.product_id,
                    "allocated": str(entry["share"]),
                    "new_cost": str(entry["new_cost"])
                })
    
    
            log_activity(db, user_id=user_id,
                         username=_u(current_user, "username"),
                         action="landed_cost.allocate",
                         resource_type="landed_cost",
                         resource_id=str(lc_id),
                         details={"method": method, "total_cost": str(total_cost.quantize(_D2, ROUND_HALF_UP))},
                         request=request)
    
            return {
                "message": i18n_message("landed_cost_distributed_method", request, total=str(total_cost.quantize(_D2, ROUND_HALF_UP)), method=method),
                "allocations": allocations_data
            }
        except HTTPException:
            raise
        except Exception:
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/{lc_id}/post", dependencies=[Depends(require_permission("buying.create"))], response_model=Dict[str, Any])
def post_landed_cost(lc_id: int, request: Request, current_user: dict = Depends(get_current_user)):
    """
    ترحيل التكاليف المُضافة — تحديث تكلفة المنتجات + قيد محاسبي
    JE: Dr: Inventory (landed costs) → Cr: AP or Expense
    """
    company_id = _u(current_user, "company_id")
    user_id = _u(current_user, "user_id") or _u(current_user, "id")
    with transactional(company_id) as db:
        try:
            lc = db.execute(text("SELECT * FROM landed_costs WHERE id = :id FOR UPDATE"), {"id": lc_id}).fetchone()
            if not lc:
                raise HTTPException(**http_error(404, "landed_cost_not_found", request))
            if lc.status == 'posted':
                raise HTTPException(**http_error(400, "landed_cost_already_posted", request))
            branch_id = validate_branch_access(current_user, lc.branch_id)
            if not branch_id:
                raise HTTPException(**http_error(400, "landed_cost_branch_required", request))
    
            # Fiscal period check
            post_date = str(lc.lc_date or datetime.now().date())
            check_fiscal_period_open(db, post_date)
    
            allocations = db.execute(text(
                "SELECT * FROM landed_cost_allocations WHERE landed_cost_id = :lcid"
            ), {"lcid": lc_id}).fetchall()
    
            if not allocations:
                raise HTTPException(**http_error(400, "landed_costs_not_allocated", request))
            _lc_rate = getattr(lc, "exchange_rate", None)
            exchange_rate = _dec(1 if _lc_rate is None else _lc_rate)
            if exchange_rate <= 0:
                raise HTTPException(**http_error(400, "exchange_rate_must_be_positive", request))
    
            # T032: Update costs through CostingService instead of direct column updates
            # F-31: track the inventory debit broken down by warehouse so the
            # journal entry hits the correct per-warehouse inventory accounts.
            from services.costing_service import CostingService
            from utils.inventory_accounts import resolve_warehouse_inventory_account
            warehouse_debit_base: Dict[int, Decimal] = {}
            for alloc in allocations:
                wh_rows = db.execute(text("""
                    SELECT warehouse_id, COALESCE(SUM(quantity), 0) AS received_qty
                    FROM po_receipt_lines
                    WHERE po_line_id = :po_line_id
                      AND product_id = :pid
                    GROUP BY warehouse_id
                    ORDER BY warehouse_id
                """), {"po_line_id": alloc.po_line_id, "pid": alloc.product_id}).fetchall()
                received_total = sum((_dec(row.received_qty) for row in wh_rows), Decimal("0"))
                allocated_remaining = _dec(alloc.allocated_amount)
                for idx, wh_row in enumerate(wh_rows):
                    wh_qty = _dec(wh_row.received_qty)
                    if wh_qty <= 0 or received_total <= 0:
                        continue
                    wh_amount = allocated_remaining if idx == len(wh_rows) - 1 else (_dec(alloc.allocated_amount) * wh_qty / received_total).quantize(_D2, ROUND_HALF_UP)
                    allocated_remaining -= wh_amount
                    base_amount = (wh_amount * exchange_rate).quantize(_D2, ROUND_HALF_UP)
                    CostingService.apply_landed_cost_adjustment(
                        db,
                        product_id=alloc.product_id,
                        warehouse_id=wh_row.warehouse_id,
                        quantity=wh_qty,
                        allocated_amount=base_amount,
                        po_line_id=alloc.po_line_id,
                    )
                    warehouse_debit_base[wh_row.warehouse_id] = (
                        warehouse_debit_base.get(wh_row.warehouse_id, Decimal("0")) + wh_amount
                    )
    
            # Build GL journal entry lines via GL service
            total_cost = _dec(lc.total_amount)
            lc_currency = lc.currency or get_base_currency(db)
    
            je_lines = []
    
            # Dr: Inventory — split per warehouse using each warehouse's
            # mapped inventory account (F-31). When all warehouses fall back
            # to the same global account this collapses to the legacy single
            # debit line.
            if warehouse_debit_base:
                for wh_id, wh_amount in warehouse_debit_base.items():
                    if wh_amount <= 0:
                        continue
                    wh_inv_acc = resolve_warehouse_inventory_account(db, wh_id)
                    if not wh_inv_acc:
                        raise HTTPException(**http_error(400, "inventory_account_not_configured", request))
                    je_lines.append({
                        "account_id": wh_inv_acc,
                        "debit": wh_amount,
                        "credit": 0,
                        "description": f"تكاليف مُضافة - مخزون (WH#{wh_id})",
                        "amount_currency": wh_amount,
                        "currency": lc_currency,
                    })
            else:
                # Defensive fallback: nothing was allocated to a warehouse but
                # we still need a balanced entry. Use the global mapping.
                inv_account = get_mapped_account_id(db, "acc_map_inventory")
                if inv_account:
                    je_lines.append({
                        "account_id": inv_account,
                        "debit": total_cost,
                        "credit": 0,
                        "description": "تكاليف مُضافة - مخزون",
                        "amount_currency": total_cost,
                        "currency": lc_currency,
                    })
    
            # Cr: Per cost type (group by vendor or expense type)
            cost_items = db.execute(text(
                "SELECT * FROM landed_cost_items WHERE landed_cost_id = :lcid"
            ), {"lcid": lc_id}).fetchall()
    
            for item in cost_items:
                if item.vendor_id:
                    ap_account = get_mapped_account_id(db, "acc_map_ap")
                    if ap_account:
                        je_lines.append({
                            "account_id": ap_account,
                            "debit": 0,
                            "credit": _dec(item.amount),
                            "description": f"{item.cost_type}: {item.description or ''}",
                            "amount_currency": _dec(item.amount),
                            "currency": lc_currency,
                        })
    
                    # T034: Update party_site_balances for vendor-issued landed costs
                    from utils.party_balance import update_party_site_balance
                    update_party_site_balance(
                        db, party_id=item.vendor_id,
                        branch_id=branch_id,
                        currency=lc_currency,
                        amount=-_dec(item.amount),
                        document_type="landed_cost"
                    )
                else:
                    acc_key = {
                        "freight": "acc_map_freight",
                        "customs": "acc_map_customs",
                        "insurance": "acc_map_landed_costs",
                        "handling": "acc_map_landed_costs",
                    }.get(item.cost_type, "acc_map_landed_costs")
                    exp_account = get_mapped_account_id(db, acc_key)
                    if exp_account:
                        je_lines.append({
                            "account_id": exp_account,
                            "debit": 0,
                            "credit": _dec(item.amount),
                            "description": f"{item.cost_type}: {item.description or ''}",
                            "amount_currency": _dec(item.amount),
                            "currency": lc_currency,
                        })
    
            # Create JE via GL service (validates balance, sequential numbering, closed period)
            je_id, _ = gl_create_journal_entry(
                db=db,
                company_id=company_id,
                date=post_date,
                description=f"تكاليف مُضافة {lc.lc_number}",
                reference=lc.lc_number,
                lines=je_lines,
                user_id=user_id,
                currency=lc_currency,
                exchange_rate=exchange_rate,
                source="landed_cost",
                source_id=lc_id
            )
    
            # Update LC status
            db.execute(text("""
                UPDATE landed_costs SET status = 'posted', journal_entry_id = :jeid
                WHERE id = :id
            """), {"jeid": je_id, "id": lc_id})
    
    
            log_activity(db, user_id=user_id,
                         username=_u(current_user, "username"),
                         action="landed_cost.post",
                         resource_type="landed_cost",
                         resource_id=str(lc_id),
                         details={"journal_entry_id": je_id, "total": str(total_cost.quantize(_D2, ROUND_HALF_UP))},
                         request=request)
    
            return {
                "message": i18n_message("landed_costs_posted_success", request),
                "journal_entry_id": je_id,
                "total_allocated": str(total_cost.quantize(_D2, ROUND_HALF_UP))
            }
        except HTTPException:
            raise
        except Exception:
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
