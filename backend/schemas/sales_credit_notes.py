"""Sales credit/debit notes module Pydantic schemas."""
from decimal import Decimal
from pydantic import BaseModel
from typing import Optional, List


class SalesNoteLine(BaseModel):
    quantity: Decimal = Decimal("1")
    unit_price: Decimal = Decimal("0")
    tax_rate: Decimal = Decimal("0")
    discount: Decimal = Decimal("0")
    product_id: Optional[int] = None
    description: str = ""


class SalesCreditNoteCreate(BaseModel):
    party_id: Optional[int] = None
    related_invoice_id: Optional[int] = None
    lines: List[SalesNoteLine] = []
    invoice_date: Optional[str] = None
    currency: Optional[str] = None
    exchange_rate: Decimal = Decimal("1")
    branch_id: Optional[int] = None
    notes: str = ""
    submitted_grand_total: Optional[Decimal] = None


class SalesDebitNoteCreate(BaseModel):
    party_id: Optional[int] = None
    related_invoice_id: Optional[int] = None
    lines: List[SalesNoteLine] = []
    invoice_date: Optional[str] = None
    currency: Optional[str] = None
    exchange_rate: Decimal = Decimal("1")
    branch_id: Optional[int] = None
    notes: str = ""
    submitted_grand_total: Optional[Decimal] = None
