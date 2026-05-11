
import { useState, useEffect, useMemo } from 'react';
import { hrAPI } from '../../utils/api';
import { toastEmitter } from '../../utils/toastEmitter';
import { useTranslation } from 'react-i18next';
import { Plus, Check, X, DollarSign } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useBranch } from '../../context/BranchContext';
import { hasPermission } from '../../utils/auth';
import { formatShortDate } from '../../utils/dateUtils';
import { formatNumber } from '../../utils/format';
import DataTable from '../../components/common/DataTable';
import SearchFilter from '../../components/common/SearchFilter';
import BackButton from '../../components/common/BackButton';

const LoanList = () => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const { currentBranch } = useBranch();
    const [loans, setLoans] = useState([]);
    const [employees, setEmployees] = useState([]);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [actionLoading, setActionLoading] = useState(false);
    const [search, setSearch] = useState('');
    const [filterValues, setFilterValues] = useState({});

    // Permissions
    const canManageLoans = hasPermission('hr.loans.manage');
    const canViewLoans = hasPermission('hr.loans.view');

    const [formData, setFormData] = useState({
        employee_id: '',
        amount: '',
        total_installments: '6',
        start_date: new Date().toISOString().split('T')[0],
        reason: ''
    });

    useEffect(() => {
        if (!canViewLoans) {
            toastEmitter.emit(t('common.unauthorized'), 'error');
            navigate('/hr');
            return;
        }
        fetchData();
    }, []);

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
            const [loansRes, employeesRes] = await Promise.all([
                hrAPI.listLoans(params),
                hrAPI.listEmployees(params)
            ]);
            const loansData = loansRes?.data;
            const employeesData = employeesRes?.data;
            setLoans(Array.isArray(loansData) ? loansData : loansData || []);
            setEmployees(Array.isArray(employeesData) ? employeesData : employeesData || []);
        } catch (error) {
            toastEmitter.emit(t('common.error'), 'error');
            const detail = error.response?.data?.detail;
            if (detail) toastEmitter.emit(detail, 'error');
        } finally {
            setLoading(false);
            setInitialLoad(false);
        }
    };

    const handleCreate = async (e) => {
        e.preventDefault();
        setActionLoading(true);
        try {
            await hrAPI.createLoan(formData);
            toastEmitter.emit(t('hr.loans.save_success'), 'success');
            setIsModalOpen(false);
            fetchData();
            setFormData({ ...formData, amount: '', reason: '' });
        } catch (error) {
            toastEmitter.emit(error.response?.data?.detail || error.message, 'error');
        } finally {
            setActionLoading(false);
        }
    };

    const handleApprove = async (id) => {
        if (!window.confirm(t('common.confirm_delete') || 'Are you sure?')) return;
        try {
            await hrAPI.approveLoan(id);
            toastEmitter.emit(t('hr.loans.approve_success'), 'success');
            fetchData();
        } catch (error) {
            toastEmitter.emit(error.response?.data?.detail || error.message, 'error');
        }
    };

    const getStatusBadge = (status) => {
        switch (status) {
            case 'active': return <span className="badge bg-success-light text-success">{t('hr.loans.active')}</span>;
            case 'completed': return <span className="badge bg-primary-light text-primary">{t('hr.loans.completed')}</span>;
            case 'pending': return <span className="badge bg-warning-light text-warning">{t('hr.loans.pending')}</span>;
            case 'rejected': return <span className="badge bg-danger-light text-danger">{t('hr.loans.rejected')}</span>;
            default: return <span className="badge bg-light text-muted">{status}</span>;
        }
    };

    const filteredData = useMemo(() => {
        let result = loans;
        if (search) {
            const q = search.toLowerCase();
            result = result.filter(loan =>
                loan.employee_name?.toLowerCase().includes(q) ||
                loan.reason?.toLowerCase().includes(q)
            );
        }
        if (filterValues.status) {
            result = result.filter(loan => loan.status === filterValues.status);
        }
        return result;
    }, [loans, search, filterValues]);

    const columns = [
        {
            key: 'employee_name',
            label: t('hr.loans.employee'),
            render: (val) => <span className="fw-bold">{val}</span>,
        },
        {
            key: 'amount',
            label: t('hr.loans.amount'),
            render: (val) => formatNumber(val),
        },
        {
            key: 'paid_amount',
            label: t('hr.loans.paid'),
            render: (val) => <span className="text-success">{formatNumber(val)}</span>,
        },
        {
            key: '_remaining',
            label: t('hr.loans.remaining'),
            render: (_val, row) => <span className="text-danger">{formatNumber(row.amount - row.paid_amount)}</span>,
        },
        {
            key: 'monthly_installment',
            label: t('hr.loans.installment'),
            render: (val) => formatNumber(val),
        },
        {
            key: 'status',
            label: t('hr.loans.status'),
            render: (val) => getStatusBadge(val),
        },
        {
            key: 'start_date',
            label: t('hr.loans.start_date'),
            render: (val) => <span className="text-muted small">{formatShortDate(val)}</span>,
        },
        {
            key: '_actions',
            label: t('common.actions'),
            width: '120px',
            render: (_val, row) => (
                row.status === 'pending' && canManageLoans ? (
                    <button
                        onClick={(e) => { e.stopPropagation(); handleApprove(row.id); }}
                        className="btn btn-icon text-success hover-bg-success-light"
                        title={t('hr.loans.approve')}
                    >
                        <Check size={18} />
                    </button>
                ) : null
            ),
        },
    ];

    const statusFilterOptions = [
        { value: 'pending', label: t('hr.loans.pending') },
        { value: 'active', label: t('hr.loans.active') },
        { value: 'completed', label: t('hr.loans.completed') },
        { value: 'rejected', label: t('hr.loans.rejected') },
    ];

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1 className="workspace-title">
                            <DollarSign size={24} className="me-2 text-primary" />
                            {t('hr.loans.title')}
                        </h1>
                        <p className="workspace-subtitle">{t('hr.loans.subtitle')}</p>
                    </div>
                    {canManageLoans && (
                        <button
                            onClick={() => setIsModalOpen(true)}
                            className="btn btn-primary shadow-sm"
                        >
                            <Plus size={18} className="me-2" />
                            {t('hr.loans.add')}
                        </button>
                    )}
                </div>
            </div>

            <SearchFilter
                value={search}
                onChange={setSearch}
                placeholder={t('common.search')}
                filters={[
                    { key: 'status', label: t('hr.loans.status'), options: statusFilterOptions },
                ]}
                filterValues={filterValues}
                onFilterChange={(key, value) => setFilterValues(prev => ({ ...prev, [key]: value }))}
            />

            <DataTable
                columns={columns}
                data={filteredData}
                loading={initialLoad && !loans.length}
                emptyIcon={<DollarSign size={48} className="text-light" />}
                emptyTitle={t('common.no_records_found')}
                emptyAction={canManageLoans ? { label: t('hr.loans.add'), onClick: () => setIsModalOpen(true) } : undefined}
            />

            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}

            {/* Create Modal */}
            {isModalOpen && (
                <div className="modal-overlay">
                    <div className="modal-content" style={{ maxWidth: '500px' }}>
                        <div className="modal-header">
                            <h3 className="modal-title">{t('hr.loans.form_title')}</h3>
                            <button className="btn-icon" onClick={() => setIsModalOpen(false)}><X size={20} /></button>
                        </div>
                        <form onSubmit={handleCreate}>
                            <div className="modal-body">
                                <div className="mb-3">
                                    <label className="form-label">{t('hr.loans.employee')}</label>
                                    <select
                                        className="form-input"
                                        value={formData.employee_id}
                                        onChange={(e) => setFormData({ ...formData, employee_id: e.target.value })}
                                        required
                                    >
                                        <option value="">-- {t('common.select')} --</option>
                                        {employees.map(emp => (
                                            <option key={emp.id} value={emp.id}>{emp.first_name} {emp.last_name}</option>
                                        ))}
                                    </select>
                                </div>

                                <div className="row g-3 mb-3">
                                    <div className="col-md-6">
                                        <label className="form-label">{t('hr.loans.amount_required')}</label>
                                        <input
                                            type="number"
                                            className="form-input"
                                            value={formData.amount}
                                            onChange={(e) => setFormData({ ...formData, amount: e.target.value })}
                                            required
                                        />
                                    </div>
                                    <div className="col-md-6">
                                        <label className="form-label">{t('hr.loans.installments')}</label>
                                        <input
                                            type="number"
                                            className="form-input"
                                            value={formData.total_installments}
                                            onChange={(e) => setFormData({ ...formData, total_installments: e.target.value })}
                                            required
                                            min="1"
                                        />
                                    </div>
                                </div>

                                <div className="mb-3">
                                    <label className="form-label">{t('hr.loans.start_date')}</label>
                                    <input
                                        className="form-input"
                                        value={formData.start_date}
                                        onChange={(e) => setFormData({ ...formData, start_date: e.target.value })}
                                        required
                                        style={{ direction: 'ltr' }}
                                    />
                                    <div className="form-text small text-muted mt-1">{t('hr.loans.start_date_help')}</div>
                                </div>

                                <div>
                                    <label className="form-label">{t('hr.loans.reason')}</label>
                                    <textarea
                                        className="form-input"
                                        rows="3"
                                        value={formData.reason}
                                        onChange={(e) => setFormData({ ...formData, reason: e.target.value })}
                                        placeholder={t('hr.loans.reason')}
                                    />
                                </div>
                            </div>

                            <div className="modal-footer">
                                <button type="button" className="btn btn-outline-secondary" onClick={() => setIsModalOpen(false)}>
                                    {t('common.cancel')}
                                </button>
                                <button type="submit" className="btn btn-primary px-4" disabled={actionLoading}>
                                    {actionLoading ? t('common.processing') : t('common.save')}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
};

export default LoanList;
