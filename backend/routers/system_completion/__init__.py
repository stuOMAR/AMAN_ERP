"""system_completion router package — aggregates split sub-routers (T6.3)."""
from fastapi import APIRouter

from .core import router as _core_router
from .treasury import router as _treasury_router
from .accounting import router as _accounting_router
from .reports import router as _reports_router
from .admin import router as _admin_router
from .settings import router as _settings_router

router = APIRouter(prefix="", tags=['System Completion'])
router.include_router(_core_router)
router.include_router(_treasury_router)
router.include_router(_accounting_router)
router.include_router(_reports_router)
router.include_router(_admin_router)
router.include_router(_settings_router)

__all__ = ["router"]
