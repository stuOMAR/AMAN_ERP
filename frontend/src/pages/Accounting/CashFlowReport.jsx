import { useState, useEffect } from 'react'
import { reportsAPI } from '../../utils/api'
import { useBranch } from '../../context/BranchContext'
import { useTranslation } from 'react-i18next'
import { formatNumber } from '../../utils/format'
import { getCurrency } from '../../utils/auth'
import CustomDatePicker from '../../components/common/CustomDatePicker'
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

function CashFlowReport() {
    const { t } = useTranslation()
    const { currentBranch } = useBranch()
    const [startDate, setStartDate] = useState(new Date(new Date().getFullYear(), new Date().getMonth(), 1))
    const [endDate, setEndDate] = useState(new Date())
    const [data, setData] = useState(null)
    const [loading, setLoading] = useState(false)
    const [initialLoad, setInitialLoad] = useState(true)
    const [error, setError] = useState(null)
    const currency = getCurrency()

    const fetchData = async () => {
        try {
            setLoading(true)
            setError(null)
            const params = {
                start_date: startDate.toISOString().split('T')[0],
                end_date: endDate.toISOString().split('T')[0],
                branch_id: currentBranch?.id
            }
            const response = await reportsAPI.getCashFlow(params)
            setData(response.data)
        } catch (err) {
            console.error("Failed to fetch cash flow", err)
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
    }, [currentBranch, startDate, endDate])

    return (
        <div className="workspace fade-in">
            <div className="workspace-header display-flex justify-between align-center">
                <BackButton />
                <div>
                    <h1 className="workspace-title">{t('reports.cash_flow.title')}</h1>
                    <p className="workspace-subtitle">{t('reports.cash_flow.subtitle')}</p>
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

            <div className="card mb-4 mt-4">
                <div className="card-body">
                    <div className="display-flex gap-4 align-center">
                        <div style={{ width: '200px' }}>
                            <label className="form-label">{t('common.start_date')}</label>
                            <CustomDatePicker
                                selected={startDate}
                                onChange={date => setStartDate(date)}
                                className="form-input"
                            />
                        </div>
                        <div style={{ width: '200px' }}>
                            <label className="form-label">{t('common.end_date')}</label>
                            <CustomDatePicker
                                selected={endDate}
                                onChange={date => setEndDate(date)}
                                className="form-input"
                            />
                        </div>
                    </div>
                </div>
            </div>

            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            {initialLoad && !data ? (
                <PageLoading />
            ) : error ? (
                <div className="alert alert-danger">{error}</div>
            ) : data && (
                <div className="display-flex flex-column gap-4">
                    {/* Summary Cards */}
                    <div className="metrics-grid">
                        <div className="metric-card">
                            <div className="metric-label">{t('reports.cash_flow.total_inflow')}</div>
                            <div className="metric-value text-success">{formatNumber(data.total_inflow)} <small>{currency}</small></div>
                        </div>
                        <div className="metric-card">
                            <div className="metric-label">{t('reports.cash_flow.total_outflow')}</div>
                            <div className="metric-value text-danger">{formatNumber(data.total_outflow)} <small>{currency}</small></div>
                        </div>
                        <div className="metric-card">
                            <div className="metric-label">{t('reports.cash_flow.net_cash_flow')}</div>
                            <div className={`metric-value ${data.net_cash_flow >= 0 ? 'text-primary' : 'text-danger'}`}>
                                {formatNumber(data.net_cash_flow)} <small>{currency}</small>
                            </div>
                        </div>
                    </div>

                    <div className="grid-2">
                        {/* Inflows Table */}
                        <div className="card">
                            <div className="card-header">
                                <h3 className="card-title">{t('reports.cash_flow.inflow_details')}</h3>
                            </div>
                            <div className="data-table-container">
                                <table className="data-table">
                                    <thead>
                                        <tr>
                                            <th>{t('reports.cash_flow.category')}</th>
                                            <th>{t('reports.cash_flow.type')}</th>
                                            <th className="text-end">{t('reports.cash_flow.amount')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {(data.inflows || []).map((item, idx) => (
                                            <tr key={idx}>
                                                <td>{item.category}</td>
                                                <td><span className="badge badge-success">{item.account_type}</span></td>
                                                <td className="text-end">{formatNumber(item.amount)}</td>
                                            </tr>
                                        ))}
                                        {(!data.inflows || data.inflows.length === 0) && (
                                            <tr>
                                                <td colSpan="3" className="text-center p-4 text-muted">
                                                    {t('common.no_data')}
                                                </td>
                                            </tr>
                                        )}
                                    </tbody>
                                    <tfoot>
                                        <tr className="fw-bold">
                                            <td colSpan="2">{t('reports.cash_flow.total_inflow')}</td>
                                            <td className="text-end text-success">{formatNumber(data.total_inflow)}</td>
                                        </tr>
                                    </tfoot>
                                </table>
                            </div>
                        </div>

                        {/* Outflows Table */}
                        <div className="card">
                            <div className="card-header">
                                <h3 className="card-title">{t('reports.cash_flow.outflow_details')}</h3>
                            </div>
                            <div className="table-responsive">
                                <table className="data-table">
                                    <thead>
                                        <tr>
                                            <th>{t('reports.cash_flow.category')}</th>
                                            <th>{t('reports.cash_flow.type')}</th>
                                            <th className="text-end">{t('reports.cash_flow.amount')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {(data.outflows || []).map((item, idx) => (
                                            <tr key={idx}>
                                                <td>{item.category}</td>
                                                <td><span className="badge badge-danger">{item.account_type}</span></td>
                                                <td className="text-end">{formatNumber(item.amount)}</td>
                                            </tr>
                                        ))}
                                        {(!data.outflows || data.outflows.length === 0) && (
                                            <tr>
                                                <td colSpan="3" className="text-center p-4 text-muted">
                                                    {t('common.no_data')}
                                                </td>
                                            </tr>
                                        )}
                                    </tbody>
                                    <tfoot>
                                        <tr className="fw-bold">
                                            <td colSpan="2">{t('reports.cash_flow.total_outflow')}</td>
                                            <td className="text-end text-danger">{formatNumber(data.total_outflow)}</td>
                                        </tr>
                                    </tfoot>
                                </table>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}

export default CashFlowReport
