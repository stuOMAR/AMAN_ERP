import api from './apiClient'

const idempotencyHeaders = () => ({
    headers: { 'Idempotency-Key': globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}` }
})

export const contractsAPI = {
    listContracts: (params) => api.get('/contracts', { params }),
    getContract: (id) => api.get(`/contracts/${id}`),
    previewContract: (data) => api.post('/contracts/preview', data),
    previewBillingCycle: (id, data = {}) => api.post('/contracts/billing-cycle/preview', { contract_id: id, ...data }),
    createContract: (data) => api.post('/contracts', data, idempotencyHeaders()),
    updateContract: (id, data) => api.put(`/contracts/${id}`, data),
    renewContract: (id) => api.post(`/contracts/${id}/renew`, null, idempotencyHeaders()),
    cancelContract: (id) => api.post(`/contracts/${id}/cancel`),
    generateInvoice: (id, data) => api.post(`/contracts/${id}/generate-invoice`, data, idempotencyHeaders()),
    getExpiringContracts: (days = 30) => api.get('/contracts/alerts/expiring', { params: { days } }),
    getContractStats: () => api.get('/contracts/stats/summary'),

    // Amendments & KPIs (C2)
    listAmendments: (contractId) => api.get(`/contracts/${contractId}/amendments`),
    createAmendment: (contractId, data) => api.post(`/contracts/${contractId}/amendments`, data),
    getContractKPIs: (contractId) => api.get(`/contracts/${contractId}/kpis`),
}
