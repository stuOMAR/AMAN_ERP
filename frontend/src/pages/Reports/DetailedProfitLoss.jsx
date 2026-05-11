import React, { useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { detailedReportsAPI } from '../../services/reports';
import { api } from '../../utils/api';
import { useBranch } from '../../context/BranchContext';
import { useToast } from '../../context/ToastContext';
import {
    BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer
} from 'recharts';
import BackButton from '../../components/common/BackButton';
import DateInput from '../../components/common/DateInput';



const DetailedProfitLoss = () => {
    const { t, i18n } = useTranslation();
    const { currentBranch } = useBranch();
    const { showToast } = useToast();
    const isRTL = i18n.language === 'ar';

    const today = new Date();
    const firstOfMonth = new Date(today.getFullYear(), today.getMonth(), 1)
        .toISOString().slice(0, 10);
    const todayStr = today.toISOString().slice(0, 10);

    const [startDate, setStartDate] = useState(firstOfMonth);
    const [endDate, setEndDate] = useState(todayStr);
    const [groupBy, setGroupBy] = useState('customer');
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(false);
    const [initialLoad, setInitialLoad] = useState(true);

    const fetchData = useCallback(async () => {
        try {
            setLoading(true);
            const params = {
                start_date: startDate,
                end_date: endDate,
                group_by: groupBy,
                branch_id: currentBranch?.id || undefined,
            };
            const res = await detailedReportsAPI.getDetailedPL(params);
            setData(res.data?.data || res.data || []);
        } catch (err) {
            console.error(err);
            showToast(t('common.error_loading'), 'error');
        } finally {
            setLoading(false);
            setInitialLoad(false);
        }
    }, [startDate, endDate, groupBy, currentBranch?.id]);

    const totals = data.reduce(
        (acc, row) => ({
            revenue: acc.revenue + (row.revenue || 0),
            cogs: acc.cogs + (row.cogs || 0),
            gross_profit: acc.gross_profit + (row.gross_profit || 0),
        }),
        { revenue: 0, cogs: 0, gross_profit: 0 }
    );
    const overallMargin = totals.revenue ? ((totals.gross_profit / totals.revenue) * 100).toFixed(1) : '0.0';

    const chartData = data.slice(0, 10).map(row => ({
        name: row.name || row.customer || row.product || row.category || '-',
        [t('reports.detailed_pl.revenue')]: row.revenue || 0,
        [t('reports.detailed_pl.cogs')]: row.cogs || 0,
        [t('reports.detailed_pl.gross_profit')]: row.gross_profit || 0,
    }));

    const handleExport = async (format) => {
        try {
            const params = new URLSearchParams({
                start_date: startDate,
                end_date: endDate,
                group_by: groupBy,
                format,
                ...(currentBranch?.id ? { branch_id: currentBranch.id } : {}),
            });
            const res = await api.get(`/reports/accounting/profit-loss/detailed?${params}`, { responseType: 'blob' });
            const url = URL.createObjectURL(res.data);
            if (format === 'pdf') {
                window.open(url, '_blank');
            } else {
                const a = document.createElement('a'); a.href = url; a.download = `profit-loss.${format === 'excel' ? 'xlsx' : format}`; a.click();
            }
            setTimeout(() => URL.revokeObjectURL(url), 60000);
        } catch (error) {
            console.error('Export failed:', error);
            showToast(t('common.exportError'), 'error');
        }
    };

    const fmt = (n) => Number(n || 0).toLocaleString(isRTL ? 'ar-SA' : 'en-US', {
        minimumFractionDigits: 2, maximumFractionDigits: 2,
    });

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            {/* Header */}
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">📊 {t('reports.detailed_pl.title')}</h1>
                    <p className="workspace-subtitle">
                        {t('reports.detailed_pl.subtitle', 'Detailed profit & loss breakdown by customer, product, or category')}
                    </p>
                </div>
                <div className="header-actions">
                    <button className="btn btn-secondary" onClick={() => handleExport('excel')} disabled={!data.length}>
                        📥 Excel
                    </button>
                    <button className="btn btn-secondary" onClick={() => handleExport('pdf')} disabled={!data.length}>
                        📄 PDF
                    </button>
                </div>
            </div>

            {/* Filters */}
            <div className="section-card" style={{ marginBottom: 16 }}>
                <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'flex-end' }}>
                    <div className="form-group" style={{ margin: 0 }}>
                        <label>{t('common.start_date')}</label>
                        <DateInput className="form-input" value={startDate}
                            onChange={e => setStartDate(e.target.value)} />
                    </div>
                    <div className="form-group" style={{ margin: 0 }}>
                        <label>{t('common.end_date')}</label>
                        <DateInput className="form-input" value={endDate}
                            onChange={e => setEndDate(e.target.value)} />
                    </div>
                    <div className="form-group" style={{ margin: 0 }}>
                        <label>{t('reports.detailed_pl.group_by')}</label>
                        <select className="form-input" value={groupBy} onChange={e => setGroupBy(e.target.value)}>
                            <option value="customer">{t('reports.detailed_pl.by_customer')}</option>
                            <option value="product">{t('reports.detailed_pl.by_product')}</option>
                            <option value="category">{t('reports.detailed_pl.by_category')}</option>
                        </select>
                    </div>
                    <button className="btn btn-primary" onClick={fetchData} disabled={loading}>
                        {loading ? t('common.loading') : t('common.search', 'Search')}
                    </button>
                </div>
            </div>

            {/* Summary Cards */}
            {data.length > 0 && (
                <div className="metrics-grid" style={{ marginBottom: 24 }}>
                    <div className="metric-card">
                        <div className="metric-label">{t('reports.detailed_pl.revenue')}</div>
                        <div className="metric-value text-success">{fmt(totals.revenue)}</div>
                    </div>
                    <div className="metric-card">
                        <div className="metric-label">{t('reports.detailed_pl.cogs')}</div>
                        <div className="metric-value text-danger">{fmt(totals.cogs)}</div>
                    </div>
                    <div className="metric-card">
                        <div className="metric-label">{t('reports.detailed_pl.gross_profit')}</div>
                        <div className="metric-value text-primary">{fmt(totals.gross_profit)}</div>
                    </div>
                    <div className="metric-card">
                        <div className="metric-label">{t('reports.detailed_pl.gross_margin')}</div>
                        <div className="metric-value text-secondary">{overallMargin}%</div>
                    </div>
                </div>
            )}

            {/* Chart */}
            {chartData.length > 0 && (
                <div className="section-card" style={{ marginBottom: 24 }}>
                    <h3 className="section-title" style={{ borderBottom: 'none', paddingBottom: 8 }}>
                        {t('reports.detailed_pl.chart_title', 'Top 10 — Revenue vs Cost vs Profit')}
                    </h3>
                    <ResponsiveContainer width="100%" height={320}>
                        <BarChart data={chartData} margin={{ top: 10, right: 30, left: 20, bottom: 5 }}>
                            <CartesianGrid strokeDasharray="3 3" />
                            <XAxis dataKey="name" tick={{ fontSize: 11 }} interval={0} angle={-20} textAnchor="end" height={60} />
                            <YAxis />
                            <Tooltip />
                            <Bar dataKey={t('reports.detailed_pl.revenue')} fill="#10B981" />
                            <Bar dataKey={t('reports.detailed_pl.cogs')} fill="#EF4444" />
                            <Bar dataKey={t('reports.detailed_pl.gross_profit')} fill="#3B82F6" />
                        </BarChart>
                    </ResponsiveContainer>
                </div>
            )}

            {/* Data Table */}
            <div className="table-container">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>
                                {groupBy === 'customer' ? t('reports.detailed_pl.by_customer') :
                                 groupBy === 'product' ? t('reports.detailed_pl.by_product') :
                                 t('reports.detailed_pl.by_category')}
                            </th>
                            <th>{t('reports.detailed_pl.revenue')}</th>
                            <th>{t('reports.detailed_pl.cogs')}</th>
                            <th>{t('reports.detailed_pl.gross_profit')}</th>
                            <th>{t('reports.detailed_pl.gross_margin')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading ? (
                            <tr><td colSpan="6" className="text-center">{t('common.loading')}</td></tr>
                        ) : data.length === 0 ? (
                            <tr><td colSpan="6" className="text-center">{t('common.no_data')}</td></tr>
                        ) : (
                            data.map((row, idx) => {
                                const margin = row.revenue ? ((row.gross_profit / row.revenue) * 100).toFixed(1) : '0.0';
                                return (
                                    <tr key={idx}>
                                        <td>{idx + 1}</td>
                                        <td style={{ fontWeight: 600 }}>
                                            {row.name || row.customer || row.product || row.category || '-'}
                                        </td>
                                        <td className="text-success">{fmt(row.revenue)}</td>
                                        <td className="text-danger">{fmt(row.cogs)}</td>
                                        <td className="text-primary" style={{ fontWeight: 600 }}>{fmt(row.gross_profit)}</td>
                                        <td>
                                            <span className={`badge ${Number(margin) >= 0 ? 'badge-success' : 'badge-danger'}`}>
                                                {margin}%
                                            </span>
                                        </td>
                                    </tr>
                                );
                            })
                        )}
                        {data.length > 0 && (
                            <tr style={{ fontWeight: 700, borderTop: '2px solid var(--border-color)' }}>
                                <td></td>
                                <td>{t('common.total', 'Total')}</td>
                                <td className="text-success">{fmt(totals.revenue)}</td>
                                <td className="text-danger">{fmt(totals.cogs)}</td>
                                <td className="text-primary">{fmt(totals.gross_profit)}</td>
                                <td><span className="badge badge-primary">{overallMargin}%</span></td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

export default DetailedProfitLoss;
