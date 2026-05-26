import React, { useState, useEffect } from 'react';
import Decimal from 'decimal.js';
import { useTranslation } from 'react-i18next';
import { hrAdvancedAPI, hrAPI } from '../../utils/api';
import { toastEmitter } from '../../utils/toastEmitter';
import { Plus, Check, X } from 'lucide-react';
import '../../index.css';
import '../../components/ModuleStyles.css';

import DateInput from '../../components/common/DateInput';
import BackButton from '../../components/common/BackButton';
const OvertimeRequests = () => {
    const { t, i18n } = useTranslation();
    const isRTL = i18n.language === 'ar';
    const [items, setItems] = useState([]);
    const [employees, setEmployees] = useState([]);
    const [overtimeRates, setOvertimeRates] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const [form, setForm] = useState({ employee_id: '', date: '', hours: '', rate_multiplier: 1.5, reason: '' });

    const fetchData = async () => {
        setLoading(true);
        try {
            // T8.4: also fetch configurable overtime multipliers from
            // /hr-advanced/overtime/rates (backed by overtime_rates_config).
            const [res, empRes, ratesRes] = await Promise.all([
                hrAdvancedAPI.listOvertime(),
                hrAPI.listEmployees({ limit: 200 }),
                hrAdvancedAPI.getOvertimeRates().catch(() => ({ data: { items: [] } })),
            ]);
            setItems(res.data || []);
            setEmployees(empRes.data?.items || empRes.data || []);
            const rates = ratesRes?.data?.items || [];
            setOvertimeRates(rates);
            // Seed the form with the first multiplier (defaults to weekday 1.5).
            if (rates.length && new Decimal(form.rate_multiplier || '0').equals('1.5')) {
                setForm(prev => ({ ...prev, rate_multiplier: rates[0].multiplier }));
            }
        } catch (e) { toastEmitter.emit(t('common.error'), 'error'); }
        setLoading(false);
    };

    useEffect(() => { fetchData(); }, []);

    const handleSave = async () => {
        try {
            await hrAdvancedAPI.createOvertime({ ...form, hours: String(form.hours), rate_multiplier: String(form.rate_multiplier), employee_id: parseInt(form.employee_id) });
            setShowModal(false);
            setForm({ employee_id: '', date: '', hours: '', rate_multiplier: 1.5, reason: '' });
            fetchData();
        } catch (e) { toastEmitter.emit(t('common.error'), 'error'); }
    };

    const handleApprove = async (id, status) => {
        try {
            await hrAdvancedAPI.approveOvertime(id, { status });
            fetchData();
        } catch (e) { toastEmitter.emit(t('common.error'), 'error'); }
    };

    const getStatusBadge = (status) => {
        const map = {
            pending: { cls: 'badge-warning', ar: 'معلق', en: 'Pending' },
            approved: { cls: 'badge-success', ar: 'موافق', en: 'Approved' },
            rejected: { cls: 'badge-danger', ar: 'مرفوض', en: 'Rejected' }
        };
        const s = map[status] || map.pending;
        return <span className={`badge ${s.cls}`}>{isRTL ? s.ar : s.en}</span>;
    };

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">{t('hr.overtime.overtime_requests')}</h1>
                    <p className="workspace-subtitle">{t('hr.overtime.manage_overtime_hours')}</p>
                </div>
                <button className="btn btn-primary" onClick={() => setShowModal(true)}>
                    <Plus size={16} /> {t('hr.overtime.new_request')}
                </button>
            </div>

            <div className="card">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>{t('hr.overtime.employee')}</th>
                            <th>{t('hr.overtime.date')}</th>
                            <th>{t('hr.overtime.hours')}</th>
                            <th>{t('hr.overtime.rate')}</th>
                            <th>{t('hr.overtime.reason')}</th>
                            <th>{t('hr.overtime.status')}</th>
                            <th>{t('hr.overtime.actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading ? (
                            <tr><td colSpan="8" style={{ textAlign: 'center', padding: '2rem' }}>{t('hr.overtime.loading')}</td></tr>
                        ) : items.length === 0 ? (
                            <tr><td colSpan="8" style={{ textAlign: 'center', padding: '2rem', color: '#666' }}>{t('hr.overtime.no_requests')}</td></tr>
                        ) : items.map((item, i) => (
                            <tr key={item.id}>
                                <td>{i + 1}</td>
                                <td style={{ fontWeight: 600 }}>{item.employee_name || `#${item.employee_id}`}</td>
                                <td>{item.date}</td>
                                <td>{item.hours}</td>
                                <td>×{item.rate_multiplier}</td>
                                <td>{item.reason || '-'}</td>
                                <td>{getStatusBadge(item.status)}</td>
                                <td>
                                    {item.status === 'pending' && (
                                        <div style={{ display: 'flex', gap: '0.25rem' }}>
                                            <button className="btn btn-sm btn-success" onClick={() => handleApprove(item.id, 'approved')} title={t('hr.overtime.approve')}><Check size={14} /></button>
                                            <button className="btn btn-sm btn-danger" onClick={() => handleApprove(item.id, 'rejected')} title={t('hr.overtime.reject')}><X size={14} /></button>
                                        </div>
                                    )}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {showModal && (
                <div className="modal-overlay" onClick={() => setShowModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 500 }}>
                        <h2 className="modal-title">{t('hr.overtime.overtime_request')}</h2>
                        <div className="form-group">
                            <label>{t('hr.overtime.employee')}</label>
                            <select className="form-input" value={form.employee_id} onChange={e => setForm({ ...form, employee_id: e.target.value })}>
                                <option value="">{t('hr.overtime.select')}</option>
                                {employees.map(emp => <option key={emp.id} value={emp.id}>{emp.name || emp.full_name}</option>)}
                            </select>
                        </div>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                            <div className="form-group">
                                <label>{t('hr.overtime.date')}</label>
                                <DateInput className="form-input" value={form.date} onChange={e => setForm({ ...form, date: e.target.value })} />
                            </div>
                            <div className="form-group">
                                <label>{t('hr.overtime.hours')}</label>
                                <input type="number" step="0.5" className="form-input" value={form.hours} onChange={e => setForm({ ...form, hours: e.target.value })} />
                            </div>
                        </div>
                        <div className="form-group">
                            <label>{t('hr.overtime.rate_multiplier')}</label>
                            <select className="form-input" value={form.rate_multiplier} onChange={e => setForm({ ...form, rate_multiplier: e.target.value })}>
                                {overtimeRates.length > 0 ? (
                                    // T8.4: backend-driven multipliers
                                    overtimeRates.map(r => (
                                        <option key={r.rate_key} value={r.multiplier}>
                                            {r.multiplier}× ({r.description || r.rate_key})
                                        </option>
                                    ))
                                ) : (
                                    <>
                                        <option value="1.5">1.5× ({t('hr.overtime.regular')})</option>
                                        <option value="2">2× ({t('hr.overtime.holiday')})</option>
                                    </>
                                )}
                            </select>
                        </div>
                        <div className="form-group">
                            <label>{t('hr.overtime.reason')}</label>
                            <textarea className="form-input" rows="2" value={form.reason} onChange={e => setForm({ ...form, reason: e.target.value })} />
                        </div>
                        <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end', marginTop: '1rem' }}>
                            <button className="btn btn-secondary" onClick={() => setShowModal(false)}>{t('hr.overtime.cancel')}</button>
                            <button className="btn btn-primary" onClick={handleSave}>{t('hr.overtime.submit')}</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default OvertimeRequests;
