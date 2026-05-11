import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { inventoryAPI } from '../../utils/api'
import { getCurrency, hasPermission, isAuthReady } from '../../utils/auth'
import { useBranch } from '../../context/BranchContext'
import { useToast } from '../../context/ToastContext'
import { useTranslation } from 'react-i18next'
import '../../components/ModuleStyles.css'
import { formatNumber } from '../../utils/format'

function StockHome() {
    const { t, i18n } = useTranslation()
    const navigate = useNavigate()
    const [stats, setStats] = useState({ product_count: 0, inventory_value: 0, low_stock_count: 0, currency: '' })
    const [loading, setLoading] = useState(true)
    const [initialLoad, setInitialLoad] = useState(true)
    const currency = stats.currency || getCurrency()
    const { currentBranch } = useBranch()
    const { showToast } = useToast()

    useEffect(() => {
        const fetchStats = async () => {
            try {
                setLoading(true)
                const params = {}
                if (currentBranch?.id) params.branch_id = currentBranch.id

                const response = await inventoryAPI.getSummary(params)
                setStats(response.data)
            } catch (err) {
                showToast(t('errors.fetch_failed'), 'error')
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
                <h1 className="workspace-title">{t('stock.home.title')}</h1>
                <p className="workspace-subtitle">{t('stock.home.subtitle')}</p>
            </div>

            {/* Metrics Section */}
            <div className="metrics-grid">
                <div className="metric-card">
                    <div className="metric-label">{t('stock.home.metrics.total_products')}</div>
                    <div className="metric-value text-primary">
                        {!isAuthReady() ? '...' : !hasPermission('stock.reports') ? '***' : (loading ? '...' : stats.product_count)}
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('stock.home.metrics.inventory_value')}</div>
                    <div className="metric-value text-success">
                        {!isAuthReady() ? '...' : !hasPermission('stock.reports') ? '***' : (loading ? '...' : formatNumber(stats.inventory_value))} {isAuthReady() && hasPermission('stock.reports') && <small>{currency}</small>}
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('stock.home.metrics.low_stock')}</div>
                    <div className="metric-value text-warning">
                        {!isAuthReady() ? '...' : !hasPermission('stock.reports') ? '***' : (loading ? '...' : stats.low_stock_count)}
                    </div>
                </div>
            </div>

            {/* Module Sections */}
            <div className="modules-grid">
                {/* Masters Section */}
                <div className="card section-card">
                    <h3 className="section-title">{t('stock.home.sections.masters')}</h3>
                    <div className="links-list">
                        <div className="link-item" onClick={() => navigate('/stock/products')}>
                            <span className="link-icon">📦</span>
                            {t('stock.home.links.products')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/stock/price-lists')}>
                            <span className="link-icon">🏷️</span>
                            {t('stock.home.links.price_lists')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/stock/categories')}>
                            <span className="link-icon">📁</span>
                            {t('stock.home.links.categories')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/stock/warehouses')}>
                            <span className="link-icon">🏭</span>
                            {t('stock.home.links.warehouses')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                    </div>
                </div>

                {/* Transactions Section */}
                <div className="card section-card">
                    <h3 className="section-title">{t('stock.home.sections.transactions')}</h3>
                    <div className="links-list">
                        <div className="link-item" onClick={() => navigate('/stock/transfer')}>
                            <span className="link-icon">🔄</span>
                            {t('stock.home.links.transfer')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/stock/shipments')}>
                            <span className="link-icon">🚚</span>
                            {t('stock.home.links.shipments')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/stock/shipments/incoming')}>
                            <span className="link-icon">📥</span>
                            {t('stock.home.links.incoming_shipments')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/stock/adjustments')}>
                            <span className="link-icon">⚖️</span>
                            {t('stock.adjustments.title')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                    </div>
                </div>

                {/* Reports Section */}
                {hasPermission('stock.reports') && (
                    <div className="card section-card">
                        <h3 className="section-title">{t('stock.home.sections.reports')}</h3>
                        <div className="links-list">
                            <div className="link-item" onClick={() => navigate('/stock/reports/balance')}>
                                <span className="link-icon">📊</span>
                                {t('stock.home.links.balance_report')}
                                <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                            </div>
                            <div className="link-item" onClick={() => navigate('/stock/reports/movements')}>
                                <span className="link-icon">📈</span>
                                {t('stock.home.links.movements_report')}
                                <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                            </div>
                            <div className="link-item" onClick={() => navigate('/stock/reports/profitability')}>
                                <span className="link-icon">💰</span>
                                {t('stock.home.links.profitability_report', 'تقرير الربحية')}
                                <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                            </div>
                        </div>
                    </div>
                )}

                {/* Advanced Inventory Section */}
                <div className="card section-card">
                    <h3 className="section-title">{t('stock.home.sections.advanced')}</h3>
                    <div className="links-list">
                        <div className="link-item" onClick={() => navigate('/stock/batches')}>
                            <span className="link-icon">📦</span>
                            {t('stock.home.links.batches')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/stock/serials')}>
                            <span className="link-icon">🏷️</span>
                            {t('stock.home.links.serials')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/stock/quality')}>
                            <span className="link-icon">🔬</span>
                            {t('stock.home.links.quality')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/stock/cycle-counts')}>
                            <span className="link-icon">📋</span>
                            {t('stock.home.links.cycle_counts')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/stock/cost-layers')}>
                            <span className="link-icon">📊</span>
                            {i18n.t('nav.cost_layers')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/stock/costing-method')}>
                            <span className="link-icon">⚙️</span>
                            {i18n.t('costing.method')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/stock/costing-valuation')}>
                            <span className="link-icon">📈</span>
                            {i18n.t('reports.inventory_valuation.title')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        {hasPermission('inventory.forecast_view') && (
                            <div className="link-item" onClick={() => navigate('/inventory/forecast')}>
                                <span className="link-icon">📉</span>
                                {i18n.t('nav.demand_forecast')}
                                <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                            </div>
                        )}
                        {hasPermission('inventory.forecast_generate') && (
                            <div className="link-item" onClick={() => navigate('/inventory/forecast/generate')}>
                                <span className="link-icon">➕</span>
                                {i18n.t('forecast.generate_forecast')}
                                <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    )
}

export default StockHome
