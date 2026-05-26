"""
AMAN ERP - Inventory Module (Split Package)
Originally routers/inventory.py (2,755 lines) → split into sub-modules
"""

from fastapi import APIRouter, Depends
from utils.permissions import require_module

router = APIRouter(prefix="/inventory", tags=["Inventory"], dependencies=[Depends(require_module("stock"))])

# Import and include all sub-routers
from .products import products_router  # noqa: E402
from .suppliers import suppliers_router  # noqa: E402
from .categories import categories_router  # noqa: E402
from .warehouses import warehouses_router  # noqa: E402
from .transfers import transfers_router  # noqa: E402
from .price_lists import price_lists_router  # noqa: E402
from .stock_movements import stock_movements_router  # noqa: E402
from .shipments import shipments_router  # noqa: E402
# notifications_router removed — unified in routers/notifications.py
from .adjustments import adjustments_router  # noqa: E402
from .reports import reports_router  # noqa: E402
from .batches import batches_router  # noqa: E402
from .advanced import advanced_router  # noqa: E402
from .costing import costing_router  # noqa: E402
from .forecast import forecast_router  # noqa: E402

router.include_router(products_router)
router.include_router(suppliers_router)
router.include_router(categories_router)
router.include_router(warehouses_router)
router.include_router(transfers_router)
router.include_router(price_lists_router)
router.include_router(stock_movements_router)
router.include_router(shipments_router)
# notifications_router removed — unified in routers/notifications.py
router.include_router(adjustments_router)
router.include_router(reports_router)
router.include_router(batches_router)
router.include_router(advanced_router)
router.include_router(costing_router)
router.include_router(forecast_router)
