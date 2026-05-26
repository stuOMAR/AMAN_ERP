import api from './apiClient'

const idempotencyHeaders = () => ({
    headers: { 'Idempotency-Key': globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}` }
})

export const crmAPI = {
    // Opportunities
    listOpportunities: (params) => api.get('/crm/opportunities', { params }),
    getPipelineSummary: () => api.get('/crm/opportunities/pipeline'),
    getOpportunity: (id) => api.get(`/crm/opportunities/${id}`),
    createOpportunity: (data) => api.post('/crm/opportunities', data, idempotencyHeaders()),
    updateOpportunity: (id, data) => api.put(`/crm/opportunities/${id}`, data),
    deleteOpportunity: (id) => api.delete(`/crm/opportunities/${id}`),
    addActivity: (oppId, data) => api.post(`/crm/opportunities/${oppId}/activities`, data),
    convertToQuotation: (oppId) => api.post(`/crm/opportunities/${oppId}/convert-quotation`, null, idempotencyHeaders()),
    // Marketing Campaigns
    listCampaigns: (params) => api.get('/crm/campaigns', { params }),
    getCampaignSummary: (params) => api.get('/crm/campaigns/summary', { params }),
    getCampaign: (id) => api.get(`/crm/campaigns/${id}`),
    createCampaign: (data) => api.post('/crm/campaigns', data, idempotencyHeaders()),
    updateCampaign: (id, data) => api.put(`/crm/campaigns/${id}`, data),
    deleteCampaign: (id) => api.delete(`/crm/campaigns/${id}`),
    executeCampaign: (id) => api.post(`/crm/campaigns/${id}/execute`, null, idempotencyHeaders()),
    getCampaignRecipients: (id, params) => api.get(`/crm/campaigns/${id}/recipients`, { params }),
    getCampaignMetrics: (id) => api.get(`/crm/campaigns/${id}/metrics`),
    attributeLead: (campaignId, leadId) => api.post(`/crm/campaigns/${campaignId}/attribute-lead`, null, {
        params: { lead_id: leadId },
        ...idempotencyHeaders()
    }),
    // Knowledge Base
    listArticles: (params) => api.get('/crm/knowledge-base', { params }),
    getArticle: (id) => api.get(`/crm/knowledge-base/${id}`),
    createArticle: (data) => api.post('/crm/knowledge-base', data),
    updateArticle: (id, data) => api.put(`/crm/knowledge-base/${id}`, data),
    deleteArticle: (id) => api.delete(`/crm/knowledge-base/${id}`),
    // Support Tickets
    listTickets: (params) => api.get('/crm/tickets', { params }),
    getTicketStats: () => api.get('/crm/tickets/stats'),
    getTicket: (id) => api.get(`/crm/tickets/${id}`),
    createTicket: (data) => api.post('/crm/tickets', data),
    updateTicket: (id, data) => api.put(`/crm/tickets/${id}`, data),
    addComment: (ticketId, data) => api.post(`/crm/tickets/${ticketId}/comments`, data),
    // Lead Scoring
    listScoringRules: () => api.get('/crm/lead-scoring/rules'),
    createScoringRule: (data) => api.post('/crm/lead-scoring/rules', data),
    updateScoringRule: (id, data) => api.put(`/crm/lead-scoring/rules/${id}`, data),
    deleteScoringRule: (id) => api.delete(`/crm/lead-scoring/rules/${id}`),
    getLeadScores: (params) => api.get('/crm/lead-scoring/scores', { params }),
    calculateLeadScore: () => api.post('/crm/lead-scoring/calculate'),
    // Customer Segments
    listSegments: () => api.get('/crm/segments'),
    createSegment: (data) => api.post('/crm/segments', data),
    getSegmentMembers: (id) => api.get(`/crm/segments/${id}/customers`),
    updateSegment: (id, data) => api.put(`/crm/segments/${id}`, data),
    addCustomerToSegment: (segId, customerId) => api.post(`/crm/segments/${segId}/customers/${customerId}`),
    removeCustomerFromSegment: (segId, customerId) => api.delete(`/crm/segments/${segId}/customers/${customerId}`),
    deleteSegment: (id) => api.delete(`/crm/segments/${id}`),
    // Contacts
    listContacts: (params) => api.get('/crm/contacts', { params }),
    createContact: (data) => api.post('/crm/contacts', data),
    updateContact: (id, data) => api.put(`/crm/contacts/${id}`, data),
    deleteContact: (id) => api.delete(`/crm/contacts/${id}`),
    // Analytics
    getPipelineAnalytics: () => api.get('/crm/analytics/pipeline'),
    getConversionAnalytics: () => api.get('/crm/analytics/conversion'),
    getSalesForecast: () => api.get('/crm/analytics/forecast'),
    getCampaignROI: () => api.get('/crm/analytics/campaign-roi'),
    getVelocity: (params) => api.get('/crm/velocity', { params }),
    getFunnel: (params) => api.get('/crm/funnel', { params }),
    getCashflowForecast: (params) => api.get('/crm/cashflow-forecast', { params }),
    // Dashboard
    getDashboard: () => api.get('/crm/dashboard'),
}
