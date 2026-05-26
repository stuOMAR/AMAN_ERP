import api from './apiClient'
import { cleanParams } from './apiClient'

const makeIdempotencyKey = (prefix) => (
    `${prefix}:${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`}`
)

export const integrationQueuesAPI = {
    listPaymentQueue: (params) => api.get('/integrations/payment-retry-queue', { params: cleanParams(params) }),
    listSmsQueue: (params) => api.get('/integrations/sms-retry-queue', { params: cleanParams(params) }),
    listDLQ: (params) => api.get('/integrations/dlq', { params: cleanParams(params) }),
    getDLQItem: (id) => api.get(`/integrations/dlq/${id}`),
    replayDLQ: (id, idempotencyKey = makeIdempotencyKey(`integration-dlq-replay:${id}`)) => (
        api.post(`/integrations/dlq/${id}/replay`, null, {
            headers: { 'Idempotency-Key': idempotencyKey }
        })
    ),
    archiveDLQ: (id) => api.post(`/integrations/dlq/${id}/archive`),
}
