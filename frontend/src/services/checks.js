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

export const checksAPI = {
    // Checks Receivable
    listReceivable: (params) => api.get('/checks/receivable', { params }),
    getReceivable: (id) => api.get(`/checks/receivable/${id}`),
    createReceivable: (data) => withPermission('treasury.create', () => api.post('/checks/receivable', data, idempotencyHeaders())),
    collectReceivable: (id, data) => withPermission('treasury.create', () => api.post(`/checks/receivable/${id}/collect`, data, idempotencyHeaders())),
    bounceReceivable: (id, data) => withPermission('treasury.create', () => api.post(`/checks/receivable/${id}/bounce`, data, idempotencyHeaders())),
    representReceivable: (id, data) => withPermission('treasury.create', () => api.post(`/checks/receivable/${id}/represent`, data, idempotencyHeaders())),
    receivableStats: (params) => api.get('/checks/receivable/summary/stats', { params }),
    // Checks Payable
    listPayable: (params) => api.get('/checks/payable', { params }),
    getPayable: (id) => api.get(`/checks/payable/${id}`),
    createPayable: (data) => withPermission('treasury.create', () => api.post('/checks/payable', data, idempotencyHeaders())),
    clearPayable: (id, data) => withPermission('treasury.create', () => api.post(`/checks/payable/${id}/clear`, data, idempotencyHeaders())),
    bouncePayable: (id, data) => withPermission('treasury.create', () => api.post(`/checks/payable/${id}/bounce`, data, idempotencyHeaders())),
    representPayable: (id, data) => withPermission('treasury.create', () => api.post(`/checks/payable/${id}/represent`, data, idempotencyHeaders())),
    payableStats: (params) => api.get('/checks/payable/summary/stats', { params }),
    // Alerts
    getDueAlerts: (params) => api.get('/checks/due-alerts', { params }),
    // Aging Report
    getAgingReport: (params) => api.get('/checks/aging', { params }),
}

export const notesAPI = {
    // Notes Receivable
    listReceivable: (params) => api.get('/notes/receivable', { params }),
    getReceivable: (id) => api.get(`/notes/receivable/${id}`),
    createReceivable: (data) => withPermission('treasury.create', () => api.post('/notes/receivable', data, idempotencyHeaders())),
    collectReceivable: (id, data) => withPermission('treasury.create', () => api.post(`/notes/receivable/${id}/collect`, data, idempotencyHeaders())),
    protestReceivable: (id, data) => withPermission('treasury.create', () => api.post(`/notes/receivable/${id}/protest`, data, idempotencyHeaders())),
    receivableStats: (params) => api.get('/notes/receivable/summary/stats', { params }),
    // Notes Payable
    listPayable: (params) => api.get('/notes/payable', { params }),
    getPayable: (id) => api.get(`/notes/payable/${id}`),
    createPayable: (data) => withPermission('treasury.create', () => api.post('/notes/payable', data, idempotencyHeaders())),
    payPayable: (id, data) => withPermission('treasury.create', () => api.post(`/notes/payable/${id}/pay`, data, idempotencyHeaders())),
    protestPayable: (id, data) => withPermission('treasury.create', () => api.post(`/notes/payable/${id}/protest`, data, idempotencyHeaders())),
    payableStats: (params) => api.get('/notes/payable/summary/stats', { params }),
    // Alerts
    getDueAlerts: (params) => api.get('/notes/due-alerts', { params }),

    // Status Lifecycle Log (B3)
    getCheckStatusLog: (checkType, checkId) => api.get(`/checks/status-log/${checkType}/${checkId}`),
    getCheckStatusSummary: () => api.get('/checks/status-log/summary'),
}
