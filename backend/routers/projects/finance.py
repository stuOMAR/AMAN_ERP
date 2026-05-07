"""projects sub-router — split from monolithic projects.py (T6.3).

Mounted under the parent router via projects/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request, File, UploadFile
from utils.i18n import http_error, i18n_message
import os
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import require_permission, validate_branch_access, validate_treasury_account_access, require_module
from utils.accounting import (
    generate_sequential_number, get_mapped_account_id,
    get_base_currency, compute_line_amounts, compute_invoice_totals
)
from utils.audit import log_activity
from utils.fiscal_lock import check_fiscal_period_open
from sqlalchemy import text
from services.gl_service import create_journal_entry as gl_create_journal_entry
import logging

logger = logging.getLogger(__name__)

_D2 = Decimal('0.01')
_D4 = Decimal('0.0001')
def _dec(v) -> Decimal:
    return Decimal(str(v)) if v is not None else Decimal('0')

from schemas.projects import (
    ProjectCreate, ProjectUpdate, TaskCreate, TaskUpdate,
    ProjectExpenseCreate, ProjectRevenueCreate,
    TimesheetCreate, TimesheetUpdate, TimesheetApprove,
    ProjectInvoiceCreate, ChangeOrderCreate, ChangeOrderUpdate, ProjectCloseRequest,
    ProjectRiskCreate, ProjectRiskUpdate, TaskDependencyCreate
)
from schemas.timetracking import (
    TimesheetEntryCreate, TimesheetEntryUpdate,
    WeeklySubmitRequest, RejectRequest
)
from schemas.resource import AllocationCreate, AllocationUpdate

router = APIRouter()

from .core import _D2, _D4, _dec

@router.post("/retainer/generate-invoices", dependencies=[Depends(require_permission("projects.edit"))], response_model=Dict[str, Any])
async def generate_retainer_invoices(
    request: Request,
    billing_date: Optional[date] = None,
    current_user: dict = Depends(get_current_user)
):
    """
    توليد فواتير دورية تلقائية لعقود Retainer المستحقة.
    Generate automatic periodic invoices for due Retainer contracts.
    Creates invoice + GL entry (Dr AR / Cr Revenue) for each project.
    """
    db = get_db_connection(current_user.company_id)
    try:
        target_date = billing_date or date.today()
        
        # Find retainer projects due for billing
        projects = db.execute(text("""
            SELECT p.*, 
                   COALESCE(c.name, pa.name, '') as customer_name,
                   COALESCE(p.customer_id, p.party_id) as bill_to_id
            FROM projects p
            LEFT JOIN customers c ON p.customer_id = c.id
            LEFT JOIN parties pa ON p.party_id = pa.id
            WHERE p.contract_type = 'retainer'
              AND p.retainer_amount > 0
              AND p.status NOT IN ('completed', 'cancelled')
              AND (p.next_billing_date IS NULL OR p.next_billing_date <= :target)
        """), {"target": target_date}).fetchall()
        
        if not projects:
            return {"success": True, "generated": 0, "message": i18n_message("no_contracts_due_for_billing")}
        
        base_currency = get_base_currency(db)
        ar_acc = get_mapped_account_id(db, "acc_map_ar")
        rev_acc = get_mapped_account_id(db, "acc_map_sales_rev") or get_mapped_account_id(db, "acc_map_project_revenue")

        # Enforce fiscal period lock before auto-billing GL posting
        check_fiscal_period_open(db, target_date)

        generated = []
        
        for proj in projects:
            p = proj._mapping
            amount = _dec(p["retainer_amount"])
            if amount <= 0:
                continue
            
            # Generate invoice
            inv_num = generate_sequential_number(db, f"RET-{target_date.year}", "invoices", "invoice_number")
            bill_to = p.get("bill_to_id") or p.get("customer_id")
            
            inv_id = db.execute(text("""
                INSERT INTO invoices (
                    invoice_number, party_id, invoice_type, invoice_date, due_date,
                    subtotal, tax_amount, discount, total, paid_amount, status, notes,
                    payment_method, created_by, branch_id, currency, exchange_rate
                ) VALUES (
                    :num, :cust, 'sales', :inv_date, :due_date,
                    :amt, 0, 0, :amt, 0, 'unpaid',
                    :notes, 'credit', :uid, :branch, :curr, 1.0
                ) RETURNING id
            """), {
                "num": inv_num, "cust": bill_to,
                "inv_date": target_date,
                "due_date": target_date + timedelta(days=30),
                "amt": amount,
                "notes": f"فاتورة دورية (Retainer) — مشروع: {p['project_name']}",
                "uid": current_user.id, "branch": p.get("branch_id"),
                "curr": base_currency
            }).scalar()
            
            # Invoice line
            db.execute(text("""
                INSERT INTO invoice_lines (invoice_id, description, quantity, unit_price, tax_rate, discount, total)
                VALUES (:inv_id, :desc, 1, :price, 0, 0, :total)
            """), {
                "inv_id": inv_id, "desc": f"رسوم اشتراك — مشروع {p['project_name']}",
                "price": amount, "total": amount
            })
            
            # Link to project revenues
            db.execute(text("""
                INSERT INTO project_revenues (project_id, revenue_type, revenue_date, amount, description, invoice_id, status, created_by)
                VALUES (:pid, 'retainer', :date, :amt, :desc, :inv_id, 'approved', :uid)
            """), {
                "pid": p["id"], "date": target_date, "amt": amount,
                "desc": f"فاتورة Retainer #{inv_num}", "inv_id": inv_id, "uid": current_user.id
            })
            
            # GL Entry: Dr AR / Cr Revenue
            je_id = None
            if ar_acc and rev_acc:
                cost_center_id = db.execute(text(
                    "SELECT id FROM cost_centers WHERE center_name ILIKE :name LIMIT 1"
                ), {"name": f"%{p['project_name']}%"}).scalar()

                je_id, entry_num = gl_create_journal_entry(
                    db=db,
                    company_id=current_user.get("company_id") if isinstance(current_user, dict) else current_user.company_id,
                    date=target_date,
                    description=f"فاتورة Retainer — {p['project_name']} — {inv_num}",
                    status="posted",
                    currency=base_currency,
                    exchange_rate=Decimal("1"),
                    lines=[
                        {
                            "account_id": ar_acc, "debit": amount, "credit": 0,
                            "description": f"ذمم مدينة — Retainer {p['project_name']}", "cost_center_id": cost_center_id
                        },
                        {
                            "account_id": rev_acc, "debit": 0, "credit": amount,
                            "description": f"إيراد Retainer {p['project_name']}", "cost_center_id": cost_center_id
                        }
                    ],
                    user_id=current_user.get("id") if isinstance(current_user, dict) else current_user.id,
                    source="project_invoice",
                    source_id=inv_id
                )
            
            # Calculate next billing date
            cycle = p.get("billing_cycle", "monthly")
            if cycle == "monthly":
                next_date = target_date + timedelta(days=30)
            elif cycle == "quarterly":
                next_date = target_date + timedelta(days=90)
            elif cycle == "yearly":
                next_date = target_date + timedelta(days=365)
            else:
                next_date = target_date + timedelta(days=30)
            
            db.execute(text("""
                UPDATE projects SET last_billed_date = :billed, next_billing_date = :next, updated_at = NOW()
                WHERE id = :id
            """), {"billed": target_date, "next": next_date, "id": p["id"]})
            
            generated.append({
                "project_id": p["id"], "project_name": p["project_name"],
                "invoice_id": inv_id, "invoice_number": inv_num,
                "amount": amount, "journal_entry_id": je_id
            })
        
        db.commit()
        log_activity(db, user_id=current_user.id, username=current_user.username, action="generate_retainer_invoices", resource_type="project_invoice", resource_id=None, details={"generated_count": len(generated)})
        
        return {
            "success": True,
            "generated": len(generated),
            "invoices": generated,
            "message": i18n_message("retainer_invoices_created_count_success", count=len(generated))
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error generating retainer invoices: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()

# ═══════════════════════════════════════════════════════════

@router.post("/{project_id}/expenses", status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("projects.edit"))], response_model=Dict[str, Any])
async def create_project_expense(
    project_id: int,
    expense: ProjectExpenseCreate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """
    تسجيل مصروف على المشروع مع قيد محاسبي تلقائي:
    مدين: حساب المصاريف | دائن: حساب النقدية/الخزينة
    """
    db = get_db_connection(current_user.company_id)
    try:
        project = db.execute(text("SELECT * FROM projects WHERE id = :id"), {"id": project_id}).fetchone()
        if not project:
            raise HTTPException(**http_error(404, "project_not_found"))
        branch_id = validate_branch_access(current_user, project._mapping.get('branch_id'))

        base_currency = get_base_currency(db)
        amount = _dec(expense.amount).quantize(_D2, ROUND_HALF_UP)

        # Fiscal period check before GL entry
        check_fiscal_period_open(db, expense.expense_date)

        # Determine expense account
        expense_acc = expense.expense_account_id
        if not expense_acc:
            type_map = {"materials": "acc_map_inventory", "labor": "acc_map_salaries_exp"}
            mapping_key = type_map.get(expense.expense_type)
            if mapping_key:
                expense_acc = get_mapped_account_id(db, mapping_key)
            if not expense_acc:
                expense_acc = db.execute(text(
                    "SELECT id FROM accounts WHERE account_code = 'OP-EXP' LIMIT 1"
                )).scalar()
            if not expense_acc:
                expense_acc = db.execute(text(
                    "SELECT id FROM accounts WHERE account_type = 'expense' LIMIT 1"
                )).scalar()

        if not expense_acc:
            raise HTTPException(status_code=400, detail=i18n_message("expense_account_not_found"))

        # Cash/treasury account
        cash_acc = None
        selected_treasury = None
        if expense.treasury_id:
            selected_treasury = validate_treasury_account_access(db, current_user, expense.treasury_id, branch_id)
            cash_acc = selected_treasury.get("gl_account_id")
        if not cash_acc:
            cash_acc = get_mapped_account_id(db, "acc_map_cash_main")
        if not cash_acc:
            raise HTTPException(status_code=400, detail=i18n_message("cash_account_not_found"))

        # 1. Record project expense
        exp_id = db.execute(text("""
            INSERT INTO project_expenses (
                project_id, expense_type, expense_date, amount,
                description, status, created_by
            ) VALUES (:pid, :type, :date, :amt, :desc, 'approved', :uid)
            RETURNING id
        """), {
            "pid": project_id, "type": expense.expense_type,
            "date": expense.expense_date, "amt": amount,
            "desc": expense.description, "uid": current_user.id
        }).scalar()

        # 2. Journal Entry
        cost_center_id = db.execute(text(
            "SELECT id FROM cost_centers WHERE center_name ILIKE :name LIMIT 1"
        ), {"name": f"%{project._mapping['project_name']}%"}).scalar()
        
        je_id, _ = gl_create_journal_entry(
            db=db,
            company_id=current_user.company_id,
            date=expense.expense_date.isoformat() if hasattr(expense.expense_date, 'isoformat') else str(expense.expense_date),
            description=f"مصروف مشروع: {project._mapping['project_name']} - {expense.description or expense.expense_type}",
            reference=None,
            status="posted",
            currency=base_currency,
            exchange_rate=Decimal('1'),
            lines=[
                {
                    "account_id": expense_acc,
                    "debit": amount,
                    "credit": 0,
                    "description": expense.description or expense.expense_type,
                    "cost_center_id": cost_center_id
                },
                {
                    "account_id": cash_acc,
                    "debit": 0,
                    "credit": amount,
                    "description": expense.description or expense.expense_type,
                    "cost_center_id": cost_center_id
                }
            ],
            user_id=current_user.id,
            branch_id=branch_id,
            source="project_expense",
            source_id=exp_id
        )

        if expense.treasury_id:
            from utils.treasury_balance import recalc_treasury_from_gl
            recalc_treasury_from_gl(db, expense.treasury_id)

        # 4. Update project actual cost
        db.execute(text("""
            UPDATE projects SET actual_cost = COALESCE(actual_cost, 0) + :amt, updated_at = NOW()
            WHERE id = :pid
        """), {"amt": amount, "pid": project_id})

        db.commit()

        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="project.expense", resource_type="project_expense",
            resource_id=str(exp_id),
            details={"project_id": project_id, "amount": float(amount), "type": expense.expense_type},
            request=request
        )

        return {"success": True, "id": exp_id, "journal_entry_id": je_id,
                "message": i18n_message("project_expense_recorded_with_je")}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating project expense: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.get("/{project_id}/expenses", dependencies=[Depends(require_permission("projects.view"))], response_model=List[Dict[str, Any]])
async def get_project_expenses(project_id: int, current_user: dict = Depends(get_current_user)):
    """جلب مصاريف المشروع"""
    db = get_db_connection(current_user.company_id)
    try:
        result = db.execute(text("""
            SELECT pe.*, COALESCE(u.full_name, '') as created_by_name
            FROM project_expenses pe
            LEFT JOIN company_users u ON pe.created_by = u.id
            WHERE pe.project_id = :pid
            ORDER BY pe.expense_date DESC
        """), {"pid": project_id}).fetchall()
        return [dict(r._mapping) for r in result]
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# Project Revenues (مع ربط محاسبي)
# ═══════════════════════════════════════════════════════════

@router.post("/{project_id}/revenues", status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("projects.edit"))], response_model=Dict[str, Any])
async def create_project_revenue(
    project_id: int,
    revenue: ProjectRevenueCreate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """
    تسجيل إيراد على المشروع مع قيد محاسبي:
    مدين: العملاء أو النقدية | دائن: الإيرادات
    """
    db = get_db_connection(current_user.company_id)
    try:
        project = db.execute(text("SELECT * FROM projects WHERE id = :id"), {"id": project_id}).fetchone()
        if not project:
            raise HTTPException(**http_error(404, "project_not_found"))

        base_currency = get_base_currency(db)
        amount = _dec(revenue.amount).quantize(_D2, ROUND_HALF_UP)

        # Fiscal period check before GL entry
        check_fiscal_period_open(db, revenue.revenue_date)

        # Revenue account
        revenue_acc = get_mapped_account_id(db, "acc_map_sales_rev")
        if not revenue_acc:
            revenue_acc = db.execute(text(
                "SELECT id FROM accounts WHERE account_type = 'revenue' LIMIT 1"
            )).scalar()
        if not revenue_acc:
            raise HTTPException(status_code=400, detail=i18n_message("revenue_account_not_found"))

        # Debit account
        debit_acc = None
        if project._mapping.get("customer_id"):
            debit_acc = get_mapped_account_id(db, "acc_map_ar")
        if not debit_acc:
            debit_acc = get_mapped_account_id(db, "acc_map_cash_main")
        if not debit_acc:
            raise HTTPException(status_code=400, detail=i18n_message("debit_account_not_found"))

        # 1. Record revenue
        rev_id = db.execute(text("""
            INSERT INTO project_revenues (
                project_id, revenue_type, revenue_date, amount,
                description, invoice_id, status, created_by
            ) VALUES (:pid, :type, :date, :amt, :desc, :inv, 'approved', :uid)
            RETURNING id
        """), {
            "pid": project_id, "type": revenue.revenue_type,
            "date": revenue.revenue_date, "amt": amount,
            "desc": revenue.description, "inv": revenue.invoice_id,
            "uid": current_user.id
        }).scalar()

        # 2. Journal Entry
        cost_center_id = db.execute(text(
            "SELECT id FROM cost_centers WHERE center_name ILIKE :name LIMIT 1"
        ), {"name": f"%{project._mapping['project_name']}%"}).scalar()

        je_id, _ = gl_create_journal_entry(
            db=db,
            company_id=current_user.company_id,
            date=revenue.revenue_date.isoformat() if hasattr(revenue.revenue_date, 'isoformat') else str(revenue.revenue_date),
            description=f"إيراد مشروع: {project._mapping['project_name']} - {revenue.description or revenue.revenue_type}",
            reference=None,
            status="posted",
            currency=base_currency,
            exchange_rate=Decimal("1"),
            lines=[
                {
                    "account_id": debit_acc,
                    "debit": amount,
                    "credit": 0,
                    "description": revenue.description or revenue.revenue_type,
                    "cost_center_id": cost_center_id
                },
                {
                    "account_id": revenue_acc,
                    "debit": 0,
                    "credit": amount,
                    "description": revenue.description or revenue.revenue_type,
                    "cost_center_id": cost_center_id
                }
            ],
            user_id=current_user.id,
            branch_id=project._mapping.get('branch_id'),
            source="project_revenue",
            source_id=rev_id
        )

        db.commit()

        log_activity(
            db, user_id=current_user.id, username=current_user.username,
            action="project.revenue", resource_type="project_revenue",
            resource_id=str(rev_id),
            details={"project_id": project_id, "amount": amount, "type": revenue.revenue_type},
            request=request
        )

        return {"success": True, "id": rev_id, "journal_entry_id": je_id,
                "message": i18n_message("project_revenue_recorded_with_je")}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating project revenue: {e}")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.get("/{project_id}/revenues", dependencies=[Depends(require_permission("projects.view"))], response_model=List[Dict[str, Any]])
async def get_project_revenues(project_id: int, current_user: dict = Depends(get_current_user)):
    """جلب إيرادات المشروع"""
    db = get_db_connection(current_user.company_id)
    try:
        result = db.execute(text("""
            SELECT pr.*, COALESCE(u.full_name, '') as created_by_name
            FROM project_revenues pr
            LEFT JOIN company_users u ON pr.created_by = u.id
            WHERE pr.project_id = :pid
            ORDER BY pr.revenue_date DESC
        """), {"pid": project_id}).fetchall()
        return [dict(r._mapping) for r in result]
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════
# Project Financial Report
# ═══════════════════════════════════════════════════════════

