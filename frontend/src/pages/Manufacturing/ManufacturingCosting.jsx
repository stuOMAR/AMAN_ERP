import { useState, useEffect } from 'react'
import { manufacturingCostingAPI, manufacturingAPI } from '../../utils/api'
import Decimal from 'decimal.js'
import { toastEmitter } from '../../utils/toastEmitter'
import { getCurrency } from '../../utils/auth'
import { useTranslation } from 'react-i18next'
import { useToast } from '../../context/ToastContext'
import BackButton from '../../components/common/BackButton'
import { formatNumber } from '../../utils/format'
import { PageLoading } from '../../components/common/LoadingStates'

function ManufacturingCosting() {
    const { t } = useTranslation()
    const { showToast } = useToast()
    const currency = getCurrency()
    const [report, setReport] = useState(null)
    const [loading, setLoading] = useState(true)
    const [calculating, setCalculating] = useState(false)
    const [orders, setOrders] = useState([])
    const [selectedOrder, setSelectedOrder] = useState('')

    useEffect(() => {
        Promise.all([
            manufacturingCostingAPI.getCostVarianceReport(),
            manufacturingAPI.listOrders({ status: 'completed' })
        ]).then(([rptRes, ordRes]) => {
            setReport(rptRes.data)
            setOrders(ordRes.data || [])
        }).catch(() => toastEmitter.emit(t('common.error'), 'error')).finally(() => setLoading(false))
    }, [])

    const handleCalculate = async () => {
        if (!selectedOrder) return
        setCalculating(true)
        try {
            await manufacturingCostingAPI.calculateCost(selectedOrder)
            showToast(t('manufacturing_costing.calculated'), 'success')
            const rpt = await manufacturingCostingAPI.getCostVarianceReport()
            setReport(rpt.data)
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        } finally { setCalculating(false) }
    }

    if (loading) return <PageLoading />

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">💰 {t('manufacturing_costing.title')}</h1>
                    <p className="workspace-subtitle">{t('manufacturing_costing.subtitle')}</p>
                </div>
            </div>

            {/* Calculate Cost for Order */}
            <div className="card p-4 mb-4">
                <h3 className="card-title mb-3">{t('manufacturing_costing.calculate_for_order')}</h3>
                <div className="form-grid-3">
                    <div className="form-group">
                        <label>{t('manufacturing_costing.production_order')}</label>
                        <select className="form-select" value={selectedOrder} onChange={e => setSelectedOrder(e.target.value)}>
                            <option value="">{t('common.select')}</option>
                            {orders.map(o => (
                                <option key={o.id} value={o.id}>{o.order_number || `#${o.id}`} - {o.product_name}</option>
                            ))}
                        </select>
                    </div>
                    <div className="form-group" style={{ display: 'flex', alignItems: 'flex-end' }}>
                        <button className="btn btn-primary" onClick={handleCalculate} disabled={!selectedOrder || calculating}>
                            {calculating ? t('common.calculating') : t('manufacturing_costing.calculate')}
                        </button>
                    </div>
                </div>
            </div>

            {/* Variance Report */}
            {report && (
                <div className="card">
                    <div className="p-4"><h3 className="card-title">{t('manufacturing_costing.variance_report')}</h3></div>
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>{t('manufacturing_costing.order')}</th>
                                <th>{t('manufacturing_costing.product')}</th>
                                <th>{t('manufacturing_costing.estimated_cost')}</th>
                                <th>{t('manufacturing_costing.actual_cost')}</th>
                                <th>{t('manufacturing_costing.variance')}</th>
                                <th>{t('manufacturing_costing.variance_pct')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {(report.orders || report).map((o, i) => {
                                const estimated = new Decimal(o.estimated_cost || '0')
                                const actual = new Decimal(o.actual_cost || '0')
                                const variance = actual.minus(estimated)
                                const pct = !estimated.isZero() ? variance.div(estimated).times(100).toFixed(1) : '-'
                                return (
                                    <tr key={i}>
                                        <td className="font-medium">{o.order_number || `#${o.id}`}</td>
                                        <td>{o.product_name}</td>
                                        <td>{formatNumber(o.estimated_cost)} {currency}</td>
                                        <td>{formatNumber(o.actual_cost)} {currency}</td>
                                        <td className={variance > 0 ? 'text-danger' : 'text-success'}>
                                            {variance > 0 ? '+' : ''}{formatNumber(variance)} {currency}
                                        </td>
                                        <td className={variance > 0 ? 'text-danger' : 'text-success'}>
                                            {pct}%
                                        </td>
                                    </tr>
                                )
                            })}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    )
}

export default ManufacturingCosting
