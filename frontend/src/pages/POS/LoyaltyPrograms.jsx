import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { posAPI } from '../../utils/api';
import { useToast } from '../../context/ToastContext';
import { Award, Plus, Users, Star } from 'lucide-react';
import '../../components/ModuleStyles.css';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

const LoyaltyPrograms = () => {
    const { t } = useTranslation();
    const { showToast } = useToast();

    const [programs, setPrograms] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const [customerLookup, setCustomerLookup] = useState('');
    const [customerLoyalty, setCustomerLoyalty] = useState(null);
    const [form, setForm] = useState({ name: '', points_per_unit: 1, min_points_redeem: 100, point_value: 0.1, is_active: true });

    useEffect(() => { fetchPrograms(); }, []);

    const fetchPrograms = async () => {
        try { setLoading(true); const res = await posAPI.listLoyaltyPrograms(); setPrograms(res.data || []); }
        catch (err) { showToast(t('common.error_occurred'), 'error'); } finally { setLoading(false); }
    };

    const handleCreate = async (e) => {
        e.preventDefault();
        try {
            await posAPI.createLoyaltyProgram({ ...form, points_per_unit: String(form.points_per_unit), min_points_redeem: parseInt(form.min_points_redeem), currency_per_point: String(form.point_value) });
            showToast(t('pos.program_created'), 'success');
            setShowModal(false); fetchPrograms();
        } catch (err) { showToast(err.response?.data?.detail || t('common.error'), 'error'); }
    };

    const lookupCustomer = async () => {
        if (!customerLookup) return;
        try {
            const res = await posAPI.getCustomerLoyalty(customerLookup);
            setCustomerLoyalty(res.data);
        } catch (err) { setCustomerLoyalty({ error: true }); }
    };

    const tierColors = { bronze: 'bg-amber-100 text-amber-700', silver: 'bg-gray-200 text-gray-700', gold: 'bg-yellow-100 text-yellow-700' };

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1 className="workspace-title"><span className="p-2 rounded-lg bg-purple-50 text-purple-600"><Award size={24} /></span> {t('pos.loyalty_title')}</h1>
                        <p className="workspace-subtitle">{t('pos.loyalty_subtitle')}</p>
                    </div>
                    <button className="btn btn-primary" onClick={() => setShowModal(true)}><Plus size={18} /> {t('pos.new_program')}</button>
                </div>
            </div>

            {/* Customer Lookup */}
            <div className="card section-card mb-4">
                <h3 className="section-title"><Users size={18} /> {t('pos.customer_lookup')}</h3>
                <div className="d-flex gap-3 align-items-end">
                    <div className="form-group" style={{ flex: 1 }}>
                        <input type="text" className="form-input" placeholder={t('pos.customer_party_id')} value={customerLookup} onChange={e => setCustomerLookup(e.target.value)} />
                    </div>
                    <button className="btn btn-secondary" onClick={lookupCustomer}>{t('pos.search')}</button>
                </div>
                {customerLoyalty && !customerLoyalty.error && (
                    <div className="mt-3 p-4 bg-purple-50 rounded-lg">
                        <div className="d-flex justify-content-between align-items-center">
                            <div>
                                <div className="font-bold text-lg">{t('pos.current_points')} <span className="text-purple-600">{customerLoyalty.total_points || 0}</span></div>
                                <div className="text-sm text-muted">{t('pos.tier')} <span className={`badge ${tierColors[customerLoyalty.tier] || 'bg-gray-100'}`}>{customerLoyalty.tier || 'bronze'}</span></div>
                            </div>
                            <Star size={32} className="text-yellow-500" fill="currentColor" />
                        </div>
                    </div>
                )}
                {customerLoyalty?.error && <div className="mt-3 p-3 bg-red-50 text-red-600 rounded-lg">{t('pos.customer_not_enrolled')}</div>}
            </div>

            {/* Programs List */}
            <div className="card section-card">
                {loading ? <PageLoading /> : (
                    <div className="data-table-container">
                        <table className="data-table">
                            <thead><tr>
                                <th>{t('pos.program_name')}</th>
                                <th>{t('pos.points_per_unit')}</th>
                                <th>{t('pos.min_redeem')}</th>
                                <th>{t('pos.point_value')}</th>
                                <th>{t('pos.status')}</th>
                            </tr></thead>
                            <tbody>
                                {programs.map(p => (
                                    <tr key={p.id}>
                                        <td className="font-semibold">{p.name}</td>
                                        <td>{p.points_per_unit}</td>
                                        <td>{p.min_points_redeem}</td>
                                        <td>{p.point_value}</td>
                                        <td><span className={`badge ${p.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100'}`}>{p.is_active ? (t('pos.active')) : (t('pos.inactive'))}</span></td>
                                    </tr>
                                ))}
                                {programs.length === 0 && <tr><td colSpan="5" className="text-center text-muted p-4">{t('pos.no_programs')}</td></tr>}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>

            {showModal && (
                <div className="modal-overlay" onClick={() => setShowModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 500 }}>
                        <h3 className="modal-title">{t('pos.new_loyalty_program')}</h3>
                        <form onSubmit={handleCreate} className="space-y-4">
                            <div className="form-group"><label className="form-label">{t('pos.program_name')}</label>
                                <input className="form-input" required value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></div>
                            <div className="grid grid-cols-3 gap-3">
                                <div className="form-group"><label className="form-label">{t('pos.pts_per_unit')}</label>
                                    <input type="number" step="0.1" className="form-input" value={form.points_per_unit} onChange={e => setForm({ ...form, points_per_unit: e.target.value })} /></div>
                                <div className="form-group"><label className="form-label">{t('pos.min_redeem')}</label>
                                    <input type="number" className="form-input" value={form.min_points_redeem} onChange={e => setForm({ ...form, min_points_redeem: e.target.value })} /></div>
                                <div className="form-group"><label className="form-label">{t('pos.point_value')}</label>
                                    <input type="number" step="0.01" className="form-input" value={form.point_value} onChange={e => setForm({ ...form, point_value: e.target.value })} /></div>
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

export default LoyaltyPrograms;
