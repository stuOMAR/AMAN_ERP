"""MRP schemas for Feature 023.

T079: MrpRunRequest, MrpRunResponse, RecommendationView, AcceptResponse, BomCycleErrorBody
"""
from __future__ import annotations

from pydantic import BaseModel
from typing import Optional


class MrpRunRequest(BaseModel):
    pass  # No body needed for a run


class MrpRunResponse(BaseModel):
    run_id: str
    recommendations_created: int
    duration_ms: int


class RecommendationView(BaseModel):
    id: int
    run_id: str
    item_id: int
    warehouse_id: int
    recommended_qty: float
    state: str
    source: Optional[str] = None
    created_at: str


class AcceptResponse(BaseModel):
    id: int
    item_id: int
    warehouse_id: int
    recommended_qty: float


class BomCycleErrorBody(BaseModel):
    code: str = "mfg.bom.cycle_detected"
    message: str
    cycle_path: list[int]
