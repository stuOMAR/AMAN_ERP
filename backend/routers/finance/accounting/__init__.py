"""accounting router package — aggregates split sub-routers (T6.3)."""
from fastapi import APIRouter

from .core import router as _core_router
from .accounts import router as _accounts_router
from .journal import router as _journal_router
from .fiscal import router as _fiscal_router
from .recurring import router as _recurring_router
from .provisions import router as _provisions_router
from .fx import router as _fx_router

router = APIRouter(prefix="/accounting", tags=['Accounting'])
router.include_router(_core_router)
router.include_router(_accounts_router)
router.include_router(_journal_router)
router.include_router(_fiscal_router)
router.include_router(_recurring_router)
router.include_router(_provisions_router)
router.include_router(_fx_router)

__all__ = ["router"]
