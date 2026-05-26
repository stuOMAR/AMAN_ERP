"""Budgets module Pydantic schemas."""
from pydantic import BaseModel
from typing import Optional
from datetime import date
from decimal import Decimal


class BudgetItemBase(BaseModel):
    account_id: int
    planned_amount: Optional[Decimal] = None
    monthly_amount: Optional[Decimal] = None
    notes: Optional[str] = None


class BudgetItemCreate(BudgetItemBase):
    pass


class BudgetItemResponse(BudgetItemBase):
    id: int
    account_name: Optional[str] = None
    account_number: Optional[str] = None


class BudgetCreate(BaseModel):
    name: str
    start_date: date
    end_date: date
    description: Optional[str] = None
    branch_id: Optional[int] = None
    cost_center_id: Optional[int] = None


class BudgetResponse(BudgetCreate):
    id: int
    status: str
    created_at: str


class BudgetReportItem(BaseModel):
    account_id: int
    account_number: str
    account_name: str
    planned: Decimal
    actual: Decimal
    variance: Decimal
    usage_percentage: Decimal
    usage_percentage_capped: Decimal
    variance_percentage: Decimal
    is_over_budget: bool
