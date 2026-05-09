import { useState, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { deliveryOrdersAPI } from '../../utils/api'
import { getCurrency } from '../../utils/auth'
import { useTranslation } from 'react-i18next'
import { formatShortDate } from '../../utils/dateUtils'
import { useBranch } from '../../context/BranchContext'
import BackButton from '../../components/common/BackButton'
import { useToast } from '../../context/ToastContext'
import { formatNumber } from '../../utils/format'
import { PageLoading } from '../../components/common/LoadingStates'

function DeliveryOrders() {
    const { t } = useTranslation()
    const { showToast } = useToast()
    const navigate = useNavigate()
    const { currentBranch } = useBranch()
    const currency = getCurrency()
    const [orders, setOrders] = useState([])
    const [loading, setLoading] = useState(true)
    const [initialLoad, setInitialLoad] = useState(true)
    const [statusFilter, setStatusFilter] = useState('')

    useEffect(() => {
        const timer = setTimeout(() => {
            const fetch = async () => {
                try {
                    const params = { branch_id: currentBranch?.id }
                    if (statusFilter) params.status = statusFilter
                    const res = await deliveryOrdersAPI.list(params)
                    setOrders(res.data)
                } catch (err) {
                    showToast(t('common.error'), 'error')
                } finally {
                    setLoading(false)
                    setInitialLoad(false)
                }
            }
            fetch()
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch, statusFilter])

    if (initialLoad) return <PageLoading />

    const statusColors = {
        draft: 'draft', confirmed: 'confirmed', shipped: 'info',
        delivered: 'success', invoiced: 'posted', cancelled: 'cancelled'
    }

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">🚚 {t('delivery_orders.title')}</h1>
                    <p className="workspace-subtitle">{t('delivery_orders.subtitle')}</p>
                </div>
                <div className="header-actions">
                    <select className="form-select" value={statusFilter} onChange={e => setStatusFilter(e.target.value)} style={{ width: 150 }}>
                        <option value="">{t('common.all_statuses')}</option>
                        <option value="draft">{t('common.draft')}</option>
                        <option value="confirmed">{t('common.confirmed')}</option>
                        <option value="shipped">{t('delivery_orders.shipped')}</option>
                        <option value="delivered">{t('delivery_orders.delivered')}</option>
                        <option value="invoiced">{t('delivery_orders.invoiced')}</option>
                    </select>
                    <Link to="/sales/delivery-orders/new" className="btn btn-primary">
                        + {t('delivery_orders.create_new')}
                    </Link>
                </div>
            </div>

            <div className="card">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('delivery_orders.do_number')}</th>
                            <th>{t('common.customer')}</th>
                            <th>{t('common.date')}</th>
                            <th>{t('delivery_orders.shipping_date')}</th>
                            <th>{t('common.total')}</th>
                            <th>{t('common.status_title')}</th>
                            <th>{t('common.actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {orders.length === 0 ? (
                            <tr><td colSpan="7" className="text-center py-5 text-muted">{t('delivery_orders.empty')}</td></tr>
                        ) : orders.map(o => (
                            <tr key={o.id}>
                                <td className="font-medium text-primary">{o.do_number}</td>
                                <td>{o.party_name}</td>
                                <td>{formatShortDate(o.do_date)}</td>
                                <td>{o.shipping_date ? formatShortDate(o.shipping_date) : '-'}</td>
                                <td className="font-bold">{formatNumber(o.total_amount)} <small>{currency}</small></td>
                                <td><span className={`status-badge ${statusColors[o.status] || o.status}`}>{t(`delivery_orders.status_${o.status}`, o.status)}</span></td>
                                <td>
                                    <button onClick={() => navigate(`/sales/delivery-orders/${o.id}`)} className="btn-icon" title={t('common.view')}>👁️</button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    )
}

export default DeliveryOrders
