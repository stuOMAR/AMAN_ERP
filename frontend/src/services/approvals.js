import api from './apiClient'

const withIdempotency = (prefix = 'approval-action') => ({
    headers: {
        'Idempotency-Key': `${prefix}:${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`}`
    }
})

export const approvalsAPI = {
    // Workflows CRUD
    listWorkflows: (params) => api.get('/approvals/workflows', { params }),
    getWorkflow: (id) => api.get(`/approvals/workflows/${id}`),
    createWorkflow: (data) => api.post('/approvals/workflows', data),
    updateWorkflow: (id, data) => api.put(`/approvals/workflows/${id}`, data),
    deleteWorkflow: (id) => api.delete(`/approvals/workflows/${id}`),

    // Approval Requests
    listRequests: (params) => api.get('/approvals/requests', { params }),
    getRequest: (id) => api.get(`/approvals/requests/${id}`),
    createRequest: (data) => api.post('/approvals/requests', data),
    takeAction: (id, data) => api.post(`/approvals/requests/${id}/action`, data, withIdempotency()),

    // Pending approvals for current user
    listPending: (params) => api.get('/approvals/pending', { params }),

    // Stats
    getStats: () => api.get('/approvals/stats'),

    // Document types
    getDocumentTypes: () => api.get('/approvals/document-types'),
}
