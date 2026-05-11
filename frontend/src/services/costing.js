import api from './apiClient'

export const costingLayerAPI = {
    listLayers: (params) => api.get('/inventory/costing/layers', { params }),
    getProductLayers: (productId, params) => api.get(`/inventory/costing/layers/${productId}`, { params }),
    changeMethod: (data) => api.put('/inventory/costing/method', data),
    getValuation: (params) => api.get('/inventory/costing/valuation', { params }),
    getConsumptionHistory: (productId) => api.get(`/inventory/costing/consumption/${productId}`),
}
