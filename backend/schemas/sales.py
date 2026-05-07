"""Sales schemas for Feature 023.

T034: OrderToInvoiceRequest/Response
T040: CancellationRequest/Response
"""
from __future__ import annotations

from pydantic import BaseModel
from typing import Optional


class OrderToInvoiceRequest(BaseModel):
    posting_date: Optional[str] = None
    memo: Optional[str] = None


class OrderToInvoiceResponse(BaseModel):
    id: int
    state: str
    invoice_type: str
    invoice_date: str
    party_id: int
    sales_order_id: Optional[int] = None
    idempotency_key: Optional[str] = None
    gl_je_id: Optional[int] = None
    zatca_outbox_id: Optional[int] = None


class Shortage(BaseModel):
    item_id: int
    warehouse_id: int
    required: float
    available: float


class CancellationRequest(BaseModel):
    reason: Optional[str] = None
    restock_warehouse_id: Optional[int] = None


class CancellationResponse(BaseModel):
    id: int
    state: str
    shortages: Optional[list[Shortage]] = None
