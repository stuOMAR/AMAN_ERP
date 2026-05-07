"""Treasury module Pydantic schemas."""
from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import date


class TreasuryAccountCreate(BaseModel):
    name: str
    name_en: Optional[str] = None
    account_type: str
    currency: str = ""
    branch_id: Optional[int] = None
    bank_name: Optional[str] = None
    account_number: Optional[str] = None
    iban: Optional[str] = None
    opening_balance: Optional[float] = 0.0
    exchange_rate: Optional[float] = 1.0
    allow_overdraft: bool = False


class TreasuryAccountResponse(TreasuryAccountCreate):
    id: int
    current_balance: float
    balance_in_currency: Optional[float] = 0.0
    gl_account_id: Optional[int] = None
    branch_name: Optional[str] = None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class TransactionCreate(BaseModel):
    transaction_date: date
    transaction_type: str
    amount: float
    treasury_id: int
    target_account_id: Optional[int] = None
    description: str
    target_treasury_id: Optional[int] = None
    reference_number: Optional[str] = None
    branch_id: Optional[int] = None
    exchange_rate: Optional[float] = 1.0


class TransactionResponse(BaseModel):
    id: int
    transaction_number: Optional[str]
    transaction_date: date
    transaction_type: str
    amount: float
    description: Optional[str]
    treasury_name: Optional[str]
    target_name: Optional[str]
    status: str
    created_at: str
