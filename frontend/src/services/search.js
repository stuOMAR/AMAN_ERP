/**
 * T7.2 frontend bridge — unified search service.
 *
 * Backend route: `GET /api/search?q=...&entities=...&limit=...`
 * (see backend/routers/search.py).
 */
import api from './apiClient'

export const searchAPI = {
    /**
     * Search the backend across one or more data entities.
     *
     * @param {string} q                       free-text query (Arabic / English).
     * @param {object} options
     * @param {string[]} options.entities      subset of registry entity_code values.
     *   Omitted → all entities allowed by backend permissions.
     * @param {number} options.limit           per-entity limit (capped at 100 server-side).
     * @param {AbortSignal} options.signal     optional Axios cancellation signal.
     * @returns {Promise<{ query: string, results: Array, total_count: number, latency_ms: number }>}
     */
    search: (q, { entities, limit = 20, signal } = {}) =>
        api.get('/search', {
            params: {
                q,
                entities: Array.isArray(entities) ? entities.join(',') : entities,
                limit,
            },
            signal,
            // Backend silently returns [] if pg_trgm/tsvector haven't been
            // applied yet; no need for the global toast on transient failures.
            skipGlobalToast: true,
        }),
}

export default searchAPI
