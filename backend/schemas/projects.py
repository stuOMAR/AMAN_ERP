"""Projects module Pydantic schemas."""
from pydantic import BaseModel
from typing import Optional, List, Literal
from datetime import date
from decimal import Decimal


class ProjectCreate(BaseModel):
    project_name: str
    project_code: Optional[str] = None
    project_name_en: Optional[str] = None
    description: Optional[str] = None
    project_type: Optional[str] = "internal"
    customer_id: Optional[int] = None
    manager_id: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    planned_budget: Decimal = Decimal(0)
    status: str = "planning"
    branch_id: Optional[int] = None
    contract_type: Optional[str] = "fixed_price"


class ProjectUpdate(BaseModel):
    project_name: Optional[str] = None
    project_name_en: Optional[str] = None
    description: Optional[str] = None
    project_type: Optional[str] = None
    customer_id: Optional[int] = None
    manager_id: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    planned_budget: Optional[Decimal] = None
    status: Optional[str] = None
    progress_percentage: Optional[Decimal] = None


class TaskCreate(BaseModel):
    task_name: str
    task_name_en: Optional[str] = None
    description: Optional[str] = None
    parent_task_id: Optional[int] = None
    assigned_to: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    planned_hours: Decimal = Decimal("0")
    status: str = "pending"


class TaskUpdate(BaseModel):
    task_name: Optional[str] = None
    description: Optional[str] = None
    assigned_to: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    planned_hours: Optional[Decimal] = None
    actual_hours: Optional[Decimal] = None
    progress: Optional[Decimal] = None
    status: Optional[str] = None


class ProjectExpenseCreate(BaseModel):
    expense_type: str
    expense_date: date
    amount: Decimal
    description: Optional[str] = None
    treasury_id: Optional[int] = None
    expense_account_id: Optional[int] = None


class ProjectRevenueCreate(BaseModel):
    revenue_type: str
    revenue_date: date
    amount: Decimal
    description: Optional[str] = None
    invoice_id: Optional[int] = None


class TimesheetCreate(BaseModel):
    project_id: int
    task_id: Optional[int] = None
    date: date
    hours: Decimal
    description: Optional[str] = None
    status: str = "draft"


class TimesheetUpdate(BaseModel):
    task_id: Optional[int] = None
    date: Optional[date] = None
    hours: Optional[Decimal] = None
    description: Optional[str] = None
    status: Optional[str] = None


class TimesheetApprove(BaseModel):
    timesheet_ids: List[int]


class ProjectDocumentCreate(BaseModel):
    file_name: str
    file_type: str


class ProjectInvoiceItem(BaseModel):
    product_id: Optional[int] = None
    description: str
    quantity: Decimal = Decimal("1.0")
    unit_price: Decimal
    tax_rate: Decimal = Decimal("0.0")
    discount: Decimal = Decimal(0)


class ProjectInvoiceCreate(BaseModel):
    customer_id: int
    warehouse_id: Optional[int] = None
    invoice_date: date
    due_date: date
    items: List[ProjectInvoiceItem]
    notes: Optional[str] = None
    payment_method: Optional[str] = "credit"
    currency: Optional[str] = None
    exchange_rate: Optional[Decimal] = Decimal(1)


class ChangeOrderCreate(BaseModel):
    title: str
    description: Optional[str] = None
    change_type: str = "scope"      # scope, budget, timeline, requirement
    cost_impact: Decimal = Decimal(0)
    time_impact_days: int = 0


class ChangeOrderUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    change_type: Optional[str] = None
    cost_impact: Optional[Decimal] = None
    time_impact_days: Optional[int] = None
    status: Optional[str] = None


class ProjectCloseRequest(BaseModel):
    close_date: Optional[date] = None
    notes: Optional[str] = None


class ProjectRiskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    probability: Literal["low", "medium", "high", "critical"] = "medium"
    impact: Literal["low", "medium", "high", "critical"] = "medium"
    status: str = "identified"
    mitigation_plan: Optional[str] = None
    owner_id: Optional[int] = None
    due_date: Optional[date] = None


class ProjectRiskUpdate(BaseModel):
    """All-Optional schema for risk updates — replaces raw dict."""
    title: Optional[str] = None
    description: Optional[str] = None
    probability: Optional[Literal["low", "medium", "high", "critical"]] = None
    impact: Optional[Literal["low", "medium", "high", "critical"]] = None
    status: Optional[str] = None
    mitigation_plan: Optional[str] = None
    owner_id: Optional[int] = None
    due_date: Optional[date] = None


class TaskDependencyCreate(BaseModel):
    """Typed schema for task dependencies — replaces raw dict."""
    task_id: int
    depends_on_task_id: int
    dependency_type: str = "FS"
    lag_days: int = 0
