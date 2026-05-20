"""Performance review module Pydantic schemas."""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date, datetime
from decimal import Decimal


# ---------- Review Cycles ----------

class ReviewCycleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    period_start: date
    period_end: date
    self_assessment_deadline: Optional[date] = None
    manager_review_deadline: Optional[date] = None


class ReviewCycleRead(BaseModel):
    id: int
    name: str
    period_start: date
    period_end: date
    self_assessment_deadline: Optional[date] = None
    manager_review_deadline: Optional[date] = None
    status: str = "draft"
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None
    total_reviews: int = 0
    completed_reviews: int = 0


# ---------- Goals ----------

class GoalCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: Optional[str] = None
    weight: Decimal = Field(ge=0, le=100)
    target: Optional[str] = None


class GoalRead(BaseModel):
    id: int
    review_id: int
    title: str
    description: Optional[str] = None
    weight: Decimal
    target: Optional[str] = None


# ---------- Reviews ----------

class GoalScore(BaseModel):
    goal_id: int
    score: Decimal = Field(ge=0, le=5)
    comments: Optional[str] = None


class SelfAssessmentSubmit(BaseModel):
    scores: List[GoalScore]
    overall_comments: Optional[str] = None


class ManagerAssessmentSubmit(BaseModel):
    scores: List[GoalScore]
    overall_comments: Optional[str] = None


class ReviewRead(BaseModel):
    id: int
    cycle_id: Optional[int] = None
    cycle_name: Optional[str] = None
    employee_id: Optional[int] = None
    employee_name: Optional[str] = None
    reviewer_id: Optional[int] = None
    reviewer_name: Optional[str] = None
    status: Optional[str] = None
    review_period: Optional[str] = None
    review_date: Optional[date] = None
    self_assessment: Optional[list] = None
    manager_assessment: Optional[list] = None
    composite_score: Optional[Decimal] = None
    final_comments: Optional[str] = None
    goals: Optional[List[GoalRead]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
