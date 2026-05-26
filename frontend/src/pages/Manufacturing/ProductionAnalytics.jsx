import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { manufacturingAPI } from '../../utils/api';
import { toastEmitter } from '../../utils/toastEmitter';
import { formatNumber } from '../../utils/format';
import '../../components/ModuleStyles.css';
import BackButton from '../../components/common/BackButton';
import DateInput from '../../components/common/DateInput';
import { ModuleKPISection } from '../../components/kpi';
import { PageLoading } from '../../components/common/LoadingStates'

const ProductionAnalytics = () => {
    const { t } = useTranslation();
    const [loading, setLoading] = useState(false);
    const [summary, setSummary] = useState(null);
    const [costReport, setCostReport] = useState(null);
    const [efficiency, setEfficiency] = useState(null);
    const [filters, setFilters] = useState({
        start_date: new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().split('T')[0],
        end_date: new Date().toISOString().split('T')[0],
    });

    const fetchAll = async () => {
        setLoading(true);
        try {
            const params = { ...filters };
            const [sumRes, costRes, effRes] = await Promise.allSettled([
                manufacturingAPI.getProductionSummary(params),
                manufacturingAPI.getProductionCostReport(params),
                manufacturingAPI.getWorkCenterEfficiency(params),
            ]);
            if (sumRes.status === 'fulfilled') setSummary(sumRes.value.data);
            if (costRes.status === 'fulfilled') setCostReport(costRes.value.data);
            if (effRes.status === 'fulfilled') setEfficiency(effRes.value.data);
        } catch (e) {
            toastEmitter.emit(t('common.error'), 'error');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchAll(); }, []);

    const statusLabels = {
        draft: t('draft', 'مسودة'),
        confirmed: t('confirmed', 'مؤكد'),
        in_progress: t('in_progress', 'قيد التنفيذ'),
        completed: t('completed', 'مكتمل'),
        cancelled: t('cancelled', 'ملغي'),
    };
    const statusColors = {
        draft: '#94a3b8',
        confirmed: '#3b82f6',
        in_progress: '#f59e0b',
        completed: '#22c55e',
        cancelled: '#ef4444',
    };

    const totalOrders = summary?.total_orders || 0;
    const byStatus = summary?.orders_by_status || {};
    const completedCount = summary?.completed_orders || 0;
    const inProgressCount = summary?.in_progress_orders || 0;

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">📊 {t('manufacturing.analytics.title', 'تحليل الإنتاج')}</h1>
                    <p className="workspace-subtitle">{t('manufacturing.analytics.subtitle', 'مراقبة مخرجات الإنتاج والكفاءة وتكاليف التصنيع')}</p>
                </div>
            </div>

            <ModuleKPISection roleKey="manufacturing" color="#ea580c" defaultOpen={false} />

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
                    <button className="btn btn-primary" onClick={fetchAll} disabled={loading}>
                        {loading ? '...' : t('common.search', 'بحث')}
                    </button>
                </div>
            </div>

            {loading ? (
                <PageLoading />
            ) : (
                <>
                    {/* KPI Metrics */}
                    <div className="metrics-grid" style={{ marginBottom: 16 }}>
                        <div className="metric-card">
                            <div className="metric-label">{t('manufacturing.analytics.total_orders', 'إجمالي الأوامر')}</div>
                            <div className="metric-value text-primary">{totalOrders}</div>
                        </div>
                        <div className="metric-card">
                            <div className="metric-label">{t('manufacturing.analytics.completed_orders', 'أوامر مكتملة')}</div>
                            <div className="metric-value text-success">{completedCount}</div>
                        </div>
                        <div className="metric-card">
                            <div className="metric-label">{t('manufacturing.analytics.in_progress_orders', 'قيد التنفيذ')}</div>
                            <div className="metric-value text-warning">{inProgressCount}</div>
                        </div>
                        <div className="metric-card">
                            <div className="metric-label">{t('manufacturing.analytics.maintenance_due', 'صيانة مستحقة')}</div>
                            <div className="metric-value text-danger">{summary?.equipment_maintenance_due || 0}</div>
                        </div>
                    </div>

                    {/* Order Status Distribution */}
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
                        <div className="card">
                            <h3 className="section-title">{t('manufacturing.analytics.status_distribution', 'توزيع حالات الأوامر')}</h3>
                            {Object.keys(byStatus).length === 0 ? (
                                <div className="empty-state"><p>{t('common.no_data', 'لا توجد بيانات')}</p></div>
                            ) : (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 12 }}>
                                    {Object.entries(byStatus).map(([status, data]) => {
                                        const pct = data.share_pct || 0;
                                        return (
                                            <div key={status}>
                                                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                                                    <span style={{ fontWeight: 600 }}>{statusLabels[status] || status}</span>
                                                    <span>{data.count} ({formatNumber(pct, 1)}%)</span>
                                                </div>
                                                <div style={{ background: '#e5e7eb', borderRadius: 999, height: 8, overflow: 'hidden' }}>
                                                    <div style={{ width: `${pct}%`, background: statusColors[status] || '#6b7280', height: '100%', borderRadius: 999, transition: 'width 0.5s' }} />
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>
                            )}
                        </div>

                        {/* Top Products */}
                        <div className="card">
                            <h3 className="section-title">{t('manufacturing.analytics.top_products', 'أكثر المنتجات إنتاجاً')}</h3>
                            {!summary?.top_produced_products?.length ? (
                                <div className="empty-state"><p>{t('common.no_data', 'لا توجد بيانات')}</p></div>
                            ) : (
                                <div className="table-responsive" style={{ marginTop: 8 }}>
                                    <table className="data-table">
                                        <thead>
                                            <tr>
                                                <th>{t('manufacturing.product', 'المنتج')}</th>
                                                <th>{t('manufacturing.analytics.produced_qty', 'الكمية المنتجة')}</th>
                                                <th>{t('manufacturing.analytics.order_count', 'عدد الأوامر')}</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {summary.top_produced_products.map((p, i) => (
                                                <tr key={i}>
                                                    <td style={{ fontWeight: 600 }}>{p.product_name}</td>
                                                    <td>{formatNumber(p.total_produced)}</td>
                                                    <td>{p.order_count}</td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            )}
                        </div>
                    </div>

                    {/* Cost Summary */}
                    {costReport?.totals && (
                        <div className="card" style={{ marginBottom: 16 }}>
                            <h3 className="section-title">{t('manufacturing.analytics.cost_analysis', 'تحليل التكاليف')}</h3>
                            <div className="metrics-grid" style={{ marginTop: 12 }}>
                                <div className="metric-card">
                                    <div className="metric-label">{t('manufacturing.analytics.material_cost', 'تكلفة المواد')}</div>
                                    <div className="metric-value text-primary">{formatNumber(costReport.totals.total_material_cost)}</div>
                                </div>
                                <div className="metric-card">
                                    <div className="metric-label">{t('manufacturing.analytics.labor_cost', 'تكلفة العمالة')}</div>
                                    <div className="metric-value text-warning">{formatNumber(costReport.totals.total_labor_cost)}</div>
                                </div>
                                <div className="metric-card">
                                    <div className="metric-label">{t('manufacturing.analytics.overhead_cost', 'تكاليف إضافية')}</div>
                                    <div className="metric-value text-secondary">{formatNumber(costReport.totals.total_overhead_cost)}</div>
                                </div>
                                <div className="metric-card">
                                    <div className="metric-label">{t('manufacturing.analytics.total_cost', 'إجمالي التكاليف')}</div>
                                    <div className="metric-value text-danger">{formatNumber(costReport.totals.total_production_cost)}</div>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Cost Details Table */}
                    {costReport?.orders?.length > 0 && (
                        <div className="card" style={{ marginBottom: 16 }}>
                            <h3 className="section-title">{t('manufacturing.analytics.cost_details', 'تفاصيل تكاليف الأوامر المكتملة')}</h3>
                            <div className="table-responsive" style={{ marginTop: 8 }}>
                                <table className="data-table">
                                    <thead>
                                        <tr>
                                            <th>{t('manufacturing.order_number', 'رقم الأمر')}</th>
                                            <th>{t('manufacturing.product', 'المنتج')}</th>
                                            <th>{t('common.quantity', 'الكمية')}</th>
                                            <th>{t('manufacturing.analytics.material_cost', 'مواد')}</th>
                                            <th>{t('manufacturing.analytics.labor_cost', 'عمالة')}</th>
                                            <th>{t('manufacturing.analytics.overhead_cost', 'إضافية')}</th>
                                            <th>{t('manufacturing.analytics.total_cost', 'الإجمالي')}</th>
                                            <th>{t('manufacturing.analytics.unit_cost', 'تكلفة الوحدة')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {costReport.orders.map((o, i) => (
                                            <tr key={i}>
                                                <td><strong>{o.order_number}</strong></td>
                                                <td>{o.product_name}</td>
                                                <td>{formatNumber(o.quantity)}</td>
                                                <td>{formatNumber(o.material_cost)}</td>
                                                <td>{formatNumber(o.labor_cost)}</td>
                                                <td>{formatNumber(o.overhead_cost)}</td>
                                                <td style={{ fontWeight: 600 }}>{formatNumber(o.total_cost)}</td>
                                                <td>{formatNumber(o.unit_cost)}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    )}

                    {/* Work Center Efficiency */}
                    {efficiency?.work_centers?.length > 0 && (
                        <div className="card">
                            <h3 className="section-title">{t('manufacturing.analytics.wc_efficiency', 'كفاءة مراكز العمل')}</h3>
                            <div className="table-responsive" style={{ marginTop: 8 }}>
                                <table className="data-table">
                                    <thead>
                                        <tr>
                                            <th>{t('manufacturing.work_center', 'مركز العمل')}</th>
                                            <th>{t('manufacturing.analytics.total_operations', 'العمليات')}</th>
                                            <th>{t('manufacturing.analytics.completed_ops', 'مكتمل')}</th>
                                            <th>{t('manufacturing.analytics.run_hours', 'ساعات التشغيل')}</th>
                                            <th>{t('manufacturing.analytics.total_output', 'الإنتاج')}</th>
                                            <th>{t('manufacturing.analytics.utilization', 'الاستغلال')}</th>
                                            <th>{t('manufacturing.analytics.total_cost', 'التكلفة')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {efficiency.work_centers.map((wc, i) => (
                                            <tr key={i}>
                                                <td style={{ fontWeight: 600 }}>{wc.work_center_name}</td>
                                                <td>{wc.total_operations}</td>
                                                <td>{wc.completed_operations}</td>
                                                <td>{formatNumber(wc.total_run_time_hours, 1)}</td>
                                                <td>{formatNumber(wc.total_output)}</td>
                                                <td>
                                                    <span className={`status-badge ${wc.utilization_direction === 'high' ? 'status-active' : wc.utilization_direction === 'medium' ? 'status-pending' : 'status-rejected'}`}>
                                                        {formatNumber(wc.utilization_percent, 1)}%
                                                    </span>
                                                </td>
                                                <td>{formatNumber(wc.total_cost)}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    )}
                </>
            )}
        </div>
    );
};

export default ProductionAnalytics;
