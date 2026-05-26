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

const withoutCurrentRate = (data) => {
    if (!data || typeof data !== 'object') return data
    const payload = { ...data }
    delete payload.current_rate
    return payload
}

export const accountingAPI = {
    list: (params, config = {}) => api.get('/accounting/accounts', { params, ...config }),
    create: (data) => withPermission('accounting.edit', () => api.post('/accounting/accounts', withoutCurrentRate(data))),
    update: (id, data) => withPermission('accounting.edit', () => api.put(`/accounting/accounts/${id}`, withoutCurrentRate(data))),
    delete: (id) => api.delete(`/accounting/accounts/${id}`),
    previewJournalEntry: (data) => api.post('/accounting/journal-entries/preview', data, { skipGlobalToast: true }),
    createJournalEntry: (data, config) => api.post('/accounting/journal-entries', data, config),
    voidJournalEntry: (id) => api.post(`/accounting/journal-entries/${id}/void`),
    getSummary: (params) => api.get('/accounting/summary', { params }),

    // Fiscal Years (ACC-001)
    listFiscalYears: () => api.get('/accounting/fiscal-years'),
    createFiscalYear: (data) => api.post('/accounting/fiscal-years', data),
    previewClosing: (year) => api.get(`/accounting/fiscal-years/${year}/preview-closing`),
    closeFiscalYear: (year, data) => api.post(`/accounting/fiscal-years/${year}/close`, data),
    reopenFiscalYear: (year, data) => api.post(`/accounting/fiscal-years/${year}/reopen`, data),
    listFiscalPeriods: (year) => api.get(`/accounting/fiscal-years/${year}/periods`),
    togglePeriod: (periodId) => api.post(`/accounting/fiscal-periods/${periodId}/toggle-close`),

    // Journal Entries (ACC-002)
    listJournalEntries: (params) => api.get('/accounting/journal-entries', { params }),
    getJournalEntry: (id) => api.get(`/accounting/journal-entries/${id}`),
    postJournalEntry: (id) => api.post(`/accounting/journal-entries/${id}/post`),
    reverseJournalEntry: (id, data) => api.post(`/accounting/journal-entries/${id}/reverse`, data),

    // Recurring Templates (ACC-003)
    listRecurringTemplates: (params) => api.get('/accounting/recurring-templates', { params }),
    getRecurringTemplate: (id) => api.get(`/accounting/recurring-templates/${id}`),
    createRecurringTemplate: (data) => withPermission('accounting.edit', () => api.post('/accounting/recurring-templates', data)),
    updateRecurringTemplate: (id, data) => withPermission('accounting.edit', () => api.put(`/accounting/recurring-templates/${id}`, data)),
    deleteRecurringTemplate: (id) => api.delete(`/accounting/recurring-templates/${id}`),
    generateFromTemplate: (id) => withPermission('accounting.edit', () => api.post(`/accounting/recurring-templates/${id}/generate`)),
    generateDueTemplates: () => api.post('/accounting/recurring-templates/generate-due'),

    // Opening Balances (ACC-005)
    getOpeningBalances: () => api.get('/accounting/opening-balances'),
    saveOpeningBalances: (data) => api.post('/accounting/opening-balances', data),

    // Closing Entries (ACC-006)
    previewClosingEntries: (params) => api.get('/accounting/closing-entries/preview', { params }),
    generateClosingEntries: (data, idempotencyKey) => api.post('/accounting/closing-entries/generate', data, {
        headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined,
    }),

    // FX Revaluation (ACC-007)
    fxRevaluation: (data) => api.post('/accounting/fx-revaluation', data),

    // Provisions (ACC-008)
    createBadDebtProvision: (data) => api.post('/accounting/provisions/bad-debt', data),
    createLeaveProvision: (data) => api.post('/accounting/provisions/leave', data),

    // Intercompany Transactions (IC-001) — legacy v1
    listIntercompanyTransactions: (params) => api.get('/accounting/intercompany/transactions', { params }),
    createIntercompanyTransaction: (data) => api.post('/accounting/intercompany/transactions', data),
    processIntercompanyTransaction: (id) => api.post(`/accounting/intercompany/transactions/${id}/process`),
    getIntercompanyEliminationReport: (params) => api.get('/accounting/intercompany/consolidate', { params }),

    // Intercompany v2 — Entity Groups, Transactions, Consolidation, Mappings
    listEntityGroups: () => api.get('/accounting/intercompany/entities'),
    createEntityGroup: (data) => withPermission(['intercompany.manage', 'accounting.edit'], () => api.post('/accounting/intercompany/entities', data)),
    updateEntityGroup: (id, data) => withPermission(['intercompany.manage', 'accounting.edit'], () => api.patch(`/accounting/intercompany/entities/${id}`, data)),
    listICTransactionsV2: (params) => api.get('/accounting/intercompany/transactions', { params }),
    createICTransactionV2: (data) => api.post('/accounting/intercompany/transactions', data),
    getICTransactionV2: (id) => api.get(`/accounting/intercompany/transactions/${id}`),
    runConsolidation: (data) => withPermission(['intercompany.manage', 'accounting.edit'], () => api.post('/accounting/intercompany/consolidate', data)),
    getICBalances: () => api.get('/accounting/intercompany/balances'),
    listAccountMappings: () => api.get('/accounting/intercompany/mappings'),
    createAccountMapping: (data) => withPermission(['intercompany.manage', 'accounting.edit'], () => api.post('/accounting/intercompany/mappings', data)),

    // Revenue Recognition (REV-001)
    listRevenueSchedules: (params) => api.get('/accounting/revenue-recognition/schedules', { params }),
    createRevenueSchedule: (data) => withPermission('accounting.edit', () => api.post('/accounting/revenue-recognition/schedules', data)),
    getRevenueSchedule: (id) => api.get(`/accounting/revenue-recognition/schedules/${id}`),
    recognizeRevenue: (id, periodIndex, idempotencyKey) => withPermission('accounting.edit', () => api.post(`/accounting/revenue-recognition/schedules/${id}/recognize?period_index=${periodIndex}`, {}, {
        headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined,
    })),
    getRevenueSummary: () => api.get('/accounting/revenue-recognition/summary'),
}

export const costCentersAPI = {
    list: (params) => api.get('/cost-centers/', { params }),
    create: (data) => api.post('/cost-centers/', withoutCurrentRate(data)),
    update: (id, data) => api.put(`/cost-centers/${id}`, withoutCurrentRate(data)),
    delete: (id) => api.delete(`/cost-centers/${id}`)
}

export const budgetsAPI = {
    list: (params) => withPermission('accounting.budgets.view', () => api.get('/accounting/budgets/', { params })),
    create: (data) => withPermission('accounting.budgets.manage', () => api.post('/accounting/budgets/', withoutCurrentRate(data))),
    createByCostCenter: (data) => withPermission('accounting.budgets.manage', () => api.post('/accounting/budgets/by-cost-center', withoutCurrentRate(data))),
    listByCostCenter: (params) => withPermission('accounting.budgets.view', () => api.get('/accounting/budgets/by-cost-center', { params })),
    getByCostCenter: (costCenterId, params) => withPermission('accounting.budgets.view', () => api.get(`/accounting/budgets/by-cost-center/${costCenterId}`, { params })),
    listMultiYear: (params) => withPermission('accounting.budgets.view', () => api.get('/accounting/budgets/multi-year', { params })),
    compare: (params) => withPermission('accounting.budgets.view', () => api.get('/accounting/budgets/comparison', { params })),
    get: (id) => withPermission('accounting.budgets.view', () => api.get(`/accounting/budgets/${id}`)),
    update: (id, data) => withPermission('accounting.budgets.manage', () => api.put(`/accounting/budgets/${id}`, withoutCurrentRate(data))),
    setItems: (id, items) => withPermission('accounting.budgets.manage', () => api.post(`/accounting/budgets/${id}/items`, items)),
    getItems: (id) => withPermission('accounting.budgets.view', () => api.get(`/accounting/budgets/${id}/items`)),
    getReport: (id, params) => withPermission('accounting.budgets.view', () => api.get(`/accounting/budgets/${id}/report`, { params })),
    delete: (id) => withPermission('accounting.budgets.manage', () => api.delete(`/accounting/budgets/${id}`)),
    activate: (id) => withPermission('accounting.budgets.manage', () => api.post(`/accounting/budgets/${id}/activate`)),
    close: (id) => withPermission('accounting.budgets.manage', () => api.post(`/accounting/budgets/${id}/close`)),
    getOverrunAlerts: (params) => withPermission('accounting.budgets.view', () => api.get('/accounting/budgets/alerts/overruns', { params })),
    getStats: (params) => withPermission('accounting.budgets.view', () => api.get('/accounting/budgets/stats/summary', { params }))
}

export const currenciesAPI = {
    list: () => api.get('/accounting/currencies/'),
    create: (data) => withPermission(['accounting.manage', 'currencies.manage'], () => api.post('/accounting/currencies/', data)),
    update: (id, data) => withPermission(['accounting.manage', 'currencies.manage'], () => api.put(`/accounting/currencies/${id}`, data)),
    delete: (id) => withPermission(['accounting.manage', 'currencies.manage'], () => api.delete(`/accounting/currencies/${id}`)),
    addRate: (data) => withPermission(['accounting.manage', 'currencies.manage'], () => api.post('/accounting/currencies/rates', data)),
    getHistory: (id, limit = 30) => api.get(`/accounting/currencies/${id}/rates`, { params: { limit } }),
    revaluate: (data) => withPermission(['accounting.manage', 'currencies.manage'], () => api.post('/accounting/currencies/revaluate', data)),
    // T8.4: dynamic rate lookup — replaces hard-coded `exchange_rate: 1.0`
    // in journal/invoice/transfer/recurring forms. Backend resolves to the
    // latest exchange_rates row dated on/before today, with graceful fallback.
    getCurrentRate: (code) => api.get('/accounting/currencies/current', {
        params: { code },
        skipGlobalToast: true,
    }),
    previewFx: (data) => api.post('/accounting/currencies/preview', data, {
        skipGlobalToast: true,
    }),
}

// Zakat Calculator
export const zakatAPI = {
    calculate: (data) => api.post('/accounting/zakat/calculate', data),
    post: (year, params, idempotencyKey) => api.post(`/accounting/zakat/${year}/post`, {}, {
        params,
        headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined,
    }),
}

// Fiscal Period Locks
export const fiscalLocksAPI = {
    listPeriods: () => api.get('/accounting/fiscal-periods'),
    createPeriod: (data) => api.post('/accounting/fiscal-periods', data),
    lockPeriod: (id) => api.post(`/accounting/fiscal-periods/${id}/lock`),
    unlockPeriod: (id) => api.post(`/accounting/fiscal-periods/${id}/unlock`),
}

// Consolidation Reports
export const consolidationAPI = {
    getTrialBalance: (params) => api.get('/reports/consolidation/trial-balance', { params }),
    getIncomeStatement: (params) => api.get('/reports/consolidation/income-statement', { params }),
    getBalanceSheet: (params) => api.get('/reports/consolidation/balance-sheet', { params }),
}

// FX Gain/Loss Report
export const fxReportAPI = {
    getGainLoss: (params) => api.get('/reports/accounting/fx-gain-loss', { params }),
}
