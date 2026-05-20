import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { purchasesAPI, inventoryAPI } from '../../utils/api';
import { useToast } from '../../context/ToastContext';
import { Plus, Send, GitCompare, ArrowRightCircle, FileText, ChevronDown, X } from 'lucide-react';
import '../../components/ModuleStyles.css';

import DateInput from '../../components/common/DateInput';
import BackButton from '../../components/common/BackButton';
import DataTable from '../../components/common/DataTable';
import SearchFilter from '../../components/common/SearchFilter';
import Decimal from 'decimal.js';

const RFQList = () => {
    const { t } = useTranslation();
    const { showToast } = useToast();
    const [rfqs, setRfqs] = useState([]);
    const [suppliers, setSuppliers] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const emptyLine = { product_name: '', quantity: '1', unit: '' };
    const [form, setForm] = useState({ title: '', supplier_ids: [], deadline: '', notes: '', lines: [{ ...emptyLine }] });
    const [supplierDropOpen, setSupplierDropOpen] = useState(false);
    const [supplierSearch, setSupplierSearch] = useState('');
    const supplierDropRef = useRef(null);
    const [search, setSearch] = useState('');
    const [statusFilter, setStatusFilter] = useState('');

    useEffect(() => {
        const handleClickOutside = (e) => {
            if (supplierDropRef.current && !supplierDropRef.current.contains(e.target)) {
                setSupplierDropOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    useEffect(() => { fetchRFQs(); fetchSuppliers(); }, []);

    const fetchSuppliers = async () => {
        try { const res = await inventoryAPI.listSuppliers({ limit: 1000 }); setSuppliers(res.data || []); }
        catch (err) { showToast(t('common.error'), 'error'); }
    };

    const fetchRFQs = async () => {
        try { setLoading(true); const res = await purchasesAPI.listRFQs(); setRfqs(res.data || []); }
        catch (err) { showToast(t('common.error'), 'error'); } finally { setLoading(false); }
    };

    const handleCreate = async (e) => {
        e.preventDefault();
        if (form.supplier_ids.length === 0) { showToast(t('buying.rfq.select_supplier_required'), 'error'); return; }
        const lines = form.lines.filter(line => (line.product_name || '').trim() && new Decimal(line.quantity || 0).gt(0));
        if (lines.length === 0) { showToast(t('buying.rfq.line_required', 'يجب إضافة بند واحد على الأقل'), 'error'); return; }
        try {
            await purchasesAPI.createRFQ({ title: form.title, supplier_ids: form.supplier_ids, deadline: form.deadline || null, notes: form.notes || null, lines });
            showToast(t('buying.rfq_created'), 'success');
            setShowModal(false); setForm({ title: '', supplier_ids: [], deadline: '', notes: '', lines: [{ ...emptyLine }] }); fetchRFQs();
        } catch (err) { showToast(err.response?.data?.detail || t('common.error'), 'error'); }
    };

    const handleSend = async (id) => {
        try { await purchasesAPI.sendRFQ(id); showToast(t('buying.rfq_sent'), 'success'); fetchRFQs(); }
        catch (err) { showToast(t('common.error'), 'error'); }
    };

    const handleCompare = async (id) => {
        try {
            const res = await purchasesAPI.compareRFQ(id);
            const recommended = res.data?.recommended;
            showToast(t('buying.rfq_compared_best') + (recommended?.supplier_name || recommended?.supplier_id || '—'), 'success');
            fetchRFQs();
        } catch (err) { showToast(t('common.error'), 'error'); }
    };

    const handleConvert = async (id) => {
        try {
            await purchasesAPI.convertRFQtoPO(id, {});
            showToast(t('buying.rfq_converted_to_po'), 'success'); fetchRFQs();
        } catch (err) { showToast(err.response?.data?.detail || t('common.error'), 'error'); }
    };

    const statusBadge = (s) => {
        const map = { draft: 'bg-gray-100 text-gray-600', sent: 'bg-blue-100 text-blue-700', received: 'bg-purple-100 text-purple-700', compared: 'bg-yellow-100 text-yellow-700', converted: 'bg-green-100 text-green-700' };
        const labels = { draft: t('buying.rfq_status_draft'), sent: t('buying.rfq_status_sent'), received: t('buying.rfq_status_received'), compared: t('buying.rfq_status_compared'), converted: t('buying.rfq_status_converted') };
        return <span className={`badge ${map[s] || 'bg-gray-100'}`}>{labels[s] || s}</span>;
    };

    const filteredRFQs = useMemo(() => {
        let result = rfqs;
        if (search) {
            const q = search.toLowerCase();
            result = result.filter(rfq =>
                (rfq.title || '').toLowerCase().includes(q) ||
                String(rfq.id).includes(q)
            );
        }
        if (statusFilter) {
            result = result.filter(rfq => rfq.status === statusFilter);
        }
        return result;
    }, [rfqs, search, statusFilter]);

    const columns = [
        {
            key: 'id',
            label: '#',
        },
        {
            key: 'title',
            label: t('buying.rfq_col_title'),
            style: { fontWeight: 600 },
        },
        {
            key: 'status',
            label: t('buying.rfq_col_status'),
            render: (val) => statusBadge(val),
        },
        {
            key: 'deadline',
            label: t('buying.rfq_col_deadline'),
            render: (val) => val || '—',
        },
        {
            key: 'response_count',
            label: t('buying.rfq_col_responses'),
            render: (val) => val || 0,
        },
        {
            key: '_actions',
            label: t('buying.rfq_col_actions'),
            render: (_, row) => (
                <div className="d-flex gap-2">
                    {row.status === 'draft' && <button className="btn btn-sm btn-primary" onClick={(e) => { e.stopPropagation(); handleSend(row.id); }} title={t('buying.send')}><Send size={14} /></button>}
                    {(row.status === 'received' || row.status === 'sent') && <button className="btn btn-sm btn-warning" onClick={(e) => { e.stopPropagation(); handleCompare(row.id); }} title={t('buying.compare')}><GitCompare size={14} /></button>}
                    {row.status === 'compared' && <button className="btn btn-sm btn-success" onClick={(e) => { e.stopPropagation(); handleConvert(row.id); }} title={t('buying.convert_to_po')}><ArrowRightCircle size={14} /></button>}
                </div>
            ),
        },
    ];

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1 className="workspace-title"><span className="p-2 rounded-lg bg-indigo-50 text-indigo-600"><FileText size={24} /></span> {t('buying.rfq_title')}</h1>
                        <p className="workspace-subtitle">{t('buying.rfq_subtitle')}</p>
                    </div>
                    <button className="btn btn-primary" onClick={() => setShowModal(true)}><Plus size={18} /> {t('buying.new_rfq')}</button>
                </div>
            </div>

            <SearchFilter
                value={search}
                onChange={setSearch}
                placeholder={t('common.search')}
                filters={[{
                    key: 'status',
                    label: t('buying.rfq_col_status'),
                    options: [
                        { value: 'draft', label: t('buying.rfq_status_draft') },
                        { value: 'sent', label: t('buying.rfq_status_sent') },
                        { value: 'received', label: t('buying.rfq_status_received') },
                        { value: 'compared', label: t('buying.rfq_status_compared') },
                        { value: 'converted', label: t('buying.rfq_status_converted') },
                    ],
                }]}
                filterValues={{ status: statusFilter }}
                onFilterChange={(key, val) => setStatusFilter(val)}
            />

            <DataTable
                columns={columns}
                data={filteredRFQs}
                loading={loading}
                emptyTitle={t('buying.no_rfqs')}
                emptyIcon="📄"
            />

            {showModal && (
                <div className="modal-overlay" onClick={() => setShowModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 500 }}>
                        <h3 className="modal-title">{t('buying.new_rfq_modal')}</h3>
                        <form onSubmit={handleCreate} className="space-y-4">
                            <div className="form-group"><label className="form-label">{t('buying.rfq_col_title')}</label>
                                <input className="form-input" required value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} /></div>
                            <div className="form-group" style={{ position: 'relative' }} ref={supplierDropRef}>
                                <label className="form-label">{t('buying.rfq.suppliers')}</label>
                                {/* chips */}
                                {form.supplier_ids.length > 0 && (
                                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 6 }}>
                                        {form.supplier_ids.map(id => {
                                            const s = suppliers.find(x => x.id === id);
                                            if (!s) return null;
                                            return (
                                                <span key={id} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, background: 'var(--primary)', color: '#fff', borderRadius: 20, padding: '3px 10px', fontSize: 13 }}>
                                                    {s.name || s.supplier_name}
                                                    <button type="button" onClick={() => setForm(prev => ({ ...prev, supplier_ids: prev.supplier_ids.filter(x => x !== id) }))} style={{ background: 'none', border: 'none', color: '#fff', cursor: 'pointer', padding: 0, display: 'flex', alignItems: 'center' }}><X size={13} /></button>
                                                </span>
                                            );
                                        })}
                                    </div>
                                )}
                                {/* trigger */}
                                <div
                                    className="form-input"
                                    style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer', userSelect: 'none' }}
                                    onClick={() => { setSupplierDropOpen(o => !o); setSupplierSearch(''); }}
                                >
                                    <span style={{ color: form.supplier_ids.length ? 'var(--text-main)' : 'var(--text-muted)' }}>
                                        {form.supplier_ids.length ? `${form.supplier_ids.length} ${t('buying.rfq.supplier_selected')}` : t('buying.rfq.choose_suppliers')}
                                    </span>
                                    <ChevronDown size={16} style={{ color: 'var(--text-muted)', transition: 'transform .2s', transform: supplierDropOpen ? 'rotate(180deg)' : 'rotate(0deg)' }} />
                                </div>
                                {/* dropdown */}
                                {supplierDropOpen && (
                                    <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 999, background: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: 8, boxShadow: '0 8px 24px rgba(0,0,0,.12)', marginTop: 4 }}>
                                        <div style={{ padding: '8px 10px', borderBottom: '1px solid var(--border-color)' }}>
                                            <input
                                                autoFocus
                                                className="form-input"
                                                style={{ padding: '6px 10px', fontSize: 13 }}
                                                placeholder={t('buying.rfq.search_supplier')}
                                                value={supplierSearch}
                                                onChange={e => setSupplierSearch(e.target.value)}
                                                onClick={e => e.stopPropagation()}
                                            />
                                        </div>
                                        <div style={{ maxHeight: 220, overflowY: 'auto' }}>
                                            {suppliers
                                                .filter(s => (s.name || s.supplier_name || '').toLowerCase().includes(supplierSearch.toLowerCase()) || (s.party_code || '').toLowerCase().includes(supplierSearch.toLowerCase()))
                                                .map(s => {
                                                    const selected = form.supplier_ids.includes(s.id);
                                                    return (
                                                        <div
                                                            key={s.id}
                                                            onClick={() => {
                                                                setForm(prev => ({
                                                                    ...prev,
                                                                    supplier_ids: selected
                                                                        ? prev.supplier_ids.filter(x => x !== s.id)
                                                                        : [...prev.supplier_ids, s.id]
                                                                }));
                                                            }}
                                                            style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 14px', cursor: 'pointer', background: selected ? 'rgba(37,99,235,.07)' : 'transparent', borderBottom: '1px solid var(--border-color)' }}
                                                            onMouseEnter={e => { if (!selected) e.currentTarget.style.background = 'var(--bg-hover)'; }}
                                                            onMouseLeave={e => { e.currentTarget.style.background = selected ? 'rgba(37,99,235,.07)' : 'transparent'; }}
                                                        >
                                                            <div style={{ width: 18, height: 18, borderRadius: 4, border: `2px solid ${selected ? 'var(--primary)' : 'var(--border-color)'}`, background: selected ? 'var(--primary)' : 'transparent', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                                                                {selected && <svg width="11" height="9" viewBox="0 0 11 9" fill="none"><path d="M1 4l3 3 6-6" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>}
                                                            </div>
                                                            <span style={{ fontSize: 14 }}>{s.name || s.supplier_name}</span>
                                                            {s.party_code && <span style={{ marginInlineStart: 'auto', color: 'var(--primary)', fontFamily: 'monospace', fontSize: 12 }}>{s.party_code}</span>}
                                                        </div>
                                                    );
                                                })
                                            }
                                            {suppliers.filter(s => (s.name || s.supplier_name || '').toLowerCase().includes(supplierSearch.toLowerCase())).length === 0 &&
                                                <div style={{ padding: '12px 14px', color: 'var(--text-muted)', fontSize: 13, textAlign: 'center' }}>{t('buying.rfq.no_results')}</div>}
                                        </div>
                                        <div style={{ padding: '8px 12px', borderTop: '1px solid var(--border-color)', display: 'flex', justifyContent: 'flex-end' }}>
                                            <button type="button" className="btn btn-sm btn-primary" onClick={() => setSupplierDropOpen(false)}>{t('common.confirm')}</button>
                                        </div>
                                    </div>
                                )}
                                {form.supplier_ids.length === 0 && <small style={{ color: 'var(--danger)' }}>{t('buying.rfq.select_supplier_required')}</small>}
                            </div>
                            <div className="form-group"><label className="form-label">{t('buying.rfq_col_deadline')}</label>
                                <DateInput className="form-input" value={form.deadline} onChange={e => setForm({ ...form, deadline: e.target.value })} /></div>
                            <div className="form-group">
                                <label className="form-label">{t('buying.orders.items')}</label>
                                {form.lines.map((line, idx) => (
                                    <div key={idx} className="form-grid-3" style={{ gap: 8, marginBottom: 8 }}>
                                        <input
                                            className="form-input"
                                            placeholder={t('buying.orders.item.product')}
                                            value={line.product_name}
                                            onChange={e => setForm(prev => ({ ...prev, lines: prev.lines.map((l, i) => i === idx ? { ...l, product_name: e.target.value } : l) }))}
                                        />
                                        <input
                                            className="form-input"
                                            type="text"
                                            inputMode="decimal"
                                            min="0.0001"
                                            step="0.0001"
                                            placeholder={t('buying.orders.item.qty_ordered')}
                                            value={line.quantity}
                                            onChange={e => setForm(prev => ({ ...prev, lines: prev.lines.map((l, i) => i === idx ? { ...l, quantity: e.target.value } : l) }))}
                                        />
                                        <input
                                            className="form-input"
                                            placeholder={t('common.unit', 'Unit')}
                                            value={line.unit}
                                            onChange={e => setForm(prev => ({ ...prev, lines: prev.lines.map((l, i) => i === idx ? { ...l, unit: e.target.value } : l) }))}
                                        />
                                    </div>
                                ))}
                                <button type="button" className="btn btn-sm btn-secondary" onClick={() => setForm(prev => ({ ...prev, lines: [...prev.lines, { ...emptyLine }] }))}>
                                    <Plus size={14} /> {t('common.add')}
                                </button>
                            </div>
                            <div className="form-group"><label className="form-label">{t('buying.rfq_notes')}</label>
                                <textarea className="form-input" rows="2" value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} /></div>
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

export default RFQList;
