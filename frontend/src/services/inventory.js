import api from './apiClient'

export const inventoryAPI = {
    listProducts: (params) => api.get('/inventory/products', { params }),
    getProduct: (id) => api.get(`/inventory/products/${id}`),
    getProductStock: (id, warehouseId) => api.get(`/inventory/products/${id}/stock`, { params: { warehouse_id: warehouseId } }),
    createProduct: (data) => api.post('/inventory/products', data),
    updateProduct: (id, data) => api.put(`/inventory/products/${id}`, data),
    deleteProduct: (id) => api.delete(`/inventory/products/${id}`),
    listSuppliers: (params) => api.get('/inventory/suppliers', { params }),
    getSupplier: (id) => api.get(`/inventory/suppliers/${id}`),
    createSupplier: (data) => api.post('/inventory/suppliers', data),
    updateSupplier: (id, data) => api.put(`/inventory/suppliers/${id}`, data),
    deleteSupplier: (id) => api.delete(`/inventory/suppliers/${id}`),
    // Categories
    listCategories: (params) => api.get('/inventory/categories', { params }),
    createCategory: (data) => api.post('/inventory/categories', data),
    updateCategory: (id, data) => api.put(`/inventory/categories/${id}`, data),
    deleteCategory: (id) => api.delete(`/inventory/categories/${id}`),
    getNextCategoryCode: () => api.get('/inventory/categories/next-code'),

    // Warehouses
    listWarehouses: (params) => api.get('/inventory/warehouses', { params }),
    createWarehouse: (data) => api.post('/inventory/warehouses', data),
    updateWarehouse: (id, data) => api.put(`/inventory/warehouses/${id}`, data),
    deleteWarehouse: (id) => api.delete(`/inventory/warehouses/${id}`),
    getWarehouse: (id) => api.get(`/inventory/warehouses/${id}`),
    getWarehouseSpecificStock: (id) => api.get(`/inventory/warehouses/${id}/current-stock?t=${new Date().getTime()}`),

    // Transfers
    transferStock: (data) => api.post('/inventory/transfer', data),

    getSummary: (params) => api.get('/inventory/summary', { params }),

    // Price Lists
    listPriceLists: () => api.get('/inventory/price-lists'),
    createPriceList: (data) => api.post('/inventory/price-lists', data),
    updatePriceList: (id, data) => api.put(`/inventory/price-lists/${id}`, data),
    deletePriceList: (id) => api.delete(`/inventory/price-lists/${id}`),
    getPriceListItems: (id) => api.get(`/inventory/price-lists/${id}/items`),
    updatePriceListItems: (id, items) => api.post(`/inventory/price-lists/${id}/items`, items),
    getInventoryBalance: (params) => api.get('/inventory/warehouse-stock', { params }),

    // Stock Movements
    getStockMovements: (params) => api.get('/inventory/movements', { params }),

    // Shipments
    createShipment: (data) => api.post('/inventory/shipments', data),
    listShipments: (params) => api.get('/inventory/shipments', { params }),
    getIncomingShipments: (params) => api.get('/inventory/shipments/incoming', { params }),
    getShipmentDetails: (id) => api.get(`/inventory/shipments/${id}`),
    confirmShipment: (id) => api.post(`/inventory/shipments/${id}/confirm`),
    cancelShipment: (id) => api.post(`/inventory/shipments/${id}/cancel`),

    // Stock Adjustments
    listAdjustments: (params) => api.get('/inventory/adjustments', { params }),
    createAdjustment: (data) => api.post('/inventory/adjustments', data),
    getValuationReport: (params) => api.get('/inventory/valuation-report', { params }),

    // Batches (INV-101)
    listBatches: (params) => api.get('/inventory/batches', { params }),
    getBatch: (id) => api.get(`/inventory/batches/${id}`),
    createBatch: (data) => api.post('/inventory/batches', data),
    updateBatch: (id, data) => api.put(`/inventory/batches/${id}`, data),
    getProductBatches: (productId, params) => api.get(`/inventory/batches/product/${productId}`, { params }),
    getExpiryAlerts: (params) => api.get('/inventory/batches/expiry-alerts', { params }),

    // Serial Numbers (INV-102)
    listSerials: (params) => api.get('/inventory/serials', { params }),
    getSerial: (id) => api.get(`/inventory/serials/${id}`),
    createSerial: (data) => api.post('/inventory/serials', data),
    createSerialsBulk: (data) => api.post('/inventory/serials/bulk', data),
    updateSerial: (id, data) => api.put(`/inventory/serials/${id}`, data),
    lookupSerial: (serialNumber) => api.get(`/inventory/serials/lookup/${serialNumber}`),

    // Product Tracking Config
    updateProductTracking: (productId, params) => api.put(`/inventory/products/${productId}/tracking`, null, { params }),

    // Quality Control (INV-104)
    listQualityInspections: (params) => api.get('/inventory/quality-inspections', { params }),
    getQualityInspection: (id) => api.get(`/inventory/quality-inspections/${id}`),
    createQualityInspection: (data) => api.post('/inventory/quality-inspections', data),
    completeQualityInspection: (id, data) => api.put(`/inventory/quality-inspections/${id}/complete`, data),

    // Cycle Counts (INV-105)
    listCycleCounts: (params) => api.get('/inventory/cycle-counts', { params }),
    getCycleCount: (id) => api.get(`/inventory/cycle-counts/${id}`),
    createCycleCount: (data) => api.post('/inventory/cycle-counts', data),
    startCycleCount: (id) => api.put(`/inventory/cycle-counts/${id}/start`),
    completeCycleCount: (id, data) => api.put(`/inventory/cycle-counts/${id}/complete`, data)
}

export const costingPolicyAPI = {
    getCurrent: () => api.get('/costing-policies/current'),
    getHistory: () => api.get('/costing-policies/history'),
    setPolicy: (data) => api.post('/costing-policies/set', data)
}

export const demandForecastAPI = {
    generate: (data) => api.post('/inventory/forecast/generate', data),
    list: (productId) => api.get('/inventory/forecast', { params: productId ? { product_id: productId } : {} }),
    get: (id) => api.get(`/inventory/forecast/${id}`),
    adjust: (id, data) => api.put(`/inventory/forecast/${id}/adjust`, data),
}
