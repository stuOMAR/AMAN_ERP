import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { salesAPI } from '../../utils/api'
import { getCurrency } from '../../utils/auth'
import { useTranslation } from 'react-i18next'
import { formatDateTime, formatShortDate } from '../../utils/dateUtils'
import { Printer, ArrowLeft, CreditCard, Clock, CheckCircle, AlertCircle, FileText, User, XCircle } from 'lucide-react'
import { formatNumber } from '../../utils/format'
import { useToast } from '../../context/ToastContext'
import InvoicePrintModal from './InvoicePrintModal'
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

function InvoiceDetails() {
    const { t } = useTranslation()
    const { showToast } = useToast()
    const { id } = useParams()
    const navigate = useNavigate()
    const [invoice, setInvoice] = useState(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)
    const [paymentHistory, setPaymentHistory] = useState([])
    const [showPrintModal, setShowPrintModal] = useState(false)
    const currency = getCurrency()

    useEffect(() => {
        const fetchData = async () => {
            try {
                const response = await salesAPI.getInvoice(id)
                setInvoice(response.data)

                const historyRes = await salesAPI.getInvoicePaymentHistory(id)
                setPaymentHistory(historyRes.data)
            } catch (err) {
                setError(t('sales.invoices.details.error_load'))
            } finally {
                setLoading(false)
            }
        }
        fetchData()
    }, [id, t])

    if (loading) return <PageLoading />
    if (error) return <div className="workspace fade-in"><div className="alert alert-error">{error}</div></div>
    if (!invoice) return <div className="workspace fade-in"><div className="alert alert-warning">{t('sales.invoices.details.not_found')}</div></div>
    const showPaidSection = invoice.status === 'paid' || invoice.status === 'partial' || paymentHistory.length > 0

    const getStatusBadge = (status) => {
        switch (status) {
            case 'paid':
                return <span className="badge badge-success" style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                    <CheckCircle size={12} /> {t('sales.invoices.status.paid')}
                </span>
            case 'partial':
                return <span className="badge badge-warning" style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                    <Clock size={12} /> {t('sales.invoices.status.partial')}
                </span>
            default:
                return <span className="badge badge-danger" style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                    <AlertCircle size={12} /> {t('sales.invoices.status.unpaid')}
                </span>
        }
    }

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <h1 className="workspace-title">{invoice.invoice_number}</h1>
                        {getStatusBadge(invoice.status)}
                    </div>
                    <p className="workspace-subtitle">{t('sales.invoices.details.subtitle', { name: invoice.customer_name })}</p>
                </div>
                <div className="header-actions">
                    {invoice.status === 'unpaid' && (
                        <button
                            className="btn btn-outline-danger"
                            onClick={async () => {
                                if (!window.confirm(t('sales.invoices.details.confirm_cancel'))) return;
                                try {
                                    await salesAPI.cancelInvoice(id);
                                    showToast(t('sales.invoices.details.cancelled_success'), 'success');
                                    const response = await salesAPI.getInvoice(id);
                                    setInvoice(response.data);
                                } catch (err) {
                                    showToast(err.response?.data?.detail || t('common.error_occurred'), 'error');
                                }
                            }}
                        >
                            <XCircle size={18} style={{ marginLeft: '8px' }} />
                            {t('sales.invoices.details.cancel_invoice')}
                        </button>
                    )}
                    {(invoice.status === 'unpaid' || invoice.status === 'partial') && (
                        <button
                            className="btn btn-primary"
                            onClick={() => navigate('/sales/receipts/new', { state: { fromInvoice: invoice } })}
                        >
                            <CreditCard size={18} style={{ marginLeft: '8px' }} />
                            {t('sales.invoices.details.record_payment')}
                        </button>
                    )}
                    <button className="btn btn-secondary" onClick={() => setShowPrintModal(true)}>
                        <Printer size={18} style={{ marginLeft: '8px' }} />
                        {t('sales.invoices.details.print')}
                    </button>
                    <button className="btn btn-secondary" onClick={() => navigate('/sales/invoices')}>
                        <ArrowLeft size={18} style={{ marginLeft: '8px' }} />
                        {t('sales.invoices.details.back_to_list')}
                    </button>
                </div>
            </div>

            <div className="section-card mb-6">
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '40px', marginBottom: '32px' }}>
                    <div style={{ padding: '16px', background: 'rgba(37, 99, 235, 0.05)', borderRadius: '12px', border: '1px solid rgba(37, 99, 235, 0.1)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
                            <User size={16} className="text-primary" />
                            <h4 style={{ color: 'var(--text-secondary)', fontSize: '13px', margin: 0 }}>{t('sales.invoices.details.customer')}</h4>
                        </div>
                        <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: 'var(--primary)' }}>{invoice.customer_name}</div>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                        <div className="p-3">
                            <h4 style={{ color: 'var(--text-secondary)', marginBottom: '4px', fontSize: '13px' }}>{t('sales.invoices.details.date')}</h4>
                            <div className="font-medium">{formatShortDate(invoice.invoice_date)}</div>
                        </div>
                        <div className="p-3">
                            <h4 style={{ color: 'var(--text-secondary)', marginBottom: '4px', fontSize: '13px' }}>{t('sales.invoices.details.due_date')}</h4>
                            <div className="font-medium">{invoice.due_date ? formatShortDate(invoice.due_date) : '-'}</div>
                        </div>
                    </div>
                </div>

                <div className="data-table-container mb-8">
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>{t('sales.invoices.details.item_desc')}</th>
                                <th style={{ textAlign: 'center' }}>{t('sales.invoices.form.items.quantity')}</th>
                                <th style={{ textAlign: 'left' }}>{t('sales.invoices.form.items.price')}</th>
                                <th style={{ textAlign: 'left' }}>{t('sales.invoices.form.items.discount')}</th>
                                <th style={{ textAlign: 'left' }}>{t('sales.invoices.form.items.tax')}</th>
                                <th style={{ textAlign: 'left' }}>{t('sales.invoices.form.items.total')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {invoice.items.map((item, index) => (
                                <tr key={index}>
                                    <td>
                                        <div className="font-medium">{item.product_name || item.description}</div>
                                        {item.description && item.description !== item.product_name && (
                                            <div className="text-muted" style={{ fontSize: '12px', marginTop: '4px' }}>{item.description}</div>
                                        )}
                                    </td>
                                    <td style={{ textAlign: 'center' }} className="font-mono">{formatNumber(item.quantity, 0)} {item.unit}</td>
                                    <td style={{ textAlign: 'left' }} className="font-mono">{formatNumber(item.unit_price)} <small>{invoice.currency || currency}</small></td>
                                    <td style={{ textAlign: 'left' }} className="font-mono text-danger">-{formatNumber(item.discount)} <small>{invoice.currency || currency}</small></td>
                                    <td style={{ textAlign: 'left' }}>{item.tax_rate}%</td>
                                    <td style={{ textAlign: 'left' }} className="font-bold">{formatNumber(item.total)} <small>{invoice.currency || currency}</small></td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '32px' }}>
                    <div style={{ flex: 1 }}>
                        {invoice.notes && (
                            <div className="p-4 rounded-lg bg-light" style={{ border: '1px solid var(--border-color)' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                                    <FileText size={16} className="text-muted" />
                                    <h4 style={{ fontSize: '14px', margin: 0 }}>{t('sales.invoices.details.notes')}</h4>
                                </div>
                                <p className="text-secondary" style={{ fontSize: '14px', margin: 0 }}>{invoice.notes}</p>
                            </div>
                        )}
                    </div>

                    <div style={{ width: '320px', padding: '24px', background: 'var(--bg-main)', borderRadius: '12px', border: '1px solid var(--border-color)' }}>
                        {invoice.currency && invoice.currency !== currency && (
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px', paddingBottom: '12px', borderBottom: '1px dashed var(--border-color)' }}>
                                <span className="text-secondary" style={{ fontSize: '13px' }}>{t('accounting.currencies.table.rate')}</span>
                                <span className="font-mono" style={{ fontSize: '13px' }}>
                                    1 {invoice.currency} = {formatNumber(invoice.exchange_rate, 6)} {currency}
                                </span>
                            </div>
                        )}

                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
                            <span className="text-muted">{t('sales.invoices.form.totals.subtotal')}</span>
                            <span className="font-medium">{formatNumber(invoice.subtotal)} <small>{invoice.currency || currency}</small></span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
                            <span className="text-muted">{t('sales.invoices.form.totals.discount')}</span>
                            <span className="text-danger">-{formatNumber(invoice.discount)} <small>{invoice.currency || currency}</small></span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
                            <span className="text-muted">{t('sales.invoices.form.totals.tax')}</span>
                            <span className="font-medium">{formatNumber(invoice.tax_amount)} <small>{invoice.currency || currency}</small></span>
                        </div>
                        <div style={{ borderTop: '1px solid var(--border-color)', margin: '16px 0' }}></div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 'bold', fontSize: '1.25rem', color: 'var(--primary)' }}>
                            <span>{t('sales.invoices.details.grand_total')}</span>
                            <span>{formatNumber(invoice.total)} <small>{invoice.currency || currency}</small></span>
                        </div>

                        {invoice.currency && invoice.currency !== currency && invoice.total_base && (
                            <div className="mt-2 text-end">
                                <small className="text-muted">
                                    ≈ {formatNumber(invoice.total_base)} {invoice.base_currency || currency}
                                </small>
                            </div>
                        )}

                        {showPaidSection && (
                            <>
                                <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '12px', color: 'var(--success)' }}>
                                    <span style={{ fontSize: '14px' }}>{t('sales.invoices.details.paid_amount')}</span>
                                    <span className="font-medium">-{formatNumber(invoice.paid_amount)} <small>{invoice.currency || currency}</small></span>
                                </div>
                                {invoice.currency && invoice.currency !== currency && invoice.paid_amount_base && (
                                    <div className="text-end">
                                        <small className="text-success" style={{ opacity: 0.8 }}>
                                            ≈ {formatNumber(invoice.paid_amount_base)} {invoice.base_currency || currency}
                                        </small>
                                    </div>
                                )}
                                <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '8px', fontWeight: 'bold' }}>
                                    <span style={{ fontSize: '14px' }}>{t('sales.invoices.details.remaining_debt')}</span>
                                    <span>{formatNumber(invoice.remaining_balance)} <small>{invoice.currency || currency}</small></span>
                                </div>
                                {invoice.currency && invoice.currency !== currency && invoice.remaining_balance_base && (
                                    <div className="text-end">
                                        <small className="text-muted">
                                            ≈ {formatNumber(invoice.remaining_balance_base)} {invoice.base_currency || currency}
                                        </small>
                                    </div>
                                )}
                            </>
                        )}
                    </div>
                </div>

                {/* ZATCA QR Code */}
                {invoice.zatca_qr && (
                    <div style={{ 
                        marginTop: '32px', 
                        padding: '20px', 
                        background: 'var(--bg-secondary)', 
                        borderRadius: '12px',
                        textAlign: 'center'
                    }}>
                        <h4 style={{ marginBottom: '12px', fontSize: '14px', color: 'var(--text-secondary)' }}>
                            {t('common.zatca_qr_code')}
                        </h4>
                        <img 
                            src={`data:image/png;base64,${invoice.zatca_qr}`}
                            alt="ZATCA QR Code"
                            style={{ width: '180px', height: '180px', borderRadius: '8px' }}
                        />
                        {invoice.zatca_status && (
                            <div style={{ marginTop: '8px' }}>
                                <span className={`badge ${invoice.zatca_status === 'submitted' ? 'badge-success' : 'badge-info'}`}>
                                    {invoice.zatca_status === 'generated' ? t('common.zatca_generated') : 
                                     invoice.zatca_status === 'submitted' ? t('common.zatca_submitted') : invoice.zatca_status}
                                </span>
                            </div>
                        )}
                        {/* T1.5c — ZATCA Clearance Status */}
                        {invoice.zatca_clearance_status && (
                            <div style={{ marginTop: '6px' }}>
                                <span
                                    className="badge"
                                    style={{
                                        background:
                                            invoice.zatca_clearance_status === 'cleared' ? '#d1fae5' :
                                            invoice.zatca_clearance_status === 'rejected' ? '#fee2e2' :
                                            '#fef3c7',
                                        color:
                                            invoice.zatca_clearance_status === 'cleared' ? '#065f46' :
                                            invoice.zatca_clearance_status === 'rejected' ? '#991b1b' :
                                            '#92400e',
                                        padding: '4px 10px',
                                        borderRadius: '6px',
                                        fontSize: '12px',
                                    }}
                                    title={invoice.zatca_clearance_message || ''}
                                >
                                    {invoice.zatca_clearance_status === 'cleared' ? '✓ تمت المقاصة' :
                                     invoice.zatca_clearance_status === 'rejected' ? '✗ مرفوضة' :
                                     invoice.zatca_clearance_status === 'pending_clearance' ? '⏳ بانتظار المقاصة' :
                                     invoice.zatca_clearance_status}
                                </span>
                                {invoice.zatca_cleared_at && (
                                    <small className="text-muted ms-2" style={{ fontSize: '11px' }}>
                                        {formatDateTime(invoice.zatca_cleared_at)}
                                    </small>
                                )}
                            </div>
                        )}
                    </div>
                )}

                {paymentHistory.length > 0 && (
                    <div style={{ marginTop: '56px' }}>
                        <h3 className="section-title">
                            {t('sales.invoices.details.payment_history')}
                        </h3>
                        <div className="data-table-container">
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>{t('sales.invoices.details.voucher_number')}</th>
                                        <th>{t('sales.invoices.details.date')}</th>
                                        <th style={{ textAlign: 'left' }}>{t('sales.invoices.details.amount')}</th>
                                        <th>{t('sales.invoices.details.payment_method')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {paymentHistory.map((payment, index) => (
                                        <tr key={index} onClick={() => navigate(`/sales/receipts/${payment.voucher_id}`)} className="hover-row" style={{ cursor: 'pointer' }}>
                                            <td className="font-medium text-primary">{payment.voucher_number}</td>
                                            <td className="text-muted">{formatShortDate(payment.voucher_date)}</td>
                                            <td style={{ textAlign: 'left' }} className="font-bold text-success">
                                                +{formatNumber(payment.allocated_amount)} <small>{invoice.currency || currency}</small>
                                            </td>
                                            <td>
                                                <span className="badge badge-success">
                                                    {payment.payment_method === 'cash' ? t('sales.invoices.form.payment.cash') :
                                                        payment.payment_method === 'bank' ? t('sales.invoices.form.payment.bank') : t('sales.invoices.form.payment.check')}
                                                </span>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                )}
            </div>

            {showPrintModal && <InvoicePrintModal invoice={invoice} onClose={() => setShowPrintModal(false)} />}
        </div>
    )
}

export default InvoiceDetails
