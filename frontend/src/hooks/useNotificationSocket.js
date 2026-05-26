import { useEffect, useRef, useCallback, useState } from 'react'
import { getToken } from '../utils/tokenStore'
import api from '../services/apiClient'

/**
 * useNotificationSocket — React hook for real-time WebSocket notifications
 * 
 * Connects to ws://host/api/notifications/ws?ticket=TICKET and receives
 * push notifications in real-time. Falls back to polling if WS fails.
 * 
 * @param {Function} onNotification - callback({id, title, message, type, link, is_read, created_at})
 * @returns {{ connected: boolean }}
 */
export function useNotificationSocket(onNotification) {
    const wsRef = useRef(null)
    const reconnectTimer = useRef(null)
    const [connected, setConnected] = useState(false)
    const attempt = useRef(0)

    const connect = useCallback(async (abortSignal) => {
        // SEC-T2.8: read access token from in-memory store (not localStorage).
        const token = getToken()
        if (!token) return

        // Basic JWT expiry pre-check — avoid opening a WS with an expired token
        try {
            const payloadB64 = token.split('.')[1]
            if (payloadB64) {
                const payload = JSON.parse(atob(payloadB64))
                const now = Math.floor(Date.now() / 1000)
                if (payload.exp && payload.exp < now) {
                    // Token is expired — wait and retry (token refresh may be in progress)
                    const delay = Math.min(1000 * Math.pow(2, attempt.current), 30000)
                    attempt.current++
                    reconnectTimer.current = setTimeout(() => connect(abortSignal), delay)
                    return
                }
            }
        } catch {
            // If we can't parse, just proceed — the backend will validate
        }

        // Fetch short-lived ws-ticket to hide JWT from query string
        let wsTicket = null
        try {
            const response = await api.post('/notifications/ws-ticket')
            wsTicket = response.data?.ticket
        } catch (err) {
            console.error("Failed to fetch WS ticket:", err)
            // Fallback to token if ticket fetch fails
        }

        if (abortSignal?.aborted) return

        // Determine WS URL — use same host so Vite proxy handles it in dev
        const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
        const host = window.location.host
        const queryParam = wsTicket ? `ticket=${encodeURIComponent(wsTicket)}` : `token=${encodeURIComponent(token)}`
        const url = `${proto}://${host}/api/notifications/ws?${queryParam}`

        // Defer creation so React StrictMode's instant cleanup sets abortSignal
        // before we ever open a socket — avoids "closed before established" warning.
        const timerId = setTimeout(() => {
            if (abortSignal?.aborted) return

            try {
                const ws = new WebSocket(url)
                wsRef.current = ws

                ws.onopen = () => {
                    if (abortSignal?.aborted) { ws.close(); return }
                    setConnected(true)
                    attempt.current = 0
                }

                ws.onmessage = (event) => {
                    try {
                        const msg = JSON.parse(event.data)
                        if (msg.event === 'new_notification' && onNotification) {
                            onNotification(msg.data)
                        }
                    } catch {
                        // Ignore non-JSON messages (pong, etc.)
                    }
                }

                ws.onclose = (e) => {
                    setConnected(false)
                    wsRef.current = null
                    // Don't reconnect if cleanup already ran (StrictMode)
                    if (abortSignal?.aborted) return
                    // Auth failure (token invalid/expired) — stop reconnecting
                    // code 4001 = explicit auth failure from backend
                    // code 1006 = abnormal close (often happens with expired tokens)
                    if (e.code === 4001) return
                    // Exponential backoff: 1s, 2s, 4s, 8s, max 30s
                    const delay = Math.min(1000 * Math.pow(2, attempt.current), 30000)
                    attempt.current++
                    reconnectTimer.current = setTimeout(() => connect(abortSignal), delay)
                }

                ws.onerror = () => {
                    ws.close()
                }

                // Send ping every 25s to keep connection alive
                const pingInterval = setInterval(() => {
                    if (ws.readyState === WebSocket.OPEN) {
                        ws.send('ping')
                    }
                }, 25000)

                ws._pingInterval = pingInterval
            } catch {
                // WebSocket constructor can throw in some environments
                setConnected(false)
            }
        }, 50) // end setTimeout

        // Store timer id so cleanup can cancel it
        wsRef._connectTimer = timerId
    }, [onNotification])

    useEffect(() => {
        // Use an abort controller so React StrictMode's double-invoke cleanup
        // can signal the socket not to reconnect on its onclose event.
        const controller = new AbortController()
        connect(controller.signal)

        // Listen for token refresh events — reconnect with fresh token
        const handleTokenRefresh = () => {
            // Close existing WS and reconnect with new token
            clearTimeout(reconnectTimer.current)
            clearTimeout(wsRef._connectTimer)
            if (wsRef.current) {
                clearInterval(wsRef.current._pingInterval)
                // Only close if already open — closing during CONNECTING
                // triggers "WebSocket is closed before connection is established".
                const ws = wsRef.current
                if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CLOSING) {
                    ws.close()
                } else if (ws.readyState === WebSocket.CONNECTING) {
                    // Wait for the connection to establish, then close it
                    ws.onopen = () => ws.close()
                    ws.onerror = () => {} // suppress — we're discarding this socket
                }
                wsRef.current = null
            }
            attempt.current = 0
            // Small delay lets the old socket fully tear down before reconnecting
            reconnectTimer.current = setTimeout(() => connect(controller.signal), 300)
        }
        window.addEventListener('token_refreshed', handleTokenRefresh)

        return () => {
            controller.abort()
            clearTimeout(reconnectTimer.current)
            clearTimeout(wsRef._connectTimer)
            if (wsRef.current) {
                clearInterval(wsRef.current._pingInterval)
                wsRef.current.close()
                wsRef.current = null
            }
            window.removeEventListener('token_refreshed', handleTokenRefresh)
        }
    }, [connect])

    return { connected }
}
