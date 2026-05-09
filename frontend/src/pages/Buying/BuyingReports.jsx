import { useState, useEffect } from 'react';
import { reportsAPI } from '../../utils/api';
import { getCurrency } from '../../utils/auth';
import ReactECharts from 'echarts-for-react';
import { useTranslation } from 'react-i18next';
import { useBranch } from '../../context/BranchContext';
import { useToast } from '../../context/ToastContext';
import { formatNumber } from '../../utils/format';
import BackButton from '../../components/common/BackButton';
import CustomDatePicker from '../../components/common/CustomDatePicker';
import { ModuleKPISection } from '../../components/kpi';
import { PageLoading } from '../../components/common/LoadingStates'

const BuyingReports = () => {
    const { t } = useTranslation();
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [summary, setSummary] = useState(null);
    const [trend, setTrend] = useState([]);
    const [topSuppliers, setTopSuppliers] = useState([]);
    const currency = getCurrency();
    const { currentBranch } = useBranch();
    const { showToast } = useToast();
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
            const [sumRes, trendRes, suppRes] = await Promise.all([
                reportsAPI.getPurchasesSummary({ branch_id: branchId, start_date: dates.start, end_date: dates.end }),
                reportsAPI.getPurchasesTrend(daysDiff, branchId),
                reportsAPI.getPurchasesBySupplier(5, branchId)
            ]);

            setSummary(sumRes.data.stats);
            setTrend(trendRes.data);
            setTopSuppliers(suppRes.data);
        } catch (error) {
            showToast(t('common.error'), 'error');
        } finally {
            setLoading(false);
            setInitialLoad(false);
        }
    };

    if (initialLoad && !summary) return <PageLoading />;

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">📉 {t('buying.reports.analytics.title')}</h1>
                    <p className="workspace-subtitle">{t('buying.reports.analytics.subtitle')}</p>
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
                    <button onClick={fetchReports} className="btn btn-secondary">🔄 {t('buying.reports.analytics.update')}</button>
                </div>
            </div>

            {/* KPI Performance Indicators */}
            <ModuleKPISection roleKey="procurement" color="#d97706" defaultOpen={false} />

            {/* Summary Cards */}
            <div className="metrics-grid">
                <div className="metric-card">
                    <div className="metric-label">{t('buying.reports.analytics.metrics.total_purchases')}</div>
                    <div className="metric-value text-primary">
                        {formatNumber(summary?.total_purchases)} <small>{currency}</small>
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('buying.reports.analytics.metrics.invoice_count')}</div>
                    <div className="metric-value text-secondary">
                        {summary?.invoice_count}
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('buying.reports.analytics.metrics.total_paid')}</div>
                    <div className="metric-value text-success">
                        {formatNumber(summary?.total_paid)} <small>{currency}</small>
                    </div>
                </div>
            </div>

            {/* Charts */}
            <div className="modules-grid">
                {/* Purchase Trend */}
                <div className="section-card">
                    <h3 className="section-title">📉 {t('buying.reports.analytics.charts.trend')}</h3>
                    <ReactECharts
                        option={trendChartOption}
                        style={{ height: '350px', width: '100%' }}
                        opts={{ renderer: 'canvas' }}
                        notMerge={true}
                        lazyUpdate={true}
                    />
                </div>

                {/* Top Suppliers */}
                <div className="section-card">
                    <h3 className="section-title">🏭 {t('buying.reports.analytics.charts.top_suppliers')}</h3>
                    <ReactECharts
                        option={suppliersChartOption}
                        style={{ height: '350px', width: '100%' }}
                        opts={{ renderer: 'canvas' }}
                        notMerge={true}
                        lazyUpdate={true}
                    />
                </div>
            </div>
        </div>
    );
};

export default BuyingReports;
