"""Manufacturing schemas for Feature 023.

T090: CompletionRequest, CompletionResponse, ApprovalResponse, ScrapLine, ByproductLine
T094: QcPassRequest, QcFailRequest
"""
from __future__ import annotations

from pydantic import BaseModel
from typing import Optional


class ScrapLine(BaseModel):
    item_id: int
    qty: float
    reason: str


class ByproductLine(BaseModel):
    item_id: int
    qty: float
    sales_value: Optional[float] = None


class CompletionRequest(BaseModel):
    qty: float
    warehouse_id: int
    scrap_lines: Optional[list[ScrapLine]] = None
    byproduct_lines: Optional[list[ByproductLine]] = None
    notes: Optional[str] = None


class CompletionResponse(BaseModel):
    mo_id: int
    completion_id: int
    qty_completed: float
    remaining_qty: float
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
