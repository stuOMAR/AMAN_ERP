import api from './apiClient'

export const servicesAPI = {
    // Service Requests
    listRequests: (params) => api.get('/services/requests', { params }),
    getRequestStats: () => api.get('/services/requests/stats'),
    getRequest: (id) => api.get(`/services/requests/${id}`),
    createRequest: (data) => api.post('/services/requests', data),
    updateRequest: (id, data) => api.put(`/services/requests/${id}`, data),
    deleteRequest: (id) => api.delete(`/services/requests/${id}`),
    assignTechnician: (id, data) => api.post(`/services/requests/${id}/assign`, data),
    addCost: (id, data) => api.post(`/services/requests/${id}/costs`, data),
    deleteCost: (reqId, costId) => api.delete(`/services/requests/${reqId}/costs/${costId}`),
    listTechnicians: () => api.get('/services/technicians'),

    // Documents
    listDocuments: (params) => api.get('/services/documents', { params }),
    getDocument: (id) => api.get(`/services/documents/${id}`),
    uploadDocument: (formData) => api.post('/services/documents', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
    }),
    updateDocument: (id, data) => api.put(`/services/documents/${id}`, data),
    uploadVersion: (id, formData) => api.post(`/services/documents/${id}/versions`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
    }),
    downloadDocument: (id) => api.get(`/services/documents/${id}/download`, { responseType: 'blob', skipAbort: true }),
    deleteDocument: (id) => api.delete(`/services/documents/${id}`),
}
