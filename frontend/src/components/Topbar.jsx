import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { getUser, getCompanyId, logout, hasPermission } from '../utils/auth'
import { notificationsAPI } from '../utils/api' // New generic API
import { useTranslation } from 'react-i18next'
import { useBranch } from '../context/BranchContext'
import { useTheme } from '../context/ThemeContext'
import { useNotificationSocket } from '../hooks/useNotificationSocket'
import GlobalSearch from './GlobalSearch'
import './GlobalSearch.css'

function Topbar({ sidebarOpen = false, onToggleSidebar }) {
    const { t, i18n } = useTranslation()
    const { darkMode, toggleDarkMode } = useTheme()
    const user = getUser()
    const companyId = getCompanyId()
    const navigate = useNavigate()
    const [showMenu, setShowMenu] = useState(false)
    const [showNotifications, setShowNotifications] = useState(false)
    const [notifications, setNotifications] = useState([])
    const [unreadCount, setUnreadCount] = useState(0)
    const [showSearch, setShowSearch] = useState(false)
    const menuRef = useRef(null)
    const notifRef = useRef(null)
    const branchRef = useRef(null)
    const [showBranchMenu, setShowBranchMenu] = useState(false)
    const { branches, currentBranch, setBranch, displayCurrency } = useBranch()
    const isAdmin = user?.role === 'admin' || user?.role === 'superuser' || user?.role === 'system_admin' || user?.permissions?.includes('*')
    const userMenuDockStyle = { marginInlineStart: 'auto' }

    // Global Ctrl+K / Cmd+K shortcut
    useEffect(() => {
        const handleKeyDown = (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
                e.preventDefault()
                setShowSearch(prev => !prev)
            }
        }
        document.addEventListener('keydown', handleKeyDown)
        return () => document.removeEventListener('keydown', handleKeyDown)
    }, [])

    // Handle incoming WebSocket notification
    const handleWsNotification = useCallback((notif) => {
        setNotifications(prev => [notif, ...prev].slice(0, 50))
        setUnreadCount(prev => prev + 1)
    }, [])

    // WebSocket connection for real-time notifications
    const { connected: wsConnected } = useNotificationSocket(
        user && user.role !== 'system_admin' ? handleWsNotification : null
    )

    // Initial fetch + fallback polling (only if WS is not connected)
    useEffect(() => {
        if (!user || user.role === 'system_admin') return;

        const fetchNotifications = async () => {
            try {
                const [notifRes, countRes] = await Promise.all([
                    notificationsAPI.getAll(),
                    notificationsAPI.getUnreadCount()
                ]);
                setNotifications(notifRes.data);
                setUnreadCount(countRes.data.count);
            } catch (err) {
                console.error("Failed to fetch notifications", err);
            }
        };
        fetchNotifications();

        // Fallback polling only when WebSocket is disconnected (60s interval)
        if (!wsConnected) {
            const interval = setInterval(fetchNotifications, 60000);
            return () => clearInterval(interval);
        }
    }, [user?.username, wsConnected]);

    // Close menus when clicking outside
    useEffect(() => {
        function handleClickOutside(event) {
            if (menuRef.current && !menuRef.current.contains(event.target)) {
                setShowMenu(false)
            }
            if (notifRef.current && !notifRef.current.contains(event.target)) {
                setShowNotifications(false)
            }
            if (branchRef.current && !branchRef.current.contains(event.target)) {
                setShowBranchMenu(false)
            }
        }
        document.addEventListener("mousedown", handleClickOutside)
        return () => document.removeEventListener("mousedown", handleClickOutside)
    }, [menuRef, notifRef, branchRef])

    const handleLogout = () => {
        logout()
    }

    const handleNotificationClick = async (notif) => {
        try {
            if (!notif.is_read) {
                await notificationsAPI.markRead(notif.id);
                setUnreadCount(prev => Math.max(0, prev - 1));
                setNotifications(prev => prev.map(n =>
                    n.id === notif.id ? { ...n, is_read: true } : n
                ));
            }
            // Navigate based on type
            // e.g. project_task -> /projects/:id
            if (notif.resource_type === 'project' || notif.resource_type === 'task') {
                navigate(`/projects`); // Ideally to specific project if resource_id is project_id
            } else if (notif.resource_type === 'invoice') {
                navigate(`/sales/invoices/${notif.resource_id}`);
            }
            setShowNotifications(false);
        } catch (err) {
            console.error(err);
        }
    };

    const handleMarkAllRead = async () => {
        try {
            await notificationsAPI.markAllRead();
            setUnreadCount(0);
            setNotifications(prev => prev.map(n => ({ ...n, is_read: true })));
        } catch (err) {
            console.error("Failed to mark all as read", err);
        }
    };

    return (
        <header className="topbar" dir="rtl" role="banner">
            <button
                className="topbar-sidebar-toggle"
                onClick={onToggleSidebar}
                aria-label={sidebarOpen ? t('common.close_menu') : t('common.open_menu')}
                aria-expanded={sidebarOpen}
                type="button"
            >
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none"
                    stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect width="18" height="18" x="3" y="3" rx="2" />
                    <path d="M3 9h18" />
                </svg>
            </button>

            <div className="topbar-search" onClick={() => setShowSearch(true)} style={{ cursor: 'pointer' }}>
                <div className="search-input" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', color: 'var(--text-muted, #94a3b8)', userSelect: 'none' }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <circle cx="11" cy="11" r="8" />
                            <path d="m21 21-4.35-4.35" />
                        </svg>
                        {t('common.search')}
                    </span>
                    <kbd style={{
                        fontSize: '11px',
                        fontWeight: 600,
                        padding: '2px 6px',
                        background: 'var(--bg-card)',
                        border: '1px solid var(--border-color)',
                        borderRadius: '4px',
                        color: 'var(--text-muted)',
                        fontFamily: 'inherit'
                    }}>Ctrl+K</kbd>
                </div>
            </div>

            <GlobalSearch isOpen={showSearch} onClose={() => setShowSearch(false)} />

            <div className="topbar-actions-row" style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                {/* Language Switcher */}
                <button
                    className="topbar-lang-btn"
                    onClick={() => {
                        const newLang = i18n.language === 'ar' ? 'en' : 'ar';
                        i18n.changeLanguage(newLang);
                    }}
                    style={{
                        background: 'none',
                        border: '1px solid var(--border-color)',
                        borderRadius: '6px',
                        padding: '4px 8px',
                        cursor: 'pointer',
                        fontSize: '13px',
                        fontWeight: '600'
                    }}
                >
                    {i18n.language === 'ar' ? 'EN' : 'ع'}
                </button>

                {/* Dark Mode Toggle */}
                <button
                    className="topbar-theme-btn"
                    onClick={toggleDarkMode}
                    aria-label={darkMode ? t('common.light_mode') : t('common.dark_mode')}
                    title={darkMode ? t('common.light_mode') : t('common.dark_mode')}
                >
                    {darkMode ? (
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>
                        </svg>
                    ) : (
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>
                        </svg>
                    )}
                </button>

                {/* Branch Selector */}
                {branches.length > 0 && (
                    <div ref={branchRef} style={{ position: 'relative' }}>
                        <button
                            className="topbar-branch-btn"
                            onClick={() => branches.length > 1 || isAdmin ? setShowBranchMenu(!showBranchMenu) : undefined}
                            style={{
                                background: 'var(--bg-card)',
                                border: '1px solid var(--border-color)',
                                borderRadius: '6px',
                                padding: '4px 12px',
                                cursor: (branches.length > 1 || isAdmin) ? 'pointer' : 'default',
                                fontSize: '13px',
                                fontWeight: '600',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '8px',
                                justifyContent: 'space-between'
                            }}
                        >
                            <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                🏢 <span className="topbar-branch-label">
                                    {currentBranch
                                        ? currentBranch.branch_name
                                        : isAdmin
                                            ? (t('branches.all_branches') || 'كل الفروع')
                                            : (t('branches.all_my_branches') || 'كل فروعي')}
                                </span>
                            </span>
                            {displayCurrency?.currency && (
                                <span style={{ fontSize: '11px', color: 'var(--text-secondary)', borderInlineStart: '1px solid var(--border-color)', paddingInlineStart: '8px' }}>
                                    {displayCurrency.currency}
                                </span>
                            )}
                            {(branches.length > 1 || isAdmin) && <span style={{ fontSize: '10px' }}>▼</span>}
                        </button>

                        {showBranchMenu && (
                            <div className="dropdown-menu fade-in" style={{
                                position: 'absolute',
                                top: '35px',
                                left: '0',
                                width: '220px',
                                background: 'var(--bg-card)',
                                borderRadius: '8px',
                                boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
                                border: '1px solid var(--border-color)',
                                zIndex: 100,
                                padding: '4px 0',
                                maxHeight: '300px',
                                overflowY: 'auto'
                            }}>
                                {/* "All branches" option — admin sees all system, non-admin sees all their branches */}
                                {(isAdmin || branches.length > 1) && (
                                    <>
                                        <div
                                            className="dropdown-item"
                                            onClick={() => { setBranch(null); setShowBranchMenu(false); }}
                                            style={{
                                                padding: '8px 12px',
                                                cursor: 'pointer',
                                                fontSize: '13px',
                                                background: !currentBranch ? 'var(--bg-hover)' : 'transparent',
                                                color: !currentBranch ? 'var(--primary)' : 'inherit',
                                                display: 'flex',
                                                justifyContent: 'space-between',
                                                alignItems: 'center',
                                                gap: '12px'
                                            }}
                                        >
                                            <span>🌐 {isAdmin
                                                ? (t('branches.all_branches') || 'كل الفروع')
                                                : (t('branches.all_my_branches') || 'كل فروعي')}</span>
                                            {displayCurrency?.currency && (
                                                <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>{displayCurrency.currency}</span>
                                            )}
                                        </div>
                                        <div style={{ height: '1px', background: 'var(--border-color)', margin: '4px 0' }}></div>
                                    </>
                                )}
                                {branches.map(branch => (
                                    <div
                                        key={branch.id}
                                        className="dropdown-item"
                                        onClick={() => { setBranch(branch); setShowBranchMenu(false); }}
                                        style={{
                                            padding: '8px 12px',
                                            cursor: 'pointer',
                                            fontSize: '13px',
                                            background: currentBranch?.id === branch.id ? 'var(--bg-hover)' : 'transparent',
                                            color: currentBranch?.id === branch.id ? 'var(--primary)' : 'inherit',
                                            display: 'flex',
                                            justifyContent: 'space-between'
                                        }}
                                    >
                                        <span>{branch.branch_name}</span>
                                        <span style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                                            {branch.default_currency && <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>{branch.default_currency}</span>}
                                            {branch.is_default && <span style={{ fontSize: '10px', background: 'var(--bg-hover)', padding: '2px 4px', borderRadius: '4px' }}>{t('common.default')}</span>}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )}

                {/* Notifications Bell */}
                <div ref={notifRef} style={{ position: 'relative' }}>
                    <button
                        onClick={() => setShowNotifications(!showNotifications)}
                        style={{
                            background: 'none',
                            border: 'none',
                            cursor: 'pointer',
                            fontSize: '20px',
                            position: 'relative',
                            padding: '8px'
                        }}
                    >
                        🔔
                        {unreadCount > 0 && (
                            <span style={{
                                position: 'absolute',
                                top: '2px',
                                right: '2px',
                                background: '#EF4444',
                                color: 'white',
                                fontSize: '10px',
                                fontWeight: 'bold',
                                borderRadius: '50%',
                                width: '18px',
                                height: '18px',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center'
                            }}>
                                {unreadCount > 9 ? '9+' : unreadCount}
                            </span>
                        )}
                    </button>

                    {showNotifications && (
                        <div className="dropdown-menu fade-in topbar-notif-dropdown" style={{
                            position: 'absolute',
                            top: '45px',
                            left: '0',
                            width: '320px',
                            maxWidth: 'calc(100vw - 32px)',
                            maxHeight: '400px',
                            overflowY: 'auto',
                            background: 'var(--bg-card)',
                            borderRadius: '12px',
                            boxShadow: '0 10px 40px rgba(0,0,0,0.15)',
                            border: '1px solid var(--border-color)',
                            zIndex: 200,
                        }}>
                            <div style={{
                                padding: '12px 16px',
                                borderBottom: '1px solid var(--border-color)',
                                display: 'flex',
                                justifyContent: 'space-between',
                                alignItems: 'center'
                            }}>
                                <span style={{ fontWeight: '700', fontSize: '15px' }}>🔔 {t('common.notifications_panel.title')}</span>
                                {unreadCount > 0 && (
                                    <button
                                        onClick={handleMarkAllRead}
                                        style={{
                                            background: 'none',
                                            border: 'none',
                                            color: 'var(--primary)',
                                            fontSize: '12px',
                                            cursor: 'pointer'
                                        }}
                                    >
                                        {t('common.notifications_panel.mark_read')}
                                    </button>
                                )}
                            </div>

                            {notifications.length === 0 ? (
                                <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)' }}>
                                    <div style={{ fontSize: '32px', marginBottom: '8px', opacity: 0.5 }}>📭</div>
                                    {t('common.notifications_panel.empty')}
                                </div>
                            ) : (
                                notifications.map(notif => (
                                    <div
                                        key={notif.id}
                                        onClick={() => handleNotificationClick(notif)}
                                        style={{
                                            padding: '12px 16px',
                                            borderBottom: '1px solid var(--border-color)',
                                            cursor: 'pointer',
                                            background: notif.is_read ? 'var(--bg-card)' : 'var(--bg-hover)',
                                            transition: 'background 0.2s'
                                        }}
                                        onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
                                        onMouseLeave={e => e.currentTarget.style.background = notif.is_read ? 'var(--bg-card)' : 'var(--bg-hover)'}
                                    >
                                        <div style={{ fontWeight: notif.is_read ? '400' : '600', fontSize: '13px', marginBottom: '4px' }}>
                                            {notif.title}
                                        </div>
                                        <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '4px' }}>
                                            {notif.message}
                                        </div>
                                        <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                                            {new Date(notif.created_at).toLocaleDateString(i18n.language === 'ar' ? 'ar-SA' : 'en-US')}
                                        </div>
                                    </div>
                                ))
                            )}

                            <Link
                                to="/stock/shipments/incoming"
                                style={{
                                    display: 'block',
                                    padding: '12px 16px',
                                    textAlign: 'center',
                                    color: 'var(--primary)',
                                    fontSize: '13px',
                                    textDecoration: 'none'
                                }}
                                onClick={() => setShowNotifications(false)}
                            >
                                {t('common.notifications_panel.view_incoming')}
                            </Link>
                        </div>
                    )}
                </div>

                {/* User Menu */}
                <div className="topbar-actions" ref={menuRef} style={userMenuDockStyle}>
                    <div
                        className="user-menu-trigger"
                        onClick={() => setShowMenu(!showMenu)}
                        style={{ display: 'flex', alignItems: 'center', cursor: 'pointer', gap: '12px' }}
                    >
                        <div className="user-info-text" style={{ textAlign: 'left' }}>
                            <div style={{ fontSize: '14px', fontWeight: '600' }}>{user?.full_name}</div>
                            <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>ID: {companyId}</div>
                        </div>
                        <div style={{
                            width: '36px',
                            height: '36px',
                            borderRadius: '50%',
                            backgroundColor: 'var(--primary)',
                            color: 'white',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            fontWeight: 'bold',
                            fontSize: '14px'
                        }}>
                            {user?.username?.charAt(0).toUpperCase() || 'U'}
                        </div>
                    </div>

                    {showMenu && (
                        <div className="dropdown-menu fade-in" style={{
                            position: 'absolute',
                            top: '60px',
                            left: '24px',
                            width: '200px',
                            background: 'var(--bg-card)',
                            borderRadius: '8px',
                            boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)',
                            border: '1px solid var(--border-color)',
                            zIndex: 100,
                            padding: '8px 0'
                        }}>
                            <div
                                className="dropdown-item"
                                onClick={() => { setShowMenu(false); navigate('/profile') }}
                                style={{ padding: '8px 16px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '8px', hover: { background: '#f1f5f9' } }}
                            >
                                <span>👤</span> {t('common.user_menu.profile')}
                            </div>
                            {hasPermission('admin.companies') && (
                                <div
                                    className="dropdown-item"
                                    onClick={() => { setShowMenu(false); navigate('/admin/company-profile') }}
                                    style={{ padding: '8px 16px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '8px' }}
                                >
                                    <span>🏢</span> {t('nav.company_profile') || 'ملف الشركة'}
                                </div>
                            )}
                            <div style={{ height: '1px', background: 'var(--border-color)', margin: '8px 0' }}></div>
                            <div
                                className="dropdown-item text-danger"
                                onClick={handleLogout}
                                style={{ padding: '8px 16px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '8px' }}
                            >
                                <span>🚪</span> {t('common.user_menu.logout')}
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </header>
    )
}

export default Topbar
