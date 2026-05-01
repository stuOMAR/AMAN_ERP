"""core router package — aggregates split sub-routers (T6.3)."""
from fastapi import APIRouter
from fastapi import Depends
from utils.permissions import require_module

from .work_centers import router as _work_centers_router
from .routes import router as _routes_router
from .boms import router as _boms_router
from .core import router as _core_router
from .orders import router as _orders_router
from .planning import router as _planning_router
from .equipment import router as _equipment_router
from .reports import router as _reports_router
from .quality import router as _quality_router

router = APIRouter(prefix="/manufacturing", tags=['Manufacturing (Phase 5)'], dependencies=[Depends(require_module("manufacturing"))])
router.include_router(_work_centers_router)
router.include_router(_routes_router)
router.include_router(_boms_router)
router.include_router(_core_router)
router.include_router(_orders_router)
router.include_router(_planning_router)
router.include_router(_equipment_router)
router.include_router(_reports_router)
router.include_router(_quality_router)

__all__ = ["router"]
