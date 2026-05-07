import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { posAPI } from '../../utils/api';
import { useToast } from '../../context/ToastContext';
import { Plus, Trash2, Users, Coffee } from 'lucide-react';
import '../../components/ModuleStyles.css';
import BackButton from '../../components/common/BackButton';

const TableManagement = () => {
    const { t } = useTranslation();
    const { showToast } = useToast();
    const [tables, setTables] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const [form, setForm] = useState({ table_number: '', capacity: 4, floor: '' });

    useEffect(() => { fetchTables(); }, []);

    const fetchTables = async () => {
        try { setLoading(true); const res = await posAPI.listTables(); setTables(res.data || []); }
        catch (err) { showToast(t('common.error_occurred'), 'error'); } finally { setLoading(false); }
    };

    const handleCreate = async (e) => {
        e.preventDefault();
        try {
            await posAPI.createTable({ ...form, capacity: parseInt(form.capacity) });
            showToast(t('pos.table_added'), 'success');
            setShowModal(false); setForm({ table_number: '', capacity: 4, floor: '' }); fetchTables();
        } catch (err) { showToast(err.response?.data?.detail || t('common.error'), 'error'); }
    };

    const handleSeat = async (id) => {
        const customerName = window.prompt(t('pos.enter_customer_name') || 'اسم العميل (اختياري)') || '';
        try { await posAPI.seatTable(id, { customer_name: customerName }); showToast(t('pos.seated'), 'success'); fetchTables(); }
        catch (err) { showToast(t('common.error'), 'error'); }
    };

    const handleClear = async (id) => {
        try { await posAPI.clearTable(id); showToast(t('pos.table_cleared'), 'success'); fetchTables(); }
        catch (err) { showToast(t('common.error'), 'error'); }
    };

    const handleDelete = async (id) => {
        if (!confirm(t('pos.delete_table_confirm'))) return;
        try { await posAPI.deleteTable(id); fetchTables(); } catch (err) { showToast(t('common.error'), 'error'); }
    };

    const statusColors = { available: 'bg-green-100 text-green-700', occupied: 'bg-red-100 text-red-700', reserved: 'bg-yellow-100 text-yellow-700' };
    const statusLabels = { available: t('pos.available'), occupied: t('pos.occupied'), reserved: t('pos.reserved') };

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1 className="workspace-title"><span className="p-2 rounded-lg bg-teal-50 text-teal-600"><Coffee size={24} /></span> {t('pos.table_management_title')}</h1>
                        <p className="workspace-subtitle">{t('pos.table_management_subtitle')}</p>
                    </div>
                    <button className="btn btn-primary" onClick={() => setShowModal(true)}><Plus size={18} /> {t('pos.new_table')}</button>
                </div>
            </div>

            {/* Metrics */}
            <div className="metrics-grid mb-4">
                <div className="metric-card"><div className="metric-label">{t('pos.total_tables')}</div><div className="metric-value text-primary">{tables.length}</div></div>
                <div className="metric-card"><div className="metric-label">{t('pos.available')}</div><div className="metric-value text-success">{tables.filter(t => t.status === 'available').length}</div></div>
                <div className="metric-card"><div className="metric-label">{t('pos.occupied')}</div><div className="metric-value text-danger">{tables.filter(t => t.status === 'occupied').length}</div></div>
            </div>

            {/* Table Grid */}
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                {tables.map(table => (
                    <div key={table.id} className="card p-4 text-center" style={{ borderTop: `4px solid ${table.status === 'available' ? '#16a34a' : table.status === 'occupied' ? '#dc2626' : '#d97706'}` }}>
                        <div className="text-2xl font-bold mb-2">#{table.table_number}</div>
                        <div className="mb-2"><span className={`badge ${statusColors[table.status] || 'bg-gray-100'}`}>{statusLabels[table.status] || table.status}</span></div>
                        <div className="text-sm text-muted mb-3"><Users size={14} className="inline" /> {table.capacity} {t('pos.seats')}{table.floor && table.floor !== 'main' ? ` — ${table.floor}` : ''}</div>
                        <div className="d-flex gap-2 justify-content-center">
                            {table.status === 'available' && <button className="btn btn-sm btn-success" onClick={() => handleSeat(table.id)}>{t('pos.seat_btn')}</button>}
                            {table.status === 'occupied' && <button className="btn btn-sm btn-warning" onClick={() => handleClear(table.id)}>{t('pos.clear_btn')}</button>}
                            <button className="btn btn-sm btn-danger" onClick={() => handleDelete(table.id)}><Trash2 size={14} /></button>
                        </div>
                    </div>
                ))}
            </div>

            {loading && <div className="text-center p-8">{t('pos.loading')}</div>}

            {showModal && (
                <div className="modal-overlay" onClick={() => setShowModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 400 }}>
                        <h3 className="modal-title">{t('pos.new_table')}</h3>
                        <form onSubmit={handleCreate} className="space-y-4">
                            <div className="form-group"><label className="form-label">{t('pos.table_number')}</label>
                                <input className="form-input" required value={form.table_number} onChange={e => setForm({ ...form, table_number: e.target.value })} /></div>
                            <div className="form-group"><label className="form-label">{t('pos.capacity')}</label>
                                <input type="number" className="form-input" min="1" value={form.capacity} onChange={e => setForm({ ...form, capacity: e.target.value })} /></div>
                            <div className="form-group"><label className="form-label">{t('pos.zone')}</label>
                                <input className="form-input" placeholder={t('pos.zone_placeholder')} value={form.floor} onChange={e => setForm({ ...form, floor: e.target.value })} /></div>
                            <div className="d-flex gap-3 pt-3">
                                <button type="submit" className="btn btn-primary flex-1">{t('pos.add')}</button>
                                <button type="button" className="btn btn-secondary" onClick={() => setShowModal(false)}>{t('pos.cancel')}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
};

export default TableManagement;
