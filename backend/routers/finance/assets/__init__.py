"""assets router package — aggregates split sub-routers (T6.3)."""
from fastapi import APIRouter
from fastapi import Depends
from utils.permissions import require_module

from .core import router as _core_router
from .transfers import router as _transfers_router
from .revaluations import router as _revaluations_router
from .maintenance import router as _maintenance_router
from .reports import router as _reports_router
from .depreciation import router as _depreciation_router
from .leases import router as _leases_router
from .insurance import router as _insurance_router
from .qr import router as _qr_router
from .impairment import router as _impairment_router

router = APIRouter(prefix="/assets", tags=['Fixed Assets'], dependencies=[Depends(require_module("assets"))])
router.include_router(_core_router)
router.include_router(_transfers_router)
router.include_router(_revaluations_router)
router.include_router(_maintenance_router)
router.include_router(_reports_router)
router.include_router(_depreciation_router)
router.include_router(_leases_router)
router.include_router(_insurance_router)
router.include_router(_qr_router)
router.include_router(_impairment_router)

__all__ = ["router"]
