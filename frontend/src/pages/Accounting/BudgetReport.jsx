import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { budgetsAPI } from '../../utils/api'
import { useBranch } from '../../context/BranchContext'
import { useTranslation } from 'react-i18next'
import { formatNumber } from '../../utils/format'
import { getCurrency } from '../../utils/auth'
import CustomDatePicker from '../../components/common/CustomDatePicker'
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

function BudgetReport() {
    const { t } = useTranslation()
    const { id: urlBudgetId } = useParams()
    const { currentBranch } = useBranch()
    const [budgets, setBudgets] = useState([])
    const [selectedBudgetId, setSelectedBudgetId] = useState('')
    const [data, setData] = useState(null)
    const [loading, setLoading] = useState(false)
    const [initialLoad, setInitialLoad] = useState(true)
    const [error, setError] = useState(null)
    const [fromDate, setFromDate] = useState('')
    const [toDate, setToDate] = useState('')
    const currency = getCurrency()

    useEffect(() => {
        const fetchBudgets = async () => {
            try {
                const params = {};
                if (currentBranch?.id) params.branch_id = currentBranch.id;
                const response = await budgetsAPI.list(params)
                setBudgets(response.data)
                if (urlBudgetId) {
                    setSelectedBudgetId(parseInt(urlBudgetId))
                } else if (response.data.length > 0) {
                    setSelectedBudgetId(response.data[0].id)
                }
            } catch (err) {
                console.error("Failed to fetch budgets", err)
            }
        }
        fetchBudgets()
    }, [currentBranch, urlBudgetId])

    const fetchData = async () => {
        if (!selectedBudgetId) return
        try {
            setLoading(true)
            setError(null)

            const params = {}
            if (fromDate) params.from_date = fromDate
            if (toDate) params.to_date = toDate
            if (currentBranch?.id) params.branch_id = currentBranch.id

            const response = await budgetsAPI.getReport(selectedBudgetId, params)
            setData(response.data)
        } catch (err) {
            console.error("Failed to fetch budget report", err)
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
    }, [selectedBudgetId, currentBranch, fromDate, toDate])

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                        <BackButton />
                        <div>
                            <h1 className="workspace-title">{t('reports.budget_vs_actual.title')}</h1>
                        </div>
                    </div>
                    <div style={{ display: 'flex', gap: '12px' }}>
                        <div style={{ minWidth: '180px' }}>
                            <label className="form-label">{t('reports.budget_vs_actual.select_budget')}</label>
                            <select
                                className="form-input w-full"
                                value={selectedBudgetId}
                                onChange={e => setSelectedBudgetId(e.target.value)}
                            >
                                <option value="">{t('common.select')}</option>
                                {budgets.map(b => (
                                    <option key={b.id} value={b.id}>{b.name}</option>
                                ))}
                            </select>
                        </div>
                        <CustomDatePicker
                            label={t('common.start_date')}
                            selected={fromDate}
                            onChange={setFromDate}
                        />
                        <CustomDatePicker
                            label={t('common.end_date')}
                            selected={toDate}
                            onChange={setToDate}
                        />
                        <button className="btn btn-secondary" onClick={() => window.print()} style={{ alignSelf: 'flex-end', height: '42px' }}>
                            🖨️ {t('common.print')}
                        </button>
                    </div>
                </div>
            </div>

            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            {initialLoad && !data ? (
                <PageLoading />
            ) : error ? (
                <div className="alert alert-danger">{error}</div>
            ) : data && (
                <div className="card card-flush" style={{ overflow: 'hidden' }}>
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>{t('accounting.coa.account')}</th>
                                <th className="text-center">{t('reports.budget_vs_actual.planned')} ({currency})</th>
                                <th className="text-center">{t('reports.budget_vs_actual.actual')} ({currency})</th>
                                <th className="text-center">{t('reports.budget_vs_actual.variance')} (%)</th>
                                <th className="text-center">{t('common.status_title')}</th>
                                <th className="text-center">{t('reports.budget_vs_actual.performance')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {data.map((item, idx) => {
                                return (
                                    <tr key={idx}>
                                        <td>
                                            <div style={{ fontWeight: '500', marginBottom: '4px' }}>
                                                {item.account_name}
                                            </div>
                                            <div style={{ fontSize: '12px', opacity: 0.6 }}>
                                                {item.account_number}
                                            </div>
                                        </td>
                                        <td className="text-center">{formatNumber(item.planned)}</td>
                                        <td className="text-center">{formatNumber(item.actual)}</td>
                                        <td className="text-center" style={{ fontWeight: '600' }}>
                                            <span style={{ color: item.is_over_budget ? '#dc2626' : '#059669' }}>
                                                {item.variance_percentage > 0 ? '+' : ''}{Math.round(item.variance_percentage)}%
                                            </span>
                                        </td>
                                        <td className="text-center">
                                            {item.is_over_budget ? (
                                                <span className="badge badge-danger">
                                                    ⚠️ {t('accounting.budgets.over_budget')}
                                                </span>
                                            ) : (
                                                <span className="badge badge-success">
                                                    ✅ {t('accounting.budgets.within_budget')}
                                                </span>
                                            )}
                                        </td>
                                        <td>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                                                <div style={{ flex: 1, height: '6px', background: '#f3f4f6', borderRadius: '3px', overflow: 'hidden' }}>
                                                    <div style={{
                                                        height: '100%',
                                                        width: `${Math.min(item.usage_percentage, 100)}%`,
                                                        background: item.is_over_budget ? '#dc2626' : '#10b981',
                                                        borderRadius: '3px'
                                                    }} />
                                                </div>
                                                <span style={{ fontSize: '12px', opacity: 0.7, minWidth: '40px', textAlign: 'right' }}>
                                                    {Math.round(item.usage_percentage)}%
                                                </span>
                                            </div>
                                        </td>
                                    </tr>
                                );
                            })}
                            {data.length === 0 && (
                                <tr>
                                    <td colSpan="6" className="start-guide">
                                        <div style={{ padding: '40px', textAlign: 'center' }}>
                                            <div style={{ fontSize: '40px', marginBottom: '12px' }}>📊</div>
                                            <div style={{ opacity: 0.6 }}>{t('common.no_data')}</div>
                                        </div>
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    )
}

export default BudgetReport
