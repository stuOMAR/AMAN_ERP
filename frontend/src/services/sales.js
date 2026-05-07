import api from './apiClient'

export const salesAPI = {
    listCustomers: (params) => api.get('/sales/customers', { params }),
    getCustomer: (id) => api.get(`/sales/customers/${id}`),
    createCustomer: (data) => api.post('/sales/customers', data),
    updateCustomer: (id, data) => api.put(`/sales/customers/${id}`, data),
    listInvoices: (params) => api.get('/sales/invoices', { params }),
    createInvoice: (data) => api.post('/sales/invoices', data),
    getInvoice: (id) => api.get(`/sales/invoices/${id}`),
    cancelInvoice: (id) => api.post(`/sales/invoices/${id}/cancel`),

    // Sales Orders
    listOrders: (params) => api.get('/sales/orders', { params }),
    getOrder: (id) => api.get(`/sales/orders/${id}`),
    createOrder: (data) => api.post('/sales/orders', data),

    // Quotations
    listQuotations: (params) => api.get('/sales/quotations', { params }),
    getQuotation: (id) => api.get(`/sales/quotations/${id}`),
    createQuotation: (data) => api.post('/sales/quotations', data),
    sendQuotation: (id) => api.post(`/sales/quotations/${id}/send-email`),

    // Customer Groups
    listCustomerGroups: (params) => api.get('/sales/customer-groups', { params }),
    createCustomerGroup: (data) => api.post('/sales/customer-groups', data),
    updateCustomerGroup: (id, data) => api.put(`/sales/customer-groups/${id}`, data),
    deleteCustomerGroup: (id) => api.delete(`/sales/customer-groups/${id}`),

    // Sales Returns
    listReturns: (params) => api.get('/sales/returns', { params }),
    getReturn: (id) => api.get(`/sales/returns/${id}`),
    createReturn: (data) => api.post('/sales/returns', data),
    approveReturn: (id) => api.post(`/sales/returns/${id}/approve`),

    // Customer Receipts
    createReceipt: (data) => api.post('/sales/receipts', data),
    listReceipts: (params) => api.get('/sales/receipts', { params }),
    getReceipt: (id) => api.get(`/sales/receipts/${id}`),
    getOutstandingInvoices: (customerId, params) => api.get(`/sales/customers/${customerId}/outstanding-invoices`, { params }),
    getInvoicePaymentHistory: (invoiceId) => api.get(`/sales/invoices/${invoiceId}/payment-history`),
    getCustomerTransactions: (customerId, branchId) => api.get(`/sales/customers/${customerId}/transactions`, { params: { branch_id: branchId } }),

    // Customer Payments (Refunds)
    createPayment: (data) => api.post('/sales/payments', data),
    listPayments: (params) => api.get('/sales/payments', { params }),
    getPayment: (id) => api.get(`/sales/payments/${id}`),

    // Sales Credit Notes
    listCreditNotes: (params) => api.get('/sales/credit-notes', { params }),
    getCreditNote: (id) => api.get(`/sales/credit-notes/${id}`),
    createCreditNote: (data) => api.post('/sales/credit-notes', data),

    // Sales Debit Notes
    listDebitNotes: (params) => api.get('/sales/debit-notes', { params }),
    getDebitNote: (id) => api.get(`/sales/debit-notes/${id}`),
    createDebitNote: (data) => api.post('/sales/debit-notes', data),

    getSummary: (params) => api.get('/sales/summary', { params }),

    // Phase 8.12 - Sales Improvements
    convertQuotation: (sqId) => api.post(`/sales/quotations/${sqId}/convert`),
    // Commissions
    listCommissionRules: () => api.get('/sales/commissions/rules'),
    createCommissionRule: (data) => api.post('/sales/commissions/rules', data),
    listCommissions: (params) => api.get('/sales/commissions', { params }),
    calculateCommissions: (data) => api.post('/sales/commissions/calculate', data),
    getCommissionSummary: (params) => api.get('/sales/commissions/summary', { params }),
    // Partial Invoicing
    createPartialInvoice: (orderId, data) => api.post(`/sales/orders/${orderId}/partial-invoice`, data),
    // Credit Limit
    getCreditStatus: (partyId) => api.get(`/sales/customers/${partyId}/credit-status`),
    updateCreditLimit: (partyId, data) => api.put(`/sales/customers/${partyId}/credit-limit`, data),
    checkCredit: (data) => api.post('/sales/credit-check', data),
}

// Delivery Orders
export const deliveryOrdersAPI = {
    list: (params) => api.get('/sales/delivery-orders', { params }),
    get: (id) => api.get(`/sales/delivery-orders/${id}`),
    create: (data) => api.post('/sales/delivery-orders', data),
    update: (id, data) => api.put(`/sales/delivery-orders/${id}`, data),
    confirm: (id) => api.post(`/sales/delivery-orders/${id}/confirm`),
    deliver: (id) => api.post(`/sales/delivery-orders/${id}/deliver`),
    createInvoice: (id) => api.post(`/sales/delivery-orders/${id}/create-invoice`),
    cancel: (id) => api.post(`/sales/delivery-orders/${id}/cancel`),
}

// CPQ
export const cpqAPI = {
    listProducts: (params) => api.get('/sales/cpq/products', { params }),
    getConfiguration: (id) => api.get(`/sales/cpq/products/${id}/configure`),
    validateConfig: (data) => api.post('/sales/cpq/validate', data),
    calculatePrice: (data) => api.post('/sales/cpq/price', data),
    createQuote: (data) => api.post('/sales/cpq/quotes', data),
    getQuote: (id) => api.get(`/sales/cpq/quotes/${id}`),
    generatePdf: (id) => api.post(`/sales/cpq/quotes/${id}/generate-pdf`),
    convertQuote: (id) => api.post(`/sales/cpq/quotes/${id}/convert`),
}
