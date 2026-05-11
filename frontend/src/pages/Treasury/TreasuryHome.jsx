import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { treasuryAPI } from '../../utils/api'
import { getCurrency, hasPermission, isAuthReady } from '../../utils/auth'
import { useBranch } from '../../context/BranchContext'
import { useTranslation } from 'react-i18next'
import '../../components/ModuleStyles.css'
import { formatNumber } from '../../utils/format'

function TreasuryHome() {
    const { t, i18n } = useTranslation()
    const navigate = useNavigate()
    const [stats, setStats] = useState({ account_count: 0, cash_count: 0, bank_count: 0, total_balance: 0 })
    const [loading, setLoading] = useState(true)
    const [initialLoad, setInitialLoad] = useState(true)
    const currency = getCurrency() || ''
    const { currentBranch } = useBranch()

    useEffect(() => {
        const fetchStats = async () => {
            try {
                setLoading(true)
                const branchId = currentBranch?.id || null
                const response = await treasuryAPI.listAccounts(branchId)

                const accounts = response.data
                const total = accounts.reduce((sum, acc) => sum + Number(acc.current_balance), 0)
                const cash = accounts.filter(a => a.account_type === 'cash').length
                const bank = accounts.filter(a => a.account_type === 'bank').length

                setStats({
                    account_count: accounts.length,
                    cash_count: cash,
                    bank_count: bank,
                    total_balance: total
                })
            } catch (err) {
                console.error("Failed to fetch treasury stats", err)
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
                <h1 className="workspace-title">{t('treasury.title')}</h1>
                <p className="workspace-subtitle">{t('treasury.subtitle')}</p>
            </div>

            {/* Metrics Section */}
            <div className="metrics-grid">
                <div className="metric-card">
                    <div className="metric-label">{t('common.total_balance')}</div>
                    <div className="metric-value text-primary">
                        {!isAuthReady() ? '...' : !hasPermission('reports.view') ? '***' : (initialLoad ? '...' : formatNumber(stats.total_balance))} {isAuthReady() && hasPermission('reports.view') && <small>{currency}</small>}
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('treasury.cash_accounts')}</div>
                    <div className="metric-value text-warning">
                        {!isAuthReady() ? '...' : !hasPermission('reports.view') ? '***' : (initialLoad ? '...' : stats.cash_count)}
                    </div>
                    <div className="metric-change">
                        {initialLoad ? '' : t('common.active')}
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('treasury.bank_accounts')}</div>
                    <div className="metric-value text-secondary">
                        {!isAuthReady() ? '...' : !hasPermission('reports.view') ? '***' : (initialLoad ? '...' : stats.bank_count)}
                    </div>
                    <div className="metric-change">
                        {initialLoad ? '' : t('common.active')}
                    </div>
                </div>
            </div>

            {/* Module Sections */}
            <div className="modules-grid">
                {/* Masters Section */}
                <div className="card section-card">
                    <h3 className="section-title">{t('treasury.sections.masters')}</h3>
                    <div className="links-list">
                        <div className="link-item" onClick={() => navigate('/treasury/accounts')}>
                            <span className="link-icon">🏦</span>
                            {t('treasury.menu.accounts')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                    </div>
                </div>

                {/* Transactions Section */}
                <div className="card section-card">
                    <h3 className="section-title">{t('treasury.sections.transactions')}</h3>
                    <div className="links-list">
                        <div className="link-item" onClick={() => navigate('/treasury/expense')}>
                            <span className="link-icon">💸</span>
                            {t('treasury.menu.expense')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/treasury/transfer')}>
                            <span className="link-icon">🔄</span>
                            {t('treasury.menu.transfer')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/treasury/reconciliation')}>
                            <span className="link-icon">📑</span>
                            {t('treasury.menu.reconciliation')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/treasury/checks-receivable')}>
                            <span className="link-icon">📥</span>
                            {t('treasury.checks_for_collection')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/treasury/checks-payable')}>
                            <span className="link-icon">📤</span>
                            {t('treasury.checks_for_payment')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/treasury/notes-receivable')}>
                            <span className="link-icon">📜</span>
                            {t('treasury.notes_receivable')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/treasury/notes-payable')}>
                            <span className="link-icon">📝</span>
                            {t('treasury.notes_payable')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                    </div>
                </div>

                {/* Reports and Finance Tools */}
                {(hasPermission('reports.view') || hasPermission('finance.cashflow_view') || hasPermission('finance.subscription_view')) && (
                    <div className="card section-card">
                        <h3 className="section-title">{t('treasury.sections.reports')}</h3>
                        <div className="links-list">
                            {hasPermission('reports.view') && (
                                <>
                                    <div className="link-item" onClick={() => navigate('/treasury/reports/cashflow')}>
                                        <span className="link-icon">📈</span>
                                        {t('treasury.menu.cashflow')}
                                        <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                                    </div>
                                    <div className="link-item" onClick={() => navigate('/treasury/reports/balances')}>
                                        <span className="link-icon">⚖️</span>
                                        {t('treasury.menu.balances')}
                                        <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                                    </div>
                                    <div className="link-item" onClick={() => navigate('/treasury/reports/checks-aging')}>
                                        <span className="link-icon">⏳</span>
                                        {i18n.t('treasury.checks_aging')}
                                        <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                                    </div>
                                </>
                            )}
                            {hasPermission('finance.cashflow_view') && (
                                <div className="link-item" onClick={() => navigate('/finance/cashflow')}>
                                    <span className="link-icon">📉</span>
                                    {i18n.t('treasury.cash_flow_forecast')}
                                    <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                                </div>
                            )}
                            {hasPermission('finance.subscription_view') && (
                                <div className="link-item" onClick={() => navigate('/finance/subscriptions')}>
                                    <span className="link-icon">🔄</span>
                                    {i18n.t('subscription.title')}
                                    <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                                </div>
                            )}
                            {hasPermission('treasury.view') && (
                                <div className="link-item" onClick={() => navigate('/treasury/bank-import')}>
                                    <span className="link-icon">🏦</span>
                                    {i18n.t('bank_import.title')}
                                    <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}

export default TreasuryHome
