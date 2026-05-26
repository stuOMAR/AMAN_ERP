import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { purchasesAPI, inventoryAPI } from '../../utils/api'
import { useTranslation } from 'react-i18next'
import { formatShortDate } from '../../utils/dateUtils'
import { useBranch } from '../../context/BranchContext'
import { formatNumber } from '../../utils/format'
import { getCurrency } from '../../utils/auth'
import '../../components/ModuleStyles.css'
import useInvoiceCalc from '../../hooks/useInvoiceCalc'

import DateInput from '../../components/common/DateInput';
import BackButton from '../../components/common/BackButton';
import { useToast } from '../../context/ToastContext'
import { PageLoading } from '../../components/common/LoadingStates'
function PurchaseDebitNotes() {
    const { t } = useTranslation()
    const { showToast } = useToast()
    const { currentBranch } = useBranch()
    const currency = getCurrency()

    const [items, setItems] = useState([])
    const [loading, setLoading] = useState(true)
    const [initialLoad, setInitialLoad] = useState(true)
    const [total, setTotal] = useState('0')
    const [page, setPage] = useState(1)
    const [search, setSearch] = useState('')
    const [statusFilter, setStatusFilter] = useState('')

    const [showCreate, setShowCreate] = useState(false)
    const [suppliers, setSuppliers] = useState([])
    const [products, setProducts] = useState([])
    const [purchaseInvoices, setPurchaseInvoices] = useState([])
    const [form, setForm] = useState({
        party_id: '', related_invoice_id: '', invoice_date: new Date().toISOString().split('T')[0],
        notes: '', branch_id: currentBranch?.id, party_site_id: '',
        lines: [{ description: '', quantity: '1', unit_price: '', discount: '' }]
    })
    const [saving, setSaving] = useState(false)

    const [detailItem, setDetailItem] = useState(null)
    const [showDetail, setShowDetail] = useState(false)

    const fetchList = useCallback(async () => {
        try {
            setLoading(true)
            const params = { page, limit: 50, branch_id: currentBranch?.id }
            if (search) params.search = search
            if (statusFilter) params.status_filter = statusFilter
            const res = await purchasesAPI.listDebitNotes(params)
            setItems(res.data.items || [])
            setTotal(res.data.total || 0)
        } catch (err) { showToast(t('common.error'), 'error') }
        finally { setLoading(false); setInitialLoad(false) }
    }, [page, search, statusFilter, currentBranch])

    useEffect(() => {
        const timer = setTimeout(() => { fetchList() }, 300)
        return () => clearTimeout(timer)
    }, [fetchList])

    const loadCreateData = async () => {
        try {
            const [suppRes, prodRes] = await Promise.all([
                inventoryAPI.listSuppliers({ limit: 500 }),
                inventoryAPI.listProducts({ limit: 1000 })
            ])
            setSuppliers(suppRes.data?.data || suppRes.data || [])
            setProducts(prodRes.data?.items || prodRes.data?.data || prodRes.data || [])
        } catch (err) { showToast(t('common.error'), 'error') }
    }

    const loadSupplierInvoices = async (partyId) => {
        if (!partyId) { setPurchaseInvoices([]); return }
        try {
            const res = await purchasesAPI.listInvoices({ supplier_id: partyId, limit: 200 })
            setPurchaseInvoices(res.data?.items || res.data || [])
        } catch (err) { showToast(t('common.error'), 'error') }
    }

    const openCreate = () => {
        setForm({
            party_id: '', related_invoice_id: '', invoice_date: new Date().toISOString().split('T')[0],
            notes: '', branch_id: currentBranch?.id, party_site_id: '',
            lines: [{ product_id: '', description: '', quantity: '1', unit_price: '', discount: '' }]
        })
        loadCreateData()
        setShowCreate(true)
    }

    const addLine = () => setForm(f => ({ ...f, lines: [...f.lines, { product_id: '', description: '', quantity: '1', unit_price: '', discount: '' }] }))
    const removeLine = (i) => setForm(f => {
        if (f.lines.length <= 1) return f;
        return { ...f, lines: f.lines.filter((_, idx) => idx !== i) };
    })
    const updateLine = (i, field, val) => {
        setForm(f => {
            const lines = [...f.lines]
            lines[i] = { ...lines[i], [field]: val }
            if (field === 'product_id' && val) {
                const prod = products.find(p => String(p.id) === String(val))
                if (prod) {
                    lines[i].description = prod.item_name || prod.name || ''
                    lines[i].unit_price = String(prod.last_buying_price || prod.buying_price || '')
                }
            }
            return { ...f, lines }
        })
    }

    // Backend-powered calculations
    const { totals: backendTotals, lines: backendLines, previewDebounced } = useInvoiceCalc()
    useEffect(() => {
        if (form.lines?.length > 0 && form.lines.some(l => l.quantity && l.unit_price)) {
            previewDebounced({
                lines: form.lines.map(l => ({
                    product_id: l.product_id || null,
                    quantity: String(l.quantity || '0'),
                    unit_price: String(l.unit_price || '0'),
                    discount: String(l.discount || '0'),
                })),
                branch_id: currentBranch?.id,
                currency,
            })
        }
    }, [form.lines, currentBranch?.id, currency, previewDebounced])

    const backendLineTotal = (index) => backendLines?.[index]?.total ?? backendLines?.[index]?.line_total ?? null
    const summarySubtotal = backendTotals?.subtotal ?? null
    const summaryTax = backendTotals?.totalTax ?? null
    const summaryTotal = backendTotals?.grandTotal ?? null

    const handleCreate = async () => {
        if (!form.party_id) return showToast(t('buying.debit_notes.supplier_required', 'warning'))
        if (!form.lines.length || form.lines.every(l => !l.unit_price)) return showToast(t('buying.debit_notes.line_required', 'warning'))
        try {
            setSaving(true)
            // Phase 2 fix: send all monetary/quantity line values as strings
            // to preserve NUMERIC(18,4) precision — never rely on JS Number for wire format.
            await purchasesAPI.createDebitNote({
                ...form,
                party_id: parseInt(form.party_id),
                branch_id: currentBranch?.id,
                party_site_id: form.party_site_id ? parseInt(form.party_site_id) : null,
                related_invoice_id: form.related_invoice_id ? parseInt(form.related_invoice_id) : null,
                lines: form.lines.map(l => ({
                    ...l,
                    product_id: l.product_id ? parseInt(l.product_id) : null,
                    quantity: String(l.quantity ?? 0),
                    unit_price: String(l.unit_price ?? 0),
                    discount: String(l.discount ?? 0),
                })),
            })
            setShowCreate(false)
            fetchList()
        } catch (err) {
            showToast(err.response?.data?.detail || t('buying.debit_notes.error_occurred', 'error'))
        } finally { setSaving(false) }
    }

    const viewDetail = async (id) => {
        try {
            const res = await purchasesAPI.getDebitNote(id)
            setDetailItem(res.data)
            setShowDetail(true)
        } catch (err) { showToast(t('common.error'), 'error') }
    }

    const statusBadge = (s) => {
        const map = { posted: 'badge-success', paid: 'badge-success', unpaid: 'badge-danger', partial: 'badge-warning', draft: 'badge-secondary' }
        const labels = { posted: t('buying.debit_notes.status_posted'), paid: t('buying.debit_notes.status_paid'), unpaid: t('buying.debit_notes.status_unpaid'), partial: t('buying.debit_notes.status_partial'), draft: t('buying.debit_notes.status_draft') }
        return <span className={`badge ${map[s] || 'badge-secondary'}`}>{labels[s] || s}</span>
    }

    if (initialLoad && !items.length) return <PageLoading />

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
                    <div>
                        <h1 className="workspace-title">📝 {t('buying.debit_notes.title')}</h1>
                        <p className="workspace-subtitle">{t('buying.debit_notes.subtitle')}</p>
                    </div>
                    <button className="btn btn-primary" onClick={openCreate}>+ {t('buying.debit_notes.create_debit_note')}</button>
                </div>
            </div>

            <div className="card" style={{ padding: 16, display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
                <input className="form-input" placeholder={t('buying.debit_notes.search_placeholder')} value={search}
                    onChange={e => setSearch(e.target.value)} style={{ maxWidth: 250 }} />
                <select className="form-input" value={statusFilter} onChange={e => setStatusFilter(e.target.value)} style={{ maxWidth: 180 }}>
                    <option value="">{t('common.all_statuses')}</option>
                    <option value="posted">{t('common.posted')}</option>
                    <option value="draft">{t('common.draft')}</option>
                </select>
                <div style={{ marginRight: 'auto', fontWeight: 600, alignSelf: 'center' }}>{t('common.total')}: {total}</div>
            </div>

            <div className="card card-flush" style={{ overflow: 'auto' }}>
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('buying.debit_notes.note_number')}</th>
                            <th>{t('common.supplier')}</th>
                            <th>{t('common.date')}</th>
                            <th>{t('buying.debit_notes.related_invoice')}</th>
                            <th>{t('common.amount')}</th>
                            <th>{t('common.status_title')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {items.length === 0 ? (
                            <tr><td colSpan="6" style={{ textAlign: 'center', padding: 40 }}>{t('buying.debit_notes.no_debit_notes')}</td></tr>
                        ) : items.map(item => (
                            <tr key={item.id} onClick={() => viewDetail(item.id)} style={{ cursor: 'pointer' }}>
                                <td style={{ fontWeight: 'bold' }}>{item.invoice_number}</td>
                                <td>{item.party_name}</td>
                                <td>{formatShortDate(item.invoice_date)}</td>
                                <td>{item.related_invoice_number || '—'}</td>
                                <td style={{ fontWeight: 'bold' }}>{formatNumber(item.total)} {currency}</td>
                                <td>{statusBadge(item.status)}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {/* Create Modal */}
            {showCreate && (
                <div className="modal-overlay" onClick={() => setShowCreate(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 1200, width: '95%', maxHeight: '95vh', overflow: 'auto' }}>
                        <div className="modal-header">
                            <h2>{t('buying.debit_notes.create_title')}</h2>
                            <button className="modal-close" onClick={() => setShowCreate(false)}>✕</button>
                        </div>
                        <div style={{ padding: 20 }}>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 20 }}>
                                <div>
                                    <label className="form-label">{t('common.supplier')} *</label>
                                    <select className="form-input" value={form.party_id} onChange={e => {
                                        setForm(f => ({ ...f, party_id: e.target.value, related_invoice_id: '' }))
                                        loadSupplierInvoices(e.target.value)
                                    }}>
                                        <option value="">{t('buying.debit_notes.choose_supplier')}</option>
                                        {suppliers.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                                    </select>
                                </div>
                                <div>
                                    <label className="form-label">{t('buying.debit_notes.related_purchase_invoice')}</label>
                                    <select className="form-input" value={form.related_invoice_id} onChange={e => setForm(f => ({ ...f, related_invoice_id: e.target.value }))}>
                                        <option value="">{t('buying.debit_notes.no_link')}</option>
                                        {purchaseInvoices.map(inv => <option key={inv.id} value={inv.id}>{inv.invoice_number} - {formatNumber(inv.total)} {currency}</option>)}
                                    </select>
                                </div>
                                <div>
                                    <label className="form-label">{t('common.date')}</label>
                                    <DateInput className="form-input" value={form.invoice_date}
                                        onChange={e => setForm(f => ({ ...f, invoice_date: e.target.value }))} />
                                </div>
                                <div>
                                    <label className="form-label">{t('common.notes')}</label>
                                    <input className="form-input" value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} />
                                </div>
                            </div>

                            <h3 style={{ marginBottom: 12 }}>{t('buying.debit_notes.items')}</h3>
                            <div className="invoice-items-container" style={{ margin: '12px 0', border: '1px solid var(--border-color)', borderRadius: '8px', overflow: 'hidden' }}>
                                <table className="data-table">
                                    <thead style={{ background: 'var(--bg-secondary)' }}>
                                        <tr>
                                            <th style={{ width: '25%' }}>{t('common.product')}</th>
                                            <th style={{ width: '20%' }}>{t('common.description')}</th>
                                            <th style={{ width: '10%' }}>{t('common.quantity')}</th>
                                            <th style={{ width: '12%' }}>{t('common.price')}</th>
                                            <th style={{ width: '10%' }}>{t('buying.debit_notes.tax_percent')}</th>
                                            <th style={{ width: '10%' }}>{t('common.discount')}</th>
                                            <th style={{ width: '10%' }}>{t('common.total')}</th>
                                            <th style={{ width: '3%' }}></th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {form.lines.map((line, i) => (
                                            <tr key={i}>
                                                <td>
                                                    <select className="form-input" value={line.product_id || ''} onChange={e => updateLine(i, 'product_id', e.target.value)}>
                                                        <option value="">{t('buying.debit_notes.select_product')}</option>
                                                        {products.map(p => <option key={p.id} value={p.id}>{p.item_name || p.name}</option>)}
                                                    </select>
                                                </td>
                                                <td><input className="form-input" value={line.description} onChange={e => updateLine(i, 'description', e.target.value)} /></td>
                                                <td><input className="form-input" type="text" inputMode="decimal" value={line.quantity} onChange={e => updateLine(i, 'quantity', e.target.value)} /></td>
                                                <td><input className="form-input" type="text" inputMode="decimal" value={line.unit_price} onChange={e => updateLine(i, 'unit_price', e.target.value)} /></td>
                                                <td style={{ textAlign: 'center' }}>{backendLines?.[i]?.tax_rate ?? '—'}</td>
                                                <td><input className="form-input" type="text" inputMode="decimal" value={line.discount} onChange={e => updateLine(i, 'discount', e.target.value)} /></td>
                                                <td style={{ fontWeight: 'bold', textAlign: 'center' }}>{backendLineTotal(i) != null ? formatNumber(backendLineTotal(i)) : '—'}</td>
                                                <td><button className="btn btn-sm" style={{ color: 'red', background: 'none', border: 'none' }} onClick={() => removeLine(i)}>✕</button></td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                            <button className="btn btn-secondary" style={{ marginTop: 8 }} onClick={addLine}>+ {t('buying.debit_notes.add_line')}</button>

                            <div style={{ marginTop: 20, display: 'flex', justifyContent: 'flex-end' }}>
                                <div style={{ minWidth: 250, background: 'var(--card-bg)', padding: 16, borderRadius: 8 }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}><span>{t('common.amount')}:</span><strong>{summarySubtotal != null ? formatNumber(summarySubtotal) : '—'} {currency}</strong></div>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}><span>{t('buying.debit_notes.tax')}:</span><strong>{summaryTax != null ? formatNumber(summaryTax) : '—'} {currency}</strong></div>
                                    <hr />
                                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 18, fontWeight: 'bold' }}><span>{t('common.total')}:</span><span>{summaryTotal != null ? formatNumber(summaryTotal) : '—'} {currency}</span></div>
                                </div>
                            </div>

                            <div style={{ marginTop: 24, display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
                                <button className="btn btn-secondary" onClick={() => setShowCreate(false)}>{t('common.cancel')}</button>
                                <button className="btn btn-primary" onClick={handleCreate} disabled={saving}>
                                    {saving ? t('buying.debit_notes.saving') : t('buying.debit_notes.create_debit_note')}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Detail Modal */}
            {showDetail && detailItem && (
                <div className="modal-overlay" onClick={() => setShowDetail(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 800, maxHeight: '90vh', overflow: 'auto' }}>
                        <div className="modal-header">
                            <h2>{t('buying.debit_notes.detail_title')}: {detailItem.invoice_number}</h2>
                            <button className="modal-close" onClick={() => setShowDetail(false)}>✕</button>
                        </div>
                        <div style={{ padding: 20 }}>
                            <div className="metrics-grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', marginBottom: 20 }}>
                                <div className="metric-card"><div className="metric-label">{t('common.supplier')}</div><div className="metric-value" style={{ fontSize: 16 }}>{detailItem.party_name}</div></div>
                                <div className="metric-card"><div className="metric-label">{t('common.date')}</div><div className="metric-value" style={{ fontSize: 16 }}>{formatShortDate(detailItem.invoice_date)}</div></div>
                                <div className="metric-card"><div className="metric-label">{t('common.total')}</div><div className="metric-value text-primary" style={{ fontSize: 18 }}>{formatNumber(detailItem.total)} {currency}</div></div>
                                <div className="metric-card"><div className="metric-label">{t('common.status_title')}</div><div className="metric-value" style={{ fontSize: 16 }}>{statusBadge(detailItem.status)}</div></div>
                            </div>
                            {detailItem.related_invoice_number && <p style={{ marginBottom: 12 }}>🔗 {t('buying.debit_notes.linked_to_invoice')}: <strong>{detailItem.related_invoice_number}</strong></p>}
                            {detailItem.notes && <p style={{ marginBottom: 16, color: '#666' }}>📝 {detailItem.notes}</p>}
                            <table className="data-table">
                                <thead><tr><th>{t('common.description')}</th><th>{t('common.quantity')}</th><th>{t('common.price')}</th><th>{t('buying.debit_notes.tax_percent')}</th><th>{t('common.discount')}</th><th>{t('common.total')}</th></tr></thead>
                                <tbody>
                                    {(detailItem.lines || []).map((l, i) => (
                                        <tr key={i}>
                                            <td>{l.product_name || l.description}</td>
                                            <td>{l.quantity}</td>
                                            <td>{formatNumber(l.unit_price)}</td>
                                            <td>{l.tax_rate}%</td>
                                            <td>{formatNumber(l.discount || 0)}</td>
                                            <td style={{ fontWeight: 'bold' }}>{formatNumber(l.total)}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                            <div style={{ marginTop: 16, display: 'flex', justifyContent: 'flex-end' }}>
                                <div style={{ minWidth: 200 }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>{t('common.amount')}:</span><span>{formatNumber(detailItem.subtotal)}</span></div>
                                    <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>{t('buying.debit_notes.tax')}:</span><span>{formatNumber(detailItem.tax_amount)}</span></div>
                                    <hr />
                                    <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 'bold', fontSize: 16 }}><span>{t('common.total')}:</span><span>{formatNumber(detailItem.total)} {currency}</span></div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}

export default PurchaseDebitNotes
