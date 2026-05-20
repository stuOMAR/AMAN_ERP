import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { getCurrency } from '../../utils/auth'
import { purchasesAPI } from '../../utils/api'
import { useTranslation } from 'react-i18next'
import { useToast } from '../../context/ToastContext'
import { formatShortDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'
import { formatNumber } from '../../utils/format'
import Decimal from 'decimal.js'

function BuyingOrderDetails() {
    const { t } = useTranslation()
    const { id } = useParams()
    const navigate = useNavigate()
    const { showToast } = useToast()
    const currency = getCurrency()
    const [order, setOrder] = useState(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)

    useEffect(() => {
        const fetchOrder = async () => {
            try {
                const response = await purchasesAPI.getOrder(id)
                setOrder(response.data)
            } catch (err) {
                showToast(t('common.error'), 'error')
                setError(t('common.error_loading'))
            } finally {
                setLoading(false)
            }
        }
        fetchOrder()
    }, [id, t])

    if (loading) return <PageLoading />
    if (error) return <div className="alert alert-error m-4">{error}</div>
    if (!order) return <div className="p-4 text-center">{t('common.not_found')}</div>

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <h1 className="workspace-title">{t('buying.orders.details.title')} #{order.po_number}</h1>
                        <span className={`status-badge ${order.status}`}>
                            {order.status === 'draft' ? t('buying.orders.status.draft') :
                                order.status === 'confirmed' ? t('buying.orders.status.confirmed') :
                                    order.status === 'received' ? t('buying.orders.status.received') : order.status}
                        </span>
                    </div>
                    <p className="workspace-subtitle">{t('buying.orders.subtitle')}</p>
                </div>
                <div className="header-actions">
                    {/* T039: Disable convert-to-invoice when no uninvoiced received qty remains */}
                    {order.items && order.items.some(item => new Decimal(item.remaining_to_invoice || 0).gt(0)) && (
                        <button
                            className="btn btn-primary"
                            onClick={() => navigate('/buying/invoices/new', { state: { fromOrder: order } })}
                        >
                            📝 {t('buying.orders.details.convert_to_invoice')}
                        </button>
                    )}
                    <button className="btn btn-secondary" onClick={() => window.print()}>
                        🖨️ {t('buying.orders.details.print')}
                    </button>
                    <button onClick={() => navigate('/buying/orders')} className="btn btn-secondary">
                        {t('buying.orders.details.back_to_list')}
                    </button>
                </div>
            </div>

            <div className="card">
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '40px', marginBottom: '32px' }}>
                    <div>
                        <h4 style={{ color: 'var(--text-secondary)', marginBottom: '8px' }}>{t('buying.orders.details.to_supplier')}:</h4>
                        <div style={{ fontSize: '18px', fontWeight: 'bold' }}>{order.supplier_name}</div>
                        {order.supplier_code && <div style={{ color: 'var(--text-secondary)' }}>{t('buying.orders.details.supplier_code')}: {order.supplier_code}</div>}
                    </div>
                    <div style={{ textAlign: 'left' }}>
                        <h4 style={{ color: 'var(--text-secondary)', marginBottom: '8px' }}>{t('buying.orders.details.additional_details')}:</h4>
                        <div>
                            <span className="text-secondary">{t('buying.orders.details.order_date')}:</span> {formatShortDate(order.order_date)}
                        </div>
                        <div>
                            <span className="text-secondary">{t('buying.orders.details.expected_date')}:</span> {order.expected_date ? formatShortDate(order.expected_date) : '-'}
                        </div>
                    </div>
                </div>

                <div className="invoice-items-container" style={{ border: '1px solid var(--border-color)', borderRadius: '8px', overflow: 'hidden' }}>
                    <table className="data-table">
                        <thead style={{ background: 'var(--bg-secondary)' }}>
                            <tr>
                                <th style={{ width: '30%' }}>{t('buying.orders.form.items.product')}</th>
                                <th style={{ width: '10%', textAlign: 'center' }}>{t('buying.orders.form.items.quantity')}</th>
                                <th style={{ width: '15%' }}>{t('buying.orders.form.items.unit_price')}</th>
                                <th style={{ width: '15%' }}>{t('buying.orders.form.items.discount')}</th>
                                <th style={{ width: '10%' }}>{t('buying.orders.form.items.tax_rate')}</th>
                                <th style={{ width: '15%' }}>{t('buying.orders.form.items.total')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {order.items.map((item, index) => (
                                <tr key={index}>
                                    <td>
                                        <div className="font-medium">{item.product_name}</div>
                                        <div className="text-secondary" style={{ fontSize: '12px' }}>{item.description}</div>
                                    </td>
                                    <td style={{ textAlign: 'center' }}>{formatNumber(item.quantity)}</td>
                                    <td style={{ textAlign: 'left' }}>{formatNumber(item.unit_price)} <small>{order.currency || currency}</small></td>
                                    <td style={{ textAlign: 'left' }}>{formatNumber(item.discount)} <small>{order.currency || currency}</small></td>
                                    <td style={{ textAlign: 'left' }}>{item.tax_rate}%</td>
                                    <td style={{ textAlign: 'left' }} className="font-bold">{formatNumber(item.total)} <small>{order.currency || currency}</small></td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '32px' }}>
                    <div style={{ flex: 1, maxWidth: '500px' }}>
                        <h4 style={{ marginBottom: '8px' }}>{t('buying.orders.details.notes')}:</h4>
                        <p style={{ whiteSpace: 'pre-wrap', color: 'var(--text-secondary)' }}>{order.notes || t('buying.orders.details.no_notes_found')}</p>
                    </div>
                    <div style={{ width: '300px', padding: '20px', background: 'var(--bg-secondary)', borderRadius: '8px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                            <span>{t('buying.orders.form.summary.subtotal')}:</span>
                            <span>{formatNumber(order.subtotal)} <small>{order.currency || currency}</small></span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                            <span>{t('buying.orders.form.summary.discount')}:</span>
                            <span className="text-error">-{formatNumber(order.discount)} <small>{order.currency || currency}</small></span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                            <span>{t('buying.orders.form.summary.tax')}:</span>
                            <span>{formatNumber(order.tax_amount)} <small>{order.currency || currency}</small></span>
                        </div>
                        <div style={{ borderTop: '1px solid var(--border-color)', margin: '12px 0' }}></div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 'bold', fontSize: '1.2rem', color: 'var(--primary)' }}>
                            <span>{t('buying.orders.form.summary.grand_total')}:</span>
                            <span>{formatNumber(order.total)} <small>{order.currency || currency}</small></span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}

export default BuyingOrderDetails
