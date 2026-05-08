import { useState, useEffect } from 'react'
import { reportsAPI, api } from '../../utils/api'
import { useBranch } from '../../context/BranchContext'
import { useTranslation } from 'react-i18next'
import { formatNumber } from '../../utils/format'
import { getCurrency } from '../../utils/auth'
import CustomDatePicker from '../../components/common/CustomDatePicker'
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

function IncomeStatement() {
    const { t, i18n } = useTranslation()
    const { currentBranch } = useBranch()
    const [startDate, setStartDate] = useState(new Date(new Date().getFullYear(), 0, 1))
    const [endDate, setEndDate] = useState(new Date())
    const [data, setData] = useState(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(null)
    const [isCompareMode, setIsCompareMode] = useState(false)
    const [compareStartDate, setCompareStartDate] = useState(new Date(new Date().getFullYear() - 1, 0, 1))
    const [compareEndDate, setCompareEndDate] = useState(new Date(new Date().getFullYear() - 1, 11, 31))
    const [showExport, setShowExport] = useState(false)

    const fetchData = async () => {
        try {
            setLoading(true)
            setError(null)

            if (isCompareMode) {
                const periods = [
                    `${startDate.toISOString().split('T')[0]}:${endDate.toISOString().split('T')[0]}`,
                    `${compareStartDate.toISOString().split('T')[0]}:${compareEndDate.toISOString().split('T')[0]}`
                ].join(',')

                const response = await reportsAPI.compareProfitLoss({
                    periods,
                    branch_id: currentBranch?.id
                })
                setData(response.data)
            } else {
                const params = {
                    start_date: startDate.toISOString().split('T')[0],
                    end_date: endDate.toISOString().split('T')[0],
                    branch_id: currentBranch?.id
                }
                const response = await reportsAPI.getProfitLoss(params)
                setData(response.data)
            }
        } catch (err) {
            console.error("Failed to fetch income statement", err)
            setError(t('accounting.income_statement.error_loading'))
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        fetchData()
    }, [currentBranch, startDate, endDate, isCompareMode, compareStartDate, compareEndDate])

    // Helpers
    const currency = getCurrency()
    const isRTL = i18n.language === 'ar'
    const getName = (acc) => (isRTL ? acc.name : (acc.name_en || acc.name))

    // Flatten account tree to a list with level info
    const flattenTree = (nodes, level = 0) => {
        const result = []
        for (const node of (nodes || [])) {
            result.push({ ...node, level })
            if (node.children && node.children.length > 0) {
                result.push(...flattenTree(node.children, level + 1))
            }
        }
        return result
    }

    // Derive totals and flat lists from API data
    const allAccounts = data?.data || []
    const revenueRoots = allAccounts.filter(a => a.account_type === 'revenue')
    const expenseRoots = allAccounts.filter(a => a.account_type === 'expense')
    const flatRevenue = flattenTree(revenueRoots)
    const flatExpense = flattenTree(expenseRoots)
    const totalRevenue = revenueRoots.reduce((sum, a) => sum + (parseFloat(a.balance) || 0), 0)
    const totalExpense = expenseRoots.reduce((sum, a) => sum + (parseFloat(a.balance) || 0), 0)
    const netIncome = data?.total !== undefined ? parseFloat(data.total) : (totalRevenue - totalExpense)

    return (
        <div className="workspace fade-in">
            <div className="workspace-header display-flex justify-between align-center">
                <BackButton />
                <div>
                    <h1 className="workspace-title">📈 {t('accounting.income_statement.title')}</h1>
                    <p className="workspace-subtitle">{t('accounting.income_statement.subtitle')}</p>
                </div>
                <div className="display-flex gap-2">
                    {/* Export Buttons */}
                    <div className="dropdown" style={{ position: 'relative' }}>
                        <button className="btn btn-secondary dropdown-toggle" onClick={() => setShowExport(!showExport)}>
                            📥 {t('common.export')}
                        </button>
                        {showExport && <div className="dropdown-menu" style={{ display: 'block', position: 'absolute', top: '100%', right: 0, zIndex: 1000, background: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: '4px', boxShadow: '0 2px 5px rgba(0,0,0,0.1)' }}>
                            <button
                                onClick={async () => {
                                    const res = await api.get(`/reports/accounting/profit-loss/export?format=pdf&start_date=${startDate.toISOString().split('T')[0]}&end_date=${endDate.toISOString().split('T')[0]}&branch_id=${currentBranch?.id || ''}`, { responseType: 'blob' });
                                    const url = URL.createObjectURL(res.data);
                                    window.open(url, '_blank');
                                    setTimeout(() => URL.revokeObjectURL(url), 60000);
                                }}
                                className="dropdown-item"
                                style={{ display: 'block', padding: '8px 16px', color: 'inherit', textDecoration: 'none', background: 'none', border: 'none', cursor: 'pointer', width: '100%', textAlign: 'start' }}
                            >
                                📄 PDF
                            </button>
                            <button
                                onClick={async () => {
                                    const res = await api.get(`/reports/accounting/profit-loss/export?format=excel&start_date=${startDate.toISOString().split('T')[0]}&end_date=${endDate.toISOString().split('T')[0]}&branch_id=${currentBranch?.id || ''}`, { responseType: 'blob' });
                                    const url = URL.createObjectURL(res.data);
                                    const a = document.createElement('a'); a.href = url; a.download = 'income-statement.xlsx'; a.click();
                                    setTimeout(() => URL.revokeObjectURL(url), 60000);
                                }}
                                className="dropdown-item"
                                style={{ display: 'block', padding: '8px 16px', color: 'inherit', textDecoration: 'none', background: 'none', border: 'none', cursor: 'pointer', width: '100%', textAlign: 'start' }}
                            >
                                📊 Excel
                            </button>
                        </div>}
                    </div>
                    <button className="btn btn-secondary" onClick={() => window.print()}>
                        {t('common.print')}
                    </button>
                    <button className="btn btn-primary" onClick={fetchData}>
                        {t('common.refresh')}
                    </button>
                </div>
            </div>

            {/* Date Filters */}
            <div className="card mb-4 mt-4">
                <div className="card-body">
                    <div className="display-flex gap-4 align-end flex-wrap">
                        <div style={{ width: '200px' }}>
                            <label className="form-label">{t('common.start_date')}</label>
                            <CustomDatePicker
                                selected={startDate}
                                onChange={date => setStartDate(date)}
                                className="form-input"
                            />
                        </div>
                        <div style={{ width: '200px' }}>
                            <label className="form-label">{t('common.end_date')}</label>
                            <CustomDatePicker
                                selected={endDate}
                                onChange={date => setEndDate(date)}
                                className="form-input"
                            />
                        </div>

                        <div className="form-check" style={{ marginBottom: '10px', marginLeft: '20px' }}>
                            <input
                                type="checkbox"
                                className="form-check-input"
                                id="compareMode"
                                checked={isCompareMode}
                                onChange={e => setIsCompareMode(e.target.checked)}
                            />
                            <label className="form-check-label" htmlFor="compareMode">
                                {t('accounting.reports.compare_periods')}
                            </label>
                        </div>

                        {isCompareMode && (
                            <>
                                <div style={{ width: '200px' }}>
                                    <label className="form-label">{t('common.start_date')} (2)</label>
                                    <CustomDatePicker
                                        selected={compareStartDate}
                                        onChange={date => setCompareStartDate(date)}
                                        className="form-input"
                                    />
                                </div>
                                <div style={{ width: '200px' }}>
                                    <label className="form-label">{t('common.end_date')} (2)</label>
                                    <CustomDatePicker
                                        selected={compareEndDate}
                                        onChange={date => setCompareEndDate(date)}
                                        className="form-input"
                                    />
                                </div>
                            </>
                        )}
                    </div>
                </div>
            </div>

            {loading ? (
                <PageLoading />
            ) : error ? (
                <div className="alert alert-danger">{error}</div>
            ) : data && (
                isCompareMode ? (
                    /* Comparison View */
                    <>
                        <div className="table-responsive card">
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>{t('accounting.general_ledger.account')}</th>
                                        {data.periods && data.periods.map((p, idx) => (
                                            <th key={idx} style={{ textAlign: 'left' }}>
                                                {p.label || `${p.start} - ${p.end}`}
                                            </th>
                                        ))}
                                        <th style={{ textAlign: 'left' }}>{t('accounting.reports.variance')}</th>
                                        <th style={{ textAlign: 'left' }}>%</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {/* Revenue Section */}
                                    <tr className="section-header" style={{ background: 'var(--bg-secondary)', fontWeight: 'bold' }}>
                                        <td colSpan={2 + (data.periods?.length || 0)}>💰 {t('accounting.income_statement.revenue')}</td>
                                    </tr>
                                    {data.comparison && data.comparison.filter(i => i.account_type === 'revenue').map((row, idx) => (
                                        <tr key={idx} className="hover-row">
                                            <td>
                                                <span className="font-mono text-muted">{row.account_number}</span> {' '}
                                                {getName(row)}
                                            </td>
                                            {row.periods.map((val, pIdx) => (
                                                <td key={pIdx} style={{ textAlign: 'left' }}>{formatNumber(val)}</td>
                                            ))}
                                            <td style={{ textAlign: 'left', color: row.change >= 0 ? 'var(--success)' : 'var(--danger)' }}>
                                                {formatNumber(row.change)}
                                            </td>
                                            <td style={{ textAlign: 'left', color: row.change >= 0 ? 'var(--success)' : 'var(--danger)' }}>
                                                {row.change_pct}%
                                            </td>
                                        </tr>
                                    ))}

                                    {/* Expense Section */}
                                    <tr className="section-header" style={{ background: 'var(--bg-secondary)', fontWeight: 'bold' }}>
                                        <td colSpan={2 + (data.periods?.length || 0)}>📉 {t('accounting.income_statement.expenses')}</td>
                                    </tr>
                                    {data.comparison && data.comparison.filter(i => i.account_type === 'expense').map((row, idx) => (
                                        <tr key={idx} className="hover-row">
                                            <td>
                                                <span className="font-mono text-muted">{row.account_number}</span> {' '}
                                                {getName(row)}
                                            </td>
                                            {row.periods.map((val, pIdx) => (
                                                <td key={pIdx} style={{ textAlign: 'left' }}>{formatNumber(val)}</td>
                                            ))}
                                            <td style={{ textAlign: 'left', color: row.change <= 0 ? 'var(--success)' : 'var(--danger)' }}>
                                                {formatNumber(row.change)}
                                            </td>
                                            <td style={{ textAlign: 'left', color: row.change <= 0 ? 'var(--success)' : 'var(--danger)' }}>
                                                {row.change_pct}%
                                            </td>
                                        </tr>
                                    ))}

                                    {/* Net Income Summary */}
                                    <tr style={{ background: 'var(--primary)', color: 'white', fontWeight: 'bold' }}>
                                        <td>{t('accounting.income_statement.net_income')}</td>
                                        {data.summary && data.summary.map((s, idx) => (
                                            <td key={idx} style={{ textAlign: 'left' }}>{formatNumber(s.net_income)}</td>
                                        ))}
                                        <td colSpan="2"></td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </>
                ) : (
                    /* Standard View */
                    <>
                        {/* Summary Cards */}
                        <div className="metrics-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
                            <div className="metric-card">
                                <div className="metric-label">{t('accounting.income_statement.total_revenue')}</div>
                                <div className="metric-value text-success">{formatNumber(totalRevenue)} <small>{currency}</small></div>
                            </div>
                            <div className="metric-card">
                                <div className="metric-label">{t('accounting.income_statement.total_expenses')}</div>
                                <div className="metric-value text-danger">{formatNumber(totalExpense)} <small>{currency}</small></div>
                            </div>
                            <div className="metric-card">
                                <div className="metric-label">{t('accounting.income_statement.net_income')}</div>
                                <div className={`metric-value ${netIncome >= 0 ? 'text-success' : 'text-error'}`}>
                                    {formatNumber(Math.abs(netIncome))} <small>{currency}</small>
                                    {netIncome >= 0 ? ' ✅' : ' ⚠️'}
                                </div>
                                <div className="metric-change">
                                    {netIncome >= 0 ? t('accounting.income_statement.profit') : t('accounting.income_statement.loss')}
                                </div>
                            </div>
                        </div>

                        {/* Revenue Section */}
                        <div className="card mb-4">
                            <div className="card-header" style={{ background: 'var(--success-bg, #ecfdf5)', borderBottom: '2px solid var(--success, #10b981)' }}>
                                <h3 className="card-title" style={{ color: 'var(--success, #10b981)' }}>
                                    💰 {t('accounting.income_statement.revenue')}
                                </h3>
                            </div>
                            <div className="table-responsive">
                                <table className="data-table">
                                    <thead>
                                        <tr>
                                            <th>{t('accounting.general_ledger.account')}</th>
                                            <th style={{ textAlign: 'left' }}>{t('accounting.income_statement.amount')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {flatRevenue.length === 0 ? (
                                            <tr>
                                                <td colSpan="2" className="text-center p-4 text-muted">{t('common.no_data')}</td>
                                            </tr>
                                        ) : (
                                            flatRevenue.map((acc, idx) => (
                                                <tr key={idx} className="hover-row" style={{
                                                    background: acc.level === 0 ? 'var(--bg-secondary)' : 'transparent',
                                                    fontWeight: acc.children && acc.children.length > 0 ? 'bold' : 'normal'
                                                }}>
                                                    <td style={{ paddingRight: `${(acc.level * 24) + 16}px` }}>
                                                        {acc.level > 0 && <span style={{ color: 'var(--text-secondary)', marginLeft: '4px' }}>↳</span>}
                                                        <span className="font-mono" style={{ marginLeft: '8px' }}>{acc.account_number}</span>
                                                        {' '}{getName(acc)}
                                                    </td>
                                                    <td style={{ textAlign: 'left' }}>{formatNumber(Math.abs(acc.balance))}</td>
                                                </tr>
                                            ))
                                        )}
                                    </tbody>
                                    <tfoot>
                                        <tr style={{ fontWeight: 'bold', background: 'var(--bg-secondary)' }}>
                                            <td>{t('accounting.income_statement.total_revenue')}</td>
                                            <td style={{ textAlign: 'left', color: 'var(--success, #10b981)' }}>{formatNumber(totalRevenue)} {currency}</td>
                                        </tr>
                                    </tfoot>
                                </table>
                            </div>
                        </div>

                        {/* Expense Section */}
                        <div className="card mb-4">
                            <div className="card-header" style={{ background: 'var(--danger-bg, #fef2f2)', borderBottom: '2px solid var(--danger, #ef4444)' }}>
                                <h3 className="card-title" style={{ color: 'var(--danger, #ef4444)' }}>
                                    📉 {t('accounting.income_statement.expenses')}
                                </h3>
                            </div>
                            <div className="table-responsive">
                                <table className="data-table">
                                    <thead>
                                        <tr>
                                            <th>{t('accounting.general_ledger.account')}</th>
                                            <th style={{ textAlign: 'left' }}>{t('accounting.income_statement.amount')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {flatExpense.length === 0 ? (
                                            <tr>
                                                <td colSpan="2" className="text-center p-4 text-muted">{t('common.no_data')}</td>
                                            </tr>
                                        ) : (
                                            flatExpense.map((acc, idx) => (
                                                <tr key={idx} className="hover-row" style={{
                                                    background: acc.level === 0 ? 'var(--bg-secondary)' : 'transparent',
                                                    fontWeight: acc.children && acc.children.length > 0 ? 'bold' : 'normal'
                                                }}>
                                                    <td style={{ paddingRight: `${(acc.level * 24) + 16}px` }}>
                                                        {acc.level > 0 && <span style={{ color: 'var(--text-secondary)', marginLeft: '4px' }}>↳</span>}
                                                        <span className="font-mono" style={{ marginLeft: '8px' }}>{acc.account_number}</span>
                                                        {' '}{getName(acc)}
                                                    </td>
                                                    <td style={{ textAlign: 'left' }}>{formatNumber(Math.abs(acc.balance))}</td>
                                                </tr>
                                            ))
                                        )}
                                    </tbody>
                                    <tfoot>
                                        <tr style={{ fontWeight: 'bold', background: 'var(--bg-secondary)' }}>
                                            <td>{t('accounting.income_statement.total_expenses')}</td>
                                            <td style={{ textAlign: 'left', color: 'var(--danger, #ef4444)' }}>{formatNumber(totalExpense)} {currency}</td>
                                        </tr>
                                    </tfoot>
                                </table>
                            </div>
                        </div>

                        {/* Net Income */}
                        <div className="card">
                            <table className="data-table">
                                <tbody>
                                    <tr style={{
                                        background: netIncome >= 0 ? 'var(--success, #10b981)' : 'var(--danger, #ef4444)',
                                        color: 'white',
                                        fontWeight: 'bold',
                                        fontSize: '1.2em'
                                    }}>
                                        <td style={{ textAlign: 'center', padding: '16px' }}>
                                            {netIncome >= 0 ? t('accounting.income_statement.net_profit') : t('accounting.income_statement.net_loss')}
                                        </td>
                                        <td style={{ textAlign: 'left', padding: '16px' }}>
                                            {formatNumber(Math.abs(netIncome))} {currency}
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </>
                )
            )}
        </div>
    )
}

export default IncomeStatement
