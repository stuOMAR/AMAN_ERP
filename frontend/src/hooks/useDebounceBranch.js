import { useEffect, useRef, useCallback } from 'react'

/**
 * useDebounceBranch - Debounces branch change callbacks
 * 
 * @param {Function} callback - Function to call when branch changes
 * @param {number} delay - Debounce delay in ms (default: 300)
 * @returns {Function} - Debounced callback
 */
export function useDebounceBranch(callback, delay = 300) {
    const timeoutRef = useRef(null)
    const callbackRef = useRef(callback)

    useEffect(() => {
        callbackRef.current = callback
    }, [callback])

    const debouncedCallback = useCallback((...args) => {
        if (timeoutRef.current) {
            clearTimeout(timeoutRef.current)
        }
        timeoutRef.current = setTimeout(() => {
            callbackRef.current(...args)
        }, delay)
    }, [delay])

    useEffect(() => {
        return () => {
            if (timeoutRef.current) {
                clearTimeout(timeoutRef.current)
            }
        }
    }, [])

    return debouncedCallback
}

export default useDebounceBranch
