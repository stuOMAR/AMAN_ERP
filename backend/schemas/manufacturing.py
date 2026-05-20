"""Manufacturing schemas for Feature 023.

T090: CompletionRequest, CompletionResponse, ApprovalResponse, ScrapLine, ByproductLine
T094: QcPassRequest, QcFailRequest
"""
from __future__ import annotations

from pydantic import BaseModel
from typing import Optional
from decimal import Decimal


class ScrapLine(BaseModel):
    item_id: int
    qty: Decimal
    reason: str


class ByproductLine(BaseModel):
    item_id: int
    qty: Decimal
    sales_value: Optional[Decimal] = None


class CompletionRequest(BaseModel):
    qty: Decimal
    warehouse_id: int
    scrap_lines: Optional[list[ScrapLine]] = None
    byproduct_lines: Optional[list[ByproductLine]] = None
    notes: Optional[str] = None


class CompletionResponse(BaseModel):
    mo_id: int
    completion_id: int
    qty_completed: Decimal
    remaining_qty: Decimal
    wip_to_fg_je_id: Optional[int] = None
    state: str


class ApprovalResponse(BaseModel):
    id: int
    state: str


class QcPassRequest(BaseModel):
    completion_ids: list[int]


class QcFailRequest(BaseModel):
    completion_ids: list[int]
    disposition: str  # 'scrap' or 'rework'
    reason: Optional[str] = None
