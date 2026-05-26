import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { getUser, getCompanyId, logout, hasPermission } from '../utils/auth'
import { useTranslation } from 'react-i18next'
import { useBranch } from '../context/BranchContext'
import { useTheme } from '../context/ThemeContext'
import GlobalSearch from './GlobalSearch'
import NotificationCenter from './Notifications/NotificationCenter'
import './GlobalSearch.css'

function Topbar({ sidebarOpen = false, onToggleSidebar }) {
    const { t, i18n } = useTranslation()
    const { darkMode, toggleDarkMode } = useTheme()
    const user = getUser()
    const companyId = getCompanyId()
    const navigate = useNavigate()
    const [showMenu, setShowMenu] = useState(false)
    const [showSearch, setShowSearch] = useState(false)
    const menuRef = useRef(null)
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

    // Close menus when clicking outside
    useEffect(() => {
        function handleClickOutside(event) {
            if (menuRef.current && !menuRef.current.contains(event.target)) {
                setShowMenu(false)
            }
            if (branchRef.current && !branchRef.current.contains(event.target)) {
                setShowBranchMenu(false)
            }
        }
        document.addEventListener("mousedown", handleClickOutside)
        return () => document.removeEventListener("mousedown", handleClickOutside)
    }, [menuRef, branchRef])

    const handleLogout = () => {
        logout()
    }

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
                {user && user.role !== 'system_admin' && <NotificationCenter />}

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
