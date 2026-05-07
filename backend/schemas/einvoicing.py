"""Einvoicing schemas for Feature 023.

T068: OutboxRowView, ReprocessResponse
"""
from __future__ import annotations

from pydantic import BaseModel
from typing import Optional


class OutboxRowView(BaseModel):
    id: int
    invoice_id: int
    state: str
    attempts: int
    max_attempts: int
    last_error: Optional[str] = None
    next_attempt_at: Optional[str] = None
    created_at: str


class ReprocessResponse(BaseModel):
    id: int
    state: str
