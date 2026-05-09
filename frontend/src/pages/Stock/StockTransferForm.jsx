import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { inventoryAPI } from '../../utils/api';

import { useBranch } from '../../context/BranchContext';
import { useToast } from '../../context/ToastContext';
import BackButton from '../../components/common/BackButton';
import FormField from '../../components/common/FormField';

const StockTransferForm = () => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const { currentBranch } = useBranch();
    const { showToast } = useToast();
    const [loading, setLoading] = useState(false);
    const [initialLoad, setInitialLoad] = useState(true);
    const [warehouses, setWarehouses] = useState([]);
    const [sourceStock, setSourceStock] = useState([]);

    const [formData, setFormData] = useState({
        source_warehouse_id: '',
        destination_warehouse_id: '',
        items: [{ product_id: '', quantity: 1 }],
        notes: ''
    });

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchInitialData();
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch]);

    const fetchInitialData = async () => {
        try {
            const params = currentBranch?.id ? { branch_id: currentBranch.id } : {};
            const whRes = await inventoryAPI.listWarehouses(params);
            setWarehouses(whRes.data);
        } catch (error) {
            console.error("Error fetching data:", error);
        } finally {
            setInitialLoad(false);
        }
    };

    useEffect(() => {
        if (formData.source_warehouse_id) {
            fetchSourceStock(formData.source_warehouse_id);
            // Clear existing items if warehouse changes to prevent invalid transfers
            setFormData(prev => ({ ...prev, items: [{ product_id: '', quantity: 1 }] }));
        } else {
            setSourceStock([]);
        }
    }, [formData.source_warehouse_id]);

    const fetchSourceStock = async (warehouseId) => {
        try {
            setLoading(true);
            const res = await inventoryAPI.getWarehouseSpecificStock(warehouseId);
            setSourceStock(res.data);
        } catch (error) {
            console.error("Error fetching source stock:", error);
        } finally {
            setLoading(false);
        }
    };

    const handleItemChange = (index, field, value) => {
        const newItems = formData.items.map((item, i) => {
            if (i === index) return { ...item, [field]: value };
            return item;
        });
        setFormData({ ...formData, items: newItems });
    };

    const addItem = () => {
        setFormData({
            ...formData,
            items: [...formData.items, { product_id: '', quantity: 1 }]
        });
    };

    const removeItem = (index) => {
        if (formData.items.length === 1) return;
        setFormData({
            ...formData,
            items: formData.items.filter((_, i) => i !== index)
        });
    };

    const handleSubmit = async (e) => {
        e.preventDefault();

        if (formData.source_warehouse_id === formData.destination_warehouse_id) {
            showToast(t('stock.transfer.validation.source_dest_same'), 'error');
            return;
        }

        try {
            setLoading(true);
            const payload = {
                source_warehouse_id: parseInt(formData.source_warehouse_id),
                destination_warehouse_id: parseInt(formData.destination_warehouse_id),
                items: formData.items.map(item => ({
                    product_id: parseInt(item.product_id),
                    quantity: String(item.quantity)
                })),
                notes: formData.notes
            };

            await inventoryAPI.transferStock(payload);
            showToast(t('stock.transfer.validation.success'), 'success');
            navigate('/stock'); // Or wherever appropriate
        } catch (error) {
            showToast(t('stock.transfer.validation.error') + (error.response?.data?.detail || error.message), 'error');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">🚚 {t('stock.transfer.title')}</h1>
                    <p className="workspace-subtitle">{t('stock.transfer.subtitle')}</p>
                </div>
            </div>

            <div className="card" style={{ maxWidth: '800px', margin: '0 auto' }}>
                <form onSubmit={handleSubmit}>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
                        <FormField label={t('stock.transfer.from_warehouse')}>
                            <select
                                className="form-input"
                                required
                                value={formData.source_warehouse_id}
                                onChange={e => setFormData({ ...formData, source_warehouse_id: e.target.value })}
                            >
                                <option value="">{t('stock.transfer.select_warehouse')}</option>
                                {warehouses.map(w => (
                                    <option key={w.id} value={w.id}>{w.name}</option>
                                ))}
                            </select>
                        </FormField>

                        <FormField label={t('stock.transfer.to_warehouse')}>
                            <select
                                className="form-input"
                                required
                                value={formData.destination_warehouse_id}
                                onChange={e => setFormData({ ...formData, destination_warehouse_id: e.target.value })}
                            >
                                <option value="">{t('stock.transfer.select_warehouse')}</option>
                                {warehouses.map(w => (
                                    <option key={w.id} value={w.id}>{w.name}</option>
                                ))}
                            </select>
                        </FormField>
                    </div>

                    <div className="mb-6">
                        <div className="flex justify-between items-center mb-2">
                            <label className="form-label">{t('stock.transfer.items')}</label>
                            <button type="button" onClick={addItem} className="text-primary text-sm font-bold">{t('stock.transfer.add_item')}</button>
                        </div>

                        {formData.items.map((item, index) => (
                            <div key={index} className="flex gap-4 mb-3 items-end">
                                <div style={{ flex: 3 }}>
                                    <select
                                        className="form-input"
                                        required
                                        value={item.product_id}
                                        onChange={e => handleItemChange(index, 'product_id', e.target.value)}
                                    >
                                        <option value="">{t('stock.transfer.select_product')}</option>
                                        {sourceStock.map(p => (
                                            <option key={p.id} value={p.id}>{p.product_name} ({t('stock.transfer.table.available')}: {p.quantity} {p.unit_name})</option>
                                        ))}
                                    </select>
                                </div>
                                <div style={{ flex: 1 }}>
                                    <input
                                        type="number"
                                        className="form-input"
                                        placeholder={t('stock.transfer.quantity')}
                                        min="0.01"
                                        step="0.01"
                                        required
                                        value={item.quantity}
                                        onChange={e => handleItemChange(index, 'quantity', e.target.value)}
                                    />
                                </div>
                                <button
                                    type="button"
                                    onClick={() => removeItem(index)}
                                    className="btn btn-secondary text-red-500"
                                    style={{ height: '42px' }}
                                >
                                    ✕
                                </button>
                            </div>
                        ))}
                    </div>

                    <FormField label={t('stock.transfer.notes')} className="mb-6">
                        <textarea
                            className="form-input"
                            rows="2"
                            value={formData.notes}
                            onChange={e => setFormData({ ...formData, notes: e.target.value })}
                        ></textarea>
                    </FormField>

                    <div className="flex justify-end gap-4">
                        <button type="button" className="btn btn-secondary" onClick={() => navigate('/stock')}>{t('stock.transfer.cancel')}</button>
                        <button type="submit" className="btn btn-primary" disabled={loading}>
                            {loading ? t('stock.transfer.confirming') : t('stock.transfer.confirm')}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
};

export default StockTransferForm;
