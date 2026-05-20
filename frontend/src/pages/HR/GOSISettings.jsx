import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { hrAdvancedAPI } from '../../utils/api';
import { toastEmitter } from '../../utils/toastEmitter';
import { Save, Calculator, Shield } from 'lucide-react';
import { formatNumber } from '../../utils/format';
import Decimal from 'decimal.js';
import '../../index.css';
import '../../components/ModuleStyles.css';
import BackButton from '../../components/common/BackButton';

const GOSISettings = () => {
    const { t } = useTranslation();
    const [settings, setSettings] = useState(null);
    const [calculations, setCalculations] = useState([]);
    const [loading, setLoading] = useState(true);
    const [activeTab, setActiveTab] = useState('settings');
    const [form, setForm] = useState({
        employee_share_percentage: 9.75,
        employer_share_percentage: 11.75,
        occupational_hazard_percentage: 2.0,
        max_insurable_salary: 45000,
        is_active: true
    });

    const fetchData = async () => {
        setLoading(true);
        try {
            const res = await hrAdvancedAPI.getGOSISettings();
            const data = Array.isArray(res.data) ? res.data : [res.data];
            if (data.length > 0 && data[0]) {
                setSettings(data[0]);
                setForm({
                    employee_share_percentage: data[0].employee_share_percentage || 9.75,
                    employer_share_percentage: data[0].employer_share_percentage || 11.75,
                    occupational_hazard_percentage: data[0].occupational_hazard_percentage || 2.0,
                    max_insurable_salary: data[0].max_insurable_salary || 45000,
                    is_active: data[0].is_active !== false
                });
            }
        } catch (e) { toastEmitter.emit(t('common.error'), 'error'); }
        setLoading(false);
    };

    const fetchCalc = async () => {
        try {
            const res = await hrAdvancedAPI.calculateGOSI();
            setCalculations(res.data || []);
        } catch (e) { toastEmitter.emit(t('common.error'), 'error'); }
    };

    useEffect(() => { fetchData(); }, []);

    const handleSave = async () => {
        try {
            await hrAdvancedAPI.saveGOSISettings(form);
            fetchData();
        } catch (e) { toastEmitter.emit(t('common.error'), 'error'); }
    };

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">{t('hr.gosi.social_insurance_gosi')}</h1>
                    <p className="workspace-subtitle">{t('hr.gosi.gosi_settings_and_calculations')}</p>
                </div>
            </div>

            {/* Tabs */}
            <div className="card" style={{ marginBottom: '1rem', padding: '0.5rem' }}>
                <div style={{ display: 'flex', gap: '0.5rem' }}>
                    <button className={`btn ${activeTab === 'settings' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setActiveTab('settings')}>
                        <Shield size={16} /> {t('hr.gosi.settings')}
                    </button>
                    <button className={`btn ${activeTab === 'calc' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => { setActiveTab('calc'); fetchCalc(); }}>
                        <Calculator size={16} /> {t('hr.gosi.calculations')}
                    </button>
                </div>
            </div>

            {activeTab === 'settings' && (
                <div className="card" style={{ maxWidth: 600 }}>
                    <h3 style={{ marginBottom: '1.5rem', color: '#1a1a2e' }}>{t('hr.gosi.contribution_rates')}</h3>
                    <div className="form-group">
                        <label>{t('hr.gosi.employee_share')}</label>
                        <input type="number" step="0.25" className="form-input" value={form.employee_share_percentage} onChange={e => setForm({ ...form, employee_share_percentage: e.target.value })} />
                    </div>
                    <div className="form-group">
                        <label>{t('hr.gosi.employer_share')}</label>
                        <input type="number" step="0.25" className="form-input" value={form.employer_share_percentage} onChange={e => setForm({ ...form, employer_share_percentage: e.target.value })} />
                    </div>
                    <div className="form-group">
                        <label>{t('hr.gosi.occupational_hazard')}</label>
                        <input type="number" step="0.25" className="form-input" value={form.occupational_hazard_percentage} onChange={e => setForm({ ...form, occupational_hazard_percentage: e.target.value })} />
                    </div>
                    <div className="form-group">
                        <label>{t('hr.gosi.max_insurable_salary')}</label>
                        <input type="number" className="form-input" value={form.max_insurable_salary} onChange={e => setForm({ ...form, max_insurable_salary: e.target.value })} />
                    </div>
                    <div className="form-group" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <input type="checkbox" checked={form.is_active} onChange={e => setForm({ ...form, is_active: e.target.checked })} />
                        <label style={{ margin: 0 }}>{t('hr.gosi.active')}</label>
                    </div>

                    {/* Summary card */}
                    <div style={{ background: '#f0f4ff', borderRadius: 8, padding: '1rem', marginTop: '1rem', marginBottom: '1rem' }}>
                        <p style={{ margin: '0.25rem 0', fontSize: '0.9rem' }}>
                            <strong>{t('hr.gosi.total_employee')}</strong> {form.employee_share_percentage}%
                        </p>
                        <p style={{ margin: '0.25rem 0', fontSize: '0.9rem' }}>
                            <strong>{t('hr.gosi.total_employer')}</strong> {new Decimal(form.employer_share_percentage || '0').plus(new Decimal(form.occupational_hazard_percentage || '0')).toFixed(2)}%
                        </p>
                    </div>

                    <button className="btn btn-primary" onClick={handleSave} style={{ width: '100%' }}>
                        <Save size={16} /> {t('hr.gosi.save_settings')}
                    </button>
                </div>
            )}

            {activeTab === 'calc' && (
                <div className="card">
                    <h3 style={{ marginBottom: '1rem' }}>{t('hr.gosi.monthly_gosi_calculations')}</h3>
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>{t('hr.gosi.employee')}</th>
                                <th>{t('hr.gosi.basic_salary')}</th>
                                <th>{t('hr.gosi.employee_share_2')}</th>
                                <th>{t('hr.gosi.employer_share_2')}</th>
                                <th>{t('hr.gosi.total')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {calculations.length === 0 ? (
                                <tr><td colSpan="5" style={{ textAlign: 'center', padding: '2rem', color: '#666' }}>{t('hr.gosi.no_data')}</td></tr>
                            ) : calculations.map((c, i) => (
                                <tr key={i}>
                                    <td style={{ fontWeight: 600 }}>{c.employee_name || `#${c.employee_id}`}</td>
                                    <td>{formatNumber(c.basic_salary)}</td>
                                    <td>{formatNumber(c.employee_share)}</td>
                                    <td>{formatNumber(c.employer_share)}</td>
                                    <td style={{ fontWeight: 700 }}>{formatNumber(c.total)}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
};

export default GOSISettings;
