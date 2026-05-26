import api from './apiClient'
import { cleanParams } from './apiClient'

const idempotencyHeaders = () => ({
    headers: { 'Idempotency-Key': globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}` }
})

export const subscriptionsAPI = {
    // Plans
    listPlans: (params) => api.get('/finance/subscriptions/plans', { params: cleanParams(params) }),
    createPlan: (data) => api.post('/finance/subscriptions/plans', data),
    updatePlan: (id, data) => api.put(`/finance/subscriptions/plans/${id}`, data),

    // Enrollments
    enroll: (data) => api.post('/finance/subscriptions/enroll', data, idempotencyHeaders()),
    listEnrollments: (params) => api.get('/finance/subscriptions/enrollments', { params: cleanParams(params) }),
    getEnrollment: (id) => api.get(`/finance/subscriptions/enrollments/${id}`),
    pauseEnrollment: (id) => api.post(`/finance/subscriptions/enrollments/${id}/pause`, null, idempotencyHeaders()),
    resumeEnrollment: (id) => api.post(`/finance/subscriptions/enrollments/${id}/resume`, null, idempotencyHeaders()),
    cancelEnrollment: (id, data) => api.post(`/finance/subscriptions/enrollments/${id}/cancel`, data, idempotencyHeaders()),
    changePlan: (id, data) => api.post(`/finance/subscriptions/enrollments/${id}/change-plan`, data, idempotencyHeaders()),
}
