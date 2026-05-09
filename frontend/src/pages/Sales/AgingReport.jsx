import { useState, useEffect } from 'react';
import { reportsAPI } from '../../utils/api';
import { getCurrency, hasPermission } from '../../utils/auth';
import ReactECharts from 'echarts-for-react';
import { useTranslation } from 'react-i18next';
import { useBranch } from '../../context/BranchContext';
import { formatNumber } from '../../utils/format';
import BackButton from '../../components/common/BackButton';
import { useToast } from '../../context/ToastContext';
import { PageLoading } from '../../components/common/LoadingStates'

const AgingReport = () => {
    const { t } = useTranslation();
    const { showToast } = useToast();
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [buckets, setBuckets] = useState([]);
    const currency = getCurrency();
    const { currentBranch } = useBranch();

    useEffect(() => {
        const timer = setTimeout(() => {
            const loadData = async () => {
                if (!hasPermission('reports.view') && !hasPermission('sales.reports')) {
                    setLoading(false);
                    setInitialLoad(false);
                    return;
                }
                try {
                    const branchId = currentBranch ? currentBranch.id : null;
                    const res = await reportsAPI.getAgingReport(branchId);
                    const rawData = res.data;
                    setData(rawData);

                    // Aggregate buckets
                    const agg = { "0-30": 0, "31-60": 0, "61-90": 0, "90+": 0 };
                    rawData.forEach(item => {
                        if (agg[item.bucket] !== undefined) {
                            agg[item.bucket] += item.amount;
                        }
                    });

                    setBuckets(Object.keys(agg).map(key => ({
                        name: key,
                        amount: agg[key]
                    })));
                } catch (err) {
                    showToast(t('common.error'), 'error');
                } finally {
                    setLoading(false);
                    setInitialLoad(false);
                }
            };
            loadData();
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch]);

    if (initialLoad) return <PageLoading />;

    const totalDue = buckets.reduce((a, b) => a + b.amount, 0);

    const agingChartOption = {
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'shadow' },
            formatter: (params) => `${t('sales.reports.aging.buckets.days')} ${params[0].name}<br/>${t('sales.reports.aging.table.amount')}: <b>${formatNumber(params[0].value)} ${currency}</b>`
        },
        grid: { left: '3%', right: '4%', bottom: '10%', top: '15%', containLabel: true },
        xAxis: {
            type: 'category',
            data: buckets.map(b => b.name + ' ' + t('sales.reports.aging.buckets.days')),
            axisLabel: { fontSize: 12 }
        },
        yAxis: {
            type: 'value',
            axisLabel: { formatter: (val) => val >= 1000 ? `${val / 1000}K` : val }
        },
        series: [{
            type: 'bar',
            data: buckets.map((b, i) => ({
                value: b.amount,
                itemStyle: {
                    color: ['#10B981', '#FBBF24', '#F97316', '#EF4444'][i],
                    borderRadius: [6, 6, 0, 0]
                }
            })),
            barWidth: '50%',
            label: {
                show: true,
                position: 'top',
                formatter: (params) => formatNumber(params.value),
                fontWeight: 'bold'
            }
        }],
        toolbox: {
            show: true,
            feature: {
                saveAsImage: { title: t('common.save') || 'Save' }
            }
        }
    };

    const pieChartOption = {
        tooltip: {
            trigger: 'item',
            formatter: (params) => `${params.name}<br/>${t('sales.reports.aging.table.amount')}: <b>${formatNumber(params.value)} ${currency}</b> (${params.percent}%)`
        },
        legend: {
            orient: 'horizontal',
            bottom: 0
        },
        series: [{
            type: 'pie',
            radius: ['35%', '65%'],
            center: ['50%', '45%'],
            avoidLabelOverlap: true,
            itemStyle: {
                borderRadius: 8,
                borderColor: '#fff',
                borderWidth: 3
            },
            label: {
                show: true,
                formatter: '{b}\n{d}%'
            },
            data: buckets.map((b, i) => ({
                name: b.name + ' ' + t('sales.reports.aging.buckets.days'),
                value: b.amount,
                itemStyle: {
                    color: ['#10B981', '#FBBF24', '#F97316', '#EF4444'][i]
                }
            }))
        }]
    };

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">⏳ {t('sales.reports.aging.title')}</h1>
                    <p className="workspace-subtitle">{t('sales.reports.aging.subtitle')}</p>
                </div>
            </div>

            {/* Top Analysis Section */}
            <div className="modules-grid" style={{ marginBottom: '24px' }}>
                {/* Bar Chart */}
                <div className="section-card" style={{ gridColumn: 'span 2' }}>
                    <h3 className="section-title">📊 {t('sales.reports.aging.chart_title_distribution')} ({currency})</h3>
                    <ReactECharts
                        option={agingChartOption}
                        style={{ height: '300px', width: '100%' }}
                        opts={{ renderer: 'canvas' }}
                        notMerge={true}
                        lazyUpdate={true}
                    />
                </div>

                {/* Pie Chart */}
                <div className="section-card">
                    <h3 className="section-title">🥧 {t('sales.reports.aging.chart_title_ratio')}</h3>
                    <ReactECharts
                        option={pieChartOption}
                        style={{ height: '300px', width: '100%' }}
                        opts={{ renderer: 'canvas' }}
                        notMerge={true}
                        lazyUpdate={true}
                    />
                </div>
            </div>

            {/* Summary Cards */}
            <div className="metrics-grid" style={{ marginBottom: '24px' }}>
                {buckets.map((b, i) => (
                    <div key={b.name} className="metric-card" style={{ borderRight: `4px solid ${['#10B981', '#FBBF24', '#F97316', '#EF4444'][i]}` }}>
                        <div className="metric-label">{b.name} {t('sales.reports.aging.buckets.days')}</div>
                        <div className="metric-value" style={{ color: ['#10B981', '#FBBF24', '#F97316', '#EF4444'][i] }}>
                            {hasPermission('reports.view') ? formatNumber(b.amount) : '***'} {hasPermission('reports.view') && <small>{currency}</small>}
                        </div>
                    </div>
                ))}
                <div className="metric-card" style={{ background: 'var(--bg-secondary)', borderRight: '4px solid var(--error)' }}>
                    <div className="metric-label">{t('sales.reports.aging.total')}</div>
                    <div className="metric-value" style={{ color: 'var(--error)' }}>
                        {hasPermission('reports.view') ? formatNumber(totalDue) : '***'} {hasPermission('reports.view') && <small>{currency}</small>}
                    </div>
                </div>
            </div>

            {/* Detailed Table */}
            <div className="card">
                <div style={{ padding: '16px', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <h3 style={{ fontWeight: '600', margin: 0 }}>{t('sales.reports.aging.details_title')}</h3>
                    <span className="badge" style={{ background: 'var(--bg-secondary)', color: 'var(--text-primary)' }}>
                        {data.length} {t('sales.reports.aging.invoice_count')}
                    </span>
                </div>
                <div className="data-table-container">
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>{t('sales.reports.aging.table.customer')}</th>
                                <th>{t('sales.reports.aging.table.invoice')}</th>
                                <th>{t('sales.reports.aging.table.date')}</th>
                                <th>{t('sales.reports.aging.table.amount')}</th>
                                <th>{t('sales.reports.aging.table.days')}</th>
                                <th>{t('sales.reports.aging.table.bucket')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {data.map((row, idx) => (
                                <tr key={idx}>
                                    <td className="font-medium">{row.customer}</td>
                                    <td className="text-muted">{row.invoice}</td>
                                    <td>{row.date}</td>
                                    <td className="font-medium" style={{ color: 'var(--error)' }}>
                                        {hasPermission('reports.view') ? formatNumber(row.amount) : '***'}
                                    </td>
                                    <td>{hasPermission('reports.view') ? row.days : '***'}</td>
                                    <td>
                                        <span className={`badge ${row.days > 90 ? 'badge-danger' :
                                            row.days > 60 ? 'badge-warning' :
                                                'badge-success'
                                            }`}>
                                            {hasPermission('reports.view') ? row.bucket : '***'}
                                        </span>
                                    </td>
                                </tr>
                            ))}
                            {data.length === 0 && (
                                <tr>
                                    <td colSpan="6" className="text-center py-5 text-muted">
                                        🎉 {t('sales.reports.aging.empty')}
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
};

export default AgingReport;
