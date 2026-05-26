import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { inventoryAPI } from '../../utils/api'
import { useBranch } from '../../context/BranchContext'
import { formatShortDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';


function QualityInspections() {
    const { t } = useTranslation()
    const { currentBranch } = useBranch()
    const [inspections, setInspections] = useState([])
    const [loading, setLoading] = useState(true)
    const [initialLoad, setInitialLoad] = useState(true)
    const [statusFilter, setStatusFilter] = useState('')
    const [typeFilter, setTypeFilter] = useState('')
    const [products, setProducts] = useState([])
    const [warehouses, setWarehouses] = useState([])
    const [batches, setBatches] = useState([])
    const [showCreateModal, setShowCreateModal] = useState(false)
    const [showCompleteModal, setShowCompleteModal] = useState(false)
    const [selectedInspection, setSelectedInspection] = useState(null)
    const [total, setTotal] = useState(0)
    const [summary, setSummary] = useState({})

    const [form, setForm] = useState({
        product_id: '',
        warehouse_id: '',
        batch_id: '',
        inspection_type: 'incoming',
        sample_size: '',
        notes: '',
        criteria: [{ criteria_name: '', expected_value: '', min_value: '', max_value: '' }]
    })

    const [completeForm, setCompleteForm] = useState({
        result: 'passed',
        defect_quantity: 0,
        inspector_notes: ''
    })

    const [saving, setSaving] = useState(false)
    const [error, setError] = useState(null)

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchInspections()
            fetchProducts()
            fetchWarehouses()
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch, statusFilter, typeFilter])

    const fetchInspections = async () => {
        try {
            setLoading(true)
            const params = { limit: 100 }
            if (statusFilter) params.status = statusFilter
            if (typeFilter) params.inspection_type = typeFilter
            const res = await inventoryAPI.listQualityInspections(params)
            setInspections(res.data.items || [])
            setTotal(res.data.total || 0)
            setSummary(res.data.summary || {})
        } catch (err) {
            console.error(err)
        } finally {
            setLoading(false)
            setInitialLoad(false)
        }
    }

    const fetchProducts = async () => {
        try {
            const res = await inventoryAPI.listProducts({ limit: 500, branch_id: currentBranch?.id })
            setProducts(res.data || [])
        } catch (err) { console.error(err) }
    }

    const fetchWarehouses = async () => {
        try {
            const res = await inventoryAPI.listWarehouses({ branch_id: currentBranch?.id })
            setWarehouses(res.data || [])
        } catch (err) { console.error(err) }
    }

    const addCriteria = () => {
        setForm({ ...form, criteria: [...form.criteria, { criteria_name: '', expected_value: '', min_value: '', max_value: '' }] })
    }

    const removeCriteria = (index) => {
        const updated = form.criteria.filter((_, i) => i !== index)
        setForm({ ...form, criteria: updated })
    }

    const updateCriteria = (index, field, value) => {
        const updated = [...form.criteria]
        updated[index][field] = value
        setForm({ ...form, criteria: updated })
    }

    const handleCreate = async (e) => {
        e.preventDefault()
        setSaving(true)
        setError(null)
        try {
            await inventoryAPI.createQualityInspection({
                product_id: parseInt(form.product_id),
                warehouse_id: parseInt(form.warehouse_id),
                batch_id: form.batch_id ? parseInt(form.batch_id) : null,
                inspection_type: form.inspection_type,
                sample_size: form.sample_size ? parseInt(form.sample_size) : null,
                notes: form.notes || null,
                criteria: form.criteria.filter(c => c.criteria_name).map(c => ({
                    ...c,
                    min_value: c.min_value ? String(c.min_value) : null,
                    max_value: c.max_value ? String(c.max_value) : null
                }))
            })
            setShowCreateModal(false)
            setForm({
                product_id: '', warehouse_id: '', batch_id: '', inspection_type: 'incoming',
                sample_size: '', notes: '',
                criteria: [{ criteria_name: '', expected_value: '', min_value: '', max_value: '' }]
            })
            fetchInspections()
        } catch (err) {
            setError(err.response?.data?.detail || t('common.error_occurred'))
        } finally {
            setSaving(false)
        }
    }

    const openCompleteModal = (inspection) => {
        setSelectedInspection(inspection)
        setCompleteForm({ result: 'passed', defect_quantity: 0, inspector_notes: '' })
        setShowCompleteModal(true)
    }

    const handleComplete = async (e) => {
        e.preventDefault()
        setSaving(true)
        setError(null)
        try {
            await inventoryAPI.completeQualityInspection(selectedInspection.id, {
                status: completeForm.result === 'conditional' ? 'partial' : completeForm.result,
                rejected_quantity: String(completeForm.defect_quantity || 0),
                result_notes: completeForm.inspector_notes || null
            })
            setShowCompleteModal(false)
            setSelectedInspection(null)
            fetchInspections()
        } catch (err) {
            setError(err.response?.data?.detail || t('common.error_occurred'))
        } finally {
            setSaving(false)
        }
    }

    const getStatusBadge = (status) => {
        const map = {
            pending: { label: t('stock.quality.pending'), cls: 'badge-warning' },
            in_progress: { label: t('stock.quality.in_progress'), cls: 'badge-primary' },
            completed: { label: t('stock.quality.completed'), cls: 'badge-success' },
            failed: { label: t('stock.quality.status_failed'), cls: 'badge-danger' }
        }
        const s = map[status] || { label: status, cls: 'badge-secondary' }
        return <span className={`badge ${s.cls}`}>{s.label}</span>
    }

    const getResultBadge = (result) => {
        if (!result) return '-'
        const map = {
            passed: { label: `✅ ${t('stock.quality.result_passed')}`, cls: 'badge-success' },
            failed: { label: `❌ ${t('stock.quality.result_failed')}`, cls: 'badge-danger' },
            conditional: { label: `⚠️ ${t('stock.quality.result_conditional')}`, cls: 'badge-warning' },
            partial: { label: `⚠️ ${t('stock.quality.result_conditional')}`, cls: 'badge-warning' }
        }
        const s = map[result] || { label: result, cls: 'badge-secondary' }
        return <span className={`badge ${s.cls}`}>{s.label}</span>
    }

    const getTypeName = (type) => {
        const map = { incoming: t('stock.quality.incoming'), outgoing: t('stock.quality.outgoing'), in_process: t('stock.quality.in_process'), random: t('stock.quality.random') }
        return map[type] || type
    }

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div>
                    <h1 className="workspace-title">🔬 {t('stock.quality.title')}</h1>
                    <p className="workspace-subtitle">{t('stock.quality.subtitle')}</p>
                </div>
                <button className="btn btn-primary" onClick={() => setShowCreateModal(true)}>
                    + {t('stock.quality.create_new')}
                </button>
            </div>

            {/* Stats */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', marginBottom: '24px' }}>
                <div className="card p-3 text-center">
                    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mx-auto mb-2 text-primary">
                        <path d="M9 11a3 3 0 1 0 6 0a3 3 0 0 0 -6 0"/>
                        <path d="M17.8 20a9 9 0 1 0 -11.6 0"/>
                    </svg>
                    <div className="small text-muted">{t('stock.quality.total_inspections')}</div>
                    <div className="fw-bold fs-4">{total}</div>
                </div>
                <div className="card p-3 text-center">
                    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mx-auto mb-2 text-warning">
                        <circle cx="12" cy="12" r="10"/>
                        <path d="M12 6v6l4 2"/>
                    </svg>
                    <div className="small text-muted">{t('stock.quality.pending')}</div>
                    <div className="fw-bold fs-4 text-warning">
                        {summary.pending_count || 0}
                    </div>
                </div>
                <div className="card p-3 text-center">
                    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mx-auto mb-2 text-success">
                        <path d="M21.801 10A10 10 0 1 1 17 3.335"/>
                        <path d="m9 11 3 3L22 4"/>
                    </svg>
                    <div className="small text-muted">{t('stock.quality.passed')}</div>
                    <div className="fw-bold fs-4 text-success">
                        {summary.passed_count || 0}
                    </div>
                </div>
                <div className="card p-3 text-center">
                    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mx-auto mb-2 text-danger">
                        <circle cx="12" cy="12" r="10"/>
                        <path d="m15 9-6 6"/>
                        <path d="m9 9 6 6"/>
                    </svg>
                    <div className="small text-muted">{t('stock.quality.failed')}</div>
                    <div className="fw-bold fs-4 text-danger">
                        {summary.failed_count || 0}
                    </div>
                </div>
            </div>

            {/* Filters */}
            <div className="card mb-4">
                <div className="form-row" style={{ gap: '12px', flexWrap: 'wrap' }}>
                    <select className="form-input" style={{ maxWidth: '180px' }}
                        value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                        <option value="">{t('common.all_statuses')}</option>
                        <option value="pending">{t('stock.quality.pending')}</option>
                        <option value="in_progress">{t('stock.quality.in_progress')}</option>
                        <option value="completed">{t('stock.quality.completed')}</option>
                    </select>
                    <select className="form-input" style={{ maxWidth: '180px' }}
                        value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
                        <option value="">{t('stock.quality.all_types')}</option>
                        <option value="incoming">{t('stock.quality.incoming')}</option>
                        <option value="outgoing">{t('stock.quality.outgoing')}</option>
                        <option value="in_process">{t('stock.quality.in_process')}</option>
                        <option value="random">{t('stock.quality.random')}</option>
                    </select>
                </div>
            </div>

            {/* Table */}
            <div className="card">
                <div className="invoice-items-container">
                    <table className="data-table">
                        <thead>
                            <tr style={{ background: 'var(--bg-secondary)' }}>
                                <th style={{ width: '10%' }}>{t('stock.quality.inspection_number')}</th>
                                <th style={{ width: '18%' }}>{t('common.product')}</th>
                                <th style={{ width: '12%' }}>{t('stock.quality.warehouse')}</th>
                                <th style={{ width: '10%' }}>{t('stock.quality.type')}</th>
                                <th style={{ width: '10%' }}>{t('stock.quality.sample_size')}</th>
                                <th style={{ width: '10%' }}>{t('common.status_title')}</th>
                                <th style={{ width: '10%' }}>{t('stock.quality.result')}</th>
                                <th style={{ width: '12%' }}>{t('stock.quality.date')}</th>
                                <th style={{ width: '8%' }}>{t('common.actions')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {loading ? (
                                <tr><td colSpan="9" style={{ textAlign: 'center', padding: '40px' }}>{t('common.loading')}</td></tr>
                            ) : inspections.length === 0 ? (
                                <tr><td colSpan="9" style={{ textAlign: 'center', padding: '40px', color: 'var(--text-secondary)' }}>
                                    {t('stock.quality.no_inspections')}
                                </td></tr>
                            ) : inspections.map(insp => (
                                <tr key={insp.id}>
                                    <td><strong>{insp.inspection_number}</strong></td>
                                    <td>{insp.product_name}</td>
                                    <td>{insp.warehouse_name}</td>
                                    <td>{getTypeName(insp.inspection_type)}</td>
                                    <td>{insp.sample_size || '-'}</td>
                                    <td>{getStatusBadge(insp.status)}</td>
                                    <td>{getResultBadge(insp.result)}</td>
                                    <td>{insp.created_at ? formatShortDate(insp.created_at) : '-'}</td>
                                    <td>
                                        {insp.status !== 'completed' && (
                                            <button className="btn btn-sm btn-primary"
                                                onClick={() => openCompleteModal(insp)}
                                                title={t('stock.quality.complete_inspection')}>
                                                ✓
                                            </button>
                                        )}
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
                        style={{ maxWidth: '800px', width: '95%', maxHeight: '90vh', overflowY: 'auto' }}>
                        <div className="modal-header">
                            <h2>{t('stock.quality.create_inspection')}</h2>
                            <button className="modal-close" onClick={() => setShowCreateModal(false)}>✕</button>
                        </div>
                        <form onSubmit={handleCreate}>
                            {error && <div className="alert alert-error mb-4">{error}</div>}
                            <div className="form-row">
                                <div className="form-group">
                                    <label className="form-label">{t('common.product')} *</label>
                                    <select className="form-input" required value={form.product_id}
                                        onChange={(e) => setForm({ ...form, product_id: e.target.value })}>
                                        <option value="">{t('stock.quality.select_product')}</option>
                                        {products.filter(p => p.item_type === 'product').map(p => (
                                            <option key={p.id} value={p.id}>{p.item_name} ({p.item_code})</option>
                                        ))}
                                    </select>
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('stock.quality.warehouse')} *</label>
                                    <select className="form-input" required value={form.warehouse_id}
                                        onChange={(e) => setForm({ ...form, warehouse_id: e.target.value })}>
                                        <option value="">{t('stock.quality.select_warehouse')}</option>
                                        {warehouses.map(w => (
                                            <option key={w.id} value={w.id}>{w.warehouse_name}</option>
                                        ))}
                                    </select>
                                </div>
                            </div>
                            <div className="form-row">
                                <div className="form-group">
                                    <label className="form-label">{t('stock.quality.inspection_type')}</label>
                                    <select className="form-input" value={form.inspection_type}
                                        onChange={(e) => setForm({ ...form, inspection_type: e.target.value })}>
                                        <option value="incoming">{t('stock.quality.incoming')}</option>
                                        <option value="outgoing">{t('stock.quality.outgoing')}</option>
                                        <option value="in_process">{t('stock.quality.in_process')}</option>
                                        <option value="random">{t('stock.quality.random')}</option>
                                    </select>
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('stock.quality.sample_size')}</label>
                                    <input type="number" className="form-input" min="1"
                                        value={form.sample_size}
                                        onChange={(e) => setForm({ ...form, sample_size: e.target.value })} />
                                </div>
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('common.notes')}</label>
                                <textarea className="form-input" rows="2" value={form.notes}
                                    onChange={(e) => setForm({ ...form, notes: e.target.value })} />
                            </div>

                            {/* Criteria */}
                            <div style={{ marginTop: '20px' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                                    <h3>{t('stock.quality.criteria')}</h3>
                                    <button type="button" className="btn btn-sm btn-secondary" onClick={addCriteria}>
                                        + {t('stock.quality.add_criteria')}
                                    </button>
                                </div>
                                {form.criteria.map((c, i) => (
                                    <div key={i} className="form-row" style={{ alignItems: 'flex-end', gap: '8px', marginBottom: '8px' }}>
                                        <div className="form-group" style={{ flex: 2 }}>
                                            {i === 0 && <label className="form-label">{t('stock.quality.criteria_name')}</label>}
                                            <input type="text" className="form-input" value={c.criteria_name}
                                                onChange={(e) => updateCriteria(i, 'criteria_name', e.target.value)}
                                                placeholder={t('stock.quality.criteria_placeholder')} />
                                        </div>
                                        <div className="form-group" style={{ flex: 1.5 }}>
                                            {i === 0 && <label className="form-label">{t('stock.quality.expected_value')}</label>}
                                            <input type="text" className="form-input" value={c.expected_value}
                                                onChange={(e) => updateCriteria(i, 'expected_value', e.target.value)} />
                                        </div>
                                        <div className="form-group" style={{ flex: 1 }}>
                                            {i === 0 && <label className="form-label">{t('stock.quality.min_value')}</label>}
                                            <input type="number" step="0.01" className="form-input" value={c.min_value}
                                                onChange={(e) => updateCriteria(i, 'min_value', e.target.value)} />
                                        </div>
                                        <div className="form-group" style={{ flex: 1 }}>
                                            {i === 0 && <label className="form-label">{t('stock.quality.max_value')}</label>}
                                            <input type="number" step="0.01" className="form-input" value={c.max_value}
                                                onChange={(e) => updateCriteria(i, 'max_value', e.target.value)} />
                                        </div>
                                        {form.criteria.length > 1 && (
                                            <button type="button" className="btn btn-sm btn-danger"
                                                onClick={() => removeCriteria(i)} style={{ marginBottom: '4px' }}>✕</button>
                                        )}
                                    </div>
                                ))}
                            </div>

                            <div style={{ display: 'flex', gap: '12px', marginTop: '20px' }}>
                                <button type="submit" className="btn btn-primary" disabled={saving}>
                                    {saving ? t('common.saving') : t('stock.quality.create_btn')}
                                </button>
                                <button type="button" className="btn btn-secondary" onClick={() => setShowCreateModal(false)}>
                                    {t('common.cancel')}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* Complete Modal */}
            {showCompleteModal && selectedInspection && (
                <div className="modal-overlay" onClick={() => setShowCompleteModal(false)}>
                    <div className="modal-content" onClick={(e) => e.stopPropagation()}
                        style={{ maxWidth: '500px', width: '90%' }}>
                        <div className="modal-header">
                            <h2>{t('stock.quality.complete_inspection')} - {selectedInspection.inspection_number}</h2>
                            <button className="modal-close" onClick={() => setShowCompleteModal(false)}>✕</button>
                        </div>
                        <form onSubmit={handleComplete}>
                            {error && <div className="alert alert-error mb-4">{error}</div>}
                            <div className="form-group">
                                <label className="form-label">{t('stock.quality.result')} *</label>
                                <select className="form-input" required value={completeForm.result}
                                    onChange={(e) => setCompleteForm({ ...completeForm, result: e.target.value })}>
                                    <option value="passed">✅ {t('stock.quality.result_passed')}</option>
                                    <option value="failed">❌ {t('stock.quality.result_failed')}</option>
                                    <option value="conditional">⚠️ {t('stock.quality.result_conditional')}</option>
                                </select>
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('stock.quality.defect_quantity')}</label>
                                <input type="number" className="form-input" min="0"
                                    value={completeForm.defect_quantity}
                                    onChange={(e) => setCompleteForm({ ...completeForm, defect_quantity: e.target.value })} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('stock.quality.inspector_notes')}</label>
                                <textarea className="form-input" rows="3" value={completeForm.inspector_notes}
                                    onChange={(e) => setCompleteForm({ ...completeForm, inspector_notes: e.target.value })} />
                            </div>
                            <div style={{ display: 'flex', gap: '12px', marginTop: '20px' }}>
                                <button type="submit" className="btn btn-primary" disabled={saving}>
                                    {saving ? t('common.saving') : t('stock.quality.complete_inspection')}
                                </button>
                                <button type="button" className="btn btn-secondary" onClick={() => setShowCompleteModal(false)}>
                                    {t('common.cancel')}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    )
}

export default QualityInspections
