import api from './apiClient'

const makeIdempotencyKey = (prefix) => (
    `${prefix}:${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`}`
)

export const dataImportAPI = {
    // Entity types available for import
    getEntityTypes: () => api.get('/data-import/entity-types'),

    // Download template for an entity type
    getTemplate: (entityType) => api.get(`/data-import/template/${entityType}`, { responseType: 'blob' }),

    // Preview import data before executing
    previewImport: (formData, entityType) => api.post('/data-import/preview', formData, {
        params: { entity_type: entityType },
        headers: { 'Content-Type': 'multipart/form-data' }
    }),

    // Execute import
    executeImport: (formData, entityType, idempotencyKey = makeIdempotencyKey(`data-import:${entityType}`)) => (
        api.post('/data-import/execute', formData, {
            params: { entity_type: entityType, skip_errors: false },
            headers: {
                'Content-Type': 'multipart/form-data',
                'Idempotency-Key': idempotencyKey
            }
        })
    ),

    // Import history
    getHistory: (params) => api.get('/data-import/history', { params }),

    // Export data
    exportData: (entityType, params) => api.get(`/data-import/export/${entityType}`, {
        params,
        responseType: 'blob'
    }),
}
