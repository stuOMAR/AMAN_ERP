import { api } from './apiClient'

export const integrationKeysAPI = {
    list: (params) => api.get('/integrations/keys', { params }),
    create: (data) => api.post('/integrations/keys', data),
    revoke: (id) => api.post(`/integrations/keys/${id}/revoke`),
    listCircuitBreakers: () => api.get('/integrations/circuit-breakers'),
    resetCircuitBreaker: (id) => api.post(`/integrations/circuit-breakers/${id}/reset`),
}
