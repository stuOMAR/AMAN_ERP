"""Campaign module Pydantic schemas."""

from pydantic import BaseModel, ConfigDict, Field
from typing import Optional
from datetime import date, datetime
from decimal import Decimal


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    campaign_type: str = Field(default="email", pattern=r"^(email|sms|both|social|event)$")
    status: str = Field(default="draft", pattern=r"^(draft|scheduled|active|paused|completed|executing)$")
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    segment_id: Optional[int] = None
    subject: Optional[str] = Field(None, max_length=500)
    content: Optional[str] = None
    scheduled_date: Optional[datetime] = None
    estimated_cost: Optional[Decimal] = Field(None, ge=0)
    budget: Optional[Decimal] = Field(None, ge=0)
    target_audience: Optional[str] = None
    branch_id: Optional[int] = None
    description: Optional[str] = None


class CampaignRead(BaseModel):
    id: int
    name: str
    campaign_type: Optional[str] = None
    segment_id: Optional[int] = None
    segment_name: Optional[str] = None
    subject: Optional[str] = None
    content: Optional[str] = None
    scheduled_date: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    status: Optional[str] = None
    total_sent: int = 0
    total_delivered: int = 0
    total_opened: int = 0
    total_clicked: int = 0
    total_responded: int = 0
    estimated_cost: Optional[Decimal] = None
    actual_cost: Optional[Decimal] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CampaignMetrics(BaseModel):
    campaign_id: int
    name: str
    total_sent: int = 0
    total_delivered: int = 0
    total_opened: int = 0
    total_clicked: int = 0
    total_responded: int = 0
    delivery_rate: Decimal = Decimal("0.0")
    open_rate: Decimal = Decimal("0.0")
    click_rate: Decimal = Decimal("0.0")
    response_rate: Decimal = Decimal("0.0")
    estimated_cost: Optional[Decimal] = None
    actual_cost: Optional[Decimal] = None
    cost_per_lead: Optional[Decimal] = None


class RecipientStatusRead(BaseModel):
    id: int
    contact_id: int
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    channel: Optional[str] = None
    delivery_status: Optional[str] = None
    opened_at: Optional[datetime] = None
    clicked_at: Optional[datetime] = None
    responded_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CampaignExecuteRequest(BaseModel):
    send_immediately: bool = True


class TrackingWebhookPayload(BaseModel):
    recipient_id: int
    event: str = Field(pattern=r"^(delivered|opened|clicked|responded|bounced|failed)$")
    signature: str
