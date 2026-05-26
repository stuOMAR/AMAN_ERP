import api from './apiClient'

export const posAPI = {
    // Promotions
    listPromotions: (params) => api.get('/pos/promotions', { params }),
    createPromotion: (data) => api.post('/pos/promotions', data),
    updatePromotion: (id, data) => api.put(`/pos/promotions/${id}`, data),
    deletePromotion: (id) => api.delete(`/pos/promotions/${id}`),
    validateCoupon: (data) => api.post('/pos/promotions/validate', data),
    // Loyalty
    listLoyaltyPrograms: (params) => api.get('/pos/loyalty/programs', { params }),
    createLoyaltyProgram: (data) => api.post('/pos/loyalty/programs', data),
    getCustomerLoyalty: (partyId) => api.get(`/pos/loyalty/customer/${partyId}`),
    enrollLoyalty: (data) => api.post('/pos/loyalty/enroll', data),
    earnPoints: (data) => api.post('/pos/loyalty/earn', data),
    redeemPoints: (data) => api.post('/pos/loyalty/redeem', data),
    // Tables
    listTables: (params) => api.get('/pos/tables', { params }),
    createTable: (data) => api.post('/pos/tables', data),
    updateTable: (id, data) => api.put(`/pos/tables/${id}`, data),
    deleteTable: (id) => api.delete(`/pos/tables/${id}`),
    seatTable: (id, data) => api.post(`/pos/tables/${id}/seat`, data),
    clearTable: (id) => api.post(`/pos/tables/${id}/clear`),
    // Kitchen Display
    listKitchenOrders: (params) => api.get('/pos/kitchen/orders', { params }),
    createKitchenOrder: (data) => api.post('/pos/kitchen/orders', data),
    updateKitchenOrderStatus: (id, data) => api.put(`/pos/kitchen/orders/${id}/status`, data),
    // Session Reports
    getDetailedSessionReport: (sessionId) => api.get(`/pos/sessions/${sessionId}/detailed-report`),

    // Sessions
    openSession: (data) => api.post('/pos/sessions/open', data),
    closeSession: (sessionId, data) => api.post(`/pos/sessions/${sessionId}/close`, data),
    getActiveSession: () => api.get('/pos/sessions/active'),

    // Orders
    previewOrder: (data) => api.post('/pos/orders/preview', data),
    createOrder: (data, idempotencyKey) => api.post('/pos/orders', data, idempotencyKey ? {
        headers: { 'Idempotency-Key': idempotencyKey }
    } : undefined),
    getHeldOrders: () => api.get('/pos/orders/held'),
    resumeOrder: (orderId) => api.post(`/pos/orders/${orderId}/resume`),
    cancelHeldOrder: (orderId) => api.delete(`/pos/orders/${orderId}/cancel-held`),
    getOrderDetails: (orderId) => api.get(`/pos/orders/${orderId}/details`),
    returnOrder: (orderId, data) => api.post(`/pos/orders/${orderId}/return`, data),

    // Products & Warehouses for POS
    getProducts: (params) => api.get('/pos/products', { params }),
    getWarehouses: () => api.get('/pos/warehouses'),

    // PWA Support (B7)
    getPWAManifest: () => api.get('/pos/pwa/manifest'),
    getPWAConfig: () => api.get('/pos/pwa/config'),
}
