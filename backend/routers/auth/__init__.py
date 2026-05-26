"""auth router package — aggregates split sub-routers (T6.3)."""
from fastapi import APIRouter

from .core import router as _core_router
from .session import router as _session_router
from .password import router as _password_router
from .twofa import router as _twofa_router
from .admin import router as _admin_router
from .core import *  # noqa: F403  # re-export module-level names

router = APIRouter(prefix="/auth", tags=['Authentication'])
router.include_router(_core_router)
router.include_router(_session_router)
router.include_router(_password_router)
router.include_router(_twofa_router)
router.include_router(_admin_router)

__all__ = ["router"]
