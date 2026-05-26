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

const idempotencyHeaders = () => ({
    headers: { 'Idempotency-Key': globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}` }
})

export const treasuryAPI = {
    listAccounts: (branchId) => withPermission('treasury.view', () => api.get('/treasury/accounts', { params: { branch_id: branchId } })),
    previewOpeningBalance: (params) => withPermission('treasury.view', () => api.get('/treasury/accounts/opening-balance-preview', { params })),
    createAccount: (data) => withPermission('treasury.create', () => api.post('/treasury/accounts', data, idempotencyHeaders())),
    updateAccount: (id, data) => withPermission('treasury.edit', () => api.put(`/treasury/accounts/${id}`, data, idempotencyHeaders())),
    deleteAccount: (id) => withPermission('treasury.delete', () => api.delete(`/treasury/accounts/${id}`, idempotencyHeaders())),
    createExpense: (data) => withPermission('treasury.manage', () => api.post('/treasury/transactions/expense', data, idempotencyHeaders())),
    createTransfer: (data) => withPermission('treasury.manage', () => api.post('/treasury/transactions/transfer', data, idempotencyHeaders())),
    listTransactions: (limit, branchId) => withPermission('treasury.view', () => api.get('/treasury/transactions', { params: { limit, branch_id: branchId } })),

    // Treasury Reports
    getBalancesReport: (params) => withPermission('treasury.view', () => api.get('/treasury/reports/balances', { params })),
    getCashflowReport: (params) => withPermission('treasury.view', () => api.get('/treasury/reports/cashflow', { params })),

    // Bank Import
    importBankStatement: (file, options = {}) => {
        const formData = new FormData();
        formData.append('file', file);
        const extension = (file?.name || '').split('.').pop()?.toLowerCase();
        const sourceFormat = options.sourceFormat || (
            extension === 'csv' ? 'csv' :
            ['xml', 'camt', 'camt053'].includes(extension) ? 'camt053' :
            'mt940'
        );
        formData.append('source_format', sourceFormat);
        if (options.bankAccountId) formData.append('bank_account_id', options.bankAccountId);
        if (options.csvConfig) formData.append('csv_config', JSON.stringify(options.csvConfig));
        return withPermission('finance.reconciliation_manage', () => api.post('/finance/bank-feeds/import', formData, {
            headers: {
                'Content-Type': 'multipart/form-data',
                ...idempotencyHeaders().headers
            }
        }));
    },
    listBankImports: (params) => api.get('/finance/bank-feeds/statements', {
        params: { limit: params?.limit || 50 }
    }),
    getBankImportLines: (statementId) => api.get(`/finance/bank-feeds/statements/${statementId}/lines`),
    autoMatchBankImport: (batchId) => withPermission('reconciliation.create', () => api.post(`/treasury/bank-import/${batchId}/auto-match`, null, idempotencyHeaders())),

    // Legacy bank-import endpoints kept for older screens that still need batch matching.
    importLegacyBankStatement: (file) => {
        const formData = new FormData();
        formData.append('file', file);
        return api.post('/treasury/bank-import', formData, {
            headers: {
                'Content-Type': 'multipart/form-data',
                ...idempotencyHeaders().headers
            }
        });
    },
    listLegacyBankImports: () => api.get('/treasury/bank-import/batches'),
    getLegacyBankImportLines: (batchId) => api.get(`/treasury/bank-import/${batchId}/lines`),
    autoMatchLegacyBankImport: (batchId) => api.post(`/treasury/bank-import/${batchId}/auto-match`, null, idempotencyHeaders()),
}

export const reconciliationAPI = {
    list: (params) => api.get('/reconciliation', { params }),
    get: (id) => api.get(`/reconciliation/${id}`),
    create: (data) => withPermission('reconciliation.create', () => api.post('/reconciliation', data, idempotencyHeaders())),
    addLines: (id, lines) => withPermission('reconciliation.create', () => api.post(`/reconciliation/${id}/lines`, lines, idempotencyHeaders())),
    deleteLine: (id, lineId) => withPermission('reconciliation.create', () => api.delete(`/reconciliation/${id}/lines/${lineId}`)),
    getLedger: (id) => api.get(`/reconciliation/${id}/ledger`),
    match: (id, data) => withPermission('reconciliation.create', () => api.post(`/reconciliation/${id}/match`, data, idempotencyHeaders())),
    unmatch: (id, data) => withPermission('reconciliation.create', () => api.post(`/reconciliation/${id}/unmatch`, data, idempotencyHeaders())),
    finalize: (id) => withPermission('finance.reconciliation.finalize', () => api.post(`/reconciliation/${id}/finalize`, null, idempotencyHeaders())),
    delete: (id) => withPermission('reconciliation.create', () => api.delete(`/reconciliation/${id}`)),
    importPreview: (id, file) => {
        const formData = new FormData();
        formData.append('file', file);
        return withPermission('reconciliation.create', () => api.post(`/reconciliation/${id}/import-preview`, formData, {
            headers: { 'Content-Type': 'multipart/form-data' }
        }));
    },
    importConfirm: (id, lines) => withPermission('reconciliation.create', () => api.post(`/reconciliation/${id}/import-confirm`, lines, idempotencyHeaders())),
    autoMatch: (id, toleranceDays = 3) => withPermission('reconciliation.create', () => api.post(`/reconciliation/${id}/auto-match?tolerance_days=${toleranceDays}`, null, idempotencyHeaders())),
}
