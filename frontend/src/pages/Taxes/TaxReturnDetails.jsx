import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { taxesAPI, treasuryAPI } from '../../utils/api'
import { useTranslation } from 'react-i18next'
import { formatNumber } from '../../utils/format'
import { getCurrency } from '../../utils/auth'

import DateInput from '../../components/common/DateInput';
import { formatShortDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';
import { useToast } from '../../context/ToastContext'
import { PageLoading } from '../../components/common/LoadingStates'
import { useBranch } from '../../context/BranchContext'

function TaxReturnDetails() {
    const { t } = useTranslation()
  const { showToast } = useToast()
    const { id } = useParams()
    const navigate = useNavigate()
    const { currentBranch } = useBranch()
    const currency = getCurrency()
    const [loading, setLoading] = useState(true)
    const [data, setData] = useState(null)
    const [error, setError] = useState(null)
    const [showPayModal, setShowPayModal] = useState(false)
    const [payForm, setPayForm] = useState({ amount: 0, payment_date: new Date().toISOString().split('T')[0], payment_method: 'bank_transfer', reference: '', notes: '' })
    const [showFileModal, setShowFileModal] = useState(false)
    const [fileForm, setFileForm] = useState({ penalty_amount: 0, interest_amount: 0 })
    const [actionLoading, setActionLoading] = useState(false)
    const [treasuryAccounts, setTreasuryAccounts] = useState([])

    const fetchData = async () => {
        try {
            setLoading(true)
            const res = await taxesAPI.getReturn(id)
            setData(res.data)
            setPayForm(prev => ({ ...prev, amount: res.data.remaining_amount || 0 }))
        } catch (err) {
            setError(err.response?.data?.detail || t('common.error_loading_data'))
        } finally {
            setLoading(false)
        }
    }

    const fetchTreasury = async () => {
        try {
            const res = await treasuryAPI.listAccounts(currentBranch?.id)
            setTreasuryAccounts(res.data || [])
        } catch (e) { /* ignore */ }
    }

    useEffect(() => {
        fetchData()
        fetchTreasury()
    }, [id, currentBranch?.id])

    const handleFile = async () => {
        setActionLoading(true)
        try {
            await taxesAPI.fileReturn(id, fileForm)
            setShowFileModal(false)
            fetchData()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error', 'error'))
        } finally {
            setActionLoading(false)
        }
    }

    const handleCancel = async () => {
        if (!confirm(t('taxes.confirm_cancel'))) return
        setActionLoading(true)
        try {
            await taxesAPI.cancelReturn(id)
            fetchData()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error', 'error'))
        } finally {
            setActionLoading(false)
        }
    }

    const handlePay = async () => {
        setActionLoading(true)
        try {
            await taxesAPI.createPayment({
                tax_return_id: parseInt(id),
                payment_date: payForm.payment_date,
                amount: parseFloat(payForm.amount),
                payment_method: payForm.payment_method,
                reference: payForm.reference || null,
                notes: payForm.notes || null,
                treasury_account_id: payForm.treasury_account_id ? parseInt(payForm.treasury_account_id) : null
            })
            setShowPayModal(false)
            fetchData()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error', 'error'))
        } finally {
            setActionLoading(false)
        }
    }

    const getStatusBadge = (status) => {
        const map = {
            draft: { label: t('taxes.status_draft'), bg: 'rgb(254, 243, 199)', color: 'rgb(217, 119, 6)', emoji: '⏳' },
            filed: { label: t('taxes.status_filed'), bg: 'rgba(59, 130, 246, 0.1)', color: 'rgb(59, 130, 246)', emoji: '📤' },
            paid: { label: t('taxes.status_paid'), bg: 'rgb(220, 252, 231)', color: 'rgb(22, 163, 74)', emoji: '✅' },
            cancelled: { label: t('taxes.status_cancelled'), bg: 'rgb(254, 226, 226)', color: 'rgb(220, 38, 38)', emoji: '❌' }
        }
        const s = map[status] || { label: status, bg: 'rgba(107, 114, 128, 0.082)', color: 'rgb(107, 114, 128)', emoji: '' }
        return <span style={{ background: s.bg, color: s.color, padding: '6px 16px', borderRadius: '20px', fontSize: '14px', fontWeight: '600', whiteSpace: 'nowrap' }}>
            {s.emoji} {s.label}
        </span>
    }

    const paymentMethodLabel = (method) => {
        const map = { bank_transfer: t('taxes.bank_transfer'), cash: t('taxes.cash'), cheque: t('taxes.cheque') }
        return map[method] || method
    }

    if (loading) return <PageLoading />
    if (error) return <div className="alert alert-danger m-4">{error}</div>
    if (!data) return null

    return (
        <div className="workspace fade-in">
            {/* Header */}
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
                    <div>
                        <h1 className="workspace-title">📋 {t('taxes.return_details')}</h1>
                        <p className="workspace-subtitle" style={{ fontFamily: 'monospace', fontSize: '16px' }}>
                            {data.return_number} — {t('taxes.period')}: {data.tax_period}
                        </p>
                    </div>
                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                        {getStatusBadge(data.status)}
                        {data.status === 'draft' && (
                            <>
                                <button className="btn btn-primary" onClick={() => setShowFileModal(true)} disabled={actionLoading}>
                                    📤 {t('taxes.file_return')}
                                </button>
                                <button className="btn btn-danger" onClick={handleCancel} disabled={actionLoading}>
                                    ❌ {t('common.cancel')}
                                </button>
                            </>
                        )}
                        {data.status === 'filed' && data.remaining_amount > 0 && (
                            <>
                                <button className="btn btn-success" onClick={() => setShowPayModal(true)} disabled={actionLoading}>
                                    💰 {t('taxes.record_payment')}
                                </button>
                                <button className="btn btn-danger" onClick={handleCancel} disabled={actionLoading}>
                                    ❌ {t('common.cancel')}
                                </button>
                            </>
                        )}
                        <button className="btn btn-secondary" onClick={() => navigate('/taxes')}>
                            ← {t('common.back')}
                        </button>
                    </div>
                </div>
            </div>

            {/* Summary Cards */}
            <div className="metrics-grid mt-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
                <div className="metric-card">
                    <div className="metric-label">{t('taxes.taxable_amount')}</div>
                    <div className="metric-value">{formatNumber(data.taxable_amount)} <small>{currency}</small></div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('taxes.tax_amount')}</div>
                    <div className="metric-value text-secondary">{formatNumber(data.tax_amount)} <small>{currency}</small></div>
                </div>
                {(data.penalty_amount > 0 || data.interest_amount > 0) && (
                    <div className="metric-card">
                        <div className="metric-label">{t('taxes.penalties')}</div>
                        <div className="metric-value text-error">{formatNumber(parseFloat(data.penalty_amount || 0) + parseFloat(data.interest_amount || 0))} <small>{currency}</small></div>
                    </div>
                )}
                <div className="metric-card" style={{ borderColor: 'var(--primary)' }}>
                    <div className="metric-label" style={{ fontWeight: 'bold' }}>{t('taxes.total_amount')}</div>
                    <div className="metric-value text-primary" style={{ fontSize: '28px' }}>{formatNumber(data.total_amount)} <small>{currency}</small></div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('taxes.paid_amount')}</div>
                    <div className="metric-value text-success">{formatNumber(data.paid_amount)} <small>{currency}</small></div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('taxes.remaining')}</div>
                    <div className={`metric-value ${data.remaining_amount > 0 ? 'text-error' : 'text-success'}`}>
                        {formatNumber(data.remaining_amount)} <small>{currency}</small>
                    </div>
                </div>
            </div>

            {/* Info Card */}
            <div className="card mt-4">
                <h3 className="section-title">{t('taxes.return_info')}</h3>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', marginTop: '12px' }}>
                    <div><strong>{t('taxes.return_number')}:</strong> <span style={{ fontFamily: 'monospace' }}>{data.return_number}</span></div>
                    <div><strong>{t('taxes.period')}:</strong> {data.tax_period}</div>
                    <div><strong>{t('taxes.tax_type')}:</strong> {data.tax_type === 'vat' ? 'ضريبة القيمة المضافة' : data.tax_type}</div>
                    <div><strong>{t('taxes.due_date')}:</strong> {data.due_date || '-'}</div>
                    <div><strong>{t('taxes.filed_date')}:</strong> {data.filed_date || '-'}</div>
                    <div><strong>{t('taxes.created_by')}:</strong> {data.created_by_name || '-'}</div>
                    {data.notes && <div style={{ gridColumn: 'span 2' }}><strong>{t('taxes.notes')}:</strong> {data.notes}</div>}
                </div>
            </div>

            {/* Payments Table */}
            <div className="card mt-4">
                <h3 className="section-title">{t('taxes.payments')}</h3>
                {data.payments && data.payments.length > 0 ? (
                    <div className="data-table-container mt-3">
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th>{t('taxes.payment_number')}</th>
                                    <th>{t('common.date')}</th>
                                    <th style={{ textAlign: 'left' }}>{t('taxes.amount')}</th>
                                    <th>{t('taxes.payment_method')}</th>
                                    <th>{t('taxes.reference')}</th>
                                    <th>{t('common.status_title')}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {data.payments.map(p => (
                                    <tr key={p.id}>
                                        <td>
                                            <span className="fw-bold" style={{ color: 'var(--primary)', fontFamily: 'monospace' }}>{p.payment_number}</span>
                                        </td>
                                        <td style={{ whiteSpace: 'nowrap' }}>{formatShortDate(p.payment_date)}</td>
                                        <td style={{ textAlign: 'left', fontWeight: '700', whiteSpace: 'nowrap' }}>
                                            {formatNumber(p.amount)} <span className="text-muted fw-normal small">{currency}</span>
                                        </td>
                                        <td>
                                            <span style={{ background: 'rgba(107, 114, 128, 0.082)', color: 'rgb(107, 114, 128)', padding: '4px 10px', borderRadius: '6px', fontSize: '12px', fontWeight: '600' }}>
                                                {paymentMethodLabel(p.payment_method)}
                                            </span>
                                        </td>
                                        <td>{p.reference || <span className="text-muted">—</span>}</td>
                                        <td>
                                            <span style={{ background: 'rgb(220, 252, 231)', color: 'rgb(22, 163, 74)', padding: '4px 12px', borderRadius: '20px', fontSize: '12px', fontWeight: '600', whiteSpace: 'nowrap' }}>
                                                ✅ {p.status === 'confirmed' ? (t('taxes.confirmed')) : p.status}
                                            </span>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                ) : (
                    <p className="text-muted mt-3">{t('taxes.no_payments')}</p>
                )}
            </div>

            {/* File Modal */}
            {showFileModal && (
                <div className="modal-backdrop" onClick={() => setShowFileModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '450px' }}>
                        <div className="modal-header">
                            <h3>📤 {t('taxes.file_return')}</h3>
                            <button className="btn-close" onClick={() => setShowFileModal(false)}>✕</button>
                        </div>
                        <div className="modal-body">
                            <p>{t('taxes.file_confirm_msg')}</p>
                            <div className="form-group mt-3">
                                <label className="form-label">{t('taxes.penalty_amount')}</label>
                                <input type="number" className="form-input" min="0" step="0.01"
                                    value={fileForm.penalty_amount}
                                    onChange={e => setFileForm({...fileForm, penalty_amount: parseFloat(e.target.value) || 0})} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('taxes.interest_amount')}</label>
                                <input type="number" className="form-input" min="0" step="0.01"
                                    value={fileForm.interest_amount}
                                    onChange={e => setFileForm({...fileForm, interest_amount: parseFloat(e.target.value) || 0})} />
                            </div>
                            <div className="alert alert-info mt-2">
                                {t('taxes.new_total')}: <strong>{formatNumber(parseFloat(data.tax_amount || 0) + (fileForm.penalty_amount || 0) + (fileForm.interest_amount || 0))} {currency}</strong>
                            </div>
                        </div>
                        <div className="modal-footer">
                            <button className="btn btn-secondary" onClick={() => setShowFileModal(false)}>{t('common.cancel')}</button>
                            <button className="btn btn-primary" onClick={handleFile} disabled={actionLoading}>
                                {actionLoading ? '...' : (t('taxes.submit'))}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Payment Modal */}
            {showPayModal && (
                <div className="modal-backdrop" onClick={() => setShowPayModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '500px' }}>
                        <div className="modal-header">
                            <h3>💰 {t('taxes.record_payment')}</h3>
                            <button className="btn-close" onClick={() => setShowPayModal(false)}>✕</button>
                        </div>
                        <div className="modal-body">
                            <div className="alert alert-info">
                                {t('taxes.remaining')}: <strong>{formatNumber(data.remaining_amount)} {currency}</strong>
                            </div>
                            <div className="form-group mt-3">
                                <label className="form-label">{t('taxes.amount')} *</label>
                                <input type="number" className="form-input" min="0.01" step="0.01"
                                    max={data.remaining_amount}
                                    value={payForm.amount}
                                    onChange={e => setPayForm({...payForm, amount: parseFloat(e.target.value) || 0})} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('taxes.payment_date')} *</label>
                                <DateInput className="form-input" value={payForm.payment_date}
                                    onChange={e => setPayForm({...payForm, payment_date: e.target.value})} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('taxes.payment_method')}</label>
                                <select className="form-input" value={payForm.payment_method}
                                    onChange={e => setPayForm({...payForm, payment_method: e.target.value})}>
                                    <option value="bank_transfer">{t('taxes.bank_transfer')}</option>
                                    <option value="cash">{t('taxes.cash')}</option>
                                    <option value="cheque">{t('taxes.cheque')}</option>
                                </select>
                            </div>
                            {treasuryAccounts.length > 0 && (
                                <div className="form-group">
                                    <label className="form-label">{t('taxes.treasury_account')}</label>
                                    <select className="form-input" value={payForm.treasury_account_id || ''}
                                        onChange={e => setPayForm({...payForm, treasury_account_id: e.target.value})}>
                                        <option value="">{t('taxes.auto_select')}</option>
                                        {treasuryAccounts.map(ta => (
                                            <option key={ta.id} value={ta.id}>{ta.name} ({ta.currency})</option>
                                        ))}
                                    </select>
                                </div>
                            )}
                            <div className="form-group">
                                <label className="form-label">{t('taxes.reference')}</label>
                                <input className="form-input" value={payForm.reference}
                                    onChange={e => setPayForm({...payForm, reference: e.target.value})}
                                    placeholder={t('taxes.ref_placeholder')} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('taxes.notes')}</label>
                                <textarea className="form-input" rows="2" value={payForm.notes}
                                    onChange={e => setPayForm({...payForm, notes: e.target.value})} />
                            </div>
                        </div>
                        <div className="modal-footer">
                            <button className="btn btn-secondary" onClick={() => setShowPayModal(false)}>{t('common.cancel')}</button>
                            <button className="btn btn-success" onClick={handlePay} disabled={actionLoading || payForm.amount <= 0}>
                                {actionLoading ? '...' : (t('taxes.confirm_payment'))}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}

export default TaxReturnDetails
