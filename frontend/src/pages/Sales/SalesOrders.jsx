import { useState, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { salesAPI } from '../../utils/api'
import { getCurrency } from '../../utils/auth'
import { useTranslation } from 'react-i18next'
import { formatShortDate } from '../../utils/dateUtils'
import { useBranch } from '../../context/BranchContext'
import { useToast } from '../../context/ToastContext'
import BackButton from '../../components/common/BackButton';
import { formatNumber } from '../../utils/format';
import { PageLoading } from '../../components/common/LoadingStates'

function SalesOrders() {
    const { t } = useTranslation()
    const { showToast } = useToast()
    const navigate = useNavigate()
    const { currentBranch } = useBranch()
    const currency = getCurrency()
    const [orders, setOrders] = useState([])
    const [loading, setLoading] = useState(true)
    const [initialLoad, setInitialLoad] = useState(true)

    useEffect(() => {
        const timer = setTimeout(() => {
            const fetchOrders = async () => {
                try {
                    const response = await salesAPI.listOrders({ branch_id: currentBranch?.id })
                    setOrders(response.data)
                } catch (err) {
                    showToast(t('common.error'), 'error')
                } finally {
                    setLoading(false)
                    setInitialLoad(false)
                }
            }
            fetchOrders()
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch])

    if (initialLoad) return <PageLoading />

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">🛒 {t('sales.orders.title')}</h1>
                    <p className="workspace-subtitle">{t('sales.orders.subtitle')}</p>
                </div>
                <div className="header-actions">
                    <Link to="/sales/orders/new" className="btn btn-primary">
                        + {t('sales.orders.create_new')}
                    </Link>
                    <Link to="/sales" className="btn btn-secondary">
                        {t('sales.orders.back')}
                    </Link>
                </div>
            </div>

            <div className="card">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('sales.orders.table.number')}</th>
                            <th>{t('sales.orders.table.customer')}</th>
                            <th>{t('sales.orders.table.date')}</th>
                            <th>{t('sales.orders.table.delivery_date')}</th>
                            <th>{t('sales.orders.table.total')}</th>
                            <th>{t('sales.orders.table.status')}</th>
                            <th>{t('sales.orders.table.actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {orders.length === 0 ? (
                            <tr>
                                <td colSpan="7" className="text-center py-5 text-muted">{t('sales.orders.empty')}</td>
                            </tr>
                        ) : (
                            orders.map(order => (
                                <tr key={order.id}>
                                    <td className="font-medium text-primary">{order.so_number}</td>
                                    <td>{order.customer_name}</td>
                                    <td>{formatShortDate(order.order_date)}</td>
                                    <td>{order.expected_delivery_date ? formatShortDate(order.expected_delivery_date) : '-'}</td>
                                    <td className="font-bold">
                                        {formatNumber(order.total)} <small>{currency}</small>
                                    </td>
                                    <td>
                                        <span className={`status-badge ${order.status}`}>
                                            {order.status === 'draft' ? t('sales.orders.status.draft') :
                                                order.status === 'confirmed' ? t('sales.orders.status.confirmed') :
                                                    order.status === 'delivered' ? t('sales.orders.status.delivered') : order.status}
                                        </span>
                                    </td>
                                    <td>
                                        <button
                                            onClick={() => navigate(`/sales/orders/${order.id}`)}
                                            className="btn-icon"
                                            title={t('sales.orders.table.actions')}
                                        >
                                            👁️
                                        </button>
                                    </td>
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>
        </div>
    )
}

export default SalesOrders
