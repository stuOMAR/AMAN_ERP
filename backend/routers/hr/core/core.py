"""core sub-router — split from monolithic core.py (T6.3).

Mounted under the parent router via core/__init__.py.
"""
from fastapi import APIRouter, Depends, HTTPException
from utils.i18n import http_error
from sqlalchemy import text
from typing import Optional, Any
from pydantic import BaseModel
from datetime import date
from decimal import Decimal
import logging
from routers.auth import get_current_user, UserResponse, get_current_user_company
from utils.tx import transactional
from utils.permissions import check_permission, require_module

logger = logging.getLogger(__name__)
_D2 = Decimal('0.01')

def _dec(v: Any) -> Decimal:
    return Decimal(str(v or 0))

router = APIRouter()

def _dec(v: Any) -> Decimal:
    return Decimal(str(v or 0))

router = APIRouter(prefix="/hr", tags=["HR & Employees"], dependencies=[Depends(require_module("hr"))])

# --- Helpers ---

def has_permission(user: UserResponse, permission: str) -> bool:
    """Helper to check permissions for a user object"""
    user_perms = getattr(user, 'permissions', []) or []
    return check_permission(user_perms, permission)

# get_current_user_company moved to routers.auth

# --- Endpoints ---

def get_current_employee(
    current_user: UserResponse = Depends(get_current_user),
    company_id: str = Depends(get_current_user_company)
):
    with transactional(company_id) as conn:
        emp = conn.execute(
            text("SELECT id, first_name, last_name, status FROM employees WHERE user_id = :uid"), 
            {"uid": current_user.get("id") if isinstance(current_user, dict) else current_user.id}
        ).fetchone()
        
        if not emp:
            raise HTTPException(**http_error(404, "employee_records_not_linked"))
        
        # Access by index since it's a Row object/tuple
        if emp[3] != 'active': # status
             raise HTTPException(**http_error(400, "employee_not_active"))
             
        return emp

class PayslipGenerateRequest(BaseModel):
    employee_id: int
    month: int
    year: int
    submitted_grand_total: Optional[Decimal] = None



class JobOpeningCreate(BaseModel):
    title: str
    department: Optional[str] = None
    positions: int = 1
    requirements: Optional[str] = None
    deadline: Optional[date] = None
    description: Optional[str] = None
    employment_type: str = "full_time"


class JobOpeningUpdate(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None
    positions: Optional[int] = None
    requirements: Optional[str] = None
    deadline: Optional[date] = None


class ApplicationCreate(BaseModel):
    job_opening_id: int
    applicant_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    resume_url: Optional[str] = None
    cover_letter: Optional[str] = None


class ApplicationStageUpdate(BaseModel):
    stage: str


class LeaveCarryoverRequest(BaseModel):
    employee_id: int
    year: Optional[int] = None


