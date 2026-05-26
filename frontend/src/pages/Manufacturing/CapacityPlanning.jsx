import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { manufacturingAPI } from '../../utils/api';
import { toastEmitter } from '../../utils/toastEmitter';
import { useToast } from '../../context/ToastContext';
import { Gauge, Plus, Activity, Settings, Edit3 } from 'lucide-react';
import BackButton from '../../components/common/BackButton';
import '../../components/ModuleStyles.css';
import DateInput from '../../components/common/DateInput';
import { formatNumber } from '../../utils/format';

const CapacityPlanning = () => {
    const { t } = useTranslation();
    const { showToast } = useToast();
    const [activeTab, setActiveTab] = useState('oee');
    const [oeeData, setOeeData] = useState(null);
    const [plans, setPlans] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showForm, setShowForm] = useState(false);
    const [editingId, setEditingId] = useState(null);
    const [oeeParams, setOeeParams] = useState({
        work_center_id: '', period_from: '', period_to: ''
    });
    const [form, setForm] = useState({
        work_center_id: '', plan_name: '', plan_date_from: '', plan_date_to: '',
        planned_capacity_hours: '', planned_output_units: '', notes: ''
    });

    useEffect(() => { fetchPlans(); }, []);

    const fetchPlans = async () => {
        try {
            setLoading(true);
            const res = await manufacturingAPI.listCapacityPlans();
            setPlans(res.data || []);
        } catch (err) { toastEmitter.emit(t('common.error'), 'error'); } finally { setLoading(false); }
    };

    const calculateOEE = async () => {
        try {
            setLoading(true);
            const res = await manufacturingAPI.calculateOEE(oeeParams);
            setOeeData(Array.isArray(res.data) ? (res.data[0] || null) : res.data);
        } catch (err) {
            showToast(err.response?.data?.detail || t('capacity_planning.oee_error', 'خطأ في حساب OEE'), 'error');
        } finally { setLoading(false); }
    };

    const handlePlanSubmit = async (e) => {
        e.preventDefault();
        try {
            if (editingId) {
                await manufacturingAPI.updateCapacityPlan(editingId, form);
                showToast(t('capacity_planning.plan_updated', 'تم تحديث الخطة'), 'success');
            } else {
                await manufacturingAPI.createCapacityPlan(form);
                showToast(t('capacity_planning.plan_created', 'تم إنشاء الخطة'), 'success');
            }
            resetForm(); fetchPlans();
        } catch (err) { showToast(err.response?.data?.detail || t('common.error', 'خطأ'), 'error'); }
    };

    const resetForm = () => {
        setShowForm(false); setEditingId(null);
        setForm({ work_center_id: '', plan_name: '', plan_date_from: '', plan_date_to: '', planned_capacity_hours: '', planned_output_units: '', notes: '' });
    };

    const oeeColorGauge = (direction) => {
        if (direction === 'high') return '#28a745';
        if (direction === 'medium') return '#ffc107';
        return '#dc3545';
    };

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div>
                    <h1 className="workspace-title">
                        <Gauge size={24} className="me-2" />
                        {t('capacity_planning.title', 'تخطيط السعة و OEE')}
                    </h1>
                    <p className="workspace-subtitle">
                        {t('capacity_planning.subtitle', 'فعالية المعدات الشاملة وتخطيط السعة الإنتاجية')}
                    </p>
                </div>
            </div>

            {/* Tabs */}
            <div className="tabs mb-4">
                <button className={`tab ${activeTab === 'oee' ? 'active' : ''}`} onClick={() => setActiveTab('oee')}>
                    <Activity size={16} /> <span className="ms-1">{t('capacity_planning.oee_analysis', 'تحليل OEE')}</span>
                </button>
                <button className={`tab ${activeTab === 'plans' ? 'active' : ''}`} onClick={() => setActiveTab('plans')}>
                    <Settings size={16} /> <span className="ms-1">{t('capacity_planning.capacity_plans', 'خطط السعة')}</span>
                </button>
            </div>

            {activeTab === 'oee' ? (
                <>
                    {/* OEE Calculator */}
                    <div className="section-card mb-4">
                        <h4 className="mb-3">{t('capacity_planning.calculate_oee', 'حساب OEE')}</h4>
                        <div className="row g-3 mb-3">
                            <div className="col-md-4">
                                <div className="form-group">
                                    <label className="form-label">{t('capacity_planning.work_center', 'مركز العمل')}</label>
                                    <input className="form-input" value={oeeParams.work_center_id} placeholder={t('capacity_planning.work_center_id', 'معرّف المركز')}
                                        onChange={e => setOeeParams(p => ({ ...p, work_center_id: e.target.value }))} />
                                </div>
                            </div>
                            <div className="col-md-3">
                                <div className="form-group">
                                    <label className="form-label">{t('capacity_planning.from_date', 'من تاريخ')}</label>
                                    <DateInput className="form-input" value={oeeParams.period_from}
                                        onChange={e => setOeeParams(p => ({ ...p, period_from: e.target.value }))} />
                                </div>
                            </div>
                            <div className="col-md-3">
                                <div className="form-group">
                                    <label className="form-label">{t('capacity_planning.to_date', 'إلى تاريخ')}</label>
                                    <DateInput className="form-input" value={oeeParams.period_to}
                                        onChange={e => setOeeParams(p => ({ ...p, period_to: e.target.value }))} />
                                </div>
                            </div>
                            <div className="col-md-2 d-flex align-items-end">
                                <button className="btn btn-primary w-100" onClick={calculateOEE}>
                                    {t('capacity_planning.calculate', 'حساب')}
                                </button>
                            </div>
                        </div>
                    </div>

                    {/* OEE Results */}
                    {oeeData && (
                        <div className="metrics-grid mb-4">
                            <div className="metric-card">
                                <div className="metric-icon" style={{ background: '#e8f5e9' }}><Activity size={22} color="#2e7d32" /></div>
                                <div className="metric-info">
                                    <span className="metric-value" style={{ color: oeeColorGauge(oeeData.availability_direction) }}>
                                        {formatNumber(oeeData.availability || 0, 1)}%
                                    </span>
                                    <span className="metric-label">{t('capacity_planning.availability', 'التوفر')}</span>
                                    <small className="text-muted">{t('capacity_planning.uptime_planned', 'وقت التشغيل / الوقت المخطط')}</small>
                                </div>
                            </div>
                            <div className="metric-card">
                                <div className="metric-icon" style={{ background: '#e3f2fd' }}><Gauge size={22} color="#1565c0" /></div>
                                <div className="metric-info">
                                    <span className="metric-value" style={{ color: oeeColorGauge(oeeData.performance_direction) }}>
                                        {formatNumber(oeeData.performance || 0, 1)}%
                                    </span>
                                    <span className="metric-label">{t('capacity_planning.performance', 'الأداء')}</span>
                                    <small className="text-muted">{t('capacity_planning.actual_ideal_speed', 'السرعة الفعلية / المُخططة')}</small>
                                </div>
                            </div>
                            <div className="metric-card">
                                <div className="metric-icon" style={{ background: '#fff3e0' }}><Settings size={22} color="#e65100" /></div>
                                <div className="metric-info">
                                    <span className="metric-value" style={{ color: oeeColorGauge(oeeData.quality_direction) }}>
                                        {formatNumber(oeeData.quality || 0, 1)}%
                                    </span>
                                    <span className="metric-label">{t('capacity_planning.quality', 'الجودة')}</span>
                                    <small className="text-muted">{t('capacity_planning.good_total_units', 'المنتجات الصالحة / الإجمالي')}</small>
                                </div>
                            </div>
                            <div className="metric-card" style={{ borderLeft: `4px solid ${oeeColorGauge(oeeData.oee_direction)}` }}>
                                <div className="metric-icon" style={{ background: '#f3e5f5' }}><Gauge size={22} color="#7b1fa2" /></div>
                                <div className="metric-info">
                                    <span className="metric-value" style={{ fontSize: '1.6rem', color: oeeColorGauge(oeeData.oee_direction) }}>
                                        {formatNumber(oeeData.oee || 0, 1)}%
                                    </span>
                                    <span className="metric-label" style={{ fontWeight: 700 }}>{t('capacity_planning.overall_oee', 'OEE الإجمالي')}</span>
                                    <small className="text-muted">{t('capacity_planning.avail_perf_quality', 'التوفر × الأداء × الجودة')}</small>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* OEE Formula */}
                    <div className="section-card" style={{ background: '#f8f9fa', border: '1px dashed #dee2e6' }}>
                        <h5>{t('capacity_planning.oee_formula', 'معادلة OEE')}</h5>
                        <p style={{ fontFamily: 'monospace', direction: 'ltr' }}>
                            <strong>OEE = Availability × Performance × Quality</strong><br />
                            Availability = Run Time / Planned Production Time<br />
                            Performance = (Ideal Cycle Time × Total Units) / Run Time<br />
                            Quality = Good Units / Total Units<br /><br />
                            <strong>{t('capacity_planning.world_class', 'المعايير العالمية:')}</strong> OEE ≥ 85% | Availability ≥ 90% | Performance ≥ 95% | Quality ≥ 99.9%
                        </p>
                    </div>
                </>
            ) : (
                <>
                    {/* Plans */}
                    <div className="mb-3">
                        <button className="btn btn-primary" onClick={() => { resetForm(); setShowForm(true); }}>
                            <Plus size={16} className="me-1" /> {t('capacity_planning.new_plan', 'خطة جديدة')}
                        </button>
                    </div>

                    {/* Plan Form */}
                    {showForm && (
                        <div className="modal-overlay">
                            <div className="modal-content" style={{ maxWidth: '880px', width: '92%' }}>
                                <div className="modal-header">
                                    <h2 className="modal-title">{editingId ? t('capacity_planning.edit_plan', 'تعديل الخطة') : t('capacity_planning.new_capacity_plan', 'خطة سعة جديدة')}</h2>
                                    <button type="button" className="btn-icon" onClick={resetForm}>✕</button>
                                </div>
                                <form onSubmit={handlePlanSubmit}>
                                    <div className="modal-body">
                                        <div className="row g-3">
                                            <div className="col-md-4">
                                                <div className="form-group">
                                                    <label className="form-label">{t('capacity_planning.plan_name', 'اسم الخطة')} *</label>
                                                    <input className="form-input" required value={form.plan_name}
                                                        onChange={e => setForm(p => ({ ...p, plan_name: e.target.value }))} />
                                                </div>
                                            </div>
                                            <div className="col-md-4">
                                                <div className="form-group">
                                                    <label className="form-label">{t('capacity_planning.work_center', 'مركز العمل')}</label>
                                                    <input className="form-input" value={form.work_center_id}
                                                        onChange={e => setForm(p => ({ ...p, work_center_id: e.target.value }))} />
                                                </div>
                                            </div>
                                            <div className="col-md-2">
                                                <div className="form-group">
                                                    <label className="form-label">{t('capacity_planning.from', 'من')}</label>
                                                    <DateInput className="form-input" value={form.plan_date_from}
                                                        onChange={e => setForm(p => ({ ...p, plan_date_from: e.target.value }))} />
                                                </div>
                                            </div>
                                            <div className="col-md-2">
                                                <div className="form-group">
                                                    <label className="form-label">{t('capacity_planning.to', 'إلى')}</label>
                                                    <DateInput className="form-input" value={form.plan_date_to}
                                                        onChange={e => setForm(p => ({ ...p, plan_date_to: e.target.value }))} />
                                                </div>
                                            </div>
                                            <div className="col-md-3">
                                                <div className="form-group">
                                                    <label className="form-label">{t('capacity_planning.planned_capacity', 'السعة المخططة (ساعات)')}</label>
                                                    <input className="form-input" type="number" value={form.planned_capacity_hours}
                                                        onChange={e => setForm(p => ({ ...p, planned_capacity_hours: e.target.value }))} />
                                                </div>
                                            </div>
                                            <div className="col-md-3">
                                                <div className="form-group">
                                                    <label className="form-label">{t('capacity_planning.planned_output', 'الإنتاج المخطط (وحدات)')}</label>
                                                    <input className="form-input" type="number" value={form.planned_output_units}
                                                        onChange={e => setForm(p => ({ ...p, planned_output_units: e.target.value }))} />
                                                </div>
                                            </div>
                                            <div className="col-md-6">
                                                <div className="form-group" style={{ marginBottom: 0 }}>
                                                    <label className="form-label">{t('common.notes', 'ملاحظات')}</label>
                                                    <textarea className="form-input" rows={2} value={form.notes}
                                                        onChange={e => setForm(p => ({ ...p, notes: e.target.value }))} />
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                    <div className="modal-footer">
                                        <button type="button" className="btn btn-secondary" onClick={resetForm}>{t('common.cancel', 'إلغاء')}</button>
                                        <button type="submit" className="btn btn-primary">{t('common.save', 'حفظ')}</button>
                                    </div>
                                </form>
                            </div>
                        </div>
                    )}

                    {/* Plans Table */}
                    <div className="section-card">
                        <div className="data-table-container">
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>{t('capacity_planning.plan_name', 'اسم الخطة')}</th>
                                        <th>{t('capacity_planning.work_center', 'مركز العمل')}</th>
                                        <th>{t('capacity_planning.period', 'الفترة')}</th>
                                        <th>{t('capacity_planning.capacity_hrs', 'السعة (ساعات)')}</th>
                                        <th>{t('capacity_planning.output_units', 'الإنتاج (وحدات)')}</th>
                                        <th></th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {plans.length === 0 ? (
                                        <tr><td colSpan={6} className="text-center p-4">{t('capacity_planning.no_plans', 'لا توجد خطط سعة')}</td></tr>
                                    ) : plans.map(p => (
                                        <tr key={p.id}>
                                            <td><strong>{p.plan_name}</strong></td>
                                            <td>{p.work_center_id || '—'}</td>
                                            <td>{p.plan_date_from} → {p.plan_date_to}</td>
                                            <td>{p.planned_capacity_hours || '—'}</td>
                                            <td>{p.planned_output_units || '—'}</td>
                                            <td>
                                                <button className="btn btn-sm btn-outline-primary" onClick={() => {
                                                    setEditingId(p.id);
                                                    setForm({ work_center_id: p.work_center_id || '', plan_name: p.plan_name, plan_date_from: p.plan_date_from || '', plan_date_to: p.plan_date_to || '', planned_capacity_hours: p.planned_capacity_hours || '', planned_output_units: p.planned_output_units || '', notes: p.notes || '' });
                                                    setShowForm(true);
                                                }}><Edit3 size={14} /></button>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </>
            )}
        </div>
    );
};

export default CapacityPlanning;
