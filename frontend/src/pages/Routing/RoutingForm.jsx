import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams, useNavigate } from 'react-router-dom';
import { routingAPI, manufacturingAPI, inventoryAPI } from '../../utils/api';
import { Plus, Trash2, ArrowLeft, Save } from 'lucide-react';
import '../../index.css';
import '../../components/ModuleStyles.css';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

const RoutingForm = () => {
    const { t, i18n } = useTranslation();
    const isRTL = i18n.language === 'ar';
    const { id } = useParams();
    const navigate = useNavigate();
    const isEdit = id && id !== 'new';

    const [loading, setLoading] = useState(!!isEdit);
    const [saving, setSaving] = useState(false);
    const [products, setProducts] = useState([]);
    const [workCenters, setWorkCenters] = useState([]);
    const [message, setMessage] = useState('');
    const [error, setError] = useState('');

    const [form, setForm] = useState({
        name: '',
        product_id: '',
        bom_id: '',
        is_default: false,
        is_active: true,
        description: '',
        operations: [],
    });

    // Estimate
    const [estimate, setEstimate] = useState(null);
    const [estQty, setEstQty] = useState(1);

    useEffect(() => {
        const loadRefs = async () => {
            try {
                const [pRes, wcRes] = await Promise.all([
                    inventoryAPI.listProducts({ limit: 1000 }),
                    manufacturingAPI.listWorkCenters(),
                ]);
                const productsData = pRes?.data;
                const workCentersData = wcRes?.data;
                setProducts(productsData?.products || productsData || []);
                setWorkCenters(workCentersData || []);
            } catch (e) { console.error(e); }
        };
        loadRefs();

        if (isEdit) {
            routingAPI.get(id)
                .then(res => {
                    const d = res.data;
                    setForm({
                        name: d.name || '',
                        product_id: d.product_id || '',
                        bom_id: d.bom_id || '',
                        is_default: d.is_default || false,
                        is_active: d.is_active !== false,
                        description: d.description || '',
                        operations: (d.operations || []).map(op => ({
                            sequence: op.sequence,
                            name: op.name || '',
                            work_center_id: op.work_center_id || '',
                            description: op.description || '',
                            setup_time: op.setup_time || 0,
                            cycle_time: op.cycle_time || 0,
                            labor_rate_per_hour: op.labor_rate_per_hour || 0,
                        })),
                    });
                })
                .catch(e => setError(e.response?.data?.detail || 'Load failed'))
                .finally(() => setLoading(false));
        }
    }, [id, isEdit]);

    const addOperation = () => {
        const maxSeq = form.operations.reduce((m, o) => Math.max(m, o.sequence), 0);
        setForm(prev => ({
            ...prev,
            operations: [...prev.operations, {
                sequence: maxSeq + 10,
                name: '',
                work_center_id: '',
                description: '',
                setup_time: 0,
                cycle_time: 0,
                labor_rate_per_hour: 0,
            }],
        }));
    };

    const removeOperation = (idx) => {
        setForm(prev => ({
            ...prev,
            operations: prev.operations.filter((_, i) => i !== idx),
        }));
    };

    const updateOp = (idx, field, value) => {
        setForm(prev => ({
            ...prev,
            operations: prev.operations.map((op, i) =>
                i === idx ? { ...op, [field]: value } : op
            ),
        }));
    };

    const handleSave = async () => {
        if (!form.name.trim()) { setError(t('routing.name_required')); return; }
        setSaving(true);
        setError('');
        setMessage('');
        try {
            const payload = {
                ...form,
                product_id: form.product_id || null,
                bom_id: form.bom_id || null,
                operations: form.operations.map(op => ({
                    ...op,
                    work_center_id: op.work_center_id || null,
                    setup_time: op.setup_time || '0',
                    cycle_time: op.cycle_time || '0',
                    labor_rate_per_hour: op.labor_rate_per_hour || '0',
                })),
            };
            if (isEdit) {
                await routingAPI.update(id, payload);
            } else {
                await routingAPI.create(payload);
            }
            setMessage(t('routing.saved'));
            setTimeout(() => navigate('/manufacturing/routing'), 1200);
        } catch (e) {
            setError(e.response?.data?.detail || t('routing.save_failed'));
        } finally {
            setSaving(false);
        }
    };

    const loadEstimate = async () => {
        if (!isEdit) return;
        try {
            const res = await routingAPI.getEstimate(id, estQty);
            setEstimate(res.data);
        } catch (e) { console.error(e); }
    };

    if (loading) return <div className="module-container"><PageLoading /></div>;

    return (
        <div className="module-container" dir={isRTL ? 'rtl' : 'ltr'}>
            <BackButton />
            <div className="module-header">
                <h1>{isEdit ? t('routing.edit_routing') : t('routing.new_routing')}</h1>
                <button className="btn btn-outline" onClick={() => navigate('/manufacturing/routing')}>
                    <ArrowLeft size={16} /> {t('routing.back_to_list')}
                </button>
            </div>

            {error && <div className="alert alert-danger" style={{ marginBottom: 16 }}>{error}</div>}
            {message && <div className="alert alert-info" style={{ marginBottom: 16 }}>{message}</div>}

            {/* Header */}
            <div className="form-card" style={{ marginBottom: 16 }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 16 }}>
                    <div className="form-group">
                        <label>{t('routing.name')} *</label>
                        <input className="form-control" value={form.name} onChange={e => setForm(p => ({ ...p, name: e.target.value }))} />
                    </div>
                    <div className="form-group">
                        <label>{t('routing.product')}</label>
                        <select className="form-control" value={form.product_id} onChange={e => setForm(p => ({ ...p, product_id: e.target.value }))}>
                            <option value="">{t('routing.select_product')}</option>
                            {products.map(p => <option key={p.id} value={p.id}>{p.product_name}</option>)}
                        </select>
                    </div>
                    <div className="form-group">
                        <label>{t('routing.description')}</label>
                        <input className="form-control" value={form.description} onChange={e => setForm(p => ({ ...p, description: e.target.value }))} />
                    </div>
                    <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
                        <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                            <input type="checkbox" checked={form.is_default} onChange={e => setForm(p => ({ ...p, is_default: e.target.checked }))} />
                            {t('routing.is_default')}
                        </label>
                        <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                            <input type="checkbox" checked={form.is_active} onChange={e => setForm(p => ({ ...p, is_active: e.target.checked }))} />
                            {t('common.active')}
                        </label>
                    </div>
                </div>
            </div>

            {/* Operations */}
            <div className="form-card" style={{ marginBottom: 16 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                    <h3>{t('routing.operations')}</h3>
                    <button className="btn btn-sm btn-primary" onClick={addOperation}>
                        <Plus size={14} /> {t('routing.add_operation')}
                    </button>
                </div>

                {form.operations.length === 0 ? (
                    <div className="empty-state" style={{ padding: 24 }}>{t('routing.no_operations')}</div>
                ) : (
                    <div className="data-table-wrapper">
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th style={{ width: 60 }}>{t('routing.seq')}</th>
                                    <th>{t('routing.op_name')}</th>
                                    <th>{t('routing.work_center')}</th>
                                    <th>{t('routing.description')}</th>
                                    <th style={{ width: 100 }}>{t('routing.setup_time')}</th>
                                    <th style={{ width: 100 }}>{t('routing.run_time')}</th>
                                    <th style={{ width: 110 }}>{t('routing.labor_rate')}</th>
                                    <th style={{ width: 50 }}></th>
                                </tr>
                            </thead>
                            <tbody>
                                {form.operations.map((op, idx) => (
                                    <tr key={idx}>
                                        <td>
                                            <input type="number" className="form-control" style={{ width: 60 }}
                                                value={op.sequence} onChange={e => updateOp(idx, 'sequence', parseInt(e.target.value) || 0)} />
                                        </td>
                                        <td>
                                            <input className="form-control" value={op.name}
                                                placeholder={t('routing.op_name_ph')}
                                                onChange={e => updateOp(idx, 'name', e.target.value)} />
                                        </td>
                                        <td>
                                            <select className="form-control" value={op.work_center_id}
                                                onChange={e => updateOp(idx, 'work_center_id', e.target.value)}>
                                                <option value="">-</option>
                                                {workCenters.map(wc => <option key={wc.id} value={wc.id}>{wc.name}</option>)}
                                            </select>
                                        </td>
                                        <td>
                                            <input className="form-control" value={op.description}
                                                onChange={e => updateOp(idx, 'description', e.target.value)} />
                                        </td>
                                        <td>
                                            <input type="number" className="form-control" step="0.01"
                                                value={op.setup_time} onChange={e => updateOp(idx, 'setup_time', e.target.value)} />
                                        </td>
                                        <td>
                                            <input type="number" className="form-control" step="0.01"
                                                value={op.cycle_time} onChange={e => updateOp(idx, 'cycle_time', e.target.value)} />
                                        </td>
                                        <td>
                                            <input type="number" className="form-control" step="0.01"
                                                value={op.labor_rate_per_hour} onChange={e => updateOp(idx, 'labor_rate_per_hour', e.target.value)} />
                                        </td>
                                        <td>
                                            <button className="btn btn-sm btn-danger" onClick={() => removeOperation(idx)}>
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

            {/* Estimate (edit-only) */}
            {isEdit && (
                <div className="form-card" style={{ marginBottom: 16 }}>
                    <h3>{t('routing.estimate')}</h3>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', marginBottom: 12 }}>
                        <div className="form-group" style={{ margin: 0 }}>
                            <label>{t('routing.quantity')}</label>
                            <input type="number" className="form-control" style={{ width: 120 }}
                                value={estQty} onChange={e => setEstQty(e.target.value)} />
                        </div>
                        <button className="btn btn-outline" onClick={loadEstimate}>{t('routing.calculate')}</button>
                    </div>
                    {estimate && (
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12 }}>
                            <div className="stat-card">
                                <div className="stat-label">{t('routing.setup_total')}</div>
                                <div className="stat-value">{estimate.total_setup_minutes} {t('routing.min')}</div>
                            </div>
                            <div className="stat-card">
                                <div className="stat-label">{t('routing.run_total')}</div>
                                <div className="stat-value">{estimate.total_run_minutes} {t('routing.min')}</div>
                            </div>
                            <div className="stat-card">
                                <div className="stat-label">{t('routing.total_time')}</div>
                                <div className="stat-value">{estimate.total_time_minutes} {t('routing.min')}</div>
                            </div>
                            <div className="stat-card">
                                <div className="stat-label">{t('routing.labor_cost')}</div>
                                <div className="stat-value">{estimate.total_labor_cost}</div>
                            </div>
                        </div>
                    )}
                </div>
            )}

            {/* Actions */}
            <div style={{ display: 'flex', gap: 8 }}>
                <button className="btn btn-primary" disabled={saving} onClick={handleSave}>
                    <Save size={16} /> {saving ? t('common.saving') : t('common.save')}
                </button>
                <button className="btn btn-outline" onClick={() => navigate('/manufacturing/routing')}>
                    {t('common.cancel')}
                </button>
            </div>
        </div>
    );
};

export default RoutingForm;
