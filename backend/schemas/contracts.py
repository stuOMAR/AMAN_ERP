from pydantic import BaseModel, ConfigDict
from typing import List, Optional
from datetime import date, datetime
from decimal import Decimal

class ContractItemBase(BaseModel):
    product_id: int
    description: Optional[str] = None
    quantity: Decimal
    unit_price: Decimal
    tax_rate: Optional[Decimal] = None

class ContractItemCreate(ContractItemBase):
    pass

class ContractItemResponse(ContractItemBase):
    id: int
    contract_id: int
    total: Decimal
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ContractBase(BaseModel):
    contract_number: str
    party_id: int
    contract_type: str = "subscription"
    start_date: date
    end_date: Optional[date] = None
    billing_interval: str = "monthly"
    total_amount: Decimal = Decimal(0)
    currency: Optional[str] = None
    notes: Optional[str] = None

class ContractCreate(ContractBase):
    items: List[ContractItemCreate]

class ContractUpdate(BaseModel):
    """All-Optional schema for partial contract updates (PATCH-style via PUT)."""
    contract_number: Optional[str] = None
    party_id: Optional[int] = None
    contract_type: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    billing_interval: Optional[str] = None
    currency: Optional[str] = None
    notes: Optional[str] = None
    items: Optional[List[ContractItemCreate]] = None

class ContractAmendmentCreate(BaseModel):
    """Typed schema for contract amendments — replaces raw dict."""
    amendment_type: str = "modification"
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    description: Optional[str] = None
    effective_date: Optional[date] = None
    amount_change: Optional[Decimal] = None

class ContractResponse(ContractBase):
    id: int
    status: str
    next_billing_date: Optional[date] = None
    created_by: Optional[int] = None
    created_at: datetime
    items: List[ContractItemResponse]
    party_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
