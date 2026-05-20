"""Parties module Pydantic schemas - unified Customer/Supplier model."""
from pydantic import BaseModel, ConfigDict
from typing import Optional
from decimal import Decimal


class PartyCreate(BaseModel):
    """Unified create schema for both customers and suppliers.
    Both are stored in the `parties` table with different `party_type` values.
    """
    name: str
    name_en: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    tax_number: Optional[str] = None
    contact_person: Optional[str] = None
    credit_limit: Decimal = Decimal("0")
    payment_terms: Optional[int] = 30
    notes: Optional[str] = None
    group_id: Optional[int] = None
    branch_id: Optional[int] = None
    currency: Optional[str] = None


class PartyResponse(BaseModel):
    id: int
    name: str
    name_en: Optional[str] = None
    party_type: str
    email: Optional[str] = None
    phone: Optional[str] = None
    tax_number: Optional[str] = None
    address: Optional[str] = None
    balance: Decimal
    credit_limit: Optional[Decimal] = None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


# Backward-compatible aliases
CustomerCreate = PartyCreate
SupplierCreate = PartyCreate
