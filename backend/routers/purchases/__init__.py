"""Purchases router package — aggregates split sub-routers (T6.3).

Replaces the monolithic ``backend/routers/purchases.py`` (3572 lines).
External imports of ``router`` continue to work unchanged.
"""
from fastapi import APIRouter, Depends

from utils.permissions import require_module

from .suppliers import router as _suppliers_router
from .orders import router as _orders_router
from .invoices import router as _invoices_router
from .returns import router as _returns_router
from .payments import router as _payments_router
from .blanket import router as _blanket_router

# Single combined router with the original prefix and module guard.
router = APIRouter(
    prefix="/buying",
    tags=["Purchases"],
    dependencies=[Depends(require_module("buying"))],
)
router.include_router(_suppliers_router)
router.include_router(_orders_router)
router.include_router(_invoices_router)
router.include_router(_returns_router)
router.include_router(_payments_router)
router.include_router(_blanket_router)

__all__ = ["router"]
