"""
AMAN ERP — Landed Costs Router
التكاليف المُضافة (الشحن، الجمارك، التأمين) وتوزيعها على أصناف الشراء
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Any, Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel
from decimal import Decimal, ROUND_HALF_UP
import logging

from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import require_permission, require_module, validate_branch_access
from utils.audit import log_activity
from utils.accounting import (
    generate_sequential_number, get_mapped_account_id,
    get_base_currency
)
from utils.fiscal_lock import check_fiscal_period_open
from services.gl_service import create_journal_entry as gl_create_journal_entry

router = APIRouter(prefix="/purchases/landed-costs", tags=["Landed Costs"], dependencies=[Depends(require_module("landed_costs"))])
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
    amount: float = 0
    vendor_id: Optional[int] = None
    invoice_ref: Optional[str] = None

class LandedCostCreate(BaseModel):
    purchase_order_id: Optional[int] = None
    grn_id: Optional[int] = None
    reference: Optional[str] = None
    lc_date: Optional[str] = None
    allocation_method: str = "by_value"  # by_value, by_quantity, by_weight, equal
    notes: Optional[str] = None
    cost_items: List[LandedCostItemCreate] = []


# ─── LIST ──────────────────────────────────────────────────────────────────────

@router.get("", dependencies=[Depends(require_permission("purchases.view"))], response_model=List[Dict[str, Any]])
def list_landed_costs(
    status_filter: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    company_id = _u(current_user, "company_id")
    with transactional(company_id) as db:
        # Branch access enforcement
        allowed = _u(current_user, "allowed_branches") or []

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
        if allowed:
            query += " AND (lc.branch_id = ANY(:branches) OR lc.branch_id IS NULL)"
            params["branches"] = allowed

        query += " ORDER BY lc.id DESC"
        rows = db.execute(text(query), params).fetchall()
        return [dict(r._mapping) for r in rows]


# ─── GET ONE ───────────────────────────────────────────────────────────────────

@router.get("/{lc_id}", dependencies=[Depends(require_permission("purchases.view"))], response_model=Dict[str, Any])
def get_landed_cost(lc_id: int, current_user: dict = Depends(get_current_user)):
    company_id = _u(current_user, "company_id")
    with transactional(company_id) as db:
        lc = db.execute(text("""
            SELECT lc.*, po.po_number
            FROM landed_costs lc
            LEFT JOIN purchase_orders po ON po.id = lc.purchase_order_id
            WHERE lc.id = :id
        """), {"id": lc_id}).fetchone()
        if not lc:
            raise HTTPException(404, "التكلفة المُضافة غير موجودة")

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

@router.post("", status_code=201, dependencies=[Depends(require_permission("purchases.create"))], response_model=Dict[str, Any])
def create_landed_cost(body: LandedCostCreate, request: Request, current_user: dict = Depends(get_current_user)):
    company_id = _u(current_user, "company_id")
    user_id = _u(current_user, "user_id")
    with transactional(company_id) as db:
        try:
            if not body.cost_items:
                raise HTTPException(400, "يجب إضافة عنصر تكلفة واحد على الأقل")
    
            year = datetime.now().year
            lc_number = generate_sequential_number(db, f"LC-{year}", "landed_costs", "lc_number")
            total = sum((_dec(item.amount) for item in body.cost_items), Decimal('0'))
    
            result = db.execute(text("""
                INSERT INTO landed_costs (
                    lc_number, purchase_order_id, grn_id, reference,
                    lc_date, total_amount, allocation_method, notes,
                    status, created_by
                ) VALUES (
                    :num, :poid, :grnid, :ref, :dt, :total, :method,
                    :notes, 'draft', :uid
                ) RETURNING id
            """), {
                "num": lc_number, "poid": body.purchase_order_id,
                "grnid": body.grn_id, "ref": body.reference,
                "dt": body.lc_date or datetime.now().date().isoformat(),
                "total": total, "method": body.allocation_method,
                "notes": body.notes, "uid": user_id
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
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ─── ALLOCATE & POST ──────────────────────────────────────────────────────────

@router.post("/{lc_id}/allocate", dependencies=[Depends(require_permission("purchases.create"))], response_model=Dict[str, Any])
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
    user_id = _u(current_user, "user_id")
    with transactional(company_id) as db:
        try:
            lc = db.execute(text("SELECT * FROM landed_costs WHERE id = :id"), {"id": lc_id}).fetchone()
            if not lc:
                raise HTTPException(404, "التكلفة المُضافة غير موجودة")
            if lc.status == 'posted':
                raise HTTPException(400, "تم ترحيل هذه التكلفة بالفعل")
    
            total_cost = _dec(lc.total_amount)
            method = lc.allocation_method
    
            # Get purchase order lines
            po_id = lc.purchase_order_id
            grn_id = lc.grn_id
    
            if po_id:
                po_lines = db.execute(text("""
                    SELECT pol.id as line_id, pol.product_id, pol.quantity,
                           pol.unit_price, pol.line_total,
                           p.product_name, p.weight_kg, p.cost_price
                    FROM purchase_order_lines pol
                    JOIN products p ON p.id = pol.product_id
                    WHERE pol.po_id = :poid
                """), {"poid": po_id}).fetchall()
            elif grn_id:
                po_lines = db.execute(text("""
                    SELECT gl.id as line_id, gl.product_id, gl.received_quantity as quantity,
                           p.cost_price as unit_price,
                           (gl.received_quantity * p.cost_price) as line_total,
                           p.product_name, p.weight_kg, p.cost_price
                    FROM grn_lines gl
                    JOIN products p ON p.id = gl.product_id
                    WHERE gl.grn_id = :grnid
                """), {"grnid": grn_id}).fetchall()
            else:
                raise HTTPException(400, "يجب ربط التكلفة بأمر شراء أو وثيقة استلام")
    
            if not po_lines:
                raise HTTPException(400, "لا توجد أصناف لتوزيع التكاليف عليها")
    
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
                raise HTTPException(400, "لا يمكن التوزيع: الأساس صفر")
    
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
                "message": f"تم توزيع {total_cost.quantize(_D2, ROUND_HALF_UP)} {method}",
                "allocations": allocations_data
            }
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/{lc_id}/post", dependencies=[Depends(require_permission("purchases.create"))], response_model=Dict[str, Any])
def post_landed_cost(lc_id: int, request: Request, current_user: dict = Depends(get_current_user)):
    """
    ترحيل التكاليف المُضافة — تحديث تكلفة المنتجات + قيد محاسبي
    JE: Dr: Inventory (landed costs) → Cr: AP or Expense
    """
    company_id = _u(current_user, "company_id")
    user_id = _u(current_user, "user_id") or _u(current_user, "id")
    with transactional(company_id) as db:
        try:
            lc = db.execute(text("SELECT * FROM landed_costs WHERE id = :id"), {"id": lc_id}).fetchone()
            if not lc:
                raise HTTPException(404, "التكلفة المُضافة غير موجودة")
            if lc.status == 'posted':
                raise HTTPException(400, "تم ترحيل هذه التكلفة بالفعل")
    
            # Fiscal period check
            post_date = str(lc.lc_date or datetime.now().date())
            check_fiscal_period_open(db, post_date)
    
            allocations = db.execute(text(
                "SELECT * FROM landed_cost_allocations WHERE landed_cost_id = :lcid"
            ), {"lcid": lc_id}).fetchall()
    
            if not allocations:
                raise HTTPException(400, "يجب توزيع التكاليف أولاً")
    
            # Update product cost_price and inventory average_cost
            for alloc in allocations:
                db.execute(text("""
                    UPDATE products SET cost_price = :new_cost, updated_at = CURRENT_TIMESTAMP
                    WHERE id = :pid
                """), {"new_cost": _dec(alloc.new_cost), "pid": alloc.product_id})
    
                db.execute(text("""
                    UPDATE inventory SET average_cost = :new_cost
                    WHERE product_id = :pid
                """), {"new_cost": _dec(alloc.new_cost), "pid": alloc.product_id})
    
            # Build GL journal entry lines via GL service
            total_cost = _dec(lc.total_amount)
            base_currency = get_base_currency(db)
    
            je_lines = []
    
            # Dr: Inventory
            inv_account = get_mapped_account_id(db, "acc_map_inventory")
            if inv_account:
                je_lines.append({
                    "account_id": inv_account,
                    "debit": total_cost,
                    "credit": 0,
                    "description": "تكاليف مُضافة - مخزون"
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
                            "description": f"{item.cost_type}: {item.description or ''}"
                        })
    
                    # Party transaction
                    db.execute(text("""
                        INSERT INTO party_transactions (
                            party_id, transaction_type, debit, credit, balance,
                            reference_type, reference_id, description, created_by
                        ) VALUES (:pid, 'landed_cost', 0, :amt, -:amt, 'landed_cost', :lcid, :desc, :uid)
                    """), {
                        "pid": item.vendor_id, "amt": _dec(item.amount),
                        "lcid": lc_id, "desc": f"تكلفة مُضافة: {item.cost_type}",
                        "uid": user_id
                    })
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
                            "description": f"{item.cost_type}: {item.description or ''}"
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
                currency=base_currency,
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
                "message": "تم ترحيل التكاليف المُضافة وتحديث تكلفة المنتجات",
                "journal_entry_id": je_id,
                "total_allocated": str(total_cost.quantize(_D2, ROUND_HALF_UP))
            }
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))
