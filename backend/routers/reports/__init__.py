"""Reports router package — aggregates split sub-routers (T6.3)."""
from fastapi import APIRouter

from .sales import router as _sales_router
from .purchases import router as _purchases_router
from .hr import router as _hr_router
from .accounting_statements import router as _acct_stmt_router
from .accounting_compare_export import router as _acct_cmp_router
from .accounting_analysis import router as _acct_analysis_router
from .inventory import router as _inventory_router
from .custom import router as _custom_router
from .kpi import router as _kpi_router
from .industry import router as _industry_router

router = APIRouter(prefix="/reports", tags=["Reports"])
router.include_router(_sales_router)
router.include_router(_purchases_router)
router.include_router(_hr_router)
router.include_router(_acct_stmt_router)
router.include_router(_acct_cmp_router)
router.include_router(_acct_analysis_router)
router.include_router(_inventory_router)
router.include_router(_custom_router)
router.include_router(_kpi_router)
router.include_router(_industry_router)

# Backwards-compat re-exports for legacy callers (e.g. services.scheduler)
# that import these helpers from the old monolithic ``routers.reports`` module.
from .accounting_statements import (  # noqa: E402, F401
    _get_profit_loss_data,
    _get_balance_sheet_data,
    _get_trial_balance_data,
)

__all__ = [
    "router",
    "_get_profit_loss_data",
    "_get_balance_sheet_data",
    "_get_trial_balance_data",
]
