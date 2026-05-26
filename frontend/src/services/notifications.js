import api from './apiClient'

const makeIdempotencyKey = (prefix) => (
    `${prefix}:${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`}`
)

export const notificationsAPI = {
    getAll: (params) => api.get('/notifications', { params, skipAbort: true }),
    getUnreadCount: () => api.get('/notifications/unread-count', { skipAbort: true }),
    markRead: (id) => api.put(`/notifications/${id}/read`),
    markAllRead: () => api.post('/notifications/mark-all-read'),

    // Send notification
    send: (data, idempotencyKey = makeIdempotencyKey('notification-send')) => (
        api.post('/notifications/send', data, {
            headers: { 'Idempotency-Key': idempotencyKey }
        })
    ),

    // Settings
    getSettings: () => api.get('/notifications/settings'),
    updateSettings: (data) => api.put('/notifications/settings', data),

    // Test
    testEmail: (data) => api.post('/notifications/test-email', data),

    // Notification Preferences
    getPreferences: () => api.get('/notifications/preferences'),
    updatePreference: (data) => api.put('/notifications/preferences', data),

    // Queue Monitor
    getQueue: (params) => api.get('/notifications/queue', { params }),
    retryQueue: (id, idempotencyKey = makeIdempotencyKey('notification-retry')) => (
        api.post(`/notifications/queue/${id}/retry`, null, {
            headers: { 'Idempotency-Key': idempotencyKey }
        })
    ),
    requeueDlq: (id, idempotencyKey = makeIdempotencyKey('notification-dlq-requeue')) => (
        api.post(`/notifications/dlq/${id}/requeue`, null, {
            headers: { 'Idempotency-Key': idempotencyKey }
        })
    ),

    // Email templates admin
    getEmailTemplates: (params) => api.get('/notifications/templates', { params }),
    createEmailTemplate: (data) => api.post('/notifications/templates', data),
    updateEmailTemplate: (id, data) => api.put(`/notifications/templates/${id}`, data),
    deleteEmailTemplate: (id) => api.delete(`/notifications/templates/${id}`),
}
