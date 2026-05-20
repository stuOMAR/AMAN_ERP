/**
 * T8.4 — `useExchangeRate(code)` hook.
 *
 * Returns the current exchange rate for `code` against the company's base
 * currency. Replaces the previously-hard-coded `exchange_rate: 1.0` in
 * invoice / journal entry / receipt / transfer / recurring-template forms.
 *
 * Caches per code in a module-level Map so concurrent forms reuse a single
 * network call.
 */
import { useEffect, useState } from 'react'
import { currenciesAPI } from '../services/accounting'

// Module-level cache: { code → Promise<rate> } — survives across mounts.
const _rateCache = new Map()

/** Fetch (or read from cache) the current rate for a currency code. */
export async function fetchCurrentRate(code) {
    const key = (code || '').toUpperCase().trim()
    if (!key) return '1'
    if (_rateCache.has(key)) return _rateCache.get(key)
    const promise = currenciesAPI
        .getCurrentRate(key)
        .then((res) => {
            const r = res?.data?.rate
            return r !== null && r !== undefined && r !== '' ? String(r) : '1'
        })
        .catch(() => '1')
    _rateCache.set(key, promise)
    return promise
}

export function calculateCrossExchangeRate(sourceRate, targetRate) {
    return null
}

export async function fetchFxPreview(sourceCode, targetCode, amount = '1', branchId = null) {
    const sourceKey = (sourceCode || '').toUpperCase().trim()
    const targetKey = (targetCode || '').toUpperCase().trim()
    if (!sourceKey || !targetKey) return null
    const res = await currenciesAPI.previewFx({
        source_currency: sourceKey,
        target_currency: targetKey,
        amount: String(amount || '0'),
        branch_id: branchId,
    })
    return res?.data || null
}

export async function fetchCrossExchangeRate(sourceCode, targetCode) {
    const sourceKey = (sourceCode || '').toUpperCase().trim()
    const targetKey = (targetCode || '').toUpperCase().trim()
    if (!sourceKey || !targetKey || sourceKey === targetKey) return '1'

    const preview = await fetchFxPreview(sourceKey, targetKey, '1')
    return preview?.cross_rate || null
}

/** Reset the cache — call after a manager edits exchange rates in settings. */
export function clearExchangeRateCache(code) {
    if (code) _rateCache.delete(String(code).toUpperCase())
    else _rateCache.clear()
}

/**
 * React hook. While loading, `rate` defaults to 1.0 so existing forms keep
 * working (degrades gracefully when the backend endpoint isn't available).
 */
export default function useExchangeRate(code) {
    const [rate, setRate] = useState('1')
    const [loading, setLoading] = useState(false)

    useEffect(() => {
        if (!code) return
        let cancelled = false
        setLoading(true)
        fetchCurrentRate(code).then((r) => {
            if (!cancelled) {
                setRate(r)
                setLoading(false)
            }
        })
        return () => { cancelled = true }
    }, [code])

    return { rate, loading }
}
