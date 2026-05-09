import { useState, useEffect } from 'react'
import { reportsAPI, accountingAPI } from '../../utils/api'
import { useBranch } from '../../context/BranchContext'
import { useTranslation } from 'react-i18next'
import { formatNumber } from '../../utils/format'
import { getCurrency } from '../../utils/auth'
import CustomDatePicker from '../../components/common/CustomDatePicker'
import { formatDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates';

function GeneralLedger() {
    const { t, i18n } = useTranslation()
    const { currentBranch } = useBranch()
    const [startDate, setStartDate] = useState(new Date(new Date().getFullYear(), 0, 1))
    const [endDate, setEndDate] = useState(new Date())
    const [accounts, setAccounts] = useState([])
    const [selectedAccount, setSelectedAccount] = useState('')
    const [entries, setEntries] = useState([])
    const [loading, setLoading] = useState(false)
    const [loadingAccounts, setLoadingAccounts] = useState(true)
    const [initialLoad, setInitialLoad] = useState(true)
    const [error, setError] = useState(null)
    const [isAggregated, setIsAggregated] = useState(false)
    const [childCount, setChildCount] = useState(0)
    const [openingBalance, setOpeningBalance] = useState(0)
    const currency = getCurrency()

    // Load accounts list
    useEffect(() => {
        const fetchAccounts = async () => {
            try {
                setLoadingAccounts(true)
                const res = await accountingAPI.list({ branch_id: currentBranch?.id })
                const data = Array.isArray(res.data) ? res.data : (res.data?.data || [])
                setAccounts(data)
            } catch (err) {
                console.error("Failed to load accounts", err)
            } finally {
                setLoadingAccounts(false)
                setInitialLoad(false)
            }
        }
        fetchAccounts()
    }, [currentBranch])

    const fetchLedger = async () => {
        if (!selectedAccount) return
        try {
            setLoading(true)
            setError(null)
            const params = {
                account_id: selectedAccount,
                start_date: startDate.toISOString().split('T')[0],
                end_date: endDate.toISOString().split('T')[0],
                branch_id: currentBranch?.id
            }
            const response = await reportsAPI.getGeneralLedger(params)
            setEntries(response.data.entries || [])
            setIsAggregated(response.data.is_aggregated || false)
            setChildCount(response.data.child_accounts_count || 0)
            setOpeningBalance(response.data.opening_balance || 0)
        } catch (err) {
            console.error("Failed to fetch ledger", err)
            setError(t('accounting.general_ledger.error_loading'))
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        const timer = setTimeout(() => {
            if (selectedAccount) {
                fetchLedger()
            }
        }, 300)
        return () => clearTimeout(timer)
    }, [selectedAccount, startDate, endDate, currentBranch])

    const selectedAccountData = accounts.find(a => String(a.id) === String(selectedAccount))

    // Calculate running balance (backend already computes it, but re-compute for display)
    let runningBalance = openingBalance
    const entriesWithBalance = entries.map(entry => {
        const debit = parseFloat(entry.debit || 0)
        const credit = parseFloat(entry.credit || 0)
        if (selectedAccountData && ['asset', 'expense'].includes(selectedAccountData.account_type)) {
            runningBalance += debit - credit
        } else {
            runningBalance += credit - debit
        }
        return { ...entry, running_balance: runningBalance }
    })

    const totalDebit = entries.reduce((sum, e) => sum + parseFloat(e.debit || 0), 0)
    const totalCredit = entries.reduce((sum, e) => sum + parseFloat(e.credit || 0), 0)

    return (
        <div className="workspace fade-in">
            <div className="workspace-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <BackButton />
                <div>
                    <h1 className="workspace-title">📚 {t('accounting.general_ledger.title')}</h1>
                    <p className="workspace-subtitle">{t('accounting.general_ledger.subtitle')}</p>
                </div>
                <div>
                    <button className="btn btn-secondary" onClick={() => window.print()}>
                        {t('common.print')}
                    </button>
                </div>
            </div>

            {/* Filters */}
            <div className="card mt-3 p-4">
                <h5 style={{ fontWeight: 600, marginBottom: '1rem' }}>🔍 {t('accounting.general_ledger.select_account')}</h5>
                <div style={{ display: 'flex', gap: '1rem', alignItems: 'flex-end', flexWrap: 'wrap' }}>
                    <div style={{ minWidth: '280px', flex: 1 }}>
                        <label className="form-label">{t('accounting.general_ledger.select_account')}</label>
                        {loadingAccounts ? (
                            <select className="form-input" disabled>
                                <option>{t('common.loading')}...</option>
                            </select>
                        ) : (
                            <select
                                className="form-input"
                                value={selectedAccount}
                                onChange={(e) => setSelectedAccount(e.target.value)}
                            >
                                <option value="">{t('accounting.general_ledger.choose_account')}</option>
                                {accounts.map(acc => (
                                    <option key={acc.id} value={acc.id}>
                                        {acc.account_number} - {i18n.language === 'en' && acc.name_en ? acc.name_en : acc.name}
                                    </option>
                                ))}
                            </select>
                        )}
                    </div>
                    <div style={{ width: '200px' }}>
                        <CustomDatePicker
                            label={t('common.start_date')}
                            selected={startDate}
                            onChange={(dateStr) => setStartDate(dateStr ? new Date(dateStr) : new Date(new Date().getFullYear(), 0, 1))}
                        />
                    </div>
                    <div style={{ width: '200px' }}>
                        <CustomDatePicker
                            label={t('common.end_date')}
                            selected={endDate}
                            onChange={(dateStr) => setEndDate(dateStr ? new Date(dateStr) : new Date())}
                        />
                    </div>
                </div>
            </div>

            {!selectedAccount ? (
                <div className="card mt-3">
                    <div style={{ textAlign: 'center', padding: '3rem 1rem', color: 'var(--text-secondary)' }}>
                        <div style={{ fontSize: '3rem', marginBottom: '16px' }}>📚</div>
                        <p style={{ fontSize: '1.1rem' }}>{t('accounting.general_ledger.select_account_prompt')}</p>
                    </div>
                </div>
            ) : loading && !initialLoad ? (
                <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>
            ) : loading ? (
                <PageLoading />
            ) : error ? (
                <div className="card mt-3 p-3" style={{ background: '#FEF2F2', color: '#DC2626', borderRadius: '12px' }}>{error}</div>
            ) : (
                <>
                    {/* Account Info & Summary */}
                    {selectedAccountData && (
                        <div className="metrics-grid mt-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
                            <div className="metric-card">
                                <div className="metric-label">{t('accounting.general_ledger.account')}</div>
                                <div className="metric-value" style={{ fontSize: '1rem' }}>
                                    {selectedAccountData.account_number} - {i18n.language === 'en' && selectedAccountData.name_en ? selectedAccountData.name_en : selectedAccountData.name}
                                </div>
                            </div>
                            <div className="metric-card">
                                <div className="metric-label">{t('accounting.general_ledger.total_debit')}</div>
                                <div className="metric-value text-primary">{formatNumber(totalDebit)} <small>{currency}</small></div>
                            </div>
                            <div className="metric-card">
                                <div className="metric-label">{t('accounting.general_ledger.total_credit')}</div>
                                <div className="metric-value text-secondary">{formatNumber(totalCredit)} <small>{currency}</small></div>
                            </div>
                            <div className="metric-card">
                                <div className="metric-label">{t('accounting.general_ledger.net_balance')}</div>
                                <div className={`metric-value ${runningBalance >= 0 ? 'text-success' : 'text-error'}`}>
                                    {formatNumber(Math.abs(runningBalance))} <small>{currency}</small>
                                    <small style={{ fontSize: '0.7em', marginRight: '4px' }}>
                                        {runningBalance >= 0 ? t('accounting.table.debit') : t('accounting.table.credit')}
                                    </small>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Aggregation banner */}
                    {isAggregated && (
                        <div className="mt-2 p-3" style={{ background: '#EFF6FF', border: '1px solid #BFDBFE', borderRadius: '10px', color: '#1D4ED8', fontSize: '0.9rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span style={{ fontSize: '1.2rem' }}>🗂️</span>
                            <span>
                                {i18n.language === 'ar'
                                    ? `يعرض هذا التقرير حركات حساب "${selectedAccountData?.name}" مع ${childCount} حساب فرعي`
                                    : `Showing transactions for "${selectedAccountData?.name_en || selectedAccountData?.name}" and ${childCount} sub-account(s)`}
                            </span>
                        </div>
                    )}

                    {/* Entries Table */}
                    <div className="card mt-3">
                        <div className="data-table-container">
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th style={{ width: '120px' }}>{t('accounting.general_ledger.date')}</th>
                                        <th style={{ width: '130px' }}>{t('accounting.general_ledger.entry_number')}</th>
                                        <th>{t('accounting.general_ledger.description')}</th>
                                        {isAggregated && <th style={{ width: '200px' }}>{t('accounting.general_ledger.account', 'الحساب')}</th>}
                                        <th style={{ width: '120px' }}>{t('accounting.general_ledger.reference')}</th>
                                        <th style={{ textAlign: 'left', width: '140px' }}>{t('accounting.table.debit')}</th>
                                        <th style={{ textAlign: 'left', width: '140px' }}>{t('accounting.table.credit')}</th>
                                        <th style={{ textAlign: 'left', width: '150px' }}>{t('accounting.general_ledger.balance')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {entriesWithBalance.length === 0 ? (
                                        <tr>
                                            <td colSpan={isAggregated ? 8 : 7} style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-secondary)' }}>
                                                {t('accounting.general_ledger.no_entries')}
                                            </td>
                                        </tr>
                                    ) : (
                                        entriesWithBalance.map((entry, idx) => (
                                            <tr key={idx} className="hover-row">
                                                <td className="font-mono" style={{ whiteSpace: 'nowrap' }}>{formatDate(entry.entry_date)}</td>
                                                <td className="font-mono" style={{ whiteSpace: 'nowrap' }}>{entry.entry_number}</td>
                                                <td style={{ maxWidth: '280px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{entry.description}</td>
                                                {isAggregated && <td style={{ fontSize: '12px', color: 'var(--text-secondary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '200px' }}>{entry.account_name || '-'}</td>}
                                                <td style={{ color: entry.reference ? 'var(--text-primary)' : 'var(--text-light)' }}>{entry.reference || '-'}</td>
                                                <td style={{ textAlign: 'left', fontWeight: parseFloat(entry.debit) > 0 ? '600' : '400', color: parseFloat(entry.debit) > 0 ? 'var(--text-primary)' : 'var(--text-light)' }}>
                                                    {parseFloat(entry.debit) > 0 ? formatNumber(entry.debit) : '-'}
                                                </td>
                                                <td style={{ textAlign: 'left', fontWeight: parseFloat(entry.credit) > 0 ? '600' : '400', color: parseFloat(entry.credit) > 0 ? 'var(--text-primary)' : 'var(--text-light)' }}>
                                                    {parseFloat(entry.credit) > 0 ? formatNumber(entry.credit) : '-'}
                                                </td>
                                                <td style={{ textAlign: 'left', fontWeight: 'bold', color: entry.running_balance >= 0 ? 'var(--text-primary)' : '#DC2626' }}>
                                                    {formatNumber(Math.abs(entry.running_balance))}
                                                    <small style={{ opacity: 0.6, marginInlineStart: '4px' }}>
                                                        {entry.running_balance >= 0 ? t('accounting.table.debit') : t('accounting.table.credit')}
                                                    </small>
                                                </td>
                                            </tr>
                                        ))
                                    )}
                                </tbody>
                                {entriesWithBalance.length > 0 && (
                                    <tfoot>
                                        <tr style={{ background: 'var(--primary)', color: 'white', fontWeight: 'bold', fontSize: '1.05em' }}>
                                            <td colSpan={isAggregated ? 5 : 4} style={{ textAlign: 'center' }}>{t('accounting.general_ledger.totals')}</td>
                                            <td style={{ textAlign: 'left' }}>{formatNumber(totalDebit)} <small>{currency}</small></td>
                                            <td style={{ textAlign: 'left' }}>{formatNumber(totalCredit)} <small>{currency}</small></td>
                                            <td style={{ textAlign: 'left' }}>
                                                {formatNumber(Math.abs(runningBalance))} <small>{currency}</small>
                                            </td>
                                        </tr>
                                    </tfoot>
                                )}
                            </table>
                        </div>
                    </div>
                </>
            )}
        </div>
    )
}

export default GeneralLedger
