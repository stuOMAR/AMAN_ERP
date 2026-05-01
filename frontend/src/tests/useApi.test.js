/**
 * Smoke tests for the T8.1 useApi hook.
 *
 * Covers:
 *   • initial fetch fires on mount when `immediate: true`,
 *   • lazy mode (`immediate: false`) does NOT fetch on mount,
 *   • `noCache: true` injects `?no_cache=1`,
 *   • errors surface via the returned `error` state,
 *   • `mutate(updater)` updates local state without a network call.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'

// Mock the shared Axios client BEFORE importing the hook.
vi.mock('../services/apiClient', () => ({
    default: { get: vi.fn() },
}))

import api from '../services/apiClient'
import useApi, { useApiMutation } from '../hooks/useApi'

beforeEach(() => {
    api.get.mockReset()
})

describe('useApi', () => {
    it('fires on mount and exposes data', async () => {
        api.get.mockResolvedValueOnce({ data: { ok: true, items: [1, 2, 3] } })

        const { result } = renderHook(() => useApi('/dummy'))

        await waitFor(() => expect(result.current.loading).toBe(false))
        expect(api.get).toHaveBeenCalledTimes(1)
        expect(result.current.data).toEqual({ ok: true, items: [1, 2, 3] })
        expect(result.current.error).toBeNull()
    })

    it('honors immediate=false (lazy mode)', () => {
        api.get.mockResolvedValueOnce({ data: 'lazy' })

        const { result } = renderHook(() => useApi('/lazy', { immediate: false }))
        expect(api.get).not.toHaveBeenCalled()
        expect(result.current.loading).toBe(false)
        expect(typeof result.current.refetch).toBe('function')
    })

    it('appends no_cache=1 when noCache option is true', async () => {
        api.get.mockResolvedValueOnce({ data: 'fresh' })

        renderHook(() => useApi('/x', { params: { a: 1 }, noCache: true }))

        await waitFor(() => expect(api.get).toHaveBeenCalled())
        const callArgs = api.get.mock.calls[0]
        expect(callArgs[0]).toBe('/x')
        expect(callArgs[1].params).toEqual({ a: 1, no_cache: 1 })
    })

    it('captures errors via the error state', async () => {
        api.get.mockRejectedValueOnce(new Error('boom'))

        const { result } = renderHook(() => useApi('/explode'))

        await waitFor(() => expect(result.current.loading).toBe(false))
        expect(result.current.error).toBeInstanceOf(Error)
        expect(result.current.error.message).toBe('boom')
        expect(result.current.data).toBeNull()
    })

    it('mutate(updater) updates local state without a fetch', async () => {
        api.get.mockResolvedValueOnce({ data: { count: 1 } })

        const { result } = renderHook(() => useApi('/c'))
        await waitFor(() => expect(result.current.loading).toBe(false))

        act(() => result.current.mutate((prev) => ({ count: (prev?.count || 0) + 10 })))
        expect(result.current.data).toEqual({ count: 11 })
        // mutate must NOT trigger another GET.
        expect(api.get).toHaveBeenCalledTimes(1)
    })
})

describe('useApiMutation', () => {
    it('runs the mutator only when call() is invoked', async () => {
        const mutator = vi.fn().mockResolvedValue({ data: { id: 7 } })
        const { result } = renderHook(() => useApiMutation(mutator))

        expect(mutator).not.toHaveBeenCalled()
        let returned
        await act(async () => {
            returned = await result.current.call({ name: 'x' })
        })
        expect(mutator).toHaveBeenCalledWith({ name: 'x' })
        expect(returned).toEqual({ id: 7 })
        expect(result.current.error).toBeNull()
    })

    it('surfaces errors from the mutator', async () => {
        const mutator = vi.fn().mockRejectedValue(new Error('nope'))
        const { result } = renderHook(() => useApiMutation(mutator))

        await act(async () => {
            await expect(result.current.call()).rejects.toThrow('nope')
        })
        expect(result.current.error?.message).toBe('nope')
    })
})
