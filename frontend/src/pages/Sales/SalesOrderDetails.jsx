import { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { salesAPI } from '../../utils/api'
import { getCurrency, hasPermission } from '../../utils/auth'
import { useTranslation } from 'react-i18next'
import { formatShortDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';
import { formatNumber } from '../../utils/format';
import { PageLoading } from '../../components/common/LoadingStates'
import { useToast } from '../../context/ToastContext'


function SalesOrderDetails() {
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
                const response = await salesAPI.getOrder(id)
                setOrder(response.data)
            } catch (err) {
                setError(t('sales.orders.form.errors.fetch_failed'))
            } finally {
                setLoading(false)
            }
        }
        fetchOrder()
    }, [id])

    const handleCancel = async () => {
        if (!window.confirm(t('common.confirm_cancel', 'هل أنت متأكد من الإلغاء؟'))) return
        try {
            await salesAPI.cancelOrder(id)
            showToast(t('common.success'), 'success')
            const response = await salesAPI.getOrder(id)
            setOrder(response.data)
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        }
    }

    if (loading) return <PageLoading />
    if (error) return <div className="alert alert-error m-4">{error}</div>
    if (!order) return <div className="p-4 text-center">{t('sales.orders.empty')}</div>

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <h1 className="workspace-title">{t('sales.orders.details.title')}: {order.so_number}</h1>
                        <span className={`status-badge ${order.status}`}>
                            {order.status === 'draft' ? t('sales.orders.status.draft') :
                                order.status === 'confirmed' ? t('sales.orders.status.confirmed') :
                                    order.status === 'delivered' ? t('sales.orders.status.delivered') : order.status}
                        </span>
                    </div>
                    <p className="workspace-subtitle">{t('sales.orders.details.date')}: {formatShortDate(order.order_date)}</p>
                </div>
                <div className="header-actions">
                    <button
                        className="btn btn-primary"
                        onClick={() => navigate('/sales/invoices/new', { state: { fromOrder: order } })}
                    >
                        📝 {t('sales.orders.details.convert')}
                    </button>
                    <button className="btn btn-secondary" onClick={() => window.print()}>
                        🖨️ {t('sales.orders.details.print')}
                    </button>
                    {hasPermission('sales.void') && !['cancelled', 'delivered', 'invoiced'].includes(order.status) && (
                        <button className="btn btn-danger" onClick={handleCancel}>
                            {t('common.cancel')}
                        </button>
                    )}
                    <Link to="/sales/orders" className="btn btn-secondary">
                        {t('sales.orders.details.back_to_list')}
                    </Link>
                </div>
            </div>

            <div className="card">
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '40px', marginBottom: '32px' }}>
                    <div>
                        <h4 style={{ color: 'var(--text-secondary)', marginBottom: '8px' }}>{t('sales.orders.details.customer')}:</h4>
                        <div style={{ fontSize: '18px', fontWeight: 'bold' }}>{order.customer_name}</div>
                        {order.customer_code && <div style={{ color: 'var(--text-secondary)' }}>{t('sales.orders.details.customer_code')}: {order.customer_code}</div>}
                    </div>
                    <div style={{ textAlign: 'left' }}>
                        <h4 style={{ color: 'var(--text-secondary)', marginBottom: '8px' }}>{t('sales.orders.details.delivery_details')}:</h4>
                        <div>{t('sales.orders.details.expected_delivery')}: {order.expected_delivery_date ? formatShortDate(order.expected_delivery_date) : '-'}</div>
                    </div>
                </div>

                <div className="invoice-items-container" style={{ border: '1px solid var(--border-color)', borderRadius: '8px', overflow: 'hidden' }}>
                    <table className="data-table">
                        <thead style={{ background: 'var(--bg-secondary)' }}>
                            <tr>
                                <th style={{ width: '25%' }}>{t('sales.orders.form.items.product')}</th>
                                <th style={{ width: '15%' }}>{t('sales.orders.form.items.description')}</th>
                                <th style={{ width: '10%', textAlign: 'center' }}>{t('sales.orders.form.items.quantity')}</th>
                                <th style={{ width: '15%' }}>{t('sales.orders.form.items.price')}</th>
                                <th style={{ width: '10%' }}>{t('sales.orders.form.items.discount')}</th>
                                <th style={{ width: '10%' }}>{t('sales.orders.form.items.tax')}</th>
                                <th style={{ width: '15%' }}>{t('sales.orders.form.items.total')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {order.items.map((item, index) => (
                                <tr key={index}>
                                    <td className="font-medium">{item.product_name}</td>
                                    <td className="text-secondary">{item.description}</td>
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
                        <h4 style={{ marginBottom: '8px' }}>{t('sales.orders.details.notes')}:</h4>
                        <p style={{ whiteSpace: 'pre-wrap', color: 'var(--text-secondary)' }}>{order.notes || t('sales.orders.details.no_notes')}</p>
                    </div>
                    <div style={{ width: '300px', padding: '20px', background: 'var(--bg-secondary)', borderRadius: '8px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                            <span>{t('sales.orders.details.subtotal')}:</span>
                            <span>{formatNumber(order.subtotal)} <small>{order.currency || currency}</small></span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                            <span>{t('sales.orders.details.discount')}:</span>
                            <span className="text-error">-{formatNumber(order.discount)} <small>{order.currency || currency}</small></span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                            <span>{t('sales.orders.details.tax')}:</span>
                            <span>{formatNumber(order.tax_amount)} <small>{order.currency || currency}</small></span>
                        </div>
                        <div style={{ borderTop: '1px solid var(--border-color)', margin: '12px 0' }}></div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 'bold', fontSize: '1.2rem', color: 'var(--primary)' }}>
                            <span>{t('sales.orders.details.grand_total')}:</span>
                            <span>{formatNumber(order.total)} <small>{order.currency || currency}</small></span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}

export default SalesOrderDetails
