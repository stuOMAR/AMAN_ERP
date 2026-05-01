import api from './apiClient'
import { cleanParams } from './apiClient'

export const smartAlertsAPI = {
    listRules: () => api.get('/alerts/rules'),
    createRule: (data) => api.post('/alerts/rules', data),
    updateRule: (id, data) => api.put(`/alerts/rules/${id}`, data),
    deleteRule: (id) => api.delete(`/alerts/rules/${id}`),

    listAlerts: (params) => api.get('/alerts/', { params: cleanParams(params) }),
    resolveAlert: (id) => api.post(`/alerts/${id}/resolve`),
}
