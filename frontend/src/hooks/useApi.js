/**
 * T8.1 — Unified `useApi` hook.
 *
 * Replaces the very common pattern:
 *
 *   const [data, setData]     = useState(null)
 *   const [loading, setLoading] = useState(false)
 *   const [error, setError]   = useState(null)
 *   useEffect(() => {
 *     setLoading(true)
 *     api.get(...).then(r => setData(r.data)).catch(setError)
 *                  .finally(() => setLoading(false))
 *   }, [...deps])
 *
 * with a single hook that:
 *   • cancels in-flight requests on unmount / dep-change (AbortController),
 *   • exposes `{ data, error, loading, refetch, mutate }`,
 *   • supports lazy mode (`immediate: false`) for buttons / save handlers,
 *   • has a thin `useApiList` variant for paginated tables,
 *   • integrates `?no_cache=1` invalidation hints from the backend cache layer
 *     (utils/cache.py) so freshly-mutated lists refetch correctly.
 *
 * DoD: ≥ 50% of pages migrate to this hook. New pages must use it.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import api from '../services/apiClient'

/**
 * @param {string|Function} fetcher
 *   - string  → treated as a GET URL and called via `api.get(url, { params, signal })`.
 *   - function → called as `fetcher({ params, signal })` — must return an Axios-like promise.
 * @param {object} options
 *   @param {object}   options.params      query/body params (deps for refetch).
 *   @param {boolean}  options.immediate   fetch on mount (default `true`). Pass `false` for lazy save buttons.
 *   @param {*}        options.initialData seed value (default `null`).
 *   @param {Function} options.onSuccess   side-effect callback on success.
 *   @param {Function} options.onError     side-effect callback on error.
 *   @param {boolean}  options.noCache     append `?no_cache=1` to bypass backend `@cached`.
 *   @param {Array}    options.deps        extra deps that should trigger refetch (besides params).
 * @returns {{
 *   data: any, error: Error|null, loading: boolean,
 *   refetch: (overrideParams?) => Promise<any>,
 *   mutate:  (newData|(prev)=>newData) => void
 * }}
 */
export default function useApi(fetcher, options = {}) {
    const {
        params,
        immediate = true,
        initialData = null,
        onSuccess,
        onError,
        noCache = false,
        deps = [],
    } = options

    const [data, setData] = useState(initialData)
    const [error, setError] = useState(null)
    const [loading, setLoading] = useState(immediate)

    // Always read latest callbacks without forcing refetch when they change.
    const onSuccessRef = useRef(onSuccess)
    const onErrorRef = useRef(onError)
    onSuccessRef.current = onSuccess
    onErrorRef.current = onError

    // Track the latest in-flight controller so a stale response can't overwrite a newer one.
    const controllerRef = useRef(null)
    const mountedRef = useRef(true)

    useEffect(() => {
        mountedRef.current = true
        return () => {
            mountedRef.current = false
            controllerRef.current?.abort()
        }
    }, [])

    const run = useCallback(
        async (overrideParams) => {
            // Cancel any previous in-flight request from this hook before issuing a new one.
            controllerRef.current?.abort()
            const ctrl = new AbortController()
            controllerRef.current = ctrl

            setLoading(true)
            setError(null)
            const callParams = overrideParams ?? params
            const finalParams = noCache ? { ...(callParams || {}), no_cache: 1 } : callParams

            try {
                let res
                if (typeof fetcher === 'string') {
                    res = await api.get(fetcher, { params: finalParams, signal: ctrl.signal })
                } else if (typeof fetcher === 'function') {
                    res = await fetcher({ params: finalParams, signal: ctrl.signal })
                } else {
                    throw new TypeError('useApi: fetcher must be a URL string or a function.')
                }
                if (!mountedRef.current || ctrl.signal.aborted) return res?.data
                const payload = res?.data
                setData(payload)
                onSuccessRef.current?.(payload)
                return payload
            } catch (e) {
                // Silently swallow aborts (component unmount / dep-change).
                if (e?.code === 'ERR_CANCELED' || e?.name === 'CanceledError' || e?.name === 'AbortError') {
                    return undefined
                }
                if (!mountedRef.current) return undefined
                setError(e)
                onErrorRef.current?.(e)
                throw e
            } finally {
                if (mountedRef.current && !ctrl.signal.aborted) setLoading(false)
            }
        },
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [fetcher, JSON.stringify(params), noCache, ...deps]
    )

    useEffect(() => {
        if (!immediate) return
        run().catch(() => { /* swallowed — surfaced via `error` */ })
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [run, immediate])

    /** Local state mutator — useful for optimistic UI updates. */
    const mutate = useCallback((updater) => {
        setData((prev) => (typeof updater === 'function' ? updater(prev) : updater))
    }, [])

    return { data, error, loading, refetch: run, mutate }
}

/**
 * Small convenience wrapper around `useApi` for paginated list endpoints.
 *
 * Returns `{ items, total, ...rest }` so consumers don't have to dig through
 * the typical `{ items, total, page, pageSize }` envelope.
 */
export function useApiList(fetcher, options = {}) {
    const result = useApi(fetcher, options)
    const items = Array.isArray(result.data) ? result.data : (result.data?.items || result.data?.results || [])
    const total = Array.isArray(result.data) ? items.length : (result.data?.total ?? items.length)
    return { ...result, items, total }
}

/**
 * Lazy mutation helper: returns a single async `call` function plus loading/error state.
 *
 * Example:
 *   const { call: createInvoice, loading } = useApiMutation((payload) => api.post('/sales/invoices', payload))
 *   <button onClick={() => createInvoice(form)}>Save</button>
 */
export function useApiMutation(mutator) {
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(null)
    const mountedRef = useRef(true)
    useEffect(() => () => { mountedRef.current = false }, [])

    const call = useCallback(async (...args) => {
        setLoading(true)
        setError(null)
        try {
            const res = await mutator(...args)
            return res?.data ?? res
        } catch (e) {
            if (mountedRef.current) setError(e)
            throw e
        } finally {
            if (mountedRef.current) setLoading(false)
        }
    }, [mutator])

    return { call, loading, error }
}
