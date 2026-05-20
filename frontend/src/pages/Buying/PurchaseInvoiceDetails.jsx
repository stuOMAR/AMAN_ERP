import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { purchasesAPI } from '../../utils/api'
import { getCurrency } from '../../utils/auth'
import { useTranslation } from 'react-i18next'
import { useToast } from '../../context/ToastContext'
import { formatShortDate } from '../../utils/dateUtils'
import { formatNumber } from '../../utils/format'
import { Printer, ArrowLeft, CreditCard, Clock, CheckCircle, AlertCircle, FileText, User } from 'lucide-react'
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'
import Decimal from 'decimal.js'

function PurchaseInvoiceDetails() {
    const { t } = useTranslation()
    const { id } = useParams()
    const navigate = useNavigate()
    const { showToast } = useToast()
    const [invoice, setInvoice] = useState(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)
    const [paymentHistory, setPaymentHistory] = useState([])
    const currency = getCurrency()

    useEffect(() => {
        const fetchData = async () => {
            try {
                const response = await purchasesAPI.getInvoice(id)
                setInvoice(response.data)

                if (response.data.paid_amount > 0) {
                    const historyRes = await purchasesAPI.getInvoicePaymentHistory(id)
                    setPaymentHistory(historyRes.data)
                }
            } catch (err) {
                setError(t('common.error_loading_details'))
                showToast(t('common.error'), 'error')
            } finally {
                setLoading(false)
            }
        }
        fetchData()
    }, [id, t])

    if (loading) return <PageLoading />
    if (error) return <div className="workspace fade-in"><div className="alert alert-error">{error}</div></div>
    if (!invoice) return <div className="workspace fade-in"><div className="alert alert-warning">{t('common.error_not_found')}</div></div>

    const getStatusBadge = (status) => {
        switch (status) {
            case 'paid':
                return <span className="badge badge-success" style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                    <CheckCircle size={12} /> {t('buying.purchase_invoices.details.status.paid')}
                </span>
            case 'partial':
                return <span className="badge badge-warning" style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                    <Clock size={12} /> {t('buying.purchase_invoices.details.status.partial')}
                </span>
            default:
                return <span className="badge badge-danger" style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                    <AlertCircle size={12} /> {t('buying.purchase_invoices.details.status.unpaid')}
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
                    <p className="workspace-subtitle">{t('buying.purchase_invoices.details.info.supplier')}: {invoice.supplier_name}</p>
                </div>
                <div className="header-actions">
                    {(invoice.status === 'unpaid' || invoice.status === 'partial') && (
                        <button
                            className="btn btn-primary"
                            onClick={() => navigate('/buying/payments/new', { state: { fromInvoice: invoice } })}
                        >
                            <CreditCard size={18} style={{ marginLeft: '8px' }} />
                            {t('buying.purchase_invoices.details.record_payment')}
                        </button>
                    )}
                    <button className="btn btn-secondary" onClick={() => window.print()}>
                        <Printer size={18} style={{ marginLeft: '8px' }} />
                        {t('buying.purchase_invoices.details.print')}
                    </button>
                    <button className="btn btn-secondary" onClick={() => navigate('/buying/invoices')}>
                        <ArrowLeft size={18} style={{ marginLeft: '8px' }} />
                        {t('buying.purchase_invoices.details.back')}
                    </button>
                </div>
            </div>

            <div className="section-card mb-6">
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '40px', marginBottom: '32px' }}>
                    <div style={{ padding: '16px', background: 'rgba(37, 99, 235, 0.05)', borderRadius: '12px', border: '1px solid rgba(37, 99, 235, 0.1)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
                            <User size={16} className="text-primary" />
                            <h4 style={{ color: 'var(--text-secondary)', fontSize: '13px', margin: 0 }}>{t('buying.purchase_invoices.details.info.supplier')}</h4>
                        </div>
                        <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: 'var(--primary)' }}>{invoice.supplier_name}</div>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                        <div className="p-3">
                            <h4 style={{ color: 'var(--text-secondary)', marginBottom: '4px', fontSize: '13px' }}>{t('buying.purchase_invoices.details.info.date')}</h4>
                            <div className="font-medium">{formatShortDate(invoice.invoice_date)}</div>
                        </div>
                        <div className="p-3">
                            <h4 style={{ color: 'var(--text-secondary)', marginBottom: '4px', fontSize: '13px' }}>{t('buying.purchase_invoices.details.info.due_date')}</h4>
                            <div className="font-medium">{invoice.due_date ? formatShortDate(invoice.due_date) : '-'}</div>
                        </div>
                    </div>
                </div>

                <div className="invoice-items-container" style={{ margin: '24px 0', border: '1px solid var(--border-color)', borderRadius: '8px', overflow: 'hidden' }}>
                    <table className="data-table">
                        <thead style={{ background: 'var(--bg-secondary)' }}>
                            <tr>
                                <th style={{ width: '30%' }}>{t('buying.purchase_invoices.form.items.product')}</th>
                                <th style={{ width: '10%', textAlign: 'center' }}>{t('buying.purchase_invoices.form.items.quantity')}</th>
                                <th style={{ width: '15%' }}>{t('buying.purchase_invoices.form.items.unit_price')}</th>
                                <th style={{ width: '10%' }}>{t('buying.purchase_invoices.form.items.discount')}</th>
                                <th style={{ width: '10%' }}>{t('buying.purchase_invoices.form.items.tax_rate')}</th>
                                <th style={{ width: '15%' }}>{t('buying.purchase_invoices.form.items.total')}</th>
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
                                    <td style={{ textAlign: 'center' }} className="font-mono">{formatNumber(item.quantity, 0)}</td>
                                    <td style={{ textAlign: 'left' }} className="font-mono">
                                        {formatNumber(item.unit_price)} <small>{invoice.currency || currency}</small>
                                        {invoice.currency && invoice.currency !== currency && (
                                            <div className="text-muted" style={{ fontSize: '11px' }}>
                                                ≈ {formatNumber(new Decimal(item.unit_price || 0).times(invoice.exchange_rate || 1).toString())} {currency}
                                            </div>
                                        )}
                                    </td>
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
                                    <h4 style={{ fontSize: '14px', margin: 0 }}>{t('buying.purchase_invoices.details.notes')}</h4>
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
                                    1 {invoice.currency} = {invoice.exchange_rate} {currency}
                                </span>
                            </div>
                        )}

                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
                            <span className="text-muted">{t('buying.purchase_invoices.form.summary.subtotal')}</span>
                            <span className="font-medium">{formatNumber(invoice.subtotal)} <small>{invoice.currency || currency}</small></span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
                            <span className="text-muted">{t('buying.purchase_invoices.form.summary.discount')}</span>
                            <span className="text-danger">-{formatNumber(invoice.discount)} <small>{invoice.currency || currency}</small></span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
                            <span className="text-muted">{t('buying.purchase_invoices.form.summary.tax')}</span>
                            <span className="font-medium">{formatNumber(invoice.tax_amount)} <small>{invoice.currency || currency}</small></span>
                        </div>
                        <div style={{ borderTop: '1px solid var(--border-color)', margin: '16px 0' }}></div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 'bold', fontSize: '1.25rem', color: 'var(--primary)' }}>
                            <span>{t('buying.purchase_invoices.form.summary.grand_total')}</span>
                            <span>{formatNumber(invoice.total)} <small>{invoice.currency || currency}</small></span>
                        </div>

                        {invoice.currency && invoice.currency !== currency && (
                            <div className="mt-2 text-end">
                                <small className="text-muted">
                                    ≈ {formatNumber(new Decimal(invoice.total || 0).times(invoice.exchange_rate || 1).toString())} {currency}
                                </small>
                            </div>
                        )}

                        {invoice.paid_amount > 0 && (
                            <>
                                <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '12px', color: 'var(--success)' }}>
                                    <span style={{ fontSize: '14px' }}>{t('buying.purchase_invoices.details.paid_amount')}</span>
                                    <span className="font-medium">-{formatNumber(invoice.paid_amount)} <small>{invoice.currency || currency}</small></span>
                                </div>
                                {invoice.currency && invoice.currency !== currency && (
                                    <div className="text-end">
                                        <small className="text-success" style={{ opacity: 0.8 }}>
                                            ≈ {formatNumber(new Decimal(invoice.paid_amount || 0).times(invoice.exchange_rate || 1).toString(), 2)} {currency}
                                        </small>
                                    </div>
                                )}
                                <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '8px', fontWeight: 'bold' }}>
                                    <span style={{ fontSize: '14px' }}>{t('buying.purchase_invoices.details.remaining_debt')}</span>
                                    <span>{formatNumber(new Decimal(invoice.total || 0).minus(invoice.paid_amount || 0).toString())} <small>{invoice.currency || currency}</small></span>
                                </div>
                            </>
                        )}
                    </div>
                </div>

                {paymentHistory.length > 0 && (
                    <div style={{ marginTop: '56px' }}>
                        <h3 className="section-title">
                            {t('buying.purchase_invoices.details.payment_history.title')}
                        </h3>
                        <div className="data-table-container">
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>{t('buying.purchase_invoices.details.payment_history.voucher_number')}</th>
                                        <th>{t('buying.purchase_invoices.details.payment_history.date')}</th>
                                        <th style={{ textAlign: 'left' }}>{t('buying.purchase_invoices.details.payment_history.amount')}</th>
                                        <th>{t('buying.purchase_invoices.details.payment_history.method')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {paymentHistory.map((payment, index) => (
                                        <tr key={index} onClick={() => navigate(`/buying/payments/${payment.voucher_id}`)} className="hover-row" style={{ cursor: 'pointer' }}>
                                            <td className="font-medium text-primary">{payment.voucher_number}</td>
                                            <td className="text-muted">{formatShortDate(payment.voucher_date)}</td>
                                            <td style={{ textAlign: 'left' }} className="font-bold text-danger">
                                                -{formatNumber(payment.allocated_amount)} <small>{invoice.currency || currency}</small>
                                            </td>
                                            <td>
                                                <span className="badge badge-warning">
                                                    {payment.payment_method === 'cash' ? t('buying.purchase_invoices.details.payment_history.methods.cash') :
                                                        payment.payment_method === 'bank' ? t('buying.purchase_invoices.details.payment_history.methods.bank') :
                                                            t('buying.purchase_invoices.details.payment_history.methods.check')}
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
        </div>
    )
}

export default PurchaseInvoiceDetails
