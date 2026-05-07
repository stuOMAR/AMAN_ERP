import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { accountingAPI } from '../../utils/api'
import { useToast } from '../../context/ToastContext'
import { useBranch } from '../../context/BranchContext'
import { formatNumber } from '../../utils/format'
import { getCurrency } from '../../utils/auth'

import DateInput from '../../components/common/DateInput';
import { formatDate, formatShortDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';

function FiscalYears() {
    const { t, i18n } = useTranslation()
    const { showToast } = useToast()
    const currency = getCurrency()
    const { currentBranch } = useBranch()
    const isRTL = i18n.language === 'ar'

    const [fiscalYears, setFiscalYears] = useState([])
    const [loading, setLoading] = useState(true)
    const [showCreateModal, setShowCreateModal] = useState(false)
    const [showPreviewModal, setShowPreviewModal] = useState(false)
    const [showPeriodsModal, setShowPeriodsModal] = useState(false)
    const [showReopenModal, setShowReopenModal] = useState(false)
    const [selectedYear, setSelectedYear] = useState(null)
    const [preview, setPreview] = useState(null)
    const [periods, setPeriods] = useState([])
    const [previewLoading, setPreviewLoading] = useState(false)
    const [actionLoading, setActionLoading] = useState(false)
    const [reopenReason, setReopenReason] = useState('')

    // Create form
    const currentYear = new Date().getFullYear()
    const [newYear, setNewYear] = useState({
        year: currentYear,
        start_date: `${currentYear}-01-01`,
        end_date: `${currentYear}-12-31`,
    })

    const fetchFiscalYears = useCallback(async () => {
        try {
            setLoading(true)
            const params = {};
            if (currentBranch?.id) params.branch_id = currentBranch.id;
            const res = await accountingAPI.listFiscalYears(params)
            setFiscalYears(res.data)
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        } finally {
            setLoading(false)
        }
    }, [showToast, currentBranch])

    useEffect(() => { fetchFiscalYears() }, [fetchFiscalYears])

    const handleCreate = async () => {
        try {
            setActionLoading(true)
            await accountingAPI.createFiscalYear(newYear)
            showToast(`تم إنشاء السنة المالية ${newYear.year}`, 'success')
            setShowCreateModal(false)
            fetchFiscalYears()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        } finally {
            setActionLoading(false)
        }
    }

    const handlePreviewClose = async (year) => {
        try {
            setPreviewLoading(true)
            setSelectedYear(year)
            const res = await accountingAPI.previewClosing(year)
            setPreview(res.data)
            setShowPreviewModal(true)
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        } finally {
            setPreviewLoading(false)
        }
    }

    const handleClose = async () => {
        try {
            setActionLoading(true)
            const res = await accountingAPI.closeFiscalYear(selectedYear, { close_periods: true })
            showToast(res.data.message, 'success')
            setShowPreviewModal(false)
            fetchFiscalYears()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        } finally {
            setActionLoading(false)
        }
    }

    const handleReopen = async () => {
        try {
            setActionLoading(true)
            const res = await accountingAPI.reopenFiscalYear(selectedYear, { reason: reopenReason })
            showToast(res.data.message, 'success')
            setShowReopenModal(false)
            setReopenReason('')
            fetchFiscalYears()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        } finally {
            setActionLoading(false)
        }
    }

    const handleShowPeriods = async (year) => {
        try {
            setSelectedYear(year)
            const res = await accountingAPI.listFiscalPeriods(year)
            setPeriods(res.data)
            setShowPeriodsModal(true)
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        }
    }

    const handleTogglePeriod = async (periodId) => {
        try {
            const res = await accountingAPI.togglePeriod(periodId)
            showToast(res.data.message, 'success')
            // Refresh periods
            const updated = await accountingAPI.listFiscalPeriods(selectedYear)
            setPeriods(updated.data)
            fetchFiscalYears()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        }
    }

    return (
        <div className="workspace fade-in">
            <div className="workspace-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <BackButton />
                <div>
                    <h1 className="workspace-title">
                        {t('accounting.fiscal_years.fiscal_years')}
                    </h1>
                    <p className="workspace-subtitle">
                        {t('accounting.fiscal_years.manage_fiscal_years_and_yearend_closing')}
                    </p>
                </div>
                <button className="btn btn-primary" onClick={() => setShowCreateModal(true)}>
                    {t('accounting.fiscal_years.new_fiscal_year')}
                </button>
            </div>

            {/* Fiscal Years Table */}
            <div className="card mt-4">
                <div className="data-table-container">
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>{t('accounting.fiscal_years.year')}</th>
                                <th>{t('accounting.fiscal_years.start_date')}</th>
                                <th>{t('accounting.fiscal_years.end_date')}</th>
                                <th>{t('accounting.fiscal_years.status')}</th>
                                <th>{t('accounting.fiscal_years.periods')}</th>
                                <th>{t('accounting.fiscal_years.retained_earnings')}</th>
                                <th>{t('accounting.fiscal_years.closed_at')}</th>
                                <th>{t('accounting.fiscal_years.actions')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {loading ? (
                                <tr><td colSpan="8" style={{ textAlign: 'center', padding: '2rem' }}>
                                    {t('accounting.fiscal_years.loading')}
                                </td></tr>
                            ) : fiscalYears.length === 0 ? (
                                <tr><td colSpan="8" style={{ textAlign: 'center', padding: '2rem' }}>
                                    {t('accounting.fiscal_years.no_fiscal_years_create_one')}
                                </td></tr>
                            ) : fiscalYears.map(fy => (
                                <tr key={fy.id}>
                                    <td><strong>{fy.year}</strong></td>
                                    <td>{formatDate(fy.start_date)}</td>
                                    <td>{formatDate(fy.end_date)}</td>
                                    <td>
                                        <span className={`badge ${fy.status === 'open' ? 'badge-success' : 'badge-secondary'}`}>
                                            {fy.status === 'open'
                                                ? (t('accounting.fiscal_years.open'))
                                                : (t('accounting.fiscal_years.closed'))}
                                        </span>
                                    </td>
                                    <td>
                                        <span
                                            style={{ cursor: 'pointer', textDecoration: 'underline', color: 'var(--primary)' }}
                                            onClick={() => handleShowPeriods(fy.year)}
                                        >
                                            {fy.closed_period_count}/{fy.period_count}
                                        </span>
                                    </td>
                                    <td>
                                        {fy.retained_earnings_account_number
                                            ? `${fy.retained_earnings_account_number} - ${fy.retained_earnings_account_name}`
                                            : (t('accounting.fiscal_years.not_set'))}
                                    </td>
                                    <td>{fy.closed_at ? formatShortDate(fy.closed_at) : '—'}</td>
                                    <td>
                                        <div style={{ display: 'flex', gap: '0.5rem' }}>
                                            {fy.status === 'open' ? (
                                                <button
                                                    className="btn btn-sm btn-warning"
                                                    onClick={() => handlePreviewClose(fy.year)}
                                                    disabled={previewLoading}
                                                >
                                                    🔒 {t('accounting.fiscal_years.close')}
                                                </button>
                                            ) : (
                                                <button
                                                    className="btn btn-sm btn-outline"
                                                    onClick={() => {
                                                        setSelectedYear(fy.year)
                                                        setShowReopenModal(true)
                                                    }}
                                                >
                                                    🔓 {t('accounting.fiscal_years.reopen')}
                                                </button>
                                            )}
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>

            {/* Create Fiscal Year Modal */}
            {showCreateModal && (
                <div className="modal-overlay" onClick={() => setShowCreateModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '500px' }}>
                        <div className="modal-header">
                            <h3>{t('accounting.fiscal_years.create_fiscal_year')}</h3>
                            <button className="modal-close" onClick={() => setShowCreateModal(false)}>✕</button>
                        </div>
                        <div className="modal-body">
                            <div className="form-group mb-3">
                                <label className="form-label">{t('accounting.fiscal_years.year')}</label>
                                <input type="number" className="form-input"
                                    value={newYear.year}
                                    onChange={e => {
                                        const y = parseInt(e.target.value)
                                        if (!y || isNaN(y)) return
                                        setNewYear({
                                            year: y,
                                            start_date: `${y}-01-01`,
                                            end_date: `${y}-12-31`
                                        })
                                    }}
                                />
                            </div>
                            <div className="form-group mb-3">
                                <label className="form-label">{t('accounting.fiscal_years.start_date')}</label>
                                <DateInput className="form-input"
                                    value={newYear.start_date}
                                    onChange={e => setNewYear({ ...newYear, start_date: e.target.value })}
                                />
                            </div>
                            <div className="form-group mb-3">
                                <label className="form-label">{t('accounting.fiscal_years.end_date')}</label>
                                <DateInput className="form-input"
                                    value={newYear.end_date}
                                    onChange={e => setNewYear({ ...newYear, end_date: e.target.value })}
                                />
                            </div>
                        </div>
                        <div className="modal-footer">
                            <button className="btn btn-secondary" onClick={() => setShowCreateModal(false)}>
                                {t('accounting.fiscal_years.cancel')}
                            </button>
                            <button className="btn btn-primary" onClick={handleCreate} disabled={actionLoading}>
                                {actionLoading ? '...' : (t('accounting.fiscal_years.create'))}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Preview Closing Modal */}
            {showPreviewModal && preview && (
                <div className="modal-overlay" onClick={() => setShowPreviewModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '800px', maxHeight: '80vh', overflow: 'auto' }}>
                        <div className="modal-header">
                            <h3>
                                {isRTL
                                    ? `معاينة إقفال السنة المالية ${selectedYear}`
                                    : `Preview Year-End Closing ${selectedYear}`}
                            </h3>
                            <button className="modal-close" onClick={() => setShowPreviewModal(false)}>✕</button>
                        </div>
                        <div className="modal-body">
                            {/* Summary Cards */}
                            <div className="modules-grid" style={{ gap: '1rem', marginBottom: '1.5rem' }}>
                                <div className="card" style={{ padding: '1rem', textAlign: 'center', background: 'var(--success-bg, #d4edda)' }}>
                                    <div style={{ fontSize: '0.85rem', color: '#666' }}>
                                        {t('accounting.fiscal_years.total_revenue')}
                                    </div>
                                    <div style={{ fontSize: '1.3rem', fontWeight: 'bold', color: 'var(--success, #28a745)' }}>
                                        {formatNumber(preview.total_revenue)} {currency}
                                    </div>
                                </div>
                                <div className="card" style={{ padding: '1rem', textAlign: 'center', background: 'var(--danger-bg, #f8d7da)' }}>
                                    <div style={{ fontSize: '0.85rem', color: '#666' }}>
                                        {t('accounting.fiscal_years.total_expenses')}
                                    </div>
                                    <div style={{ fontSize: '1.3rem', fontWeight: 'bold', color: 'var(--danger, #dc3545)' }}>
                                        {formatNumber(preview.total_expenses)} {currency}
                                    </div>
                                </div>
                                <div className="card" style={{
                                    padding: '1rem', textAlign: 'center',
                                    background: preview.net_income >= 0 ? 'var(--success-bg, #d4edda)' : 'var(--danger-bg, #f8d7da)'
                                }}>
                                    <div style={{ fontSize: '0.85rem', color: '#666' }}>
                                        {isRTL
                                            ? (preview.net_income >= 0 ? t('common.net_profit') : t('common.net_loss'))
                                            : (preview.net_income >= 0 ? 'Net Profit' : 'Net Loss')}
                                    </div>
                                    <div style={{
                                        fontSize: '1.3rem', fontWeight: 'bold',
                                        color: preview.net_income >= 0 ? 'var(--success, #28a745)' : 'var(--danger, #dc3545)'
                                    }}>
                                        {formatNumber(Math.abs(preview.net_income))} {currency}
                                    </div>
                                </div>
                            </div>

                            {/* Retained Earnings Account */}
                            {preview.retained_earnings_account && (
                                <div className="alert alert-info mb-3" style={{ padding: '0.75rem' }}>
                                    {t('accounting.fiscal_years.result_will_be_posted_to')}
                                    <strong>
                                        {preview.retained_earnings_account.account_number} - {preview.retained_earnings_account.name}
                                    </strong>
                                </div>
                            )}

                            {/* Revenue Accounts */}
                            {preview.revenue_accounts.length > 0 && (
                                <>
                                    <h4 style={{ margin: '1rem 0 0.5rem' }}>
                                        {t('accounting.fiscal_years.revenue_accounts')}
                                    </h4>
                                    <table className="data-table" style={{ fontSize: '0.85rem' }}>
                                        <thead>
                                            <tr>
                                                <th>{t('accounting.fiscal_years.account')}</th>
                                                <th>{t('accounting.fiscal_years.account_name')}</th>
                                                <th>{t('accounting.fiscal_years.balance')}</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {preview.revenue_accounts.map(acc => (
                                                <tr key={acc.id}>
                                                    <td>{acc.account_number}</td>
                                                    <td>{isRTL ? acc.name : (acc.name_en || acc.name)}</td>
                                                    <td style={{ color: 'var(--success, #28a745)' }}>
                                                        {formatNumber(acc.balance)} {currency}
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </>
                            )}

                            {/* Expense Accounts */}
                            {preview.expense_accounts.length > 0 && (
                                <>
                                    <h4 style={{ margin: '1rem 0 0.5rem' }}>
                                        {t('accounting.fiscal_years.expense_accounts')}
                                    </h4>
                                    <table className="data-table" style={{ fontSize: '0.85rem' }}>
                                        <thead>
                                            <tr>
                                                <th>{t('accounting.fiscal_years.account')}</th>
                                                <th>{t('accounting.fiscal_years.account_name')}</th>
                                                <th>{t('accounting.fiscal_years.balance')}</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {preview.expense_accounts.map(acc => (
                                                <tr key={acc.id}>
                                                    <td>{acc.account_number}</td>
                                                    <td>{isRTL ? acc.name : (acc.name_en || acc.name)}</td>
                                                    <td style={{ color: 'var(--danger, #dc3545)' }}>
                                                        {formatNumber(acc.balance)} {currency}
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </>
                            )}

                            {/* Warning */}
                            <div className="alert alert-warning mt-3" style={{ padding: '0.75rem' }}>
                                ⚠️ {t('accounting.fiscal_years.a_closing_entry_will_be_created_that_zeros_revenue')}
                            </div>
                        </div>
                        <div className="modal-footer">
                            <button className="btn btn-secondary" onClick={() => setShowPreviewModal(false)}>
                                {t('accounting.fiscal_years.cancel')}
                            </button>
                            <button className="btn btn-danger" onClick={handleClose} disabled={actionLoading}>
                                {actionLoading ? '...' : (t('accounting.fiscal_years.confirm_close'))}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Periods Modal */}
            {showPeriodsModal && (
                <div className="modal-overlay" onClick={() => setShowPeriodsModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '700px' }}>
                        <div className="modal-header">
                            <h3>
                                {isRTL
                                    ? `الفترات المحاسبية - ${selectedYear}`
                                    : `Fiscal Periods - ${selectedYear}`}
                            </h3>
                            <button className="modal-close" onClick={() => setShowPeriodsModal(false)}>✕</button>
                        </div>
                        <div className="modal-body">
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>{t('accounting.fiscal_years.period')}</th>
                                        <th>{t('accounting.fiscal_years.from')}</th>
                                        <th>{t('accounting.fiscal_years.to')}</th>
                                        <th>{t('accounting.fiscal_years.entries')}</th>
                                        <th>{t('accounting.fiscal_years.status')}</th>
                                        <th>{t('accounting.fiscal_years.action')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {periods.map(p => (
                                        <tr key={p.id}>
                                            <td>{p.name}</td>
                                            <td>{formatDate(p.start_date)}</td>
                                            <td>{formatDate(p.end_date)}</td>
                                            <td>{p.entry_count}</td>
                                            <td>
                                                <span className={`badge ${p.is_closed ? 'badge-secondary' : 'badge-success'}`}>
                                                    {p.is_closed
                                                        ? (t('accounting.fiscal_years.closed_2'))
                                                        : (t('accounting.fiscal_years.open'))}
                                                </span>
                                            </td>
                                            <td>
                                                <button
                                                    className={`btn btn-sm ${p.is_closed ? 'btn-outline' : 'btn-warning'}`}
                                                    onClick={() => handleTogglePeriod(p.id)}
                                                >
                                                    {p.is_closed
                                                        ? (t('accounting.fiscal_years.open_2'))
                                                        : (t('accounting.fiscal_years.close_2'))}
                                                </button>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                        <div className="modal-footer">
                            <button className="btn btn-secondary" onClick={() => setShowPeriodsModal(false)}>
                                {t('accounting.fiscal_years.close_2')}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Reopen Modal */}
            {showReopenModal && (
                <div className="modal-overlay" onClick={() => setShowReopenModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '500px' }}>
                        <div className="modal-header">
                            <h3>
                                {isRTL
                                    ? `إعادة فتح السنة المالية ${selectedYear}`
                                    : `Reopen Fiscal Year ${selectedYear}`}
                            </h3>
                            <button className="modal-close" onClick={() => setShowReopenModal(false)}>✕</button>
                        </div>
                        <div className="modal-body">
                            <div className="alert alert-warning" style={{ padding: '0.75rem', marginBottom: '1rem' }}>
                                ⚠️ {t('accounting.fiscal_years.the_closing_entry_will_be_reversed_and_all_fiscal_')}
                            </div>
                            <div className="form-group">
                                <label className="form-label">
                                    {t('accounting.fiscal_years.reason_for_reopening_optional')}
                                </label>
                                <textarea
                                    className="form-input"
                                    rows={3}
                                    value={reopenReason}
                                    onChange={e => setReopenReason(e.target.value)}
                                    placeholder={t('accounting.fiscal_years.enter_reason')}
                                />
                            </div>
                        </div>
                        <div className="modal-footer">
                            <button className="btn btn-secondary" onClick={() => setShowReopenModal(false)}>
                                {t('accounting.fiscal_years.cancel')}
                            </button>
                            <button className="btn btn-warning" onClick={handleReopen} disabled={actionLoading}>
                                {actionLoading ? '...' : (t('accounting.fiscal_years.confirm_reopen'))}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}

export default FiscalYears
