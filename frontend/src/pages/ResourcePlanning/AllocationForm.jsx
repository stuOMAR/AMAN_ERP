import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import { resourceAPI, projectsAPI } from '../../utils/api';
import '../../index.css';
import '../../components/ModuleStyles.css';
import BackButton from '../../components/common/BackButton';
import FormField from '../../components/common/FormField';
import DateInput from '../../components/common/DateInput';

const AllocationForm = () => {
    const { t, i18n } = useTranslation();
    const isRTL = i18n.language === 'ar';
    const navigate = useNavigate();
    const { id } = useParams(); // edit mode if id present
    const isEdit = Boolean(id);

    const [form, setForm] = useState({
        employee_id: '',
        project_id: '',
        role: '',
        allocation_percent: 50,
        start_date: new Date().toISOString().slice(0, 10),
        end_date: '',
    });
    const [employees, setEmployees] = useState([]);
    const [projects, setProjects] = useState([]);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState('');
    const [warning, setWarning] = useState('');

    useEffect(() => {
        projectsAPI.list()
            .then(res => setProjects(Array.isArray(res.data) ? res.data : res.data?.projects || []))
            .catch(() => {});

        resourceAPI.getAvailability({})
            .then(res => {
                const emps = res.data?.employees || [];
                setEmployees(emps.map(e => ({ id: e.employee_id, name: e.employee_name })));
            })
            .catch(() => {});

        if (isEdit) {
            // fetch existing allocation — from project resources or by id
            // The API doesn't have a single get by id; we load from availability
        }
    }, [isEdit, id]);

    const handleChange = (field, value) => {
        setForm(prev => ({ ...prev, [field]: value }));
        setError('');
        setWarning('');
    };

    const validate = () => {
        if (!form.employee_id) return t('resource.employee_required');
        if (!form.project_id) return t('resource.project_required');
        if (!form.allocation_percent || form.allocation_percent <= 0 || form.allocation_percent > 100) {
            return t('resource.percent_range');
        }
        if (!form.start_date) return t('resource.start_date_required');
        if (!form.end_date) return t('resource.end_date_required');
        if (form.start_date > form.end_date) return t('resource.date_order');
        return null;
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        const err = validate();
        if (err) { setError(err); return; }

        setSaving(true);
        setError('');
        setWarning('');
        try {
            const payload = {
                employee_id: parseInt(form.employee_id),
                project_id: parseInt(form.project_id),
                role: form.role || null,
                allocation_percent: form.allocation_percent,
                start_date: form.start_date,
                end_date: form.end_date,
            };

            let res;
            if (isEdit) {
                res = await resourceAPI.updateAllocation(id, payload);
            } else {
                res = await resourceAPI.allocate(payload);
            }

            if (res.data?.warning_message) {
                setWarning(res.data.warning_message);
            }

            navigate('/projects/resources/availability');
        } catch (err2) {
            setError(err2.response?.data?.detail || t('common.error'));
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="module-container" dir={isRTL ? 'rtl' : 'ltr'}>
            <BackButton />
            <div className="module-header">
                <h1>{isEdit ? t('resource.edit_allocation') : t('resource.new_allocation')}</h1>
            </div>

            <form onSubmit={handleSubmit} className="form-card" style={{ maxWidth: 600 }}>
                {error && <div className="alert alert-danger">{error}</div>}
                {warning && <div className="alert alert-warning">{warning}</div>}

                <FormField label={t('resource.employee')} required>
                    <select className="form-control" value={form.employee_id}
                            onChange={e => handleChange('employee_id', e.target.value)}>
                        <option value="">{t('common.select')}</option>
                        {employees.map(emp => (
                            <option key={emp.id} value={emp.id}>{emp.name}</option>
                        ))}
                    </select>
                </FormField>

                <FormField label={t('resource.project')} required>
                    <select className="form-control" value={form.project_id}
                            onChange={e => handleChange('project_id', e.target.value)}>
                        <option value="">{t('common.select')}</option>
                        {projects.map(p => (
                            <option key={p.id} value={p.id}>{p.name || p.project_name}</option>
                        ))}
                    </select>
                </FormField>

                <FormField label={t('resource.role')}>
                    <input type="text" className="form-control" value={form.role}
                           onChange={e => handleChange('role', e.target.value)}
                           placeholder={t('resource.role_placeholder')} maxLength={50} />
                </FormField>

                <FormField label={t('resource.allocation_percent')} required>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <input type="range" min={5} max={100} step={5} value={form.allocation_percent}
                               onChange={e => handleChange('allocation_percent', e.target.value)}
                               style={{ flex: 1 }} />
                        <input type="number" className="form-control" value={form.allocation_percent}
                               onChange={e => handleChange('allocation_percent', e.target.value)}
                               min={1} max={100} style={{ width: 80 }} />
                        <span>%</span>
                    </div>
                </FormField>

                <div style={{ display: 'flex', gap: 16 }}>
                    <FormField label={t('resource.start_date')} required style={{ flex: 1 }}>
                        <DateInput className="form-control" value={form.start_date}
                               onChange={e => handleChange('start_date', e.target.value)} />
                    </FormField>
                    <FormField label={t('resource.end_date')} required style={{ flex: 1 }}>
                        <DateInput className="form-control" value={form.end_date}
                               onChange={e => handleChange('end_date', e.target.value)} />
                    </FormField>
                </div>

                <div style={{ display: 'flex', gap: 12, marginTop: 16 }}>
                    <button type="submit" className="btn btn-primary" disabled={saving}>
                        {saving ? t('common.saving') : isEdit ? t('common.update') : t('resource.allocate')}
                    </button>
                    <button type="button" className="btn btn-secondary"
                            onClick={() => navigate('/projects/resources/availability')}>
                        {t('common.cancel')}
                    </button>
                </div>
            </form>
        </div>
    );
};

export default AllocationForm;
