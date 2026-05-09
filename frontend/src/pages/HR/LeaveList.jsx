import { useState, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
    Plus, Check, X, Clock,
    CheckCircle, XCircle
} from 'lucide-react';
import { hrAPI } from '../../utils/api';
import { toastEmitter } from '../../utils/toastEmitter';
import { hasPermission } from '../../utils/auth';
import { useBranch } from '../../context/BranchContext';
import SimpleModal from '../../components/common/SimpleModal';
import { formatShortDate } from '../../utils/dateUtils';
import DataTable from '../../components/common/DataTable';
import SearchFilter from '../../components/common/SearchFilter';
import BackButton from '../../components/common/BackButton';

const LeaveList = () => {
    const { t } = useTranslation();
    const [leaves, setLeaves] = useState([]);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [actionLoading, setActionLoading] = useState(false);
    const [search, setSearch] = useState('');
    const [filterValues, setFilterValues] = useState({});
    const { currentBranch } = useBranch();

    // Permissions
    const canManageLeaves = hasPermission('hr.leaves.manage');

    // Form State
    const [formData, setFormData] = useState({
        leave_type: 'annual',
        start_date: '',
        end_date: '',
        reason: ''
    });

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchData();
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch]);

    const fetchData = async () => {
        setLoading(true);
        try {
            const params = {};
            if (currentBranch?.id) {
                params.branch_id = currentBranch.id;
            }
            const response = await hrAPI.listLeaveRequests(params);
            setLeaves(Array.isArray(response.data) ? response.data : []);
        } catch (error) {
            toastEmitter.emit(t('common.error'), 'error');
        } finally {
            setLoading(false);
            setInitialLoad(false);
        }
    };

    const handleCreate = async () => {
        setActionLoading(true);
        try {
            await hrAPI.createLeaveRequest(formData);
            toastEmitter.emit(t('common.success'), 'success');
            setIsModalOpen(false);
            setFormData({ leave_type: 'annual', start_date: '', end_date: '', reason: '' });
            fetchData();
        } catch (error) {
            toastEmitter.emit(error.message || t('common.error_occurred'), 'error');
        } finally {
            setActionLoading(false);
        }
    };

    const handleStatusUpdate = async (id, status) => {
        if (!window.confirm(t('common.confirm_action'))) return;

        try {
            await hrAPI.updateLeaveStatus(id, status);
            toastEmitter.emit(t('common.success'), 'success');
            fetchData();
        } catch (error) {
            toastEmitter.emit(t('common.error_occurred'), 'error');
        }
    };

    const getStatusBadge = (status) => {
        const styles = {
            pending: 'badge-warning',
            approved: 'badge-success',
            rejected: 'badge-danger'
        };
        const icons = {
            pending: Clock,
            approved: CheckCircle,
            rejected: XCircle
        };
        const Icon = icons[status] || Clock;
        const label = t(`status.${status}`) || status;

        return (
            <span className={`badge ${styles[status] || 'badge-secondary'}`}>
                <span className="d-flex align-items-center gap-1">
                    <Icon size={12} />
                    {label}
                </span>
            </span>
        );
    };

    const getLeaveTypeLabel = (type) => {
        const types = {
            annual: t('hr.leaves.type_annual'),
            sick: t('hr.leaves.type_sick'),
            unpaid: t('hr.leaves.type_unpaid'),
            emergency: t('hr.leaves.type_emergency')
        };
        return types[type] || type;
    };

    // Calculate Stats
    const totalRequests = leaves.length;
    const pendingRequests = leaves.filter(l => l.status === 'pending').length;
    const approvedRequests = leaves.filter(l => l.status === 'approved').length;

    const filteredData = useMemo(() => {
        let result = leaves;
        if (search) {
            const q = search.toLowerCase();
            result = result.filter(leave =>
                leave.employee_name?.toLowerCase().includes(q) ||
                leave.reason?.toLowerCase().includes(q)
            );
        }
        if (filterValues.status) {
            result = result.filter(leave => leave.status === filterValues.status);
        }
        if (filterValues.leave_type) {
            result = result.filter(leave => leave.leave_type === filterValues.leave_type);
        }
        return result;
    }, [leaves, search, filterValues]);

    const columns = [
        {
            key: 'employee_name',
            label: t('hr.leaves.employee'),
            width: '25%',
            render: (val, row) => (
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <div className="avatar-xs" style={{ background: '#eff6ff', color: 'var(--primary)', fontWeight: 'bold' }}>
                        {val?.charAt(0).toUpperCase() || 'U'}
                    </div>
                    <span style={{ fontWeight: '600', color: 'var(--text-primary)' }}>{val || t('common.me')}</span>
                </div>
            ),
        },
        {
            key: 'leave_type',
            label: t('hr.leaves.type'),
            width: '15%',
            render: (val) => <span style={{ color: 'var(--text-primary)' }}>{getLeaveTypeLabel(val)}</span>,
        },
        {
            key: 'start_date',
            label: t('hr.leaves.period'),
            width: '20%',
            render: (val, row) => (
                <div style={{ display: 'flex', flexDirection: 'column' }}>
                    <span style={{ fontWeight: '500', color: 'var(--text-primary)' }}>{formatShortDate(val)}</span>
                    <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>{t('common.to')} {formatShortDate(row.end_date)}</span>
                </div>
            ),
        },
        {
            key: '_duration',
            label: t('hr.leaves.duration'),
            width: '10%',
            headerStyle: { textAlign: 'center' },
            style: { textAlign: 'center' },
            render: (_val, row) => {
                const start = new Date(row.start_date);
                const end = new Date(row.end_date);
                const duration = Math.ceil((end - start) / (1000 * 60 * 60 * 24)) + 1;
                return <span className="badge" style={{ background: '#f1f5f9', color: 'var(--text-secondary)' }}>{duration} {t('common.days')}</span>;
            },
        },
        {
            key: 'reason',
            label: t('hr.leaves.reason'),
            width: '20%',
            style: { maxWidth: '150px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--text-secondary)' },
            render: (val) => val || '-',
        },
        {
            key: 'status',
            label: t('common.status_title'),
            render: (val) => getStatusBadge(val),
        },
        {
            key: 'created_at',
            label: t('common.created_at'),
            width: '10%',
            render: (val) => <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>{formatShortDate(val)}</span>,
        },
        ...(canManageLeaves ? [{
            key: '_actions',
            label: t('common.actions'),
            headerStyle: { textAlign: 'end' },
            style: { textAlign: 'end' },
            render: (_val, row) => (
                row.status === 'pending' ? (
                    <div className="btn-group">
                        <button
                            onClick={(e) => { e.stopPropagation(); handleStatusUpdate(row.id, 'approved'); }}
                            className="table-action-btn text-success"
                            title={t('common.approve')}
                        >
                            <Check size={16} />
                        </button>
                        <button
                            onClick={(e) => { e.stopPropagation(); handleStatusUpdate(row.id, 'rejected'); }}
                            className="table-action-btn text-danger"
                            title={t('common.reject')}
                        >
                            <X size={16} />
                        </button>
                    </div>
                ) : null
            ),
        }] : []),
    ];

    const statusFilterOptions = [
        { value: 'pending', label: t('status.pending') },
        { value: 'approved', label: t('status.approved') },
        { value: 'rejected', label: t('status.rejected') },
    ];

    const typeFilterOptions = [
        { value: 'annual', label: t('hr.leaves.type_annual') },
        { value: 'sick', label: t('hr.leaves.type_sick') },
        { value: 'emergency', label: t('hr.leaves.type_emergency') },
        { value: 'unpaid', label: t('hr.leaves.type_unpaid') },
    ];

    return (
        <div className="workspace fade-in">
            {/* Header */}
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
                    <div>
                        <h1 className="workspace-title">{t('hr.leaves.title')}</h1>
                        <p className="workspace-subtitle">{t('hr.leaves.subtitle')}</p>
                    </div>
                    <button
                        onClick={() => setIsModalOpen(true)}
                        className="btn btn-primary"
                    >
                        <Plus size={18} className="me-2" />
                        {t('hr.leaves.request')}
                    </button>
                </div>
            </div>

            {/* Metrics Section */}
            <div className="metrics-grid mb-4">
                <div className="metric-card">
                    <div className="metric-label">{t('common.count', 'Total Requests')}</div>
                    <div className="metric-value text-primary">
                        {hasPermission('hr.reports') ? totalRequests : '***'}
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('status.pending', 'Pending')}</div>
                    <div className="metric-value text-warning">
                        {hasPermission('hr.reports') ? pendingRequests : '***'}
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('status.approved', 'Approved')}</div>
                    <div className="metric-value text-success">
                        {hasPermission('hr.reports') ? approvedRequests : '***'}
                    </div>
                </div>
            </div>

            <SearchFilter
                value={search}
                onChange={setSearch}
                placeholder={t('common.search')}
                filters={[
                    { key: 'status', label: t('common.status_title'), options: statusFilterOptions },
                    { key: 'leave_type', label: t('hr.leaves.type'), options: typeFilterOptions },
                ]}
                filterValues={filterValues}
                onFilterChange={(key, value) => setFilterValues(prev => ({ ...prev, [key]: value }))}
            />

            <DataTable
                columns={columns}
                data={filteredData}
                loading={initialLoad && !leaves.length}
                emptyTitle={t('common.no_data')}
                emptyAction={{ label: t('hr.leaves.request'), onClick: () => setIsModalOpen(true) }}
            />

            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}

            {/* Create Modal */}
            <SimpleModal
                isOpen={isModalOpen}
                onClose={() => setIsModalOpen(false)}
                title={t('hr.leaves.request')}
                footer={
                    <>
                        <button className="btn btn-secondary" onClick={() => setIsModalOpen(false)}>
                            {t('common.cancel')}
                        </button>
                        <button className="btn btn-primary" onClick={handleCreate} disabled={actionLoading}>
                            {actionLoading ? t('common.saving') : t('common.submit')}
                        </button>
                    </>
                }
            >
                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                    <div className="form-group">
                        <label className="form-label">{t('hr.leaves.type')}</label>
                        <select
                            className="form-input"
                            value={formData.leave_type}
                            onChange={(e) => setFormData({ ...formData, leave_type: e.target.value })}
                            required
                        >
                            <option value="annual">{t('hr.leaves.type_annual')}</option>
                            <option value="sick">{t('hr.leaves.type_sick')}</option>
                            <option value="emergency">{t('hr.leaves.type_emergency')}</option>
                            <option value="unpaid">{t('hr.leaves.type_unpaid')}</option>
                        </select>
                    </div>
                    <div style={{ display: 'flex', gap: '16px' }}>
                        <div className="form-group" style={{ flex: 1 }}>
                            <label className="form-label">{t('hr.leaves.start_date')}</label>
                            <input
                                className="form-input"
                                value={formData.start_date}
                                onChange={(e) => setFormData({ ...formData, start_date: e.target.value })}
                                required
                                style={{ direction: 'ltr' }}
                            />
                        </div>
                        <div className="form-group" style={{ flex: 1 }}>
                            <label className="form-label">{t('hr.leaves.end_date')}</label>
                            <input
                                className="form-input"
                                value={formData.end_date}
                                onChange={(e) => setFormData({ ...formData, end_date: e.target.value })}
                                required
                                style={{ direction: 'ltr' }}
                            />
                        </div>
                    </div>
                    <div className="form-group">
                        <label className="form-label">{t('hr.leaves.reason')}</label>
                        <textarea
                            className="form-input"
                            rows="3"
                            value={formData.reason}
                            onChange={(e) => setFormData({ ...formData, reason: e.target.value })}
                            placeholder={t('common.notes', 'Notes')}
                        ></textarea>
                    </div>
                </div>
            </SimpleModal>
        </div>
    );
};

export default LeaveList;
