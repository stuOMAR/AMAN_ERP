import { useState, useEffect } from 'react'
import { reportsAPI, api } from '../../utils/api'
import { useBranch } from '../../context/BranchContext'
import { useTranslation } from 'react-i18next'
import { formatNumber } from '../../utils/format'
import { getCurrency } from '../../utils/auth'
import CustomDatePicker from '../../components/common/CustomDatePicker'
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

function BalanceSheet() {
    const { t, i18n } = useTranslation()
    const { currentBranch } = useBranch()
    const [asOfDate, setAsOfDate] = useState(new Date())
    const [isCompareMode, setIsCompareMode] = useState(false)
    const [compareDate, setCompareDate] = useState(new Date(new Date().getFullYear() - 1, 11, 31))
    const [data, setData] = useState(null)
    const [loading, setLoading] = useState(false)
    const [initialLoad, setInitialLoad] = useState(true)
    const [error, setError] = useState(null)
    const [showExport, setShowExport] = useState(false)
    const currency = getCurrency()

    const fetchData = async () => {
        try {
            setLoading(true)
            setError(null)

            if (isCompareMode) {
                const periods = [
                    asOfDate.toISOString().split('T')[0],
                    compareDate.toISOString().split('T')[0]
                ].join(',')

                const response = await reportsAPI.compareBalanceSheet({
                    periods,
                    branch_id: currentBranch?.id
                })
                setData(response.data)
            } else {
                const params = {
                    as_of_date: asOfDate.toISOString().split('T')[0],
                    branch_id: currentBranch?.id
                }
                const response = await reportsAPI.getBalanceSheet(params)
                setData(response.data)
            }
        } catch (err) {
            console.error("Failed to fetch balance sheet", err)
            setError(t('accounting.balance_sheet.error_loading'))
        } finally {
            setLoading(false)
            setInitialLoad(false)
        }
    }

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchData()
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch, asOfDate, isCompareMode, compareDate])

    // Flatten tree for display
    const flattenTree = (nodes, level = 0) => {
        const result = []
        for (const node of nodes) {
            result.push({ ...node, level })
            if (node.children && node.children.length > 0) {
                result.push(...flattenTree(node.children, level + 1))
            }
        }
        return result
    }

    const assetAccounts = data ? data.data.filter(a => a.account_type === 'asset') : []
    const liabilityAccounts = data ? data.data.filter(a => a.account_type === 'liability') : []
    const equityAccounts = data ? data.data.filter(a => a.account_type === 'equity') : []
    const revenueAccounts = data ? data.data.filter(a => a.account_type === 'revenue') : []
    const expenseAccounts = data ? data.data.filter(a => a.account_type === 'expense') : []

    // Only sum leaf accounts (is_header = false) to avoid double counting
    const leafAssets = assetAccounts.filter(a => !a.is_header)
    const leafLiabilities = liabilityAccounts.filter(a => !a.is_header)
    const leafEquity = equityAccounts.filter(a => !a.is_header)
    const leafRevenue = revenueAccounts.filter(a => !a.is_header)
    const leafExpenses = expenseAccounts.filter(a => !a.is_header)

    const totalAssets = leafAssets.reduce((sum, a) => sum + parseFloat(a.balance || 0), 0)
    const totalLiabilities = leafLiabilities.reduce((sum, a) => sum + parseFloat(a.balance || 0), 0)
    const totalEquity = leafEquity.reduce((sum, a) => sum + parseFloat(a.balance || 0), 0)
    const totalRevenue = leafRevenue.reduce((sum, a) => sum + parseFloat(a.balance || 0), 0)
    const totalExpenses = leafExpenses.reduce((sum, a) => sum + parseFloat(a.balance || 0), 0)
    const netRevenue = totalRevenue + totalExpenses
    const totalLiabAndEquity = totalLiabilities + totalEquity

    const flatAssets = flattenTree(assetAccounts)
    const flatLiabilities = flattenTree(liabilityAccounts)
    const flatEquity = flattenTree(equityAccounts)

    const isBalanced = Math.abs(totalAssets - totalLiabAndEquity) < 0.01

    const getName = (item) => {
        if (i18n.language === 'en' && item.name_en) return item.name_en
        return item.name
    }

    const renderSection = (title, icon, items, total, colorVar) => (
        <div className="card mb-4">
            <div className="card-header" style={{ borderBottom: `2px solid var(${colorVar})` }}>
                <h3 className="card-title">
                    {icon} {title}
                </h3>
            </div>
            <div className="data-table-container">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('accounting.general_ledger.account')}</th>
                            <th style={{ textAlign: 'left' }}>{t('accounting.balance_sheet.amount')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {items.length === 0 ? (
                            <tr>
                                <td colSpan="2" className="text-center p-4 text-muted">{t('common.no_data')}</td>
                            </tr>
                        ) : (
                            items.map((acc, idx) => (
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
                            <td>{title}</td>
                            <td style={{ textAlign: 'left' }}>{formatNumber(total)} {currency}</td>
                        </tr>
                    </tfoot>
                </table>
            </div>
        </div>
    )

    return (
        <div className="workspace fade-in">
            <div className="workspace-header display-flex justify-between align-center">
                <BackButton />
                <div>
                    <h1 className="workspace-title">🏦 {t('accounting.balance_sheet.title')}</h1>
                    <p className="workspace-subtitle">{t('accounting.balance_sheet.subtitle')}</p>
                </div>
                <div className="display-flex gap-2">
                    <div className="dropdown" style={{ position: 'relative' }}>
                        <button className="btn btn-secondary dropdown-toggle" onClick={() => setShowExport(!showExport)}>
                            📥 {t('common.export')}
                        </button>
                        {showExport && <div className="dropdown-menu" style={{ display: 'block', position: 'absolute', top: '100%', right: 0, zIndex: 1000, background: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: '4px', boxShadow: '0 2px 5px rgba(0,0,0,0.1)' }}>
                            <button
                                onClick={async () => {
                                    const res = await api.get(`/reports/accounting/balance-sheet/export?format=pdf&as_of_date=${asOfDate.toISOString().split('T')[0]}&branch_id=${currentBranch?.id || ''}`, { responseType: 'blob' });
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
                                    const res = await api.get(`/reports/accounting/balance-sheet/export?format=excel&as_of_date=${asOfDate.toISOString().split('T')[0]}&branch_id=${currentBranch?.id || ''}`, { responseType: 'blob' });
                                    const url = URL.createObjectURL(res.data);
                                    const a = document.createElement('a'); a.href = url; a.download = 'balance-sheet.xlsx'; a.click();
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

            {/* Date Filter */}
            <div className="card mb-4 mt-4">
                <div className="card-body">
                    <div className="display-flex gap-4 align-end flex-wrap">
                        <div style={{ width: '200px' }}>
                            <label className="form-label">{t('accounting.balance_sheet.as_of_date')}</label>
                            <CustomDatePicker
                                selected={asOfDate}
                                onChange={date => setAsOfDate(date)}
                                className="form-input"
                            />
                        </div>

                        <div className="form-check" style={{ marginBottom: '10px', marginLeft: '20px' }}>
                            <input
                                type="checkbox"
                                className="form-check-input"
                                id="compareModeBS"
                                checked={isCompareMode}
                                onChange={e => setIsCompareMode(e.target.checked)}
                            />
                            <label className="form-check-label" htmlFor="compareModeBS">
                                {t('accounting.reports.compare_periods')}
                            </label>
                        </div>

                        {isCompareMode && (
                            <div style={{ width: '200px' }}>
                                <label className="form-label">{t('accounting.balance_sheet.as_of_date')} (2)</label>
                                <CustomDatePicker
                                    selected={compareDate}
                                    onChange={date => setCompareDate(date)}
                                    className="form-input"
                                />
                            </div>
                        )}
                    </div>
                </div>
            </div>

            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            {initialLoad && !data ? (
                <PageLoading />
            ) : error ? (
                <div className="alert alert-danger">{error}</div>
            ) : data && (
                isCompareMode ? (
                    /* Comparison View */
                    <div className="table-responsive card">
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th>{t('accounting.general_ledger.account')}</th>
                                    {data.periods && data.periods.map((p, idx) => (
                                        <th key={idx} style={{ textAlign: 'left' }}>
                                            {p.label || p.date}
                                        </th>
                                    ))}
                                    <th style={{ textAlign: 'left' }}>{t('accounting.reports.variance')}</th>
                                    <th style={{ textAlign: 'left' }}>%</th>
                                </tr>
                            </thead>
                            <tbody>
                                {/* Assets Section */}
                                <tr className="section-header" style={{ background: 'var(--bg-secondary)', fontWeight: 'bold' }}>
                                    <td colSpan={2 + (data.periods?.length || 0)}>🏢 {t('accounting.balance_sheet.assets')}</td>
                                </tr>
                                {data.comparison && data.comparison.filter(i => i.account_type === 'asset').map((row, idx) => (
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
                                {/* Total Assets */}
                                <tr style={{ background: 'var(--bg-secondary)', fontWeight: 'bold' }}>
                                    <td>{t('accounting.balance_sheet.total_assets')}</td>
                                    {data.summary && data.summary.map((s, idx) => (
                                        <td key={idx} style={{ textAlign: 'left', color: 'var(--primary)' }}>{formatNumber(s.total_assets)}</td>
                                    ))}
                                    <td colSpan={2}></td>
                                </tr>

                                {/* Liabilities Section */}
                                <tr className="section-header" style={{ background: 'var(--bg-secondary)', fontWeight: 'bold' }}>
                                    <td colSpan={2 + (data.periods?.length || 0)}>📋 {t('accounting.balance_sheet.liabilities')}</td>
                                </tr>
                                {data.comparison && data.comparison.filter(i => i.account_type === 'liability').map((row, idx) => (
                                    <tr key={idx} className="hover-row">
                                        <td>
                                            <span className="font-mono text-muted">{row.account_number}</span> {' '}
                                            {getName(row)}
                                        </td>
                                        {row.periods.map((val, pIdx) => (
                                            <td key={pIdx} style={{ textAlign: 'left' }}>{formatNumber(val)}</td>
                                        ))}
                                        <td style={{ textAlign: 'left' }}>
                                            {formatNumber(row.change)}
                                        </td>
                                        <td style={{ textAlign: 'left' }}>
                                            {row.change_pct}%
                                        </td>
                                    </tr>
                                ))}
                                {/* Total Liabilities */}
                                <tr style={{ background: 'var(--bg-secondary)', fontWeight: 'bold' }}>
                                    <td>{t('accounting.balance_sheet.total_liabilities')}</td>
                                    {data.summary && data.summary.map((s, idx) => (
                                        <td key={idx} style={{ textAlign: 'left', color: 'var(--danger)' }}>{formatNumber(s.total_liabilities)}</td>
                                    ))}
                                    <td colSpan={2}></td>
                                </tr>

                                {/* Equity Section */}
                                <tr className="section-header" style={{ background: 'var(--bg-secondary)', fontWeight: 'bold' }}>
                                    <td colSpan={2 + (data.periods?.length || 0)}>🏛️ {t('accounting.balance_sheet.equity')}</td>
                                </tr>
                                {data.comparison && data.comparison.filter(i => i.account_type === 'equity').map((row, idx) => (
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
                                {/* Total Equity */}
                                <tr style={{ background: 'var(--bg-secondary)', fontWeight: 'bold' }}>
                                    <td>{t('accounting.balance_sheet.total_equity')}</td>
                                    {data.summary && data.summary.map((s, idx) => (
                                        <td key={idx} style={{ textAlign: 'left', color: 'var(--secondary)' }}>{formatNumber(s.total_equity)}</td>
                                    ))}
                                    <td colSpan={2}></td>
                                </tr>

                                {/* Total Liab + Equity */}
                                <tr style={{ background: 'var(--primary)', color: 'white', fontWeight: 'bold' }}>
                                    <td>{t('accounting.balance_sheet.total_liabilities_and_equity')}</td>
                                    {data.summary && data.summary.map((s, idx) => (
                                        <td key={idx} style={{ textAlign: 'left' }}>{formatNumber(s.total_liabilities + s.total_equity)}</td>
                                    ))}
                                    <td colSpan={2}></td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                ) : (
                    <>
                        {/* Summary Cards */}
                        <div className="metrics-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
                            <div className="metric-card">
                                <div className="metric-label">{t('accounting.balance_sheet.total_assets')}</div>
                                <div className="metric-value text-primary">{formatNumber(totalAssets)} <small>{currency}</small></div>
                            </div>
                            <div className="metric-card">
                                <div className="metric-label">{t('accounting.balance_sheet.total_liabilities')}</div>
                                <div className="metric-value text-danger">{formatNumber(totalLiabilities)} <small>{currency}</small></div>
                            </div>
                            <div className="metric-card">
                                <div className="metric-label">{t('accounting.balance_sheet.total_equity')}</div>
                                <div className="metric-value text-secondary">{formatNumber(totalEquity)} <small>{currency}</small></div>
                            </div>
                            <div className="metric-card">
                                <div className="metric-label">{t('accounting.balance_sheet.equation_check')}</div>
                                <div className={`metric-value ${isBalanced ? 'text-success' : 'text-error'}`}>
                                    {isBalanced ? '✅' : '⚠️'}
                                    <small style={{ fontSize: '0.7em', marginRight: '8px' }}>
                                        {isBalanced ? t('accounting.balance_sheet.balanced') : t('accounting.balance_sheet.unbalanced')}
                                    </small>
                                </div>
                            </div>
                        </div>

                        {/* Assets Section */}
                        {renderSection(
                            t('accounting.balance_sheet.assets'),
                            '🏢',
                            flatAssets,
                            totalAssets,
                            '--primary'
                        )}

                        {/* Liabilities Section */}
                        {renderSection(
                            t('accounting.balance_sheet.liabilities'),
                            '📋',
                            flatLiabilities,
                            totalLiabilities,
                            '--danger, #ef4444'
                        )}

                        {/* Equity Section */}
                        {renderSection(
                            t('accounting.balance_sheet.equity'),
                            '🏛️',
                            flatEquity,
                            totalEquity,
                            '--secondary'
                        )}

                        {/* Balance Equation */}
                        <div className="card">
                            <table className="data-table">
                                <tbody>
                                    <tr style={{
                                        background: 'var(--primary)',
                                        color: 'white',
                                        fontWeight: 'bold',
                                        fontSize: '1.1em'
                                    }}>
                                        <td style={{ padding: '16px', textAlign: 'center' }}>
                                            {t('accounting.balance_sheet.total_assets')}
                                        </td>
                                        <td style={{ padding: '16px', textAlign: 'left' }}>
                                            {formatNumber(totalAssets)} {currency}
                                        </td>
                                    </tr>
                                    <tr style={{
                                        background: 'var(--bg-secondary)',
                                        fontWeight: 'bold',
                                        fontSize: '1.1em'
                                    }}>
                                        <td style={{ padding: '16px', textAlign: 'center' }}>
                                            {t('accounting.balance_sheet.total_liabilities_and_equity')}
                                        </td>
                                        <td style={{ padding: '16px', textAlign: 'left' }}>
                                            {formatNumber(totalLiabAndEquity)} {currency}
                                        </td>
                                    </tr>
                                    <tr style={{
                                        background: isBalanced ? 'var(--success, #10b981)' : 'var(--danger, #ef4444)',
                                        color: 'white',
                                        fontWeight: 'bold',
                                        fontSize: '1em'
                                    }}>
                                        <td style={{ padding: '12px', textAlign: 'center' }}>
                                            {t('accounting.balance_sheet.difference')}
                                        </td>
                                        <td style={{ padding: '12px', textAlign: 'left' }}>
                                            {formatNumber(Math.abs(totalAssets - totalLiabAndEquity))} {currency}
                                            {isBalanced && ' ✅'}
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

export default BalanceSheet
