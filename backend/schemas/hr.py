"""HR module Pydantic schemas."""
from decimal import Decimal
from pydantic import BaseModel, ConfigDict
from typing import List, Optional
from datetime import date, datetime


class LoanCreate(BaseModel):
    employee_id: int
    amount: Decimal
    total_installments: int
    start_date: date
    reason: Optional[str] = None


class LoanResponse(LoanCreate):
    id: int
    monthly_installment: Decimal
    paid_amount: Decimal
    status: str
    created_at: datetime
    employee_name: Optional[str] = None


class EmployeeCreate(BaseModel):
    employee_code: Optional[str] = None
    first_name: str
    last_name: str
    first_name_en: Optional[str] = None
    last_name_en: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    position_title: Optional[str] = None
    department_name: Optional[str] = None
    salary: Decimal = Decimal("0")
    housing_allowance: Decimal = Decimal("0")
    transport_allowance: Decimal = Decimal("0")
    other_allowances: Decimal = Decimal("0")
    hourly_cost: Decimal = Decimal("0")
    hire_date: Optional[date] = None
    create_user: bool = False
    username: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    currency: Optional[str] = None
    nationality: Optional[str] = None
    create_ledger: bool = False
    branch_id: Optional[int] = None
    allowed_branch_ids: Optional[List[int]] = None


class EmployeeUpdate(BaseModel):
    employee_code: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    position_title: Optional[str] = None
    department_name: Optional[str] = None
    salary: Optional[Decimal] = None
    housing_allowance: Optional[Decimal] = None
    transport_allowance: Optional[Decimal] = None
    other_allowances: Optional[Decimal] = None
    hourly_cost: Optional[Decimal] = None
    currency: Optional[str] = None
    nationality: Optional[str] = None
    branch_id: Optional[int] = None
    allowed_branch_ids: Optional[List[int]] = None
    role: Optional[str] = None


class EmployeeResponse(BaseModel):
    id: int
    employee_code: Optional[str] = None
    first_name: str
    last_name: str
    position: Optional[str] = None
    department: Optional[str] = None
    status: str
    user_id: Optional[int] = None
    account_id: Optional[int] = None
    branch_id: Optional[int] = None
    allowed_branches: List[int] = []
    role: Optional[str] = None
    hourly_cost: Decimal = Decimal("0")
    # PII fields — always masked in list/detail responses
    salary: Optional[str] = None
    salary_masked: bool = False
    iban: Optional[str] = None
    iban_masked: bool = False
    national_id: Optional[str] = None
    national_id_masked: bool = False
    passport_number: Optional[str] = None
    passport_number_masked: bool = False
    bank_account_number: Optional[str] = None
    bank_account_number_masked: bool = False
    gosi_number: Optional[str] = None
    gosi_number_masked: bool = False


class EmployeePiiOut(BaseModel):
    """Schema for the PII unmask endpoint — returns plaintext for a single field."""
    employee_id: int
    field: str
    value: str


class DepartmentCreate(BaseModel):
    department_name: str


class DepartmentResponse(BaseModel):
    id: int
    department_name: str


class PositionCreate(BaseModel):
    position_name: str
    department_id: Optional[int] = None


class PositionResponse(BaseModel):
    id: int
    position_name: str
    department_id: Optional[int] = None
    department_name: Optional[str] = None


class PayrollPeriodCreate(BaseModel):
    start_date: date
    end_date: date
    payment_date: Optional[date] = None
    name: str


class PayrollGenerate(BaseModel):
    period_id: int


class PayrollEntryResponse(BaseModel):
    id: int
    employee_name: str
    position: Optional[str] = None
    basic_salary: Decimal
    housing_allowance: Decimal
    transport_allowance: Decimal
    other_allowances: Decimal
    deductions: Decimal
    net_salary: Decimal
    status: Optional[str] = None
    currency: Optional[str] = None
    exchange_rate: Optional[Decimal] = Decimal("1")
    net_salary_base: Optional[Decimal] = None
    gosi_employee_share: Optional[Decimal] = Decimal("0")
    gosi_employer_share: Optional[Decimal] = Decimal("0")
    overtime_amount: Optional[Decimal] = Decimal("0")
    violation_deduction: Optional[Decimal] = Decimal("0")
    loan_deduction: Optional[Decimal] = Decimal("0")
    salary_components_earning: Optional[Decimal] = Decimal("0")
    salary_components_deduction: Optional[Decimal] = Decimal("0")


class PayrollPeriodResponse(BaseModel):
    id: int
    name: str
    start_date: date
    end_date: date
    status: str
    total_net: Decimal = Decimal("0")
    created_at: datetime


class AttendanceResponse(BaseModel):
    id: int
    employee_id: int
    date: date
    check_in: Optional[datetime] = None
    check_out: Optional[datetime] = None
    status: Optional[str] = None
    notes: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class LeaveRequestCreate(BaseModel):
    employee_id: Optional[int] = None
    leave_type: str
    start_date: date
    end_date: date
    reason: Optional[str] = None
    attachment_url: Optional[str] = None


class LeaveRequestResponse(BaseModel):
    id: int
    employee_id: int
    employee_name: Optional[str] = None
    leave_type: str
    start_date: date
    end_date: date
    reason: Optional[str] = None
    status: str
    created_at: datetime


class EndOfServiceRequest(BaseModel):
    employee_id: int
    termination_date: Optional[date] = None
    termination_reason: str = "resignation"
