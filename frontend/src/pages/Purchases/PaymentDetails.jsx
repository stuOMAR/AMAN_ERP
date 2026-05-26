import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { purchasesAPI } from '../../utils/api'
import { getCurrency } from '../../utils/auth'
import { useTranslation } from 'react-i18next'
import { useToast } from '../../context/ToastContext'
import { formatShortDate } from '../../utils/dateUtils'
import { Printer, ArrowLeft, CreditCard, Calendar, User, FileText, CheckCircle, Info } from 'lucide-react'
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'
import { formatNumber } from '../../utils/format'

function PaymentDetails() {
    const { t } = useTranslation()
    const { id } = useParams()
    const navigate = useNavigate()
    const { showToast } = useToast()
    const [payment, setPayment] = useState(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)
    const currency = getCurrency()

    useEffect(() => {
        const fetchData = async () => {
            try {
                const response = await purchasesAPI.getPayment(id)
                setPayment(response.data)
            } catch (err) {
                setError(t('buying.payments.details.failed_load'))
                showToast(t('common.error'), 'error')
            } finally {
                setLoading(false)
            }
        }
        fetchData()
    }, [id, t])

    if (loading) return <PageLoading />
    if (error) return <div className="workspace fade-in"><div className="alert alert-error">{error}</div></div>
    if (!payment) return <div className="workspace fade-in"><div className="alert alert-warning">{t('buying.payments.details.not_found')}</div></div>

    const totalAllocated = payment.total_allocated || '0'

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <h1 className="workspace-title">{payment.voucher_number}</h1>
                        <span className={`badge ${payment.status === 'posted' ? 'badge-success' : 'badge-secondary'}`}>
                            {payment.status === 'posted' ? (
                                <><CheckCircle size={12} style={{ marginLeft: '4px' }} /> {t('buying.payments.status.posted')}</>
                            ) : (
                                <><FileText size={12} style={{ marginLeft: '4px' }} /> {t('buying.payments.status.draft')}</>
                            )}
                        </span>
                    </div>
                    <p className="workspace-subtitle">{t('buying.payments.details.subtitle')}</p>
                </div>
                <div className="header-actions">
                    <button className="btn btn-secondary" onClick={() => window.print()}>
                        <Printer size={18} style={{ marginLeft: '8px' }} />
                        {t('buying.payments.details.print')}
                    </button>
                    <button className="btn btn-secondary" onClick={() => navigate('/buying/payments')}>
                        <ArrowLeft size={18} style={{ marginLeft: '8px' }} />
                        {t('buying.payments.details.back')}
                    </button>
                </div>
            </div>

            <div className="section-card mb-6">
                <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: '32px', marginBottom: '40px' }}>
                    <div style={{ padding: '20px', background: 'rgba(37, 99, 235, 0.05)', borderRadius: '12px', border: '1px solid rgba(37, 99, 235, 0.1)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
                            <User size={18} className="text-primary" />
                            <h4 style={{ color: 'var(--text-secondary)', fontSize: '13px', margin: 0 }}>{t('buying.payments.details.supplier_section')}</h4>
                        </div>
                        <div style={{ fontSize: '1.4rem', fontWeight: 'bold', color: 'var(--primary)' }}>{payment.supplier_name}</div>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '20px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <Calendar size={16} className="text-muted" />
                                <span className="text-secondary">{t('buying.payments.details.date')}</span>
                            </div>
                            <span className="font-medium">{formatShortDate(payment.voucher_date)}</span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <CreditCard size={16} className="text-muted" />
                                <span className="text-secondary">{t('buying.payments.details.payment_method')}</span>
                            </div>
                            <span className="badge badge-secondary" style={{ fontSize: '13px' }}>
                                {payment.payment_method === 'cash' ? t('buying.purchase_invoices.details.payment_history.methods.cash') :
                                    payment.payment_method === 'bank' ? t('buying.purchase_invoices.details.payment_history.methods.bank') :
                                        t('buying.purchase_invoices.details.payment_history.methods.check')}
                            </span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span className="text-secondary">{t('buying.payments.details.amount')}</span>
                            <span style={{ fontSize: '1.4rem', fontWeight: '800', color: 'var(--danger)' }}>
                                -{formatNumber(payment.amount)} <small>{payment.currency || currency}</small>
                            </span>
                        </div>
                    </div>
                </div>

                {(payment.check_number || payment.reference) && (
                    <div style={{ padding: '20px', background: 'var(--bg-main)', borderRadius: '12px', border: '1px solid var(--border-color)', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '32px', marginBottom: '40px' }}>
                        {payment.check_number && (
                            <div>
                                <div className="text-secondary text-xs font-bold mb-1" style={{ textTransform: 'uppercase' }}>{t('buying.payments.details.check_number')}</div>
                                <div className="font-medium" style={{ fontSize: '15px' }}>{payment.check_number}</div>
                            </div>
                        )}
                        {payment.check_date && (
                            <div>
                                <div className="text-secondary text-xs font-bold mb-1" style={{ textTransform: 'uppercase' }}>{t('buying.payments.details.check_date')}</div>
                                <div className="font-medium" style={{ fontSize: '15px' }}>{formatShortDate(payment.check_date)}</div>
                            </div>
                        )}
                        {payment.reference && (
                            <div>
                                <div className="text-secondary text-xs font-bold mb-1" style={{ textTransform: 'uppercase' }}>{t('buying.payments.details.reference')}</div>
                                <div className="font-medium" style={{ fontSize: '15px' }}>{payment.reference}</div>
                            </div>
                        )}
                    </div>
                )}

                <div style={{ marginTop: '24px' }}>
                    <h3 className="section-title">
                        {t('buying.payments.details.allocations_title')}
                    </h3>

                    {payment.allocations && payment.allocations.length > 0 ? (
                        <div className="data-table-container">
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>{t('buying.payments.details.invoice_number')}</th>
                                        <th style={{ textAlign: 'left' }}>{t('buying.payments.details.allocated_amount')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {payment.allocations.map((alloc, index) => (
                                        <tr key={index} onClick={() => navigate(`/buying/invoices/${alloc.invoice_id}`)} className="hover-row" style={{ cursor: 'pointer' }}>
                                            <td className="font-medium text-primary">{alloc.invoice_number}</td>
                                            <td style={{ textAlign: 'left' }} className="font-bold text-danger">
                                                -{formatNumber(alloc.allocated_amount)} <small>{payment.currency || currency}</small>
                                            </td>
                                        </tr>
                                    ))}
                                    <tr style={{ background: 'var(--bg-main)', fontWeight: 'bold' }}>
                                        <td>{t('buying.payments.details.total_allocated')}</td>
                                        <td style={{ textAlign: 'left' }} className="text-danger">
                                            -{formatNumber(totalAllocated)} <small>{payment.currency || currency}</small>
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    ) : (
                        <div style={{ padding: '48px', textAlign: 'center', background: 'var(--bg-main)', borderRadius: '12px', border: '1px dashed var(--border-color)', color: 'var(--text-secondary)' }}>
                            <Info size={32} style={{ margin: '0 auto 16px', opacity: 0.5 }} />
                            <p>{t('buying.payments.details.down_payment')}</p>
                        </div>
                    )}
                </div>

                {payment.notes && (
                    <div style={{ marginTop: '40px', padding: '24px', background: '#fffbeb', borderRadius: '12px', border: '1px solid #fef3c7' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                            <FileText size={16} className="text-warning" />
                            <h4 style={{ fontSize: '14px', margin: 0 }}>{t('buying.payments.details.notes')}</h4>
                        </div>
                        <p style={{ color: 'var(--text-secondary)', fontSize: '14px', margin: 0, whiteSpace: 'pre-wrap' }}>{payment.notes}</p>
                    </div>
                )}
            </div>
        </div>
    )
}

export default PaymentDetails
