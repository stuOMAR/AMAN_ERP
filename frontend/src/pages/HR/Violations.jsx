import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { hrAdvancedAPI, hrAPI } from '../../utils/api';
import { formatNumber } from '../../utils/format';
import { toastEmitter } from '../../utils/toastEmitter';
import { Plus, Edit2 } from 'lucide-react';
import '../../index.css';
import '../../components/ModuleStyles.css';

import DateInput from '../../components/common/DateInput';
import BackButton from '../../components/common/BackButton';
const Violations = () => {
    const { t, i18n } = useTranslation();
    const isRTL = i18n.language === 'ar';
    const [violations, setViolations] = useState([]);
    const [employees, setEmployees] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const [editItem, setEditItem] = useState(null);
    const [form, setForm] = useState({ employee_id: '', violation_type: '', violation_date: '', description: '', action_taken: 'warning', deduction_amount: 0 });

    const violationTypes = [
        { value: 'absence', ar: 'غياب بدون إذن', en: 'Unauthorized Absence' },
        { value: 'late', ar: 'تأخير', en: 'Tardiness' },
        { value: 'misconduct', ar: 'سوء سلوك', en: 'Misconduct' },
        { value: 'negligence', ar: 'إهمال', en: 'Negligence' },
        { value: 'policy_violation', ar: 'مخالفة سياسة', en: 'Policy Violation' },
        { value: 'other', ar: 'أخرى', en: 'Other' }
    ];

    const actions = [
        { value: 'warning', ar: 'إنذار', en: 'Warning' },
        { value: 'written_warning', ar: 'إنذار كتابي', en: 'Written Warning' },
        { value: 'deduction', ar: 'خصم', en: 'Deduction' },
        { value: 'suspension', ar: 'إيقاف', en: 'Suspension' },
        { value: 'termination', ar: 'فصل', en: 'Termination' }
    ];

    const fetchData = async () => {
        setLoading(true);
        try {
            const [vRes, empRes] = await Promise.all([
                hrAdvancedAPI.listViolations(),
                hrAPI.listEmployees({ limit: 200 })
            ]);
            setViolations(vRes.data || []);
            setEmployees(empRes.data?.items || empRes.data || []);
        } catch (e) { toastEmitter.emit(t('common.error'), 'error'); }
        setLoading(false);
    };

    useEffect(() => { fetchData(); }, []);

    const handleSave = async () => {
        try {
            const payload = { ...form, employee_id: parseInt(form.employee_id), deduction_amount: String(form.deduction_amount || 0) };
            if (editItem) {
                await hrAdvancedAPI.updateViolation(editItem.id, payload);
            } else {
                await hrAdvancedAPI.createViolation(payload);
            }
            setShowModal(false); setEditItem(null);
            setForm({ employee_id: '', violation_type: '', violation_date: '', description: '', action_taken: 'warning', deduction_amount: 0 });
            fetchData();
        } catch (e) { toastEmitter.emit(t('common.error'), 'error'); }
    };

    const getActionBadge = (action) => {
        const colorMap = { warning: 'badge-warning', written_warning: 'badge-warning', deduction: 'badge-danger', suspension: 'badge-danger', termination: 'badge-danger' };
        const a = actions.find(a => a.value === action);
        return <span className={`badge ${colorMap[action] || 'badge-info'}`}>{a ? (isRTL ? a.ar : a.en) : action}</span>;
    };

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">{t('hr.violations.violations_penalties')}</h1>
                    <p className="workspace-subtitle">{t('hr.violations.manage_employee_violations_and_penalties')}</p>
                </div>
                <button className="btn btn-primary" onClick={() => { setEditItem(null); setForm({ employee_id: '', violation_type: '', violation_date: '', description: '', action_taken: 'warning', deduction_amount: 0 }); setShowModal(true); }}>
                    <Plus size={16} /> {t('hr.violations.new_violation')}
                </button>
            </div>

            <div className="card">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>{t('hr.violations.employee')}</th>
                            <th>{t('hr.violations.type')}</th>
                            <th>{t('hr.violations.date')}</th>
                            <th>{t('hr.violations.description')}</th>
                            <th>{t('hr.violations.action')}</th>
                            <th>{t('hr.violations.deduction')}</th>
                            <th>{t('common.actions', 'إجراءات')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading ? (
                            <tr><td colSpan="8" style={{ textAlign: 'center', padding: '2rem' }}>{t('hr.violations.loading')}</td></tr>
                        ) : violations.length === 0 ? (
                            <tr><td colSpan="8" style={{ textAlign: 'center', padding: '2rem', color: '#666' }}>{t('hr.violations.no_violations')}</td></tr>
                        ) : violations.map((v, i) => (
                            <tr key={v.id}>
                                <td>{i + 1}</td>
                                <td style={{ fontWeight: 600 }}>{v.employee_name || `#${v.employee_id}`}</td>
                                <td>{violationTypes.find(vt => vt.value === v.violation_type)?.[t('hr.violations.en')] || v.violation_type}</td>
                                <td>{v.violation_date}</td>
                                <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{v.description || '-'}</td>
                                <td>{getActionBadge(v.action_taken)}</td>
                                <td>{v.deduction_amount > 0 ? formatNumber(v.deduction_amount) : '-'}</td>
                                <td>
                                    <button className="btn btn-sm btn-secondary" onClick={() => { setEditItem(v); setForm({ employee_id: v.employee_id, violation_type: v.violation_type || '', violation_date: v.violation_date || '', description: v.description || '', action_taken: v.action_taken || 'warning', deduction_amount: v.deduction_amount || 0 }); setShowModal(true); }}><Edit2 size={14} /></button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {showModal && (
                <div className="modal-overlay" onClick={() => setShowModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 500 }}>
                        <h2 className="modal-title">{editItem ? (t('hr.violations.edit_violation')) : (t('hr.violations.new_violation'))}</h2>
                        <div className="form-group">
                            <label>{t('hr.violations.employee')}</label>
                            <select className="form-input" value={form.employee_id} onChange={e => setForm({ ...form, employee_id: e.target.value })}>
                                <option value="">{t('hr.violations.select')}</option>
                                {employees.map(emp => <option key={emp.id} value={emp.id}>{emp.name || emp.full_name}</option>)}
                            </select>
                        </div>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                            <div className="form-group">
                                <label>{t('hr.violations.violation_type')}</label>
                                <select className="form-input" value={form.violation_type} onChange={e => setForm({ ...form, violation_type: e.target.value })}>
                                    <option value="">{t('hr.violations.select')}</option>
                                    {violationTypes.map(vt => <option key={vt.value} value={vt.value}>{isRTL ? vt.ar : vt.en}</option>)}
                                </select>
                            </div>
                            <div className="form-group">
                                <label>{t('hr.violations.date')}</label>
                                <DateInput className="form-input" value={form.violation_date} onChange={e => setForm({ ...form, violation_date: e.target.value })} />
                            </div>
                        </div>
                        <div className="form-group">
                            <label>{t('hr.violations.description')}</label>
                            <textarea className="form-input" rows="2" value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} />
                        </div>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                            <div className="form-group">
                                <label>{t('hr.violations.action_taken')}</label>
                                <select className="form-input" value={form.action_taken} onChange={e => setForm({ ...form, action_taken: e.target.value })}>
                                    {actions.map(a => <option key={a.value} value={a.value}>{isRTL ? a.ar : a.en}</option>)}
                                </select>
                            </div>
                            <div className="form-group">
                                <label>{t('hr.violations.deduction_amount')}</label>
                                <input type="number" className="form-input" value={form.deduction_amount} onChange={e => setForm({ ...form, deduction_amount: e.target.value })} disabled={form.action_taken !== 'deduction'} />
                            </div>
                        </div>
                        <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end', marginTop: '1rem' }}>
                            <button className="btn btn-secondary" onClick={() => setShowModal(false)}>{t('hr.violations.cancel')}</button>
                            <button className="btn btn-primary" onClick={handleSave}>{t('hr.violations.save')}</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default Violations;
