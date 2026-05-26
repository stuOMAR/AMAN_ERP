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
        <div ref={containerRef} style={{ position: 'relative', display: 'inline-block' }}>
            {/* Bell button */}
            <button
                className="topbar-icon-btn"
                onClick={() => setOpen((o) => !o)}
                title={t('notification_center.title')}
                aria-label={t('notification_center.title')}
                style={{ position: 'relative', background: 'none', border: 'none', cursor: 'pointer', padding: '6px' }}
            >
                <span style={{ fontSize: '1.25rem' }}>🔔</span>
                {unread > 0 && (
                    <span
                        style={{
                            position: 'absolute',
                            top: 2,
                            insetInlineEnd: 2,
                            minWidth: 16,
                            height: 16,
                            borderRadius: 8,
                            background: 'var(--danger, #e53e3e)',
                            color: '#fff',
                            fontSize: '0.65rem',
                            fontWeight: 700,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            padding: '0 3px',
                        }}
                    >
                        {unread > 99 ? '99+' : unread}
                    </span>
                )}
            </button>

            {/* Dropdown */}
            {open && (
                <div
                    className="notification-dropdown"
                    style={{
                        position: 'absolute',
                        insetInlineEnd: 0,
                        top: 'calc(100% + 6px)',
                        width: 340,
                        maxHeight: 460,
                        overflowY: 'auto',
                        background: 'var(--card-bg, #fff)',
                        border: '1px solid var(--border, #e2e8f0)',
                        borderRadius: 8,
                        boxShadow: '0 8px 24px rgba(0,0,0,0.12)',
                        zIndex: 9999,
                    }}
                >
                    {/* Header */}
                    <div
                        style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            padding: '10px 14px',
                            borderBottom: '1px solid var(--border, #e2e8f0)',
                            fontWeight: 600,
                        }}
                    >
                        <span>{t('notification_center.title')}</span>
                        {unread > 0 && (
                            <button
                                onClick={handleMarkAllRead}
                                style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '0.78rem', color: 'var(--primary, #3b82f6)' }}
                            >
                                {t('notification_center.mark_all_read')}
                            </button>
                        )}
                    </div>

                    {/* List */}
                    {loading && items.length === 0 ? (
                        <div style={{ padding: 20, textAlign: 'center', color: 'var(--muted, #718096)' }}>
                            {t('notification_center.loading')}
                        </div>
                    ) : items.length === 0 ? (
                        <div style={{ padding: 20, textAlign: 'center', color: 'var(--muted, #718096)' }}>
                            {t('notification_center.empty')}
                        </div>
                    ) : (
                        items.map((n) => (
                            <div
                                key={n.id}
                                onClick={() => handleClick(n)}
                                style={{
                                    display: 'flex',
                                    gap: 10,
                                    padding: '10px 14px',
                                    cursor: n.link ? 'pointer' : 'default',
                                    background: n.is_read ? 'transparent' : 'var(--primary-light, #ebf8ff)',
                                    borderBottom: '1px solid var(--border-subtle, #f0f0f0)',
                                    transition: 'background 0.15s',
                                }}
                            >
                                <div style={{ flex: 1, minWidth: 0 }}>
                                    <div style={{ fontWeight: n.is_read ? 400 : 600, fontSize: '0.875rem', marginBottom: 2 }}>
                                        {n.title}
                                    </div>
                                    {(n.body || n.message) && (
                                        <div style={{ fontSize: '0.78rem', color: 'var(--muted, #718096)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                            {n.body || n.message}
                                        </div>
                                    )}
                                    <div style={{ fontSize: '0.7rem', color: 'var(--muted, #718096)', marginTop: 2 }}>
                                        {n.created_at ? new Date(n.created_at).toLocaleString() : ''}
                                    </div>
                                </div>
                                {!n.is_read && (
                                    <div style={{ width: 8, height: 8, borderRadius: 4, background: 'var(--primary, #3b82f6)', flexShrink: 0, marginTop: 6 }} />
                                )}
                            </div>
                        ))
                    )}
                </div>
            )}
        </div>
    )
}
