"""POS offline schemas for Feature 023.

T051: OfflineBatchSubmit, OfflineBatchView
"""
from __future__ import annotations

from pydantic import BaseModel
from typing import Optional
from decimal import Decimal


class OfflineBatchLine(BaseModel):
    product_id: int
    quantity: Decimal
    unit_price: Decimal


class OfflineBatchSubmit(BaseModel):
    device_id: str
    client_uuid: str
    warehouse_id: int
    lines: list[OfflineBatchLine]


class OfflineBatchView(BaseModel):
    id: int
    device_id: str
    client_uuid: str
    state: str
    failure_reason_code: Optional[str] = None
    failure_detail: Optional[str] = None
    pos_sale_id: Optional[int] = None
    queued_at: str
    processed_at: Optional[str] = None
