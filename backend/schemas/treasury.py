"""Treasury module Pydantic schemas."""
from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import date
from decimal import Decimal


class TreasuryAccountCreate(BaseModel):
    name: str
    name_en: Optional[str] = None
    account_type: str
    currency: str = ""
    branch_id: Optional[int] = None
    bank_name: Optional[str] = None
    account_number: Optional[str] = None
    iban: Optional[str] = None
    opening_balance: Optional[Decimal] = Decimal("0.0")
    allow_overdraft: bool = False


class TreasuryAccountResponse(TreasuryAccountCreate):
    id: int
    current_balance: Decimal
    balance_in_currency: Optional[Decimal] = Decimal("0.0")
    current_balance_direction: Optional[str] = None
    balance_in_currency_direction: Optional[str] = None
    gl_account_id: Optional[int] = None
    branch_name: Optional[str] = None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class TransactionCreate(BaseModel):
    transaction_date: date
    transaction_type: str
    amount: Decimal
    treasury_id: int
    target_account_id: Optional[int] = None
    description: str
    target_treasury_id: Optional[int] = None
    reference_number: Optional[str] = None
    branch_id: Optional[int] = None
    cost_center_id: Optional[int] = None


class TransactionResponse(BaseModel):
    id: int
    transaction_number: Optional[str]
    transaction_date: date
    transaction_type: str
    amount: Decimal
    description: Optional[str]
    treasury_name: Optional[str]
    target_name: Optional[str]
    status: str
    created_at: str
