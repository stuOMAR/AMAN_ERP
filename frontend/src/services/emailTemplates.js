import api from './apiClient'

export const emailTemplatesAPI = {
    list: () => api.get('/email-templates'),
    get: (id) => api.get(`/email-templates/${id}`),
    create: (data) => api.post('/email-templates', data),
    update: (id, data) => api.put(`/email-templates/${id}`, data),
    delete: (id) => api.delete(`/email-templates/${id}`),
}
