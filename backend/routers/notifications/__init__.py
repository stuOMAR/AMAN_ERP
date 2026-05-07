"""Notifications router package.

Re-exports the main router from core.py and includes sub-routers
for queue admin and templates admin.
"""

from .core import router
from .queue_admin import router as queue_admin_router
from .templates_admin import router as templates_admin_router

# Include sub-routers into the main router
router.include_router(queue_admin_router)
router.include_router(templates_admin_router)

__all__ = ["router"]
