import { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { salesAPI } from '../../utils/api'
import { getCurrency } from '../../utils/auth'
import { useTranslation } from 'react-i18next'
import { formatShortDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';
import { formatNumber } from '../../utils/format';
import { PageLoading } from '../../components/common/LoadingStates'
import { useToast } from '../../context/ToastContext'


function SalesQuotationDetails() {
    const { t } = useTranslation()
    const { id } = useParams()
    const navigate = useNavigate()
    const { showToast } = useToast()
    const currency = getCurrency()
    const [quotation, setQuotation] = useState(null)
    const [loading, setLoading] = useState(true)
    const [actionLoading, setActionLoading] = useState(null)
    const [error, setError] = useState(null)

    const refreshQuotation = async () => {
        const response = await salesAPI.getQuotation(id)
        setQuotation(response.data)
    }

    useEffect(() => {
        const fetchQuotation = async () => {
            try {
                await refreshQuotation()
            } catch (err) {
                setError(t('sales.quotations.form.errors.fetch_failed'))
            } finally {
                setLoading(false)
            }
        }
        fetchQuotation()
    }, [id])

    const handleSendEmail = async () => {
        setActionLoading('send')
        try {
            const response = await salesAPI.sendQuotation(id)
            showToast(response.data?.message || 'تم إرسال عرض السعر بنجاح', 'success')
            await refreshQuotation()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        } finally {
            setActionLoading(null)
        }
    }

    const handleConvertToOrder = async () => {
        setActionLoading('convert')
        try {
            const response = await salesAPI.convertQuotation(id)
            showToast(response.data?.message || 'تم تحويل عرض السعر إلى أمر بيع', 'success')
            navigate(`/sales/orders/${response.data.order_id}`)
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        } finally {
            setActionLoading(null)
        }
    }

    if (loading) return <PageLoading />
    if (error) return <div className="alert alert-error m-4">{error}</div>
    if (!quotation) return <div className="p-4 text-center">{t('sales.quotations.empty')}</div>

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <h1 className="workspace-title">{t('sales.quotations.details.title')}: {quotation.sq_number}</h1>
                        <span className={`status-badge ${quotation.status}`}>
                            {quotation.status === 'draft' ? t('sales.quotations.status.draft') :
                                quotation.status === 'sent' ? t('sales.quotations.status.sent') :
                                    quotation.status === 'accepted' ? t('sales.quotations.status.accepted') :
                                        quotation.status === 'converted' ? t('sales.quotations.status.converted') : quotation.status}
                        </span>
                    </div>
                    <p className="workspace-subtitle">{t('sales.quotations.details.date')}: {formatShortDate(quotation.quotation_date)}</p>
                </div>
                <div className="header-actions">
                    {quotation.status !== 'converted' && quotation.status !== 'cancelled' && (
                        <button
                            className="btn btn-secondary"
                            onClick={handleSendEmail}
                            disabled={actionLoading !== null}
                        >
                            {actionLoading === 'send' ? t('common.loading', '...') : `✉️ ${t('sales.quotations.details.send_email', 'إرسال بالبريد')}`}
                        </button>
                    )}
                    {quotation.status !== 'converted' && quotation.status !== 'cancelled' && quotation.status !== 'expired' && (
                        <button
                            className="btn btn-primary"
                            onClick={handleConvertToOrder}
                            disabled={actionLoading !== null}
                        >
                            {actionLoading === 'convert' ? t('common.loading', '...') : `📝 ${t('sales.quotations.details.convert')}`}
                        </button>
                    )}
                    <button className="btn btn-secondary" onClick={() => window.print()}>
                        🖨️ {t('sales.quotations.details.print')}
                    </button>
                    <Link to="/sales/quotations" className="btn btn-secondary">
                        {t('sales.quotations.details.back_to_list')}
                    </Link>
                </div>
            </div>

            <div className="card">
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '40px', marginBottom: '32px' }}>
                    <div>
                        <h4 style={{ color: 'var(--text-secondary)', marginBottom: '8px' }}>{t('sales.quotations.details.customer')}:</h4>
                        <div style={{ fontSize: '18px', fontWeight: 'bold' }}>{quotation.customer_name}</div>
                        {quotation.customer_email && <div style={{ color: 'var(--text-secondary)' }}>Email: {quotation.customer_email}</div>}
                    </div>
                    <div style={{ textAlign: 'left' }}>
                        <h4 style={{ color: 'var(--text-secondary)', marginBottom: '8px' }}>{t('sales.quotations.details.expiry')}:</h4>
                        <div>{quotation.expiry_date ? formatShortDate(quotation.expiry_date) : '-'}</div>
                    </div>
                </div>

                <div className="invoice-items-container" style={{ border: '1px solid var(--border-color)', borderRadius: '8px', overflow: 'hidden' }}>
                    <table className="data-table">
                        <thead style={{ background: 'var(--bg-secondary)' }}>
                            <tr>
                                <th style={{ width: '25%' }}>{t('sales.quotations.form.items.product')}</th>
                                <th style={{ width: '15%' }}>{t('sales.quotations.form.items.description')}</th>
                                <th style={{ width: '10%', textAlign: 'center' }}>{t('sales.quotations.form.items.quantity')}</th>
                                <th style={{ width: '15%' }}>{t('sales.quotations.form.items.price')}</th>
                                <th style={{ width: '10%' }}>{t('sales.quotations.form.items.discount')}</th>
                                <th style={{ width: '10%' }}>{t('sales.quotations.form.items.tax')}</th>
                                <th style={{ width: '15%' }}>{t('sales.quotations.form.items.total')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {quotation.items.map((item, index) => (
                                <tr key={index}>
                                    <td className="font-medium">{item.product_code ? `${item.product_code} - ` : ''}{item.product_name}</td>
                                    <td className="text-secondary">{item.description}</td>
                                    <td style={{ textAlign: 'center' }}>{formatNumber(item.quantity)}</td>
                                    <td style={{ textAlign: 'left' }}>{formatNumber(item.unit_price)} <small>{quotation.currency || currency}</small></td>
                                    <td style={{ textAlign: 'left' }}>{formatNumber(item.discount)} <small>{quotation.currency || currency}</small></td>
                                    <td style={{ textAlign: 'left' }}>{item.tax_rate}%</td>
                                    <td style={{ textAlign: 'left' }} className="font-bold">{formatNumber(item.total)} <small>{quotation.currency || currency}</small></td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '32px' }}>
                    <div style={{ flex: 1, maxWidth: '500px' }}>
                        <h4 style={{ marginBottom: '8px' }}>{t('sales.quotations.details.notes')}:</h4>
                        <p style={{ whiteSpace: 'pre-wrap', color: 'var(--text-secondary)' }}>{quotation.notes || t('sales.quotations.details.no_notes')}</p>

                        {quotation.terms_conditions && (
                            <>
                                <h4 style={{ marginBottom: '8px', marginTop: '16px' }}>{t('sales.quotations.details.terms')}:</h4>
                                <p style={{ whiteSpace: 'pre-wrap', color: 'var(--text-secondary)' }}>{quotation.terms_conditions}</p>
                            </>
                        )}
                    </div>
                    <div style={{ width: '300px', padding: '20px', background: 'var(--bg-secondary)', borderRadius: '8px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                            <span>{t('sales.quotations.details.subtotal')}:</span>
                            <span>{formatNumber(quotation.subtotal)} <small>{quotation.currency || currency}</small></span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                            <span>{t('sales.quotations.details.discount')}:</span>
                            <span className="text-error">-{formatNumber(quotation.discount)} <small>{quotation.currency || currency}</small></span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                            <span>{t('sales.quotations.details.tax')}:</span>
                            <span>{formatNumber(quotation.tax_amount)} <small>{quotation.currency || currency}</small></span>
                        </div>
                        <div style={{ borderTop: '1px solid var(--border-color)', margin: '12px 0' }}></div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 'bold', fontSize: '1.2rem', color: 'var(--primary)' }}>
                            <span>{t('sales.quotations.details.grand_total')}:</span>
                            <span>{formatNumber(quotation.total)} <small>{quotation.currency || currency}</small></span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}

export default SalesQuotationDetails
