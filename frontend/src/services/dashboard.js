import api from './apiClient'

export const dashboardAPI = {
    // Stats & Overview
    getStats: () => api.get('/dashboard/stats'),
    getSystemStats: () => api.get('/dashboard/system-stats'),

    // Charts
    getFinancialCharts: (params) => api.get('/dashboard/charts/financial', { params }),
    getProductsCharts: (params) => api.get('/dashboard/charts/products', { params }),

    // Widgets
    getAvailableWidgets: () => api.get('/dashboard/widgets/available'),
    getCashFlowWidget: (params) => api.get('/dashboard/widgets/cash-flow', { params }),
    getLowStockWidget: () => api.get('/dashboard/widgets/low-stock'),
    getPendingTasksWidget: () => api.get('/dashboard/widgets/pending-tasks'),
    getSalesSummaryWidget: (params) => api.get('/dashboard/widgets/sales-summary', { params }),
    getTopProductsWidget: (params) => api.get('/dashboard/widgets/top-products', { params }),

    // Layouts
    getLayouts: () => api.get('/dashboard/layouts'),
    createLayout: (data) => api.post('/dashboard/layouts', data),
    updateLayout: (id, data) => api.put(`/dashboard/layouts/${id}`, data),
    deleteLayout: (id) => api.delete(`/dashboard/layouts/${id}`),

    // BI Analytics Dashboards (US9)
    listAnalyticsDashboards: () => api.get('/dashboard/analytics'),
    getAnalyticsDashboard: (id, config = {}) => api.get(`/dashboard/analytics/${id}`, config),
    createAnalyticsDashboard: (data) => api.post('/dashboard/analytics', data),
    updateAnalyticsDashboard: (id, data) => api.put(`/dashboard/analytics/${id}`, data),
    deleteAnalyticsDashboard: (id) => api.delete(`/dashboard/analytics/${id}`),
    getWidgetData: (widgetId, params) => api.get(`/dashboard/analytics/widget-data/${widgetId}`, { params }),
}
