/**
 * T9.6 — Frontend test coverage for Phase 7/8 additions.
 *
 * Targets four under-tested service modules so each gets at least one
 * exercised unit:
 *   - services/search.js              (unified search)
 *   - services/parties.js             (getDuplicatesByPhone)
 *   - services/hr.js                  (getOvertimeRates)
 *   - hooks/useExchangeRate.js        (fetchCurrentRate cache + degrade)
 *
 * We mock `services/apiClient` (and the imported `accounting` module for the
 * exchange-rate hook) so no network round-trips happen.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

// ---- Mocks ---------------------------------------------------------------

vi.mock('../services/apiClient', () => {
    const get = vi.fn()
    const post = vi.fn()
    const put = vi.fn()
    const del = vi.fn()
    return { default: { get, post, put, delete: del } }
})

vi.mock('../services/accounting', () => ({
    currenciesAPI: {
        getCurrentRate: vi.fn(),
        previewFx: vi.fn(),
    },
}))

// Imports MUST come after vi.mock calls so the mocks are active.
import api from '../services/apiClient'
import { searchAPI } from '../services/search'
import { partiesAPI } from '../services/parties'
import { hrAdvancedAPI } from '../services/hr'
import {
    fetchCurrentRate,
    fetchCrossExchangeRate,
    calculateCrossExchangeRate,
    clearExchangeRateCache,
} from '../hooks/useExchangeRate'
import { currenciesAPI } from '../services/accounting'

// ---- Tests ---------------------------------------------------------------

describe('services/search — searchAPI.search', () => {
    beforeEach(() => {
        api.get.mockReset()
    })

    it('joins entities array into a CSV param and forwards limit + signal', async () => {
        api.get.mockResolvedValueOnce({ data: { items: [], total: 0 } })
        const ctrl = new AbortController()

        await searchAPI.search('شركة', {
            entities: ['parties', 'products'],
            limit: 5,
            signal: ctrl.signal,
        })

        expect(api.get).toHaveBeenCalledTimes(1)
        const [url, opts] = api.get.mock.calls[0]
        expect(url).toBe('/search')
        expect(opts.params).toEqual({
            q: 'شركة',
            entities: 'parties,products',
            limit: 5,
        })
        expect(opts.signal).toBe(ctrl.signal)
        // Transient failures must not pop the global toast.
        expect(opts.skipGlobalToast).toBe(true)
    })

    it('omits entities param entirely when caller passes none', async () => {
        api.get.mockResolvedValueOnce({ data: { items: [] } })
        await searchAPI.search('test', { limit: 20 })
        const [, opts] = api.get.mock.calls[0]
        // searchAPI passes `entities: undefined` when not provided.
        expect(opts.params.entities).toBeUndefined()
        expect(opts.params.limit).toBe(20)
    })
})

describe('services/parties — getDuplicatesByPhone', () => {
    beforeEach(() => api.get.mockReset())

    it('hits /parties/duplicates-by-phone with phone + default limit', async () => {
        api.get.mockResolvedValueOnce({ data: [] })
        await partiesAPI.getDuplicatesByPhone('+966500000000')

        expect(api.get).toHaveBeenCalledWith(
            '/parties/duplicates-by-phone',
            expect.objectContaining({
                params: { phone: '+966500000000', limit: 50 },
                skipGlobalToast: true,
            }),
        )
    })

    it('honours an explicit limit override', async () => {
        api.get.mockResolvedValueOnce({ data: [] })
        await partiesAPI.getDuplicatesByPhone('0500', 5)
        const [, opts] = api.get.mock.calls[0]
        expect(opts.params.limit).toBe(5)
    })
})

describe('services/hr — hrAdvancedAPI.getOvertimeRates', () => {
    beforeEach(() => api.get.mockReset())

    it('GETs /hr-advanced/overtime/rates and suppresses global toast', async () => {
        api.get.mockResolvedValueOnce({ data: { weekday: 1.5, holiday: 2.0 } })
        const res = await hrAdvancedAPI.getOvertimeRates()

        expect(api.get).toHaveBeenCalledWith(
            '/hr-advanced/overtime/rates',
            expect.objectContaining({ skipGlobalToast: true }),
        )
        expect(res.data.weekday).toBe(1.5)
    })
})

describe('hooks/useExchangeRate — fetchCurrentRate', () => {
    beforeEach(() => {
        clearExchangeRateCache()
        currenciesAPI.getCurrentRate.mockReset()
    })

    it('returns null immediately for empty/falsy code (no network)', async () => {
        const r = await fetchCurrentRate('')
        expect(r).toBeNull()
        expect(currenciesAPI.getCurrentRate).not.toHaveBeenCalled()
    })

    it('caches per code — second call does NOT hit the API again', async () => {
        currenciesAPI.getCurrentRate.mockResolvedValueOnce({ data: { rate: 3.75 } })

        const a = await fetchCurrentRate('USD')
        const b = await fetchCurrentRate('usd') // case-insensitive
        expect(a).toBe('3.75')
        expect(b).toBe('3.75')
        expect(currenciesAPI.getCurrentRate).toHaveBeenCalledTimes(1)
    })

    it('returns null when the API rejects', async () => {
        currenciesAPI.getCurrentRate.mockRejectedValueOnce(new Error('boom'))
        const r = await fetchCurrentRate('EUR')
        expect(r).toBeNull()
    })

    it('returns null when API returns a non-positive rate', async () => {
        currenciesAPI.getCurrentRate.mockResolvedValueOnce({ data: { rate: 0 } })
        const r = await fetchCurrentRate('XYZ')
        expect(r).toBeNull()
    })

    it('calculates source-to-target cross rates from base-currency rates', () => {
        expect(calculateCrossExchangeRate('1.021', '1')).toBe('1.02100000')
        expect(calculateCrossExchangeRate('3.75', '1.021')).toBe('3.67286974')
    })

    it('fetches source and target rates before calculating a cross rate', async () => {
        currenciesAPI.previewFx.mockResolvedValueOnce({ data: { cross_rate: 1.021 } })

        const r = await fetchCrossExchangeRate('AED', 'SAR')
        expect(r).toBe(1.021)
        expect(currenciesAPI.previewFx).toHaveBeenCalledTimes(1)
    })
})
