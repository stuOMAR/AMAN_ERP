import api from './apiClient'

export const purchasesAPI = {
    createInvoice: (data) => api.post('/buying/invoices', data),
    listInvoices: (params) => api.get('/buying/invoices', { params }),
    getInvoice: (id) => api.get(`/buying/invoices/${id}`),
    cancelInvoice: (id) => api.post(`/buying/invoices/${id}/cancel`),

    // Suppliers are owned by the inventory/parties router and reused by buying flows.
    listSuppliers: (params) => api.get('/inventory/suppliers', { params }),
    createSupplier: (data) => api.post('/inventory/suppliers', data),

    // Purchase Orders
    listOrders: (params) => api.get('/buying/orders', { params }),
    getOrder: (id) => api.get(`/buying/orders/${id}`),
    createOrder: (data) => api.post('/buying/orders', data),
    approveOrder: (id) => api.put(`/buying/orders/${id}/approve`),
    receiveOrder: (id, data) => api.post(`/buying/orders/${id}/receive`, data),

    // Supplier Groups
    listSupplierGroups: (params) => api.get('/buying/supplier-groups', { params }),
    createSupplierGroup: (data) => api.post('/buying/supplier-groups', data),
    updateSupplierGroup: (id, data) => api.put(`/buying/supplier-groups/${id}`, data),
    deleteSupplierGroup: (id) => api.delete(`/buying/supplier-groups/${id}`),

    // Supplier Payments
    createPayment: (data) => api.post('/buying/payments', data),
    listPayments: (params) => api.get('/buying/payments', { params }),
    getPayment: (id) => api.get(`/buying/payments/${id}`),
    getOutstandingInvoices: (supplierId, params) => api.get(`/buying/suppliers/${supplierId}/outstanding-invoices`, { params }),
    getInvoicePaymentHistory: (invoiceId) => api.get(`/buying/invoices/${invoiceId}/payment-history`),
    getSupplierTransactions: (supplierId, branchId) => api.get(`/buying/suppliers/${supplierId}/transactions`, { params: { branch_id: branchId } }),

    // Purchase Returns
    listReturns: (params) => api.get('/buying/returns', { params }),
    createReturn: (data) => api.post('/buying/returns', data),
    getReturn: (id) => api.get(`/buying/returns/${id}`),
    cancelReturn: (id) => api.post(`/buying/returns/${id}/cancel`),

    // Purchase Credit Notes
    listCreditNotes: (params) => api.get('/buying/credit-notes', { params }),
    getCreditNote: (id) => api.get(`/buying/credit-notes/${id}`),
    createCreditNote: (data) => api.post('/buying/credit-notes', data),

    // Purchase Debit Notes
    listDebitNotes: (params) => api.get('/buying/debit-notes', { params }),
    getDebitNote: (id) => api.get(`/buying/debit-notes/${id}`),
    createDebitNote: (data) => api.post('/buying/debit-notes', data),

    getSummary: (params) => api.get('/buying/summary', { params }),

    // Phase 8.11 - Purchases Improvements
    // RFQ
    listRFQs: (params) => api.get('/buying/rfq', { params }),
    getRFQ: (id) => api.get(`/buying/rfq/${id}`),
    createRFQ: (data) => api.post('/buying/rfq', data),
    sendRFQ: (id) => api.put(`/buying/rfq/${id}/send`),
    addRFQResponse: (id, data) => api.post(`/buying/rfq/${id}/responses`, data),
    compareRFQ: (id) => api.post(`/buying/rfq/${id}/compare`),
    convertRFQtoPO: (id, data) => api.post(`/buying/rfq/${id}/convert`, data),
    // Supplier Ratings
    listSupplierRatings: (params) => api.get('/buying/supplier-ratings', { params }),
    getSupplierRatingSummary: (supplierId) => api.get(`/buying/supplier-ratings/summary/${supplierId}`),
    createSupplierRating: (data) => api.post('/buying/supplier-ratings', data),
    // Purchase Agreements
    listAgreements: (params) => api.get('/buying/agreements', { params }),
    getAgreement: (id) => api.get(`/buying/agreements/${id}`),
    createAgreement: (data) => api.post('/buying/agreements', data),
    activateAgreement: (id) => api.put(`/buying/agreements/${id}/activate`),
    callOffAgreement: (id, data) => api.post(`/buying/agreements/${id}/call-off`, data),

    // Three-Way Matching
    listMatches: (params) => api.get('/buying/matches', { params }),
    getMatch: (id) => api.get(`/buying/matches/${id}`),
    approveMatch: (id, data) => api.put(`/buying/matches/${id}/approve`, data),
    rejectMatch: (id, data) => api.put(`/buying/matches/${id}/reject`, data),

    // Match Tolerances
    listTolerances: () => api.get('/buying/tolerances'),
    saveTolerance: (data) => api.post('/buying/tolerances', data),

    // Blanket Purchase Orders (US10)
    listBlanketPOs: (params) => api.get('/buying/blanket', { params }),
    getBlanketPO: (id) => api.get(`/buying/blanket/${id}`),
    createBlanketPO: (data) => api.post('/buying/blanket', data),
    activateBlanketPO: (id) => api.put(`/buying/blanket/${id}/activate`),
    createBlanketPORelease: (id, data) => api.post(`/buying/blanket/${id}/release`, data),
    amendBlanketPOPrice: (id, data) => api.put(`/buying/blanket/${id}/amend-price`, data),
}

// Landed Costs
export const landedCostsAPI = {
    list: (params) => api.get('/purchases/landed-costs', { params }),
    get: (id) => api.get(`/purchases/landed-costs/${id}`),
    create: (data) => api.post('/purchases/landed-costs', data),
    allocate: (id, data) => api.post(`/purchases/landed-costs/${id}/allocate`, data),
    post: (id) => api.post(`/purchases/landed-costs/${id}/post`),
}
