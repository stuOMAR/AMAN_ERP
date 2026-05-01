"""projects router package — aggregates split sub-routers (T6.3)."""
from fastapi import APIRouter
from fastapi import Depends
from utils.permissions import require_module

from .core import router as _core_router
from .timetracking import router as _timetracking_router
from .resources import router as _resources_router
from .finance import router as _finance_router
from .monitoring import router as _monitoring_router
from .tasks import router as _tasks_router
from .change_orders import router as _change_orders_router
from .risks import router as _risks_router

router = APIRouter(prefix="/projects", tags=['Projects'], dependencies=[Depends(require_module("projects"))])
router.include_router(_core_router)
router.include_router(_timetracking_router)
router.include_router(_resources_router)
router.include_router(_finance_router)
router.include_router(_monitoring_router)
router.include_router(_tasks_router)
router.include_router(_change_orders_router)
router.include_router(_risks_router)

__all__ = ["router"]
