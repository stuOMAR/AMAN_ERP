import { useState, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { getCurrency, hasPermission } from '../../utils/auth'
import { purchasesAPI } from '../../utils/api'
import { useTranslation } from 'react-i18next'
import { formatShortDate } from '../../utils/dateUtils'
import { useBranch } from '../../context/BranchContext'
import { useToast } from '../../context/ToastContext'
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

function BuyingOrders() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { currentBranch } = useBranch()
    const { showToast } = useToast()
    const currency = getCurrency()
    const [orders, setOrders] = useState([])
    const [loading, setLoading] = useState(true)
    const [initialLoad, setInitialLoad] = useState(true)
    const [approving, setApproving] = useState(null)

    const fetchOrders = async () => {
        try {
            setLoading(true)
            const response = await purchasesAPI.listOrders({ branch_id: currentBranch?.id })
            setOrders(response.data)
        } catch (err) {
            showToast(t('common.error'), 'error')
        } finally {
            setLoading(false)
            setInitialLoad(false)
        }
    }

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchOrders()
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch])

    const handleApprove = async (id) => {
        if (!window.confirm(t('buying.orders.confirm_approve'))) return
        try {
            setApproving(id)
            await purchasesAPI.approveOrder(id)
            fetchOrders()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        } finally {
            setApproving(null)
        }
    }

    const getStatusBadge = (status) => {
        const styles = {
            draft: { bg: '#f3f4f6', color: '#374151', label: t('buying.orders.status.draft') },
            approved: { bg: '#dbeafe', color: '#1d4ed8', label: t('buying.orders.status.approved') },
            partial: { bg: '#fef3c7', color: '#d97706', label: t('buying.orders.status.partial') },
            received: { bg: '#d1fae5', color: '#059669', label: t('buying.orders.status.received') },
            cancelled: { bg: '#fee2e2', color: '#dc2626', label: t('buying.orders.status.cancelled') }
        }
        const style = styles[status] || styles.draft
        return (
            <span style={{
                backgroundColor: style.bg,
                color: style.color,
                padding: '4px 12px',
                borderRadius: '12px',
                fontSize: '12px',
                fontWeight: '500'
            }}>
                {style.label}
            </span>
        )
    }

    if (initialLoad && !orders.length) return <PageLoading />

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">{t('buying.orders.title')}</h1>
                    <p className="workspace-subtitle">{t('buying.orders.subtitle')}</p>
                </div>
                <div className="header-actions">
                    <Link to="/buying/orders/new" className="btn btn-primary">
                        + {t('buying.orders.new_order')}
                    </Link>
                    <Link to="/buying" className="btn btn-secondary">
                        {t('buying.orders.back')}
                    </Link>
                </div>
            </div>

            <div className="card">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('buying.orders.table.order_number')}</th>
                            <th>{t('buying.orders.table.supplier')}</th>
                            <th>{t('buying.orders.table.order_date')}</th>
                            <th>{t('buying.orders.table.expected_date')}</th>
                            <th>{t('buying.orders.table.total')}</th>
                            <th>{t('buying.orders.table.status')}</th>
                            <th>{t('buying.orders.table.actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {orders.length === 0 ? (
                            <tr>
                                <td colSpan="7" className="text-center py-5 text-muted">{t('buying.orders.empty')}</td>
                            </tr>
                        ) : (
                            orders.map(order => (
                                <tr key={order.id}>
                                    <td
                                        className="font-medium text-primary"
                                        style={{ cursor: 'pointer' }}
                                        onClick={() => navigate(`/buying/orders/${order.id}`)}
                                    >
                                        {order.po_number}
                                    </td>
                                    <td>{order.supplier_name}</td>
                                    <td>{formatShortDate(order.order_date)}</td>
                                    <td>{order.expected_date ? formatShortDate(order.expected_date) : '-'}</td>
                                    <td className="font-bold">
                                        {Number(order.total).toLocaleString()} <small>{currency}</small>
                                    </td>
                                    <td>{getStatusBadge(order.status)}</td>
                                    <td>
                                        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                                            <button
                                                onClick={() => navigate(`/buying/orders/${order.id}`)}
                                                className="btn btn-sm btn-secondary"
                                                title={t('common.view_details')}
                                            >
                                                👁️ {t('common.view')}
                                            </button>
                                            {order.status === 'draft' && hasPermission('buying.approve') && (
                                                <button
                                                    onClick={() => handleApprove(order.id)}
                                                    className="btn btn-sm btn-success"
                                                    disabled={approving === order.id}
                                                >
                                                    {approving === order.id ? '...' : `✓ ${t('buying.orders.approve')}`}
                                                </button>
                                            )}
                                            {(order.status === 'approved' || order.status === 'partial') && hasPermission('buying.receive') && (
                                                <button
                                                    onClick={() => navigate(`/buying/orders/${order.id}/receive`)}
                                                    className="btn btn-sm btn-primary"
                                                >
                                                    📥 {t('buying.orders.receive')}
                                                </button>
                                            )}
                                        </div>
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

export default BuyingOrders
