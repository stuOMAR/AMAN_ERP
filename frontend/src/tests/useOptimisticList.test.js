/**
 * Smoke tests for the T8.5 optimistic-list helper.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'

vi.mock('../services/apiClient', () => ({ default: { get: vi.fn() } }))

import api from '../services/apiClient'
import useOptimisticList from '../hooks/useOptimisticList'

beforeEach(() => api.get.mockReset())

describe('useOptimisticList', () => {
    it('optimisticAdd appends immediately and replaces with server result', async () => {
        api.get.mockResolvedValueOnce({ data: { items: [{ id: 1, name: 'A' }], total: 1 } })

        const { result } = renderHook(() => useOptimisticList({ fetcher: '/customers' }))
        await waitFor(() => expect(result.current.loading).toBe(false))
        expect(result.current.items).toHaveLength(1)

        const mutator = vi.fn().mockResolvedValue({ data: { id: 99, name: 'B' } })
        await act(async () => {
            await result.current.optimisticAdd({ name: 'B' }, mutator)
        })
        expect(mutator).toHaveBeenCalledWith({ name: 'B' })
        expect(result.current.items.map(i => i.id)).toEqual([1, 99])
        expect(result.current.items.find(i => i.id === 99)?._optimistic).toBe(false)
    })

    it('optimisticAdd rolls back the temp record on failure', async () => {
        api.get.mockResolvedValueOnce({ data: { items: [{ id: 1 }], total: 1 } })

        const { result } = renderHook(() => useOptimisticList({ fetcher: '/x' }))
        await waitFor(() => expect(result.current.loading).toBe(false))

        const mutator = vi.fn().mockRejectedValue(new Error('boom'))
        await act(async () => {
            await expect(result.current.optimisticAdd({ name: 'C' }, mutator)).rejects.toThrow('boom')
        })
        expect(result.current.items).toHaveLength(1)
        expect(result.current.items[0].id).toBe(1)
    })

    it('optimisticUpdate patches immediately and merges server reply', async () => {
        api.get.mockResolvedValueOnce({ data: { items: [{ id: 5, name: 'old' }], total: 1 } })

        const { result } = renderHook(() => useOptimisticList({ fetcher: '/x' }))
        await waitFor(() => expect(result.current.loading).toBe(false))

        const mutator = vi.fn().mockResolvedValue({ data: { id: 5, name: 'new', updated_at: 'T' } })
        await act(async () => {
            await result.current.optimisticUpdate(5, { name: 'new' }, mutator)
        })
        expect(result.current.items[0]).toMatchObject({ id: 5, name: 'new', updated_at: 'T' })
    })

    it('optimisticRemove drops & restores on error', async () => {
        api.get.mockResolvedValueOnce({ data: { items: [{ id: 7, name: 'g' }], total: 1 } })

        const { result } = renderHook(() => useOptimisticList({ fetcher: '/x' }))
        await waitFor(() => expect(result.current.loading).toBe(false))

        const mutator = vi.fn().mockRejectedValue(new Error('nope'))
        await act(async () => {
            await expect(result.current.optimisticRemove(7, mutator)).rejects.toThrow('nope')
        })
        // restored
        expect(result.current.items).toHaveLength(1)
        expect(result.current.items[0].id).toBe(7)
    })

    it('optimisticRemove on success leaves item gone', async () => {
        api.get.mockResolvedValueOnce({ data: { items: [{ id: 7 }, { id: 8 }], total: 2 } })

        const { result } = renderHook(() => useOptimisticList({ fetcher: '/x' }))
        await waitFor(() => expect(result.current.loading).toBe(false))

        const mutator = vi.fn().mockResolvedValue({ data: { ok: true } })
        await act(async () => {
            await result.current.optimisticRemove(7, mutator)
        })
        expect(result.current.items.map(i => i.id)).toEqual([8])
    })
})
