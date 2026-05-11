"""
AMAN ERP - Expenses Module
وحدة إدارة المصاريف - مع نظام اعتماد وربط محاسبي كامل
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from utils.i18n import http_error
from typing import Any, Dict, List, Optional
from datetime import date
from decimal import Decimal
from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from sqlalchemy import text
from utils.permissions import branch_scope_filter_from_scope, require_permission, resolve_branch_scope, validate_branch_access, validate_treasury_account_access, require_module
from utils.accounting import (
    generate_sequential_number, get_mapped_account_id,
    get_base_currency
)
from utils.audit import log_activity
from utils.fiscal_lock import check_fiscal_period_open
import logging

logger = logging.getLogger(__name__)

from schemas.expenses import ExpenseCreate, ExpenseUpdate, ExpenseApproval, ExpensePolicyCreate, ExpensePolicyUpdate, ExpenseValidation

router = APIRouter(prefix="/expenses", tags=["Expenses"], dependencies=[Depends(require_module("expenses"))])

EXPENSE_TYPES = [
    "travel", "meals", "supplies", "transportation", "entertainment",
    "materials", "labor", "services", "rent", "utilities", "salaries", "other"
]

VALID_APPROVAL_STATUSES = ["pending", "approved", "rejected", "submitted", "reversed"]


# ═══════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════

def get_expense_account_by_type(db, expense_type: str) -> Optional[int]:
    """تحديد حساب المصروف بناءً على النوع"""
    type_map = {
        "rent": "acc_map_rent_expense",
        "utilities": "acc_map_utilities_expense",
        "salaries": "acc_map_salaries",
        "materials": "acc_map_inventory",
        "travel": "acc_map_travel_expense",
    }
    
    mapped_key = type_map.get(expense_type)
    if mapped_key:
        acc_id = get_mapped_account_id(db, mapped_key)
        if acc_id:
            return acc_id
    
    # Fallback: general expense
    acc_id = get_mapped_account_id(db, "acc_map_general_expense")
    if acc_id:
        return acc_id
    
    # Last resort: any expense account
    return db.execute(text(
        "SELECT id FROM accounts WHERE account_type = 'expense' AND is_active = true LIMIT 1"
    )).scalar()


def _resolve_expense_department_id(db, *, department_id: Optional[int] = None, cost_center_id: Optional[int] = None) -> Optional[int]:
    if department_id:
        return department_id
    if not cost_center_id:
        return None
    return db.execute(text(
        "SELECT department_id FROM cost_centers WHERE id = :id"
    ), {"id": cost_center_id}).scalar()


def _get_applicable_expense_policies(db, *, expense_type: Optional[str], department_id: Optional[int]) -> List[Dict[str, Any]]:
    rows = db.execute(text("""
        SELECT * FROM expense_policies
        WHERE is_active = TRUE AND is_deleted = false
          AND (expense_type IS NULL OR expense_type = '' OR expense_type = :expense_type)
          AND (department_id IS NULL OR department_id = :department_id)
        ORDER BY
          CASE WHEN expense_type = :expense_type THEN 0 ELSE 1 END,
          CASE WHEN department_id = :department_id THEN 0 ELSE 1 END
    """), {"expense_type": expense_type, "department_id": department_id}).fetchall()
    return [dict(row._mapping) for row in rows]


def _evaluate_expense_policy(
    db,
    *,
    expense_type: Optional[str],
    amount: Decimal,
    current_user_id: int,
    expense_date: date,
    department_id: Optional[int] = None,
    cost_center_id: Optional[int] = None,
    has_receipt: bool = False,
) -> Dict[str, Any]:
    resolved_department_id = _resolve_expense_department_id(
        db, department_id=department_id, cost_center_id=cost_center_id
    )
    policies = _get_applicable_expense_policies(
        db, expense_type=expense_type, department_id=resolved_department_id
    )
    amount_value = Decimal(str(amount or 0))
    violations: List[str] = []
    auto_approve = True
    applied_policy_id = policies[0]["id"] if policies else None

    for policy in policies:
        policy_name = policy.get("name") or policy.get("id")

        if policy.get("daily_limit") and amount_value > Decimal(str(policy["daily_limit"])):
            violations.append(f"Amount exceeds daily limit of {policy['daily_limit']} for policy '{policy_name}'")

        if policy.get("requires_receipt") and not has_receipt:
            violations.append(f"Policy '{policy_name}' requires a receipt")

        if policy.get("auto_approve_below") and amount_value >= Decimal(str(policy["auto_approve_below"])):
            auto_approve = False
        if policy.get("requires_approval"):
            auto_approve = False

        period_filters = [
            "e.expense_type = :expense_type",
            "e.is_deleted = false",
            "e.approval_status != 'rejected'",
        ]
        params = {
            "expense_type": expense_type,
            "user_id": current_user_id,
            "expense_date": expense_date,
            "policy_department_id": policy.get("department_id"),
        }
        join_cost_centers = ""
        if policy.get("department_id"):
            join_cost_centers = "LEFT JOIN cost_centers cc ON cc.id = e.cost_center_id"
            period_filters.append("cc.department_id = :policy_department_id")
        else:
            period_filters.append("e.created_by = :user_id")

        if policy.get("monthly_limit"):
            monthly_total = db.execute(text(f"""
                SELECT COALESCE(SUM(e.amount), 0)
                FROM expenses e
                {join_cost_centers}
                WHERE {' AND '.join(period_filters)}
                  AND DATE_TRUNC('month', e.expense_date) = DATE_TRUNC('month', CAST(:expense_date AS date))
            """), params).scalar()
            if Decimal(str(monthly_total or 0)) + amount_value > Decimal(str(policy["monthly_limit"])):
                scope = "department" if policy.get("department_id") else "user"
                violations.append(f"Total would exceed {scope} monthly limit of {policy['monthly_limit']} for policy '{policy_name}'")

        if policy.get("annual_limit"):
            annual_total = db.execute(text(f"""
                SELECT COALESCE(SUM(e.amount), 0)
                FROM expenses e
                {join_cost_centers}
                WHERE {' AND '.join(period_filters)}
                  AND EXTRACT(YEAR FROM e.expense_date) = EXTRACT(YEAR FROM CAST(:expense_date AS date))
            """), params).scalar()
            if Decimal(str(annual_total or 0)) + amount_value > Decimal(str(policy["annual_limit"])):
                scope = "department" if policy.get("department_id") else "user"
                violations.append(f"Total would exceed {scope} annual limit of {policy['annual_limit']} for policy '{policy_name}'")

    return {
        "valid": len(violations) == 0,
        "auto_approve": auto_approve and len(violations) == 0,
        "violations": violations,
        "policies_checked": len(policies),
        "policy_id": applied_policy_id,
        "department_id": resolved_department_id,
    }


def create_expense_journal_entry(db, expense_data: dict, user_id: int, base_currency: str, *, je_status: str = "posted"):
    """إنشاء قيد محاسبي للمصروف.

    T3.11: ``je_status`` controls whether the JE is posted immediately
    (legacy / auto-approved path) or created as ``draft`` so it shows
    up in GL but doesn't move account balances until approval. Both
    paths share the same line construction so balances reconcile
    exactly when the draft is later posted.
    """
    from services.gl_service import create_journal_entry as gl_create_journal_entry
    
    je_number = generate_sequential_number(db, "EXP", "journal_entries", "entry_number")
    
    je_lines = [
        {
            "account_id": expense_data["expense_account_id"], 
            "debit": Decimal(str(expense_data["amount"])), 
            "credit": 0,
            "cost_center_id": expense_data.get("cost_center_id"),
            "description": expense_data.get("description")
        },
        {
            "account_id": expense_data["cash_account_id"], 
            "debit": 0, 
            "credit": Decimal(str(expense_data["amount"])),
            "description": expense_data.get("description")
        },
    ]

    je_id, _ = gl_create_journal_entry(
        db=db,
        company_id=expense_data.get("company_id"),
        date=expense_data["expense_date"],
        description=f"مصروف {expense_data['expense_type']}: {expense_data.get('description', '')}",
        lines=je_lines,
        user_id=user_id,
        branch_id=expense_data.get("branch_id"),
        reference=je_number,
        status=je_status,
        currency=base_currency,
        exchange_rate=1.0,
        source="expense",
        source_id=expense_data.get("expense_id")
    )
    
    # Update journal entry number to keep the EXP- prefix (since gl_service generates JV-)
    db.execute(text("UPDATE journal_entries SET entry_number = :num WHERE id = :id"), {"num": je_number, "id": je_id})
    
    return je_id, je_number


# ═══════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════

@router.get("/", dependencies=[Depends(require_permission("expenses.view"))], response_model=List[Dict[str, Any]])
async def list_expenses(
    branch_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    expense_type: Optional[str] = None,
    approval_status: Optional[str] = None,
    search: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """قائمة المصاريف مع الفلاتر"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    with transactional(current_user.company_id) as db:
        params = {"company_id": current_user.company_id}
        filters = ["e.is_deleted = false"]
        
        branch_condition = branch_scope_filter_from_scope(branch_scope, "e.branch_id", params, prefix="").strip()
        if branch_condition:
            filters.append(branch_condition)
        if start_date:
            filters.append("e.expense_date >= :start_date")
            params["start_date"] = start_date
        if end_date:
            filters.append("e.expense_date <= :end_date")
            params["end_date"] = end_date
        if expense_type:
            filters.append("e.expense_type = :expense_type")
            params["expense_type"] = expense_type
        if approval_status:
            filters.append("e.approval_status = :approval_status")
            params["approval_status"] = approval_status
        if search:
            filters.append("(e.description ILIKE :search OR e.expense_number ILIKE :search)")
            params["search"] = f"%{search}%"
        
        where_clause = " AND ".join(filters)
        
        result = db.execute(text(f"""
            SELECT 
                e.id, e.expense_number, e.expense_date, e.expense_type,
                e.amount, e.description, e.category, e.payment_method,
                e.approval_status, e.receipt_number, e.vendor_name,
                e.created_at, e.branch_id,
                u.username as created_by_name,
                cc.center_name as cost_center_name,
                p.project_name,
                ta.name as treasury_name,
                approver.username as approved_by_name,
                e.approved_at
            FROM expenses e
            LEFT JOIN company_users u ON e.created_by = u.id
            LEFT JOIN cost_centers cc ON e.cost_center_id = cc.id
            LEFT JOIN projects p ON e.project_id = p.id
            LEFT JOIN treasury_accounts ta ON e.treasury_id = ta.id
            LEFT JOIN company_users approver ON e.approved_by = approver.id
            WHERE {where_clause}
            ORDER BY e.expense_date DESC, e.id DESC
            LIMIT 100
        """), params).fetchall()
        
        return [dict(r._mapping) for r in result]


@router.get("/summary", dependencies=[Depends(require_permission("expenses.view"))], response_model=Dict[str, Any])
async def get_expenses_summary(
    branch_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    current_user: dict = Depends(get_current_user)
):
    """إحصائيات المصاريف"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    with transactional(current_user.company_id) as db:
        params = {}
        filters = ["is_deleted = false"]
        
        branch_condition = branch_scope_filter_from_scope(branch_scope, "branch_id", params, prefix="").strip()
        if branch_condition:
            filters.append(branch_condition)
        if start_date:
            filters.append("expense_date >= :start_date")
            params["start_date"] = start_date
        if end_date:
            filters.append("expense_date <= :end_date")
            params["end_date"] = end_date
        
        where_clause = " AND ".join(filters)
        
        result = db.execute(text(f"""
            SELECT
                COUNT(*) as total_expenses,
                SUM(CASE WHEN approval_status = 'pending' THEN 1 ELSE 0 END) as pending_approval,
                SUM(CASE WHEN approval_status = 'approved' THEN 1 ELSE 0 END) as approved,
                SUM(CASE WHEN approval_status = 'rejected' THEN 1 ELSE 0 END) as rejected,
                SUM(amount) as total_amount,
                SUM(CASE WHEN approval_status = 'approved' THEN amount ELSE 0 END) as approved_amount,
                SUM(CASE WHEN approval_status = 'pending' THEN amount ELSE 0 END) as pending_amount
            FROM expenses
            WHERE {where_clause}
        """), params).fetchone()
        
        return dict(result._mapping) if result else {
            "total_expenses": 0, "pending_approval": 0, "approved": 0, "rejected": 0,
            "total_amount": 0, "approved_amount": 0, "pending_amount": 0
        }



# ===================== C1: Expense Policies =====================

@router.get("/policies", dependencies=[Depends(require_permission("expenses.view"))], response_model=List[Dict[str, Any]])
def list_expense_policies(current_user=Depends(get_current_user)):
    """سياسات المصروفات"""
    with transactional(current_user.company_id) as db:
        rows = db.execute(text("""
            SELECT ep.*, d.department_name as department_name
            FROM expense_policies ep
            LEFT JOIN departments d ON d.id = ep.department_id
            WHERE ep.is_deleted = false
            ORDER BY ep.name
        """)).fetchall()
        return [dict(r._mapping) for r in rows]


@router.post("/policies", dependencies=[Depends(require_permission("expenses.manage"))], response_model=Dict[str, Any])
def create_expense_policy(request: Request, policy: ExpensePolicyCreate, current_user=Depends(get_current_user)):
    """إنشاء سياسة مصروفات"""
    with transactional(current_user.company_id) as db:
        try:
            result = db.execute(text("""
                INSERT INTO expense_policies (name, expense_type, department_id,
                    daily_limit, monthly_limit, annual_limit, requires_receipt,
                    requires_approval, auto_approve_below, is_active)
                VALUES (:n, :et, :did, :dl, :ml, :al, :rr, :ra, :aab, :ia)
                RETURNING id
            """), {
                "n": policy.name, "et": policy.expense_type,
                "did": policy.department_id, "dl": policy.daily_limit,
                "ml": policy.monthly_limit, "al": policy.annual_limit,
                "rr": policy.requires_receipt,
                "ra": policy.requires_approval,
                "aab": policy.auto_approve_below, "ia": policy.is_active
            })
            pid = result.fetchone()[0]
            return {"id": pid, "message": i18n_message("expense_policy_created", request)}
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.put("/policies/{policy_id}", dependencies=[Depends(require_permission("expenses.manage"))], response_model=Dict[str, Any])
def update_expense_policy(request: Request, policy_id: int, policy: ExpensePolicyUpdate, current_user=Depends(get_current_user)):
    """تحديث سياسة مصروفات"""
    with transactional(current_user.company_id) as db:
        try:
            fields = []
            params = {"id": policy_id}
            for field_name in ["name", "expense_type", "department_id", "daily_limit",
                               "monthly_limit", "annual_limit", "requires_receipt",
                               "requires_approval", "auto_approve_below", "is_active"]:
                value = getattr(policy, field_name)
                if value is not None:
                    fields.append(f"{field_name} = :{field_name}")
                    params[field_name] = value
            if not fields:
                raise HTTPException(**http_error(400, "no_data_to_update"))
            fields.append("updated_at = NOW()")
            fields.append("updated_by = :uid")
            params["uid"] = current_user.id
            db.execute(text(f"UPDATE expense_policies SET {', '.join(fields)} WHERE id = :id AND is_deleted = false"), params)
            return {"message": i18n_message("expense_policy_updated", request)}
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.delete("/policies/{policy_id}", dependencies=[Depends(require_permission("expenses.manage"))], response_model=Dict[str, Any])
def delete_expense_policy(request: Request, policy_id: int, current_user=Depends(get_current_user)):
    """حذف سياسة مصروفات"""
    with transactional(current_user.company_id) as db:
        try:
            db.execute(text(
                "UPDATE expense_policies SET is_deleted = true, updated_at = NOW(), updated_by = :uid WHERE id = :id"
            ), {"id": policy_id, "uid": current_user.id})
            return {"message": i18n_message("expense_policy_deleted", request)}
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/validate-policy", response_model=Dict[str, Any])
def validate_expense_against_policy(expense: ExpenseValidation, current_user=Depends(get_current_user)):
    """التحقق من المصروف ضد السياسات"""
    with transactional(current_user.company_id) as db:
        return _evaluate_expense_policy(
            db,
            expense_type=expense.expense_type,
            amount=expense.amount,
            current_user_id=current_user.id,
            expense_date=date.today(),
            department_id=expense.department_id,
            has_receipt=expense.has_receipt,
        )


@router.get("/{expense_id}", dependencies=[Depends(require_permission("expenses.view"))], response_model=Dict[str, Any])
async def get_expense_details(expense_id: int, current_user: dict = Depends(get_current_user)):
    """تفاصيل مصروف محدد"""
    with transactional(current_user.company_id) as db:
        result = db.execute(text("""
            SELECT 
                e.*,
                u.username as created_by_name,
                cc.center_name as cost_center_name,
                p.project_name, p.project_code,
                ta.name as treasury_name,
                approver.username as approved_by_name,
                a.name as expense_account_name,
                a.account_number as expense_account_number
            FROM expenses e
            LEFT JOIN company_users u ON e.created_by = u.id
            LEFT JOIN cost_centers cc ON e.cost_center_id = cc.id
            LEFT JOIN projects p ON e.project_id = p.id
            LEFT JOIN treasury_accounts ta ON e.treasury_id = ta.id
            LEFT JOIN company_users approver ON e.approved_by = approver.id
            LEFT JOIN accounts a ON e.expense_account_id = a.id
            WHERE e.id = :id AND e.is_deleted = false
        """), {"id": expense_id}).fetchone()
        
        if not result:
            raise HTTPException(**http_error(404, "expense_not_found"))
        
        expense = dict(result._mapping)
        
        # Get journal entry if exists
        je = db.execute(text("""
            SELECT id, entry_number, entry_date, description, status
            FROM journal_entries
            WHERE entry_number LIKE :pattern
            ORDER BY created_at DESC
            LIMIT 1
        """), {"pattern": f"%{expense['expense_number']}%"}).fetchone()
        
        expense["journal_entry"] = dict(je._mapping) if je else None
        
        return expense


@router.post("/", status_code=status.HTTP_201_CREATED, 
             dependencies=[Depends(require_permission("expenses.create"))], response_model=Dict[str, Any])
async def create_expense(
    request: Request, 
    expense: ExpenseCreate, 
    current_user: dict = Depends(get_current_user)
):
    """إنشاء مصروف جديد"""
    expense.branch_id = validate_branch_access(current_user, expense.branch_id)
    with transactional(current_user.company_id) as db:
        try:
            # Check fiscal period is open for the expense date
            check_fiscal_period_open(db, str(expense.expense_date), raise_error=True)
            
            # Validate expense type
            if expense.expense_type and expense.expense_type not in EXPENSE_TYPES:
                raise HTTPException(status_code=400, detail=i18n_message("invalid_expense_type", request))

            require_cost_center = db.execute(text("""
                SELECT LOWER(setting_value) IN ('1', 'true', 'yes', 'on')
                FROM company_settings
                WHERE setting_key = 'expenses_require_cost_center'
            """)).scalar() or False
            if require_cost_center and not expense.cost_center_id:
                raise HTTPException(**http_error(400, "cost_center_required", request))
            
            policy_result = _evaluate_expense_policy(
                db,
                expense_type=expense.expense_type,
                amount=expense.amount,
                current_user_id=current_user.id,
                expense_date=expense.expense_date,
                cost_center_id=expense.cost_center_id,
                has_receipt=bool(expense.receipt_number),
            )
            if not policy_result["valid"]:
                raise HTTPException(status_code=400, detail={
                    "code": "expense_policy_violation",
                    "violations": policy_result["violations"],
                })
            
            base_currency = get_base_currency(db)
            
            # Determine expense account
            expense_account_id = expense.expense_account_id
            if not expense_account_id:
                expense_account_id = get_expense_account_by_type(db, expense.expense_type)
            
            if not expense_account_id:
                raise HTTPException(**http_error(400, "expense_account_required", request))
            
            # Determine cash/bank account
            cash_account_id = None
            if expense.treasury_id:
                treasury_row = validate_treasury_account_access(
                    db, current_user, expense.treasury_id, expense.branch_id
                )
                cash_account_id = treasury_row["gl_account_id"]
            
            if not cash_account_id:
                cash_account_id = get_mapped_account_id(db, "acc_map_cash_main")
            
            if not cash_account_id:
                raise HTTPException(**http_error(400, "cash_account_required", request))
            
            # Generate expense number
            expense_number = generate_sequential_number(db, "EXP", "expenses", "expense_number")
            
            # Initial approval status
            requires_policy_approval = not policy_result["auto_approve"]
            approval_status = "pending" if expense.requires_approval or requires_policy_approval else "approved"
            
            # Insert expense record
            expense_id = db.execute(text("""
                INSERT INTO expenses (
                    expense_number, expense_date, expense_type, amount, description,
                    category, payment_method, treasury_id, expense_account_id,
                    cost_center_id, project_id, branch_id, policy_id, approval_status,
                    receipt_number, vendor_name, created_by
                ) VALUES (
                    :num, :date, :type, :amt, :desc,
                    :cat, :pm, :tid, :eaid,
                    :ccid, :pid, :bid, :policy_id, :status,
                    :receipt, :vendor, :uid
                ) RETURNING id
            """), {
                "num": expense_number, "date": expense.expense_date, "type": expense.expense_type,
                "amt": str(expense.amount), "desc": expense.description,
                "cat": expense.category, "pm": expense.payment_method, "tid": expense.treasury_id,
                "eaid": expense_account_id,
                "ccid": expense.cost_center_id, "pid": expense.project_id, "bid": expense.branch_id,
                "policy_id": policy_result["policy_id"], "status": approval_status,
                "receipt": expense.receipt_number, "vendor": expense.vendor_name, "uid": current_user.id
            }).scalar()
            
            # T3.11: ALWAYS create a journal entry. Auto-approved expenses
            # post immediately; pending expenses get a `draft` JE so the
            # transaction is visible in GL but doesn't move balances until
            # approval flips it to `posted`. This eliminates the previous
            # split between "create now" and "create on approval" paths.
            je_status = "posted" if approval_status == "approved" else "draft"
            expense_data = {
                "expense_date": expense.expense_date,
                "expense_type": expense.expense_type,
                "amount": str(expense.amount),
                "description": expense.description,
                "expense_account_id": expense_account_id,
                "cash_account_id": cash_account_id,
                "cost_center_id": expense.cost_center_id,
                "branch_id": expense.branch_id,
                "company_id": current_user.company_id,
                "expense_id": expense_id
            }
            je_id, je_number = create_expense_journal_entry(
                db, expense_data, current_user.id, base_currency, je_status=je_status
            )
    
            # Update expense with journal entry reference (always — even
            # for drafts so approval can post the existing JE rather than
            # creating a second one).
            db.execute(text("""
                UPDATE expenses SET journal_entry_id = :jid WHERE id = :id
            """), {"jid": je_id, "id": expense_id})
    
            # Treasury / project side-effects only fire for posted JEs.
            if approval_status == "approved":
                # Update treasury balance (with sufficiency check)
                if expense.treasury_id:
                    treasury_balance = db.execute(text(
                        "SELECT current_balance FROM treasury_accounts WHERE id = :id FOR UPDATE"
                    ), {"id": expense.treasury_id}).scalar() or 0
                    if Decimal(str(treasury_balance)) < Decimal(str(expense.amount)):
                        raise HTTPException(status_code=400, detail=i18n_message("insufficient_treasury_balance", request))
                    db.execute(text("""
                        UPDATE treasury_accounts 
                        SET current_balance = current_balance - :amt 
                        WHERE id = :id
                    """), {"amt": str(expense.amount), "id": expense.treasury_id})
                
                # Update project actual_cost if linked
                if expense.project_id:
                    db.execute(text("""
                        UPDATE projects 
                        SET actual_cost = actual_cost + :amt
                        WHERE id = :id
                    """), {"amt": str(expense.amount), "id": expense.project_id})
            
            
            log_activity(
                db, user_id=current_user.id, username=current_user.username,
                action="expense.create", resource_type="expense", resource_id=str(expense_id),
                details={"expense_number": expense_number, "amount": str(expense.amount)},
                request=request, branch_id=expense.branch_id
            )
            
            # Submit for approval workflow if pending
            approval_info = None
            if approval_status == "pending":
                try:
                    from utils.approval_utils import try_submit_for_approval
                    approval_info = try_submit_for_approval(
                        db,
                        document_type="expense",
                        document_id=expense_id,
                        document_number=expense_number,
                        amount=Decimal(str(expense.amount)),
                        submitted_by=current_user.id,
                        description=f"مصروف {expense.expense_type}: {expense.description or ''} - {Decimal(str(expense.amount)):,.2f}",
                        link=f"/expenses/{expense_id}"
                    )
                    if approval_info:
                        db.commit()
                except Exception:
                    pass  # Non-blocking
            
            response = {
                "success": True,
                "id": expense_id,
                "expense_number": expense_number,
                "approval_status": approval_status,
                "message": i18n_message("expense_created_success", request) if approval_status == "approved" else "تم إنشاء المصروف - في انتظار الاعتماد",
                "policy": policy_result,
            }
    
            # Notify about expense submission
            if approval_status == "pending":
                try:
                    db.execute(text("""
                        INSERT INTO notifications (user_id, type, title, message, link, is_read, created_at)
                        SELECT DISTINCT u.id, 'expense', :title, :message, :link, FALSE, NOW()
                        FROM company_users u
                        WHERE u.is_active = TRUE AND u.role IN ('admin', 'superuser')
                        AND u.id != :current_uid
                    """), {
                        "title": i18n_message("notif_new_expense", request),
                        "message": i18n_message("expense_notification_details", request),
                        "link": f"/expenses/{expense_id}",
                        "current_uid": current_user.id
                    })
                    db.commit()
                except Exception:
                    pass
    
            if approval_info:
                response["approval"] = approval_info
            return response
        except HTTPException:
            raise
        except Exception as e:
            pass
            logger.error(f"Error creating expense: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.put("/{expense_id}", dependencies=[Depends(require_permission("expenses.edit"))], response_model=Dict[str, Any])
async def update_expense(
    request: Request,
    expense_id: int,
    expense: ExpenseUpdate,
    current_user: dict = Depends(get_current_user)
):
    """تعديل مصروف"""
    with transactional(current_user.company_id) as db:
        try:
            # Check if expense exists and is pending
            existing = db.execute(text(
                "SELECT id, approval_status FROM expenses WHERE id = :id AND is_deleted = false"
            ), {"id": expense_id}).fetchone()
            
            if not existing:
                raise HTTPException(**http_error(404, "expense_not_found"))
            
            if existing.approval_status != "pending":
                raise HTTPException(**http_error(400, "expense_cannot_edit_approved_or_rejected", request))
            
            # Build update fields
            update_fields = []
            params = {"id": expense_id}
            
            for field in ["expense_date", "expense_type", "amount", "description", "category",
                         "payment_method", "treasury_id", "expense_account_id", "cost_center_id",
                         "project_id", "receipt_number", "vendor_name"]:
                value = getattr(expense, field)
                if value is not None:
                    update_fields.append(f"{field} = :{field}")
                    params[field] = value
            
            if not update_fields:
                raise HTTPException(**http_error(400, "no_data_to_update"))
            
            update_fields.append("updated_at = CURRENT_TIMESTAMP")
            
            db.execute(text(f"""
                UPDATE expenses SET {', '.join(update_fields)}
                WHERE id = :id
            """), params)
            
            
            log_activity(
                db, user_id=current_user.id, username=current_user.username,
                action="expense.update", resource_type="expense", resource_id=str(expense_id),
                details={"updates": update_fields}, request=request
            )
            
            return {"success": True, "message": i18n_message("expense_updated", request)}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.post("/{expense_id}/approve", dependencies=[Depends(require_permission("expenses.approve"))], response_model=Dict[str, Any])
async def approve_expense(
    request: Request,
    expense_id: int,
    approval: ExpenseApproval,
    current_user: dict = Depends(get_current_user)
):
    """اعتماد أو رفض مصروف"""
    with transactional(current_user.company_id) as db:
        try:
            # T3.12: lock the expense row for the duration of the approval
            # so two concurrent approvers can't both post the JE. The lock
            # is taken first thing — before any JE work — so the second
            # caller waits until the first one's transaction completes and
            # then sees the updated approval_status.
            db.execute(text(
                "SELECT id FROM expenses WHERE id = :id AND is_deleted = false FOR UPDATE"
            ), {"id": expense_id})
    
            # Get expense details
            expense_row = db.execute(text("""
                SELECT e.*, a.id as expense_account_id, ta.gl_account_id as cash_account_id
                FROM expenses e
                LEFT JOIN accounts a ON e.expense_account_id = a.id
                LEFT JOIN treasury_accounts ta ON e.treasury_id = ta.id
                WHERE e.id = :id AND e.is_deleted = false
            """), {"id": expense_id}).fetchone()
            
            if not expense_row:
                raise HTTPException(**http_error(404, "expense_not_found"))
            
            expense = dict(expense_row._mapping)
            
            if expense["approval_status"] != "pending":
                raise HTTPException(**http_error(400, "expense_already_approved_or_rejected", request))
            
            # Validate approval_status value
            if approval.approval_status not in VALID_APPROVAL_STATUSES:
                raise HTTPException(**http_error(400, "invalid_approval_status", request, statuses=', '.join(VALID_APPROVAL_STATUSES)))
            
            # Update approval status
            db.execute(text("""
                UPDATE expenses 
                SET approval_status = :status, 
                    approved_by = :uid, 
                    approved_at = CURRENT_TIMESTAMP,
                    approval_notes = :notes
                WHERE id = :id
            """), {
                "status": approval.approval_status, 
                "uid": current_user.id, 
                "notes": approval.approval_notes,
                "id": expense_id
            })
            
            # If approved, transition the existing draft JE to posted.
            # T3.11: ``create_expense`` now always inserts the JE on
            # creation (draft when pending) so approval is a pure status
            # flip plus side-effect application — no second JE is ever
            # created.
            if approval.approval_status == "approved":
                base_currency = get_base_currency(db)
    
                # Determine cash account
                cash_account_id = expense["cash_account_id"]
                if expense["treasury_id"]:
                    treasury_row = validate_treasury_account_access(
                        db, current_user, expense["treasury_id"], expense.get("branch_id")
                    )
                    cash_account_id = treasury_row["gl_account_id"]
                if not cash_account_id:
                    cash_account_id = get_mapped_account_id(db, "acc_map_cash_main")
    
                if not cash_account_id:
                    raise HTTPException(**http_error(400, "cash_account_not_set", request))
    
                existing_je_id = expense.get("journal_entry_id")
                if existing_je_id:
                    from services.gl_service import post_draft_journal_entry
                    post_draft_journal_entry(db, existing_je_id, current_user.id)
                else:
                    # Backwards-compat: legacy expenses created before T3.11
                    # don't have a draft JE attached. Create-and-post one
                    # in a single shot to keep them auditable.
                    expense_data = {
                        "expense_date": expense["expense_date"],
                        "expense_type": expense["expense_type"],
                        "amount": str(expense["amount"]),
                        "description": expense["description"],
                        "expense_account_id": expense["expense_account_id"],
                        "cash_account_id": cash_account_id,
                        "cost_center_id": expense["cost_center_id"],
                        "branch_id": expense["branch_id"],
                        "company_id": current_user.company_id,
                        "expense_id": expense_id
                    }
                    je_id, je_number = create_expense_journal_entry(
                        db, expense_data, current_user.id, base_currency, je_status="posted"
                    )
                    db.execute(text(
                        "UPDATE expenses SET journal_entry_id = :jid WHERE id = :id"
                    ), {"jid": je_id, "id": expense_id})
    
                # Update treasury balance (with sufficiency check)
                if expense["treasury_id"]:
                    treasury_balance = db.execute(text(
                        "SELECT current_balance FROM treasury_accounts WHERE id = :id FOR UPDATE"
                    ), {"id": expense["treasury_id"]}).scalar() or 0
                    if Decimal(str(treasury_balance)) < Decimal(str(expense["amount"])):
                        raise HTTPException(status_code=400, detail=i18n_message("insufficient_treasury_balance", request))
                    db.execute(text("""
                        UPDATE treasury_accounts 
                        SET current_balance = current_balance - :amt 
                        WHERE id = :id
                    """), {"amt": str(expense["amount"]), "id": expense["treasury_id"]})
                
                # Update project actual_cost if linked
                if expense["project_id"]:
                    db.execute(text("""
                        UPDATE projects 
                        SET actual_cost = actual_cost + :amt
                        WHERE id = :id
                    """), {"amt": str(expense["amount"]), "id": expense["project_id"]})
            
            
            log_activity(
                db, user_id=current_user.id, username=current_user.username,
                action=f"expense.{approval.approval_status}", resource_type="expense",
                resource_id=str(expense_id),
                details={"approval_status": approval.approval_status, "notes": approval.approval_notes},
                request=request
            )
            
            message = "تم اعتماد المصروف بنجاح" if approval.approval_status == "approved" else "تم رفض المصروف"
    
            # Notify the expense submitter
            try:
                submitted_by = db.execute(text("SELECT created_by FROM expenses WHERE id = :id"), {"id": expense_id}).scalar()
                if submitted_by:
                    icon = "✅" if approval.approval_status == "approved" else "❌"
                    status_ar = "اعتُمد" if approval.approval_status == "approved" else "رُفض"
                    exp_num = expense.get('expense_number', '') if isinstance(expense, dict) else ''
                    db.execute(text("""
                        INSERT INTO notifications (user_id, type, title, message, link, is_read, created_at)
                        VALUES (:uid, 'expense_status', :title, :message, :link, FALSE, NOW())
                    """), {
                        "uid": submitted_by,
                        "title": f"{icon} مصروفك {status_ar}",
                        "message": i18n_message("expense_status_update_details", request) if isinstance(expense, dict) else f"تم {status_ar} طلب المصروف",
                        "link": f"/expenses/{expense_id}"
                    })
                    db.commit()
            except Exception:
                pass
    
            return {"success": True, "message": message}
        except HTTPException:
            raise
        except Exception as e:
            pass
            logger.error(f"Error approving expense: {e}")
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


# ═══════════════════════════════════════════════════════════
# T3.13 — Reverse an approved expense
# ═══════════════════════════════════════════════════════════

@router.post("/{expense_id}/reverse", dependencies=[Depends(require_permission("expenses.approve"))], response_model=Dict[str, Any])
async def reverse_expense(
    request: Request,
    expense_id: int,
    payload: dict = None,
    current_user: dict = Depends(get_current_user),
):
    """عكس مصروف معتمد بإنشاء قيد عكسي وتغيير الحالة إلى ``reversed``.

    DoD (T3.13): إجمالي AP/Cash لا يتأثر بعد الإلغاء — أي أن مجموع
    المدين والدائن لكل حساب طرف في القيدين الأصلي والعكسي يتساوى،
    فيُعاد الرصيد لقيمته قبل المصروف.
    """
    db = get_db_connection(current_user.company_id)
    payload = payload or {}
    reason = (payload.get("reason") or "").strip() or None
    reversal_date = payload.get("reversal_date")

    try:
        # Lock the row before any work — T3.12 pattern.
        db.execute(text(
            "SELECT id FROM expenses WHERE id = :id AND is_deleted = false FOR UPDATE"
        ), {"id": expense_id})

        row = db.execute(text("""
            SELECT id, expense_number, amount, treasury_id, project_id,
                   approval_status, journal_entry_id, branch_id
            FROM expenses
            WHERE id = :id AND is_deleted = false
        """), {"id": expense_id}).fetchone()
        if not row:
            raise HTTPException(**http_error(404, "expense_not_found"))

        expense = dict(row._mapping)
        if expense["approval_status"] != "approved":
            raise HTTPException(**http_error(400, "expense_cannot_reverse_non_approved", request))
        if not expense["journal_entry_id"]:
            raise HTTPException(**http_error(400, "expense_original_je_not_found", request))

        # Fiscal lock check on the reversal date (defaults to today).
        from datetime import date as _date
        eff_date = reversal_date or str(_date.today())
        check_fiscal_period_open(db, eff_date, raise_error=True)

        from services.gl_service import reverse_journal_entry
        rev_id, rev_num = reverse_journal_entry(
            db,
            je_id=expense["journal_entry_id"],
            user_id=current_user.id,
            company_id=current_user.company_id,
            reversal_date=eff_date,
            reason=reason,
        )

        amount = Decimal(str(expense["amount"]))

        # Reverse treasury balance.
        if expense["treasury_id"]:
            db.execute(text("""
                UPDATE treasury_accounts
                SET current_balance = current_balance + :amt
                WHERE id = :id
            """), {"amt": str(amount), "id": expense["treasury_id"]})

        # Reverse project actual_cost.
        if expense["project_id"]:
            db.execute(text("""
                UPDATE projects
                SET actual_cost = GREATEST(actual_cost - :amt, 0)
                WHERE id = :id
            """), {"amt": str(amount), "id": expense["project_id"]})

        # Mark the expense reversed.
        db.execute(text("""
            UPDATE expenses
            SET approval_status = 'reversed',
                reversal_journal_entry_id = :rid,
                reversed_at = NOW(),
                reversed_by = :uid,
                reversal_reason = :reason
            WHERE id = :id
        """), {"rid": rev_id, "uid": current_user.id, "reason": reason, "id": expense_id})

        db.commit()

        log_activity(
            db,
            user_id=current_user.id,
            username=current_user.username,
            action="expense.reverse",
            resource_type="expense",
            resource_id=str(expense_id),
            details={
                "expense_number": expense["expense_number"],
                "amount": str(amount),
                "original_je_id": expense["journal_entry_id"],
                "reversal_je_id": rev_id,
                "reversal_je_number": rev_num,
                "reason": reason,
            },
            request=request,
            branch_id=expense.get("branch_id"),
        )

        return {
            "success": True,
            "message": i18n_message("expense_reversed_success", request),
            "expense_id": expense_id,
            "reversal_journal_entry_id": rev_id,
            "reversal_journal_entry_number": rev_num,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error reversing expense: {e}")
        logger.exception("Internal error")
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.delete("/{expense_id}", dependencies=[Depends(require_permission("expenses.delete"))], response_model=Dict[str, Any])
async def delete_expense(
    request: Request,
    expense_id: int,
    current_user: dict = Depends(get_current_user)
):
    """حذف مصروف (فقط إذا كان معلق)"""
    with transactional(current_user.company_id) as db:
        try:
            expense = db.execute(text(
                "SELECT approval_status FROM expenses WHERE id = :id AND is_deleted = false"
            ), {"id": expense_id}).fetchone()
            
            if not expense:
                raise HTTPException(**http_error(404, "expense_not_found"))
            
            if expense.approval_status != "pending":
                raise HTTPException(**http_error(400, "expense_approved_cannot_delete", request))
            
            db.execute(text(
                "UPDATE expenses SET is_deleted = true, updated_at = NOW(), updated_by = :uid WHERE id = :id"
            ), {"id": expense_id, "uid": current_user.id})
            
            log_activity(
                db, user_id=current_user.id, username=current_user.username,
                action="expense.delete", resource_type="expense", resource_id=str(expense_id),
                request=request
            )
            
            return {"success": True, "message": i18n_message("expense_deleted", request)}
        except HTTPException:
            raise
        except Exception:
            pass
            logger.exception("Internal error")
            raise HTTPException(**http_error(500, "internal_error"))


@router.get("/reports/by-type", dependencies=[Depends(require_permission("expenses.view"))], response_model=List[Dict[str, Any]])
async def get_expenses_by_type(
    branch_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير المصاريف حسب النوع"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    with transactional(current_user.company_id) as db:
        params = {}
        filters = ["approval_status = 'approved'", "is_deleted = false"]
        
        branch_condition = branch_scope_filter_from_scope(branch_scope, "branch_id", params, prefix="").strip()
        if branch_condition:
            filters.append(branch_condition)
        if start_date:
            filters.append("expense_date >= :start_date")
            params["start_date"] = start_date
        if end_date:
            filters.append("expense_date <= :end_date")
            params["end_date"] = end_date
        
        where_clause = " AND ".join(filters)
        
        result = db.execute(text( # noqa: sql-lint
                    f"""
            SELECT 
                expense_type,
                COUNT(*) as count,
                SUM(amount) as total_amount,
                AVG(amount) as avg_amount,
                MIN(amount) as min_amount,
                MAX(amount) as max_amount
            FROM expenses
            WHERE {where_clause}
            GROUP BY expense_type
            ORDER BY total_amount DESC
        """), params).fetchall()
        
        return [dict(r._mapping) for r in result]


@router.get("/reports/by-cost-center", dependencies=[Depends(require_permission("expenses.view"))], response_model=List[Dict[str, Any]])
async def get_expenses_by_cost_center(
    branch_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير المصاريف حسب مركز التكلفة"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    with transactional(current_user.company_id) as db:
        params = {}
        filters = ["e.approval_status = 'approved'", "e.is_deleted = false"]
        
        branch_condition = branch_scope_filter_from_scope(branch_scope, "e.branch_id", params, prefix="").strip()
        if branch_condition:
            filters.append(branch_condition)
        if start_date:
            filters.append("e.expense_date >= :start_date")
            params["start_date"] = start_date
        if end_date:
            filters.append("e.expense_date <= :end_date")
            params["end_date"] = end_date
        
        where_clause = " AND ".join(filters)
        
        result = db.execute(text( # noqa: sql-lint
                    f"""
            SELECT 
                COALESCE(cc.center_name, 'غير محدد') as cost_center_name,
                COUNT(*) as count,
                SUM(e.amount) as total_amount
            FROM expenses e
            LEFT JOIN cost_centers cc ON e.cost_center_id = cc.id
            WHERE {where_clause}
            GROUP BY cc.center_name
            ORDER BY total_amount DESC
        """), params).fetchall()
        
        return [dict(r._mapping) for r in result]


@router.get("/reports/monthly", dependencies=[Depends(require_permission("expenses.view"))], response_model=List[Dict[str, Any]])
async def get_monthly_expenses(
    branch_id: Optional[int] = None,
    year: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """تقرير المصاريف الشهري"""
    branch_scope = resolve_branch_scope(current_user, branch_id)
    with transactional(current_user.company_id) as db:
        from datetime import datetime
        current_year = year or datetime.now().year
        
        params = {"year": current_year}
        filters = ["approval_status = 'approved'", "is_deleted = false", "EXTRACT(YEAR FROM expense_date) = :year"]
        
        branch_condition = branch_scope_filter_from_scope(branch_scope, "branch_id", params, prefix="").strip()
        if branch_condition:
            filters.append(branch_condition)
        
        where_clause = " AND ".join(filters)
        
        result = db.execute(text( # noqa: sql-lint
                    f"""
            SELECT 
                EXTRACT(MONTH FROM expense_date) as month,
                COUNT(*) as count,
                SUM(amount) as total_amount
            FROM expenses
            WHERE {where_clause}
            GROUP BY EXTRACT(MONTH FROM expense_date)
            ORDER BY month
        """), params).fetchall()
        
        return [dict(r._mapping) for r in result]

