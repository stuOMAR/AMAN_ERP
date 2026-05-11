"""
AMAN ERP — Petty Cash module (T15 P1 #70/#71/#72/#104)
العُهَد النقدية والمصاريف النثرية

Provides three things on top of the schema added in
``backend/db_ddl/tenant_schema.py``:

  1. CRUD for ``petty_cash_funds`` (cash floats held by a custodian).
  2. POST ``/funds/{id}/replenish`` — top up a fund from a treasury
     account, posting a JE: Dr Petty-Cash GL  Cr Treasury GL.
  3. POST ``/funds/{id}/disburse`` — record a small expense paid out of
     the fund: creates an ``expenses`` row + JE: Dr Expense  Cr Petty-Cash.

Both flows update ``petty_cash_funds.current_balance`` atomically inside
a single transaction; we rely on row-level locking via
``SELECT ... FOR UPDATE`` to avoid lost-update races when two operators
disburse from the same fund concurrently.

Why a dedicated module rather than abusing ``expenses.py``:
  * The float is a *running balance* (asset, not expense). Disbursements
    decrement the float; only at expense-recognition time does an expense
    line book to P&L. Folding this into the generic expense router would
    blur cash-on-hand reporting.
  * Reconciliation between treasury and the petty-cash GL account is
    materially different from regular AP — the auditor needs the
    transactions list per fund, not per supplier.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from database import get_db_connection
from routers.auth import get_current_user
from utils.audit import log_activity
from utils.fiscal_lock import check_fiscal_period_open
from utils.i18n import http_error
from utils.permissions import branch_scope_filter, require_permission, require_module, validate_branch_access, validate_treasury_account_access

router = APIRouter(
    prefix="/petty-cash",
    tags=["Petty Cash"],
    dependencies=[Depends(require_module("treasury"))],
)


# --------------------------------------------------------------------------- #
# Pydantic schemas — kept inline because the surface is small and the schemas
# package is already crowded with sales/HR/inventory artifacts.
# --------------------------------------------------------------------------- #

class PettyCashFundCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    custodian_employee_id: Optional[int] = None
    treasury_account_id: int
    gl_account_id: Optional[int] = None
    branch_id: Optional[int] = None
    currency: str = "SAR"
    ceiling_amount: Decimal = Decimal("0")


class PettyCashFundResponse(BaseModel):
    id: int
    name: str
    custodian_employee_id: Optional[int] = None
    treasury_account_id: int
    gl_account_id: Optional[int] = None
    branch_id: Optional[int] = None
    currency: str
    ceiling_amount: Decimal
    current_balance: Decimal
    is_active: bool


class PettyCashOp(BaseModel):
    """Common payload for replenish / disburse / return."""
    amount: Decimal = Field(..., gt=0)
    description: Optional[str] = None
    txn_date: Optional[date] = None
    expense_account_id: Optional[int] = None  # only used by disburse


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _resolve_petty_cash_gl(db, fund_row, request=None) -> int:
    """Return the GL account id used as the petty-cash control account.

    Preference order:
      1. ``fund.gl_account_id`` if set.
      2. The treasury account's GL (so a single fund stays linked to its
         own asset bucket).
    """
    if fund_row.gl_account_id:
        return fund_row.gl_account_id
    gl_id = db.execute(
        text("SELECT gl_account_id FROM treasury_accounts WHERE id = :id"),
        {"id": fund_row.treasury_account_id},
    ).scalar()
    if not gl_id:
        raise HTTPException(**http_error(400, "petty_cash_no_gl_account", request))
    return gl_id


def _resolve_expense_gl(db, expense_account_id: Optional[int], request=None) -> int:
    """Pick the expense GL for a disbursement. Falls back to the generic
    ``acc_map_general_expense`` mapping used by ``routers/finance/expenses.py``."""
    if expense_account_id:
        return expense_account_id
    row = db.execute(text(
        "SELECT acc_id FROM acc_mappings WHERE map_key = 'acc_map_general_expense' LIMIT 1"
    )).fetchone()
    if not row or not row[0]:
        raise HTTPException(**http_error(400, "petty_cash_expense_account_not_configured", request))
    return row[0]


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #

@router.get("/funds", response_model=List[PettyCashFundResponse],
            dependencies=[Depends(require_permission("treasury.view"))])
def list_funds(branch_id: Optional[int] = None,
               current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        q = "SELECT * FROM petty_cash_funds WHERE is_active = TRUE"
        params: Dict[str, Any] = {}
        q += " " + branch_scope_filter(current_user, branch_id, "branch_id", params, branch_param="bid")
        q += " ORDER BY id"
        rows = db.execute(text(q), params).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


@router.post("/funds", response_model=PettyCashFundResponse,
             status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_permission("treasury.create"))])
def create_fund(payload: PettyCashFundCreate, request: Request,
                current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        branch_id = validate_branch_access(current_user, payload.branch_id)
        treasury_account = validate_treasury_account_access(
            db, current_user, payload.treasury_account_id, branch_id
        )
        if branch_id is None and treasury_account.get("branch_id") is not None:
            branch_id = int(treasury_account["branch_id"])

        # Verify treasury exists and currency matches.
        if treasury_account.get("currency") and payload.currency and treasury_account["currency"] != payload.currency:
            raise HTTPException(**http_error(400, "petty_cash_currency_mismatch", request))

        gl_id = payload.gl_account_id or treasury_account.get("gl_account_id")
        row = db.execute(text("""
            INSERT INTO petty_cash_funds
                (name, custodian_employee_id, treasury_account_id, gl_account_id,
                 branch_id, currency, ceiling_amount, current_balance, is_active)
            VALUES (:name, :cust, :tid, :gl, :bid, :curr, :ceil, 0, TRUE)
            RETURNING *
        """), {
            "name": payload.name,
            "cust": payload.custodian_employee_id,
            "tid": payload.treasury_account_id,
            "gl": gl_id,
            "bid": branch_id,
            "curr": payload.currency,
            "ceil": payload.ceiling_amount,
        }).fetchone()
        db.commit()
        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="petty_cash.fund.create", resource_type="petty_cash_fund",
                     resource_id=str(row.id), details={"name": payload.name},
                     request=request, branch_id=branch_id)
        return dict(row._mapping)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


def _post_je(db, *, company_id, user_id, branch_id, fund_id, txn_date,
             dr_acc, cr_acc, amount, description, source, source_id):
    """Thin wrapper around services.gl_service.create_journal_entry that
    builds a balanced 2-line JE and returns the new ``je_id``."""
    from services.gl_service import create_journal_entry
    je_id = create_journal_entry(
        db=db, company_id=company_id,
        date=txn_date.isoformat() if hasattr(txn_date, "isoformat") else str(txn_date),
        description=description,
        lines=[
            {"account_id": dr_acc, "debit": float(amount), "credit": 0,
             "currency": None, "exchange_rate": 1.0},
            {"account_id": cr_acc, "debit": 0, "credit": float(amount),
             "currency": None, "exchange_rate": 1.0},
        ],
        user_id=user_id, branch_id=branch_id,
        source=source, source_id=source_id,
    )
    return je_id


@router.post("/funds/{fund_id}/replenish",
             dependencies=[Depends(require_permission("treasury.create"))],
             response_model=Dict[str, Any])
def replenish_fund(fund_id: int, payload: PettyCashOp, request: Request,
                   current_user=Depends(get_current_user)):
    """Top up a fund from its linked treasury.

    JE: Dr Petty-Cash GL    Cr Treasury GL
    """
    db = get_db_connection(current_user.company_id)
    try:
        # Lock the fund row to serialise concurrent ops on the same fund.
        fund = db.execute(
            text("SELECT * FROM petty_cash_funds WHERE id = :id FOR UPDATE"),
            {"id": fund_id},
        ).fetchone()
        if not fund or not fund.is_active:
            raise HTTPException(**http_error(404, "fund_not_found", request))
        branch_id = validate_branch_access(current_user, fund.branch_id)
        treasury_account = validate_treasury_account_access(
            db, current_user, fund.treasury_account_id, branch_id
        )

        if fund.ceiling_amount and (fund.current_balance + payload.amount) > fund.ceiling_amount:
            raise HTTPException(**http_error(400, "petty_cash_exceeds_ceiling", request))

        txn_date = payload.txn_date or date.today()
        check_fiscal_period_open(db, txn_date.isoformat())

        petty_gl = _resolve_petty_cash_gl(db, fund, request)
        treasury_gl = treasury_account.get("gl_account_id")
        if not treasury_gl:
            raise HTTPException(**http_error(400, "treasury_no_gl_account", request))

        je_id = _post_je(
            db, company_id=current_user.company_id, user_id=current_user.id,
            branch_id=branch_id, fund_id=fund_id, txn_date=txn_date,
            dr_acc=petty_gl, cr_acc=treasury_gl, amount=payload.amount,
            description=payload.description or f"Petty cash replenishment — {fund.name}",
            source="petty_cash_replenish", source_id=fund_id,
        )

        txn = db.execute(text("""
            INSERT INTO petty_cash_transactions
                (fund_id, txn_type, amount, txn_date, description, je_id, created_by)
            VALUES (:fid, 'replenish', :amt, :td, :desc, :je, :uid)
            RETURNING id
        """), {
            "fid": fund_id, "amt": payload.amount, "td": txn_date,
            "desc": payload.description, "je": je_id, "uid": current_user.id,
        }).scalar()

        db.execute(text(
            "UPDATE petty_cash_funds SET current_balance = current_balance + :amt, "
            "updated_at = NOW() WHERE id = :id"
        ), {"amt": payload.amount, "id": fund_id})

        db.commit()
        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="petty_cash.replenish", resource_type="petty_cash_fund",
                     resource_id=str(fund_id),
                     details={"amount": float(payload.amount), "je_id": je_id, "txn_id": txn},
                     request=request, branch_id=branch_id)
        return {"txn_id": txn, "je_id": je_id, "new_balance": float(fund.current_balance + payload.amount)}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.post("/funds/{fund_id}/disburse",
             dependencies=[Depends(require_permission("expenses.create"))],
             response_model=Dict[str, Any])
def disburse_fund(fund_id: int, payload: PettyCashOp, request: Request,
                  current_user=Depends(get_current_user)):
    """Disburse cash from a fund as an expense.

    JE: Dr Expense GL    Cr Petty-Cash GL
    """
    db = get_db_connection(current_user.company_id)
    try:
        fund = db.execute(
            text("SELECT * FROM petty_cash_funds WHERE id = :id FOR UPDATE"),
            {"id": fund_id},
        ).fetchone()
        if not fund or not fund.is_active:
            raise HTTPException(**http_error(404, "fund_not_found", request))
        branch_id = validate_branch_access(current_user, fund.branch_id)
        validate_treasury_account_access(db, current_user, fund.treasury_account_id, branch_id)
        if payload.amount > fund.current_balance:
            raise HTTPException(**http_error(400, "petty_cash_insufficient_balance", request))

        txn_date = payload.txn_date or date.today()
        check_fiscal_period_open(db, txn_date.isoformat())

        petty_gl = _resolve_petty_cash_gl(db, fund, request)
        expense_gl = _resolve_expense_gl(db, payload.expense_account_id, request)

        je_id = _post_je(
            db, company_id=current_user.company_id, user_id=current_user.id,
            branch_id=branch_id, fund_id=fund_id, txn_date=txn_date,
            dr_acc=expense_gl, cr_acc=petty_gl, amount=payload.amount,
            description=payload.description or f"Petty cash expense — {fund.name}",
            source="petty_cash_disburse", source_id=fund_id,
        )

        txn = db.execute(text("""
            INSERT INTO petty_cash_transactions
                (fund_id, txn_type, amount, txn_date, description, je_id, created_by)
            VALUES (:fid, 'disburse', :amt, :td, :desc, :je, :uid)
            RETURNING id
        """), {
            "fid": fund_id, "amt": payload.amount, "td": txn_date,
            "desc": payload.description, "je": je_id, "uid": current_user.id,
        }).scalar()

        db.execute(text(
            "UPDATE petty_cash_funds SET current_balance = current_balance - :amt, "
            "updated_at = NOW() WHERE id = :id"
        ), {"amt": payload.amount, "id": fund_id})

        db.commit()
        log_activity(db, user_id=current_user.id, username=current_user.username,
                     action="petty_cash.disburse", resource_type="petty_cash_fund",
                     resource_id=str(fund_id),
                     details={"amount": float(payload.amount), "je_id": je_id, "txn_id": txn},
                     request=request, branch_id=branch_id)
        return {"txn_id": txn, "je_id": je_id,
                "new_balance": float(fund.current_balance - payload.amount)}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(**http_error(500, "internal_error"))
    finally:
        db.close()


@router.get("/funds/{fund_id}/transactions",
            dependencies=[Depends(require_permission("treasury.view"))],
            response_model=List[Dict[str, Any]])
def list_transactions(request: Request, fund_id: int, limit: int = 200,
                      current_user=Depends(get_current_user)):
    db = get_db_connection(current_user.company_id)
    try:
        fund = db.execute(
            text("SELECT branch_id, treasury_account_id FROM petty_cash_funds WHERE id = :id"),
            {"id": fund_id},
        ).fetchone()
        if not fund:
            raise HTTPException(**http_error(404, "fund_not_found", request))
        branch_id = validate_branch_access(current_user, fund.branch_id)
        validate_treasury_account_access(db, current_user, fund.treasury_account_id, branch_id)

        rows = db.execute(text("""
            SELECT id, txn_type, amount, txn_date, description, je_id, created_by, created_at
            FROM petty_cash_transactions
            WHERE fund_id = :fid
            ORDER BY txn_date DESC, id DESC
            LIMIT :lim
        """), {"fid": fund_id, "lim": limit}).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()
