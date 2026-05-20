import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { purchasesAPI, inventoryAPI } from '../../utils/api';
import { useToast } from '../../context/ToastContext';
import { Plus, FileCheck, Play, ShoppingCart } from 'lucide-react';
import '../../components/ModuleStyles.css';

import DateInput from '../../components/common/DateInput';
import { formatDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'
const PurchaseAgreements = () => {
    const { t } = useTranslation();
    const { showToast } = useToast();
    const [agreements, setAgreements] = useState([]);
    const [suppliers, setSuppliers] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const [form, setForm] = useState({ supplier_id: '', title: '', start_date: '', end_date: '', notes: '' });

    useEffect(() => { fetchAgreements(); fetchSuppliers(); }, []);

    const fetchSuppliers = async () => {
        try { const res = await inventoryAPI.listSuppliers({ limit: 500 }); setSuppliers(res.data || []); }
        catch (err) { showToast(t('common.error'), 'error'); }
    };

    const fetchAgreements = async () => {
        try { setLoading(true); const res = await purchasesAPI.listAgreements(); setAgreements(res.data || []); }
        catch (err) { showToast(t('common.error'), 'error'); } finally { setLoading(false); }
    };

    const handleCreate = async (e) => {
        e.preventDefault();
        try {
            await purchasesAPI.createAgreement({ ...form, supplier_id: parseInt(form.supplier_id) });
            showToast(t('buying.agreement_created'), 'success');
            setShowModal(false); fetchAgreements();
        } catch (err) { showToast(err.response?.data?.detail || t('common.error'), 'error'); }
    };

    const handleActivate = async (id) => {
        try { await purchasesAPI.activateAgreement(id); showToast(t('buying.activated'), 'success'); fetchAgreements(); }
        catch (err) { showToast(t('common.error'), 'error'); }
    };

    const handleCallOff = async (id) => {
        const qty = prompt(t('buying.quantity_prompt'));
        if (!qty) return;
        try {
            await purchasesAPI.callOffAgreement(id, { quantity: String(qty) });
            showToast(t('buying.calloff_created'), 'success'); fetchAgreements();
        } catch (err) { showToast(err.response?.data?.detail || t('common.error'), 'error'); }
    };

    const statusBadge = (s) => {
        const map = { draft: 'bg-gray-100 text-gray-600', active: 'bg-green-100 text-green-700', expired: 'bg-red-100 text-red-600', completed: 'bg-blue-100 text-blue-700' };
        const labels = { draft: t('buying.agreement_status_draft'), active: t('buying.agreement_status_active'), expired: t('buying.agreement_status_expired'), completed: t('buying.agreement_status_completed') };
        return <span className={`badge ${map[s] || 'bg-gray-100'}`}>{labels[s] || s}</span>;
    };

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1 className="workspace-title"><span className="p-2 rounded-lg bg-green-50 text-green-600"><FileCheck size={24} /></span> {t('buying.agreements_title')}</h1>
                        <p className="workspace-subtitle">{t('buying.agreements_subtitle')}</p>
                    </div>
                    <button className="btn btn-primary" onClick={() => setShowModal(true)}><Plus size={18} /> {t('buying.new_agreement')}</button>
                </div>
            </div>

            <div className="card section-card">
                {loading ? <PageLoading /> : (
                    <div className="data-table-container">
                        <table className="data-table">
                            <thead><tr>
                                <th>#</th>
                                <th>{t('buying.agreement_col_title')}</th>
                                <th>{t('buying.agreement_col_supplier')}</th>
                                <th>{t('buying.agreement_col_status')}</th>
                                <th>{t('buying.agreement_col_period')}</th>
                                <th>{t('buying.agreement_col_actions')}</th>
                            </tr></thead>
                            <tbody>
                                {agreements.map(a => (
                                    <tr key={a.id}>
                                        <td>{a.id}</td>
                                        <td className="font-semibold">{a.title}</td>
                                        <td>{a.supplier_name || `#${a.supplier_id}`}</td>
                                        <td>{statusBadge(a.status)}</td>
                                        <td className="text-sm">{formatDate(a.start_date)} → {formatDate(a.end_date)}</td>
                                        <td>
                                            <div className="d-flex gap-2">
                                                {a.status === 'draft' && <button className="btn btn-sm btn-success" onClick={() => handleActivate(a.id)} title={t('buying.activate')}><Play size={14} /></button>}
                                                {a.status === 'active' && <button className="btn btn-sm btn-primary" onClick={() => handleCallOff(a.id)} title={t('buying.calloff')}><ShoppingCart size={14} /></button>}
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                                {agreements.length === 0 && <tr><td colSpan="6" className="text-center text-muted p-4">{t('buying.no_agreements')}</td></tr>}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>

            {showModal && (
                <div className="modal-overlay" onClick={() => setShowModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 500 }}>
                        <h3 className="modal-title">{t('buying.new_agreement_modal')}</h3>
                        <form onSubmit={handleCreate} className="space-y-4">
                            <div className="form-group"><label className="form-label">{t('buying.agreement_col_title')}</label>
                                <input className="form-input" required value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} /></div>
                            <div className="form-group"><label className="form-label">{t('buying.agreement_supplier_id')}</label>
                                <select className="form-input" required value={form.supplier_id} onChange={e => setForm({ ...form, supplier_id: e.target.value })}>
                                    <option value="">-- {t('common.select_supplier')} --</option>
                                    {suppliers.map(s => (
                                        <option key={s.id} value={s.id}>{s.name || s.supplier_name}{s.party_code ? ` (${s.party_code})` : ''}</option>
                                    ))}
                                </select></div>
                            <div className="grid grid-cols-2 gap-3">
                                <div className="form-group"><label className="form-label">{t('buying.agreement_start')}</label>
                                    <DateInput className="form-input" required value={form.start_date} onChange={e => setForm({ ...form, start_date: e.target.value })} /></div>
                                <div className="form-group"><label className="form-label">{t('buying.agreement_end')}</label>
                                    <DateInput className="form-input" required value={form.end_date} onChange={e => setForm({ ...form, end_date: e.target.value })} /></div>
                            </div>
                            <div className="d-flex gap-3 pt-3">
                                <button type="submit" className="btn btn-primary flex-1">{t('buying.create')}</button>
                                <button type="button" className="btn btn-secondary" onClick={() => setShowModal(false)}>{t('buying.cancel')}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
};

export default PurchaseAgreements;
