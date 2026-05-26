"""Pydantic schemas for US17 — Time Tracking."""

from datetime import date
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, field_validator


class TimesheetEntryCreate(BaseModel):
    employee_id: Optional[int] = None
    project_id: int
    task_id: Optional[int] = None
    date: date
    hours: Decimal
    is_billable: bool = True
    billing_rate: Optional[Decimal] = None
    description: Optional[str] = None

    @field_validator('hours')
    @classmethod
    def hours_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0 or v > 24:
            raise ValueError('hours must be > 0 and <= 24')
        return v


class TimesheetEntryRead(BaseModel):
    id: int
    employee_id: int
    employee_name: Optional[str] = None
    project_id: int
    project_name: Optional[str] = None
    task_id: Optional[int] = None
    task_name: Optional[str] = None
    date: date
    hours: Decimal
    is_billable: bool
    billing_rate: Optional[Decimal] = None
    description: Optional[str] = None
    status: str
    approved_by: Optional[int] = None
    approver_name: Optional[str] = None
    rejection_reason: Optional[str] = None

    class Config:
        from_attributes = True


class TimesheetEntryUpdate(BaseModel):
    task_id: Optional[int] = None
    date: Optional[date] = None
    hours: Optional[Decimal] = None
    is_billable: Optional[bool] = None
    billing_rate: Optional[Decimal] = None
    description: Optional[str] = None

    @field_validator('hours')
    @classmethod
    def hours_must_be_positive(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and (v <= 0 or v > 24):
            raise ValueError('hours must be > 0 and <= 24')
        return v


class WeeklySubmitRequest(BaseModel):
    week_start: date   # Monday of the week
    employee_id: Optional[int] = None


class RejectRequest(BaseModel):
    rejection_reason: str


class ProfitabilityReport(BaseModel):
    project_id: int
    project_name: str
    planned_budget: Decimal
    total_hours: Decimal
    billable_hours: Decimal
    non_billable_hours: Decimal
    billable_revenue: Decimal
    total_expenses: Decimal
    total_cost: Decimal
    profit: Decimal
    margin_pct: Decimal
