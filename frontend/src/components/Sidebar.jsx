import { NavLink } from 'react-router-dom'
import { getUser, hasPermission } from '../utils/auth'
import { useTranslation } from 'react-i18next'
import { getIndustryType } from '../hooks/useIndustryType'
import { isModuleEnabledForIndustry } from '../config/industryModules'

function Sidebar({ isOpen, isMobile, onClose, onToggle }) {
    const { t } = useTranslation()
    const user = getUser()
    const industryType = getIndustryType()
    const navItems = [
        { path: '/dashboard', label: t('nav.workspace'), icon: '🏠' },
    ]

    if (user?.role === 'system_admin') {
        navItems.push({ path: '/admin/companies', label: t('nav.companies'), icon: '🏢' })
        navItems.push({ path: '/admin/ops/scheduler', label: t('nav.ops_scheduler', 'جدولة العمليات'), icon: '⚡' })
        navItems.push({ path: '/health/detailed', label: t('nav.health', 'صحة النظام'), icon: '🏥' })
    } else {
        const enabledModules = user?.enabled_modules || []
        const isSystemAdmin = user?.role === 'system_admin'

        // Helper to check if module is enabled
        // أولوية 1: enabled_modules المخزنة في الباك إند (القائمة المخصصة)
        // أولوية 2: مصفوفة النشاط التجاري (الافتراضي)
        // أولوية 3: إذا لم يُحدد شيء → إظهار الكل
        const isModuleEnabled = (moduleKey) => {
            if (isSystemAdmin) return true
            // الأولوية للقائمة المخصصة من enabled_modules
            if (enabledModules.length > 0) {
                return enabledModules.includes(moduleKey)
            }
            // مصفوفة النشاط التجاري (fallback)
            if (industryType) {
                return isModuleEnabledForIndustry(industryType, moduleKey)
            }
            // لم يُعدّ شيء بعد → إظهار الكل
            return true
        }

        if (hasPermission('accounting.view') && isModuleEnabled('accounting')) {
            navItems.push({ path: '/accounting', label: t('nav.accounting'), icon: '📊' })
        }
        if (hasPermission('assets.view') && isModuleEnabled('assets')) {
            navItems.push({ path: '/assets', label: t('nav.assets'), icon: '🏗️' })
        }
        if (hasPermission('treasury.view') && isModuleEnabled('treasury')) {
            navItems.push({ path: '/treasury', label: t('nav.treasury'), icon: '🏦' })
        }
        if (hasPermission('sales.view') && isModuleEnabled('sales')) {
            navItems.push({ path: '/sales', label: t('nav.sales'), icon: '💰' })
        }
        // POS Module
        if (hasPermission('pos.view') && isModuleEnabled('pos')) {
            navItems.push({ path: '/pos', label: t('nav.pos'), icon: '🏪' })
        }

        if (hasPermission('buying.view') && isModuleEnabled('buying')) {
            navItems.push({ path: '/buying', label: t('nav.buying'), icon: '🛒' })
        }
        if (hasPermission('stock.view') && isModuleEnabled('stock')) {
            navItems.push({ path: '/stock', label: t('nav.inventory'), icon: '📦' })
        }
        // Manufacturing Module
        if (hasPermission('manufacturing.view') && isModuleEnabled('manufacturing')) {
            navItems.push({ path: '/manufacturing', label: t('nav.manufacturing'), icon: '🏭' })
        }
        // Projects Module
        if (hasPermission('projects.view') && isModuleEnabled('projects')) {
            navItems.push({ path: '/projects', label: t('nav.projects'), icon: '📐' })
        }
        // CRM Module
        if (hasPermission('sales.view') && isModuleEnabled('crm')) {
            navItems.push({ path: '/crm', label: t('nav.crm'), icon: '🤝' })
        }
        // Services Module
        if (hasPermission('services.view') && isModuleEnabled('services')) {
            navItems.push({ path: '/services', label: t('nav.services'), icon: '🔧' })
        }
        // Expenses Module
        if (hasPermission('expenses.view') && isModuleEnabled('expenses')) {
            navItems.push({ path: '/expenses', label: t('nav.expenses'), icon: '💸' })
        }
        // Taxes Module
        if (hasPermission('accounting.view') && isModuleEnabled('taxes')) {
            navItems.push({ path: '/taxes', label: t('nav.taxes'), icon: '🧾' })
        }
        if (hasPermission('approvals.view') && isModuleEnabled('approvals')) {
            navItems.push({ path: '/approvals', label: t('nav.approvals'), icon: '✅' })
        }
        if (hasPermission('reports.view') && isModuleEnabled('reports')) {
            navItems.push({ path: '/reports', label: t('nav.reports'), icon: '📈' })
        }
        if (hasPermission('hr.view') && isModuleEnabled('hr')) {
            navItems.push({ path: '/hr', label: t('nav.hr'), icon: '👥' })
        }
        if (hasPermission('settings.view')) {
            navItems.push({ path: '/settings', label: t('nav.settings'), icon: '⚙️' })
        }
        if (hasPermission('admin.roles')) {
            navItems.push({ path: '/reports/kpi-admin', label: t('nav.kpi_admin', 'إدارة المؤشرات'), icon: '🎯' })
        }
    }


    const handleToggleClick = (e) => {
        e.preventDefault()
        e.stopPropagation()
        if (typeof onToggle === 'function') {
            onToggle()
        }
    }

    return (
        <aside
            className={`sidebar${isOpen ? ' sidebar-open' : ''}`}
            dir="rtl"
            role="navigation"
            aria-label={t('a11y.primary_nav', 'القائمة الرئيسية')}
        >
            <div className="sidebar-brand">
                <button
                    className="sidebar-toggle"
                    onClick={handleToggleClick}
                    aria-label={isOpen ? t('common.close_menu') : t('common.open_menu')}
                    aria-expanded={isOpen}
                    type="button"
                >
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none"
                        stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <rect width="18" height="18" x="3" y="3" rx="2" />
                        <path d="M3 9h18" />
                    </svg>
                </button>
                <span className="sidebar-brand-text">AMAN ERP</span>
            </div>
            <nav className="sidebar-nav">
                {navItems.map((item) => (
                    <NavLink
                        key={item.path}
                        to={item.path}
                        data-nav-target={item.path}
                        end={item.path === '/treasury' || item.path === '/settings'}
                        className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}
                        onClick={isMobile ? onClose : undefined}
                    >
                        <div className="nav-icon-container">
                            <span className="nav-icon">{item.icon}</span>
                        </div>
                        <span className="nav-label">{item.label}</span>
                    </NavLink>
                ))}
            </nav>
        </aside>
    )
}

export default Sidebar
