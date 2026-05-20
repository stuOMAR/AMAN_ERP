"""Costing Policies module Pydantic schemas."""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from decimal import Decimal


class CostingPolicySet(BaseModel):
    policy_type: str
    reason: Optional[str] = None


class CostingPolicyHistoryResponse(BaseModel):
    old_policy_type: Optional[str]
    new_policy_type: str
    change_date: datetime
    reason: Optional[str]
    changed_by_name: Optional[str]
    affected_products_count: Optional[int]
    total_cost_impact: Optional[Decimal]
    status: str
