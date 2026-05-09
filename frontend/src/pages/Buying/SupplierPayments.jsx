import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { purchasesAPI } from '../../utils/api'
import { getCurrency } from '../../utils/auth'
import { useTranslation } from 'react-i18next'
import { useBranch } from '../../context/BranchContext'
import { useToast } from '../../context/ToastContext'
import { formatShortDate } from '../../utils/dateUtils';
import { PageLoading } from '../../components/common/LoadingStates';
import { formatNumber } from '../../utils/format'
import BackButton from '../../components/common/BackButton';


function SupplierPayments() {
    const { t } = useTranslation()
    const { currentBranch } = useBranch()
    const { showToast } = useToast()
    const currency = getCurrency()
    const [payments, setPayments] = useState([])
    const [loading, setLoading] = useState(true)
    const [initialLoad, setInitialLoad] = useState(true)
    const [error, setError] = useState(null)

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchPayments()
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch])

    const fetchPayments = async () => {
        try {
            setLoading(true)
            const response = await purchasesAPI.listPayments({ branch_id: currentBranch?.id })
            setPayments(response.data)
        } catch (err) {
            showToast(t('common.error'), 'error')
            setError(t('common.error_loading'))
        } finally {
            setLoading(false)
            setInitialLoad(false)
        }
    }

    if (initialLoad && !payments.length) {
        return (
            <div className="workspace fade-in">
                {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
                <div className="workspace-header">
                    <BackButton />
                    <h1 className="workspace-title">{t('buying.supplier_payments.title')}</h1>
                </div>
                <PageLoading />
            </div>
        )
    }

    if (error) {
        return (
            <div className="workspace fade-in">
                <div className="workspace-header">
                    <h1 className="workspace-title">{t('buying.supplier_payments.title')}</h1>
                </div>
                <div className="alert alert-error">{error}</div>
            </div>
        )
    }

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <h1 className="workspace-title">{t('buying.supplier_payments.title')}</h1>
                <p className="workspace-subtitle">{t('buying.supplier_payments.subtitle')}</p>
            </div>

            <div className="workspace-actions">
                <Link to="/buying/payments/new" className="btn btn-primary">
                    <span style={{ marginLeft: '8px' }}>+</span>
                    {t('buying.supplier_payments.new_voucher')}
                </Link>
            </div>

            <div className="card">
                {payments.length === 0 ? (
                    <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-secondary)' }}>
                        <p>{t('buying.supplier_payments.no_vouchers')}</p>
                    </div>
                ) : (
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>{t('buying.supplier_payments.voucher_no')}</th>
                                <th>{t('buying.supplier_payments.supplier')}</th>
                                <th>{t('buying.supplier_payments.date')}</th>
                                <th>{t('buying.supplier_payments.amount')}</th>
                                <th>{t('buying.supplier_payments.payment_method')}</th>
                                <th>{t('buying.supplier_payments.status')}</th>
                                <th>{t('buying.supplier_payments.actions')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {payments.map(payment => (
                                <tr key={payment.id}>
                                    <td>
                                        <Link to={`/buying/payments/${payment.id}`} className="link">
                                            {payment.voucher_number}
                                        </Link>
                                    </td>
                                    <td>{payment.supplier_name}</td>
                                    <td>{formatShortDate(payment.voucher_date)}</td>
                                    <td className="font-bold">
                                        {formatNumber(payment.amount)} {payment.currency || currency}
                                    </td>
                                    <td>
                                        <span className="badge badge-info">
                                            {payment.payment_method === 'cash' ? t('common.cash') :
                                                payment.payment_method === 'bank' ? t('common.bank') :
                                                    payment.payment_method === 'check' ? t('common.check') : payment.payment_method}
                                        </span>
                                    </td>
                                    <td>
                                        <span className={`badge ${payment.status === 'posted' ? 'badge-success' :
                                            payment.status === 'draft' ? 'badge-warning' : 'badge-secondary'
                                            }`}>
                                            {payment.status === 'posted' ? t('common.posted') :
                                                payment.status === 'draft' ? t('common.draft') : payment.status}
                                        </span>
                                    </td>
                                    <td>
                                        <Link to={`/buying/payments/${payment.id}`} className="btn btn-sm btn-secondary">
                                            {t('common.view')}
                                        </Link>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </div>
        </div>
    )
}

export default SupplierPayments
