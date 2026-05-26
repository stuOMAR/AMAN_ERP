import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { projectsAPI } from '../../utils/api';
import { formatNumber } from '../../utils/format';
import '../../components/ModuleStyles.css';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

const ProjectFinancialsReport = () => {
    const { t } = useTranslation();
    const [loading, setLoading] = useState(false);
    const [report, setReport] = useState(null);
    const [statusFilter, setStatusFilter] = useState('');

    const fetchReport = async () => {
        setLoading(true);
        try {
            const params = {};
            if (statusFilter) params.status_filter = statusFilter;
            const res = await projectsAPI.getProfitabilityReport(params);
            setReport(res.data);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchReport(); }, []);

    const statusLabels = {
        planning:    t('projects.status.planning', 'تخطيط'),
        in_progress: t('projects.status.in_progress', 'قيد التنفيذ'),
        completed:   t('projects.status.completed', 'مكتمل'),
        on_hold:     t('projects.status.on_hold', 'متوقف'),
        cancelled:   t('projects.status.cancelled', 'ملغي'),
    };

    const totals = report?.totals || {};

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">💰 {t('projects.reports.financials_title', 'ماليات المشاريع')}</h1>
                    <p className="workspace-subtitle">{t('projects.reports.financials_subtitle', 'تحليل الربحية والتكاليف لكل مشروع')}</p>
                </div>
            </div>

            {/* Filters */}
            <div className="card" style={{ marginBottom: 16 }}>
                <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
                    <div className="form-group" style={{ flex: 1, minWidth: 180 }}>
                        <label className="form-label">{t('common.status_title', 'الحالة')}</label>
                        <select className="form-input" value={statusFilter}
                            onChange={e => setStatusFilter(e.target.value)}>
                            <option value="">{t('common.all', 'الكل')}</option>
                            {Object.entries(statusLabels).map(([k, v]) => (
                                <option key={k} value={k}>{v}</option>
                            ))}
                        </select>
                    </div>
                    <button className="btn btn-primary" onClick={fetchReport} disabled={loading}>
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
                            <div className="metric-label">{t('projects.reports.total_revenue', 'إجمالي الإيرادات')}</div>
                            <div className="metric-value text-success">{formatNumber(totals.total_revenue || 0)}</div>
                        </div>
                        <div className="metric-card">
                            <div className="metric-label">{t('projects.reports.total_expense', 'إجمالي المصاريف')}</div>
                            <div className="metric-value text-danger">{formatNumber(totals.total_expense || 0)}</div>
                        </div>
                        <div className="metric-card">
                            <div className="metric-label">{t('projects.reports.total_profit', 'صافي الربح')}</div>
                            <div className="metric-value" style={{ color: totals.profit_status === 'profitable' ? 'var(--success)' : 'var(--danger)' }}>
                                {formatNumber(totals.total_profit || 0)}
                            </div>
                        </div>
                        <div className="metric-card">
                            <div className="metric-label">{t('projects.reports.avg_margin', 'متوسط الهامش')}</div>
                            <div className="metric-value text-primary">{formatNumber(totals.avg_margin_pct || 0, 1)}%</div>
                        </div>
                    </div>

                    {/* Projects Table */}
                    <div className="card">
                        <h3 className="section-title">{t('projects.reports.projects_profitability', 'ربحية المشاريع')} ({totals.project_count || 0})</h3>
                        {!report?.projects?.length ? (
                            <div className="empty-state"><p>{t('common.no_data', 'لا توجد بيانات')}</p></div>
                        ) : (
                            <div className="table-responsive" style={{ marginTop: 8 }}>
                                <table className="data-table">
                                    <thead>
                                        <tr>
                                            <th>{t('projects.fields.code', 'الرمز')}</th>
                                            <th>{t('projects.fields.name', 'اسم المشروع')}</th>
                                            <th>{t('common.status_title', 'الحالة')}</th>
                                            <th>{t('projects.fields.budget', 'الميزانية')}</th>
                                            <th>{t('projects.reports.revenue', 'الإيرادات')}</th>
                                            <th>{t('projects.reports.expenses', 'المصاريف')}</th>
                                            <th>{t('projects.reports.net_profit', 'الربح')}</th>
                                            <th>{t('projects.reports.margin', 'الهامش')}</th>
                                            <th>{t('projects.reports.budget_variance', 'انحراف الميزانية')}</th>
                                            <th>{t('projects.fields.progress', 'الإنجاز')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {report.projects.map((p) => (
                                            <tr key={p.project_id}>
                                                <td><strong>{p.project_code}</strong></td>
                                                <td style={{ fontWeight: 600 }}>{p.project_name}</td>
                                                <td>
                                                    <span className={`status-badge ${p.status === 'completed' ? 'status-active' : p.status === 'in_progress' ? 'status-pending' : ''}`}>
                                                        {statusLabels[p.status] || p.status}
                                                    </span>
                                                </td>
                                                <td>{formatNumber(p.planned_budget)}</td>
                                                <td style={{ color: 'var(--success)' }}>{formatNumber(p.total_revenues)}</td>
                                                <td style={{ color: 'var(--danger)' }}>{formatNumber(p.total_expenses)}</td>
                                                <td style={{ fontWeight: 700, color: p.profit_status === 'profitable' ? 'var(--success)' : 'var(--danger)' }}>
                                                    {formatNumber(p.net_profit)}
                                                </td>
                                                <td>
                                                    <span className={`status-badge ${p.profit_status === 'profitable' ? 'status-active' : 'status-rejected'}`}>
                                                        {formatNumber(p.margin_pct, 1)}%
                                                    </span>
                                                </td>
                                                <td style={{ color: p.budget_status === 'within_budget' ? 'var(--success)' : 'var(--danger)' }}>
                                                    {formatNumber(p.budget_variance)}
                                                </td>
                                                <td>
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                                        <div style={{ flex: 1, background: '#e5e7eb', borderRadius: 999, height: 6, overflow: 'hidden', minWidth: 50 }}>
                                                            <div style={{ width: `${p.progress}%`, background: '#3b82f6', height: '100%', borderRadius: 999 }} />
                                                        </div>
                                                        <span style={{ fontSize: 11, fontWeight: 600 }}>{formatNumber(p.progress, 0)}%</span>
                                                    </div>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                    <tfoot>
                                        <tr style={{ fontWeight: 700, background: '#f9fafb' }}>
                                            <td colSpan={3}>{t('common.total', 'الإجمالي')}</td>
                                            <td>-</td>
                                            <td style={{ color: 'var(--success)' }}>{formatNumber(totals.total_revenue)}</td>
                                            <td style={{ color: 'var(--danger)' }}>{formatNumber(totals.total_expense)}</td>
                                            <td style={{ color: totals.total_profit >= 0 ? 'var(--success)' : 'var(--danger)' }}>{formatNumber(totals.total_profit)}</td>
                                            <td>{formatNumber(totals.avg_margin_pct, 1)}%</td>
                                            <td colSpan={2}>-</td>
                                        </tr>
                                    </tfoot>
                                </table>
                            </div>
                        )}
                    </div>
                </>
            )}
        </div>
    );
};

export default ProjectFinancialsReport;
