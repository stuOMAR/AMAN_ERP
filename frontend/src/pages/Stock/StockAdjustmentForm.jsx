import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Save, AlertCircle } from 'lucide-react';
import { inventoryAPI } from '../../utils/api';
import { useBranch } from '../../context/BranchContext';
import { useToast } from '../../context/ToastContext';
import BackButton from '../../components/common/BackButton';
import FormField from '../../components/common/FormField';

const StockAdjustmentForm = () => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const { currentBranch } = useBranch();
    const { showToast } = useToast();
    const [loading, setLoading] = useState(false);
    const [initialLoad, setInitialLoad] = useState(true);
    const [warehouses, setWarehouses] = useState([]);
    const [products, setProducts] = useState([]);
    const [formData, setFormData] = useState({
        warehouse_id: '',
        product_id: '',
        new_quantity: '',
        reason: 'Physical Count',
        notes: ''
    });
    const [error, setError] = useState('');

    useEffect(() => {
        const timer = setTimeout(() => {
            const loadData = async () => {
                try {
                    const whRes = await inventoryAPI.listWarehouses();
                    const prodRes = await inventoryAPI.listProducts();

                    setWarehouses(whRes.data || []);
                    setProducts(prodRes.data || []);

                    if (whRes.data && whRes.data.length > 0) {
                        setFormData(prev => ({ ...prev, warehouse_id: whRes.data[0].id }));
                    }
                } catch (err) {
                    showToast(t('stock.adjustments.form.validation.error_load'), 'error');
                } finally {
                    setInitialLoad(false);
                }
            };
            loadData();
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch]);

    const handleChange = (e) => {
        setFormData({ ...formData, [e.target.name]: e.target.value });
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!formData.warehouse_id || !formData.product_id || formData.new_quantity === '') {
            setError(t('common.fill_required'));
            return;
        }

        setLoading(true);
        setError('');

        try {
            await inventoryAPI.createAdjustment({
                warehouse_id: parseInt(formData.warehouse_id),
                product_id: parseInt(formData.product_id),
                new_quantity: String(formData.new_quantity),
                reason: formData.reason,
                notes: formData.notes,
                branch_id: currentBranch?.id
            });
            navigate('/stock/adjustments');
        } catch (err) {
            setError(err.response?.data?.detail || t('stock.adjustments.form.validation.error'));
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                        <BackButton />
                        <div>
                            <h1 className="workspace-title">{t('stock.adjustments.form.title')}</h1>
                            <p className="workspace-subtitle">{t('stock.adjustments.form.subtitle')}</p>
                        </div>
                    </div>
                    <button onClick={handleSubmit} className="btn btn-primary" disabled={loading}>
                        <Save size={18} style={{ marginLeft: '8px' }} />
                        {loading ? t('common.saving') : t('common.save')}
                    </button>
                </div>
            </div>

            <div className="workspace-content" style={{ maxWidth: '800px' }}>
                {error && (
                    <div className="alert alert-error animate-fade-in" style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '24px' }}>
                        <AlertCircle size={20} />
                        {error}
                    </div>
                )}

                <div className="card" style={{ padding: '32px' }}>
                    <form onSubmit={handleSubmit}>
                        <div className="row">
                            <FormField label={t('stock.adjustments.form.warehouse')} required className="col-md-6 mb-4">
                                <select
                                    name="warehouse_id"
                                    value={formData.warehouse_id}
                                    onChange={handleChange}
                                    className="form-input"
                                    required
                                >
                                    <option value="">{t('stock.adjustments.form.select_warehouse')}</option>
                                    {warehouses.map(w => (
                                        <option key={w.id} value={w.id}>{w.name}</option>
                                    ))}
                                </select>
                            </FormField>

                            <FormField label={t('stock.adjustments.form.product')} required className="col-md-6 mb-4">
                                <select
                                    name="product_id"
                                    value={formData.product_id}
                                    onChange={handleChange}
                                    className="form-input"
                                    required
                                >
                                    <option value="">{t('stock.adjustments.form.select_product')}</option>
                                    {products.map(p => (
                                        <option key={p.id} value={p.id}>{p.product_name} {p.item_code ? `(${p.item_code})` : ''}</option>
                                    ))}
                                </select>
                            </FormField>
                        </div>

                        <div className="mb-4">
                            <FormField label={t('stock.adjustments.form.actual_quantity')} required>
                                <input
                                    type="number"
                                    step="0.01"
                                    name="new_quantity"
                                    value={formData.new_quantity}
                                    onChange={handleChange}
                                    className="form-input"
                                    style={{ fontSize: '18px', fontWeight: 'bold', background: '#f0f7ff', borderColor: '#bfdbfe' }}
                                    placeholder={t('stock.adjustments.form.quantity_placeholder')}
                                    required
                                />
                            </FormField>
                            <div className="mt-2 text-muted" style={{ fontSize: '12px' }}>
                                <AlertCircle size={12} style={{ display: 'inline', marginLeft: '4px' }} />
                                {t('stock.adjustments.form.quantity_help')}
                            </div>
                        </div>

                        <div className="row">
                            <FormField label={t('stock.adjustments.form.reason')} className="col-md-6 mb-4">
                                <select name="reason" value={formData.reason} onChange={handleChange} className="form-input">
                                    <option value="Physical Count">{t('stock.adjustments.reasons.physical_count')}</option>
                                    <option value="Damaged">{t('stock.adjustments.reasons.damaged')}</option>
                                    <option value="Theft">{t('stock.adjustments.reasons.theft')}</option>
                                    <option value="Other">{t('stock.adjustments.reasons.other')}</option>
                                </select>
                            </FormField>
                        </div>

                        <FormField label={t('stock.adjustments.form.notes')} className="mb-4">
                            <textarea
                                name="notes"
                                value={formData.notes}
                                onChange={handleChange}
                                className="form-input"
                                style={{ height: '100px' }}
                                placeholder={t('common.notes_placeholder')}
                            />
                        </FormField>

                        <div className="mt-6 pt-4 border-top d-flex justify-content-end gap-3">
                            <button
                                type="button"
                                onClick={() => navigate('/stock/adjustments')}
                                className="btn"
                                style={{ background: 'var(--bg-hover)' }}
                            >
                                {t('common.cancel')}
                            </button>
                            <button
                                type="submit"
                                disabled={loading}
                                className="btn btn-primary"
                                style={{ minWidth: '120px' }}
                            >
                                {loading ? t('common.saving') : t('common.save')}
                            </button>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    );
};

export default StockAdjustmentForm;
