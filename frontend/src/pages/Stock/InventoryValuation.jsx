import { useState, useEffect } from 'react'
import { inventoryAPI } from '../../utils/api'
import { useBranch } from '../../context/BranchContext'
import { useToast } from '../../context/ToastContext'
import { useTranslation } from 'react-i18next'
import { formatNumber } from '../../utils/format'
import { getCurrency, hasPermission } from '../../utils/auth'
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

function InventoryValuation() {
    const { t } = useTranslation()
    const { currentBranch } = useBranch()
    const { showToast } = useToast()
    const [data, setData] = useState([])
    const [loading, setLoading] = useState(false)
    const [initialLoad, setInitialLoad] = useState(true)
    const [error, setError] = useState(null)
    const currency = getCurrency()

    const fetchData = async () => {
        try {
            setLoading(true)
            setError(null)
            const response = await inventoryAPI.getValuationReport({ branch_id: currentBranch?.id })
            setData(response.data)
        } catch (err) {
            showToast(t('errors.fetch_failed'), 'error')
            setError(t('errors.fetch_failed'))
        } finally {
            setLoading(false)
            setInitialLoad(false)
        }
    }

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchData()
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch])

    const totalValuation = data.reduce((sum, item) => sum + item.valuation, 0)
    const totalItems = data.length

    return (
        <div className="workspace fade-in">
            <div className="workspace-header display-flex justify-between align-center">
                <BackButton />
                <div>
                    <h1 className="workspace-title">{t('reports.inventory_valuation.title')}</h1>
                    <p className="workspace-subtitle">{t('reports.inventory_valuation.subtitle')}</p>
                </div>
                <div className="display-flex gap-2">
                    <button className="btn btn-secondary" onClick={() => window.print()}>
                        {t('common.print')}
                    </button>
                    <button className="btn btn-primary" onClick={fetchData}>
                        {t('common.refresh')}
                    </button>
                </div>
            </div>

            <div className="metrics-grid mb-6 mt-4">
                <div className="metric-card">
                    <div className="metric-label">{t('reports.inventory_valuation.total_value')}</div>
                    <div className="metric-value">{formatNumber(totalValuation)} <small>{currency}</small></div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('reports.inventory_valuation.item_count')}</div>
                    <div className="metric-value">{totalItems}</div>
                </div>
            </div>

            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}

            {initialLoad ? (
                <PageLoading />
            ) : error ? (
                <div className="alert alert-danger">{error}</div>
            ) : (
                <div className="card">
                    <div className="data-table-container">
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th>{t('inventory.product_code')}</th>
                                    <th>{t('inventory.product_name')}</th>
                                    <th>{t('inventory.category')}</th>
                                    <th className="text-center">{t('inventory.quantity')}</th>
                                    <th>{t('inventory.unit')}</th>
                                    {hasPermission('stock.view_cost') && (
                                        <>
                                            <th className="text-end">{t('inventory.cost_price')}</th>
                                            <th className="text-end">{t('reports.inventory_valuation.valuation')}</th>
                                        </>
                                    )}
                                </tr>
                            </thead>
                            <tbody>
                                {data.map((item) => (
                                    <tr key={item.id}>
                                        <td><code>{item.code}</code></td>
                                        <td>{item.name}</td>
                                        <td><span className="badge badge-light">{item.category}</span></td>
                                        <td className="text-center fw-bold">{formatNumber(item.quantity)}</td>
                                        <td>{item.unit}</td>
                                        {hasPermission('stock.view_cost') && (
                                            <>
                                                <td className="text-end">{formatNumber(item.cost)}</td>
                                                <td className="text-end fw-bold">{formatNumber(item.valuation)}</td>
                                            </>
                                        )}
                                    </tr>
                                ))}
                                {data.length === 0 && (
                                    <tr>
                                        <td colSpan={hasPermission('stock.view_cost') ? 7 : 5} className="text-center p-5 text-muted">
                                            {t('common.no_data')}
                                        </td>
                                    </tr>
                                )}
                            </tbody>
                            {data.length > 0 && hasPermission('stock.view_cost') && (
                                <tfoot>
                                    <tr className="fw-bold bg-light">
                                        <td colSpan="6" className="text-end">{t('reports.inventory_valuation.grand_total')}</td>
                                        <td className="text-end">{formatNumber(totalValuation)} {currency}</td>
                                    </tr>
                                </tfoot>
                            )}
                        </table>
                    </div>
                </div>
            )}
        </div>
    )
}

export default InventoryValuation
