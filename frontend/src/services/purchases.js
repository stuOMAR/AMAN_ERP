import api from './apiClient'
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

const withPermissions = (permissions, request) => {
    permissions.forEach(requireFrontendPermission)
    return request()
}

const idempotencyHeaders = () => ({
    headers: { 'Idempotency-Key': globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}` }
})

export const purchasesAPI = {
    createInvoice: (data) => withPermission('buying.create', () => api.post('/buying/invoices', data, idempotencyHeaders())),
    listInvoices: (params) => api.get('/buying/invoices', { params }),
    getInvoice: (id) => api.get(`/buying/invoices/${id}`),
    cancelInvoice: (id) => api.post(`/buying/invoices/${id}/cancel`),

    // Suppliers are owned by the inventory/parties router and reused by buying flows.
    listSuppliers: (params) => api.get('/inventory/suppliers', { params }),
    createSupplier: (data) => withPermission('buying.create', () => api.post('/inventory/suppliers', data)),

    // Purchase Orders
    listOrders: (params) => api.get('/buying/orders', { params }),
    getOrder: (id) => api.get(`/buying/orders/${id}`),
    createOrder: (data) => withPermission('buying.create', () => api.post('/buying/orders', data, idempotencyHeaders())),
    approveOrder: (id) => withPermission('buying.approve', () => api.put(`/buying/orders/${id}/approve`)),
    receiveOrder: (id, data) => withPermission('buying.receive', () => api.post(`/buying/orders/${id}/receive`, data, idempotencyHeaders())),

    // Supplier Groups
    listSupplierGroups: (params) => api.get('/buying/supplier-groups', { params }),
    createSupplierGroup: (data) => withPermission('buying.create', () => api.post('/buying/supplier-groups', data)),
    updateSupplierGroup: (id, data) => withPermission('buying.edit', () => api.put(`/buying/supplier-groups/${id}`, data)),
    deleteSupplierGroup: (id) => api.delete(`/buying/supplier-groups/${id}`),

    // Supplier Payments
    previewPayment: (data) => withPermissions(['buying.view', 'treasury.view'], () => api.post('/buying/payments/preview', data)),
    createPayment: (data) => withPermissions(['buying.create', 'treasury.create'], () => api.post('/buying/payments', data, idempotencyHeaders())),
    listPayments: (params) => api.get('/buying/payments', { params }),
    getPayment: (id) => api.get(`/buying/payments/${id}`),
    getOutstandingInvoices: (supplierId, params) => api.get(`/buying/suppliers/${supplierId}/outstanding-invoices`, { params }),
    getInvoicePaymentHistory: (invoiceId) => api.get(`/buying/invoices/${invoiceId}/payment-history`),
    getSupplierTransactions: (supplierId, branchId) => api.get(`/buying/suppliers/${supplierId}/transactions`, { params: { branch_id: branchId } }),

    // Purchase Returns
    listReturns: (params) => api.get('/buying/returns', { params }),
    createReturn: (data) => withPermission('buying.create', () => api.post('/buying/returns', data, idempotencyHeaders())),
    getReturn: (id) => api.get(`/buying/returns/${id}`),
    cancelReturn: (id) => api.post(`/buying/returns/${id}/cancel`),

    // Purchase Credit Notes
    listCreditNotes: (params) => api.get('/buying/credit-notes', { params }),
    getCreditNote: (id) => api.get(`/buying/credit-notes/${id}`),
    createCreditNote: (data) => withPermission('buying.create', () => api.post('/buying/credit-notes', data, idempotencyHeaders())),

    // Purchase Debit Notes
    listDebitNotes: (params) => api.get('/buying/debit-notes', { params }),
    getDebitNote: (id) => api.get(`/buying/debit-notes/${id}`),
    createDebitNote: (data) => withPermission('buying.create', () => api.post('/buying/debit-notes', data, idempotencyHeaders())),

    getSummary: (params) => api.get('/buying/summary', { params }),

    // Phase 8.11 - Purchases Improvements
    // RFQ
    listRFQs: (params) => api.get('/buying/rfq', { params }),
    getRFQ: (id) => api.get(`/buying/rfq/${id}`),
    createRFQ: (data) => withPermission('buying.create', () => api.post('/buying/rfq', data)),
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
    createAgreement: (data) => withPermission('buying.create', () => api.post('/buying/agreements', data)),
    activateAgreement: (id) => withPermission('buying.approve', () => api.put(`/buying/agreements/${id}/activate`)),
    callOffAgreement: (id, data) => withPermission('buying.create', () => api.post(`/buying/agreements/${id}/call-off`, data, idempotencyHeaders())),

    // Three-Way Matching
    listMatches: (params) => api.get('/buying/matches', { params }),
    getMatch: (id) => api.get(`/buying/matches/${id}`),
    approveMatch: (id, data) => withPermission('matching.approve', () => api.put(`/buying/matches/${id}/approve`, data)),
    rejectMatch: (id, data) => withPermission('matching.approve', () => api.put(`/buying/matches/${id}/reject`, data)),

    // Match Tolerances
    listTolerances: () => api.get('/buying/tolerances'),
    saveTolerance: (data) => withPermission('matching.manage', () => api.post('/buying/tolerances', data)),

    // Blanket Purchase Orders (US10)
    listBlanketPOs: (params) => api.get('/buying/blanket', { params }),
    getBlanketPO: (id) => api.get(`/buying/blanket/${id}`),
    createBlanketPO: (data) => withPermission('buying.blanket_manage', () => api.post('/buying/blanket', data)),
    activateBlanketPO: (id) => withPermission('buying.blanket_manage', () => api.put(`/buying/blanket/${id}/activate`)),
    createBlanketPORelease: (id, data) => withPermission('buying.blanket_release', () => api.post(`/buying/blanket/${id}/release`, data, idempotencyHeaders())),
    amendBlanketPOPrice: (id, data) => withPermission('buying.blanket_manage', () => api.put(`/buying/blanket/${id}/amend-price`, data)),
}

// Landed Costs
export const landedCostsAPI = {
    list: (params) => api.get('/purchases/landed-costs', { params }),
    get: (id) => api.get(`/purchases/landed-costs/${id}`),
    create: (data) => withPermission('buying.create', () => api.post('/purchases/landed-costs', data, idempotencyHeaders())),
    allocate: (id, data) => withPermission('buying.edit', () => api.post(`/purchases/landed-costs/${id}/allocate`, data, idempotencyHeaders())),
    post: (id) => withPermission('buying.approve', () => api.post(`/purchases/landed-costs/${id}/post`, null, idempotencyHeaders())),
}
