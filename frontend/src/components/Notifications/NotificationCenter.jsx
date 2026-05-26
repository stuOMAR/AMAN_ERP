/**
 * NotificationCenter — Bell icon with unread badge, dropdown list, and live WS updates.
 *
 * Usage (e.g. in Topbar):
 *   import NotificationCenter from '../components/Notifications/NotificationCenter'
 *   <NotificationCenter />
 */
import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { notificationsAPI } from '../../utils/api'
import { useNotificationSocket } from '../../hooks/useNotificationSocket'
import './NotificationCenter.css'

export default function NotificationCenter() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const [open, setOpen] = useState(false)
    const [items, setItems] = useState([])
    const [unread, setUnread] = useState(0)
    const [loading, setLoading] = useState(false)
    const containerRef = useRef(null)

    /* ------------------------------------------------------------------ */
    /*  WebSocket — live updates                                            */
    /* ------------------------------------------------------------------ */
    const handleWsNotification = useCallback((notif) => {
        setItems((prev) => [notif, ...prev].slice(0, 50))
        setUnread((c) => c + 1)
        // Toast (native browser Notification API — graceful degradation)
        if ('Notification' in window && Notification.permission === 'granted') {
            new Notification(notif.title || t('notification_center.new_notification'), {
                body: notif.body || notif.message || '',
            })
        }
    }, [t])

    const { connected: wsConnected } = useNotificationSocket(handleWsNotification)

    /* ------------------------------------------------------------------ */
    /*  Initial fetch + optional polling fallback                          */
    /* ------------------------------------------------------------------ */
    const fetchNotifications = useCallback(async () => {
        setLoading(true)
        try {
            const [listRes, countRes] = await Promise.all([
                notificationsAPI.getAll({ limit: 50 }),
                notificationsAPI.getUnreadCount(),
            ])
            const payload = listRes.data
            setItems(payload?.items ?? payload ?? [])
            setUnread(countRes.data?.unread_count ?? countRes.data?.count ?? 0)
        } catch {
            /* silently ignore */
        } finally {
            setLoading(false)
        }
    }, [])

    useEffect(() => {
        fetchNotifications()
        if (!wsConnected) {
            const id = setInterval(fetchNotifications, 60_000)
            return () => clearInterval(id)
        }
    }, [fetchNotifications, wsConnected])

    /* ------------------------------------------------------------------ */
    /*  Outside-click to close                                             */
    /* ------------------------------------------------------------------ */
    useEffect(() => {
        const handler = (e) => {
            if (containerRef.current && !containerRef.current.contains(e.target)) {
                setOpen(false)
            }
        }
        document.addEventListener('mousedown', handler)
        return () => document.removeEventListener('mousedown', handler)
    }, [])

    /* ------------------------------------------------------------------ */
    /*  Actions                                                             */
    /* ------------------------------------------------------------------ */
    const handleClick = async (notif) => {
        try {
            if (!notif.is_read) {
                await notificationsAPI.markRead(notif.id)
                setUnread((c) => Math.max(0, c - 1))
                setItems((prev) => prev.map((n) => (n.id === notif.id ? { ...n, is_read: true } : n)))
            }
            if (notif.link) {
                navigate(notif.link)
                setOpen(false)
            }
        } catch { /* ignore */ }
    }

    const handleMarkAllRead = async () => {
        try {
            await notificationsAPI.markAllRead()
            setUnread(0)
            setItems((prev) => prev.map((n) => ({ ...n, is_read: true })))
        } catch { /* ignore */ }
    }

    /* ------------------------------------------------------------------ */
    /*  Render                                                              */
    /* ------------------------------------------------------------------ */
    return (
        <div ref={containerRef} className="nc-container">
            {/* Bell button */}
            <button
                className="topbar-icon-btn nc-bell-btn"
                onClick={() => setOpen((o) => !o)}
                title={t('notification_center.title')}
                aria-label={t('notification_center.title')}
            >
                <span className="nc-bell-icon">🔔</span>
                {unread > 0 && (
                    <span className="nc-badge">
                        {unread > 99 ? '99+' : unread}
                    </span>
                )}
            </button>

            {/* Dropdown */}
            {open && (
                <div className="nc-dropdown">
                    {/* Header */}
                    <div className="nc-header">
                        <span>{t('notification_center.title')}</span>
                        {unread > 0 && (
                            <button
                                onClick={handleMarkAllRead}
                                className="nc-mark-all-btn"
                            >
                                {t('notification_center.mark_all_read')}
                            </button>
                        )}
                    </div>

                    {/* List */}
                    {loading && items.length === 0 ? (
                        <div className="nc-empty">
                            {t('notification_center.loading')}
                        </div>
                    ) : items.length === 0 ? (
                        <div className="nc-empty">
                            {t('notification_center.empty')}
                        </div>
                    ) : (
                        items.map((n) => (
                            <div
                                key={n.id}
                                onClick={() => handleClick(n)}
                                className={`nc-item ${n.is_read ? 'nc-item-read' : 'nc-item-unread'} ${n.link ? 'nc-item-clickable' : ''}`}
                            >
                                <div className="nc-item-content">
                                    <div className={`nc-item-title ${n.is_read ? '' : 'nc-item-title-bold'}`}>
                                        {n.title}
                                    </div>
                                    {(n.body || n.message) && (
                                        <div className="nc-item-body">
                                            {n.body || n.message}
                                        </div>
                                    )}
                                    <div className="nc-item-time">
                                        {n.created_at ? new Date(n.created_at).toLocaleString() : ''}
                                    </div>
                                </div>
                                {!n.is_read && (
                                    <div className="nc-unread-dot" />
                                )}
                            </div>
                        ))
                    )}
                </div>
            )}
        </div>
    )
}
