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

function SalesQuotations() {
    const { t } = useTranslation()
    const { showToast } = useToast()
    const navigate = useNavigate()
    const { currentBranch } = useBranch()
    const currency = getCurrency()
    const [quotations, setQuotations] = useState([])
    const [loading, setLoading] = useState(true)
    const [initialLoad, setInitialLoad] = useState(true)

    useEffect(() => {
        const timer = setTimeout(() => {
            const fetchQuotations = async () => {
                try {
                    const response = await salesAPI.listQuotations({ branch_id: currentBranch?.id })
                    setQuotations(response.data)
                } catch (err) {
                    showToast(t('common.error'), 'error')
                } finally {
                    setLoading(false)
                    setInitialLoad(false)
                }
            }
            fetchQuotations()
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
                    <h1 className="workspace-title">💬 {t('sales.quotations.title')}</h1>
                    <p className="workspace-subtitle">{t('sales.quotations.subtitle')}</p>
                </div>
                <div className="header-actions">
                    <Link to="/sales/quotations/new" className="btn btn-primary">
                        + {t('sales.quotations.create_new')}
                    </Link>
                    <Link to="/sales" className="btn btn-secondary">
                        {t('sales.quotations.back')}
                    </Link>
                </div>
            </div>

            <div className="card">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('sales.quotations.table.number')}</th>
                            <th>{t('sales.quotations.table.customer')}</th>
                            <th>{t('sales.quotations.table.date')}</th>
                            <th>{t('sales.quotations.table.expiry')}</th>
                            <th>{t('sales.quotations.table.total')}</th>
                            <th>{t('sales.quotations.table.status')}</th>
                            <th>{t('sales.quotations.table.actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {quotations.length === 0 ? (
                            <tr>
                                <td colSpan="7" className="text-center py-5 text-muted">{t('sales.quotations.empty')}</td>
                            </tr>
                        ) : (
                            quotations.map(quote => (
                                <tr key={quote.id}>
                                    <td className="font-medium text-primary">{quote.sq_number}</td>
                                    <td>{quote.customer_name}</td>
                                    <td>{formatShortDate(quote.quotation_date)}</td>
                                    <td>{quote.expiry_date ? formatShortDate(quote.expiry_date) : '-'}</td>
                                    <td className="font-bold">
                                        {formatNumber(quote.total)} <small>{currency}</small>
                                    </td>
                                    <td>
                                        <span className={`status-badge ${quote.status}`}>
                                            {quote.status === 'draft' ? t('sales.quotations.status.draft') :
                                                quote.status === 'sent' ? t('sales.quotations.status.sent') :
                                                    quote.status === 'accepted' ? t('sales.quotations.status.accepted') :
                                                        quote.status === 'converted' ? t('sales.quotations.status.converted') : quote.status}
                                        </span>
                                    </td>
                                    <td>
                                        <button
                                            onClick={() => navigate(`/sales/quotations/${quote.id}`)}
                                            className="btn-icon"
                                            title={t('sales.quotations.table.actions')}
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

export default SalesQuotations
