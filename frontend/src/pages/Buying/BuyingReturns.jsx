import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { purchasesAPI } from '../../utils/api'
import { useTranslation } from 'react-i18next'
import { formatShortDate } from '../../utils/dateUtils'
import { useBranch } from '../../context/BranchContext'
import { useToast } from '../../context/ToastContext'
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

function BuyingReturns() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { currentBranch } = useBranch()
    const { showToast } = useToast()
    const [returns, setReturns] = useState([])
    const [loading, setLoading] = useState(true)
    const [initialLoad, setInitialLoad] = useState(true)
    const [error, setError] = useState(null)

    useEffect(() => {
        const fetchReturns = async () => {
            try {
                const response = await purchasesAPI.listReturns({ branch_id: currentBranch?.id })
                setReturns(response.data)
            } catch (err) {
                showToast(t('common.error'), 'error')
                setError(t('common.error_loading'))
            } finally {
                setLoading(false)
                setInitialLoad(false)
            }
        }
        const timer = setTimeout(() => {
            fetchReturns()
        }, 300)
        return () => clearTimeout(timer)
    }, [t, currentBranch])

    if (initialLoad && !returns.length) return <PageLoading />

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1 className="workspace-title">{t('buying.returns.title')}</h1>
                        <p className="workspace-subtitle">{t('buying.returns.subtitle')}</p>
                    </div>
                    <button className="btn btn-danger" onClick={() => navigate('/buying/returns/new')}>
                        <span style={{ marginLeft: '8px' }}>+</span>
                        {t('buying.returns.new_return')}
                    </button>
                </div>
            </div>

            {error && <div className="alert alert-error">{error}</div>}

            <div className="data-table-container">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('buying.returns.table.return_number')}</th>
                            <th>{t('buying.returns.table.supplier')}</th>
                            <th>{t('buying.returns.table.date')}</th>
                            <th>{t('buying.returns.table.total')}</th>
                            <th>{t('buying.returns.table.status')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {returns.length === 0 ? (
                            <tr>
                                <td colSpan="5" className="start-guide">
                                    <div style={{ padding: '40px', textAlign: 'center' }}>
                                        <div style={{ fontSize: '48px', marginBottom: '16px' }}>📦🔙</div>
                                        <h3>{t('buying.returns.empty.title')}</h3>
                                        <p>{t('buying.returns.empty.desc')}</p>
                                        <button className="btn btn-danger mt-4" onClick={() => navigate('/buying/returns/new')}>
                                            {t('buying.returns.empty.action')}
                                        </button>
                                    </div>
                                </td>
                            </tr>
                        ) : (
                            returns.map(ret => (
                                <tr key={ret.id} style={{ cursor: 'pointer' }} onClick={() => navigate(`/buying/returns/${ret.id}`)}>
                                    <td style={{ fontWeight: 'bold' }}>{ret.invoice_number}</td>
                                    <td>{ret.supplier_name}</td>
                                    <td>{formatShortDate(ret.invoice_date)}</td>
                                    <td>{Number(ret.total).toLocaleString()}</td>
                                    <td>
                                        <span className="badge badge-success">{t('buying.returns.status.posted')}</span>
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

export default BuyingReturns
