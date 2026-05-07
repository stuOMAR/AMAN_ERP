import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
    Mail, Phone,
    CheckCircle, XCircle, Shield,
    DollarSign, MoreVertical, Plus
} from 'lucide-react';
import { hrAPI, branchesAPI, rolesAPI, currenciesAPI } from '../../utils/api';
import { formatNumber } from '../../utils/format';
import { useBranch } from '../../context/BranchContext';
import { getCurrency, getUser } from '../../utils/auth';
import { toastEmitter } from '../../utils/toastEmitter';
import Pagination, { usePagination } from '../../components/common/Pagination';
import '../../index.css';

import { useLocation } from 'react-router-dom';
import BackButton from '../../components/common/BackButton';

const toAmount = (value) => {
    const n = Number(value);
    return Number.isFinite(n) ? n : 0;
};

const employeeTotalSalary = (emp) => (
    toAmount(emp.salary)
    + toAmount(emp.housing_allowance)
    + toAmount(emp.transport_allowance)
    + toAmount(emp.other_allowances)
);

const Employees = () => {
    const { t } = useTranslation();
    const location = useLocation();
    const companyCurrency = getCurrency();
    const user = getUser();
    const isAdmin = user?.role === 'admin' || user?.role === 'system_admin' || user?.role === 'superuser' || user?.role === 'gm' || user?.role === 'manager';
    const [employees, setEmployees] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const [branches, setBranches] = useState([]);
    const [isEditMode, setIsEditMode] = useState(false);
    const [selectedId, setSelectedId] = useState(null);
    const [departments, setDepartments] = useState([]);
    const [positions, setPositions] = useState([]);
    const [availableRoles, setAvailableRoles] = useState([]);
    const [currencies, setCurrencies] = useState([]);
    const { currentPage, pageSize, totalItems, paginatedItems, onPageChange, onPageSizeChange } = usePagination(employees);

    useEffect(() => {
        if (location.state?.openModal) {
            setShowModal(true);
            window.history.replaceState({}, document.title)
        }
    }, [location]);

    const { currentBranch } = useBranch();
    const [activeTab, setActiveTab] = useState('basic');

    // Form State
    const [formData, setFormData] = useState({
        employee_code: '',
        first_name: '',
        last_name: '',
        first_name_en: '',
        last_name_en: '',
        email: '',
        phone: '',
        department_name: '',
        position_title: '',
        salary: 0,
        housing_allowance: 0,
        transport_allowance: 0,
        other_allowances: 0,
        hire_date: new Date().toISOString().split('T')[0],
        create_user: false,
        username: '',
        password: '',
        role: 'user',
        create_ledger: false,
        branch_id: currentBranch?.id || null,
        allowed_branch_ids: [],
        currency: currentBranch?.default_currency || companyCurrency,
        nationality: ''
    });

    useEffect(() => {
        fetchEmployees();
        fetchBranches();
        fetchCommonData();
        fetchCurrencies();
    }, [currentBranch]);

    const fetchCurrencies = async () => {
        try {
            const res = await currenciesAPI.list();
            setCurrencies(res.data || []);
        } catch (err) {
            toastEmitter.emit(t('common.error'), 'error');
        }
    };

    // Auto-set currency when branch changes in form
    const handleBranchChange = (branchId) => {
        const selectedBranch = branches.find(b => b.id === branchId);
        const branchCurrency = selectedBranch?.default_currency || companyCurrency;
        setFormData(prev => ({
            ...prev,
            branch_id: branchId,
            currency: branchCurrency
        }));
    };

    const fetchCommonData = async () => {
        try {
            const [deptRes, posRes, rolesRes] = await Promise.all([
                hrAPI.listDepartments(),
                hrAPI.listPositions(),
                rolesAPI.list()
            ]);
            setDepartments(deptRes.data);
            setPositions(posRes.data);
            setAvailableRoles(rolesRes.data);
        } catch (err) {
            toastEmitter.emit(t('common.error'), 'error');
        }
    };

    const fetchBranches = async () => {
        try {
            const res = await branchesAPI.list();
            setBranches(res.data);
        } catch (err) {
            toastEmitter.emit(t('common.error'), 'error');
        }
    };

    const fetchEmployees = async () => {
        try {
            const params = {};
            if (currentBranch?.id) {
                params.branch_id = currentBranch.id;
            }
            const response = await hrAPI.listEmployees(params);
            setEmployees(response.data);
        } catch (error) {
            toastEmitter.emit(t('common.error'), 'error');
        } finally {
            setLoading(false);
        }
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        try {
            if (isEditMode) {
                // Remove role from update payload — backend rejects role changes via HR endpoint
                const { role, ...updateData } = formData;
                await hrAPI.updateEmployee(selectedId, updateData);
            } else {
                await hrAPI.createEmployee(formData);
            }
            setShowModal(false);
            fetchEmployees();
            resetForm();
            toastEmitter.emit(isEditMode ? t("hr.employees.update_success") : t("hr.employees.add_success"), "success");
        } catch (error) {
            toastEmitter.emit(t('hr.employees.error_saving') + (error.response?.data?.detail || error.message), 'error');
        }
    };

    const resetForm = () => {
        setFormData({
            employee_code: '',
            first_name: '',
            last_name: '',
            email: '',
            phone: '',
            position_title: '',
            department_name: '',
            salary: 0,
            housing_allowance: 0,
            transport_allowance: 0,
            other_allowances: 0,
            create_user: false,
            username: '',
            password: '',
            role: 'user',
            create_ledger: false,
            branch_id: currentBranch?.id || null,
            allowed_branch_ids: [],
            currency: currentBranch?.default_currency || companyCurrency,
            nationality: ''
        });
        setActiveTab('basic');
        setIsEditMode(false);
        setSelectedId(null);
    };

    const handleEdit = (emp) => {
        setIsEditMode(true);
        setSelectedId(emp.id);
        setFormData({
            employee_code: emp.employee_code || '',
            first_name: emp.first_name,
            last_name: emp.last_name,
            email: emp.email || '',
            phone: emp.phone || '',
            position_title: emp.position || '',
            department_name: emp.department || '',
            salary: emp.salary || 0,
            housing_allowance: emp.housing_allowance || 0,
            transport_allowance: emp.transport_allowance || 0,
            other_allowances: emp.other_allowances || 0,
            create_user: !!emp.user_id,
            username: '', // Can't edit username easily usually
            password: '',
            role: emp.role || 'user',
            create_ledger: !!emp.account_id,
            branch_id: emp.branch_id || null,
            allowed_branch_ids: emp.allowed_branches || [],
            currency: emp.currency || companyCurrency,
            nationality: emp.nationality || ''
        });
        setShowModal(true);
    };

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">{t("hr.employees.title")}</h1>
                    <p className="workspace-subtitle">{t("hr.employees.subtitle")}</p>
                </div>
                <div className="header-actions">
                    <button className="btn btn-primary" onClick={() => setShowModal(true)}>
                        <Plus size={18} style={{ marginLeft: '8px' }} />
                        {t('hr.employees.new_employee')}
                    </button>
                </div>
            </div>

            <div className="data-table-container">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t("hr.employees.code")}</th>
                            <th>{t("hr.employees.employee")}</th>
                            <th>{t("hr.employees.position_dept")}</th>
                            <th>{t("hr.employees.contact_info")}</th>
                            <th>{t("common.status_title")}</th>
                            <th>{t("hr.employees.system_link")}</th>
                            <th>{t("hr.employees.financial_link")}</th>
                            <th>{t('employee.total_salary', 'Total Salary')}</th>
                            <th>{t("hr.employees.actions")}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading ? (
                            <tr><td colSpan="7" className="text-center p-4">{t("common.loading")}</td></tr>
                        ) : employees.length === 0 ? (
                            <tr>
                                <td colSpan="7" className="start-guide">
                                    <div style={{ padding: '60px 20px', textAlign: 'center' }}>
                                        <div style={{ fontSize: '48px', marginBottom: '16px' }}>👥</div>
                                        <h3 style={{ fontSize: '18px', marginBottom: '8px' }}>{t("hr.employees.no_employees")}</h3>
                                        <p style={{ color: 'var(--text-secondary)', marginBottom: '24px' }}>
                                            {t("hr.employees.no_employees_desc")}
                                        </p>
                                        <button className="btn btn-primary" onClick={() => setShowModal(true)}>
                                            <Plus size={18} className="ms-2" />
                                            {t('hr.employees.add_first')}
                                        </button>
                                    </div>
                                </td>
                            </tr>
                        ) : (
                            paginatedItems.map(emp => (
                                <tr key={emp.id} className="hover-row">
                                    <td>
                                        <span className="text-muted fw-bold">{emp.employee_code || `#${emp.id}`}</span>
                                    </td>
                                    <td>
                                        <div className="d-flex align-items-center gap-2">
                                            <div className="avatar-circle">
                                                {emp.first_name[0]}{emp.last_name[0]}
                                            </div>
                                            <div>
                                                <div className="fw-bold">{emp.first_name} {emp.last_name}</div>
                                            </div>
                                        </div>
                                    </td>
                                    <td>
                                        <div>{emp.position}</div>
                                        <small className="text-muted">{emp.department}</small>
                                    </td>
                                    <td>
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                            {emp.email && (
                                                <div className="d-flex align-items-center gap-1 text-muted small">
                                                    <Mail size={12} /> {emp.email}
                                                </div>
                                            )}
                                            {emp.phone && (
                                                <div className="d-flex align-items-center gap-1 text-muted small">
                                                    <Phone size={12} /> {emp.phone}
                                                </div>
                                            )}
                                        </div>
                                    </td>
                                    <td>
                                        <span className={`status-badge status-${emp.status}`}>
                                            {emp.status}
                                        </span>
                                    </td>
                                    <td>
                                        {emp.user_id ? (
                                            <span className="badge badge-success">
                                                <Shield size={12} className="me-1" />
                                                {t('hr.employees.linked')}
                                            </span>
                                        ) : (
                                            <span className="text-muted">-</span>
                                        )}
                                    </td>
                                    <td>
                                        {emp.account_id ? (
                                            <span className="badge badge-info">
                                                <DollarSign size={12} className="me-1" />
                                                {t('hr.employees.linked')}
                                            </span>
                                        ) : (
                                            <span className="text-muted">-</span>
                                        )}
                                    </td>
                                    <td>
                                        <div className="fw-bold">
                                            {formatNumber(employeeTotalSalary(emp))} {emp.currency || companyCurrency}
                                        </div>
                                    </td>
                                    <td>
                                        <button className="btn-icon" onClick={() => handleEdit(emp)}>
                                            <MoreVertical size={16} />
                                        </button>
                                    </td>
                                </tr>
                            ))
                        )}
                    </tbody>
                    {employees.length > 0 && (
                        <tfoot className="table-footer bg-light">
                            <tr>
                                <td colSpan="7" className="text-start fw-bold p-3">{t("hr.employees.total_salaries")}</td>
                                <td className="fw-bold text-primary p-3" style={{ fontSize: '1.1rem' }}>
                                    {(() => {
                                        const byCurrency = {};
                                        employees.forEach(emp => {
                                            const c = emp.currency || companyCurrency;
                                            const total = employeeTotalSalary(emp);
                                            byCurrency[c] = (byCurrency[c] || 0) + total;
                                        });
                                        // Sort: base currency first, then alphabetically
                                        const sorted = Object.entries(byCurrency).sort(([a], [b]) => {
                                            if (a === companyCurrency) return -1;
                                            if (b === companyCurrency) return 1;
                                            return a.localeCompare(b);
                                        });
                                        return sorted.map(([c, total]) => (
                                            <div key={c}>{formatNumber(total)} {c}</div>
                                        ));
                                    })()}
                                </td>
                                <td></td>
                            </tr>
                        </tfoot>
                    )}
                </table>
                <Pagination currentPage={currentPage} totalItems={totalItems} pageSize={pageSize} onPageChange={onPageChange} onPageSizeChange={onPageSizeChange} />
            </div>

            {/* Modal */}
            {showModal && (
                <div className="modal-overlay">
                    <div className="modal-content">
                        <div className="modal-header">
                            <h3 className="modal-title">{isEditMode ? t("hr.employees.edit_employee") : t("hr.employees.new_employee")}</h3>
                            <button className="btn-icon" onClick={() => setShowModal(false)}>
                                <XCircle size={20} className="text-muted hover-danger" />
                            </button>
                        </div>

                        <div className="modal-tabs">
                            <button
                                className={`modal-tab ${activeTab === 'basic' ? 'active' : ''}`}
                                onClick={() => setActiveTab('basic')}
                            >
                                {t('hr.employees.basic_data')}
                            </button>
                            <button
                                className={`modal-tab ${activeTab === 'access' ? 'active' : ''}`}
                                onClick={() => setActiveTab('access')}
                            >
                                {t('hr.employees.access_permissions')}
                            </button>
                            <button
                                className={`modal-tab ${activeTab === 'finance' ? 'active' : ''}`}
                                onClick={() => setActiveTab('finance')}
                            >
                                {t('hr.employees.financial_info')}
                            </button>
                        </div>

                        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
                            <div className="modal-body">
                                {activeTab === 'basic' && (
                                    <div className="row g-3">
                                        <div className="col-md-12">
                                            <label className="form-label">{t("hr.employees.code")}</label>
                                            <input
                                                type="text"
                                                className="form-input"
                                                value={formData.employee_code}
                                                onChange={e => setFormData({ ...formData, employee_code: e.target.value })}
                                                placeholder={t("hr.employees.code_placeholder")}
                                            />
                                        </div>
                                        <div className="col-md-6">
                                            <label className="form-label">{t('employee.first_name', 'First Name')} <span className="text-danger">*</span></label>
                                            <input
                                                type="text"
                                                className="form-input"
                                                required
                                                value={formData.first_name}
                                                onChange={e => setFormData({ ...formData, first_name: e.target.value })}
                                                placeholder={t("hr.employees.first_name_ph")}
                                            />
                                        </div>
                                        <div className="col-md-6">
                                            <label className="form-label">{t('employee.last_name', 'Last Name')} <span className="text-danger">*</span></label>
                                            <input
                                                type="text"
                                                className="form-input"
                                                required
                                                value={formData.last_name}
                                                onChange={e => setFormData({ ...formData, last_name: e.target.value })}
                                                placeholder={t("hr.employees.last_name_ph")}
                                            />
                                        </div>

                                        <div className="col-md-6">
                                            <label className="form-label">{t('common.primary_branch', 'Primary Branch')}</label>
                                            <select
                                                className="form-input"
                                                value={formData.branch_id || ''}
                                                onChange={e => handleBranchChange(e.target.value ? parseInt(e.target.value) : null)}
                                            >
                                                <option value="">{t("common.not_specified")}</option>
                                                {branches.map(b => (
                                                    <option key={b.id} value={b.id}>{b.branch_name} ({b.default_currency || companyCurrency})</option>
                                                ))}
                                            </select>
                                        </div>
                                        <div className="col-md-6">
                                            <label className="form-label">{t('hr.employees.nationality', 'الجنسية')}</label>
                                            <select
                                                className="form-input"
                                                value={formData.nationality}
                                                onChange={e => setFormData({ ...formData, nationality: e.target.value })}
                                            >
                                                <option value="">{t("common.not_specified")}</option>
                                                <option value="SA">{t('hr.nationality.saudi')}</option>
                                                <option value="AE">{t('hr.nationality.emirati')}</option>
                                                <option value="EG">{t('hr.nationality.egyptian')}</option>
                                                <option value="JO">{t('hr.nationality.jordanian')}</option>
                                                <option value="SY">{t('hr.nationality.syrian')}</option>
                                                <option value="LB">{t('hr.nationality.lebanese')}</option>
                                                <option value="PK">{t('hr.nationality.pakistani')}</option>
                                                <option value="IN">{t('hr.nationality.indian')}</option>
                                                <option value="BD">{t('hr.nationality.bangladeshi')}</option>
                                                <option value="PH">{t('hr.nationality.filipino')}</option>
                                                <option value="OTHER">{t('common.other', 'أخرى')}</option>
                                            </select>
                                        </div>
                                        <div className="col-md-6">
                                            <label className="form-label">{t('common.department', 'Department')}</label>
                                            <select
                                                className="form-input"
                                                value={formData.department_name}
                                                onChange={e => setFormData({ ...formData, department_name: e.target.value })}
                                            >
                                                <option value="">{t("hr.employees.select_dept")}</option>
                                                {departments.map(dept => (
                                                    <option key={dept.id} value={dept.department_name}>{dept.department_name}</option>
                                                ))}
                                            </select>
                                        </div>
                                        <div className="col-md-6">
                                            <label className="form-label">{t('common.position', 'Position')}</label>
                                            <select
                                                className="form-input"
                                                value={formData.position_title}
                                                onChange={e => setFormData({ ...formData, position_title: e.target.value })}
                                            >
                                                <option value="">{t("hr.employees.select_position")}</option>
                                                {positions
                                                    .filter(p => !formData.department_name || !p.department_name || p.department_name === formData.department_name)
                                                    .map(pos => (
                                                        <option key={pos.id} value={pos.position_name}>{pos.position_name}</option>
                                                    ))}
                                            </select>
                                        </div>
                                        <div className="col-md-6">
                                            <label className="form-label">{t("hr.employees.email")}</label>
                                            <input
                                                type="email"
                                                className="form-input"
                                                value={formData.email}
                                                onChange={e => setFormData({ ...formData, email: e.target.value })}
                                                placeholder="email@example.com"
                                            />
                                        </div>
                                        <div className="col-md-6">
                                            <label className="form-label">{t("hr.employees.phone")}</label>
                                            <input
                                                type="text"
                                                className="form-input"
                                                value={formData.phone}
                                                onChange={e => setFormData({ ...formData, phone: e.target.value })}
                                                placeholder="05xxxxxxxx"
                                            />
                                        </div>
                                    </div>
                                )}



                                {activeTab === 'access' && (
                                    <div className="d-flex flex-column gap-4">
                                        <div className="card p-3 bg-light border-0">
                                            <div className="form-check form-switch d-flex align-items-center">
                                                <input
                                                    className="form-check-input ms-3"
                                                    type="checkbox"
                                                    id="createUserToggle"
                                                    checked={formData.create_user}
                                                    onChange={e => setFormData({ ...formData, create_user: e.target.checked })}
                                                    style={{ width: '2.5em', height: '1.25em' }}
                                                    disabled={isEditMode && formData.create_user} // Can't un-create easily?
                                                />
                                                <div>
                                                    <label className="form-check-label fw-bold d-block" htmlFor="createUserToggle">
                                                        {isEditMode && formData.create_user ? t('hr.employees.has_account') : t('hr.employees.create_account')}
                                                    </label>
                                                    <small className="text-muted">
                                                        {t("hr.employees.account_note")}
                                                    </small>
                                                </div>
                                            </div>
                                        </div>

                                        {formData.create_user && (
                                            <div className="row g-3 animate-fade-in">
                                                {!isEditMode && (
                                                    <>
                                                        <div className="col-md-12">
                                                            <label className="form-label">{t("hr.employees.username")} <span className="text-danger">*</span></label>
                                                            <input
                                                                type="text"
                                                                className="form-input"
                                                                required={formData.create_user}
                                                                value={formData.username}
                                                                onChange={e => setFormData({ ...formData, username: e.target.value })}
                                                                autoComplete="new-password"
                                                            />
                                                        </div>
                                                        <div className="col-md-6">
                                                            <label className="form-label">{t("hr.employees.password")} <span className="text-danger">*</span></label>
                                                            <input
                                                                type="password"
                                                                className="form-input"
                                                                required={formData.create_user}
                                                                value={formData.password}
                                                                onChange={e => setFormData({ ...formData, password: e.target.value })}
                                                                autoComplete="new-password"
                                                            />
                                                        </div>
                                                    </>
                                                )}

                                                <div className="col-md-6">
                                                    <label className="form-label">{t("hr.employees.role")} <span className="text-danger">*</span></label>
                                                    <select
                                                        className="form-input"
                                                        value={formData.role}
                                                        onChange={e => setFormData({ ...formData, role: e.target.value })}
                                                    >
                                                        {availableRoles.map(r => (
                                                            <option key={r.id} value={r.role_name}>{r.role_name_ar || r.role_name}</option>
                                                        ))}
                                                        {availableRoles.length === 0 && (
                                                            <>
                                                                <option value="user">{t("hr.employees.regular_user")}</option>
                                                                <option value="admin">{t("hr.employees.system_admin")}</option>
                                                            </>
                                                        )}
                                                    </select>
                                                </div>

                                                <div className="col-md-12">
                                                    <label className="form-label fw-bold">{t("hr.employees.allowed_branches")}</label>
                                                    <div className="card p-3" style={{ maxHeight: '150px', overflowY: 'auto' }}>
                                                        {branches.map(branch => (
                                                            <div key={branch.id} className="form-check mb-2">
                                                                <input
                                                                    className="form-check-input ms-2"
                                                                    type="checkbox"
                                                                    id={`branch-${branch.id}`}
                                                                    checked={formData.allowed_branch_ids.includes(branch.id)}
                                                                    onChange={(e) => {
                                                                        const checked = e.target.checked;
                                                                        setFormData(prev => {
                                                                            if (checked) {
                                                                                return { ...prev, allowed_branch_ids: [...prev.allowed_branch_ids, branch.id] };
                                                                            } else {
                                                                                return { ...prev, allowed_branch_ids: prev.allowed_branch_ids.filter(id => id !== branch.id) };
                                                                            }
                                                                        });
                                                                    }}
                                                                />
                                                                <label className="form-check-label" htmlFor={`branch-${branch.id}`}>
                                                                    {branch.branch_name}
                                                                </label>
                                                            </div>
                                                        ))}
                                                        {branches.length === 0 && <small className="text-muted">{t("hr.employees.no_branches")}</small>}
                                                    </div>
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                )}

                                {activeTab === 'finance' && (
                                    <div className="d-flex flex-column gap-4">
                                        <div className="card p-3 bg-light border-0">
                                            <div className="form-check form-switch d-flex align-items-center">
                                                <input
                                                    className="form-check-input ms-3"
                                                    type="checkbox"
                                                    id="createLedgerToggle"
                                                    checked={formData.create_ledger}
                                                    onChange={e => setFormData({ ...formData, create_ledger: e.target.checked })}
                                                    style={{ width: '2.5em', height: '1.25em' }}
                                                />
                                                <div>
                                                    <label className="form-check-label fw-bold d-block" htmlFor="createLedgerToggle">
                                                        {t('hr.employees.create_ledger')}
                                                    </label>
                                                    <small className="text-muted">
                                                        {t("hr.employees.ledger_note")}
                                                    </small>
                                                </div>
                                            </div>
                                        </div>

                                        <div className="row g-3">
                                            <div className="col-md-12">
                                                <label className="form-label">{t('hr.employees.salary_currency', 'عملة الراتب')}</label>
                                                {isAdmin && !currentBranch ? (
                                                    <select
                                                        className="form-input"
                                                        value={formData.currency}
                                                        onChange={e => setFormData({ ...formData, currency: e.target.value })}
                                                    >
                                                        {currencies.filter(c => c.is_active).map(c => (
                                                            <option key={c.id} value={c.code}>{c.name} ({c.code})</option>
                                                        ))}
                                                    </select>
                                                ) : (
                                                    <div className="form-input" style={{ backgroundColor: 'var(--bg-secondary)', cursor: 'not-allowed', display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                        <DollarSign size={16} />
                                                        <strong>{formData.currency || companyCurrency}</strong>
                                                        <small className="text-muted">— {t('hr.employees.currency_auto', 'يتم تحديدها تلقائياً حسب الفرع')}</small>
                                                    </div>
                                                )}
                                            </div>
                                            <div className="col-md-6">
                                                <label className="form-label">{t("hr.employees.basic_salary")}</label>
                                                <div className="input-group">
                                                    <input
                                                        type="number"
                                                        className="form-input"
                                                        value={formData.salary}
                                                        onChange={e => setFormData({ ...formData, salary: e.target.value })}
                                                    />
                                                    <span className="input-group-text bg-white border-end-0">{formData.currency || companyCurrency}</span>
                                                </div>
                                            </div>
                                            <div className="col-md-6">
                                                <label className="form-label">{t("hr.employees.housing_allowance")}</label>
                                                <div className="input-group">
                                                    <input
                                                        type="number"
                                                        className="form-input"
                                                        value={formData.housing_allowance}
                                                        onChange={e => setFormData({ ...formData, housing_allowance: e.target.value })}
                                                    />
                                                    <span className="input-group-text bg-white border-end-0">{formData.currency || companyCurrency}</span>
                                                </div>
                                            </div>
                                            <div className="col-md-6">
                                                <label className="form-label">{t("hr.employees.transport_allowance")}</label>
                                                <div className="input-group">
                                                    <input
                                                        type="number"
                                                        className="form-input"
                                                        value={formData.transport_allowance}
                                                        onChange={e => setFormData({ ...formData, transport_allowance: e.target.value })}
                                                    />
                                                    <span className="input-group-text bg-white border-end-0">{formData.currency || companyCurrency}</span>
                                                </div>
                                            </div>
                                            <div className="col-md-6">
                                                <label className="form-label">{t("hr.employees.other_allowances")}</label>
                                                <div className="input-group">
                                                    <input
                                                        type="number"
                                                        className="form-input"
                                                        value={formData.other_allowances}
                                                        onChange={e => setFormData({ ...formData, other_allowances: e.target.value })}
                                                    />
                                                    <span className="input-group-text bg-white border-end-0">{formData.currency || companyCurrency}</span>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                )}
                            </div>

                            <div className="modal-footer">
                                <button type="button" className="btn btn-outline-secondary" onClick={() => setShowModal(false)}>{t("common.cancel")}</button>
                                <button type="submit" className="btn btn-primary">
                                    <CheckCircle size={16} className="ms-2" />
                                    {t('hr.employees.save_employee')}
                                </button>
                            </div>
                        </form>
                    </div>
                </div >
            )}
        </div >
    );
};

export default Employees;
