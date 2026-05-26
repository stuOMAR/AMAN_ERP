import { useState, useEffect, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { dashboardAPI } from '../../services/dashboard'
import BackButton from '../../components/common/BackButton'
import { formatNumber } from '../../utils/format'
import {
    BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
    XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer
} from 'recharts'
import DateInput from '../../components/common/DateInput';

const CHART_COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042', '#8884D8', '#82CA9D', '#FFC658', '#FF6B6B']

const formatCellValue = (value) => {
    if (value === null || value === undefined || value === '') return ''
    const raw = String(value)
    return /^-?\d+(\.\d+)?$/.test(raw) ? formatNumber(raw) : raw
}

function KPICard({ title, data, dataSource }) {
    const total = data?.summary?.display_value ?? data?.summary?.value ?? '0'

    return (
        <div className="card h-100">
            <div className="card-body text-center">
                <h6 className="text-muted mb-2">{title}</h6>
                <h3 className="mb-0" style={{ color: 'var(--primary)' }}>
                    {formatNumber(total)}
                </h3>
                <small className="text-muted">{dataSource}</small>
            </div>
        </div>
    )
}

function GaugeWidget({ title, widget }) {
    const value = widget.summary?.gauge_value ?? widget.summary?.display_value ?? '0'
    const dasharray = widget.summary?.gauge_dasharray || '0 157'
    return (
        <div className="card h-100">
            <div className="card-body text-center">
                <h6 className="text-muted mb-3">{title}</h6>
                <div style={{ position: 'relative', width: 120, height: 60, margin: '0 auto' }}>
                    <svg viewBox="0 0 120 60" width="120" height="60">
                        <path d="M10 55 A50 50 0 0 1 110 55" fill="none" stroke="#e9ecef" strokeWidth="8" />
                        <path
                            d="M10 55 A50 50 0 0 1 110 55"
                            fill="none"
                            stroke="#0088FE"
                            strokeWidth="8"
                            strokeDasharray={dasharray}
                        />
                    </svg>
                </div>
                <h4 className="mt-2">{formatNumber(value, 4)}</h4>
            </div>
        </div>
    )
}

function TableWidget({ title, data }) {
    const { t } = useTranslation()
    if (!Array.isArray(data) || data.length === 0) {
        return <div className="card h-100"><div className="card-body"><h6>{title}</h6><p className="text-muted">{t('common.no_data')}</p></div></div>
    }
    const keys = Object.keys(data[0]).filter(k => k !== 'party_id' && k !== 'product_id')
    return (
        <div className="card h-100">
            <div className="card-body">
                <h6 className="mb-3">{title}</h6>
                <div style={{ overflowX: 'auto', maxHeight: 300 }}>
                    <table className="table table-sm table-striped">
                        <thead>
                            <tr>{keys.map(k => <th key={k}>{k.replace(/_/g, ' ')}</th>)}</tr>
                        </thead>
                        <tbody>
                            {data.slice(0, 20).map((row, i) => (
                                <tr key={i}>
                                    {keys.map(k => (
                                        <td key={k}>{formatCellValue(row[k])}</td>
                                    ))}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    )
}

function ChartWidget({ widget }) {
    const { t } = useTranslation()
    const { widget_type, title, data } = widget
    if (!Array.isArray(data) || data.length === 0) {
        return <div className="card h-100"><div className="card-body"><h6>{title}</h6><p className="text-muted">{t('common.no_data')}</p></div></div>
    }

    const numericKeys = widget.value_keys || []
    const labelKey = widget.label_key || Object.keys(data[0] || {})[0]

    if (widget_type === 'bar_chart') {
        return (
            <div className="card h-100">
                <div className="card-body">
                    <h6 className="mb-3">{title}</h6>
                    <ResponsiveContainer width="100%" height={250}>
                        <BarChart data={data}>
                            <CartesianGrid strokeDasharray="3 3" />
                            <XAxis dataKey={labelKey} tick={{ fontSize: 11 }} />
                            <YAxis tick={{ fontSize: 11 }} />
                            <Tooltip />
                            {numericKeys.slice(0, 3).map((k, i) => (
                                <Bar key={k} dataKey={k} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                            ))}
                        </BarChart>
                    </ResponsiveContainer>
                </div>
            </div>
        )
    }

    if (widget_type === 'line_chart') {
        return (
            <div className="card h-100">
                <div className="card-body">
                    <h6 className="mb-3">{title}</h6>
                    <ResponsiveContainer width="100%" height={250}>
                        <LineChart data={data}>
                            <CartesianGrid strokeDasharray="3 3" />
                            <XAxis dataKey={labelKey} tick={{ fontSize: 11 }} />
                            <YAxis tick={{ fontSize: 11 }} />
                            <Tooltip />
                            {numericKeys.slice(0, 3).map((k, i) => (
                                <Line key={k} type="monotone" dataKey={k} stroke={CHART_COLORS[i % CHART_COLORS.length]} />
                            ))}
                        </LineChart>
                    </ResponsiveContainer>
                </div>
            </div>
        )
    }

    if (widget_type === 'pie_chart') {
        const pieData = widget.pie_data || []

        return (
            <div className="card h-100">
                <div className="card-body">
                    <h6 className="mb-3">{title}</h6>
                    <ResponsiveContainer width="100%" height={250}>
                        <PieChart>
                            <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} label>
                                {pieData.map((_, i) => (
                                    <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                                ))}
                            </Pie>
                            <Tooltip />
                        </PieChart>
                    </ResponsiveContainer>
                </div>
            </div>
        )
    }

    return null
}

function WidgetRenderer({ widget }) {
    const { widget_type } = widget
    if (widget_type === 'kpi_card') return <KPICard title={widget.title} data={widget} dataSource={widget.data_source} />
    if (widget_type === 'gauge') return <GaugeWidget title={widget.title} widget={widget} />
    if (widget_type === 'table') return <TableWidget title={widget.title} data={widget.data} />
    return <ChartWidget widget={widget} />
}


function DashboardView() {
    const { id } = useParams()
    const { t } = useTranslation()
    const [dashboard, setDashboard] = useState(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)
    const [dateFrom, setDateFrom] = useState('')
    const [dateTo, setDateTo] = useState('')
    const [branchFilter, setBranchFilter] = useState('')

    const fetchDashboard = useCallback(async () => {
        try {
            setLoading(true)
            const params = {}
            if (dateFrom) params.date_from = dateFrom
            if (dateTo) params.date_to = dateTo
            if (branchFilter) params.branch_id = branchFilter
            params.limit = 25
            const response = await dashboardAPI.getAnalyticsDashboard(id, { params })
            setDashboard(response.data)
        } catch (err) {
            setError(t('analytics.error_loading'))
            console.error(err)
        } finally {
            setLoading(false)
        }
    }, [id, t, dateFrom, dateTo, branchFilter])

    useEffect(() => {
        fetchDashboard()
    }, [fetchDashboard])

    const handleRefreshWidget = async (widgetId) => {
        try {
            const params = {}
            if (dateFrom) params.date_from = dateFrom
            if (dateTo) params.date_to = dateTo
            if (branchFilter) params.branch_id = branchFilter
            params.limit = 25
            const resp = await dashboardAPI.getWidgetData(widgetId, params)
            setDashboard(prev => {
                if (!prev) return prev
                return {
                    ...prev,
                    widgets: prev.widgets.map(w =>
                        w.id === widgetId ? { ...w, ...resp.data } : w
                    )
                }
            })
        } catch (err) {
            console.error('Widget refresh failed:', err)
        }
    }

    if (loading) return <div className="workspace fade-in">{t('common.loading')}</div>
    if (error) return <div className="workspace fade-in text-danger">{error}</div>
    if (!dashboard) return <div className="workspace fade-in">{t('analytics.not_found')}</div>

    return (
        <div className="workspace fade-in">
            <div className="d-flex justify-content-between align-items-center mb-4">
                <div>
                    <BackButton fallback="/analytics" />
                    <h2>{dashboard.name}</h2>
                    {dashboard.description && <p className="text-muted">{dashboard.description}</p>}
                </div>
                <div className="d-flex gap-2 align-items-center flex-wrap">
                    <DateInput
                        className="form-control form-control-sm"
                        value={dateFrom}
                        onChange={(e) => setDateFrom(e.target.value)}
                        placeholder={t('analytics.date_from')}
                        style={{ width: 150 }}
                    />
                    <DateInput
                        className="form-control form-control-sm"
                        value={dateTo}
                        onChange={(e) => setDateTo(e.target.value)}
                        placeholder={t('analytics.date_to')}
                        style={{ width: 150 }}
                    />
                    <input
                        type="text"
                        className="form-control form-control-sm"
                        value={branchFilter}
                        onChange={(e) => setBranchFilter(e.target.value)}
                        placeholder={t('analytics.branch_filter')}
                        style={{ width: 140 }}
                    />
                    <button className="btn btn-sm btn-outline-primary" onClick={fetchDashboard}>
                        {t('analytics.refresh_all')}
                    </button>
                </div>
            </div>

            <div className="row g-3">
                {dashboard.widgets?.map((widget) => {
                    const pos = widget.position || {}
                    const colClass = `col-md-${Math.min((pos.width || 3) , 12)} col-12`
                    return (
                        <div key={widget.id} className={colClass}>
                            <div className="position-relative">
                                <WidgetRenderer widget={widget} />
                                <button
                                    className="btn btn-sm btn-link position-absolute"
                                    style={{ top: 4, right: 4, opacity: 0.6 }}
                                    onClick={() => handleRefreshWidget(widget.id)}
                                    title={t('analytics.refresh_widget')}
                                >
                                    🔄
                                </button>
                            </div>
                        </div>
                    )
                })}
            </div>

            <div className="mt-3 text-muted small">
                {t('analytics.auto_refresh', { interval: dashboard.refresh_interval_minutes || 15 })}
            </div>
        </div>
    )
}

export default DashboardView
