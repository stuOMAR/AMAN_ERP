import api from './apiClient'
import { cleanParams } from './apiClient'
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

export const expensesAPI = {
    list: (params) => api.get('/expenses/', { params: cleanParams(params) }),
    summary: (params) => api.get('/expenses/summary', { params: cleanParams(params) }),
    get: (id) => api.get(`/expenses/${id}`),
    create: (data) => api.post('/expenses/', data),
    update: (id, data) => withPermission('expenses.edit', () => api.put(`/expenses/${id}`, data)),
    approve: (id, data) => withPermission('expenses.approve', () => api.post(`/expenses/${id}/approve`, data)),
    reverse: (id, data) => withPermission('expenses.approve', () => api.post(`/expenses/${id}/reverse`, data)),
    delete: (id) => withPermission('expenses.delete', () => api.delete(`/expenses/${id}`)),
    getReportByType: (params) => api.get('/expenses/reports/by-type', { params: cleanParams(params) }),
    getReportByCostCenter: (params) => api.get('/expenses/reports/by-cost-center', { params: cleanParams(params) }),
    getReportMonthly: (params) => api.get('/expenses/reports/monthly', { params: cleanParams(params) }),

    // Expense Policies (C1)
    listPolicies: () => api.get('/expenses/policies'),
    createPolicy: (data) => api.post('/expenses/policies', data),
    updatePolicy: (id, data) => api.put(`/expenses/policies/${id}`, data),
    deletePolicy: (id) => api.delete(`/expenses/policies/${id}`),
    validatePolicy: (data) => api.post('/expenses/validate-policy', data),
}
