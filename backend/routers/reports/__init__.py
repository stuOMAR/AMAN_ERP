"""Reports router package — aggregates split sub-routers (T6.3)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from fastapi import HTTPException, Request
from pydantic import BaseModel

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


class CacheRefreshRequest(BaseModel):
    scope: str = "all"
    report_codes: list[str] | None = None


class CacheRefreshResponse(BaseModel):
    refreshed: int
    scope: str
    details: dict[str, bool] = {}


@router.post("/cache/refresh", response_model=CacheRefreshResponse)
async def refresh_report_cache(body: CacheRefreshRequest, request: Request):
    """On-demand cache refresh for report materialized views and warm-up."""
    from services.reports.mv_refresh import refresh_report_mvs

    results = {}
    refreshed = 0

    if body.scope in ("all", "mv_only"):
        mv_results = await refresh_report_mvs()
        results.update(mv_results)
        refreshed += sum(1 for value in mv_results.values() if value)

    if body.scope in ("all", "warmup_only"):
        from services.cache.warmup import warmup_cache
        from utils.cache import cache

        warmed = await warmup_cache(cache, lambda key: None)
        results["warmup"] = warmed > 0
        refreshed += warmed

    return CacheRefreshResponse(refreshed=refreshed, scope=body.scope, details=results)


@router.get("/income_statement")
async def income_statement(
    request: Request,
    period_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    company_id: str = "",
    tenant_id: str = "",
):
    """Income statement report with cache observability headers."""
    from middleware.cache_observability import set_cache_hit
    from services.reports.income_statement import get_income_statement
    from database import get_tenant_db

    set_cache_hit(request, False)
    with get_tenant_db(tenant_id) as db:
        return get_income_statement(db, tenant_id, company_id, period_id, start_date, end_date)


@router.get("/trial_balance")
async def trial_balance(
    request: Request,
    as_of_date: Optional[str] = None,
    company_id: str = "",
    tenant_id: str = "",
):
    """Trial balance report with tolerance and drift reporting."""
    from middleware.cache_observability import set_cache_hit
    from services.reports.trial_balance import get_trial_balance
    from database import get_tenant_db

    set_cache_hit(request, False)
    with get_tenant_db(tenant_id) as db:
        return get_trial_balance(db, tenant_id, company_id, as_of_date)


@router.get("/balance_sheet")
async def balance_sheet(
    request: Request,
    as_of_date: Optional[str] = None,
    company_id: str = "",
    tenant_id: str = "",
):
    """Balance sheet report with classifier-driven sign logic."""
    from middleware.cache_observability import set_cache_hit
    from services.reports.balance_sheet import get_balance_sheet
    from database import get_tenant_db

    set_cache_hit(request, False)
    with get_tenant_db(tenant_id) as db:
        return get_balance_sheet(db, tenant_id, company_id, as_of_date)


@router.get("/period_stats")
async def period_stats(
    request: Request,
    period_id: str = "",
    company_id: str = "",
    tenant_id: str = "",
):
    """Period stats from mv_period_stats with live-compute fallback."""
    from middleware.cache_observability import set_cache_hit
    from services.reports.period_stats import read_period_stats
    from database import get_tenant_db

    set_cache_hit(request, False)
    with get_tenant_db(tenant_id) as db:
        result = read_period_stats(db, tenant_id, company_id, period_id)
    if not result:
        raise HTTPException(**http_error(404, "period_not_found", request))
    return result

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
