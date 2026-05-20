import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { accountingAPI } from '../../utils/api'
import { useToast } from '../../context/ToastContext'
import { useBranch } from '../../context/BranchContext'
import { getCurrency } from '../../utils/auth'
import { formatNumber } from '../../utils/format'
import { TrendingUp, TrendingDown, DollarSign, AlertTriangle } from 'lucide-react'
import CustomDatePicker from '../../components/common/CustomDatePicker'
import BackButton from '../../components/common/BackButton';

export default function ClosingEntries() {
    const { t, i18n } = useTranslation()
    const { showToast } = useToast()
    const { currentBranch } = useBranch()
    const currency = getCurrency()

    const now = new Date()
    const [startDate, setStartDate] = useState(`${now.getFullYear()}-01-01`)
    const [endDate, setEndDate] = useState(now.toISOString().slice(0, 10))
    const [loading, setLoading] = useState(false)
    const [initialLoad, setInitialLoad] = useState(true)
    const [generating, setGenerating] = useState(false)
    const [preview, setPreview] = useState(null)
    const [useIncomeSummary, setUseIncomeSummary] = useState(false)
    const [result, setResult] = useState(null)

    const fetchPreview = async () => {
        setLoading(true)
        setResult(null)
        try {
            const params = { start_date: startDate, end_date: endDate };
            if (currentBranch?.id) params.branch_id = currentBranch.id;
            const res = await accountingAPI.previewClosingEntries(params)
            setPreview(res.data)
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        } finally {
            setLoading(false)
        }
    }

    const handleGenerate = async () => {
        if (!confirm(t('closing.confirm_generate')))
            return
        setGenerating(true)
        try {
            const payload = {
                start_date: startDate,
                end_date: endDate,
                entry_date: endDate,
                use_income_summary: useIncomeSummary,
                income_summary_account_id: preview?.income_summary_account?.id,
                retained_earnings_account_id: preview?.retained_earnings_account?.id,
            }
            if (currentBranch?.id) payload.branch_id = currentBranch.id;
            const res = await accountingAPI.generateClosingEntries(payload)
            setResult(res.data)
            showToast(res.data.message || (t('closing.generated')), 'success')
            setPreview(null)
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        } finally {
            setGenerating(false)
        }
    }

    const formatNum = (n) => {
        if (!n && n !== 0) return '-'
        return formatNumber(n)
    }

    return (
        <div className="workspace fade-in" dir={i18n.dir()}>
            <div className="workspace-header">
                <BackButton />
                <div>
                    <h1 className="workspace-title">🔒 {t('closing.title')}</h1>
                    <p className="workspace-subtitle">
                        {t('closing.subtitle')}
                    </p>
                </div>
            </div>

            {/* Period Selection */}
            <div className="card mb-4">
                <div >
                    <h5 className="fw-bold mb-3">📅 {t('closing.select_period')}</h5>
                    <div className="row g-3">
                        <div className="col-md-4">
                            <CustomDatePicker
                                label={t('closing.start_date')}
                                selected={startDate}
                                onChange={(dateStr) => setStartDate(dateStr)}
                            />
                        </div>
                        <div className="col-md-4">
                            <CustomDatePicker
                                label={t('closing.end_date')}
                                selected={endDate}
                                onChange={(dateStr) => setEndDate(dateStr)}
                            />
                        </div>
                        <div className="col-md-4">
                            <label className="form-label" style={{ opacity: 0 }}>.</label>
                            <button className="btn btn-primary w-100" onClick={fetchPreview} disabled={loading}>
                                {loading ? '⏳' : '🔍'} {t('closing.preview')}
                            </button>
                        </div>
                    </div>
                    <div className="mt-3">
                        <div className="form-check">
                            <input type="checkbox" className="form-check-input" id="useIS"
                                checked={useIncomeSummary} onChange={e => setUseIncomeSummary(e.target.checked)} />
                            <label className="form-check-label" htmlFor="useIS">
                                {t('closing.use_income_summary')}
                            </label>
                        </div>
                    </div>
                </div>
            </div>

            {/* Result of generation */}
            {result && (
                <div className="card mb-4" style={{ borderLeft: '4px solid #10b981' }}>
                    <div >
                        <h5 className="fw-bold text-success mb-3">✅ {result.message}</h5>
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', marginBottom: '16px' }}>
                            <div className="p-3 bg-light rounded text-center">
                                <div className="small text-muted">{t('closing.total_revenue')}</div>
                                <div className="fw-bold text-success fs-5">{formatNum(result.total_revenue)} <small>{currency}</small></div>
                            </div>
                            <div className="p-3 bg-light rounded text-center">
                                <div className="small text-muted">{t('closing.total_expenses')}</div>
                                <div className="fw-bold text-danger fs-5">{formatNum(result.total_expense)} <small>{currency}</small></div>
                            </div>
                            <div className="p-3 bg-light rounded text-center">
                                <div className="small text-muted">{t('closing.net_income')}</div>
                                <div className={`fw-bold fs-5 ${result.net_income >= 0 ? 'text-success' : 'text-danger'}`}>
                                    {formatNum(result.net_income)} <small>{currency}</small>
                                </div>
                            </div>
                        </div>
                        <div className="mt-3">
                            <strong>{t('closing.generated_entries')}</strong>{' '}
                            <span className="badge bg-primary">{result.entries.map(e => `#${e.number}`).join(', ')}</span>
                        </div>
                    </div>
                </div>
            )}

            {/* Preview */}
            {preview && (
                <>
                    {/* Summary Cards */}
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', marginBottom: '24px' }}>
                        <div className="card p-3 text-center border-success">
                            <TrendingUp size={24} className="text-success mb-2" />
                            <div className="small text-muted">{t('closing.total_revenue')}</div>
                            <div className="fw-bold fs-4 text-success">{formatNum(preview.total_revenue)} <small>{currency}</small></div>
                            <div className="small text-muted">{preview.revenues.length} {t('closing.accounts_count')}</div>
                        </div>
                        <div className="card p-3 text-center border-danger">
                            <TrendingDown size={24} className="text-danger mb-2" />
                            <div className="small text-muted">{t('closing.total_expenses')}</div>
                            <div className="fw-bold fs-4 text-danger">{formatNum(preview.total_expense)} <small>{currency}</small></div>
                            <div className="small text-muted">{preview.expenses.length} {t('closing.accounts_count')}</div>
                        </div>
                        <div className={`card p-3 text-center border-${preview.net_income >= 0 ? 'success' : 'warning'}`}>
                            {preview.net_income >= 0 ? <DollarSign size={24} className="text-success mb-2" /> : <AlertTriangle size={24} className="text-warning mb-2" />}
                            <div className="small text-muted">{t('closing.net_income')}</div>
                            <div className={`fw-bold fs-4 ${preview.net_income >= 0 ? 'text-success' : 'text-warning'}`}>
                                {formatNum(preview.net_income)} <small>{currency}</small>
                            </div>
                            <div className="small text-muted">
                                {preview.net_income >= 0 ? (t('closing.profit')) : (t('closing.loss'))}
                            </div>
                        </div>
                    </div>

                    {/* Target Accounts */}
                    <div className="card mb-4">
                        <div >
                            <h6 className="fw-bold mb-3">🎯 {t('closing.target_accounts')}</h6>
                            <div className="row g-3">
                                <div className="col-md-6">
                                    <label className="form-label small text-muted">{t('closing.retained_earnings')}</label>
                                    <div className="form-input" style={{ background: '#f8f9fa' }}>
                                        {preview.retained_earnings_account
                                            ? `${preview.retained_earnings_account.account_number} - ${preview.retained_earnings_account.name}`
                                            : <span className="text-danger">❌ {t('closing.not_found')}</span>}
                                    </div>
                                </div>
                                {useIncomeSummary && (
                                    <div className="col-md-6">
                                        <label className="form-label small text-muted">{t('closing.income_summary_account')}</label>
                                        <div className="form-input" style={{ background: '#f8f9fa' }}>
                                            {preview.income_summary_account
                                                ? `${preview.income_summary_account.account_number} - ${preview.income_summary_account.name}`
                                                : <span className="text-warning">⚠️ {t('closing.not_found_warning')}</span>}
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>

                    {/* Revenue Accounts Table */}
                    {preview.revenues.length > 0 && (
                        <div className="card mb-4">
                            <div className="card-header bg-success bg-opacity-10 border-0" >
                                <strong className="text-success">📈 {t('closing.revenue_accounts')}</strong>
                            </div>
                            <div className="data-table-container">
                                <table className="data-table mb-0">
                                    <thead>
                                        <tr>
                                            <th>{t('closing.code')}</th>
                                            <th>{t('closing.account')}</th>
                                            <th className="text-end">{t('closing.balance')}</th>
                                            <th className="text-end">{t('closing.debit_close')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {preview.revenues.map(r => (
                                            <tr key={r.id}>
                                                <td className="text-muted small">{r.account_number}</td>
                                                <td>{i18n.language === 'ar' ? r.name : (r.name_en || r.name)}</td>
                                                <td className="text-end text-success">{formatNum(r.balance)}</td>
                                                <td className="text-end">{formatNum(r.balance)}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                    <tfoot className="fw-bold">
                                        <tr>
                                            <td colSpan="2">{t('closing.total')}</td>
                                            <td className="text-end text-success">{formatNum(preview.total_revenue)}</td>
                                            <td className="text-end">{formatNum(preview.total_revenue)}</td>
                                        </tr>
                                    </tfoot>
                                </table>
                            </div>
                        </div>
                    )}

                    {/* Expense Accounts Table */}
                    {preview.expenses.length > 0 && (
                        <div className="card mb-4">
                            <div className="card-header bg-danger bg-opacity-10 border-0" >
                                <strong className="text-danger">📉 {t('closing.expense_accounts')}</strong>
                            </div>
                            <div className="data-table-container">
                                <table className="data-table mb-0">
                                    <thead>
                                        <tr>
                                            <th>{t('closing.code')}</th>
                                            <th>{t('closing.account')}</th>
                                            <th className="text-end">{t('closing.balance')}</th>
                                            <th className="text-end">{t('closing.credit_close')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {preview.expenses.map(e => (
                                            <tr key={e.id}>
                                                <td className="text-muted small">{e.account_number}</td>
                                                <td>{i18n.language === 'ar' ? e.name : (e.name_en || e.name)}</td>
                                                <td className="text-end text-danger">{formatNum(e.balance)}</td>
                                                <td className="text-end">{formatNum(e.balance)}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                    <tfoot className="fw-bold">
                                        <tr>
                                            <td colSpan="2">{t('closing.total')}</td>
                                            <td className="text-end text-danger">{formatNum(preview.total_expense)}</td>
                                            <td className="text-end">{formatNum(preview.total_expense)}</td>
                                        </tr>
                                    </tfoot>
                                </table>
                            </div>
                        </div>
                    )}

                    {/* Generate Button */}
                    <div className="text-center mt-4">
                        <button className="btn btn-danger btn-lg px-5" onClick={handleGenerate}
                            disabled={generating || (!preview.revenues.length && !preview.expenses.length)}
                            style={{ borderRadius: '8px' }}>
                            {generating ? '⏳' : '🔒'}{' '}
                            {t('closing.generate_post')}
                        </button>
                        <p className="text-muted small mt-2">
                            {t('closing.entries_posted_immediately')}
                        </p>
                    </div>
                </>
            )}

            {!preview && !result && !loading && (
                <div className="card text-center p-5">
                    <div style={{ fontSize: '72px', marginBottom: '16px' }}>🔒</div>
                    <h5 className="fw-bold mb-2">{t('closing.title')}</h5>
                    <p className="text-muted">{t('closing.select_period_hint')}</p>
                </div>
            )}
        </div>
    )
}
