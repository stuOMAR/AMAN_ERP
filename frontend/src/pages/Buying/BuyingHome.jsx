import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { purchasesAPI } from '../../utils/api'
import { getCurrency, hasPermission } from '../../utils/auth'
import { useBranch } from '../../context/BranchContext'
import { useTranslation } from 'react-i18next'
import { useToast } from '../../context/ToastContext'
import '../../components/ModuleStyles.css'
import { formatNumber } from '../../utils/format'
import { getIndustryFeature } from '../../hooks/useIndustryType'

function BuyingHome() {
    const { t, i18n } = useTranslation()
    const navigate = useNavigate()
    const { showToast } = useToast()
    const [stats, setStats] = useState({ supplier_count: 0, total_payables: 0, monthly_purchases: 0 })
    const [loading, setLoading] = useState(true)
    const [initialLoad, setInitialLoad] = useState(true)
    const currency = getCurrency()
    const { currentBranch } = useBranch()

    const showRFQ             = getIndustryFeature('buying.rfq')
    const showAgreements      = getIndustryFeature('buying.agreements')
    const showSupplierRatings = getIndustryFeature('buying.supplier_ratings')
    useEffect(() => {
        const fetchStats = async () => {
            if (!hasPermission('buying.reports')) {
                setLoading(false);
                setInitialLoad(false);
                return;
            }
            try {
                setLoading(true)
                const params = {}
                if (currentBranch?.id) params.branch_id = currentBranch.id

                const response = await purchasesAPI.getSummary(params)
                setStats(response.data)
            } catch (err) {
                showToast(t('common.error'), 'error')
            } finally {
                setLoading(false)
                setInitialLoad(false)
            }
        }
        const timer = setTimeout(() => {
            fetchStats()
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch])

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <h1 className="workspace-title">{t('buying.home.title')}</h1>
                <p className="workspace-subtitle">{t('buying.home.subtitle')}</p>
            </div>

            {/* Metrics Section */}
            <div className="metrics-grid">
                <div className="metric-card">
                    <div className="metric-label">{t('buying.home.metrics.monthly_purchases')}</div>
                    <div className="metric-value text-primary">
                        {!hasPermission('buying.reports') ? '***' : (loading ? '...' : formatNumber(stats.monthly_purchases))} {hasPermission('buying.reports') && <small>{currency}</small>}
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('buying.home.metrics.total_payables')}</div>
                    <div className="metric-value text-warning">
                        {!hasPermission('buying.reports') ? '***' : (loading ? '...' : formatNumber(stats.total_payables))} {hasPermission('buying.reports') && <small>{currency}</small>}
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('buying.home.metrics.supplier_count')}</div>
                    <div className="metric-value text-secondary">
                        {!hasPermission('buying.reports') ? '***' : (loading ? '...' : stats.supplier_count)}
                    </div>
                </div>
            </div>

            {/* Module Sections */}
            <div className="modules-grid">
                {/* Masters Section */}
                <div className="card section-card">
                    <h3 className="section-title">{t('buying.home.sections.masters')}</h3>
                    <div className="links-list">
                        <div className="link-item" onClick={() => navigate('/buying/suppliers')}>
                            <span className="link-icon">🏭</span>
                            {t('buying.home.links.suppliers')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/buying/supplier-groups')}>
                            <span className="link-icon">📁</span>
                            {t('buying.home.links.supplier_groups')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                    </div>
                </div>

                {/* Transactions Section */}
                <div className="card section-card">
                    <h3 className="section-title">{t('buying.home.sections.transactions')}</h3>
                    <div className="links-list">
                        <div className="link-item" onClick={() => navigate('/buying/invoices')}>
                            <span className="link-icon">🧾</span>
                            {t('buying.home.links.invoices')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/buying/returns')}>
                            <span className="link-icon">🔙</span>
                            {t('buying.home.links.returns')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/buying/orders')}>
                            <span className="link-icon">📝</span>
                            {t('buying.home.links.orders')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/buying/payments')}>
                            <span className="link-icon">💳</span>
                            {t('buying.home.links.payments')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/buying/credit-notes')}>
                            <span className="link-icon">📋</span>
                            {t('buying.home.links.credit_notes')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/buying/debit-notes')}>
                            <span className="link-icon">📝</span>
                            {t('buying.home.links.debit_notes')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        {showRFQ && (
                            <div className="link-item" onClick={() => navigate('/buying/rfq')}>
                                <span className="link-icon">📨</span>
                                {i18n.t('buying.rfq_title')}
                                <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                            </div>
                        )}
                        {showAgreements && (
                            <div className="link-item" onClick={() => navigate('/buying/agreements')}>
                                <span className="link-icon">🤝</span>
                                {i18n.t('buying.agreements_title')}
                                <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                            </div>
                        )}
                        <div className="link-item" onClick={() => navigate('/buying/blanket-po')}>
                            <span className="link-icon">📋</span>
                            {i18n.t('blanket_po.title')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                    </div>
                </div>

                {/* Reports Section */}
                {/* Reports Section */}
                {hasPermission('buying.reports') && (
                    <div className="card section-card">
                        <h3 className="section-title">{t('buying.home.sections.reports')}</h3>
                        <div className="links-list">
                            <div className="link-item" onClick={() => navigate('/buying/reports/analytics')}>
                                <span className="link-icon">📊</span>
                                {t('buying.home.links.reports_analytics')}
                                <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                            </div>
                            <div className="link-item" onClick={() => navigate('/buying/reports/supplier-statement')}>
                                <span className="link-icon">📜</span>
                                {t('buying.home.links.reports_statement')}
                                <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                            </div>
                            {showSupplierRatings && (
                                <div className="link-item" onClick={() => navigate('/buying/supplier-ratings')}>
                                    <span className="link-icon">⭐</span>
                                    {i18n.t('buying.ratings_title')}
                                    <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                                </div>
                            )}
                            <div className="link-item" onClick={() => navigate('/buying/reports/aging')}>
                                <span className="link-icon">⏳</span>
                                {i18n.t('buying.purchases_aging')}
                                <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                            </div>
                        </div>
                    </div>
                )}

                {/* Matching & Quality Section */}
                {hasPermission('buying.view') && (
                    <div className="card section-card">
                        <h3 className="section-title">{i18n.t('buying.matching_quality')}</h3>
                        <div className="links-list">
                            <div className="link-item" onClick={() => navigate('/buying/matching')}>
                                <span className="link-icon">🔗</span>
                                {i18n.t('nav.matching')}
                                <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                            </div>
                            <div className="link-item" onClick={() => navigate('/buying/matching/tolerances')}>
                                <span className="link-icon">⚙️</span>
                                {i18n.t('matching.tolerances')}
                                <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                            </div>
                            <div className="link-item" onClick={() => navigate('/buying/landed-costs')}>
                                <span className="link-icon">🚢</span>
                                {i18n.t('landed_costs.title')}
                                <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}

export default BuyingHome
