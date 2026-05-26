"""Taxes module Pydantic schemas."""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import date
from decimal import Decimal


class TaxRateCreate(BaseModel):
    tax_code: str = Field(..., min_length=1, max_length=50)
    tax_name: str = Field(..., min_length=1, max_length=255)
    tax_name_en: Optional[str] = None
    rate_type: str = "percentage"
    rate_value: Decimal = Decimal("0")
    country_code: Optional[str] = None
    description: Optional[str] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    is_active: bool = True


class TaxRateUpdate(BaseModel):
    tax_name: Optional[str] = None
    tax_name_en: Optional[str] = None
    rate_value: Optional[Decimal] = None
    country_code: Optional[str] = None
    description: Optional[str] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    is_active: Optional[bool] = None
    reason: Optional[str] = None


class TaxGroupCreate(BaseModel):
    group_code: str = Field(..., min_length=1, max_length=50)
    group_name: str = Field(..., min_length=1, max_length=255)
    group_name_en: Optional[str] = None
    description: Optional[str] = None
    tax_ids: list = []
    is_active: bool = True


class TaxReturnCreate(BaseModel):
    tax_period: str = Field(..., min_length=1)
    tax_type: str = Field(default="vat")
    due_date: Optional[date] = None
    notes: Optional[str] = None
    branch_id: Optional[int] = None
    submitted_tax_due: Optional[Decimal] = None
    submitted_grand_total: Optional[Decimal] = None


class TaxPaymentCreate(BaseModel):
    tax_return_id: int
    payment_date: date
    amount: Decimal
    payment_method: str = "bank_transfer"
    reference: Optional[str] = None
    notes: Optional[str] = None
    treasury_account_id: Optional[int] = None
