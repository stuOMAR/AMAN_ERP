import { useEffect, useState, useCallback } from 'react'
import { useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import Sidebar from './Sidebar'
import Topbar from './Topbar'
import { authAPI } from '../utils/api'
import { getUser } from '../utils/auth'

function Layout({ children }) {
    const { i18n } = useTranslation()
    const location = useLocation()
    const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth > 1024)
    const [isMobile, setIsMobile] = useState(() => window.innerWidth <= 1024)

    useEffect(() => {
        const user = getUser();
        const syncUser = async () => {
            try {
                const response = await authAPI.me()
                localStorage.setItem('user', JSON.stringify(response.data))
            } catch (err) {
                console.error("Session sync failed", err)
            }
        }
        if (user) syncUser();
    }, [])

    // Track screen size
    useEffect(() => {
        const handleResize = () => {
            const mobile = window.innerWidth <= 1024
            setIsMobile(mobile)
            if (mobile) setSidebarOpen(false)
            else setSidebarOpen(true)
        }
        window.addEventListener('resize', handleResize)
        return () => window.removeEventListener('resize', handleResize)
    }, [])

    const toggleSidebar = useCallback(() => setSidebarOpen(prev => !prev), [])
    const closeSidebar = useCallback(() => setSidebarOpen(false), [])

    useEffect(() => {
        const rawTarget = sessionStorage.getItem('aman:return-target')
        if (!rawTarget) return

        const fullTarget = rawTarget
        const pathTarget = rawTarget.split('?')[0]

        const selector = [
            `[data-nav-target="${fullTarget}"]`,
            `[data-nav-target="${pathTarget}"]`,
            `a[href="${fullTarget}"]`,
            `a[href="${pathTarget}"]`,
        ].join(', ')

        // Wait one frame to ensure destination page UI is mounted.
        const raf = requestAnimationFrame(() => {
            const el = document.querySelector(selector)
            if (!el) {
                return
            }

            el.classList.add('nav-return-flash')
            setTimeout(() => {
                el.classList.remove('nav-return-flash')
            }, 1200)
            sessionStorage.removeItem('aman:return-target')
        })

        return () => cancelAnimationFrame(raf)
    }, [location.pathname, location.search])

    return (
        <div className="app-layout">
            {/* Dark overlay — only on mobile when sidebar is open */}
            {isMobile && sidebarOpen && (
                <div
                    className="sidebar-overlay"
                    onClick={closeSidebar}
                    aria-hidden="true"
                    style={{ display: 'block' }}
                />
            )}
            <Sidebar isOpen={sidebarOpen} isMobile={isMobile} onClose={closeSidebar} onToggle={toggleSidebar} />
            <div className={`main-container ${sidebarOpen ? 'sidebar-open' : 'sidebar-closed'}`}>
                <Topbar sidebarOpen={sidebarOpen} onToggleSidebar={toggleSidebar} />
                {/* page-scroll-area: always direction:rtl so the scrollbar
                    stays pinned to the FAR LEFT regardless of app language.
                    The inner <main> gets the real dir from i18n. */}
                <div className="page-scroll-area">
                    {/* T8.2 a11y: id="main-content" is the skip-link target;
                        role="main" + tabIndex make it focusable when activated. */}
                    <main
                        id="main-content"
                        role="main"
                        tabIndex="-1"
                        className="content-area"
                        dir={i18n.language === 'ar' ? 'rtl' : 'ltr'}
                    >
                        {children}
                    </main>
                </div>
            </div>
        </div>
    )
}

export default Layout
