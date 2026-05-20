import api from './apiClient'

export const taxesAPI = {
    getVATReport: (params) => api.get('/taxes/vat-report', { params }),
    getTaxAudit: (params) => api.get('/taxes/audit-report', { params }),
    getSummary: (params) => api.get('/taxes/summary', { params }),
    // Tax Rates
    listRates: (params) => api.get('/taxes/rates', { params }),
    getRate: (id) => api.get(`/taxes/rates/${id}`),
    createRate: (data) => api.post('/taxes/rates', data),
    updateRate: (id, data) => api.put(`/taxes/rates/${id}`, data),
    deleteRate: (id) => api.delete(`/taxes/rates/${id}`),
    // Branch Tax (auto-resolve)
    getBranchTax: (branchId) => api.get(`/taxes/rates/branch/${branchId}`),
    // Tax History (audit trail)
    getTaxHistory: (taxId) => api.get(`/taxes/rates/${taxId}/history`),
    // Tax Groups
    listGroups: () => api.get('/taxes/groups'),
    createGroup: (data) => api.post('/taxes/groups', data),
    // Tax Classifications
    listClassifications: () => api.get('/tax-compliance/classifications'),
    listClassificationsForCountry: (countryCode) => api.get(`/tax-compliance/classifications/by-country/${countryCode}`),
    createClassification: (data) => api.post('/tax-compliance/classifications', data),
    updateClassification: (id, data) => api.put(`/tax-compliance/classifications/${id}`, data),
    deleteClassification: (id) => api.delete(`/tax-compliance/classifications/${id}`),
    getClassificationRates: (id) => api.get(`/tax-compliance/classifications/${id}/rates`),
    addClassificationRate: (id, data) => api.post(`/tax-compliance/classifications/${id}/rates`, data),
    deleteClassificationRate: (id, rateLinkId) => api.delete(`/tax-compliance/classifications/${id}/rates/${rateLinkId}`),
    // Tax Returns
    listReturns: (params) => api.get('/taxes/returns', { params }),
    getReturn: (id) => api.get(`/taxes/returns/${id}`),
    createReturn: (data) => api.post('/taxes/returns', data),
    fileReturn: (id, data) => api.put(`/taxes/returns/${id}/file`, data),
    cancelReturn: (id) => api.put(`/taxes/returns/${id}/cancel`),
    // Tax Payments
    listPayments: (params) => api.get('/taxes/payments', { params }),
    createPayment: (data, idempotencyKey) => api.post('/taxes/payments', data, {
        headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined,
    }),
    // Settlement
    settle: (data) => api.post('/taxes/settle', data),
    // Branch Tax Analysis
    getBranchAnalysis: (params) => api.get('/taxes/branch-analysis', { params }),
    // Employee Tax Obligations
    getEmployeeTaxes: (params) => api.get('/taxes/employee-taxes', { params }),
    // Tax Calendar
    listCalendar: (params) => api.get('/taxes/calendar', { params }),
    getCalendarSummary: (params) => api.get('/taxes/calendar/summary', { params }),
    getCalendarItem: (id) => api.get(`/taxes/calendar/${id}`),
    createCalendarItem: (data) => api.post('/taxes/calendar', data),
    updateCalendarItem: (id, data) => api.put(`/taxes/calendar/${id}`, data),
    deleteCalendarItem: (id) => api.delete(`/taxes/calendar/${id}`),
    completeCalendarItem: (id) => api.put(`/taxes/calendar/${id}/complete`),
}

// ── Tax Compliance API ──────────────────────────────────────
export const taxComplianceAPI = {
    // Tax regimes
    listRegimes: (params) => api.get('/tax-compliance/regimes', { params }),
    listCountries: () => api.get('/tax-compliance/countries'),

    // Company tax settings
    getCompanySettings: () => api.get('/tax-compliance/company-settings'),
    updateCompanySettings: (data) => api.put('/tax-compliance/company-settings', data),

    // Branch tax settings
    getBranchSettings: (branchId) => api.get(`/tax-compliance/branch-settings/${branchId}`),
    updateBranchSetting: (data) => api.put('/tax-compliance/branch-settings', data),

    // Applicable taxes per branch
    getApplicableTaxes: (branchId) => api.get(`/tax-compliance/applicable-taxes/${branchId}`),

    // Country-specific reports
    getSaudiVATReport: (params) => api.get('/tax-compliance/reports/sa-vat', { params }),
    getSyrianIncomeReport: (params) => api.get('/tax-compliance/reports/sy-income', { params }),
    getUAEVATReport: (params) => api.get('/tax-compliance/reports/ae-vat', { params }),
    getEgyptVATReport: (params) => api.get('/tax-compliance/reports/eg-vat', { params }),
    getTurkeyKDVReport: (params) => api.get('/tax-compliance/reports/tr-kdv', { params }),
    getGenericIncomeReport: (params) => api.get('/tax-compliance/reports/generic-income', { params }),

    // Compliance overview
    getOverview: (params) => api.get('/tax-compliance/overview', { params }),
}
