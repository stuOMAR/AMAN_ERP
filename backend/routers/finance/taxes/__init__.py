"""taxes router package — aggregates split sub-routers (T6.3)."""
from fastapi import APIRouter
from fastapi import Depends
from utils.permissions import require_module

from .core import router as _core_router
from .rates import router as _rates_router
from .groups import router as _groups_router
from .returns_ import router as _returns__router
from .payments import router as _payments_router
from .reports import router as _reports_router
from .calendar import router as _calendar_router

router = APIRouter(prefix="/taxes", tags=['Taxes'], dependencies=[Depends(require_module("taxes"))])
router.include_router(_core_router)
router.include_router(_rates_router)
router.include_router(_groups_router)
router.include_router(_returns__router)
router.include_router(_payments_router)
router.include_router(_reports_router)
router.include_router(_calendar_router)

__all__ = ["router"]
