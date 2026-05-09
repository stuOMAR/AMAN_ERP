import api from './apiClient'

export const externalAPI = {
    // API Keys
    listApiKeys: () => api.get('/external/api-keys'),
    createApiKey: (data) => api.post('/external/api-keys', data),
    deleteApiKey: (id) => api.delete(`/external/api-keys/${id}`),
    // Webhooks
    getWebhookEvents: () => api.get('/external/webhooks/events'),
    listWebhooks: () => api.get('/external/webhooks'),
    createWebhook: (data) => api.post('/external/webhooks', data),
    updateWebhook: (id, data) => api.put(`/external/webhooks/${id}`, data),
    deleteWebhook: (id) => api.delete(`/external/webhooks/${id}`),
    getWebhookLogs: (id) => api.get(`/external/webhooks/${id}/logs`),
    // ZATCA
    generateQR: (invoiceId) => api.post('/external/zatca/generate-qr', { invoice_id: invoiceId }),
    generateZatcaKeypair: () => api.post('/external/zatca/generate-keypair'),
    verifyZatca: (invoiceId) => api.get(`/external/zatca/verify/${invoiceId}`),
    // WHT
    listWhtRates: (params) => api.get('/external/wht/rates', { params }),
    createWhtRate: (data) => api.post('/external/wht/rates', data),
    calculateWht: (data) => api.post('/external/wht/calculate', data),
    listWhtTransactions: (params) => api.get('/external/wht/transactions', { params }),
    createWhtTransaction: (data, idempotencyKey) => api.post('/external/wht/transactions', data, {
        headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined,
    }),
}
