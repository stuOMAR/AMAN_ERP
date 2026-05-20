"""Blanket Purchase Order Pydantic schemas."""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import date
from decimal import Decimal


class BlanketPOCreate(BaseModel):
    supplier_id: int
    total_quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(gt=0)
    valid_from: date
    valid_to: date
    branch_id: Optional[int] = None
    currency: Optional[str] = "SAR"
    notes: Optional[str] = None
    party_site_id: Optional[int] = None


class BlanketPORead(BaseModel):
    id: int
    supplier_id: int
    agreement_number: str
    total_quantity: Decimal
    unit_price: Decimal
    total_amount: Decimal
    released_quantity: Decimal
    released_amount: Decimal
    remaining_quantity: Decimal
    remaining_amount: Decimal
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    status: str
    price_amendment_history: Optional[list] = []
    branch_id: Optional[int] = None
    currency: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[str] = None
    created_by: Optional[str] = None

    class Config:
        from_attributes = True


class ReleaseOrderCreate(BaseModel):
    release_quantity: Decimal = Field(gt=0)
    release_date: Optional[date] = None
    notes: Optional[str] = None


class PriceAmendRequest(BaseModel):
    new_price: Decimal = Field(gt=0)
    effective_date: date
    reason: Optional[str] = None
