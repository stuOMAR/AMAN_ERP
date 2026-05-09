import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { scheduledReportsAPI, reportSharingAPI } from '../../services/reports';
import { branchesAPI } from '../../utils/api';
import { useBranch } from '../../context/BranchContext';
import { useToast } from '../../context/ToastContext';
import BackButton from '../../components/common/BackButton';

const REPORT_TYPE_KEYS = [
    'profit_loss', 'balance_sheet', 'trial_balance', 'general_ledger',
    'cashflow', 'sales_summary', 'sales_aging', 'detailed_pl',
    'commissions', 'inventory_valuation', 'payroll_trend',
];

const STATUS_COLORS = {
    pending: 'badge-secondary',
    running: 'badge-warning',
    completed: 'badge-success',
    failed: 'badge-danger',
};

const ScheduledReports = () => {
    const { t } = useTranslation();
    const { showToast } = useToast();
    const { currentBranch } = useBranch();

    const getReportTypeLabel = (key) => t(`reports.report_types.${key}`, key);
    const [reports, setReports] = useState([]);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const [editingId, setEditingId] = useState(null);
    const [branches, setBranches] = useState([]);

    // Sharing state
    const [showShareModal, setShowShareModal] = useState(false);
    const [shareReportId, setShareReportId] = useState(null);
    const [users, setUsers] = useState([]);
    const [shareForm, setShareForm] = useState({ shared_with: '', permission: 'view', message: '' });
    const [shareList, setShareList] = useState([]);

    const defaultForm = {
        report_name: '',
        report_type: 'profit_loss',
        frequency: 'monthly',
        recipients: '',
        format: 'pdf',
        branch_id: '',
        report_config: {},
    };
    const [formData, setFormData] = useState(defaultForm);

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchReports();
            fetchBranches();
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch?.id]);

    const fetchReports = async () => {
        try {
            setLoading(true);
            const res = await scheduledReportsAPI.list({ branch_id: currentBranch?.id || undefined });
            setReports(res.data);
        } catch (err) {
            console.error(err);
            showToast(t('common.error_loading'), 'error');
        } finally {
            setLoading(false);
            setInitialLoad(false);
        }
    };

    const fetchBranches = async () => {
        try {
            const res = await branchesAPI.list();
            setBranches(res.data);
        } catch (err) {
            console.error(err);
        }
    };

    const openCreate = () => {
        setEditingId(null);
        setFormData(defaultForm);
        setShowModal(true);
    };

    const openEdit = (report) => {
        setEditingId(report.id);
        setFormData({
            report_name: report.report_name || '',
            report_type: report.report_type,
            frequency: report.frequency,
            recipients: report.recipients,
            format: report.format || 'pdf',
            branch_id: report.branch_id || '',
            report_config: report.report_config || {},
        });
        setShowModal(true);
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        try {
            const payload = { ...formData, branch_id: formData.branch_id || null };
            if (editingId) {
                await scheduledReportsAPI.update(editingId, payload);
                showToast(t('common.success_update'), 'success');
            } else {
                await scheduledReportsAPI.create(payload);
                showToast(t('common.success_create'), 'success');
            }
            setShowModal(false);
            fetchReports();
        } catch (err) {
            console.error(err);
            showToast(t('common.error_create'), 'error');
        }
    };

    const handleDelete = async (id) => {
        if (!window.confirm(t('common.confirm_delete'))) return;
        try {
            await scheduledReportsAPI.delete(id);
            showToast(t('common.success_delete'), 'success');
            fetchReports();
        } catch (err) {
            showToast(t('common.error_delete'), 'error');
        }
    };

    const handleToggle = async (id, currentStatus) => {
        try {
            await scheduledReportsAPI.toggle(id, !currentStatus);
            fetchReports();
        } catch (err) {
            showToast(t('common.error_update'), 'error');
        }
    };

    const handleRunNow = async (id) => {
        try {
            await scheduledReportsAPI.runNow(id);
            showToast(t('reports.scheduled.run_started', 'Report execution started'), 'success');
            setTimeout(fetchReports, 3000);
        } catch (err) {
            showToast(t('common.error'), 'error');
        }
    };

    // ─── Sharing ─────────────────────────────────────────
    const openShareModal = async (reportId) => {
        setShareReportId(reportId);
        setShareForm({ shared_with: '', permission: 'view', message: '' });
        setShowShareModal(true);
        try {
            const [usersRes, sharesRes] = await Promise.all([
                reportSharingAPI.listUsers(),
                reportSharingAPI.getReportShares('scheduled', reportId),
            ]);
            setUsers(usersRes.data);
            setShareList(sharesRes.data);
        } catch (err) {
            console.error(err);
        }
    };

    const handleShare = async () => {
        if (!shareForm.shared_with) return;
        try {
            await reportSharingAPI.share({
                report_type: 'scheduled',
                report_id: shareReportId,
                shared_with: Number(shareForm.shared_with),
                permission: shareForm.permission,
                message: shareForm.message,
            });
            showToast(t('reports.sharing.shared_success', 'Report shared'), 'success');
            const res = await reportSharingAPI.getReportShares('scheduled', shareReportId);
            setShareList(res.data);
            setShareForm({ shared_with: '', permission: 'view', message: '' });
        } catch (err) {
            showToast(t('common.error'), 'error');
        }
    };

    const handleUnshare = async (shareId) => {
        try {
            await reportSharingAPI.unshare(shareId);
            const res = await reportSharingAPI.getReportShares('scheduled', shareReportId);
            setShareList(res.data);
        } catch (err) {
            showToast(t('common.error'), 'error');
        }
    };

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">⏰ {t('reports.scheduled.title', 'Scheduled Reports')}</h1>
                    <p className="workspace-subtitle">{t('reports.scheduled.subtitle', 'Manage automated report generation and emailing')}</p>
                </div>
                <div className="header-actions">
                    <button className="btn btn-primary" onClick={openCreate}>
                        + {t('reports.scheduled.new', 'New Schedule')}
                    </button>
                </div>
            </div>

            {/* Summary */}
            <div className="metrics-grid" style={{ marginBottom: 20 }}>
                <div className="metric-card">
                    <div className="metric-label">{t('reports.scheduled.total', 'Total')}</div>
                    <div className="metric-value text-primary">{reports.length}</div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('reports.scheduled.active_count', 'Active')}</div>
                    <div className="metric-value text-success">{reports.filter(r => r.is_active).length}</div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('reports.scheduled.last_failed', 'Failed')}</div>
                    <div className="metric-value text-danger">{reports.filter(r => r.last_status === 'failed').length}</div>
                </div>
            </div>

            <div className="table-container">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('reports.scheduled.report_name', 'Report Name')}</th>
                            <th>{t('reports.scheduled.report_type', 'Report Type')}</th>
                            <th>{t('reports.scheduled.frequency', 'Frequency')}</th>
                            <th>{t('reports.scheduled.recipients', 'Recipients')}</th>
                            <th>{t('reports.scheduled.branch', 'Branch')}</th>
                            <th>{t('reports.scheduled.next_run', 'Next Run')}</th>
                            <th>{t('reports.scheduled.last_status_col', 'Last Status')}</th>
                            <th>{t('reports.scheduled.status', 'Active')}</th>
                            <th>{t('common.actions', 'Actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
                        {initialLoad && loading ? (
                            <tr><td colSpan="9" className="text-center">{t('common.loading')}</td></tr>
                        ) : reports.length === 0 ? (
                            <tr><td colSpan="9" className="text-center">{t('common.no_data')}</td></tr>
                        ) : (
                            reports.map(report => (
                                <tr key={report.id}>
                                    <td style={{ fontWeight: 600 }}>{report.report_name || report.report_type}</td>
                                    <td>
                                        {getReportTypeLabel(report.report_type)}
                                        <span className="badge badge-secondary ms-2">{(report.format || 'pdf').toUpperCase()}</span>
                                    </td>
                                    <td>{t(`reports.frequency.${report.frequency}`, report.frequency)}</td>
                                    <td>
                                        <div className="text-truncate" style={{ maxWidth: 180 }} title={report.recipients}>
                                            {report.recipients}
                                        </div>
                                    </td>
                                    <td>{report.branch_name || t('common.all_branches', 'All Branches')}</td>
                                    <td>{report.next_run_at ? new Date(report.next_run_at).toLocaleString() : '-'}</td>
                                    <td>
                                        <span className={`badge ${STATUS_COLORS[report.last_status] || 'badge-secondary'}`}>
                                            {report.last_status || 'pending'}
                                        </span>
                                    </td>
                                    <td>
                                        <div className="form-check form-switch">
                                            <input
                                                className="form-check-input"
                                                type="checkbox"
                                                checked={report.is_active}
                                                onChange={() => handleToggle(report.id, report.is_active)}
                                            />
                                        </div>
                                    </td>
                                    <td>
                                        <div style={{ display: 'flex', gap: 4 }}>
                                            <button className="btn-icon" onClick={() => handleRunNow(report.id)} title={t('reports.scheduled.run_now', 'Run Now')}>
                                                ▶️
                                            </button>
                                            <button className="btn-icon" onClick={() => openEdit(report)} title={t('common.edit')}>
                                                ✏️
                                            </button>
                                            <button className="btn-icon" onClick={() => openShareModal(report.id)} title={t('reports.sharing.share', 'Share')}>
                                                🔗
                                            </button>
                                            <button className="btn-icon text-danger" onClick={() => handleDelete(report.id)} title={t('common.delete')}>
                                                🗑️
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>

            {/* Create/Edit Modal */}
            {showModal && (
                <div className="modal-overlay">
                    <div className="modal-content" style={{ maxWidth: 560 }}>
                        <div className="modal-header">
                            <h3>{editingId ? t('reports.scheduled.edit', 'Edit Schedule') : t('reports.scheduled.new', 'New Schedule')}</h3>
                            <button className="btn-close" onClick={() => setShowModal(false)}>×</button>
                        </div>
                        <form onSubmit={handleSubmit}>
                            <div className="modal-body">
                                <div className="form-group">
                                    <label>{t('reports.scheduled.report_name', 'Report Name')}</label>
                                    <input type="text" className="form-input"
                                        value={formData.report_name}
                                        onChange={e => setFormData({ ...formData, report_name: e.target.value })}
                                        placeholder={t('reports.scheduled.report_name_placeholder', 'e.g. Monthly P&L for Management')}
                                    />
                                </div>

                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                                    <div className="form-group">
                                        <label>{t('reports.scheduled.report_type', 'Report Type')}</label>
                                        <select className="form-input" value={formData.report_type}
                                            onChange={e => setFormData({ ...formData, report_type: e.target.value })}>
                                            {REPORT_TYPE_KEYS.map(key => (
                                                <option key={key} value={key}>{getReportTypeLabel(key)}</option>
                                            ))}
                                        </select>
                                    </div>

                                    <div className="form-group">
                                        <label>{t('reports.scheduled.frequency', 'Frequency')}</label>
                                        <select className="form-input" value={formData.frequency}
                                            onChange={e => setFormData({ ...formData, frequency: e.target.value })}>
                                            <option value="daily">{t('reports.frequency.daily', 'Daily')}</option>
                                            <option value="weekly">{t('reports.frequency.weekly', 'Weekly')}</option>
                                            <option value="monthly">{t('reports.frequency.monthly', 'Monthly')}</option>
                                        </select>
                                    </div>
                                </div>

                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                                    <div className="form-group">
                                        <label>{t('reports.scheduled.format', 'Format')}</label>
                                        <select className="form-input" value={formData.format}
                                            onChange={e => setFormData({ ...formData, format: e.target.value })}>
                                            <option value="pdf">PDF</option>
                                            <option value="excel">Excel</option>
                                        </select>
                                    </div>

                                    <div className="form-group">
                                        <label>{t('reports.scheduled.branch', 'Branch')}</label>
                                        <select className="form-input" value={formData.branch_id}
                                            onChange={e => setFormData({ ...formData, branch_id: e.target.value })}>
                                            <option value="">{t('common.all_branches', 'All Branches')}</option>
                                            {branches.map(b => (
                                                <option key={b.id} value={b.id}>{b.branch_name}</option>
                                            ))}
                                        </select>
                                    </div>
                                </div>

                                <div className="form-group">
                                    <label>{t('reports.scheduled.recipients', 'Recipients (comma separated emails)')}</label>
                                    <textarea className="form-input" rows="2" required
                                        value={formData.recipients}
                                        onChange={e => setFormData({ ...formData, recipients: e.target.value })}
                                        placeholder="email1@example.com, email2@example.com"
                                    />
                                </div>
                            </div>
                            <div className="modal-footer">
                                <button type="button" className="btn btn-secondary" onClick={() => setShowModal(false)}>
                                    {t('common.cancel')}
                                </button>
                                <button type="submit" className="btn btn-primary">
                                    {editingId ? t('common.update') : t('common.save')}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* Share Modal */}
            {showShareModal && (
                <div className="modal-overlay">
                    <div className="modal-content" style={{ maxWidth: 520 }}>
                        <div className="modal-header">
                            <h3>🔗 {t('reports.sharing.title', 'Share Report')}</h3>
                            <button className="btn-close" onClick={() => setShowShareModal(false)}>×</button>
                        </div>
                        <div className="modal-body">
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
                                <div className="form-group" style={{ margin: 0 }}>
                                    <label>{t('reports.sharing.share_with', 'Share With')}</label>
                                    <select className="form-input" value={shareForm.shared_with}
                                        onChange={e => setShareForm({ ...shareForm, shared_with: e.target.value })}>
                                        <option value="">{t('common.select', 'Select...')}</option>
                                        {users.map(u => (
                                            <option key={u.id} value={u.id}>{u.full_name} ({u.email})</option>
                                        ))}
                                    </select>
                                </div>
                                <div className="form-group" style={{ margin: 0 }}>
                                    <label>{t('reports.sharing.permission', 'Permission')}</label>
                                    <select className="form-input" value={shareForm.permission}
                                        onChange={e => setShareForm({ ...shareForm, permission: e.target.value })}>
                                        <option value="view">{t('reports.sharing.view', 'View Only')}</option>
                                        <option value="edit">{t('reports.sharing.edit', 'Can Edit')}</option>
                                    </select>
                                </div>
                            </div>
                            <div className="form-group" style={{ marginBottom: 12 }}>
                                <label>{t('reports.sharing.message', 'Message (optional)')}</label>
                                <input type="text" className="form-input" value={shareForm.message}
                                    onChange={e => setShareForm({ ...shareForm, message: e.target.value })}
                                    placeholder={t('reports.sharing.message_placeholder', 'Add a note...')}
                                />
                            </div>
                            <button className="btn btn-primary" onClick={handleShare} disabled={!shareForm.shared_with}
                                style={{ marginBottom: 16 }}>
                                {t('reports.sharing.share', 'Share')}
                            </button>

                            {/* Current shares */}
                            {shareList.length > 0 && (
                                <>
                                    <h4 style={{ fontSize: 14, marginBottom: 8, color: 'var(--text-secondary)' }}>
                                        {t('reports.sharing.shared_with_list', 'Shared With')}
                                    </h4>
                                    {shareList.map(s => (
                                        <div key={s.id} style={{
                                            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                                            padding: '8px 12px', background: 'var(--bg-secondary)', borderRadius: 8, marginBottom: 6,
                                            border: '1px solid var(--border-color)'
                                        }}>
                                            <div>
                                                <strong>{s.shared_with_name}</strong>
                                                <span className="badge badge-secondary ms-2">{s.permission}</span>
                                            </div>
                                            <button className="btn-icon text-danger" onClick={() => handleUnshare(s.id)}>×</button>
                                        </div>
                                    ))}
                                </>
                            )}
                        </div>
                        <div className="modal-footer">
                            <button className="btn btn-secondary" onClick={() => setShowShareModal(false)}>
                                {t('common.close', 'Close')}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default ScheduledReports;
