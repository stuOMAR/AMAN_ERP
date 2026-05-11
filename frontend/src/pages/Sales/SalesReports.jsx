import { useState, useEffect } from 'react';
import { reportsAPI } from '../../utils/api';
import { getCurrency } from '../../utils/auth';
import ReactECharts from 'echarts-for-react';
import { useTranslation } from 'react-i18next';
import { useBranch } from '../../context/BranchContext';
import { formatNumber } from '../../utils/format';
import BackButton from '../../components/common/BackButton';
import CustomDatePicker from '../../components/common/CustomDatePicker';
import { useToast } from '../../context/ToastContext';
import { ModuleKPISection } from '../../components/kpi';
import { PageLoading } from '../../components/common/LoadingStates'

const SalesReports = () => {
    const { t } = useTranslation();
    const { showToast } = useToast();
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [summary, setSummary] = useState(null);
    const [trend, setTrend] = useState([]);
    const [topCustomers, setTopCustomers] = useState([]);
    const [topProducts, setTopProducts] = useState([]);
    const currency = getCurrency();
    const { currentBranch } = useBranch();
    const [dates, setDates] = useState({
        start: new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().split('T')[0],
        end: new Date().toISOString().split('T')[0]
    });

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchReports();
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch, dates]);

    const fetchReports = async () => {
        try {
            setLoading(true);
            const branchId = currentBranch ? currentBranch.id : null;
            const daysDiff = Math.ceil((new Date(dates.end) - new Date(dates.start)) / (1000 * 60 * 60 * 24)) || 30;
            const [sumRes, trendRes, custRes, prodRes] = await Promise.all([
                reportsAPI.getSalesSummary(dates.start, dates.end, branchId),
                reportsAPI.getSalesTrend(daysDiff, branchId),
                reportsAPI.getSalesByCustomer(5, branchId),
                reportsAPI.getSalesByProduct(5, branchId)
            ]);

            setSummary(sumRes.data.stats);
            setTrend(trendRes.data);
            setTopCustomers(custRes.data);
            setTopProducts(prodRes.data);
        } catch (error) {
            showToast(t('common.error'), 'error');
        } finally {
            setLoading(false);
            setInitialLoad(false);
        }
    };

    if (initialLoad) return <PageLoading />;

    // ECharts Options
    const trendChartOption = {
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'cross' },
            formatter: (params) => {
                const data = params[0];
                return `${data.axisValue}<br/>${t('sales.reports.analytics.sale_legend')}: <b>${formatNumber(data.value)} ${currency}</b>`;
            }
        },
        legend: { data: [t('sales.reports.analytics.sale_legend')], bottom: 0 },
        grid: { left: '3%', right: '4%', bottom: '15%', top: '10%', containLabel: true },
        xAxis: {
            type: 'category',
            data: trend.map(d => d.date),
            axisLabel: { rotate: 45, fontSize: 10 }
        },
        yAxis: {
            type: 'value',
            axisLabel: { formatter: (val) => val >= 1000 ? `${val / 1000}K` : val }
        },
        series: [{
            name: t('sales.reports.analytics.sale_legend'),
            type: 'line',
            smooth: true,
            data: trend.map(d => d.total),
            areaStyle: {
                color: {
                    type: 'linear',
                    x: 0, y: 0, x2: 0, y2: 1,
                    colorStops: [
                        { offset: 0, color: 'rgba(16, 185, 129, 0.4)' },
                        { offset: 1, color: 'rgba(16, 185, 129, 0.05)' }
                    ]
                }
            },
            lineStyle: { color: '#10B981', width: 3 },
            itemStyle: { color: '#10B981' },
            symbol: 'circle',
            symbolSize: 8
        }],
        toolbox: {
            show: true,
            feature: {
                saveAsImage: { title: t('common.save') || 'Save' },
                dataZoom: { title: { zoom: t('common.zoom') || 'Zoom', back: t('common.back') || 'Back' } }
            }
        }
    };

    const productsChartOption = {
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'shadow' },
            formatter: (params) => `${params[0].name}: <b>${formatNumber(params[0].value)} ${currency}</b>`
        },
        grid: { left: '3%', right: '4%', bottom: '3%', top: '10%', containLabel: true },
        xAxis: { type: 'value' },
        yAxis: {
            type: 'category',
            data: topProducts.map(p => p.name),
            axisLabel: { fontSize: 11 }
        },
        series: [{
            type: 'bar',
            data: topProducts.map(p => p.value),
            itemStyle: {
                color: {
                    type: 'linear',
                    x: 0, y: 0, x2: 1, y2: 0,
                    colorStops: [
                        { offset: 0, color: '#10B981' },
                        { offset: 1, color: '#34D399' }
                    ]
                },
                borderRadius: [0, 4, 4, 0]
            },
            label: {
                show: true,
                position: 'right',
                formatter: (params) => formatNumber(params.value)
            }
        }],
        toolbox: {
            show: true,
            feature: { saveAsImage: { title: t('common.save') || 'Save' } }
        }
    };

    const customersChartOption = {
        tooltip: {
            trigger: 'item',
            formatter: (params) => `${params.name}: <b>${formatNumber(params.value)} ${currency}</b> (${params.percent}%)`
        },
        legend: {
            orient: 'vertical',
            left: 'left',
            top: 'middle'
        },
        series: [{
            type: 'pie',
            radius: ['40%', '70%'],
            center: ['60%', '50%'],
            avoidLabelOverlap: true,
            itemStyle: {
                borderRadius: 6,
                borderColor: '#fff',
                borderWidth: 2
            },
            label: {
                show: false,
                position: 'center'
            },
            emphasis: {
                label: {
                    show: true,
                    fontSize: 16,
                    fontWeight: 'bold'
                }
            },
            labelLine: { show: false },
            data: topCustomers.map((c, i) => ({
                name: c.name,
                value: c.value,
                itemStyle: {
                    color: ['#10B981', '#34D399', '#6EE7B7', '#A7F3D0', '#D1FAE5'][i % 5]
                }
            }))
        }],
        toolbox: {
            show: true,
            feature: { saveAsImage: { title: t('common.save') || 'Save' } }
        }
    };

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">📊 {t('sales.reports.analytics.title')}</h1>
                    <p className="workspace-subtitle">{t('sales.reports.analytics.subtitle')}</p>
                </div>
                <div className="header-actions">
                    <CustomDatePicker
                        label={t('common.start_date')}
                        selected={dates.start}
                        onChange={(d) => setDates(prev => ({ ...prev, start: d }))}
                    />
                    <CustomDatePicker
                        label={t('common.end_date')}
                        selected={dates.end}
                        onChange={(d) => setDates(prev => ({ ...prev, end: d }))}
                    />
                    <button onClick={fetchReports} className="btn btn-secondary">🔄 {t('sales.reports.analytics.update')}</button>
                </div>
            </div>

            {/* KPI Performance Indicators */}
            <ModuleKPISection roleKey="sales" color="#059669" defaultOpen={false} />

            {/* Summary KPI Cards */}
            <div className="metrics-grid mb-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
                <div className="metric-card">
                    <div className="metric-label">{t('sales.reports.analytics.kpi.total_sales')}</div>
                    <div className="metric-value text-primary">
                        {formatNumber(summary?.total_sales)} <small>{currency}</small>
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('sales.reports.analytics.kpi.total_tax')}</div>
                    <div className="metric-value text-warning">
                        {formatNumber(summary?.total_tax)} <small>{currency}</small>
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('sales.reports.analytics.kpi.net_revenue')}</div>
                    <div className="metric-value text-info" style={{ color: 'var(--primary-color)' }}>
                        {formatNumber(summary?.net_revenue)} <small>{currency}</small>
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('sales.reports.analytics.kpi.total_cogs')}</div>
                    <div className="metric-value text-danger" style={{ color: '#ef4444' }}>
                        {formatNumber(summary?.total_cogs)} <small>{currency}</small>
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('sales.reports.analytics.kpi.gross_profit')}</div>
                    <div className="metric-value text-success">
                        {formatNumber(summary?.gross_profit)} <small>{currency}</small>
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('sales.reports.analytics.kpi.net_profit')}</div>
                    <div className="metric-value" style={{ color: (summary?.net_profit || 0) >= 0 ? 'var(--success)' : 'var(--danger)' }}>
                        {formatNumber(summary?.net_profit)} <small>{currency}</small>
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('sales.reports.analytics.kpi.collected')}</div>
                    <div className="metric-value text-success">
                        {formatNumber(summary?.total_paid)} <small>{currency}</small>
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('sales.reports.analytics.kpi.total_due')}</div>
                    <div className="metric-value text-danger">
                        {formatNumber(summary?.total_due)} <small>{currency}</small>
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('sales.reports.analytics.kpi.invoice_count')}</div>
                    <div className="metric-value text-secondary">
                        {summary?.invoice_count}
                    </div>
                </div>
            </div>

            {/* Charts Row 1 */}
            <div className="modules-grid" style={{ marginBottom: '24px' }}>
                {/* Sales Trend */}
                <div className="section-card">
                    <h3 className="section-title">📈 {t('sales.reports.analytics.charts.trend_daily')}</h3>
                    <ReactECharts
                        option={trendChartOption}
                        style={{ height: '350px', width: '100%' }}
                        opts={{ renderer: 'canvas' }}
                        notMerge={true}
                        lazyUpdate={true}
                    />
                </div>

                {/* Top Products */}
                <div className="section-card">
                    <h3 className="section-title">🏆 {t('sales.reports.analytics.charts.top_products')}</h3>
                    <ReactECharts
                        option={productsChartOption}
                        style={{ height: '350px', width: '100%' }}
                        opts={{ renderer: 'canvas' }}
                        notMerge={true}
                        lazyUpdate={true}
                    />
                </div>
            </div>

            {/* Row 2: Customers & Table */}
            <div className="modules-grid">
                {/* Top Customers (Pie) */}
                <div className="section-card">
                    <h3 className="section-title">👥 {t('sales.reports.analytics.charts.top_customers')}</h3>
                    <ReactECharts
                        option={customersChartOption}
                        style={{ height: '320px', width: '100%' }}
                        opts={{ renderer: 'canvas' }}
                        notMerge={true}
                        lazyUpdate={true}
                    />
                </div>

                {/* Detailed Table */}
                <div className="section-card" style={{ gridColumn: 'span 2' }}>
                    <h3 className="section-title">📋 {t('sales.reports.analytics.charts.daily_details')}</h3>
                    <div className="data-table-container" style={{ maxHeight: '320px', overflow: 'auto' }}>
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th>{t('sales.reports.analytics.table.date')}</th>
                                    <th>{t('sales.reports.analytics.table.count')}</th>
                                    <th>{t('sales.reports.analytics.table.total')}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {trend.slice().reverse().map((day, idx) => (
                                    <tr key={idx}>
                                        <td className="font-medium">{day.date}</td>
                                        <td className="text-muted">{day.count}</td>
                                        <td className="text-primary font-medium">{formatNumber(day.total)} {currency}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default SalesReports;
