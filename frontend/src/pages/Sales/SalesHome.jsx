import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { salesAPI } from '../../utils/api'
import { getCurrency, hasPermission, isAuthReady } from '../../utils/auth'
import { useBranch } from '../../context/BranchContext'
import { useTranslation } from 'react-i18next'
import '../../components/ModuleStyles.css'
import { formatNumber } from '../../utils/format'
import { getIndustryFeature } from '../../hooks/useIndustryType'
import { useToast } from '../../context/ToastContext'

function SalesHome() {
    const { t, i18n } = useTranslation()
    const { showToast } = useToast()
    const navigate = useNavigate()
    const [stats, setStats] = useState({ customer_count: 0, total_receivables: 0, monthly_sales: 0, unpaid_count: 0 })
    const [loading, setLoading] = useState(true)
    const [initialLoad, setInitialLoad] = useState(true)
    const currency = getCurrency()
    const { currentBranch } = useBranch()

    const showContracts = getIndustryFeature('sales.contracts')
    useEffect(() => {
        const timer = setTimeout(() => {
            const fetchStats = async () => {
                try {
                    setLoading(true)
                    const params = {}
                    if (currentBranch?.id) params.branch_id = currentBranch.id

                    const response = await salesAPI.getSummary(params)
                    setStats(response.data)
                } catch (err) {
                    showToast(t('common.error'), 'error')
                } finally {
                    setLoading(false)
                    setInitialLoad(false)
                }
            }
            fetchStats()
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch])

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <h1 className="workspace-title">{t('sales.title')}</h1>
                <p className="workspace-subtitle">{t('sales.subtitle')}</p>
            </div>

            {/* Metrics Section */}
            <div className="metrics-grid">
                <div className="metric-card">
                    <div className="metric-label">{t('sales.metrics.monthly_sales')}</div>
                    <div className="metric-value text-primary">
                        {!isAuthReady() ? '...' : !hasPermission('sales.reports') ? '***' : (initialLoad ? '...' : formatNumber(stats.monthly_sales))} {isAuthReady() && hasPermission('sales.reports') && <small>{currency}</small>}
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('sales.metrics.receivables')}</div>
                    <div className="metric-value text-warning">
                        {!isAuthReady() ? '...' : !hasPermission('sales.reports') ? '***' : (initialLoad ? '...' : formatNumber(stats.total_receivables))} {isAuthReady() && hasPermission('sales.reports') && <small>{currency}</small>}
                    </div>
                    {isAuthReady() && hasPermission('sales.reports') && (
                        <div className="metric-change">
                            {initialLoad ? '' : `${stats.unpaid_count} ${t('sales.metrics.invoices_count')}`}
                        </div>
                    )}
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('sales.metrics.total_customers')}</div>
                    <div className="metric-value text-secondary">
                        {!isAuthReady() ? '...' : !hasPermission('sales.reports') ? '***' : (initialLoad ? '...' : stats.customer_count)}
                    </div>
                </div>
            </div>

            {/* Module Sections */}
            <div className="modules-grid">
                {/* Masters Section */}
                <div className="card section-card">
                    <h3 className="section-title">{t('sales.sections.masters')}</h3>
                    <div className="links-list">
                        <div className="link-item" onClick={() => navigate('/sales/customers')}>
                            <span className="link-icon">👥</span>
                            {t('sales.menu.customers')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/sales/customer-groups')}>
                            <span className="link-icon">📁</span>
                            {t('sales.menu.customer_groups')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/sales/price-lists')}>
                            <span className="link-icon">🏷️</span>
                            {t('sales.menu.price_lists')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                    </div>
                </div>

                {/* Transactions Section */}
                <div className="card section-card">
                    <h3 className="section-title">{t('sales.sections.transactions')}</h3>
                    <div className="links-list">
                        <div className="link-item" onClick={() => navigate('/sales/invoices')}>
                            <span className="link-icon">🧾</span>
                            {t('sales.menu.invoices')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/sales/orders')}>
                            <span className="link-icon">📦</span>
                            {t('sales.menu.orders')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/sales/quotations')}>
                            <span className="link-icon">💬</span>
                            {t('sales.menu.quotations')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/sales/cpq/products')}>
                            <span className="link-icon">🧮</span>
                            {t('sales.menu.advanced_pricing')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/sales/returns')}>
                            <span className="link-icon">🔄</span>
                            {t('sales.menu.returns')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/sales/receipts')}>
                            <span className="link-icon">💰</span>
                            {t('sales.menu.vouchers')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        {showContracts && (
                            <div className="link-item" onClick={() => navigate('/sales/contracts')}>
                                <span className="link-icon">📄</span>
                                {t('sales.menu.contracts')}
                                <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                            </div>
                        )}
                        <div className="link-item" onClick={() => navigate('/sales/credit-notes')}>
                            <span className="link-icon">📋</span>
                            {t('sales.menu.credit_notes')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/sales/debit-notes')}>
                            <span className="link-icon">📝</span>
                            {t('sales.menu.debit_notes')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/sales/commissions')}>
                            <span className="link-icon">💵</span>
                            {i18n.t('reports.report_types.commissions')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                    </div>
                </div>

                {/* Reports Section */}
                {/* Reports Section */}
                {hasPermission('sales.reports') && (
                    <div className="card section-card">
                        <h3 className="section-title">{t('sales.sections.reports')}</h3>
                        <div className="links-list">
                            <div className="link-item" onClick={() => navigate('/sales/reports/analytics')}>
                                <span className="link-icon">📊</span>
                                {t('sales.menu.analytics_report')}
                                <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                            </div>
                            <div className="link-item" onClick={() => navigate('/sales/reports/customer-statement')}>
                                <span className="link-icon">📜</span>
                                {t('sales.menu.statement_report')}
                                <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                            </div>
                            <div className="link-item" onClick={() => navigate('/sales/reports/aging')}>
                                <span className="link-icon">⏳</span>
                                {t('sales.menu.aging_report')}
                                <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                            </div>
                            <div className="link-item" onClick={() => navigate('/sales/commissions')}>
                                <span className="link-icon">💵</span>
                                {t('reports.commissions.title', 'تقرير عمولات المبيعات')}
                                <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}

export default SalesHome
