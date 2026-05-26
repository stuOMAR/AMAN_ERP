import api from './apiClient'
import { hasPermission } from '../utils/auth'

const requireFrontendPermission = (permission) => {
    if (hasPermission(permission)) return
    const error = new Error('Permission denied')
    error.response = { status: 403, data: { detail: 'Permission denied' } }
    throw error
}

const withPermission = (permission, request) => {
    requireFrontendPermission(permission)
    return request()
}

export const reportsAPI = {
    getSalesSummary: (start_date, end_date, branch_id) => api.get('/reports/sales/summary', { params: { start_date, end_date, branch_id } }),
    getSalesTrend: (days = 30, branch_id = null) => api.get('/reports/sales/trend', { params: { days, branch_id } }),
    getSalesByCustomer: (limit = 5, branch_id = null) => api.get('/reports/sales/by-customer', { params: { limit, branch_id } }),
    getSalesByProduct: (limit = 5, branch_id = null) => api.get('/reports/sales/by-product', { params: { limit, branch_id } }),
    getCustomerStatement: (customerId, params) => api.get(`/reports/sales/customer-statement/${customerId}`, { params }),
    getAgingReport: (branch_id = null) => api.get('/reports/sales/aging', { params: { branch_id } }),
    getAgingSummary: (branch_id = null) => api.get('/reports/sales/aging/summary', { params: { branch_id } }),

    getPurchasesSummary: (params) => api.get('/reports/purchases/summary', { params }),
    getPurchasesTrend: (days = 30, branch_id = null) => api.get('/reports/purchases/trend', { params: { days, branch_id } }),
    getPurchasesBySupplier: (limit = 5, branch_id = null) => api.get('/reports/purchases/by-supplier', { params: { limit, branch_id } }),
    getSupplierStatement: (supplierId, params) => api.get(`/reports/purchases/supplier-statement/${supplierId}`, { params }),
    getPurchasesAging: (branch_id = null) => api.get('/reports/purchases/aging', { params: { branch_id } }),
    getPurchasesAgingSummary: (branch_id = null) => api.get('/reports/purchases/aging/summary', { params: { branch_id } }),

    // Cashflow IAS 7
    getCashFlowIAS7: (params) => api.get('/reports/accounting/cashflow-ias7', { params }),

    // HR Reports
    getPayrollTrend: (months = 12) => api.get('/reports/hr/payroll/trend', { params: { months } }),
    getLeaveUsage: (params) => api.get('/reports/hr/leaves/usage', { params }),

    // Financial Reports
    getGeneralLedger: (params) => api.get('/reports/accounting/general-ledger', { params }),
    getTrialBalance: (params) => api.get('/reports/accounting/trial-balance', { params }),
    getProfitLoss: (params) => api.get('/reports/accounting/profit-loss', { params }),
    getBalanceSheet: (params) => api.get('/reports/accounting/balance-sheet', { params }),
    getCashFlow: (params) => api.get('/reports/accounting/cashflow', { params }),
    getBudgetVsActual: (budgetId, params) => api.get(`/reports/accounting/budget-vs-actual`, { params: { budget_id: budgetId, ...params } }),

    // Period Comparison (ACC-004)
    compareProfitLoss: (params) => api.get('/reports/accounting/profit-loss/compare', { params }),
    compareBalanceSheet: (params) => api.get('/reports/accounting/balance-sheet/compare', { params }),
    compareTrialBalance: (params) => api.get('/reports/accounting/trial-balance/compare', { params }),

    // Exports
    exportBalanceSheet: (params) => api.get('/reports/accounting/balance-sheet/export', { params, responseType: 'blob' }),
    exportCashFlow: (params) => api.get('/reports/accounting/cashflow/export', { params, responseType: 'blob' }),
    exportProfitLoss: (params) => api.get('/reports/accounting/profit-loss/export', { params, responseType: 'blob' }),
    exportGeneralLedger: (params) => api.get('/reports/accounting/general-ledger/export', { params, responseType: 'blob' }),
    exportTrialBalance: (params) => api.get('/reports/accounting/trial-balance/export', { params, responseType: 'blob' }),
    exportAging: (params) => api.get('/reports/sales/aging/export', { params, responseType: 'blob' }),

    // Advanced Analytics
    getCostCenterReport: (params) => api.get('/reports/accounting/cost-center-report', { params }),
    getFinancialRatios: (params) => api.get('/reports/accounting/financial-ratios', { params }),
    getHorizontalAnalysis: (params) => api.get('/reports/accounting/horizontal-analysis', { params }),

    // Inventory Reports
    getCOGSReport: (params) => api.get('/reports/inventory/cogs', { params }),
    getDeadStockReport: (params) => api.get('/reports/inventory/dead-stock', { params }),
    getTurnoverReport: (params) => api.get('/reports/inventory/turnover', { params }),
    getValuationReport: (params) => api.get('/reports/inventory/valuation', { params }),

    // Sales Advanced
    getSalesByCashier: (params) => api.get('/reports/sales/by-cashier', { params }),
    getTargetVsActual: (params) => api.get('/reports/sales/target-vs-actual', { params }),
}

export const customReportsAPI = {
    create: (data) => withPermission('reports.create', () => api.post('/reports/custom', data)),
    list: () => api.get('/reports/custom'),
    get: (id) => api.get(`/reports/custom/${id}`),
    delete: (id) => withPermission('reports.delete', () => api.delete(`/reports/custom/${id}`)),
    preview: (data) => api.post('/reports/custom/preview', data),
}

export const scheduledReportsAPI = {
    list: (params) => api.get('/reports/scheduled/', { params }),
    create: (data) => api.post('/reports/scheduled/', data),
    update: (id, data) => api.put(`/reports/scheduled/${id}`, data),
    delete: (id) => api.delete(`/reports/scheduled/${id}`),
    toggle: (id, active) => api.put(`/reports/scheduled/${id}/toggle`, null, { params: { active } }),
    runNow: (id) => api.post(`/reports/scheduled/${id}/run`),
    getTypes: () => api.get('/reports/scheduled/types'),
}

// ─── Detailed P&L & Commission Reports ────────────────────────
export const detailedReportsAPI = {
    getDetailedPL: (params) => api.get('/reports/accounting/profit-loss/detailed', { params }),
    getCommissionReport: (params) => api.get('/reports/sales/commissions/report', { params }),
}

// ─── RPT-106: Report Sharing ──────────────────────────────────
export const reportSharingAPI = {
    share: (data) => api.post('/reports/share', data),
    unshare: (id) => api.delete(`/reports/share/${id}`),
    listShared: () => api.get('/reports/shared/'),
    getReportShares: (reportType, reportId) => api.get(`/reports/shared/by-report/${reportType}/${reportId}`),
    listUsers: () => api.get('/reports/users/'),

    // KPI Dashboard (B8)
    getKPIDashboard: () => api.get('/reports/kpi/dashboard'),
}
