"""Currencies module Pydantic schemas."""
from pydantic import BaseModel
from typing import Optional
from datetime import date
from decimal import Decimal


class RevaluationRequest(BaseModel):
    currency_id: int
    rate_date: date
    new_rate: Decimal
    description: Optional[str] = None


class FXPreviewRequest(BaseModel):
    source_currency: str
    target_currency: str
    amount: Decimal = Decimal("0")
    branch_id: Optional[int] = None
