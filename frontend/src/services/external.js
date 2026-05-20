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

export const externalAPI = {
    // API Keys
    listApiKeys: () => withPermission('admin', () => api.get('/external/api-keys')),
    createApiKey: (data) => withPermission('admin', () => api.post('/external/api-keys', data)),
    deleteApiKey: (id) => withPermission('admin', () => api.delete(`/external/api-keys/${id}`)),
    // Webhooks
    getWebhookEvents: () => withPermission(['settings.view', 'admin'], () => api.get('/external/webhooks/events')),
    listWebhooks: () => withPermission(['settings.view', 'admin'], () => api.get('/external/webhooks')),
    createWebhook: (data) => withPermission(['settings.manage', 'admin'], () => api.post('/external/webhooks', data)),
    updateWebhook: (id, data) => withPermission(['settings.manage', 'admin'], () => api.put(`/external/webhooks/${id}`, data)),
    deleteWebhook: (id) => withPermission(['settings.manage', 'admin'], () => api.delete(`/external/webhooks/${id}`)),
    getWebhookLogs: (id) => withPermission(['settings.view', 'admin'], () => api.get(`/external/webhooks/${id}/logs`)),
    // ZATCA
    generateQR: (invoiceId) => withPermission(['sales.view', 'accounting.view'], () => api.post('/external/zatca/generate-qr', { invoice_id: invoiceId })),
    generateZatcaKeypair: () => withPermission('admin', () => api.post('/external/zatca/generate-keypair')),
    verifyZatca: (invoiceId) => withPermission(['sales.view', 'accounting.view'], () => api.get(`/external/zatca/verify/${invoiceId}`)),
    // WHT
    listWhtRates: (params) => withPermission(['accounting.view', 'taxes.view'], () => api.get('/external/wht/rates', { params })),
    createWhtRate: (data) => withPermission(['accounting.manage', 'taxes.manage'], () => api.post('/external/wht/rates', data)),
    calculateWht: (data) => withPermission(['accounting.view', 'buying.view'], () => api.post('/external/wht/calculate', data)),
    listWhtTransactions: (params) => withPermission(['accounting.view', 'taxes.view'], () => api.get('/external/wht/transactions', { params })),
    createWhtTransaction: (data, idempotencyKey) => withPermission(['accounting.edit', 'taxes.manage'], () => api.post('/external/wht/transactions', data, {
        headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined,
    })),
}
