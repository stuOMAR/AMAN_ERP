import api from './apiClient'

const idempotencyHeaders = () => ({
    headers: { 'Idempotency-Key': globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}` }
})

export const projectsAPI = {
    list: (params) => api.get('/projects/', { params }),
    summary: (params) => api.get('/projects/summary', { params }),
    get: (id) => api.get(`/projects/${id}`),
    create: (data) => api.post('/projects/', data, idempotencyHeaders()),
    update: (id, data) => api.put(`/projects/${id}`, data),
    delete: (id) => api.delete(`/projects/${id}`),
    getTasks: (id) => api.get(`/projects/${id}/tasks`),
    createTask: (id, data) => api.post(`/projects/${id}/tasks`, data),
    updateTask: (id, tid, data) => api.put(`/projects/${id}/tasks/${tid}`, data),
    deleteTask: (id, tid) => api.delete(`/projects/${id}/tasks/${tid}`),
    getExpenses: (id) => api.get(`/projects/${id}/expenses`),
    createExpense: (id, data) => api.post(`/projects/${id}/expenses`, data, idempotencyHeaders()),
    getRevenues: (id) => api.get(`/projects/${id}/revenues`),
    createRevenue: (id, data) => api.post(`/projects/${id}/revenues`, data, idempotencyHeaders()),
    getFinancials: (id) => api.get(`/projects/${id}/financials`),
    listTimesheets: (id) => api.get(`/projects/${id}/timesheets`),
    createTimesheet: (id, data) => api.post(`/projects/${id}/timesheets`, data, idempotencyHeaders()),
    updateTimesheet: (id, data) => api.put(`/projects/timesheets/${id}`, data),
    deleteTimesheet: (id) => api.delete(`/projects/timesheets/${id}`),
    approveTimesheets: (id, data) => api.post(`/projects/${id}/timesheets/approve`, data, idempotencyHeaders()),
    getResourceAllocation: (params) => api.get('/projects/resources/allocation', { params }),
    getProfitabilityReport: (params) => api.get('/projects/reports/profitability', { params }),
    getResourceUtilization: (params) => api.get('/projects/reports/resource-utilization', { params }),

    // Documents
    uploadDocument: (id, formData) => api.post(`/projects/${id}/documents`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
    }),
    getDocuments: (id) => api.get(`/projects/${id}/documents`),
    downloadDocument: (fileUrl) => api.get(fileUrl, { responseType: 'blob', skipAbort: true }),
    deleteDocument: (id, docId) => api.delete(`/projects/${id}/documents/${docId}`),

    // Invoicing
    previewInvoice: (id, data) => api.post(`/projects/${id}/create-invoice/preview`, data),
    createInvoice: (id, data) => api.post(`/projects/${id}/create-invoice`, data, idempotencyHeaders()),

    // Alerts
    getAlertsDashboard: () => api.get('/projects/alerts/dashboard'),
    getOverBudgetAlerts: () => api.get('/projects/alerts/over-budget'),
    getOverdueTaskAlerts: () => api.get('/projects/alerts/overdue-tasks'),

    // Change Orders
    getChangeOrders: (projectId) => api.get(`/projects/${projectId}/change-orders`),
    createChangeOrder: (projectId, data) => api.post(`/projects/${projectId}/change-orders`, data, idempotencyHeaders()),
    updateChangeOrder: (coId, data) => api.put(`/projects/change-orders/${coId}`, data),
    approveChangeOrder: (coId) => api.post(`/projects/change-orders/${coId}/approve`, null, idempotencyHeaders()),

    // EVM & Analysis
    getEVM: (projectId) => api.get(`/projects/${projectId}/evm`),
    closeProject: (projectId) => api.post(`/projects/${projectId}/close`, null, idempotencyHeaders()),
    getVarianceReport: (params) => api.get('/projects/reports/variance', { params }),

    // Retainer
    setupRetainer: (projectId, data) => api.put(`/projects/${projectId}/retainer-setup`, data),
    generateRetainerInvoices: (data) => api.post('/projects/retainer/generate-invoices', data, idempotencyHeaders()),

    // Project Risks (B5)
    listProjectRisks: (projectId) => api.get(`/projects/${projectId}/risks`),
    createProjectRisk: (projectId, data) => api.post(`/projects/${projectId}/risks`, data),
    updateProjectRisk: (riskId, data) => api.put(`/projects/risks/${riskId}`, data),
    deleteProjectRisk: (riskId) => api.delete(`/projects/risks/${riskId}`),

    // Task Dependencies (B5)
    listTaskDependencies: (projectId) => api.get(`/projects/${projectId}/task-dependencies`),
    createTaskDependency: (projectId, data) => api.post(`/projects/${projectId}/task-dependencies`, data),
    deleteTaskDependency: (depId) => api.delete(`/projects/task-dependencies/${depId}`),
}

// US17 — Time Tracking API
export const timesheetAPI = {
    // Employee: log / list / update / submit
    logEntry: (data) => api.post('/projects/timetracking', data, idempotencyHeaders()),
    listOwn: (params) => api.get('/projects/timetracking', { params }),
    getWeekSummary: (params) => api.get('/projects/timetracking/week-summary', { params }),
    updateEntry: (id, data) => api.put(`/projects/timetracking/${id}`, data),
    submitWeek: (data) => api.post('/projects/timetracking/submit-week', data, idempotencyHeaders()),

    // Manager: team view + approve / reject
    listTeam: (params) => api.get('/projects/timetracking/team', { params }),
    approve: (id) => api.post(`/projects/timetracking/${id}/approve`, null, idempotencyHeaders()),
    reject: (id, data) => api.post(`/projects/timetracking/${id}/reject`, data, idempotencyHeaders()),

    // Profitability report
    getProfitability: (projectId) => api.get(`/projects/timetracking/profitability/${projectId}`),
}

// US18 — Resource Planning API
export const resourceAPI = {
    getAvailability: (params) => api.get('/projects/resources/availability', { params }),
    allocate: (data) => api.post('/projects/resources/allocate', data, idempotencyHeaders()),
    updateAllocation: (id, data) => api.put(`/projects/resources/allocate/${id}`, data, idempotencyHeaders()),
    deleteAllocation: (id) => api.delete(`/projects/resources/allocate/${id}`),
    getProjectResources: (projectId) => api.get(`/projects/resources/project/${projectId}`),
}
