import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { timesheetAPI, projectsAPI } from '../../utils/api';
import { formatNumber } from '../../utils/format';
import { TrendingUp, TrendingDown, Clock, DollarSign, Search } from 'lucide-react';
import '../../index.css';
import '../../components/ModuleStyles.css';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

const KpiCard = ({ label, value, sub, color }) => (
    <div className="kpi-card" style={{ borderLeft: `4px solid ${color}` }}>
        <div className="kpi-label">{label}</div>
        <div className="kpi-value" style={{ color }}>{value}</div>
        {sub && <div className="kpi-sub">{sub}</div>}
    </div>
);

// Simple horizontal bar chart component
const BarChart = ({ data, t }) => {
    return (
        <div style={{ marginTop: 16 }}>
            {data.map((d, i) => (
                <div key={i} style={{ marginBottom: 16 }}>
                    <div style={{ fontWeight: 600, marginBottom: 4 }}>{d.label}</div>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                        <span style={{ width: 80, fontSize: 12, color: '#6c757d' }}>{t('common.revenue')}</span>
                        <div style={{ flex: 1, background: '#e9ecef', borderRadius: 4, height: 18, position: 'relative' }}>
                            <div style={{
                                width: `${d.revenue_bar_pct || '0'}%`,
                                background: '#28a745',
                                height: '100%',
                                borderRadius: 4,
                                minWidth: 2,
                            }} />
                        </div>
                        <span style={{ width: 80, fontSize: 12, textAlign: 'right' }}>
                            {formatNumber(d.revenue, 0)}
                        </span>
                    </div>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 4 }}>
                        <span style={{ width: 80, fontSize: 12, color: '#6c757d' }}>{t('common.cost')}</span>
                        <div style={{ flex: 1, background: '#e9ecef', borderRadius: 4, height: 18, position: 'relative' }}>
                            <div style={{
                                width: `${d.cost_bar_pct || '0'}%`,
                                background: d.profit_status === 'profitable' ? '#ffc107' : '#dc3545',
                                height: '100%',
                                borderRadius: 4,
                                minWidth: 2,
                            }} />
                        </div>
                        <span style={{ width: 80, fontSize: 12, textAlign: 'right' }}>
                            {formatNumber(d.cost, 0)}
                        </span>
                    </div>
                </div>
            ))}
        </div>
    );
};

const ProjectProfitability = () => {
    const { t, i18n } = useTranslation();
    const isRTL = i18n.language === 'ar';

    const [projects, setProjects] = useState([]);
    const [selectedProjectId, setSelectedProjectId] = useState('');
    const [report, setReport] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    useEffect(() => {
        projectsAPI.list().then(res => setProjects(res.data || [])).catch(() => {});
    }, []);

    const loadReport = async (projectId) => {
        if (!projectId) return;
        setLoading(true);
        setError('');
        setReport(null);
        try {
            const res = await timesheetAPI.getProfitability(projectId);
            setReport(res.data);
        } catch (e) {
            setError(t('timetracking.profitability_error'));
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (selectedProjectId) loadReport(selectedProjectId);
    }, [selectedProjectId]);

    const fmt = (n) => formatNumber(n || 0);
    const isProfitable = report?.profit_status === 'profitable';

    return (
        <div className="module-container" dir={isRTL ? 'rtl' : 'ltr'}>
            <BackButton />
            <div className="module-header">
                <h1>{t('timetracking.profitability_report')}</h1>
            </div>

            <div style={{ display: 'flex', gap: 12, marginBottom: 24, alignItems: 'center' }}>
                <Search size={16} />
                <select
                    className="form-control"
                    style={{ maxWidth: 320 }}
                    value={selectedProjectId}
                    onChange={e => setSelectedProjectId(e.target.value)}
                >
                    <option value="">{t('timetracking.select_project')}</option>
                    {projects.map(p => (
                        <option key={p.id} value={p.id}>{p.project_name}</option>
                    ))}
                </select>
            </div>

            {loading && <PageLoading />}
            {error && <div className="alert alert-danger">{error}</div>}

            {report && (
                <>
                    <div className="kpi-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16, marginBottom: 24 }}>
                        <KpiCard
                            label={t('timetracking.total_hours')}
                            value={fmt(report.total_hours) + ' h'}
                            sub={`${fmt(report.billable_hours)} h ${t('timetracking.billable')}`}
                            color="#007bff"
                        />
                        <KpiCard
                            label={t('timetracking.billable_revenue')}
                            value={fmt(report.billable_revenue)}
                            sub={t('timetracking.approved_hours_only')}
                            color="#28a745"
                        />
                        <KpiCard
                            label={t('timetracking.total_cost')}
                            value={fmt(report.total_cost)}
                            sub={`${t('timetracking.expenses')}: ${fmt(report.total_expenses)}`}
                            color="#ffc107"
                        />
                        <KpiCard
                            label={t('timetracking.profit')}
                            value={fmt(report.profit)}
                            sub={`${t('timetracking.margin')}: ${fmt(report.margin_pct)}%`}
                            color={isProfitable ? '#28a745' : '#dc3545'}
                        />
                        <KpiCard
                            label={t('timetracking.planned_budget')}
                            value={fmt(report.planned_budget)}
                            sub={report.budget_status === 'over_budget'
                                ? t('timetracking.over_budget')
                                : t('timetracking.within_budget')}
                            color="#6f42c1"
                        />
                    </div>

                    <div className="card" style={{ padding: 24 }}>
                        <h3>{t('timetracking.revenue_vs_cost')}</h3>
                        <BarChart data={[{
                            label: report.project_name,
                            revenue: report.billable_revenue,
                            cost: report.total_cost,
                            revenue_bar_pct: report.revenue_bar_pct,
                            cost_bar_pct: report.cost_bar_pct,
                            profit_status: report.profit_status,
                        }]} t={t} />

                        <div style={{ marginTop: 24 }}>
                            <table className="data-table">
                                <tbody>
                                    <tr>
                                        <td><Clock size={14} /> {t('timetracking.billable_hours')}</td>
                                        <td style={{ fontWeight: 600 }}>{fmt(report.billable_hours)} h</td>
                                    </tr>
                                    <tr>
                                        <td><Clock size={14} /> {t('timetracking.non_billable_hours')}</td>
                                        <td style={{ fontWeight: 600 }}>{fmt(report.non_billable_hours)} h</td>
                                    </tr>
                                    <tr>
                                        <td><DollarSign size={14} /> {t('timetracking.billable_revenue')}</td>
                                        <td style={{ fontWeight: 600, color: '#28a745' }}>{fmt(report.billable_revenue)}</td>
                                    </tr>
                                    <tr>
                                        <td><DollarSign size={14} /> {t('timetracking.total_expenses')}</td>
                                        <td style={{ fontWeight: 600 }}>{fmt(report.total_expenses)}</td>
                                    </tr>
                                    <tr>
                                        <td><DollarSign size={14} /> {t('timetracking.total_cost')}</td>
                                        <td style={{ fontWeight: 600 }}>{fmt(report.total_cost)}</td>
                                    </tr>
                                    <tr>
                                        <td>
                                            {isProfitable
                                                ? <TrendingUp size={14} color="#28a745" />
                                                : <TrendingDown size={14} color="#dc3545" />
                                            }
                                            {' '}{t('timetracking.profit')}
                                        </td>
                                        <td style={{ fontWeight: 700, color: isProfitable ? '#28a745' : '#dc3545' }}>
                                            {fmt(report.profit)}
                                        </td>
                                    </tr>
                                    <tr>
                                        <td>{t('timetracking.margin_pct')}</td>
                                        <td style={{ fontWeight: 700, color: isProfitable ? '#28a745' : '#dc3545' }}>
                                            {fmt(report.margin_pct)}%
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </>
            )}
        </div>
    );
};

export default ProjectProfitability;
