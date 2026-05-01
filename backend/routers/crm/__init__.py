"""crm router package — aggregates split sub-routers (T6.3)."""
from fastapi import APIRouter
from fastapi import Depends
from utils.permissions import require_module

from .core import router as _core_router
from .opportunities import router as _opportunities_router
from .tickets import router as _tickets_router
from .campaigns import router as _campaigns_router
from .knowledge_base import router as _knowledge_base_router
from .segments import router as _segments_router
from .contacts import router as _contacts_router
from .analytics import router as _analytics_router

router = APIRouter(prefix="/crm", tags=['CRM'], dependencies=[Depends(require_module("crm"))])
router.include_router(_core_router)
router.include_router(_opportunities_router)
router.include_router(_tickets_router)
router.include_router(_campaigns_router)
router.include_router(_knowledge_base_router)
router.include_router(_segments_router)
router.include_router(_contacts_router)
router.include_router(_analytics_router)

__all__ = ["router"]
