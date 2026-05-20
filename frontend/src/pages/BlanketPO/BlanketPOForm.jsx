import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { purchasesAPI } from '../../utils/api';
import { getCurrency } from '../../utils/auth';
import { useToast } from '../../context/ToastContext';
import Decimal from 'decimal.js';
import { formatNumber } from '../../utils/format';
import DateInput from '../../components/common/DateInput';
import BackButton from '../../components/common/BackButton';
import '../../components/ModuleStyles.css';

const BlanketPOForm = () => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const { showToast } = useToast();
    const [suppliers, setSuppliers] = useState([]);
    const [submitting, setSubmitting] = useState(false);
    const [form, setForm] = useState({
        supplier_id: '',
        party_site_id: '',
        total_quantity: '',
        unit_price: '',
        valid_from: '',
        valid_to: '',
        currency: getCurrency() || 'SAR',
        notes: '',
    });

    useEffect(() => {
        const fetchSuppliers = async () => {
            try {
                const res = await purchasesAPI.listSuppliers({ limit: 500 });
                setSuppliers(res.data || []);
            } catch (err) {
                showToast(t('common.error'), 'error');
            }
        };
        fetchSuppliers();
    }, []);

    const totalAmount = (form.total_quantity && form.unit_price)
        ? new Decimal(form.total_quantity || '0').times(new Decimal(form.unit_price || '0'))
        : null;

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (submitting) return;
        if (form.valid_from && form.valid_to && new Date(form.valid_to) <= new Date(form.valid_from)) {
            showToast(t('blanket_po.date_range_error'), 'error');
            return;
        }
        setSubmitting(true);
        try {
            const payload = {
                supplier_id: parseInt(form.supplier_id),
                party_site_id: form.party_site_id ? parseInt(form.party_site_id) : null,
                total_quantity: String(form.total_quantity),
                unit_price: String(form.unit_price),
                valid_from: form.valid_from,
                valid_to: form.valid_to,
                currency: form.currency || getCurrency() || 'SAR',
                notes: form.notes || null,
            };
            const res = await purchasesAPI.createBlanketPO(payload);
            showToast(t('blanket_po.created_success'), 'success');
            navigate(`/buying/blanket-po/${res.data.id}`);
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error');
        } finally {
            setSubmitting(false);
        }
    };

    const set = (field, value) => setForm(prev => ({ ...prev, [field]: value }));

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <h1 className="workspace-title">{t('blanket_po.new')}</h1>
                <p className="workspace-subtitle">{t('blanket_po.form_subtitle')}</p>
            </div>

            <div className="card section-card">
                <form onSubmit={handleSubmit} className="p-4 space-y-4">
                    <div className="grid grid-cols-2 gap-4">
                        <div className="form-group">
                            <label className="form-label">{t('blanket_po.supplier')} *</label>
                            <select className="form-input" required value={form.supplier_id}
                                onChange={e => set('supplier_id', e.target.value)}>
                                <option value="">{t('blanket_po.select_supplier')}</option>
                                {suppliers.map(s => (
                                    <option key={s.id} value={s.id}>{s.name || s.supplier_name}{s.party_code ? ` (${s.party_code})` : ''}</option>
                                ))}
                            </select>
                        </div>
                        <div className="form-group">
                            <label className="form-label">{t('blanket_po.currency')}</label>
                            <select className="form-input" value={form.currency} onChange={e => set('currency', e.target.value)}>
                                <option value="SAR">SAR</option>
                                <option value="USD">USD</option>
                                <option value="EUR">EUR</option>
                            </select>
                        </div>
                    </div>

                    <div className="grid grid-cols-3 gap-4">
                        <div className="form-group">
                            <label className="form-label">{t('blanket_po.total_qty')} *</label>
                            <input type="number" step="0.01" min="0.01" className="form-input" required
                                value={form.total_quantity} onChange={e => set('total_quantity', e.target.value)} />
                        </div>
                        <div className="form-group">
                            <label className="form-label">{t('blanket_po.unit_price')} *</label>
                            <input type="number" step="0.01" min="0.01" className="form-input" required
                                value={form.unit_price} onChange={e => set('unit_price', e.target.value)} />
                        </div>
                        <div className="form-group">
                            <label className="form-label">{t('blanket_po.total_amount')}</label>
                            <input type="text" className="form-input" disabled
                                value={totalAmount && !totalAmount.isZero() ? formatNumber(totalAmount.toString()) : '—'} />
                        </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                        <div className="form-group">
                            <label className="form-label">{t('blanket_po.valid_from')} *</label>
                            <DateInput className="form-input" required value={form.valid_from}
                                onChange={e => set('valid_from', e.target.value)} />
                        </div>
                        <div className="form-group">
                            <label className="form-label">{t('blanket_po.valid_to')} *</label>
                            <DateInput className="form-input" required value={form.valid_to}
                                onChange={e => set('valid_to', e.target.value)} />
                        </div>
                    </div>

                    <div className="form-group">
                        <label className="form-label">{t('blanket_po.notes')}</label>
                        <textarea className="form-input" rows={3} value={form.notes}
                            onChange={e => set('notes', e.target.value)} />
                    </div>

                    <div className="d-flex gap-3 pt-3">
                        <button type="submit" className="btn btn-primary" disabled={submitting}>
                            {submitting ? t('common.saving') : t('blanket_po.create')}
                        </button>
                        <button type="button" className="btn btn-secondary" onClick={() => navigate('/buying/blanket-po')}>
                            {t('common.cancel')}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
};

export default BlanketPOForm;
