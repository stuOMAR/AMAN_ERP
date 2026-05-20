
import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { FileText, BarChart2, X, Trash2, AlertTriangle, PlayCircle, Lock, TrendingUp, TrendingDown, Wallet, PieChart, Calendar, MoreVertical, Filter } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'react-hot-toast';
import { budgetsAPI, costCentersAPI } from '../../utils/api';
import { useBranch } from '../../context/BranchContext';
import { useTheme } from '../../context/ThemeContext';
import { formatNumber } from '../../utils/format';
import { getCurrency, hasPermission } from '../../utils/auth';
import CustomDatePicker from '../../components/common/CustomDatePicker';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates';
import { formatDate } from '../../utils/dateUtils';

const STATUS_BADGE = {
    draft: { bg: '#f3f4f6', color: '#6b7280', icon: FileText },
    active: { bg: '#dcfce7', color: '#16a34a', icon: PlayCircle },
    closed: { bg: '#fef3c7', color: '#d97706', icon: Lock },
};

const Budgets = () => {
    const { t } = useTranslation();
    const { darkMode } = useTheme();
    const navigate = useNavigate();
    const [budgets, setBudgets] = useState([]);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [actionLoading, setActionLoading] = useState(false);
    const [stats, setStats] = useState(null);
    const [alerts, setAlerts] = useState([]);
    const [openMenu, setOpenMenu] = useState(null);
    const [costCenters, setCostCenters] = useState([]);
    const [selectedCC, setSelectedCC] = useState('');
    const currency = getCurrency() || '';
    const { currentBranch } = useBranch();
    const canManageBudgets = hasPermission('accounting.budgets.manage');
    const permissionDenied = () => toast.error(t('common.permission_denied', 'ليس لديك صلاحية تنفيذ هذا الإجراء'));

    const [formData, setFormData] = useState({
        name: '',
        start_date: new Date().toISOString().split('T')[0],
        end_date: new Date(Date.now() + 365 * 24 * 60 * 60 * 1000).toISOString().split('T')[0],
        description: '',
        cost_center_id: ''
    });

    useEffect(() => {
        fetchCostCenters();
    }, [currentBranch]);

    const fetchCostCenters = async () => {
        try {
            const params = {};
            if (currentBranch?.id) params.branch_id = currentBranch.id;
            const res = await costCentersAPI.list(params);
            setCostCenters(res.data || []);
        } catch (err) {
            console.error(err);
        }
    };

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchAll();
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch, selectedCC]);

    const fetchAll = async () => {
        setLoading(true);
        try {
            const params = {};
            if (currentBranch?.id) params.branch_id = currentBranch.id;
            if (selectedCC) params.cost_center_id = selectedCC;
            params.threshold = 80;
            const [budgetsRes, statsRes, alertsRes] = await Promise.all([
                budgetsAPI.list(params),
                budgetsAPI.getStats(params).catch(() => ({ data: null })),
                budgetsAPI.getOverrunAlerts(params).catch(() => ({ data: [] }))
            ]);
            setBudgets(budgetsRes.data || []);
            setStats(statsRes.data);
            setAlerts(alertsRes.data || []);
        } catch (error) {
            console.error(error);
        } finally {
            setLoading(false);
            setInitialLoad(false);
        }
    };

    const handleCreate = async (e) => {
        e.preventDefault();
        if (!canManageBudgets) {
            permissionDenied();
            return;
        }
        setActionLoading(true);
        try {
            const payload = { ...formData };
            if (currentBranch?.id) payload.branch_id = currentBranch.id;
            if (payload.cost_center_id) payload.cost_center_id = parseInt(payload.cost_center_id);
            else delete payload.cost_center_id;
            await (payload.cost_center_id ? budgetsAPI.createByCostCenter(payload) : budgetsAPI.create(payload));
            toast.success(t('common.success'));
            setIsModalOpen(false);
            setFormData({ name: '', start_date: new Date().toISOString().split('T')[0], end_date: new Date(Date.now() + 365 * 24 * 60 * 60 * 1000).toISOString().split('T')[0], description: '', cost_center_id: '' });
            fetchAll();
        } catch (error) {
            console.error(error);
            toast.error(error.response?.data?.detail || t('common.error'));
        } finally {
            setActionLoading(false);
        }
    };

    const handleDelete = async (id) => {
        if (!canManageBudgets) {
            permissionDenied();
            return;
        }
        if (!window.confirm(t('common.confirm_delete'))) return;
        try {
            await budgetsAPI.delete(id);
            toast.success(t('common.success'));
            fetchAll();
        } catch (error) {
            toast.error(t('common.error'));
        }
    };

    const handleActivate = async (id) => {
        if (!canManageBudgets) {
            permissionDenied();
            return;
        }
        try {
            await budgetsAPI.activate(id);
            toast.success(t('accounting.budgets.activated'));
            fetchAll();
        } catch (error) {
            toast.error(error.response?.data?.detail || t('common.error'));
        }
    };

    const handleClose = async (id) => {
        if (!canManageBudgets) {
            permissionDenied();
            return;
        }
        if (!window.confirm(t('accounting.budgets.confirm_close'))) return;
        try {
            await budgetsAPI.close(id);
            toast.success(t('accounting.budgets.closed_success'));
            fetchAll();
        } catch (error) {
            toast.error(error.response?.data?.detail || t('common.error'));
        }
    };

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                        <BackButton />
                        <div>
                            <h1 className="workspace-title">{t('accounting.budgets.title')}</h1>
                            <p className="text-muted small mb-0">{t('accounting.budgets.subtitle')}</p>
                        </div>
                    </div>
                    {canManageBudgets && (
                        <button onClick={() => setIsModalOpen(true)} className="btn btn-primary">
                            <span style={{ marginLeft: '8px' }}>+</span>
                            {t('accounting.budgets.new')}
                        </button>
                    )}
                </div>
            </div>

            {/* Filters */}
            <div style={{ display: 'flex', gap: '12px', marginBottom: '20px', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Filter size={16} style={{ color: 'var(--text-muted)' }} />
                    <select
                        className="form-input"
                        value={selectedCC}
                        onChange={(e) => setSelectedCC(e.target.value)}
                        style={{ minWidth: '200px', padding: '8px 12px', fontSize: '13px' }}
                    >
                        <option value="">{t('accounting.budgets.all_cost_centers', 'جميع مراكز التكلفة')}</option>
                        {costCenters.map(cc => (
                            <option key={cc.id} value={cc.id}>{cc.center_name}</option>
                        ))}
                    </select>
                </div>
            </div>

            {/* Stats Cards */}
            {stats && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', marginBottom: '20px' }}>
                    <div className="card" style={{ padding: '16px', display: 'flex', alignItems: 'center', gap: '14px' }}>
                        <div style={{ width: '42px', height: '42px', borderRadius: '10px', background: '#eff6ff', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                            <PieChart size={20} style={{ color: '#2563eb' }} />
                        </div>
                        <div>
                            <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('accounting.budgets.stats.total')}</div>
                            <div style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-main)' }}>{stats.total_budgets}</div>
                            <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                                {t('accounting.budgets.stats.active')}: {stats.active_count} | {t('accounting.budgets.stats.draft')}: {stats.draft_count}
                            </div>
                        </div>
                    </div>
                    <div className="card" style={{ padding: '16px', display: 'flex', alignItems: 'center', gap: '14px' }}>
                        <div style={{ width: '42px', height: '42px', borderRadius: '10px', background: '#f0fdf4', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                            <TrendingUp size={20} style={{ color: '#16a34a' }} />
                        </div>
                        <div>
                            <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('accounting.budgets.stats.total_planned')}</div>
                            <div style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-main)' }}>{formatNumber(stats.total_planned)}</div>
                            <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{currency}</div>
                        </div>
                    </div>
                    <div className="card" style={{ padding: '16px', display: 'flex', alignItems: 'center', gap: '14px' }}>
                        <div style={{ width: '42px', height: '42px', borderRadius: '10px', background: '#fffbeb', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                            <TrendingDown size={20} style={{ color: '#d97706' }} />
                        </div>
                        <div>
                            <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('accounting.budgets.stats.total_actual')}</div>
                            <div style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-main)' }}>{formatNumber(stats.total_actual)}</div>
                            <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{currency} • {stats.overall_usage_pct}%</div>
                        </div>
                    </div>
                    <div className="card" style={{ padding: '16px', display: 'flex', alignItems: 'center', gap: '14px' }}>
                        <div style={{ width: '42px', height: '42px', borderRadius: '10px', background: stats.overrun_items_count > 0 ? '#fef2f2' : '#f0fdf4', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                            <AlertTriangle size={20} style={{ color: stats.overrun_items_count > 0 ? '#ef4444' : '#16a34a' }} />
                        </div>
                        <div>
                            <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{t('accounting.budgets.stats.overruns')}</div>
                            <div style={{ fontSize: '20px', fontWeight: 700, color: stats.overrun_items_count > 0 ? '#ef4444' : '#16a34a' }}>{stats.overrun_items_count}</div>
                            <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{stats.overrun_items_count > 0 ? t('common.warning') : t('common.good')}</div>
                        </div>
                    </div>
                </div>
            )}

            {/* Overrun Alerts */}
            {alerts.length > 0 && (
                <div className="card card-flush" style={{ marginBottom: '20px', borderLeft: '4px solid #ef4444' }}>
                    <div style={{ padding: '16px 20px', display: 'flex', alignItems: 'center', gap: '10px', borderBottom: '1px solid var(--border-color)' }}>
                        <AlertTriangle size={18} style={{ color: '#ef4444' }} />
                        <span style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-main)' }}>{t('accounting.budgets.overrun_alerts')}</span>
                        <span style={{ background: '#fef2f2', color: '#ef4444', padding: '2px 8px', borderRadius: '10px', fontSize: '11px', fontWeight: 700 }}>{alerts.length}</span>
                    </div>
                    <div style={{ overflowX: 'auto' }}>
                        <table className="data-table" style={{ fontSize: '13px' }}>
                            <thead>
                                <tr>
                                    <th>{t('accounting.budgets.budget_name')}</th>
                                    <th>{t('accounting.account_name')}</th>
                                    <th style={{ textAlign: 'center' }}>{t('reports.budget_vs_actual.planned')}</th>
                                    <th style={{ textAlign: 'center' }}>{t('reports.budget_vs_actual.actual')}</th>
                                    <th style={{ textAlign: 'center' }}>{t('accounting.budgets.usage')}</th>
                                    <th style={{ textAlign: 'center' }}>{t('common.status_title')}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {alerts.slice(0, 10).map((alert, idx) => (
                                    <tr key={idx}>
                                        <td style={{ fontWeight: 600 }}>{alert.budget_name}</td>
                                        <td>
                                            <span style={{ color: 'var(--primary)', marginRight: '6px' }}>{alert.account_number}</span>
                                            {alert.account_name}
                                        </td>
                                        <td style={{ textAlign: 'center' }}>{formatNumber(alert.planned)}</td>
                                        <td style={{ textAlign: 'center' }}>{formatNumber(alert.actual)}</td>
                                        <td style={{ textAlign: 'center' }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', justifyContent: 'center' }}>
                                                <div style={{ width: '50px', height: '4px', background: '#f3f4f6', borderRadius: '2px', overflow: 'hidden' }}>
                                                    <div style={{
                                                        height: '100%',
                                                        width: `${Math.min(alert.usage_percentage, 100)}%`,
                                                        background: alert.severity === 'critical' ? '#dc2626' : alert.severity === 'danger' ? '#f97316' : '#f59e0b',
                                                        borderRadius: '2px',
                                                    }} />
                                                </div>
                                                <span style={{ fontSize: '11px', fontWeight: 700 }}>{alert.usage_percentage}%</span>
                                            </div>
                                        </td>
                                        <td style={{ textAlign: 'center' }}>
                                            <span style={{
                                                padding: '3px 10px', borderRadius: '20px', fontSize: '11px', fontWeight: 600,
                                                background: alert.severity === 'critical' ? '#fef2f2' : '#fffbeb',
                                                color: alert.severity === 'critical' ? '#dc2626' : '#d97706',
                                            }}>
                                                {alert.severity === 'critical' ? t('accounting.budgets.over_budget') :
                                                 alert.severity === 'danger' ? t('accounting.budgets.near_limit') :
                                                 t('accounting.budgets.warning_label')}
                                            </span>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {/* Budget Cards */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: '16px' }}>
                {loading ? (
                    <div style={{ gridColumn: '1 / -1', textAlign: 'center', padding: '40px 20px' }}>
                        <PageLoading />
                    </div>
                ) : budgets.length === 0 ? (
                    <div style={{ gridColumn: '1 / -1', textAlign: 'center', padding: '40px 20px' }}>
                        <Wallet size={40} style={{ color: 'var(--text-muted)', marginBottom: '12px' }} />
                        <h3 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text-muted)', margin: 0 }}>{t('common.no_data')}</h3>
                    </div>
                ) : (
                    budgets.map((budget) => {
                        const status = budget.status || 'draft';
                        const badge = STATUS_BADGE[status] || STATUS_BADGE.draft;
                        const StatusIcon = badge.icon;

                        return (
                            <div key={budget.id} className="card" style={{ padding: '20px', position: 'relative' }}>
                                {/* Header */}
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '12px' }}>
                                    <div style={{ flex: 1, minWidth: 0 }}>
                                        <h3 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-main)', margin: '0 0 6px 0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                            {budget.name}
                                        </h3>
                                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', padding: '3px 10px', borderRadius: '20px', fontSize: '11px', fontWeight: 600, background: badge.bg, color: badge.color }}>
                                            <StatusIcon size={12} />
                                            {t(`accounting.budgets.status_${status}`, status)}
                                        </span>
                                    </div>
                                    {canManageBudgets && (
                                    <div style={{ position: 'relative' }}>
                                        <button
                                            onClick={() => setOpenMenu(openMenu === budget.id ? null : budget.id)}
                                            style={{ width: '28px', height: '28px', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'transparent', border: 'none', borderRadius: '6px', cursor: 'pointer', color: 'var(--text-muted)' }}
                                        >
                                            <MoreVertical size={14} />
                                        </button>
                                        {openMenu === budget.id && (
                                            <div style={{ position: 'absolute', top: '100%', left: 0, zIndex: 50, minWidth: '150px', background: darkMode ? 'var(--bg-card)' : '#fff', border: '1px solid var(--border-color)', borderRadius: '8px', boxShadow: '0 4px 12px rgba(0,0,0,0.1)', padding: '4px' }}>
                                                {status === 'draft' && (
                                                    <button onClick={() => { handleActivate(budget.id); setOpenMenu(null); }} style={{ display: 'flex', alignItems: 'center', gap: '8px', width: '100%', padding: '8px 10px', fontSize: '12px', fontWeight: 500, color: '#16a34a', background: 'transparent', border: 'none', borderRadius: '6px', cursor: 'pointer' }}
                                                        onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
                                                        onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                                                    >
                                                        <PlayCircle size={13} /> {t('accounting.budgets.activate')}
                                                    </button>
                                                )}
                                                {status === 'active' && (
                                                    <button onClick={() => { handleClose(budget.id); setOpenMenu(null); }} style={{ display: 'flex', alignItems: 'center', gap: '8px', width: '100%', padding: '8px 10px', fontSize: '12px', fontWeight: 500, color: '#d97706', background: 'transparent', border: 'none', borderRadius: '6px', cursor: 'pointer' }}
                                                        onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
                                                        onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                                                    >
                                                        <Lock size={13} /> {t('accounting.budgets.close_budget')}
                                                    </button>
                                                )}
                                                {status !== 'active' && (
                                                    <button onClick={() => { handleDelete(budget.id); setOpenMenu(null); }} style={{ display: 'flex', alignItems: 'center', gap: '8px', width: '100%', padding: '8px 10px', fontSize: '12px', fontWeight: 500, color: '#ef4444', background: 'transparent', border: 'none', borderRadius: '6px', cursor: 'pointer' }}
                                                        onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover)'}
                                                        onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                                                    >
                                                        <Trash2 size={13} /> {t('common.delete')}
                                                    </button>
                                                )}
                                            </div>
                                        )}
                                    </div>
                                    )}
                                </div>

                                {/* Description */}
                                {budget.description && (
                                    <p style={{ fontSize: '12px', color: 'var(--text-muted)', margin: '0 0 12px 0', lineHeight: 1.4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                        {budget.description}
                                    </p>
                                )}

                                {/* Date range */}
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 10px', background: darkMode ? 'var(--bg-secondary)' : '#f8fafc', borderRadius: '8px', marginBottom: '14px' }}>
                                    <Calendar size={13} style={{ color: 'var(--primary)', flexShrink: 0 }} />
                                    <div style={{ flex: 1, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                        <div style={{ textAlign: 'center' }}>
                                            <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontWeight: 500 }}>{t('common.start_date')}</div>
                                            <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-main)' }}>{formatDate(budget.start_date)}</div>
                                        </div>
                                        <div style={{ width: '20px', height: '1px', background: 'var(--border-color)' }} />
                                        <div style={{ textAlign: 'center' }}>
                                            <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontWeight: 500 }}>{t('common.end_date')}</div>
                                            <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-main)' }}>{formatDate(budget.end_date)}</div>
                                        </div>
                                    </div>
                                </div>

                                {/* Action buttons */}
                                <div style={{ display: 'flex', gap: '8px' }}>
                                    <button
                                        className="btn btn-outline-primary btn-sm"
                                        onClick={() => navigate(`/accounting/budgets/${budget.id}/items`)}
                                        style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px', borderRadius: '8px', fontSize: '12px' }}
                                    >
                                        <FileText size={13} /> {t('accounting.budgets.items')}
                                    </button>
                                    <button
                                        className="btn btn-primary btn-sm"
                                        onClick={() => navigate(`/accounting/budgets/${budget.id}/report`)}
                                        style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px', borderRadius: '8px', fontSize: '12px' }}
                                    >
                                        <BarChart2 size={13} /> {t('accounting.budgets.report')}
                                    </button>
                                </div>
                            </div>
                        );
                    })
                )}
            </div>

            {/* Create Modal */}
            {isModalOpen && canManageBudgets && (
                <div className="modal-overlay">
                    <div className="modal-content" style={{ maxWidth: '500px' }}>
                        <div className="modal-header">
                            <h2 className="modal-title">{t('accounting.budgets.new')}</h2>
                            <button type="button" className="btn-icon" style={{ background: 'transparent' }} onClick={() => setIsModalOpen(false)}>
                                <X size={20} />
                            </button>
                        </div>
                        <form onSubmit={handleCreate}>
                            <div className="modal-body">
                                <div className="form-group">
                                    <label className="form-label">{t('common.name')}</label>
                                    <input type="text" className="form-input" required value={formData.name} onChange={(e) => setFormData({ ...formData, name: e.target.value })} placeholder={t('accounting.budgets.name_placeholder')} />
                                </div>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                                    <div className="form-group">
                                        <CustomDatePicker label={t('common.start_date')} selected={formData.start_date ? new Date(formData.start_date + 'T00:00:00') : null} onChange={(dateStr) => setFormData({ ...formData, start_date: dateStr })} required />
                                    </div>
                                    <div className="form-group">
                                        <CustomDatePicker label={t('common.end_date')} selected={formData.end_date ? new Date(formData.end_date + 'T00:00:00') : null} onChange={(dateStr) => setFormData({ ...formData, end_date: dateStr })} required />
                                    </div>
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('common.description')}</label>
                                    <textarea className="form-input" rows="3" value={formData.description} onChange={(e) => setFormData({ ...formData, description: e.target.value })} placeholder={t('common.notes')}></textarea>
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('accounting.cost_center', 'مركز التكلفة')}</label>
                                    <select
                                        className="form-input"
                                        value={formData.cost_center_id}
                                        onChange={(e) => setFormData({ ...formData, cost_center_id: e.target.value })}
                                    >
                                        <option value="">{t('common.none', 'بدون')}</option>
                                        {costCenters.map(cc => (
                                            <option key={cc.id} value={cc.id}>{cc.center_name}</option>
                                        ))}
                                    </select>
                                </div>
                            </div>
                            <div className="modal-footer">
                                <button type="button" className="btn" style={{ background: 'var(--bg-hover)' }} onClick={() => setIsModalOpen(false)}>{t('common.cancel')}</button>
                                <button type="submit" className="btn btn-primary" disabled={actionLoading}>{actionLoading ? t('common.saving') : t('common.save')}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
};

export default Budgets;
