import { useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Edit2, RefreshCw, FileText, XCircle, Calendar, DollarSign, User, Clock } from 'lucide-react'
import { contractsAPI } from '../../utils/api'
import { getCurrency } from '../../utils/auth'
import { formatNumber } from '../../utils/format'
import { formatShortDate } from '../../utils/dateUtils'
import { useToast } from '../../context/ToastContext'
import SimpleModal from '../../components/common/SimpleModal'
import '../../components/ModuleStyles.css'
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

export default function ContractDetails() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { id } = useParams()
    const { showToast } = useToast()
    const currency = getCurrency()

    const [contract, setContract] = useState(null)
    const [loading, setLoading] = useState(true)
    const [showCancelModal, setShowCancelModal] = useState(false)
    const [showRenewModal, setShowRenewModal] = useState(false)
    const [actionLoading, setActionLoading] = useState(false)

    useEffect(() => {
        fetchContract()
    }, [id])

    const fetchContract = async () => {
        try {
            setLoading(true)
            const res = await contractsAPI.getContract(id)
            setContract(res.data)
        } catch (err) {
            showToast(t('contracts.details.load_error'), 'error')
        } finally {
            setLoading(false)
        }
    }

    const handleRenew = async () => {
        setActionLoading(true)
        try {
            await contractsAPI.renewContract(id)
            showToast(t('contracts.details.renewed_success'), 'success')
            setShowRenewModal(false)
            fetchContract()
        } catch (err) {
            showToast(err.response?.data?.detail || t('contracts.details.renew_error'), 'error')
        } finally {
            setActionLoading(false)
        }
    }

    const handleCancel = async () => {
        setActionLoading(true)
        try {
            await contractsAPI.cancelContract(id)
            showToast(t('contracts.details.cancelled_success'), 'success')
            setShowCancelModal(false)
            fetchContract()
        } catch (err) {
            showToast(err.response?.data?.detail || t('contracts.details.cancel_error'), 'error')
        } finally {
            setActionLoading(false)
        }
    }

    const handleGenerateInvoice = async () => {
        setActionLoading(true)
        try {
            const res = await contractsAPI.generateInvoice(id)
            showToast(
                `${t('contracts.details.invoice_generated')}: ${res.data.invoice_number}`, 'success'
            )
        } catch (err) {
            showToast(err.response?.data?.detail || t('contracts.details.invoice_error'), 'error')
        } finally {
            setActionLoading(false)
        }
    }

    if (loading) return <PageLoading />
    if (!contract) return <div className="page-center"><p>{t('contracts.details.not_found')}</p></div>

    const getStatusBadge = (status) => {
        switch (status) {
            case 'active': return 'badge-success'
            case 'expired': return 'badge-danger'
            case 'cancelled': return 'badge-ghost'
            default: return 'badge-info'
        }
    }

    const getStatusLabel = (status) => {
        switch (status) {
            case 'active': return t('contracts.details.status_active')
            case 'expired': return t('contracts.details.status_expired')
            case 'cancelled': return t('contracts.details.status_cancelled')
            default: return status
        }
    }

    const getTypeLabel = (type) => {
        switch (type) {
            case 'subscription': return t('contracts.details.type_subscription')
            case 'fixed': return t('contracts.details.type_fixed')
            case 'recurring': return t('contracts.details.type_recurring')
            case 'sales': return t('contracts.details.type_sales')
            case 'purchase': return t('contracts.details.type_purchase')
            default: return type
        }
    }

    const getIntervalLabel = (interval) => {
        switch (interval) {
            case 'monthly': return t('contracts.details.interval_monthly')
            case 'quarterly': return t('contracts.details.interval_quarterly')
            case 'semi_annual': return t('contracts.details.interval_semi_annual')
            case 'annual': return t('contracts.details.interval_annual')
            default: return interval
        }
    }

    // Calculate days remaining
    const daysRemaining = contract.end_date
        ? Math.ceil((new Date(contract.end_date) - new Date()) / (1000 * 60 * 60 * 24))
        : null

    // Calculate item totals
    const subtotal = (contract.items || []).reduce((sum, item) => sum + (item.quantity * item.unit_price), 0)
    const taxTotal = (contract.items || []).reduce((sum, item) => sum + (item.quantity * item.unit_price * item.tax_rate / 100), 0)

    return (
        <div className="workspace fade-in">
            {/* Header */}
            <div className="workspace-header">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <BackButton />
                        <div>
                            <h1 className="workspace-title" style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                                {contract.contract_number}
                                <span className={`badge ${getStatusBadge(contract.status)}`}>
                                    {getStatusLabel(contract.status)}
                                </span>
                            </h1>
                            <p className="workspace-subtitle">
                                {contract.party_name} — {getTypeLabel(contract.contract_type)}
                            </p>
                        </div>
                    </div>
                    {contract.status === 'active' && (
                        <div style={{ display: 'flex', gap: '8px' }}>
                            <button className="btn btn-secondary" onClick={() => navigate(`/sales/contracts/${id}/edit`)}>
                                <Edit2 size={16} /> {t('contracts.details.edit')}
                            </button>
                            <button className="btn btn-primary" onClick={handleGenerateInvoice} disabled={actionLoading}>
                                <FileText size={16} /> {t('contracts.details.generate_invoice')}
                            </button>
                            <button className="btn btn-secondary" onClick={() => setShowRenewModal(true)}>
                                <RefreshCw size={16} /> {t('contracts.details.renew')}
                            </button>
                            <button className="btn btn-danger" onClick={() => setShowCancelModal(true)}>
                                <XCircle size={16} /> {t('contracts.details.cancel')}
                            </button>
                        </div>
                    )}
                </div>
            </div>

            {/* Expiry Alert */}
            {contract.status === 'active' && daysRemaining !== null && daysRemaining <= 30 && daysRemaining > 0 && (
                <div className="alert alert-warning mb-4" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Clock size={18} />
                    {t('contracts.details.expiring_alert', { days: daysRemaining }) || `⚠️ هذا العقد سينتهي خلال ${daysRemaining} يوم`}
                </div>
            )}
            {contract.status === 'active' && daysRemaining !== null && daysRemaining <= 0 && (
                <div className="alert alert-error mb-4" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Clock size={18} />
                    {t('contracts.details.expired_alert')}
                </div>
            )}

            {/* Summary Cards */}
            <div className="grid grid-4 mb-4">
                <div className="metric-card">
                    <div className="metric-icon" style={{ background: 'var(--primary-light)' }}>
                        <DollarSign size={20} style={{ color: 'var(--primary)' }} />
                    </div>
                    <div className="metric-content">
                        <span className="metric-label">{t('contracts.details.total_value')}</span>
                        <span className="metric-value">{formatNumber(contract.total_amount)} {contract.currency || currency}</span>
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-icon" style={{ background: '#e8f5e9' }}>
                        <User size={20} style={{ color: '#2e7d32' }} />
                    </div>
                    <div className="metric-content">
                        <span className="metric-label">{t('contracts.details.client')}</span>
                        <span className="metric-value" style={{ fontSize: '1rem' }}>{contract.party_name}</span>
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-icon" style={{ background: '#fff3e0' }}>
                        <Calendar size={20} style={{ color: '#e65100' }} />
                    </div>
                    <div className="metric-content">
                        <span className="metric-label">{t('contracts.details.period')}</span>
                        <span className="metric-value" style={{ fontSize: '0.9rem' }}>
                            {formatShortDate(contract.start_date)} — {contract.end_date ? formatShortDate(contract.end_date) : '∞'}
                        </span>
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-icon" style={{ background: '#e3f2fd' }}>
                        <RefreshCw size={20} style={{ color: '#1565c0' }} />
                    </div>
                    <div className="metric-content">
                        <span className="metric-label">{t('contracts.details.billing_cycle')}</span>
                        <span className="metric-value" style={{ fontSize: '1rem' }}>{getIntervalLabel(contract.billing_interval)}</span>
                    </div>
                </div>
            </div>

            {/* Contract Info */}
            <div className="grid grid-2 mb-4">
                <div className="card">
                    <h3 className="section-title">{t('contracts.details.info')}</h3>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                        <div>
                            <label className="form-label" style={{ fontWeight: 'normal', color: '#888' }}>{t('contracts.details.contract_number')}</label>
                            <p style={{ fontWeight: 'bold' }}>{contract.contract_number}</p>
                        </div>
                        <div>
                            <label className="form-label" style={{ fontWeight: 'normal', color: '#888' }}>{t('contracts.details.type')}</label>
                            <p>{getTypeLabel(contract.contract_type)}</p>
                        </div>
                        <div>
                            <label className="form-label" style={{ fontWeight: 'normal', color: '#888' }}>{t('contracts.details.start_date')}</label>
                            <p>{formatShortDate(contract.start_date)}</p>
                        </div>
                        <div>
                            <label className="form-label" style={{ fontWeight: 'normal', color: '#888' }}>{t('contracts.details.end_date')}</label>
                            <p>{contract.end_date ? formatShortDate(contract.end_date) : t('contracts.details.no_end_date')}</p>
                        </div>
                        <div>
                            <label className="form-label" style={{ fontWeight: 'normal', color: '#888' }}>{t('contracts.details.days_remaining')}</label>
                            <p style={{ color: daysRemaining <= 30 ? '#e65100' : 'inherit', fontWeight: daysRemaining <= 30 ? 'bold' : 'normal' }}>
                                {daysRemaining !== null ? (daysRemaining > 0 ? `${daysRemaining} ${t('contracts.details.days')}` : t('contracts.details.expired_label')) : '—'}
                            </p>
                        </div>
                        <div>
                            <label className="form-label" style={{ fontWeight: 'normal', color: '#888' }}>{t('contracts.details.currency')}</label>
                            <p>{contract.currency || currency}</p>
                        </div>
                    </div>
                    {contract.notes && (
                        <div style={{ marginTop: '16px', padding: '12px', background: '#f9f9f9', borderRadius: '8px' }}>
                            <label className="form-label" style={{ fontWeight: 'normal', color: '#888' }}>{t('contracts.details.notes')}</label>
                            <p>{contract.notes}</p>
                        </div>
                    )}
                </div>

                {/* Totals */}
                <div className="card">
                    <h3 className="section-title">{t('contracts.details.financial_summary')}</h3>
                    <div style={{ marginTop: '12px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', padding: '10px 0', borderBottom: '1px solid #eee' }}>
                            <span>{t('contracts.details.subtotal')}</span>
                            <span>{formatNumber(subtotal)} {contract.currency || currency}</span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', padding: '10px 0', borderBottom: '1px solid #eee' }}>
                            <span>{t('contracts.details.tax')}</span>
                            <span>{formatNumber(taxTotal)} {contract.currency || currency}</span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', padding: '14px 0', fontWeight: 'bold', fontSize: '1.2rem' }}>
                            <span>{t('contracts.details.grand_total')}</span>
                            <span style={{ color: 'var(--primary)' }}>{formatNumber(contract.total_amount)} {contract.currency || currency}</span>
                        </div>
                    </div>
                </div>
            </div>

            {/* Items Table */}
            <div className="card">
                <h3 className="section-title">{t('contracts.details.items')} ({(contract.items || []).length})</h3>
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>{t('contracts.details.item_desc')}</th>
                            <th>{t('contracts.details.quantity')}</th>
                            <th>{t('contracts.details.unit_price')}</th>
                            <th>{t('contracts.details.tax_rate')}</th>
                            <th>{t('contracts.details.item_total')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {(contract.items || []).map((item, idx) => (
                            <tr key={item.id || idx}>
                                <td>{idx + 1}</td>
                                <td>{item.description || '—'}</td>
                                <td>{formatNumber(item.quantity)}</td>
                                <td>{formatNumber(item.unit_price)} {contract.currency || currency}</td>
                                <td>{item.tax_rate}%</td>
                                <td style={{ fontWeight: 'bold' }}>{formatNumber(item.total)} {contract.currency || currency}</td>
                            </tr>
                        ))}
                        {(contract.items || []).length === 0 && (
                            <tr>
                                <td colSpan="6" style={{ textAlign: 'center', padding: '24px', color: '#888' }}>
                                    {t('contracts.details.no_items')}
                                </td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>

            {/* Cancel Modal */}
            {showCancelModal && (
                <SimpleModal
                    title={t('contracts.details.cancel_title')}
                    onClose={() => setShowCancelModal(false)}
                >
                    <p style={{ marginBottom: '16px' }}>
                        {t('contracts.details.cancel_confirm')}
                    </p>
                    <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                        <button className="btn btn-secondary" onClick={() => setShowCancelModal(false)} disabled={actionLoading}>
                            {t('common.close')}
                        </button>
                        <button className="btn btn-danger" onClick={handleCancel} disabled={actionLoading}>
                            {actionLoading ? t('common.loading') || '...' : t('contracts.details.confirm_cancel')}
                        </button>
                    </div>
                </SimpleModal>
            )}

            {/* Renew Modal */}
            {showRenewModal && (
                <SimpleModal
                    title={t('contracts.details.renew_title')}
                    onClose={() => setShowRenewModal(false)}
                >
                    <p style={{ marginBottom: '16px' }}>
                        {t('contracts.details.renew_confirm')}
                    </p>
                    <div style={{ background: '#f5f5f5', padding: '12px', borderRadius: '8px', marginBottom: '16px' }}>
                        <p><strong>{t('contracts.details.billing_cycle')}:</strong> {getIntervalLabel(contract.billing_interval)}</p>
                        <p><strong>{t('contracts.details.current_end')}:</strong> {contract.end_date ? formatShortDate(contract.end_date) : '—'}</p>
                    </div>
                    <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                        <button className="btn btn-secondary" onClick={() => setShowRenewModal(false)} disabled={actionLoading}>
                            {t('common.close')}
                        </button>
                        <button className="btn btn-primary" onClick={handleRenew} disabled={actionLoading}>
                            {actionLoading ? t('common.loading') || '...' : t('contracts.details.confirm_renew')}
                        </button>
                    </div>
                </SimpleModal>
            )}
        </div>
    )
}
