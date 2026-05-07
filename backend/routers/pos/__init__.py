"""pos router package — aggregates split sub-routers (T6.3)."""
from fastapi import APIRouter
from fastapi import Depends
from utils.permissions import require_module

from .core import router as _core_router
from .sessions import router as _sessions_router
from .orders import router as _orders_router
from .promotions import router as _promotions_router
from .loyalty import router as _loyalty_router
from .tables import router as _tables_router
from .kitchen import router as _kitchen_router
from .pwa import router as _pwa_router
from .sync import router as _sync_router  # T17 #88 \u2014 conflict resolution

router = APIRouter(prefix="/pos", tags=['Point of Sale'], dependencies=[Depends(require_module("pos"))])
router.include_router(_core_router)
router.include_router(_sessions_router)
router.include_router(_orders_router)
router.include_router(_promotions_router)
router.include_router(_loyalty_router)
router.include_router(_tables_router)
router.include_router(_kitchen_router)
router.include_router(_pwa_router)
router.include_router(_sync_router)

__all__ = ["router"]
