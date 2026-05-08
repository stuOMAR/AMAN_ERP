import React, { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { reportsAPI } from '../../utils/api'
import { useBranch } from '../../context/BranchContext'
import { formatNumber } from '../../utils/format'
import BackButton from '../../components/common/BackButton';
import CustomDatePicker from '../../components/common/CustomDatePicker';
import { PageLoading } from '../../components/common/LoadingStates'

function TrialBalance() {
    const { t } = useTranslation()
    const { currentBranch } = useBranch()
    const [accounts, setAccounts] = useState([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState('')
    const [totals, setTotals] = useState({ debit: 0, credit: 0, balance: 0 })
    const [startDate, setStartDate] = useState(new Date(new Date().getFullYear(), 0, 1))
    const [endDate, setEndDate] = useState(new Date())
    const [showExport, setShowExport] = useState(false)
    const [currency, setCurrency] = useState('SAR')

    useEffect(() => {
        const fetchData = async () => {
            try {
                setLoading(true)
                const startStr = startDate.toISOString().split('T')[0]
                const endStr = endDate.toISOString().split('T')[0]
                
                const params = {
                    start_date: startStr,
                    end_date: endStr,
                }
                if (currentBranch?.id) params.branch_id = currentBranch.id

                const response = await reportsAPI.getTrialBalance(params)
                const result = response.data || {}
                const data = result.data || result.items || []
                
                setAccounts(Array.isArray(data) ? data : [])
                setCurrency(result.currency || currentBranch?.default_currency || 'SAR')

                // Calculate Totals from closing balances
                let debSum = 0
                let credSum = 0

                if (Array.isArray(data)) {
                    data.forEach(acc => {
                        const debit = parseFloat(acc.closing_debit || acc.period_debit || acc.debit || 0)
                        const credit = parseFloat(acc.closing_credit || acc.period_credit || acc.credit || 0)
                        debSum += debit
                        credSum += credit
                    })
                }

                if (result.totals) {
                    debSum = parseFloat(result.totals.closing_debit || result.totals.period_debit || 0)
                    credSum = parseFloat(result.totals.closing_credit || result.totals.period_credit || 0)
                }

                setTotals({ debit: debSum, credit: credSum, balance: debSum - credSum })
            } catch (err) {
                console.error('Trial balance error:', err)
                setError(t('common.error'))
            } finally {
                setLoading(false)
            }
        }
        fetchData()
    }, [currentBranch, startDate, endDate])

    if (loading) return <PageLoading />

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div>
                    <h1 className="workspace-title">⚖️ {t('accounting.trial_balance.title')}</h1>
                    <p className="workspace-subtitle">{t('accounting.trial_balance.subtitle')}</p>
                </div>
                <div className="action-buttons" style={{ display: 'flex', gap: '8px' }}>
                    <div className="dropdown" style={{ position: 'relative' }}>
                        <button className="btn btn-secondary dropdown-toggle" onClick={() => setShowExport(!showExport)}>
                            📥 {t('common.export', 'تصدير')}
                        </button>
                        {showExport && <div className="dropdown-menu" style={{ display: 'block', position: 'absolute', top: '100%', right: 0, zIndex: 1000, background: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: '4px', boxShadow: '0 2px 5px rgba(0,0,0,0.1)' }}>
                            <button
                                onClick={async () => {
                                    const res = await api.get(`/reports/accounting/trial-balance/export?format=pdf&start_date=${startDate.toISOString().split('T')[0]}&end_date=${endDate.toISOString().split('T')[0]}&branch_id=${currentBranch?.id || ''}`, { responseType: 'blob' });
                                    const url = URL.createObjectURL(res.data);
                                    window.open(url, '_blank');
                                    setTimeout(() => URL.revokeObjectURL(url), 60000);
                                    setShowExport(false);
                                }}
                                className="dropdown-item"
                                style={{ display: 'block', padding: '8px 16px', color: 'inherit', textDecoration: 'none', background: 'none', border: 'none', cursor: 'pointer', width: '100%', textAlign: 'start' }}
                            >
                                📄 PDF
                            </button>
                            <button
                                onClick={async () => {
                                    const res = await api.get(`/reports/accounting/trial-balance/export?format=excel&start_date=${startDate.toISOString().split('T')[0]}&end_date=${endDate.toISOString().split('T')[0]}&branch_id=${currentBranch?.id || ''}`, { responseType: 'blob' });
                                    const url = URL.createObjectURL(res.data);
                                    const a = document.createElement('a'); a.href = url; a.download = 'trial-balance.xlsx'; a.click();
                                    setTimeout(() => URL.revokeObjectURL(url), 60000);
                                    setShowExport(false);
                                }}
                                className="dropdown-item"
                                style={{ display: 'block', padding: '8px 16px', color: 'inherit', textDecoration: 'none', background: 'none', border: 'none', cursor: 'pointer', width: '100%', textAlign: 'start' }}
                            >
                                📊 Excel
                            </button>
                        </div>}
                    </div>
                    <button className="btn btn-secondary" onClick={() => window.print()}>
                        {t('accounting.trial_balance.print')}
                    </button>
                </div>
            </div>

            {/* Date Filters */}
            <div className="card mb-4 mt-4">
                <div className="card-body">
                    <div className="display-flex gap-4 align-end flex-wrap">
                        <div style={{ width: '200px' }}>
                            <label className="form-label">{t('common.start_date', 'من تاريخ')}</label>
                            <CustomDatePicker selected={startDate} onChange={date => setStartDate(date)} className="form-input" />
                        </div>
                        <div style={{ width: '200px' }}>
                            <label className="form-label">{t('common.end_date', 'إلى تاريخ')}</label>
                            <CustomDatePicker selected={endDate} onChange={date => setEndDate(date)} className="form-input" />
                        </div>
                    </div>
                </div>
            </div>

            <div className="metrics-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
                <div className="metric-card">
                    <div className="metric-label">{t('accounting.trial_balance.metrics.total_debit')}</div>
                    <div className="metric-value text-primary">{formatNumber(totals.debit)} <small>{currency}</small></div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('accounting.trial_balance.metrics.total_credit')}</div>
                    <div className="metric-value text-secondary">{formatNumber(totals.credit)} <small>{currency}</small></div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('accounting.trial_balance.metrics.difference')}</div>
                    <div className={`metric-value ${Math.abs(totals.balance) < 0.01 ? 'text-success' : 'text-error'}`}>
                        {formatNumber(totals.balance)} <small>{currency}</small>
                    </div>
                    {Math.abs(totals.balance) < 0.01 && <div className="metric-change">{t('accounting.trial_balance.matched')} ✅</div>}
                </div>
            </div>

            <div className="card">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('accounting.trial_balance.table.account_number')}</th>
                            <th>{t('accounting.trial_balance.table.account_name')}</th>
                            <th style={{ textAlign: 'left' }}>{t('accounting.trial_balance.table.debit')}</th>
                            <th style={{ textAlign: 'left' }}>{t('accounting.trial_balance.table.credit')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {['asset', 'liability', 'equity', 'revenue', 'expense'].map(type => {
                            const typeAccounts = accounts.filter(a => a.account_type === type)
                            if (typeAccounts.length === 0) return null

                            // Calculate Group Totals
                            let groupDebit = 0
                            let groupCredit = 0
                            typeAccounts.forEach(acc => {
                                groupDebit += parseFloat(acc.closing_debit || acc.period_debit || acc.debit || 0)
                                groupCredit += parseFloat(acc.closing_credit || acc.period_credit || acc.credit || 0)
                            })

                            const typeLabels = {
                                asset: t('accounting.coa.types.asset'),
                                liability: t('accounting.coa.types.liability'),
                                equity: t('accounting.coa.types.equity'),
                                revenue: t('accounting.coa.types.revenue'),
                                expense: t('accounting.coa.types.expense')
                            }

                            return (
                                <React.Fragment key={type}>
                                    <tr style={{ background: 'var(--bg-secondary)' }}>
                                        <td colSpan="4" style={{ fontWeight: 'bold', padding: '12px 16px' }}>
                                            {typeLabels[type]}
                                        </td>
                                    </tr>
                                    {typeAccounts.map(acc => {
                                        const debit = parseFloat(acc.closing_debit || acc.period_debit || acc.debit || 0)
                                        const credit = parseFloat(acc.closing_credit || acc.period_credit || acc.credit || 0)

                                        return (
                                            <tr key={acc.account_id || acc.id} className="hover-row">
                                                <td className="font-mono" style={{ paddingLeft: '24px' }}>{acc.account_number}</td>
                                                <td className="font-medium">
                                                    {acc.parent_id ? <span style={{ marginRight: '8px', color: 'var(--text-secondary)' }}>↳</span> : ''}
                                                    {acc.name}
                                                </td>
                                                <td style={{ textAlign: 'left', color: debit > 0 ? 'var(--text-primary)' : 'var(--text-light)' }}>
                                                    {debit > 0 ? formatNumber(debit) : '-'}
                                                </td>
                                                <td style={{ textAlign: 'left', color: credit > 0 ? 'var(--text-primary)' : 'var(--text-light)' }}>
                                                    {credit > 0 ? formatNumber(credit) : '-'}
                                                </td>
                                            </tr>
                                        )
                                    })}
                                    <tr style={{ borderTop: '2px solid var(--border-color)', background: '#F8FAFC' }}>
                                        <td colSpan="2" style={{ textAlign: 'left', fontWeight: 'bold', paddingLeft: '24px' }}>
                                            {t('accounting.trial_balance.total_for')} {typeLabels[type]}
                                        </td>
                                        <td style={{ textAlign: 'left', fontWeight: 'bold' }}>{formatNumber(groupDebit)}</td>
                                        <td style={{ textAlign: 'left', fontWeight: 'bold' }}>{formatNumber(groupCredit)}</td>
                                    </tr>
                                </React.Fragment>
                            )
                        })}
                        <tr style={{ background: 'var(--primary)', color: 'white', fontWeight: 'bold', fontSize: '1.1em' }}>
                            <td colSpan="2" style={{ textAlign: 'center' }}>{t('accounting.trial_balance.total_grand')}</td>
                            <td style={{ textAlign: 'left' }}>{formatNumber(totals.debit)} {currency}</td>
                            <td style={{ textAlign: 'left' }}>{formatNumber(totals.credit)} {currency}</td>
                        </tr>
                    </tbody>
                </table>
            </div>

        </div>
    )
}

export default TrialBalance
