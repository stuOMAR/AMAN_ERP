import api from './apiClient'

const makeIdempotencyKey = (prefix) => (
    `${prefix}:${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`}`
)

export const dmsAPI = {
    getQuotas: () => api.get('/dms/quotas'),
    listQuarantine: (params) => api.get('/dms/quarantine', { params }),
    getScanStats: () => api.get('/dms/scan-stats'),
    recalculateStorage: (idempotencyKey = makeIdempotencyKey('dms-storage-recalculate')) => (
        api.post('/dms/storage/recalculate', null, {
            headers: { 'Idempotency-Key': idempotencyKey }
        })
    ),
    releaseQuarantined: (documentId, idempotencyKey = makeIdempotencyKey(`dms-quarantine-release:${documentId}`)) => (
        api.post(`/dms/quarantine/${documentId}/release`, null, {
            headers: { 'Idempotency-Key': idempotencyKey }
        })
    ),
}
