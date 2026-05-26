import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { manufacturingAPI } from '../../utils/api';
import { toastEmitter } from '../../utils/toastEmitter';
import { formatNumber } from '../../utils/format';
import '../../components/ModuleStyles.css';
import BackButton from '../../components/common/BackButton';
import DateInput from '../../components/common/DateInput';
import { PageLoading } from '../../components/common/LoadingStates'

const WorkOrderStatusReport = () => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const [loading, setLoading] = useState(false);
    const [orders, setOrders] = useState([]);
    const [summary, setSummary] = useState(null);
    const [filters, setFilters] = useState({
        start_date: new Date(new Date().getFullYear(), 0, 1).toISOString().split('T')[0],
        end_date: new Date().toISOString().split('T')[0],
        status: '',
    });

    const fetchData = async (activeFilters = filters) => {
        setLoading(true);
        try {
            const params = { start_date: activeFilters.start_date, end_date: activeFilters.end_date };
            const [sumRes, ordersRes] = await Promise.allSettled([
                manufacturingAPI.getProductionSummary(params),
                manufacturingAPI.listOrders({ ...params, status: activeFilters.status || undefined, limit: 100 }),
            ]);
            if (sumRes.status === 'fulfilled') setSummary(sumRes.value.data);
            if (ordersRes.status === 'fulfilled') {
                const data = ordersRes.value.data;
                setOrders(data?.orders || data?.items || data || []);
            }
        } catch (e) {
            toastEmitter.emit(t('common.error'), 'error');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchData(); }, []);

    const statusConfig = {
        draft:       { label: t('draft', 'مسودة'),          color: '#94a3b8', bg: '#f1f5f9' },
        confirmed:   { label: t('confirmed', 'مؤكد'),       color: '#3b82f6', bg: '#eff6ff' },
        planned:     { label: t('planned', 'مخطط'),         color: '#8b5cf6', bg: '#f5f3ff' },
        in_progress: { label: t('in_progress', 'قيد التنفيذ'), color: '#f59e0b', bg: '#fffbeb' },
        completed:   { label: t('completed', 'مكتمل'),      color: '#22c55e', bg: '#f0fdf4' },
        cancelled:   { label: t('cancelled', 'ملغي'),       color: '#ef4444', bg: '#fef2f2' },
    };

    const byStatus = summary?.orders_by_status || {};
    const totalOrders = summary?.total_orders || 0;

    const formatDate = (d) => {
        if (!d) return '-';
        try { return new Date(d).toLocaleDateString('ar-EG') } catch { return d }
    };

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">📋 {t('manufacturing.work_orders_report.title', 'حالة أوامر العمل')}</h1>
                    <p className="workspace-subtitle">{t('manufacturing.work_orders_report.subtitle', 'تتبع حالة وتقدم أوامر العمل والإنتاج')}</p>
                </div>
            </div>

            {/* Filters */}
            <div className="card" style={{ marginBottom: 16 }}>
                <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
                    <div className="form-group" style={{ flex: 1, minWidth: 150 }}>
                        <label className="form-label">{t('common.from_date', 'من تاريخ')}</label>
                        <DateInput className="form-input" value={filters.start_date}
                            onChange={e => setFilters(p => ({ ...p, start_date: e.target.value }))} />
                    </div>
                    <div className="form-group" style={{ flex: 1, minWidth: 150 }}>
                        <label className="form-label">{t('common.to_date', 'إلى تاريخ')}</label>
                        <DateInput className="form-input" value={filters.end_date}
                            onChange={e => setFilters(p => ({ ...p, end_date: e.target.value }))} />
                    </div>
                    <div className="form-group" style={{ flex: 1, minWidth: 150 }}>
                        <label className="form-label">{t('common.status_title', 'الحالة')}</label>
                        <select className="form-input" value={filters.status}
                            onChange={e => setFilters(p => ({ ...p, status: e.target.value }))}>
                            <option value="">{t('common.all', 'الكل')}</option>
                            {Object.entries(statusConfig).map(([k, v]) => (
                                <option key={k} value={k}>{v.label}</option>
                            ))}
                        </select>
                    </div>
                    <button className="btn btn-primary" onClick={() => fetchData()} disabled={loading}>
                        {loading ? '...' : t('common.search', 'بحث')}
                    </button>
                </div>
            </div>

            {loading ? (
                <PageLoading />
            ) : (
                <>
                    {/* Status Summary Cards */}
                    <div className="metrics-grid" style={{ marginBottom: 16 }}>
                            {Object.entries(statusConfig).map(([status, cfg]) => {
                                const count = byStatus[status]?.count || 0;
                                const qty = byStatus[status]?.total_qty || 0;
                                const nextFilters = { ...filters, status: filters.status === status ? '' : status };
                                return (
                                    <div key={status} className="metric-card" style={{ cursor: 'pointer', border: filters.status === status ? `2px solid ${cfg.color}` : undefined }}
                                    onClick={() => { setFilters(nextFilters); fetchData(nextFilters); }}>
                                    <div className="metric-label">{cfg.label}</div>
                                    <div className="metric-value" style={{ color: cfg.color }}>{count}</div>
                                    <div style={{ fontSize: 12, color: '#6b7280', marginTop: 2 }}>{t('common.quantity', 'كمية')}: {formatNumber(qty)}</div>
                                </div>
                            );
                        })}
                    </div>

                    {/* Completion Rate */}
                    {totalOrders > 0 && (
                        <div className="card" style={{ marginBottom: 16 }}>
                            <h3 className="section-title">{t('manufacturing.work_orders_report.completion_rate', 'معدل الإكمال')}</h3>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginTop: 12 }}>
                                <div style={{ flex: 1 }}>
                                    <div style={{ background: '#e5e7eb', borderRadius: 999, height: 16, overflow: 'hidden' }}>
                                        <div style={{
                                            width: `${summary?.completion_rate_pct || 0}%`,
                                            background: 'linear-gradient(90deg, #22c55e, #16a34a)',
                                            height: '100%', borderRadius: 999, transition: 'width 0.5s'
                                        }} />
                                    </div>
                                </div>
                                <span style={{ fontWeight: 700, fontSize: 18, color: '#22c55e', minWidth: 60, textAlign: 'center' }}>
                                    {formatNumber(summary?.completion_rate_pct || 0, 1)}%
                                </span>
                            </div>
                        </div>
                    )}

                    {/* Orders Table */}
                    <div className="card">
                        <h3 className="section-title">{t('manufacturing.work_orders_report.orders_list', 'قائمة الأوامر')} ({orders.length})</h3>
                        {orders.length === 0 ? (
                            <div className="empty-state"><p>{t('common.no_data', 'لا توجد بيانات')}</p></div>
                        ) : (
                            <div className="table-responsive" style={{ marginTop: 8 }}>
                                <table className="data-table">
                                    <thead>
                                        <tr>
                                            <th>{t('manufacturing.order_number', 'رقم الأمر')}</th>
                                            <th>{t('manufacturing.product', 'المنتج')}</th>
                                            <th>{t('common.status_title', 'الحالة')}</th>
                                            <th>{t('manufacturing.work_orders_report.progress', 'التقدم')}</th>
                                            <th>{t('common.quantity', 'الكمية')}</th>
                                            <th>{t('manufacturing.work_orders_report.produced', 'المنتج')}</th>
                                            <th>{t('common.start_date', 'بداية')}</th>
                                            <th>{t('common.due_date', 'الاستحقاق')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {orders.map(o => {
                                            const pct = o.completion_percent || 0;
                                            const cfg = statusConfig[o.status] || { label: o.status, color: '#6b7280', bg: '#f3f4f6' };
                                            const isOverdue = Boolean(o.is_overdue);
                                            return (
                                                <tr key={o.id} style={{ cursor: 'pointer' }} onClick={() => navigate(`/manufacturing/orders/${o.id}`)}>
                                                    <td><strong style={{ color: isOverdue ? '#ef4444' : undefined }}>{o.order_number}</strong></td>
                                                    <td>{o.product_name}</td>
                                                    <td>
                                                        <span className="status-badge" style={{ background: cfg.bg, color: cfg.color, fontWeight: 600 }}>
                                                            {cfg.label}
                                                        </span>
                                                    </td>
                                                    <td style={{ minWidth: 120 }}>
                                                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                                            <div style={{ flex: 1, background: '#e5e7eb', borderRadius: 999, height: 6, overflow: 'hidden' }}>
                                                                <div style={{ width: `${pct}%`, background: o.completion_status === 'complete' ? '#22c55e' : '#3b82f6', height: '100%', borderRadius: 999 }} />
                                                            </div>
                                                            <span style={{ fontSize: 12, fontWeight: 600, minWidth: 35 }}>{pct}%</span>
                                                        </div>
                                                    </td>
                                                    <td>{formatNumber(o.quantity)}</td>
                                                    <td>{formatNumber(o.produced_quantity || 0)}</td>
                                                    <td>{formatDate(o.start_date)}</td>
                                                    <td style={{ color: isOverdue ? '#ef4444' : undefined, fontWeight: isOverdue ? 700 : undefined }}>
                                                        {formatDate(o.due_date)} {isOverdue && '⚠️'}
                                                    </td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>
                </>
            )}
        </div>
    );
};

export default WorkOrderStatusReport;
