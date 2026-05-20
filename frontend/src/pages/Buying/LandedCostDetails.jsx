import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { landedCostsAPI } from '../../utils/api'
import { getCurrency } from '../../utils/auth'
import { useTranslation } from 'react-i18next'
import { useToast } from '../../context/ToastContext'
import BackButton from '../../components/common/BackButton'
import { PageLoading } from '../../components/common/LoadingStates'
import { formatNumber } from '../../utils/format'

function LandedCostDetails() {
    const { id } = useParams()
    const { t } = useTranslation()
    const { showToast } = useToast()
    const currency = getCurrency()
    const [lc, setLC] = useState(null)
    const [loading, setLoading] = useState(true)
    const [allocMethod, setAllocMethod] = useState('by_value')
    const [actionLoading, setActionLoading] = useState(false)

    const fetchLC = async () => {
        try { const r = await landedCostsAPI.get(id); setLC(r.data) }
        catch { showToast(t('common.error'), 'error') }
        finally { setLoading(false) }
    }

    useEffect(() => { fetchLC() }, [id])

    const handleAllocate = async () => {
        setActionLoading(true)
        try {
            await landedCostsAPI.allocate(id, { method: allocMethod })
            showToast(t('landed_costs.allocated'), 'success')
            fetchLC()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        } finally { setActionLoading(false) }
    }

    const handlePost = async () => {
        setActionLoading(true)
        try {
            await landedCostsAPI.post(id)
            showToast(t('landed_costs.posted'), 'success')
            fetchLC()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        } finally { setActionLoading(false) }
    }

    if (loading) return <PageLoading />
    if (!lc) return <div className="p-4 text-muted">{t('common.not_found')}</div>

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">📦 {lc.lc_number}</h1>
                    <span className={`status-badge ${lc.status}`}>{lc.status}</span>
                </div>
                <div className="header-actions">
                    {lc.status === 'draft' && (
                        <>
                            <select className="form-select" value={allocMethod} onChange={e => setAllocMethod(e.target.value)} style={{ width: 150 }}>
                                <option value="by_value">{t('landed_costs.by_value')}</option>
                                <option value="by_quantity">{t('landed_costs.by_quantity')}</option>
                                <option value="by_weight">{t('landed_costs.by_weight')}</option>
                                <option value="equal">{t('landed_costs.equal')}</option>
                            </select>
                            <button className="btn btn-primary" disabled={actionLoading} onClick={handleAllocate}>
                                📊 {t('landed_costs.allocate')}
                            </button>
                        </>
                    )}
                    {lc.status === 'allocated' && (
                        <button className="btn btn-success" disabled={actionLoading} onClick={handlePost}>
                            ✅ {t('common.post')}
                        </button>
                    )}
                </div>
            </div>

            <div className="card p-4">
                <h3 className="card-title">{t('landed_costs.cost_items')}</h3>
                <table className="data-table mt-2">
                    <thead><tr><th>{t('common.type')}</th><th>{t('common.description')}</th><th>{t('common.amount')}</th></tr></thead>
                    <tbody>
                        {(lc.items || []).map((item, i) => (
                            <tr key={i}>
                                <td>{t(`landed_costs.${item.cost_type}`, item.cost_type)}</td>
                                <td>{item.description || '-'}</td>
                                <td className="font-bold">{formatNumber(item.amount)} {currency}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                <div className="mt-2 text-lg font-bold">
                    {t('landed_costs.total_cost')}: {formatNumber(lc.total_cost)} {currency}
                </div>
            </div>

            {(lc.allocations || []).length > 0 && (
                <div className="card mt-4 p-4">
                    <h3 className="card-title">{t('landed_costs.allocations')}</h3>
                    <table className="data-table mt-2">
                        <thead>
                            <tr>
                                <th>{t('common.product')}</th>
                                <th>{t('landed_costs.original_cost')}</th>
                                <th>{t('landed_costs.allocated_amount')}</th>
                                <th>{t('landed_costs.new_cost')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {lc.allocations.map((a, i) => (
                                <tr key={i}>
                                    <td>{a.product_name || `#${a.line_id}`}</td>
                                    <td>{formatNumber(a.original_cost)} {currency}</td>
                                    <td className="text-primary">{formatNumber(a.allocated_amount)} {currency}</td>
                                    <td className="font-bold">{formatNumber(a.new_cost)} {currency}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    )
}

export default LandedCostDetails
