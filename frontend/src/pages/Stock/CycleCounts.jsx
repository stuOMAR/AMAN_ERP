import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { inventoryAPI } from '../../utils/api'
import { useBranch } from '../../context/BranchContext'
import { formatShortDate } from '../../utils/dateUtils';
import { formatNumber } from '../../utils/format';
import BackButton from '../../components/common/BackButton';
import { useToast } from '../../context/ToastContext'


function CycleCounts() {
    const { t } = useTranslation()
  const { showToast } = useToast()
    const { currentBranch } = useBranch()
    const [cycleCounts, setCycleCounts] = useState([])
    const [loading, setLoading] = useState(true)
    const [initialLoad, setInitialLoad] = useState(true)
    const [statusFilter, setStatusFilter] = useState('')
    const [warehouses, setWarehouses] = useState([])
    const [products, setProducts] = useState([])
    const [showCreateModal, setShowCreateModal] = useState(false)
    const [showDetailModal, setShowDetailModal] = useState(false)
    const [selectedCount, setSelectedCount] = useState(null)
    const [countDetail, setCountDetail] = useState(null)
    const [total, setTotal] = useState(0)
    const [summary, setSummary] = useState({})

    const [form, setForm] = useState({
        warehouse_id: '',
        count_type: 'full',
        product_ids: [],
        notes: ''
    })

    const [itemUpdates, setItemUpdates] = useState([])
    const [saving, setSaving] = useState(false)
    const [error, setError] = useState(null)

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchCycleCounts()
            fetchWarehouses()
            fetchProducts()
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch, statusFilter])

    const fetchCycleCounts = async () => {
        try {
            setLoading(true)
            const params = { limit: 100 }
            if (statusFilter) params.status = statusFilter
            const res = await inventoryAPI.listCycleCounts(params)
            setCycleCounts(res.data.items || [])
            setTotal(res.data.total || 0)
            setSummary(res.data.summary || {})
        } catch (err) {
            console.error(err)
        } finally {
            setLoading(false)
            setInitialLoad(false)
        }
    }

    const fetchWarehouses = async () => {
        try {
            const res = await inventoryAPI.listWarehouses({ branch_id: currentBranch?.id })
            setWarehouses(res.data || [])
        } catch (err) { console.error(err) }
    }

    const fetchProducts = async () => {
        try {
            const res = await inventoryAPI.listProducts({ limit: 500, branch_id: currentBranch?.id })
            setProducts(res.data || [])
        } catch (err) { console.error(err) }
    }

    const handleCreate = async (e) => {
        e.preventDefault()
        setSaving(true)
        setError(null)
        try {
            await inventoryAPI.createCycleCount({
                warehouse_id: parseInt(form.warehouse_id),
                count_type: form.count_type,
                product_ids: form.product_ids.map(id => parseInt(id)),
                notes: form.notes || null
            })
            setShowCreateModal(false)
            setForm({ warehouse_id: '', count_type: 'full', product_ids: [], notes: '' })
            fetchCycleCounts()
        } catch (err) {
            setError(err.response?.data?.detail || t('common.error_occurred'))
        } finally {
            setSaving(false)
        }
    }

    const handleStart = async (id) => {
        try {
            await inventoryAPI.startCycleCount(id)
            fetchCycleCounts()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error_occurred', 'error'))
        }
    }

    const openDetail = async (cc) => {
        setSelectedCount(cc)
        try {
            const res = await inventoryAPI.getCycleCount(cc.id)
            setCountDetail(res.data)
            const items = (res.data.items || []).map(item => ({
                item_id: item.id,
                counted_quantity: item.counted_quantity ?? item.system_quantity ?? 0,
                notes: item.notes || ''
            }))
            setItemUpdates(items)
            setShowDetailModal(true)
        } catch (err) {
            showToast(t('stock.cycle.error_loading', 'error'))
        }
    }

    const updateItemCount = (itemId, field, value) => {
        setItemUpdates(prev => prev.map(item =>
            item.item_id === itemId ? { ...item, [field]: value } : item
        ))
    }

    const handleComplete = async () => {
        setSaving(true)
        setError(null)
        try {
            await inventoryAPI.completeCycleCount(selectedCount.id, {
                items: itemUpdates.map(item => ({
                    ...item,
                    counted_quantity: String(item.counted_quantity || 0)
                }))
            })
            setShowDetailModal(false)
            setSelectedCount(null)
            setCountDetail(null)
            fetchCycleCounts()
        } catch (err) {
            setError(err.response?.data?.detail || t('common.error_occurred'))
        } finally {
            setSaving(false)
        }
    }

    const getStatusBadge = (status) => {
        const map = {
            draft: { label: t('stock.cycle.draft'), cls: 'badge-secondary' },
            in_progress: { label: t('stock.cycle.in_progress'), cls: 'badge-warning' },
            completed: { label: t('stock.cycle.completed'), cls: 'badge-success' },
            cancelled: { label: t('stock.cycle.cancelled'), cls: 'badge-danger' }
        }
        const s = map[status] || { label: status, cls: 'badge-secondary' }
        return <span className={`badge ${s.cls}`}>{s.label}</span>
    }

    const getCountTypeName = (type) => {
        const map = { full: t('stock.cycle.full_count'), partial: t('stock.cycle.partial_count'), random: t('stock.cycle.random_count') }
        return map[type] || type
    }

    const toggleProductSelect = (productId) => {
        const id = String(productId)
        setForm(prev => ({
            ...prev,
            product_ids: prev.product_ids.includes(id)
                ? prev.product_ids.filter(p => p !== id)
                : [...prev.product_ids, id]
        }))
    }

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div>
                    <h1 className="workspace-title">📋 {t('stock.cycleCounts.title')}</h1>
                    <p className="workspace-subtitle">{t('stock.cycleCounts.subtitle')}</p>
                </div>
                <button className="btn btn-primary" onClick={() => setShowCreateModal(true)}>
                    + {t('stock.cycle.create_new')}
                </button>
            </div>

            {/* Stats */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', marginBottom: '24px' }}>
                <div className="card p-3 text-center">
                    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mx-auto mb-2 text-primary">
                        <path d="M3 3v18h18"/>
                        <path d="m19 9-5 5-4-4-3 3"/>
                    </svg>
                    <div className="small text-muted">{t('stock.cycle.total_counts')}</div>
                    <div className="fw-bold fs-4">{total}</div>
                </div>
                <div className="card p-3 text-center">
                    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mx-auto mb-2 text-warning">
                        <path d="M12 2v20"/>
                        <path d="m15 19-3 3-3-3"/>
                        <path d="m19 15 3-3-3-3"/>
                        <circle cx="12" cy="12" r="3"/>
                    </svg>
                    <div className="small text-muted">{t('stock.cycle.in_progress')}</div>
                    <div className="fw-bold fs-4 text-warning">
                        {summary.in_progress_count || 0}
                    </div>
                </div>
                <div className="card p-3 text-center">
                    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mx-auto mb-2 text-success">
                        <path d="M21.801 10A10 10 0 1 1 17 3.335"/>
                        <path d="m9 11 3 3L22 4"/>
                    </svg>
                    <div className="small text-muted">{t('stock.cycle.completed')}</div>
                    <div className="fw-bold fs-4 text-success">
                        {summary.completed_count || 0}
                    </div>
                </div>
                <div className="card p-3 text-center">
                    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mx-auto mb-2 text-primary">
                        <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/>
                        <polyline points="14 2 14 8 20 8"/>
                    </svg>
                    <div className="small text-muted">{t('stock.cycle.drafts')}</div>
                    <div className="fw-bold fs-4 text-primary">
                        {summary.draft_count || 0}
                    </div>
                </div>
            </div>

            {/* Filters */}
            <div className="card mb-4">
                <div className="form-row" style={{ gap: '12px', flexWrap: 'wrap' }}>
                    <select className="form-input" style={{ maxWidth: '180px' }}
                        value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                        <option value="">{t('common.all_statuses')}</option>
                        <option value="draft">{t('stock.cycle.draft')}</option>
                        <option value="in_progress">{t('stock.cycle.in_progress')}</option>
                        <option value="completed">{t('stock.cycle.completed')}</option>
                    </select>
                </div>
            </div>

            {/* Table */}
            <div className="card">
                <div className="invoice-items-container">
                    <table className="data-table">
                        <thead>
                            <tr style={{ background: 'var(--bg-secondary)' }}>
                                <th style={{ width: '12%' }}>{t('stock.cycle.count_number')}</th>
                                <th style={{ width: '15%' }}>{t('stock.cycle.warehouse')}</th>
                                <th style={{ width: '12%' }}>{t('stock.cycle.type')}</th>
                                <th style={{ width: '10%' }}>{t('stock.cycle.items_count')}</th>
                                <th style={{ width: '10%' }}>{t('stock.cycle.variances')}</th>
                                <th style={{ width: '10%' }}>{t('common.status_title')}</th>
                                <th style={{ width: '15%' }}>{t('stock.cycle.date')}</th>
                                <th style={{ width: '16%' }}>{t('common.actions')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {loading ? (
                                <tr><td colSpan="8" style={{ textAlign: 'center', padding: '40px' }}>{t('common.loading')}</td></tr>
                            ) : cycleCounts.length === 0 ? (
                                <tr><td colSpan="8" style={{ textAlign: 'center', padding: '40px', color: 'var(--text-secondary)' }}>
                                    {t('stock.cycle.no_counts')}
                                </td></tr>
                            ) : cycleCounts.map(cc => (
                                <tr key={cc.id}>
                                    <td><strong>{cc.count_number}</strong></td>
                                    <td>{cc.warehouse_name}</td>
                                    <td>{getCountTypeName(cc.count_type)}</td>
                                    <td>{cc.total_items || '-'}</td>
                                    <td>
                                        {cc.total_variance != null ? (
                                            <span style={{ color: cc.has_variance ? 'var(--danger)' : 'var(--success)' }}>
                                                {cc.total_variance}
                                            </span>
                                        ) : '-'}
                                    </td>
                                    <td>{getStatusBadge(cc.status)}</td>
                                    <td>{cc.created_at ? formatShortDate(cc.created_at) : '-'}</td>
                                    <td>
                                        <div style={{ display: 'flex', gap: '6px' }}>
                                            {cc.status === 'draft' && (
                                                <button className="btn btn-sm btn-primary" onClick={() => handleStart(cc.id)}>
                                                    ▶ {t('stock.cycle.start_count')}
                                                </button>
                                            )}
                                            {cc.status === 'in_progress' && (
                                                <button className="btn btn-sm btn-success" onClick={() => openDetail(cc)}>
                                                    📝 {t('stock.cycle.record_count')}
                                                </button>
                                            )}
                                            {cc.status === 'completed' && (
                                                <button className="btn btn-sm btn-secondary" onClick={() => openDetail(cc)}>
                                                    👁 {t('stock.cycle.view')}
                                                </button>
                                            )}
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>

            {/* Create Modal */}
            {showCreateModal && (
                <div className="modal-overlay" onClick={() => setShowCreateModal(false)}>
                    <div className="modal-content" onClick={(e) => e.stopPropagation()}
                        style={{ maxWidth: '700px', width: '90%', maxHeight: '90vh', overflowY: 'auto' }}>
                        <div className="modal-header">
                            <h2>{t('stock.cycle.create_count')}</h2>
                            <button className="modal-close" onClick={() => setShowCreateModal(false)}>✕</button>
                        </div>
                        <form onSubmit={handleCreate}>
                            {error && <div className="alert alert-error mb-4">{error}</div>}
                            <div className="form-row">
                                <div className="form-group">
                                    <label className="form-label">{t('stock.cycle.warehouse')} *</label>
                                    <select className="form-input" required value={form.warehouse_id}
                                        onChange={(e) => setForm({ ...form, warehouse_id: e.target.value })}>
                                        <option value="">{t('stock.cycle.select_warehouse')}</option>
                                        {warehouses.map(w => (
                                            <option key={w.id} value={w.id}>{w.warehouse_name}</option>
                                        ))}
                                    </select>
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('stock.cycle.count_type')}</label>
                                    <select className="form-input" value={form.count_type}
                                        onChange={(e) => setForm({ ...form, count_type: e.target.value })}>
                                        <option value="full">{t('stock.cycle.full_count')}</option>
                                        <option value="partial">{t('stock.cycle.partial_count')}</option>
                                        <option value="random">{t('stock.cycle.random_count')}</option>
                                    </select>
                                </div>
                            </div>

                            {form.count_type === 'partial' && (
                                <div className="form-group">
                                    <label className="form-label">{t('stock.cycle.select_products')}</label>
                                    <div style={{ maxHeight: '200px', overflowY: 'auto', border: '1px solid var(--border)', borderRadius: '8px', padding: '8px' }}>
                                        {products.filter(p => p.item_type === 'product').map(p => (
                                            <label key={p.id} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '6px', cursor: 'pointer' }}>
                                                <input type="checkbox" checked={form.product_ids.includes(String(p.id))}
                                                    onChange={() => toggleProductSelect(p.id)} />
                                                {p.item_name} ({p.item_code})
                                            </label>
                                        ))}
                                    </div>
                                    <small style={{ color: 'var(--text-secondary)' }}>{t('stock.cycle.selected_products', { count: form.product_ids.length })}</small>
                                </div>
                            )}

                            <div className="form-group">
                                <label className="form-label">{t('common.notes')}</label>
                                <textarea className="form-input" rows="2" value={form.notes}
                                    onChange={(e) => setForm({ ...form, notes: e.target.value })} />
                            </div>

                            <div style={{ display: 'flex', gap: '12px', marginTop: '20px' }}>
                                <button type="submit" className="btn btn-primary" disabled={saving}>
                                    {saving ? t('common.creating') : t('stock.cycle.create_count_btn')}
                                </button>
                                <button type="button" className="btn btn-secondary" onClick={() => setShowCreateModal(false)}>
                                    {t('common.cancel')}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* Detail/Count Modal */}
            {showDetailModal && countDetail && (
                <div className="modal-overlay" onClick={() => setShowDetailModal(false)}>
                    <div className="modal-content" onClick={(e) => e.stopPropagation()}
                        style={{ maxWidth: '900px', width: '95%', maxHeight: '90vh', overflowY: 'auto' }}>
                        <div className="modal-header">
                            <h2>
                                {selectedCount?.status === 'in_progress' ? `📝 ${t('stock.cycle.record_count')}` : `👁 ${t('stock.cycle.detail_view')}`} - {countDetail.count_number}
                            </h2>
                            <button className="modal-close" onClick={() => setShowDetailModal(false)}>✕</button>
                        </div>

                        <div className="modules-grid" style={{ marginBottom: '16px', gap: '12px' }}>
                            <div><strong>{t('stock.cycle.warehouse')}:</strong> {countDetail.warehouse_name}</div>
                            <div><strong>{t('stock.cycle.type')}:</strong> {getCountTypeName(countDetail.count_type)}</div>
                            <div><strong>{t('common.status_title')}:</strong> {getStatusBadge(countDetail.status)}</div>
                        </div>

                        {error && <div className="alert alert-error mb-4">{error}</div>}

                        <div className="invoice-items-container">
                            <table className="data-table">
                                <thead>
                                    <tr style={{ background: 'var(--bg-secondary)' }}>
                                        <th>{t('common.product')}</th>
                                        <th>{t('stock.cycle.system_quantity')}</th>
                                        <th>{t('stock.cycle.actual_quantity')}</th>
                                        <th>{t('stock.cycle.variance')}</th>
                                        <th>{t('common.notes')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {(countDetail.items || []).map(item => {
                                        const update = itemUpdates.find(u => u.item_id === item.id)
                                        const variance = item.variance ?? '0'
                                        return (
                                            <tr key={item.id}>
                                                <td>{item.product_name}</td>
                                                <td>{formatNumber(item.system_quantity || 0)}</td>
                                                <td>
                                                    {selectedCount?.status === 'in_progress' ? (
                                                        <input type="number" className="form-input" min="0" step="0.01"
                                                            style={{ width: '120px' }}
                                                            value={update?.counted_quantity ?? ''}
                                                            onChange={(e) => updateItemCount(item.id, 'counted_quantity', e.target.value)} />
                                                    ) : (
                                                        formatNumber(item.counted_quantity || 0)
                                                    )}
                                                </td>
                                                <td>
                                                    <span style={{ color: item.has_variance ? 'var(--danger)' : 'var(--success)', fontWeight: 'bold' }}>
                                                        {selectedCount?.status === 'in_progress' ? '-' : `${item.variance_prefix || ''}${variance}`}
                                                    </span>
                                                </td>
                                                <td>
                                                    {selectedCount?.status === 'in_progress' ? (
                                                        <input type="text" className="form-input"
                                                            style={{ width: '150px' }}
                                                            value={update?.notes ?? ''}
                                                            onChange={(e) => updateItemCount(item.id, 'notes', e.target.value)}
                                                            placeholder={t('stock.cycle.variance_reason')} />
                                                    ) : (
                                                        item.notes || '-'
                                                    )}
                                                </td>
                                            </tr>
                                        )
                                    })}
                                </tbody>
                            </table>
                        </div>

                        {selectedCount?.status === 'in_progress' && (
                            <div style={{ display: 'flex', gap: '12px', marginTop: '20px' }}>
                                <button className="btn btn-success" onClick={handleComplete} disabled={saving}>
                                    {saving ? t('common.saving') : `✓ ${t('stock.cycle.complete_count')}`}
                                </button>
                                <button className="btn btn-secondary" onClick={() => setShowDetailModal(false)}>
                                    {t('common.cancel')}
                                </button>
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    )
}

export default CycleCounts
