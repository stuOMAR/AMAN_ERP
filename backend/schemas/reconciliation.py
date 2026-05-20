"""Reconciliation module Pydantic schemas."""
from pydantic import BaseModel
from typing import Optional
from datetime import date
from decimal import Decimal


class ReconciliationCreate(BaseModel):
    treasury_account_id: int
    statement_date: date
    start_balance: Decimal
    end_balance: Decimal
    tolerance_amount: Optional[Decimal] = None
    notes: Optional[str] = None
    branch_id: Optional[int] = None


class StatementLineCreate(BaseModel):
    transaction_date: date
    description: str
    reference: Optional[str] = None
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")


class MatchRequest(BaseModel):
    statement_line_id: int
    journal_line_id: int


class UnmatchRequest(BaseModel):
    statement_line_id: int
