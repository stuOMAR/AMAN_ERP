"""core router package — aggregates split sub-routers (T6.3)."""
from fastapi import APIRouter
from fastapi import Depends
from utils.permissions import require_module

from .core import router as _core_router
from .employees import router as _employees_router
from .payroll import router as _payroll_router
from .departments import router as _departments_router
from .attendance import router as _attendance_router
from .leaves import router as _leaves_router
from .recruitment import router as _recruitment_router

router = APIRouter(prefix="/hr", tags=['HR & Employees'], dependencies=[Depends(require_module("hr"))])
router.include_router(_core_router)
router.include_router(_employees_router)
router.include_router(_payroll_router)
router.include_router(_departments_router)
router.include_router(_attendance_router)
router.include_router(_leaves_router)
router.include_router(_recruitment_router)

__all__ = ["router"]
