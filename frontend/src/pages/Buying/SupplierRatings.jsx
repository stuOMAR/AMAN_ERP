import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { purchasesAPI } from '../../utils/api';
import { useToast } from '../../context/ToastContext';
import { Star, Plus } from 'lucide-react';
import '../../components/ModuleStyles.css';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'
import { formatNumber } from '../../utils/format';

const SupplierRatings = () => {
    const { t } = useTranslation();
    const { showToast } = useToast();
    const [ratings, setRatings] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const [form, setForm] = useState({ supplier_id: '', purchase_order_id: '', quality_rating: 5, price_rating: 5, delivery_rating: 5, comments: '' });

    useEffect(() => { fetchRatings(); }, []);

    const fetchRatings = async () => {
        try { setLoading(true); const res = await purchasesAPI.listSupplierRatings(); setRatings(res.data || []); }
        catch (err) { showToast(t('common.error'), 'error'); } finally { setLoading(false); }
    };

    const handleCreate = async (e) => {
        e.preventDefault();
        try {
            await purchasesAPI.createSupplierRating({
                supplier_id: parseInt(form.supplier_id), purchase_order_id: form.purchase_order_id ? parseInt(form.purchase_order_id) : null,
                quality_rating: parseInt(form.quality_rating), price_rating: parseInt(form.price_rating),
                delivery_rating: parseInt(form.delivery_rating), comments: form.comments || null
            });
            showToast(t('buying.rating_submitted'), 'success');
            setShowModal(false); fetchRatings();
        } catch (err) { showToast(err.response?.data?.detail || t('common.error'), 'error'); }
    };

    const renderStars = (rating) => {
        return Array.from({ length: 5 }, (_, i) => (
            <Star key={i} size={14} className={i < rating ? 'text-yellow-500' : 'text-gray-300'} fill={i < rating ? 'currentColor' : 'none'} />
        ));
    };

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1 className="workspace-title"><span className="p-2 rounded-lg bg-yellow-50 text-yellow-600"><Star size={24} /></span> {t('buying.ratings_title')}</h1>
                        <p className="workspace-subtitle">{t('buying.ratings_subtitle')}</p>
                    </div>
                    <button className="btn btn-primary" onClick={() => setShowModal(true)}><Plus size={18} /> {t('buying.new_rating')}</button>
                </div>
            </div>

            <div className="card section-card">
                {loading ? <PageLoading /> : (
                    <div className="data-table-container">
                        <table className="data-table">
                            <thead><tr>
                                <th>{t('buying.col_supplier')}</th>
                                <th>{t('buying.col_quality')}</th>
                                <th>{t('buying.col_price')}</th>
                                <th>{t('buying.col_delivery')}</th>
                                <th>{t('buying.col_overall')}</th>
                                <th>{t('buying.col_comments')}</th>
                                <th>{t('buying.col_date')}</th>
                            </tr></thead>
                            <tbody>
                                {ratings.map(r => (
                                    <tr key={r.id}>
                                        <td className="font-semibold">{r.supplier_name || `#${r.supplier_id}`}</td>
                                        <td><div className="d-flex">{renderStars(r.quality_rating)}</div></td>
                                        <td><div className="d-flex">{renderStars(r.price_rating)}</div></td>
                                        <td><div className="d-flex">{renderStars(r.delivery_rating)}</div></td>
                                        <td><span className="font-bold text-lg">{r.overall_rating != null ? formatNumber(r.overall_rating, 1) : '—'}</span></td>
                                        <td className="text-sm">{r.comments || '—'}</td>
                                        <td className="text-sm">{r.created_at?.split('T')[0]}</td>
                                    </tr>
                                ))}
                                {ratings.length === 0 && <tr><td colSpan="7" className="text-center text-muted p-4">{t('buying.no_ratings')}</td></tr>}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>

            {showModal && (
                <div className="modal-overlay" onClick={() => setShowModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 500 }}>
                        <h3 className="modal-title">{t('buying.rate_supplier_modal')}</h3>
                        <form onSubmit={handleCreate} className="space-y-4">
                            <div className="form-group"><label className="form-label">{t('buying.supplier_id')}</label>
                                <input type="number" className="form-input" required value={form.supplier_id} onChange={e => setForm({ ...form, supplier_id: e.target.value })} /></div>
                            <div className="form-group"><label className="form-label">{t('buying.po_number_optional')}</label>
                                <input type="number" className="form-input" value={form.purchase_order_id} onChange={e => setForm({ ...form, purchase_order_id: e.target.value })} /></div>
                            <div className="grid grid-cols-3 gap-3">
                                {[{ key: 'quality_rating', label: t('buying.col_quality') }, { key: 'price_rating', label: t('buying.col_price') }, { key: 'delivery_rating', label: t('buying.col_delivery') }].map(f => (
                                    <div key={f.key} className="form-group"><label className="form-label">{f.label}</label>
                                        <select className="form-input" value={form[f.key]} onChange={e => setForm({ ...form, [f.key]: e.target.value })}>
                                            {[1, 2, 3, 4, 5].map(n => <option key={n} value={n}>{n} ⭐</option>)}
                                        </select></div>
                                ))}
                            </div>
                            <div className="form-group"><label className="form-label">{t('buying.col_comments')}</label>
                                <textarea className="form-input" rows="2" value={form.comments} onChange={e => setForm({ ...form, comments: e.target.value })} /></div>
                            <div className="d-flex gap-3 pt-3">
                                <button type="submit" className="btn btn-primary flex-1">{t('buying.submit_rating')}</button>
                                <button type="button" className="btn btn-secondary" onClick={() => setShowModal(false)}>{t('buying.cancel')}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
};

export default SupplierRatings;
