import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { projectsAPI } from '../../utils/api';
import { formatNumber } from '../../utils/format';
import '../../components/ModuleStyles.css';
import BackButton from '../../components/common/BackButton';
import DateInput from '../../components/common/DateInput';
import { PageLoading } from '../../components/common/LoadingStates'

const ResourceUtilizationReport = () => {
    const { t } = useTranslation();
    const [loading, setLoading] = useState(false);
    const [report, setReport] = useState(null);
    const [filters, setFilters] = useState({
        start_date: new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().split('T')[0],
        end_date: new Date().toISOString().split('T')[0],
    });

    const fetchReport = async () => {
        setLoading(true);
        try {
            const res = await projectsAPI.getResourceUtilization(filters);
            setReport(res.data);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchReport(); }, []);

    const resources = report?.resources || [];
    const summary = report?.summary || {};

    const statusColors = {
        overload: '#ef4444',
        optimal: '#22c55e',
        moderate: '#f59e0b',
        light: '#94a3b8',
    };

    const getUtilizationColor = (status) => statusColors[status] || statusColors.light;

    const getUtilizationLabel = (status) => {
        const labels = {
            overload: t('projects.load_overload', 'حمل زائد'),
            optimal: t('projects.load_optimal', 'حمل مثالي'),
            moderate: t('projects.load_moderate', 'حمل متوسط'),
            light: t('projects.load_light', 'حمل خفيف'),
        };
        return labels[status] || labels.light;
    };

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">👥 {t('projects.reports.resources_title', 'استغلال الموارد')}</h1>
                    <p className="workspace-subtitle">{t('projects.reports.resources_subtitle', 'تتبع توزيع الموظفين وأعباء العمل عبر المشاريع')}</p>
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
                            <div className="metric-label">{t('projects.reports.total_employees', 'عدد الموظفين')}</div>
                            <div className="metric-value text-primary">{summary.employee_count || 0}</div>
                        </div>
                        <div className="metric-card">
                            <div className="metric-label">{t('projects.reports.total_hours', 'إجمالي الساعات')}</div>
                            <div className="metric-value text-success">{formatNumber(summary.total_hours || 0, 1)}</div>
                        </div>
                        <div className="metric-card">
                            <div className="metric-label">{t('projects.reports.avg_utilization', 'متوسط الاستغلال')}</div>
                            <div className="metric-value">
                                {formatNumber(summary.avg_utilization || 0, 1)}%
                            </div>
                        </div>
                        <div className="metric-card">
                            <div className="metric-label">{t('projects.reports.overloaded', 'حمل زائد')}</div>
                            <div className="metric-value text-danger">
                                {summary.overloaded_count || 0}
                            </div>
                        </div>
                    </div>

                    {/* Resource Cards */}
                    {resources.length === 0 ? (
                        <div className="card">
                            <div className="empty-state">
                                <p>{t('projects.reports.no_resources', 'لا توجد بيانات موارد في الفترة المحددة')}</p>
                            </div>
                        </div>
                    ) : (
                        <>
                            {/* Visual Summary */}
                            <div className="card" style={{ marginBottom: 16 }}>
                                <h3 className="section-title">{t('projects.reports.utilization_overview', 'نظرة عامة على الاستغلال')}</h3>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 12 }}>
                                    {resources.map(r => (
                                        <div key={r.user_id}>
                                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, alignItems: 'center' }}>
                                                <span style={{ fontWeight: 600 }}>{r.name}</span>
                                                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                                                    <span style={{ fontSize: 12, color: '#6b7280' }}>{r.projects_count} {t('projects.title', 'مشاريع')}</span>
                                                    <span style={{ fontWeight: 700, color: getUtilizationColor(r.load_status), minWidth: 45, textAlign: 'left' }}>
                                                        {formatNumber(r.utilization_pct, 1)}%
                                                    </span>
                                                </div>
                                            </div>
                                            <div style={{ background: '#e5e7eb', borderRadius: 999, height: 10, overflow: 'hidden' }}>
                                                <div style={{
                                                    width: `${r.utilization_bar_pct || '0'}%`,
                                                    background: getUtilizationColor(r.load_status),
                                                    height: '100%', borderRadius: 999, transition: 'width 0.5s'
                                                }} />
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>

                            {/* Details Table */}
                            <div className="card">
                                <h3 className="section-title">{t('projects.reports.details', 'التفاصيل')}</h3>
                                <div className="table-responsive" style={{ marginTop: 8 }}>
                                    <table className="data-table">
                                        <thead>
                                            <tr>
                                                <th>{t('projects.reports.employee', 'الموظف')}</th>
                                                <th>{t('projects.reports.projects_count', 'عدد المشاريع')}</th>
                                                <th>{t('projects.reports.total_hours', 'إجمالي الساعات')}</th>
                                                <th>{t('projects.reports.avg_daily', 'متوسط يومي')}</th>
                                                <th>{t('projects.reports.working_days', 'أيام العمل')}</th>
                                                <th>{t('projects.reports.utilization', 'الاستغلال')}</th>
                                                <th>{t('projects.reports.load_status', 'الحالة')}</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {resources.map(r => (
                                                <tr key={r.user_id}>
                                                    <td style={{ fontWeight: 600 }}>{r.name}</td>
                                                    <td>{r.projects_count}</td>
                                                    <td>{formatNumber(r.total_hours, 1)}</td>
                                                    <td>{formatNumber(r.avg_daily_hours, 1)}</td>
                                                    <td>{r.working_days}</td>
                                                    <td>
                                                        <span className={`status-badge status-${r.load_status === 'overload' ? 'rejected' : r.load_status === 'optimal' ? 'active' : 'pending'}`}>
                                                            {formatNumber(r.utilization_pct, 1)}%
                                                        </span>
                                                    </td>
                                                    <td>
                                                        <span style={{ fontSize: 12, fontWeight: 600, color: getUtilizationColor(r.load_status) }}>
                                                            {getUtilizationLabel(r.load_status)}
                                                        </span>
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </>
                    )}
                </>
            )}
        </div>
    );
};

export default ResourceUtilizationReport;
