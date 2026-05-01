import api from './apiClient'

export const hrAPI = {
    listEmployees: (params) => api.get('/hr/employees', { params }),
    createEmployee: (data) => api.post('/hr/employees', data),
    getEmployee: (id) => api.get(`/hr/employees/${id}`),
    updateEmployee: (id, data) => api.put(`/hr/employees/${id}`, data),

    // Payroll
    listPayrollPeriods: () => api.get('/hr/payroll-periods'),
    createPayrollPeriod: (data) => api.post('/hr/payroll-periods', data),
    getPayrollPeriod: (id) => api.get(`/hr/payroll-periods/${id}`),
    getPayrollEntries: (id, params) => api.get(`/hr/payroll-periods/${id}/entries`, { params }),
    generatePayroll: (id) => api.post(`/hr/payroll-periods/${id}/generate`),
    postPayroll: (id) => api.post(`/hr/payroll-periods/${id}/post`),

    // Configuration
    listDepartments: () => api.get('/hr/departments'),
    createDepartment: (data) => api.post('/hr/departments', data),
    deleteDepartment: (id) => api.delete(`/hr/departments/${id}`),

    listPositions: () => api.get('/hr/positions'),
    createPosition: (data) => api.post('/hr/positions', data),
    deletePosition: (id) => api.delete(`/hr/positions/${id}`),

    // Loans
    listLoans: (params) => api.get('/hr/loans', { params }),
    createLoan: (data) => api.post('/hr/loans', data),
    approveLoan: (id) => api.put(`/hr/loans/${id}/approve`),

    // Leave Requests
    listLeaveRequests: (params) => api.get('/hr/leaves', { params }),
    createLeaveRequest: (data) => api.post('/hr/leaves', data),
    updateLeaveStatus: (id, status) => api.put(`/hr/leaves/${id}/status`, null, { params: { status_in: status } }),

    // End of Service
    calculateEndOfService: (data) => api.post('/hr/end-of-service/calculate', data),
}

export const hrAdvancedAPI = {
    // Salary Structures
    listSalaryStructures: () => api.get('/hr-advanced/salary-structures'),
    createSalaryStructure: (data) => api.post('/hr-advanced/salary-structures', data),
    updateSalaryStructure: (id, data) => api.put(`/hr-advanced/salary-structures/${id}`, data),
    deleteSalaryStructure: (id) => api.delete(`/hr-advanced/salary-structures/${id}`),

    // Salary Components
    listSalaryComponents: (params) => api.get('/hr-advanced/salary-components', { params }),
    createSalaryComponent: (data) => api.post('/hr-advanced/salary-components', data),
    updateSalaryComponent: (id, data) => api.put(`/hr-advanced/salary-components/${id}`, data),

    // Employee Salary Components
    getEmployeeSalaryComponents: (empId) => api.get(`/hr-advanced/employee-salary-components/${empId}`),
    assignSalaryComponent: (data) => api.post('/hr-advanced/employee-salary-components', data),

    // Overtime
    listOvertime: (params) => api.get('/hr-advanced/overtime', { params }),
    createOvertime: (data) => api.post('/hr-advanced/overtime', data),
    approveOvertime: (id, data) => api.put(`/hr-advanced/overtime/${id}/approve`, data),
    // T8.4: configurable rate multipliers from backend (overtime_rates_config).
    getOvertimeRates: () => api.get('/hr-advanced/overtime/rates', { skipGlobalToast: true }),

    // GOSI
    getGOSISettings: () => api.get('/hr-advanced/gosi-settings'),
    saveGOSISettings: (data) => api.post('/hr-advanced/gosi-settings', data),
    calculateGOSI: () => api.get('/hr-advanced/gosi-calculation'),

    // Documents
    listDocuments: (params) => api.get('/hr-advanced/documents', { params }),
    createDocument: (data) => api.post('/hr-advanced/documents', data),
    updateDocument: (id, data) => api.put(`/hr-advanced/documents/${id}`, data),
    deleteDocument: (id) => api.delete(`/hr-advanced/documents/${id}`),

    // Performance Reviews
    listPerformanceReviews: (params) => api.get('/hr-advanced/performance-reviews', { params }),
    createPerformanceReview: (data) => api.post('/hr-advanced/performance-reviews', data),
    updatePerformanceReview: (id, data) => api.put(`/hr-advanced/performance-reviews/${id}`, data),

    // Performance Cycles (US12)
    listCycles: (params) => api.get('/hr/performance/cycles', { params }),
    createCycle: (data) => api.post('/hr/performance/cycles', data),
    launchCycle: (id) => api.post(`/hr/performance/cycles/${id}/launch`),
    listMyReviews: (params) => api.get('/hr/performance/reviews', { params }),
    getReviewDetail: (id) => api.get(`/hr/performance/reviews/${id}`),
    submitSelfAssessment: (id, data) => api.put(`/hr/performance/reviews/${id}/self-assessment`, data),
    listTeamReviews: (params) => api.get('/hr/performance/team-reviews', { params }),
    submitManagerAssessment: (id, data) => api.put(`/hr/performance/reviews/${id}/manager-assessment`, data),
    finalizeReview: (id) => api.post(`/hr/performance/reviews/${id}/finalize`),
    addGoal: (reviewId, data) => api.post(`/hr/performance/reviews/${reviewId}/goals`, data),
    listGoals: (reviewId) => api.get(`/hr/performance/reviews/${reviewId}/goals`),
    deleteGoal: (goalId) => api.delete(`/hr/performance/goals/${goalId}`),

    // Training
    listTraining: () => api.get('/hr-advanced/training'),
    createTraining: (data) => api.post('/hr-advanced/training', data),
    updateTraining: (id, data) => api.put(`/hr-advanced/training/${id}`, data),
    listParticipants: (id) => api.get(`/hr-advanced/training/${id}/participants`),
    addParticipant: (id, data) => api.post(`/hr-advanced/training/${id}/participants`, data),
    updateParticipant: (id, data) => api.put(`/hr-advanced/training/participants/${id}`, data),

    // Violations
    listViolations: (params) => api.get('/hr-advanced/violations', { params }),
    createViolation: (data) => api.post('/hr-advanced/violations', data),
    updateViolation: (id, data) => api.put(`/hr-advanced/violations/${id}`, data),

    // Custody
    listCustody: (params) => api.get('/hr-advanced/custody', { params }),
    createCustody: (data) => api.post('/hr-advanced/custody', data),
    updateCustody: (id, data) => api.put(`/hr-advanced/custody/${id}`, data),
    returnCustody: (id, data) => api.put(`/hr-advanced/custody/${id}/return`, data),

    // GOSI Export
    exportGOSI: (params) => api.get('/hr-advanced/gosi-export', { params, responseType: 'blob' }),
}

export const hrImprovementsAPI = {
    // Payslips
    listPayslips: (params) => api.get('/hr/payslips', { params }),
    generatePayslip: (data) => api.post('/hr/payslips/generate', data),
    getPayslip: (entryId) => api.get(`/hr/payslips/${entryId}`),
    getEmployeePayslips: (empId, params) => api.get(`/hr/employees/${empId}/payslips`, { params }),
    // Leave Balance & Carryover
    getLeaveBalance: (empId) => api.get(`/hr/leave-balance/${empId}`),
    calculateLeaveCarryover: (data) => api.post('/hr/leave-carryover/calculate', data),
    // Recruitment
    listJobOpenings: (params) => api.get('/hr/recruitment/openings', { params }),
    createJobOpening: (data) => api.post('/hr/recruitment/openings', data),
    updateJobOpening: (id, data) => api.put(`/hr/recruitment/openings/${id}`, data),
    listApplications: (openingId) => api.get(`/hr/recruitment/openings/${openingId}/applications`),
    listAllApplications: (params) => api.get('/hr/recruitment/applications', { params }),
    createApplication: (data) => api.post('/hr/recruitment/applications', data),
    updateApplicationStage: (id, data) => api.put(`/hr/recruitment/applications/${id}/stage`, data),
}

export const attendanceAPI = {
    checkIn: () => api.post('/hr/attendance/check-in'),
    checkOut: () => api.post('/hr/attendance/check-out'),
    getStatus: () => api.get('/hr/attendance/status'),
    getHistory: (params) => api.get('/hr/attendance/history', { params })
}

// WPS & Saudization (SA-specific)
export const wpsAPI = {
    exportWPS: (data) => api.post('/hr/wps/export', data, { responseType: 'blob' }),
    previewWPS: (periodId) => api.get(`/hr/wps/preview/${periodId}`),
    getSaudizationDashboard: () => api.get('/hr/saudization/dashboard'),
    getSaudizationReport: (params) => api.get('/hr/saudization/report', { params }),
    settleEndOfService: (data) => api.post('/hr/end-of-service/calculate', data),
}

// Employee Self-Service (US6)
export const selfServiceAPI = {
    getProfile: () => api.get('/hr/self-service/profile'),
    updateProfile: (data) => api.put('/hr/self-service/profile', data),
    listPayslips: () => api.get('/hr/self-service/payslips'),
    getPayslip: (id) => api.get(`/hr/self-service/payslips/${id}`),
    getLeaveBalance: () => api.get('/hr/self-service/leave-balance'),
    submitLeaveRequest: (data) => api.post('/hr/self-service/leave-request', data),
    listLeaveRequests: (params) => api.get('/hr/self-service/leave-requests', { params }),
    listTeamRequests: (params) => api.get('/hr/self-service/team-requests', { params }),
    approveLeave: (id) => api.post(`/hr/self-service/leave-request/${id}/approve`),
    rejectLeave: (id, reason) => api.post(`/hr/self-service/leave-request/${id}/reject`, null, { params: { reason } }),
}
