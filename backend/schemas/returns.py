"""Returns schemas for Feature 023.

T044: ReturnCreate, ReturnPost, ReturnView
"""
from __future__ import annotations

from decimal import Decimal
from pydantic import BaseModel
from typing import Optional


class ReturnLine(BaseModel):
    product_id: int
    quantity: Decimal
    unit_price: Optional[Decimal] = None
    warehouse_id: Optional[int] = None


class ReturnCreate(BaseModel):
    source: str  # 'sales' or 'pos'
    original_invoice_id: Optional[int] = None
    original_pos_sale_id: Optional[int] = None
    restock_warehouse_id: Optional[int] = None
    lines: list[ReturnLine]
    reason: Optional[str] = None


class ReturnPost(BaseModel):
    pass  # No body needed — endpoint just transitions state


class ReturnView(BaseModel):
    id: int
    source: str
    state: str
    original_invoice_id: Optional[int] = None
    original_pos_sale_id: Optional[int] = None
    restock_warehouse_id: Optional[int] = None
    reason: Optional[str] = None
    gl_je_id: Optional[int] = None
    created_at: str
