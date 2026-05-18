import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { deliveryOrdersAPI } from '../../utils/api'
import { getCurrency, hasPermission } from '../../utils/auth'
import { useTranslation } from 'react-i18next'
import { formatShortDate } from '../../utils/dateUtils'
import { useToast } from '../../context/ToastContext'
import BackButton from '../../components/common/BackButton'
import { formatNumber } from '../../utils/format'
import { PageLoading } from '../../components/common/LoadingStates'

function DeliveryOrderDetails() {
    const { id } = useParams()
    const { t } = useTranslation()
    const { showToast } = useToast()
    const currency = getCurrency()
    const [order, setOrder] = useState(null)
    const [loading, setLoading] = useState(true)
    const [actionLoading, setActionLoading] = useState(false)

    // M3: gate each action button on the same permission the backend
    // endpoint requires, so view-only users never see buttons that
    // would return 403.
    const canConfirm  = hasPermission('sales.create')
    const canDeliver  = hasPermission('sales.create')
    const canInvoice  = hasPermission('sales.create')
    const canCancel   = hasPermission('sales.void')

    const fetchOrder = async () => {
        try {
            const res = await deliveryOrdersAPI.get(id)
            setOrder(res.data)
        } catch (err) {
            showToast(t('common.error'), 'error')
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => { fetchOrder() }, [id])

    const handleAction = async (action, label) => {
        setActionLoading(true)
        try {
            if (action === 'confirm') await deliveryOrdersAPI.confirm(id)
            else if (action === 'deliver') await deliveryOrdersAPI.deliver(id)
            else if (action === 'invoice') await deliveryOrdersAPI.createInvoice(id)
            else if (action === 'cancel') await deliveryOrdersAPI.cancel(id)
            showToast(`${label} ✓`, 'success')
            fetchOrder()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        } finally {
            setActionLoading(false)
        }
    }

    if (loading) return <PageLoading />
    if (!order) return <div className="p-4 text-muted">{t('common.not_found')}</div>

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">🚚 {order.do_number}</h1>
                    <span className={`status-badge ${order.status}`}>{t(`delivery_orders.status_${order.status}`, order.status)}</span>
                </div>
                <div className="header-actions">
                    {canConfirm && order.status === 'draft' && (
                        <button className="btn btn-primary" disabled={actionLoading} onClick={() => handleAction('confirm', t('common.confirm'))}>
                            ✅ {t('common.confirm')}
                        </button>
                    )}
                    {canDeliver && order.status === 'confirmed' && (
                        <button className="btn btn-primary" disabled={actionLoading} onClick={() => handleAction('deliver', t('delivery_orders.mark_delivered'))}>
                            📦 {t('delivery_orders.mark_delivered')}
                        </button>
                    )}
                    {canInvoice && (order.status === 'delivered' || order.status === 'confirmed') && (
                        <button className="btn btn-success" disabled={actionLoading} onClick={() => handleAction('invoice', t('delivery_orders.create_invoice'))}>
                            🧾 {t('delivery_orders.create_invoice')}
                        </button>
                    )}
                    {canCancel && order.status === 'draft' && (
                        <button className="btn btn-danger" disabled={actionLoading} onClick={() => handleAction('cancel', t('common.cancel'))}>
                            ❌ {t('common.cancel')}
                        </button>
                    )}
                </div>
            </div>

            <div className="grid grid-2">
                <div className="card p-4">
                    <h3 className="card-title">{t('common.details')}</h3>
                    <div className="detail-grid">
                        <div><strong>{t('common.customer')}:</strong> {order.party_name}</div>
                        <div><strong>{t('common.date')}:</strong> {formatShortDate(order.do_date)}</div>
                        <div><strong>{t('delivery_orders.shipping_date')}:</strong> {order.shipping_date ? formatShortDate(order.shipping_date) : '-'}</div>
                        <div><strong>{t('delivery_orders.shipping_method')}:</strong> {order.shipping_method || '-'}</div>
                        <div><strong>{t('delivery_orders.tracking_number')}:</strong> {order.tracking_number || '-'}</div>
                        {order.so_number && <div><strong>{t('delivery_orders.sales_order')}:</strong> {order.so_number}</div>}
                    </div>
                    {order.shipping_address && (
                        <div className="mt-3">
                            <strong>{t('delivery_orders.shipping_address')}:</strong>
                            <p className="text-muted">{order.shipping_address}</p>
                        </div>
                    )}
                </div>
                <div className="card p-4">
                    <h3 className="card-title">{t('common.summary')}</h3>
                    <div className="detail-grid">
                        <div><strong>{t('common.subtotal')}:</strong> {formatNumber(order.subtotal)} {currency}</div>
                        <div><strong>{t('common.tax')}:</strong> {formatNumber(order.tax_amount)} {currency}</div>
                        <div className="text-xl font-bold"><strong>{t('common.total')}:</strong> {formatNumber(order.total_amount)} {currency}</div>
                    </div>
                </div>
            </div>

            <div className="card mt-4">
                <h3 className="card-title p-4">{t('common.items')}</h3>
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('common.product')}</th>
                            <th>{t('common.quantity')}</th>
                            <th>{t('common.unit_price')}</th>
                            <th>{t('common.total')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {(order.lines || []).map((line, i) => (
                            <tr key={i}>
                                <td>{line.product_name || `#${line.product_id}`}</td>
                                <td>{line.quantity}</td>
                                <td>{formatNumber(line.unit_price)} {currency}</td>
                                <td className="font-bold">{formatNumber(line.total)} {currency}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    )
}

export default DeliveryOrderDetails
