import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Plus, Check, X, RotateCcw, Eye, Settings, Clock, CheckCircle, XCircle, AlertCircle, Zap, ArrowUpCircle, BarChart3 } from 'lucide-react';
import api from '../../utils/api';
import { useToast } from '../../context/ToastContext';
import BackButton from '../../components/common/BackButton';
import { formatNumber } from '../../utils/format';
import { getCurrency, hasPermission } from '../../utils/auth';
import SimpleModal from '../../components/common/SimpleModal';
import { formatDate } from '../../utils/dateUtils';
import { PageLoading, Spinner } from '../../components/common/LoadingStates'

const makeIdempotencyKey = (prefix) => `${prefix}:${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`}`;

const ApprovalsPage = () => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const { showToast } = useToast();
    const currency = getCurrency();
    const [activeTab, setActiveTab] = useState('pending'); // pending, requests, workflows, advanced

    // Permissions
    const canAction = hasPermission('approvals.action');
    const canCreate = hasPermission('approvals.create');
    const canEdit = hasPermission('approvals.edit');
    const canDelete = hasPermission('approvals.delete');
    const canManage = hasPermission('approvals.manage') || hasPermission('settings.edit');

    // State
    const [pendingItems, setPendingItems] = useState([]);
    const [allRequests, setAllRequests] = useState([]);
    const [workflows, setWorkflows] = useState([]);
    const [loading, setLoading] = useState(false);

    // Advanced Workflow State
    const [selectedWorkflowId, setSelectedWorkflowId] = useState(null);
    const [slaForm, setSlaForm] = useState({ sla_hours: 24, auto_approve_below: 0, escalation_to: null, allow_parallel: false });
    const [savingSLA, setSavingSLA] = useState(false);
    const [workflowAnalytics, setWorkflowAnalytics] = useState(null);
    const [runningAction, setRunningAction] = useState(null);

    // Action Modal State
    const [selectedRequest, setSelectedRequest] = useState(null);
    const [actionType, setActionType] = useState(null); // approve, reject, return
    const [actionNotes, setActionNotes] = useState('');
    const [submittingAction, setSubmittingAction] = useState(false);

    useEffect(() => {
        fetchAllOnMount();
    }, []);

    const fetchAllOnMount = async () => {
        try {
            const [pRes, rRes, wRes] = await Promise.allSettled([
                api.get('/approvals/pending'),
                api.get('/approvals/requests'),
                api.get('/approvals/workflows')
            ]);
            if (pRes.status === 'fulfilled') setPendingItems(pRes.value.data.items || []);
            if (rRes.status === 'fulfilled') setAllRequests(rRes.value.data.items || []);
            if (wRes.status === 'fulfilled') setWorkflows(wRes.value.data || []);
        } catch { }
    };

    const fetchData = async () => {
        setLoading(true);
        try {
            if (activeTab === 'pending') {
                const response = await api.get('/approvals/pending');
                setPendingItems(response.data.items || []);
            } else if (activeTab === 'requests') {
                const response = await api.get('/approvals/requests');
                setAllRequests(response.data.items || []);
            } else if (activeTab === 'workflows') {
                const response = await api.get('/approvals/workflows');
                setWorkflows(response.data || []);
            } else if (activeTab === 'advanced') {
                const wfRes = await api.get('/approvals/workflows');
                setWorkflows(wfRes.data || []);
                try {
                    const analyticsRes = await api.get('/workflow/analytics');
                    setWorkflowAnalytics(analyticsRes.data);
                } catch { setWorkflowAnalytics(null); }
            }
        } catch (error) {
            console.error("Failed to fetch data", error);
            showToast(t('common.error_loading_data'), 'error');
        } finally {
            setLoading(false);
        }
    };

    const handleAction = async () => {
        if (!selectedRequest || !actionType) return;

        setSubmittingAction(true);
        try {
            await api.post(`/approvals/requests/${selectedRequest.id}/action`, {
                action: actionType,
                notes: actionNotes
            }, {
                headers: { 'Idempotency-Key': makeIdempotencyKey('approval-action') }
            });

            showToast(t('common.success_update'), 'success');
            setSelectedRequest(null);
            setActionType(null);
            setActionNotes('');
            fetchData(); // Refresh list
        } catch (error) {
            showToast(error.response?.data?.detail || t('common.error_occurred'), 'error');
        } finally {
            setSubmittingAction(false);
        }
    };

    const openActionModal = (request, type) => {
        setSelectedRequest(request);
        setActionType(type);
        setActionNotes('');
    };

    const openDetailsModal = (request) => {
        setSelectedRequest(request);
        setActionType(null);
        setActionNotes('');
    };

    const handleDeleteWorkflow = async (id) => {
        if (!window.confirm(t('common.confirm_delete'))) return;

        try {
            await api.delete(`/approvals/workflows/${id}`);
            showToast(t('common.success_delete'), 'success');
            fetchData();
        } catch (error) {
            showToast(error.response?.data?.detail || t('common.error_deleting'), 'error');
        }
    };

    const getStatusBadge = (status) => {
        switch (status) {
            case 'pending': return <span className="badge badge-warning gap-1"><Clock size={12} /> {t('approvals.status.pending')}</span>;
            case 'approved': return <span className="badge badge-success gap-1"><CheckCircle size={12} /> {t('approvals.status.approved')}</span>;
            case 'rejected': return <span className="badge badge-error gap-1"><XCircle size={12} /> {t('approvals.status.rejected')}</span>;
            case 'returned': return <span className="badge badge-info gap-1"><RotateCcw size={12} /> {t('approvals.status.returned')}</span>;
            default: return <span className="badge badge-ghost">{status}</span>;
        }
    };

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
                    <div>
                        <h1 className="workspace-title">✅ {t('approvals.title')}</h1>
                        <p className="workspace-subtitle">{t('approvals.pending_actions')}</p>
                    </div>
                    <div style={{ display: 'flex', gap: '8px' }}>
                        {canCreate && (
                            <button onClick={() => navigate('/approvals/new')} className="btn btn-primary">
                                <Plus size={18} />
                                {t('approvals.create_workflow')}
                            </button>
                        )}
                    </div>
                </div>
            </div>

            {/* Metrics */}
            <div className="metrics-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
                <div className="metric-card" style={{ cursor: 'pointer', borderColor: activeTab === 'pending' ? 'var(--primary)' : undefined }} onClick={() => setActiveTab('pending')}>
                    <div className="metric-label">⏳ {t('approvals.pending_actions')}</div>
                    <div className="metric-value text-warning">{loading && activeTab === 'pending' ? '...' : pendingItems.length}</div>
                    <div className="metric-change">{t('approvals.table.requires_action', 'يتطلب إجراء')}</div>
                </div>
                <div className="metric-card" style={{ cursor: 'pointer', borderColor: activeTab === 'requests' ? 'var(--primary)' : undefined }} onClick={() => setActiveTab('requests')}>
                    <div className="metric-label">📋 {t('approvals.all_requests')}</div>
                    <div className="metric-value text-primary">{loading && activeTab === 'requests' ? '...' : allRequests.length}</div>
                    <div className="metric-change">{t('approvals.table.total_requests', 'جميع الطلبات')}</div>
                </div>
                <div className="metric-card" style={{ cursor: 'pointer', borderColor: activeTab === 'workflows' ? 'var(--primary)' : undefined }} onClick={() => setActiveTab('workflows')}>
                    <div className="metric-label">⚙️ {t('approvals.workflows')}</div>
                    <div className="metric-value">{loading && activeTab === 'workflows' ? '...' : workflows.length}</div>
                    <div className="metric-change">{t('approvals.table.configured', 'تدفقات معرّفة')}</div>
                </div>
            </div>

            {/* Tabs */}
            <div className="tabs mt-4">
                <button className={`tab ${activeTab === 'pending' ? 'active' : ''}`} onClick={() => setActiveTab('pending')}>
                    {t('approvals.pending_actions')}
                    {pendingItems.length > 0 && (
                        <span style={{ background: 'var(--error)', color: '#fff', borderRadius: '12px', padding: '1px 7px', fontSize: '11px', fontWeight: '700', marginInlineStart: '6px' }}>
                            {pendingItems.length}
                        </span>
                    )}
                </button>
                <button className={`tab ${activeTab === 'requests' ? 'active' : ''}`} onClick={() => setActiveTab('requests')}>
                    {t('approvals.all_requests')}
                </button>
                <button className={`tab ${activeTab === 'workflows' ? 'active' : ''}`} onClick={() => setActiveTab('workflows')}>
                    {t('approvals.workflows')}
                </button>
                {canManage && (
                    <button className={`tab ${activeTab === 'advanced' ? 'active' : ''}`} onClick={() => setActiveTab('advanced')}>
                        ⚡ {t('approvals.advanced_settings', 'إعدادات متقدمة')}
                    </button>
                )}
            </div>

            {/* Content Container */}
            <div className="card mt-4">
            <div className="data-table-container">
                {loading ? (
                    <div className="flex justify-center items-center py-20">
                        <PageLoading />
                    </div>
                ) : (
                    <>
                        {/* Tab 1: Pending Actions */}
                        {activeTab === 'pending' && (
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th style={{ width: '80px' }}>{t('approvals.table.id')}</th>
                                        <th>{t('approvals.table.document')}</th>
                                        <th>{t('approvals.table.requested_by')}</th>
                                        <th>{t('approvals.table.date')}</th>
                                        <th>{t('approvals.table.current_step')}</th>
                                        {canAction && <th style={{ width: '150px' }}>{t('approvals.table.actions')}</th>}
                                    </tr>
                                </thead>
                                <tbody>
                                    {pendingItems.length === 0 ? (
                                        <tr><td colSpan={canAction ? 6 : 5} className="text-center py-12 opacity-50">{t('approvals.table.no_pending')}</td></tr>
                                    ) : (
                                        pendingItems.map((item) => (
                                            <tr key={item.id}>
                                                <td className="font-mono text-sm text-primary font-medium">#{item.id}</td>
                                                <td>
                                                    <div className="font-bold">{t(`approvals.document_types.${item.document_type}`) || item.document_type}</div>
                                                    <div className="text-xs opacity-70">{t('approvals.table.ref')}: {item.document_id} • <strong>{formatNumber(item.amount)} {currency}</strong></div>
                                                    {item.description && <div className="text-xs italic mt-1 text-base-content/60 max-w-xs truncate">{item.description}</div>}
                                                </td>
                                                <td>{item.requested_by_name || '—'}</td>
                                                <td>{formatDate(item.created_at)}</td>
                                                <td>
                                                    {item.steps && item.steps.length > 0 ? (
                                                        <div className="d-flex align-items-center" style={{ display: 'flex', alignItems: 'center', gap: '4px', flexWrap: 'wrap' }}>
                                                            {item.steps.map((step, idx) => (
                                                                <div key={idx} style={{ display: 'flex', alignItems: 'center' }}>
                                                                    <span className={`badge badge-sm ${
                                                                        step.status === 'approved' ? 'badge-success' :
                                                                        step.status === 'rejected' ? 'badge-error' :
                                                                        idx === (item.current_step || 1) - 1 ? 'badge-primary' :
                                                                        'badge-ghost'
                                                                    }`} style={{ borderRadius: '12px', fontSize: '10px', padding: '2px 8px' }}>
                                                                        {step.approver_name || step.label || `${idx + 1}`}
                                                                    </span>
                                                                    {idx < item.steps.length - 1 && (
                                                                        <span style={{ margin: '0 2px', opacity: 0.4, fontSize: '10px' }}>›</span>
                                                                    )}
                                                                </div>
                                                            ))}
                                                        </div>
                                                    ) : (
                                                        <div className="badge badge-outline badge-sm">{t('approvals.table.step')} {item.current_step} / {item.total_steps}</div>
                                                    )}
                                                </td>
                                                {canAction && (
                                                    <td>
                                                        <div className="flex gap-1">
                                                            <button
                                                                onClick={() => openActionModal(item, 'approve')}
                                                                className="btn btn-xs btn-success text-white"
                                                                title={t('common.approve')}
                                                            >
                                                                <Check size={14} />
                                                            </button>
                                                            <button
                                                                onClick={() => openActionModal(item, 'return')}
                                                                className="btn btn-xs btn-warning text-white"
                                                                title={t('approvals.actions.return')}
                                                            >
                                                                <RotateCcw size={14} />
                                                            </button>
                                                            <button
                                                                onClick={() => openActionModal(item, 'reject')}
                                                                className="btn btn-xs btn-error text-white"
                                                                title={t('common.reject')}
                                                            >
                                                                <X size={14} />
                                                            </button>
                                                        </div>
                                                    </td>
                                                )}
                                            </tr>
                                        ))
                                    )}
                                </tbody>
                            </table>
                        )}

                        {/* Tab 2: All Requests */}
                        {activeTab === 'requests' && (
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th style={{ width: '80px' }}>{t('approvals.table.id')}</th>
                                        <th>{t('approvals.table.workflow')}</th>
                                        <th>{t('approvals.table.document')}</th>
                                        <th>{t('approvals.table.requested_by')}</th>
                                        <th>{t('approvals.table.date')}</th>
                                        <th>{t('approvals.table.status')}</th>
                                        <th style={{ width: '50px' }}></th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {allRequests.length === 0 ? (
                                        <tr><td colSpan="7" className="text-center py-12 opacity-50">{t('approvals.table.no_requests')}</td></tr>
                                    ) : (
                                        allRequests.map((item) => (
                                            <tr key={item.id}>
                                                <td className="font-mono text-sm text-primary font-medium">#{item.id}</td>
                                                <td><span className="font-medium">{item.workflow_name}</span></td>
                                                <td>
                                                    <div className="font-bold">{t(`approvals.document_types.${item.document_type}`) || item.document_type}</div>
                                                    <div className="text-xs opacity-70">{t('approvals.table.ref')}: {item.document_id} • <strong>{formatNumber(item.amount)} {currency}</strong></div>
                                                </td>
                                                <td>{item.requested_by_name || '—'}</td>
                                                <td>{formatDate(item.created_at)}</td>
                                                <td>{getStatusBadge(item.status)}</td>
                                                <td>
                                                    <button className="btn btn-ghost btn-xs text-primary" title={t('common.view_details')}
                                                        onClick={() => openDetailsModal(item)}>
                                                        <Eye size={16} />
                                                    </button>
                                                </td>
                                            </tr>
                                        ))
                                    )}
                                </tbody>
                            </table>
                        )}

                        {/* Tab 3: Workflows */}
                        {activeTab === 'workflows' && (
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>{t('approvals.table.name')}</th>
                                        <th>{t('approvals.table.document_type')}</th>
                                        <th>{t('approvals.table.steps')}</th>
                                        <th>{t('approvals.table.active')}</th>
                                        <th style={{ width: '100px' }}>{t('approvals.table.actions')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {workflows.length === 0 ? (
                                        <tr><td colSpan="5" className="text-center py-12 opacity-50">{t('approvals.table.no_workflows')}</td></tr>
                                    ) : (
                                        workflows.map((wf) => (
                                            <tr key={wf.id}>
                                                <td className="font-bold">{wf.name}</td>
                                                <td>{t(`approvals.document_types.${wf.document_type}`) || wf.document_type}</td>
                                                <td>
                                                    {(() => {
                                                        try {
                                                            const steps = typeof wf.steps === 'string' ? JSON.parse(wf.steps) : wf.steps;
                                                            return <span className="badge badge-secondary badge-outline badge-sm">{steps?.length || 0} {t('approvals.table.steps')}</span>;
                                                        } catch (e) {
                                                            return <span className="badge badge-ghost badge-sm">{t('approvals.table.invalid_data')}</span>;
                                                        }
                                                    })()}
                                                </td>
                                                <td>
                                                    {wf.is_active ?
                                                        <span className="badge badge-success badge-sm">{t('common.active')}</span> :
                                                        <span className="badge badge-ghost badge-sm">{t('common.inactive')}</span>
                                                    }
                                                </td>
                                                <td>
                                                    <div className="flex gap-1">
                                                        {canEdit && (
                                                            <button
                                                                onClick={() => navigate(`/approvals/${wf.id}/edit`)}
                                                                className="btn btn-ghost btn-xs text-primary"
                                                                title={t('common.edit')}
                                                            >
                                                                <Settings size={16} />
                                                            </button>
                                                        )}
                                                        {canDelete && (
                                                            <button
                                                                onClick={() => handleDeleteWorkflow(wf.id)}
                                                                className="btn btn-ghost btn-xs text-error"
                                                                title={t('common.delete')}
                                                            >
                                                                <X size={16} />
                                                            </button>
                                                        )}
                                                    </div>
                                                </td>
                                            </tr>
                                        ))
                                    )}
                                </tbody>
                            </table>
                        )}

                        {/* Tab 4: Advanced SLA & Auto-Approve */}
                        {activeTab === 'advanced' && (
                            <div className="p-4 space-y-6">
                                {/* Quick Actions */}
                                <div className="flex flex-wrap gap-3">
                                    <button
                                        className="btn btn-success btn-sm"
                                        disabled={runningAction === 'auto-approve'}
                                        onClick={async () => {
                                            setRunningAction('auto-approve');
                                            try {
                                                const res = await api.post('/workflow/auto-approve', null, {
                                                    headers: { 'Idempotency-Key': makeIdempotencyKey('workflow-auto-approve') }
                                                });
                                                showToast(`${res.data.message || t('common.success')}`, 'success');
                                                fetchData();
                                            } catch (e) { showToast(t('common.error'), 'error'); }
                                            finally { setRunningAction(null); }
                                        }}
                                    >
                                        {runningAction === 'auto-approve' ? <Spinner size="sm"/> : <Zap size={14} />}
                                        {t('approvals.run_auto_approve', 'تشغيل الموافقة التلقائية')}
                                    </button>
                                    <button
                                        className="btn btn-warning btn-sm"
                                        disabled={runningAction === 'escalation'}
                                        onClick={async () => {
                                            setRunningAction('escalation');
                                            try {
                                                const res = await api.post('/workflow/check-escalation');
                                                showToast(`${res.data.message || t('common.success')}`, 'success');
                                                fetchData();
                                            } catch (e) { showToast(t('common.error'), 'error'); }
                                            finally { setRunningAction(null); }
                                        }}
                                    >
                                        {runningAction === 'escalation' ? <Spinner size="sm"/> : <ArrowUpCircle size={14} />}
                                        {t('approvals.run_escalation', 'تشغيل التصعيد')}
                                    </button>
                                </div>

                                {/* Analytics Summary */}
                                {workflowAnalytics && (
                                    <div className="bg-base-200/50 p-4 rounded-xl border">
                                        <h4 className="font-bold mb-3 flex items-center gap-2"><BarChart3 size={16} /> {t('approvals.analytics_title', 'إحصاءات الاعتمادات')}</h4>
                                        <div className="metrics-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))' }}>
                                            <div className="metric-card">
                                                <div className="metric-label">{t('approvals.total_requests_stat', 'إجمالي الطلبات')}</div>
                                                <div className="metric-value">{workflowAnalytics.total_requests || 0}</div>
                                            </div>
                                            <div className="metric-card">
                                                <div className="metric-label">{t('approvals.approval_rate', 'معدل الموافقة')}</div>
                                                <div className="metric-value text-success">{workflowAnalytics.approval_rate || 0}%</div>
                                            </div>
                                            <div className="metric-card">
                                                <div className="metric-label">{t('approvals.avg_hours', 'متوسط وقت الاعتماد')}</div>
                                                <div className="metric-value">{workflowAnalytics.avg_approval_hours ? `${Math.round(workflowAnalytics.avg_approval_hours)}h` : '-'}</div>
                                            </div>
                                        </div>
                                    </div>
                                )}

                                {/* SLA Settings per Workflow */}
                                <div>
                                    <h4 className="font-bold mb-3">{t('approvals.sla_settings', 'إعدادات SLA والموافقة التلقائية')}</h4>
                                    <table className="data-table">
                                        <thead>
                                            <tr>
                                                <th>{t('approvals.table.name')}</th>
                                                <th>{t('approvals.table.document_type')}</th>
                                                <th>{t('approvals.sla_hours_label', 'SLA (ساعة)')}</th>
                                                <th>{t('approvals.auto_approve_below_label', 'موافقة تلقائية تحت')}</th>
                                                <th style={{ width: '100px' }}>{t('approvals.table.actions')}</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {workflows.length === 0 ? (
                                                <tr><td colSpan="5" className="text-center py-8 opacity-50">{t('approvals.table.no_workflows')}</td></tr>
                                            ) : (
                                                workflows.map(wf => (
                                                    <tr key={wf.id}>
                                                        <td className="font-bold">{wf.name}</td>
                                                        <td>{t(`approvals.document_types.${wf.document_type}`) || wf.document_type}</td>
                                                        <td>{wf.sla_hours ?? '-'}</td>
                                                        <td>{wf.auto_approve_below ? `${formatNumber(wf.auto_approve_below)} ${currency}` : '-'}</td>
                                                        <td>
                                                            <button
                                                                className="btn btn-ghost btn-xs text-primary"
                                                                onClick={async () => {
                                                                    setSelectedWorkflowId(wf.id);
                                                                    try {
                                                                        const res = await api.get(`/workflow/advanced/${wf.id}`);
                                                                        setSlaForm({
                                                                            sla_hours: res.data.sla_hours ?? 24,
                                                                            auto_approve_below: res.data.auto_approve_below ?? 0,
                                                                            escalation_to: res.data.escalation_to ?? null,
                                                                            allow_parallel: res.data.allow_parallel ?? false
                                                                        });
                                                                    } catch {
                                                                        setSlaForm({ sla_hours: wf.sla_hours ?? 24, auto_approve_below: wf.auto_approve_below ?? 0, escalation_to: null, allow_parallel: false });
                                                                    }
                                                                }}
                                                            >
                                                                <Settings size={16} /> {t('common.edit')}
                                                            </button>
                                                        </td>
                                                    </tr>
                                                ))
                                            )}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        )}
                    </>
                )}
            </div>
            </div>

            {/* SLA Settings Modal */}
            <SimpleModal
                isOpen={selectedWorkflowId !== null}
                onClose={() => setSelectedWorkflowId(null)}
                title={t('approvals.sla_settings', 'إعدادات SLA والموافقة التلقائية')}
            >
                <div className="p-4 space-y-4">
                    <div className="form-input">
                        <label className="label"><span className="label-text font-medium">{t('approvals.sla_hours_label', 'SLA (ساعة)')}</span></label>
                        <input type="number" className="input input-bordered w-full" min="0" value={slaForm.sla_hours}
                            onChange={e => setSlaForm(prev => ({ ...prev, sla_hours: parseInt(e.target.value) || 0 }))}
                        />
                        <p className="text-xs opacity-60 mt-1">{t('approvals.sla_hours_hint', 'عدد الساعات قبل التصعيد التلقائي. 0 = بلا حد')}</p>
                    </div>
                    <div className="form-input">
                        <label className="label"><span className="label-text font-medium">{t('approvals.auto_approve_below_label', 'موافقة تلقائية تحت')}</span></label>
                        <input type="number" className="input input-bordered w-full" min="0" step="100" value={slaForm.auto_approve_below}
                            onChange={e => setSlaForm(prev => ({ ...prev, auto_approve_below: e.target.value }))}
                        />
                        <p className="text-xs opacity-60 mt-1">{t('approvals.auto_approve_hint', 'المبالغ أقل من هذا الحد تُوافَق تلقائياً عند تشغيل الموافقة التلقائية. 0 = معطّل')}</p>
                    </div>
                    <div className="form-input">
                        <label className="label"><span className="label-text font-medium">{t('approvals.escalation_to_label', 'تصعيد إلى (ID المستخدم)')}</span></label>
                        <input type="number" className="input input-bordered w-full" min="0" value={slaForm.escalation_to || ''}
                            onChange={e => setSlaForm(prev => ({ ...prev, escalation_to: parseInt(e.target.value) || null }))}
                        />
                        <p className="text-xs opacity-60 mt-1">{t('approvals.escalation_hint', 'المستخدم الذي يتلقى الطلب عند تجاوز SLA')}</p>
                    </div>
                    <div className="form-control">
                        <label className="label cursor-pointer justify-start gap-3">
                            <input type="checkbox" className="checkbox checkbox-primary checkbox-sm" checked={slaForm.allow_parallel}
                                onChange={e => setSlaForm(prev => ({ ...prev, allow_parallel: e.target.checked }))}
                            />
                            <span className="label-text">{t('approvals.allow_parallel_label', 'السماح بالموافقة المتوازية')}</span>
                        </label>
                    </div>
                    <div className="flex justify-end gap-3 pt-4 border-t">
                        <button className="btn btn-ghost" onClick={() => setSelectedWorkflowId(null)}>{t('common.cancel')}</button>
                        <button className="btn btn-primary min-w-[120px]" disabled={savingSLA}
                            onClick={async () => {
                                setSavingSLA(true);
                                try {
                                    await api.put(`/workflow/advanced/${selectedWorkflowId}/sla`, slaForm);
                                    showToast(t('common.saved'), 'success');
                                    setSelectedWorkflowId(null);
                                    fetchData();
                                } catch (e) {
                                    showToast(e.response?.data?.detail || t('common.error'), 'error');
                                } finally { setSavingSLA(false); }
                            }}
                        >
                            {savingSLA ? <Spinner size="sm"/> : t('common.save')}
                        </button>
                    </div>
                </div>
            </SimpleModal>
            <SimpleModal
                isOpen={!!selectedRequest}
                onClose={() => setSelectedRequest(null)}
                title={
                    actionType === 'approve' ? t('common.approve') :
                        actionType === 'reject' ? t('common.reject') :
                            actionType === 'return' ? t('approvals.actions.return') : t('common.view_details')
                }
            >
                <div className="p-4 space-y-4">
                    {actionType && (
                        <div className="alert alert-info bg-primary/5 border-primary/20 text-sm">
                            <AlertCircle size={18} className="text-primary" />
                            <div>
                                {t('approvals.approvals.confirm_action_on_this_request')}
                            </div>
                        </div>
                    )}

                    {selectedRequest && (
                        <div className="bg-base-200/50 p-4 rounded-xl border border-base-200">
                            <div className="flex justify-between items-start mb-2">
                                <div className="font-bold text-lg">{t(`approvals.document_types.${selectedRequest.document_type}`) || selectedRequest.document_type}</div>
                                <div className="font-mono text-primary">#{selectedRequest.document_id}</div>
                            </div>
                            <div className="grid grid-cols-2 gap-4 text-sm">
                                <div>
                                    <span className="opacity-60 block">{t('common.amount')}</span>
                                    <span className="font-bold">{formatNumber(selectedRequest.amount)} {currency}</span>
                                </div>
                                <div>
                                    <span className="opacity-60 block">{t('approvals.table.requested_by')}</span>
                                    <span>{selectedRequest.requested_by_name}</span>
                                </div>
                                {selectedRequest.description && (
                                    <div className="col-span-2 mt-2">
                                        <span className="opacity-60 block">{t('common.description')}</span>
                                        <div className="italic text-base-content/70">{selectedRequest.description}</div>
                                    </div>
                                )}
                            </div>
                        </div>
                    )}

                    {actionType && (
                        <div className="form-input">
                            <label className="label">
                                <span className="label-text font-medium">{t('common.notes')}</span>
                            </label>
                            <textarea
                                className="textarea textarea-bordered h-24 focus:border-primary"
                                placeholder={t('approvals.add_notes_placeholder')}
                                value={actionNotes}
                                onChange={(e) => setActionNotes(e.target.value)}
                            />
                        </div>
                    )}

                    <div className="flex justify-end gap-3 pt-4 border-t border-base-200">
                        <button
                            className="btn btn-ghost"
                            onClick={() => setSelectedRequest(null)}
                            disabled={submittingAction}
                        >
                            {t('common.cancel')}
                        </button>
                        {actionType && (
                            <button
                                className={`btn ${actionType === 'approve' ? 'btn-success' :
                                    actionType === 'reject' ? 'btn-error' : 'btn-warning'
                                    } text-white min-w-[120px]`}
                                onClick={handleAction}
                                disabled={submittingAction}
                            >
                                {submittingAction ?
                                    <Spinner size="sm"/> :
                                    (actionType === 'approve' ? t('common.approve') :
                                        actionType === 'reject' ? t('common.reject') :
                                            t('approvals.actions.return'))
                                }
                            </button>
                        )}
                    </div>
                </div>
            </SimpleModal>
        </div>
    );
};

export default ApprovalsPage;
