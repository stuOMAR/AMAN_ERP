"""
AMAN ERP - Human Resources Module
الموارد البشرية

Sub-modules:
  core (/hr) — employees, departments, payroll, attendance, leaves, etc.
  advanced (/hr-advanced) — performance, training, violations, custody, recruitment
"""

from fastapi import APIRouter

from .core import router as hr_router
from .advanced import router as hr_advanced_router
from .self_service import router as self_service_router
from .performance import router as performance_router
from .advances import router as advances_router  # T15 — salary advances

# Combined router — each sub-module keeps its own prefix
router = APIRouter()
router.include_router(hr_router)
router.include_router(hr_advanced_router)
router.include_router(self_service_router)
router.include_router(performance_router)
router.include_router(advances_router)
