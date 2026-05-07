import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { posAPI } from '../../utils/api';
import { useToast } from '../../context/ToastContext';
import { Plus, Tag, Trash2 } from 'lucide-react';
import '../../components/ModuleStyles.css';

import DateInput from '../../components/common/DateInput';
import BackButton from '../../components/common/BackButton';
const Promotions = () => {
    const { t } = useTranslation();
    const { showToast } = useToast();
    const [promotions, setPromotions] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const [couponCode, setCouponCode] = useState('');
    const [couponResult, setCouponResult] = useState(null);
    const [form, setForm] = useState({
        name: '', type: 'percentage', value: '', min_order_amount: '',
        coupon_code: '', start_date: '', end_date: '', is_active: true,
        buy_x: '', get_y: '', category_id: ''
    });

    useEffect(() => { fetchPromotions(); }, []);

    const fetchPromotions = async () => {
        try {
            setLoading(true);
            const res = await posAPI.listPromotions();
            setPromotions(res.data || []);
        } catch (err) { showToast(t('common.error_occurred'), 'error'); } finally { setLoading(false); }
    };

    const handleCreate = async (e) => {
        e.preventDefault();
        try {
            const payload = { ...form, promotion_type: form.type, value: String(form.value || 0), min_order_amount: String(form.min_order_amount || 0) };
            delete payload.type;
            if (form.buy_x) payload.buy_qty = parseInt(form.buy_x);
            if (form.get_y) payload.get_qty = parseInt(form.get_y);
            delete payload.buy_x;
            delete payload.get_y;
            await posAPI.createPromotion(payload);
            showToast(t('pos.promotion_created'), 'success');
            setShowModal(false);
            setForm({ name: '', type: 'percentage', value: '', min_order_amount: '', coupon_code: '', start_date: '', end_date: '', is_active: true, buy_x: '', get_y: '', category_id: '' });
            fetchPromotions();
        } catch (err) { showToast(err.response?.data?.detail || t('common.error'), 'error'); }
    };

    const handleDelete = async (id) => {
        if (!confirm(t('pos.confirm_delete'))) return;
        try {
            await posAPI.deletePromotion(id);
            showToast(t('pos.deleted'), 'success');
            fetchPromotions();
        } catch (err) { showToast(t('common.error'), 'error'); }
    };

    const handleValidateCoupon = async () => {
        try {
            const res = await posAPI.validateCoupon({ coupon_code: couponCode, order_amount: 100 });
            setCouponResult(res.data);
        } catch (err) { setCouponResult({ valid: false, message: err.response?.data?.detail || 'Invalid' }); }
    };

    const typeLabels = { percentage: t('pos.type_percentage'), fixed: t('pos.type_fixed'), buy_x_get_y: t('pos.type_buy_x_get_y') };

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1 className="workspace-title">
                            <span className="p-2 rounded-lg bg-orange-50 text-orange-600"><Tag size={24} /></span>
                            {t('pos.promotions_title')}
                        </h1>
                        <p className="workspace-subtitle">{t('pos.promotions_subtitle')}</p>
                    </div>
                    <button className="btn btn-primary" onClick={() => setShowModal(true)}><Plus size={18} /> {t('pos.new_promotion')}</button>
                </div>
            </div>

            {/* Coupon Validator */}
            <div className="card section-card mb-4">
                <h3 className="section-title">{t('pos.validate_coupon')}</h3>
                <div className="d-flex gap-3 align-items-end">
                    <div className="form-group" style={{ flex: 1 }}>
                        <input type="text" className="form-input" placeholder={t('pos.enter_coupon_code')} value={couponCode} onChange={e => setCouponCode(e.target.value)} />
                    </div>
                    <button className="btn btn-secondary" onClick={handleValidateCoupon}>{t('pos.check')}</button>
                </div>
                {couponResult && (
                    <div className={`mt-3 p-3 rounded-lg ${couponResult.valid ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
                        {couponResult.valid ? `✅ ${t('pos.valid_coupon_discount')} ${couponResult.discount_value}` : `❌ ${couponResult.message || (t('pos.invalid_coupon'))}`}
                    </div>
                )}
            </div>

            {/* Promotions List */}
            <div className="card section-card">
                {loading ? <div className="text-center p-4">{t('common.loading')}...</div> : (
                    <div className="data-table-container">
                        <table className="data-table">
                            <thead><tr>
                                <th>{t('pos.promotion_name')}</th>
                                <th>{t('pos.promotion_type')}</th>
                                <th>{t('pos.promotion_value')}</th>
                                <th>{t('pos.coupon_code')}</th>
                                <th>{t('pos.period')}</th>
                                <th>{t('pos.status')}</th>
                                <th>{t('pos.actions')}</th>
                            </tr></thead>
                            <tbody>
                                {promotions.map(p => (
                                    <tr key={p.id}>
                                        <td className="font-semibold">{p.name}</td>
                                        <td><span className="badge bg-blue-100 text-blue-700">{typeLabels[p.type] || p.type}</span></td>
                                        <td>{p.value}{p.type === 'percentage' ? '%' : ''}</td>
                                        <td>{p.coupon_code || '—'}</td>
                                        <td className="text-sm">{p.start_date || '—'} → {p.end_date || '—'}</td>
                                        <td><span className={`badge ${p.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>{p.is_active ? (t('pos.active')) : (t('pos.inactive'))}</span></td>
                                        <td><button className="btn btn-sm btn-danger" onClick={() => handleDelete(p.id)}><Trash2 size={14} /></button></td>
                                    </tr>
                                ))}
                                {promotions.length === 0 && <tr><td colSpan="7" className="text-center text-muted p-4">{t('pos.no_promotions')}</td></tr>}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>

            {/* Create Modal */}
            {showModal && (
                <div className="modal-overlay" onClick={() => setShowModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 600 }}>
                        <h3 className="modal-title">{t('pos.new_promotion')}</h3>
                        <form onSubmit={handleCreate} className="space-y-4">
                            <div className="form-group"><label className="form-label">{t('pos.promotion_name')}</label>
                                <input className="form-input" required value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></div>
                            <div className="grid grid-cols-2 gap-4">
                                <div className="form-group"><label className="form-label">{t('pos.promotion_type')}</label>
                                    <select className="form-input" value={form.type} onChange={e => setForm({ ...form, type: e.target.value })}>
                                        <option value="percentage">{t('pos.type_percentage')}</option>
                                        <option value="fixed">{t('pos.type_fixed')}</option>
                                        <option value="buy_x_get_y">{t('pos.type_buy_x_get_y')}</option>
                                    </select></div>
                                <div className="form-group"><label className="form-label">{t('pos.promotion_value')}</label>
                                    <input type="number" className="form-input" required value={form.value} onChange={e => setForm({ ...form, value: e.target.value })} /></div>
                            </div>
                            <div className="grid grid-cols-2 gap-4">
                                <div className="form-group"><label className="form-label">{t('pos.coupon_code')}</label>
                                    <input className="form-input" value={form.coupon_code} onChange={e => setForm({ ...form, coupon_code: e.target.value })} /></div>
                                <div className="form-group"><label className="form-label">{t('pos.min_order')}</label>
                                    <input type="number" className="form-input" value={form.min_order_amount} onChange={e => setForm({ ...form, min_order_amount: e.target.value })} /></div>
                            </div>
                            {form.type === 'buy_x_get_y' && (
                                <div className="grid grid-cols-2 gap-4">
                                    <div className="form-group"><label className="form-label">{t('pos.buy_x')}</label>
                                        <input type="number" className="form-input" value={form.buy_x} onChange={e => setForm({ ...form, buy_x: e.target.value })} /></div>
                                    <div className="form-group"><label className="form-label">{t('pos.get_y')}</label>
                                        <input type="number" className="form-input" value={form.get_y} onChange={e => setForm({ ...form, get_y: e.target.value })} /></div>
                                </div>
                            )}
                            <div className="grid grid-cols-2 gap-4">
                                <div className="form-group"><label className="form-label">{t('pos.start_date')}</label>
                                    <DateInput className="form-input" value={form.start_date} onChange={e => setForm({ ...form, start_date: e.target.value })} /></div>
                                <div className="form-group"><label className="form-label">{t('pos.end_date')}</label>
                                    <DateInput className="form-input" value={form.end_date} onChange={e => setForm({ ...form, end_date: e.target.value })} /></div>
                            </div>
                            <div className="d-flex gap-3 pt-3">
                                <button type="submit" className="btn btn-primary flex-1">{t('pos.create')}</button>
                                <button type="button" className="btn btn-secondary" onClick={() => setShowModal(false)}>{t('pos.cancel')}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
};

export default Promotions;
