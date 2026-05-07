"""
AMAN ERP - Finance & Accounting Module
المحاسبة والمالية

Sub-modules:
  accounting, currencies, cost_centers, budgets, reconciliation,
  treasury, taxes, tax_compliance, costing_policies, checks, notes, assets, expenses,
  intercompany (v2 only), revenue_recognition, advanced_workflow
"""

from fastapi import APIRouter

from .accounting import router as accounting_router
from .currencies import router as currencies_router
from .cost_centers import router as cost_centers_router
from .budgets import router as budgets_router
from .reconciliation import router as reconciliation_router
from .treasury import router as treasury_router
from .taxes import router as taxes_router
from .tax_compliance import router as tax_compliance_router
from .costing_policies import router as costing_policies_router
from .checks import router as checks_router
from .notes import router as notes_router
from .assets import router as assets_router
from .expenses import router as expenses_router
from .intercompany_v2 import router as intercompany_v2_router
from .revenue_recognition import rev_router as revenue_recognition_router
from .advanced_workflow import router as advanced_workflow_router
from .cashflow import router as cashflow_router
from .subscriptions import router as subscriptions_router
from .accounting_depth import router as accounting_depth_router  # Phase 5 (TASK-036..040)
from .payments import router as payments_router  # Phase 6 — payment gateways
from .bank_feeds import router as bank_feeds_router  # Phase 6 ext — MT940/CSV bank feeds
from .petty_cash import router as petty_cash_router  # T15 — Petty cash funds & disbursements

# Combined router — each sub-module keeps its own prefix
router = APIRouter()
router.include_router(accounting_router)
router.include_router(currencies_router)
router.include_router(cost_centers_router)
router.include_router(budgets_router)
router.include_router(reconciliation_router)
router.include_router(treasury_router)
router.include_router(taxes_router)
router.include_router(tax_compliance_router)
router.include_router(costing_policies_router)
router.include_router(checks_router)
router.include_router(notes_router)
router.include_router(assets_router)
router.include_router(expenses_router)
router.include_router(intercompany_v2_router)
router.include_router(revenue_recognition_router)
router.include_router(advanced_workflow_router)
router.include_router(cashflow_router)
router.include_router(subscriptions_router)
router.include_router(accounting_depth_router)
router.include_router(payments_router)
router.include_router(bank_feeds_router)
router.include_router(petty_cash_router)  # T15 — Petty cash
