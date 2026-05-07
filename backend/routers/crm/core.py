"""crm sub-router — split from monolithic crm.py (T6.3).

Mounted under the parent router via crm/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from utils.i18n import http_error
from sqlalchemy import text
from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel
import logging
from database import get_db_connection
from routers.auth import get_current_user
from utils.tx import transactional
from utils.permissions import require_permission, require_module, validate_branch_access
from utils.accounting import generate_sequential_number
from utils.audit import log_activity
from utils.sql_builder import validate_update_keys
from services.notification_service import notification_service
from schemas.campaign import CampaignCreate, TrackingWebhookPayload

logger = logging.getLogger(__name__)

router = APIRouter()

class OpportunityCreate(BaseModel):
    title: str
    customer_id: Optional[int] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    stage: str = "lead"
    probability: int = 10
    expected_value: float = 0
    expected_close_date: Optional[str] = None
    currency: Optional[str] = None
    source: Optional[str] = None
    assigned_to: Optional[int] = None
    branch_id: Optional[int] = None
    notes: Optional[str] = None

class OpportunityUpdate(BaseModel):
    title: Optional[str] = None
    stage: Optional[str] = None
    probability: Optional[int] = None
    expected_value: Optional[float] = None
    expected_close_date: Optional[str] = None
    assigned_to: Optional[int] = None
    notes: Optional[str] = None
    lost_reason: Optional[str] = None

class ActivityCreate(BaseModel):
    activity_type: str  # call, email, meeting, note, task
    title: str
    contact_id: Optional[int] = None
    description: Optional[str] = None
    due_date: Optional[str] = None
    # T10.2 #151: completion-tracking fields. ``is_completed`` maps to
    # the existing ``completed`` BOOLEAN column on opportunity_activities.
    outcome: Optional[str] = None        # e.g. won, lost, follow_up, no_answer
    duration_minutes: Optional[int] = None
    is_completed: Optional[bool] = None


class ActivityUpdate(BaseModel):
    """T10.2 #150: partial-update payload for opportunity_activities.

    All fields optional — caller sets only what changes (typical use:
    mark an activity complete with outcome + duration_minutes).
    """
    activity_type: Optional[str] = None
    title: Optional[str] = None
    contact_id: Optional[int] = None
    description: Optional[str] = None
    due_date: Optional[str] = None
    outcome: Optional[str] = None
    duration_minutes: Optional[int] = None
    is_completed: Optional[bool] = None

class TicketCreate(BaseModel):
    subject: str
    description: Optional[str] = None
    customer_id: Optional[int] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    priority: str = "medium"
    category: Optional[str] = None
    assigned_to: Optional[int] = None
    branch_id: Optional[int] = None
    sla_hours: int = 24

class TicketUpdate(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    assigned_to: Optional[int] = None
    resolution: Optional[str] = None

class CommentCreate(BaseModel):
    comment: str
    is_internal: bool = False
    attachment_url: Optional[str] = None


# Valid stages and their probabilities
OPPORTUNITY_STAGES = {
    "lead": 10,
    "qualified": 25,
    "proposal": 50,
    "negotiation": 75,
    "won": 100,
    "lost": 0
}

# Whitelist of fields that may be updated via update_opportunity (FR-008)
OPPORTUNITY_ALLOWED_FIELDS = {
    "title", "stage", "probability", "expected_value",
    "expected_close_date", "assigned_to", "notes", "lost_reason"
}


# ======================== CRM-002: Sales Opportunities ========================

class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    campaign_type: Optional[str] = None
    status: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    budget: Optional[float] = None
    target_audience: Optional[str] = None
    description: Optional[str] = None
    segment_id: Optional[int] = None
    subject: Optional[str] = None
    content: Optional[str] = None
    scheduled_date: Optional[str] = None
    estimated_cost: Optional[float] = None


class ArticleCreate(BaseModel):
    title: str
    category: str = "general"  # faq, guide, policy, general
    content: str
    tags: Optional[str] = None
    is_published: bool = False

class ArticleUpdate(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[str] = None
    is_published: Optional[bool] = None


class LeadScoringRuleCreate(BaseModel):
    rule_name: str
    field_name: str  # stage, source, expected_value, customer_id, etc.
    operator: str = "equals"  # equals, greater_than, less_than, contains, exists
    field_value: Optional[str] = None
    score: int = 0

class LeadScoringRuleUpdate(BaseModel):
    rule_name: Optional[str] = None
    field_name: Optional[str] = None
    operator: Optional[str] = None
    field_value: Optional[str] = None
    score: Optional[int] = None
    is_active: Optional[bool] = None


class SegmentCreate(BaseModel):
    name: str
    description: Optional[str] = None
    criteria: Optional[dict] = {}
    color: str = "#3B82F6"
    auto_assign: bool = False

class SegmentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    criteria: Optional[dict] = None
    color: Optional[str] = None
    auto_assign: Optional[bool] = None
    is_active: Optional[bool] = None


class ContactCreate(BaseModel):
    customer_id: int
    first_name: str
    last_name: Optional[str] = None
    job_title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    department: Optional[str] = None
    is_primary: bool = False
    is_decision_maker: bool = False
    notes: Optional[str] = None

class ContactUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    job_title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    department: Optional[str] = None
    is_primary: Optional[bool] = None
    is_decision_maker: Optional[bool] = None
    notes: Optional[str] = None


