import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import { Plus, Save, Trash2, Info, Clock, ChevronUp, ChevronDown } from 'lucide-react';
import api from '../../utils/api';
import { useToast } from '../../context/ToastContext';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

const WorkflowEditor = () => {
    const { t, i18n } = useTranslation();
    const navigate = useNavigate();
    const { id } = useParams(); // If present, we are editing
    const { showToast } = useToast();
    const isRTL = i18n.language === 'ar';

    const [loading, setLoading] = useState(false);
    const [roles, setRoles] = useState([]);
    const [documentTypes, setDocumentTypes] = useState([]);

    // Form State
    const [formData, setFormData] = useState({
        name: '',
        document_type: '',
        description: '',
        min_amount: '',
        max_amount: '',
        is_active: true,
        steps: [
            { step: 1, approver_role: '', label: '' }
        ]
    });

    useEffect(() => {
        loadInitialData();
    }, [id]);

    const loadInitialData = async () => {
        setLoading(true);
        try {
            // Parallel fetch for dependencies
            const [rolesRes, docTypesRes] = await Promise.all([
                api.get('/roles/'),
                api.get('/approvals/document-types')
            ]);

            setRoles(rolesRes.data || []);
            setDocumentTypes(docTypesRes.data || []);

            // If editing, fetch workflow
            if (id) {
                const workflowRes = await api.get(`/approvals/workflows/${id}`);
                const wf = workflowRes.data;

                // Parse potential JSON fields if they come as strings
                let conditions = wf.conditions;
                if (typeof conditions === 'string') conditions = JSON.parse(conditions);

                let steps = wf.steps;
                if (typeof steps === 'string') steps = JSON.parse(steps);

                setFormData({
                    name: wf.name,
                    document_type: wf.document_type,
                    description: wf.description || '',
                    min_amount: conditions?.min_amount || '',
                    max_amount: conditions?.max_amount || '',
                    is_active: wf.is_active,
                    steps: steps || []
                });
            }
        } catch (error) {
            console.error("Failed to load data", error);
            showToast(t('common.error_loading_data'), 'error');
        } finally {
            setLoading(false);
        }
    };

    const handleChange = (e) => {
        const { name, value, type, checked } = e.target;
        setFormData(prev => ({
            ...prev,
            [name]: type === 'checkbox' ? checked : value
        }));
    };

    const handleStepChange = (index, field, value) => {
        const newSteps = [...formData.steps];
        newSteps[index] = { ...newSteps[index], [field]: value };
        setFormData(prev => ({ ...prev, steps: newSteps }));
    };

    const addStep = () => {
        setFormData(prev => ({
            ...prev,
            steps: [
                ...prev.steps,
                { step: prev.steps.length + 1, approver_role: '', label: '' }
            ]
        }));
    };

    const handleMoveUp = (index) => {
        if (index === 0) return;
        const newSteps = [...formData.steps];
        [newSteps[index - 1], newSteps[index]] = [newSteps[index], newSteps[index - 1]];
        newSteps.forEach((s, i) => s.step = i + 1);
        setFormData(prev => ({ ...prev, steps: newSteps }));
    };

    const handleMoveDown = (index) => {
        if (index === formData.steps.length - 1) return;
        const newSteps = [...formData.steps];
        [newSteps[index], newSteps[index + 1]] = [newSteps[index + 1], newSteps[index]];
        newSteps.forEach((s, i) => s.step = i + 1);
        setFormData(prev => ({ ...prev, steps: newSteps }));
    };

    const removeStep = (index) => {
        if (formData.steps.length <= 1) {
            showToast(t('approvals.workflow_min_steps'), "warning");
            return;
        }
        const newSteps = formData.steps.filter((_, i) => i !== index).map((step, i) => ({
            ...step,
            step: i + 1 // Re-index steps
        }));
        setFormData(prev => ({ ...prev, steps: newSteps }));
    };

    const handleSubmit = async (e) => {
        if (e) e.preventDefault();

        // Validation
        if (!formData.name || !formData.document_type) {
            showToast(t('common.fill_required'), "error");
            return;
        }

        for (const step of formData.steps) {
            if (!step.approver_role) {
                showToast(`${t('approvals.approver_role')} ${t('common.required')} (Step ${step.step})`, "error");
                return;
            }
        }

        // Prepare payload — wrap amount fields into conditions object
        const payload = {
            name: formData.name,
            document_type: formData.document_type,
            description: formData.description,
            conditions: {
                min_amount: formData.min_amount || null,
                max_amount: formData.max_amount || null,
            },
            is_active: formData.is_active,
            steps: formData.steps
        };

        setLoading(true);
        try {
            if (id) {
                await api.put(`/approvals/workflows/${id}`, payload);
                showToast(t('common.success_update'), "success");
            } else {
                await api.post('/approvals/workflows', payload);
                showToast(t('common.success_add'), "success");
            }
            navigate('/approvals');
        } catch (error) {
            console.error("Submit error", error);
            showToast(error.response?.data?.detail || t('common.error_saving'), "error");
        } finally {
            setLoading(false);
        }
    };

    if (loading && !roles.length) {
        return (
            <div className="workspace flex justify-center items-center py-20">
                <PageLoading />
            </div>
        );
    }

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                        <BackButton />
                        <div>
                            <h1 className="workspace-title">
                                {id ? t('approvals.edit_workflow') : t('approvals.new_workflow')}
                            </h1>
                            <p className="workspace-subtitle">
                                {t('approvals.workflow_name')}: {formData.name || '...'}
                            </p>
                        </div>
                    </div>
                    <div style={{ display: 'flex', gap: '12px' }}>
                        <button
                            onClick={() => navigate('/approvals')}
                            className="btn btn-ghost"
                        >
                            {t('common.cancel')}
                        </button>
                        <button
                            onClick={handleSubmit}
                            className="btn btn-primary"
                            disabled={loading}
                        >
                            <Save size={18} style={{ [isRTL ? 'marginLeft' : 'marginRight']: '8px' }} />
                            {loading ? t('common.saving') : t('common.save')}
                        </button>
                    </div>
                </div>
            </div>

            <div className="workspace-content max-w-5xl">
                {/* General Settings Card */}
                <div className="card mb-6">
                    <div className="card-body p-5">
                        <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
                            <Info size={18} className="text-primary" />
                            {t('common.basic_info')}
                        </h3>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            <div className="form-group">
                                <label className="form-label">{t('approvals.workflow_name')} *</label>
                                <input
                                    type="text"
                                    name="name"
                                    className="form-input"
                                    value={formData.name}
                                    onChange={handleChange}
                                    required
                                    placeholder={t('approvals.workflow_name_placeholder')}
                                />
                            </div>

                            <div className="form-group">
                                <label className="form-label">{t('approvals.module')} *</label>
                                <select
                                    name="document_type"
                                    className="form-input"
                                    value={formData.document_type}
                                    onChange={handleChange}
                                    required
                                >
                                    <option value="">{t('approvals.select_document_type')}</option>
                                    {documentTypes.map(type => (
                                        <option key={type.value} value={type.value}>
                                            {isRTL ? (type.label_ar || type.label) : (type.label || type.label_ar)}
                                        </option>
                                    ))}
                                </select>
                            </div>

                            <div className="form-group md:col-span-2">
                                <label className="form-label">{t('common.description')}</label>
                                <textarea
                                    name="description"
                                    className="form-input h-20"
                                    value={formData.description}
                                    onChange={handleChange}
                                    placeholder={t('common.notes_placeholder')}
                                />
                            </div>

                            <div className="form-group">
                                <label className="form-label">{t('approvals.min_amount')} {t('approvals.optional')}</label>
                                <input
                                    type="number"
                                    name="min_amount"
                                    className="form-input"
                                    value={formData.min_amount}
                                    onChange={handleChange}
                                    step="0.01"
                                />
                            </div>

                            <div className="form-group">
                                <label className="form-label">{t('approvals.max_amount')} {t('approvals.optional')}</label>
                                <input
                                    type="number"
                                    name="max_amount"
                                    className="form-input"
                                    value={formData.max_amount}
                                    onChange={handleChange}
                                    step="0.01"
                                />
                            </div>

                            <div className="col-span-full">
                                <label className="flex items-center gap-3 cursor-pointer p-3 bg-base-200/30 rounded-lg hover:bg-base-200/50 transition-colors">
                                    <input
                                        type="checkbox"
                                        name="is_active"
                                        className="toggle toggle-primary toggle-sm"
                                        checked={formData.is_active}
                                        onChange={handleChange}
                                    />
                                    <span className="font-medium">{t('common.is_active')}</span>
                                </label>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Steps Card */}
                <div className="card">
                    <div className="card-body p-0">
                        <div className="p-5 border-b border-base-200 flex justify-between items-center">
                            <h3 className="text-lg font-bold flex items-center gap-2">
                                <Clock size={18} className="text-primary" />
                                {t('approvals.steps')}
                            </h3>
                            <button
                                type="button"
                                onClick={addStep}
                                className="btn btn-outline-primary btn-sm"
                            >
                                <Plus size={16} style={{ [isRTL ? 'marginLeft' : 'marginRight']: '4px' }} />
                                {t('approvals.add_step')}
                            </button>
                        </div>

                        <div className="data-table-container">
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th style={{ width: '60px' }}>#</th>
                                        <th>{t('approvals.approver_role')} *</th>
                                        <th>{t('approvals.step_label')} {t('approvals.optional')}</th>
                                         <th style={{ width: '130px' }}></th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {formData.steps.map((step, index) => (
                                        <tr key={index}>
                                            <td className="text-center font-bold opacity-40">{index + 1}</td>
                                            <td>
                                                <select
                                                    className="form-input"
                                                    style={{ border: 'none', background: 'transparent', padding: '0' }}
                                                    value={step.approver_role}
                                                    onChange={(e) => handleStepChange(index, 'approver_role', e.target.value)}
                                                    required
                                                >
                                                    <option value="">{t('common.select')}</option>
                                                    {roles.map(role => (
                                                        <option key={role.id} value={role.role_name}>
                                                            {isRTL ? (role.role_name_ar || role.role_name) : (role.role_name || role.role_name_ar)}
                                                        </option>
                                                    ))}
                                                </select>
                                            </td>
                                            <td>
                                                <input
                                                    type="text"
                                                    className="form-input"
                                                    style={{ border: 'none', background: 'transparent', padding: '0' }}
                                                    value={step.label}
                                                    onChange={(e) => handleStepChange(index, 'label', e.target.value)}
                                                    placeholder={t('approvals.step_name_placeholder')}
                                                />
                                            </td>
                                            <td className="text-center">
                                                <div className="d-flex" style={{ display: 'flex', gap: '2px', justifyContent: 'center' }}>
                                                    <button
                                                        type="button"
                                                        onClick={() => handleMoveUp(index)}
                                                        className="table-action-btn"
                                                        title={t('common.move_up', 'Move Up')}
                                                        disabled={index === 0}
                                                        style={{ opacity: index === 0 ? 0.3 : 1 }}
                                                    >
                                                        <ChevronUp size={16} />
                                                    </button>
                                                    <button
                                                        type="button"
                                                        onClick={() => handleMoveDown(index)}
                                                        className="table-action-btn"
                                                        title={t('common.move_down', 'Move Down')}
                                                        disabled={index === formData.steps.length - 1}
                                                        style={{ opacity: index === formData.steps.length - 1 ? 0.3 : 1 }}
                                                    >
                                                        <ChevronDown size={16} />
                                                    </button>
                                                    <button
                                                        type="button"
                                                        onClick={() => removeStep(index)}
                                                        className="table-action-btn"
                                                        style={{ color: 'var(--danger)' }}
                                                        title={t('common.delete')}
                                                        disabled={formData.steps.length === 1}
                                                    >
                                                        <Trash2 size={16} />
                                                    </button>
                                                </div>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>

                        {formData.steps.length === 0 && (
                            <div className="p-10 text-center opacity-50 italic">
                                {t('approvals.no_steps')}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};

export default WorkflowEditor;
