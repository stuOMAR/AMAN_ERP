import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import Decimal from 'decimal.js';
import { projectsAPI } from '../../utils/api';
import { useToast } from '../../context/ToastContext';
import { formatNumber } from '../../utils/format';
import { AlertTriangle, Plus, Trash2, Edit3, Save, X, GitBranch, Link2 } from 'lucide-react';
import BackButton from '../../components/common/BackButton';
import '../../components/ModuleStyles.css';
import DateInput from '../../components/common/DateInput';
import { PageLoading } from '../../components/common/LoadingStates'

const ProjectRisks = () => {
    const { t } = useTranslation();
    const { showToast } = useToast();
    const [projects, setProjects] = useState([]);
    const [selectedProject, setSelectedProject] = useState('');
    const [activeTab, setActiveTab] = useState('risks');
    const [risks, setRisks] = useState([]);
    const [dependencies, setDependencies] = useState([]);
    const [tasks, setTasks] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showForm, setShowForm] = useState(false);
    const [editingId, setEditingId] = useState(null);
    const [form, setForm] = useState({
        title: '', description: '', probability: '0.5', impact: '0.5',
        status: 'identified', mitigation_plan: '', owner_id: '', due_date: ''
    });
    const [depForm, setDepForm] = useState({ task_id: '', depends_on_task_id: '', dependency_type: 'FS', lag_days: '0' });
    const [showDepForm, setShowDepForm] = useState(false);

    useEffect(() => { fetchProjects(); }, []);
    useEffect(() => { if (selectedProject) fetchData(); }, [selectedProject, activeTab]);

    const fetchProjects = async () => {
        try {
            const res = await projectsAPI.list();
            const list = res.data?.projects || res.data || [];
            setProjects(list);
            if (list.length > 0) setSelectedProject(list[0].id);
        } catch (err) { console.error(err); }
    };

    const fetchData = async () => {
        try {
            setLoading(true);
            if (activeTab === 'risks') {
                const res = await projectsAPI.listProjectRisks(selectedProject);
                setRisks(res.data || []);
            } else {
                const [depRes, taskRes] = await Promise.all([
                    projectsAPI.listTaskDependencies(selectedProject),
                    projectsAPI.getTasks ? projectsAPI.getTasks(selectedProject) : Promise.resolve({ data: [] })
                ]);
                setDependencies(depRes.data || []);
                setTasks(taskRes.data?.tasks || taskRes.data || []);
            }
        } catch (err) { console.error(err); } finally { setLoading(false); }
    };

    const handleRiskSubmit = async (e) => {
        e.preventDefault();
        try {
            if (editingId) {
                await projectsAPI.updateProjectRisk(editingId, form);
                showToast(t('project_risks.risk_updated', 'تم تحديث الخطر'), 'success');
            } else {
                await projectsAPI.createProjectRisk(selectedProject, form);
                showToast(t('project_risks.risk_added', 'تم إضافة الخطر'), 'success');
            }
            resetRiskForm(); fetchData();
        } catch (err) { showToast(err.response?.data?.detail || t('common.error', 'خطأ'), 'error'); }
    };

    const handleDepSubmit = async (e) => {
        e.preventDefault();
        try {
            await projectsAPI.createTaskDependency(selectedProject, depForm);
            showToast(t('project_risks.dependency_created', 'تم إنشاء التبعية'), 'success');
            setShowDepForm(false); fetchData();
        } catch (err) { showToast(err.response?.data?.detail || t('common.error'), 'error'); }
    };

    const handleDeleteRisk = async (id) => {
        if (!confirm(t('project_risks.delete_risk_confirm', 'حذف هذا الخطر؟'))) return;
        try {
            await projectsAPI.deleteProjectRisk(id);
            showToast(t('project_risks.risk_deleted', 'تم حذف الخطر'), 'success');
            fetchData();
        } catch (err) { showToast(t('common.error', 'خطأ'), 'error'); }
    };

    const handleDeleteDep = async (id) => {
        try {
            await projectsAPI.deleteTaskDependency(id);
            showToast(t('project_risks.dependency_deleted', 'تم حذف التبعية'), 'success');
            fetchData();
        } catch (err) { showToast(t('common.error'), 'error'); }
    };

    const resetRiskForm = () => {
        setShowForm(false); setEditingId(null);
        setForm({ title: '', description: '', probability: '0.5', impact: '0.5', status: 'identified', mitigation_plan: '', owner_id: '', due_date: '' });
    };

    const riskColor = (score) => {
        if (score >= 0.6) return '#dc3545';
        if (score >= 0.3) return '#ffc107';
        return '#28a745';
    };

    const riskStatuses = { identified: t('project_risks.identified', 'مُحدد'), mitigating: t('project_risks.mitigating', 'قيد المعالجة'), resolved: t('project_risks.resolved', 'تم الحل'), accepted: t('project_risks.accepted', 'مقبول') };
    const depTypes = { FS: t('project_risks.fs', 'نهاية–بداية'), SS: t('project_risks.ss', 'بداية–بداية'), FF: t('project_risks.ff', 'نهاية–نهاية'), SF: t('project_risks.sf', 'بداية–نهاية') };

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="d-flex align-items-center justify-content-between w-100">
                    <div>
                        <h1 className="workspace-title">
                            <AlertTriangle size={24} className="me-2" />
                            {t('project_risks.title', 'المخاطر وتبعيات المهام')}
                        </h1>
                        <p className="workspace-subtitle">
                            {t('project_risks.subtitle', 'سجل المخاطر وإدارة تبعيات المهام')}
                        </p>
                    </div>
                </div>
            </div>

            {/* Project Selector */}
            <div className="d-flex gap-3 mb-4 align-items-center">
                <label className="form-label mb-0" style={{ whiteSpace: 'nowrap' }}>{t('project_risks.project', 'المشروع') + ':'}</label>
                <select className="form-input" style={{ maxWidth: 400 }} value={selectedProject}
                    onChange={e => setSelectedProject(e.target.value)}>
                    {projects.map(p => <option key={p.id} value={p.id}>{p.project_name}</option>)}
                </select>
            </div>

            {/* Metrics */}
            <div className="metrics-grid mb-4">
                <div className="metric-card">
                    <div className="metric-icon" style={{ background: '#fce4ec' }}><AlertTriangle size={22} color="#c62828" /></div>
                    <div className="metric-info">
                        <span className="metric-value">{risks.filter(r => new Decimal(r.risk_score || '0').gte('0.6')).length}</span>
                        <span className="metric-label">{t('project_risks.high_risks', 'مخاطر عالية')}</span>
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-icon" style={{ background: '#fff3e0' }}><AlertTriangle size={22} color="#ef6c00" /></div>
                    <div className="metric-info">
                        <span className="metric-value">{risks.length}</span>
                        <span className="metric-label">{t('project_risks.total_risks', 'إجمالي المخاطر')}</span>
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-icon" style={{ background: '#e3f2fd' }}><GitBranch size={22} color="#1565c0" /></div>
                    <div className="metric-info">
                        <span className="metric-value">{dependencies.length}</span>
                        <span className="metric-label">{t('project_risks.dependencies', 'التبعيات')}</span>
                    </div>
                </div>
            </div>

            {/* Tabs */}
            <div className="tabs mb-3">
                <button className={`tab ${activeTab === 'risks' ? 'active' : ''}`} onClick={() => setActiveTab('risks')}>
                    <AlertTriangle size={16} /> <span className="ms-1">{t('project_risks.risk_register', 'سجل المخاطر')}</span>
                </button>
                <button className={`tab ${activeTab === 'deps' ? 'active' : ''}`} onClick={() => setActiveTab('deps')}>
                    <Link2 size={16} /> <span className="ms-1">{t('project_risks.task_dependencies', 'تبعيات المهام')}</span>
                </button>
            </div>

            {/* Add buttons */}
            <div className="mb-3">
                {activeTab === 'risks' ? (
                    <button className="btn btn-primary" onClick={() => { resetRiskForm(); setShowForm(true); }}>
                        <Plus size={16} className="me-1" /> {t('project_risks.add_risk', 'إضافة خطر')}
                    </button>
                ) : (
                    <button className="btn btn-primary" onClick={() => setShowDepForm(true)}>
                        <Plus size={16} className="me-1" /> {t('project_risks.add_dependency', 'إضافة تبعية')}
                    </button>
                )}
            </div>

            {/* Risk Form */}
            {showForm && activeTab === 'risks' && (
                <div className="modal-overlay">
                    <div className="modal-content" style={{ maxWidth: '880px', width: '92%' }}>
                        <div className="modal-header">
                            <h2 className="modal-title">{editingId ? t('project_risks.edit_risk', 'تعديل الخطر') : t('project_risks.new_risk', 'خطر جديد')}</h2>
                            <button type="button" className="btn-icon" onClick={resetRiskForm}>✕</button>
                        </div>
                        <form onSubmit={handleRiskSubmit}>
                            <div className="modal-body">
                                <div className="row g-3">
                                    <div className="col-md-6">
                                        <div className="form-group">
                                            <label className="form-label">{t('common.title', 'العنوان')} *</label>
                                            <input className="form-input" required value={form.title}
                                                onChange={e => setForm(p => ({ ...p, title: e.target.value }))} />
                                        </div>
                                    </div>
                                    <div className="col-md-3">
                                        <div className="form-group">
                                            <label className="form-label">{t('project_risks.probability', 'الاحتمالية')} (0-1)</label>
                                            <input className="form-input" type="number" step="0.1" min="0" max="1" value={form.probability}
                                                onChange={e => setForm(p => ({ ...p, probability: e.target.value }))} />
                                        </div>
                                    </div>
                                    <div className="col-md-3">
                                        <div className="form-group">
                                            <label className="form-label">{t('project_risks.impact', 'التأثير')} (0-1)</label>
                                            <input className="form-input" type="number" step="0.1" min="0" max="1" value={form.impact}
                                                onChange={e => setForm(p => ({ ...p, impact: e.target.value }))} />
                                        </div>
                                    </div>
                                    <div className="col-md-3">
                                        <div className="form-group">
                                            <label className="form-label">{t('project_risks.risk_score', 'درجة الخطر')}</label>
                                            <div className="form-input" style={{ background: riskColor(new Decimal(form.probability || '0').times(new Decimal(form.impact || '0')).toNumber()), color: '#fff', textAlign: 'center', fontWeight: 700 }}>
                                                {formatNumber(new Decimal(form.probability || '0').times(new Decimal(form.impact || '0')).toString())}
                                            </div>
                                        </div>
                                    </div>
                                    <div className="col-md-3">
                                        <div className="form-group">
                                            <label className="form-label">{t('project_risks.status', 'الحالة')}</label>
                                            <select className="form-select" value={form.status}
                                                onChange={e => setForm(p => ({ ...p, status: e.target.value }))}>
                                                {Object.entries(riskStatuses).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                                            </select>
                                        </div>
                                    </div>
                                    <div className="col-md-3">
                                        <div className="form-group">
                                            <label className="form-label">{t('project_risks.due_date', 'تاريخ الاستحقاق')}</label>
                                            <DateInput className="form-input" value={form.due_date}
                                                onChange={e => setForm(p => ({ ...p, due_date: e.target.value }))} />
                                        </div>
                                    </div>
                                    <div className="col-md-12">
                                        <div className="form-group" style={{ marginBottom: 0 }}>
                                            <label className="form-label">{t('project_risks.mitigation_plan', 'خطة التخفيف')}</label>
                                            <textarea className="form-input" rows={2} value={form.mitigation_plan}
                                                onChange={e => setForm(p => ({ ...p, mitigation_plan: e.target.value }))} />
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <div className="modal-footer">
                                <button type="button" className="btn btn-secondary" onClick={resetRiskForm}>{t('common.cancel', 'إلغاء')}</button>
                                <button type="submit" className="btn btn-primary">{t('common.save', 'حفظ')}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* Dependency Form */}
            {showDepForm && activeTab === 'deps' && (
                <div className="section-card mb-4">
                    <h4 className="mb-3">{t('project_risks.new_dependency', 'تبعية جديدة')}</h4>
                    <form onSubmit={handleDepSubmit}>
                        <div className="row g-3">
                            <div className="col-md-3">
                                <div className="form-group">
                                    <label className="form-label">{t('project_risks.task', 'المهمة')} *</label>
                                    <select className="form-input" required value={depForm.task_id}
                                        onChange={e => setDepForm(p => ({ ...p, task_id: e.target.value }))}>
                                        <option value="">{t('common.select', 'اختر')}</option>
                                        {tasks.map(t => <option key={t.id} value={t.id}>{t.task_name}</option>)}
                                    </select>
                                </div>
                            </div>
                            <div className="col-md-3">
                                <div className="form-group">
                                    <label className="form-label">{t('project_risks.depends_on', 'تعتمد على')} *</label>
                                    <select className="form-input" required value={depForm.depends_on_task_id}
                                        onChange={e => setDepForm(p => ({ ...p, depends_on_task_id: e.target.value }))}>
                                        <option value="">{t('common.select', 'اختر')}</option>
                                        {tasks.map(t => <option key={t.id} value={t.id}>{t.task_name}</option>)}
                                    </select>
                                </div>
                            </div>
                            <div className="col-md-3">
                                <div className="form-group">
                                    <label className="form-label">{t('project_risks.dependency_type', 'النوع')}</label>
                                    <select className="form-input" value={depForm.dependency_type}
                                        onChange={e => setDepForm(p => ({ ...p, dependency_type: e.target.value }))}>
                                        {Object.entries(depTypes).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                                    </select>
                                </div>
                            </div>
                            <div className="col-md-3">
                                <div className="form-group">
                                    <label className="form-label">{t('project_risks.lag_days', 'أيام التأخير')}</label>
                                    <input className="form-input" type="number" value={depForm.lag_days}
                                        onChange={e => setDepForm(p => ({ ...p, lag_days: e.target.value }))} />
                                </div>
                            </div>
                        </div>
                        <div className="d-flex gap-2 mt-3">
                            <button type="submit" className="btn btn-primary"><Save size={16} className="me-1" /> {t('common.save', 'حفظ')}</button>
                            <button type="button" className="btn btn-outline-secondary" onClick={() => setShowDepForm(false)}><X size={16} className="me-1" /> {t('common.cancel', 'إلغاء')}</button>
                        </div>
                    </form>
                </div>
            )}

            {/* Tables */}
            <div className="section-card">
                {loading ? (
                    <PageLoading />
                ) : activeTab === 'risks' ? (
                    <div className="data-table-container">
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th>{t('common.title', 'العنوان')}</th>
                                    <th>{t('project_risks.probability', 'الاحتمالية')}</th>
                                    <th>{t('project_risks.impact', 'التأثير')}</th>
                                    <th>{t('project_risks.risk_score', 'الدرجة')}</th>
                                    <th>{t('project_risks.status', 'الحالة')}</th>
                                    <th>{t('project_risks.mitigation', 'التخفيف')}</th>
                                    <th>{t('project_risks.due', 'الاستحقاق')}</th>
                                    <th></th>
                                </tr>
                            </thead>
                            <tbody>
                                {risks.length === 0 ? (
                                    <tr><td colSpan={8} className="text-center p-4">{t('project_risks.no_risks', 'لا توجد مخاطر مسجلة')}</td></tr>
                                ) : risks.map(r => (
                                    <tr key={r.id}>
                                        <td><strong>{r.title}</strong><br /><small className="text-muted">{r.description}</small></td>
                                        <td>{formatNumber(r.probability || '0')}</td>
                                        <td>{formatNumber(r.impact || '0')}</td>
                                        <td>
                                            <span className="badge" style={{ background: riskColor(new Decimal(r.risk_score || '0').toNumber()), color: '#fff', fontSize: '0.85rem' }}>
                                                {formatNumber(r.risk_score || '0')}
                                            </span>
                                        </td>
                                        <td><span className="badge bg-secondary">{riskStatuses[r.status] || r.status}</span></td>
                                        <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.mitigation_plan || '—'}</td>
                                        <td>{r.due_date ? new Date(r.due_date).toLocaleDateString() : '—'}</td>
                                        <td>
                                            <div className="d-flex gap-1">
                                                <button className="btn btn-sm btn-outline-primary" onClick={() => {
                                                    setEditingId(r.id);
                                                    setForm({ title: r.title, description: r.description || '', probability: r.probability, impact: r.impact, status: r.status, mitigation_plan: r.mitigation_plan || '', owner_id: r.owner_id || '', due_date: r.due_date || '' });
                                                    setShowForm(true);
                                                }}><Edit3 size={14} /></button>
                                                <button className="btn btn-sm btn-outline-danger" onClick={() => handleDeleteRisk(r.id)}><Trash2 size={14} /></button>
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                ) : (
                    <div className="data-table-container">
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th>{t('project_risks.task', 'المهمة')}</th>
                                    <th>{t('project_risks.depends_on', 'تعتمد على')}</th>
                                    <th>{t('project_risks.type', 'النوع')}</th>
                                    <th>{t('project_risks.lag', 'التأخير')}</th>
                                    <th></th>
                                </tr>
                            </thead>
                            <tbody>
                                {dependencies.length === 0 ? (
                                    <tr><td colSpan={5} className="text-center p-4">{t('project_risks.no_dependencies', 'لا توجد تبعيات')}</td></tr>
                                ) : dependencies.map(d => (
                                    <tr key={d.id}>
                                        <td>{d.task_name || `#${d.task_id}`}</td>
                                        <td>{d.depends_on_name || `#${d.depends_on_task_id}`}</td>
                                        <td><span className="badge bg-info">{depTypes[d.dependency_type] || d.dependency_type}</span></td>
                                        <td>{d.lag_days || 0} {t('project_risks.days', 'يوم')}</td>
                                        <td>
                                            <button className="btn btn-sm btn-outline-danger" onClick={() => handleDeleteDep(d.id)}>
                                                <Trash2 size={14} />
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>
        </div>
    );
};

export default ProjectRisks;
