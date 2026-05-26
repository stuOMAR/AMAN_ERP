import { useState, useEffect, Fragment } from 'react'
import { useTranslation } from 'react-i18next'
import { servicesAPI, salesAPI } from '../../utils/api'
import '../../components/ModuleStyles.css'
import { formatShortDate } from '../../utils/dateUtils'
import { formatNumber } from '../../utils/format'
import BackButton from '../../components/common/BackButton'
import DateInput from '../../components/common/DateInput';
import { useToast } from '../../context/ToastContext'

const statusBadgeStyles = {
    pending:     { background: '#6b7280', color: '#fff' },
    assigned:    { background: '#3b82f6', color: '#fff' },
    in_progress: { background: '#eab308', color: '#fff' },
    on_hold:     { background: '#f97316', color: '#fff' },
    completed:   { background: '#22c55e', color: '#fff' },
    cancelled:   { background: '#ef4444', color: '#fff' }
}

const priorityBadgeStyles = {
    critical: { background: '#ef4444', color: '#fff' },
    high:     { background: '#f97316', color: '#fff' },
    medium:   { background: '#eab308', color: '#fff' },
    low:      { background: '#22c55e', color: '#fff' }
}

function ServiceRequests() {
    const { t } = useTranslation()
  const { showToast } = useToast()

    const statusOptions = [
        { value: 'pending',     label: t('services.status_pending') },
        { value: 'assigned',    label: t('services.status_assigned') },
        { value: 'in_progress', label: t('services.status_in_progress') },
        { value: 'on_hold',     label: t('services.status_on_hold') },
        { value: 'completed',   label: t('services.status_completed') },
        { value: 'cancelled',   label: t('services.status_cancelled') }
    ]

    const priorityOptions = [
        { value: 'critical', label: t('services.priority_critical') },
        { value: 'high',     label: t('services.priority_high') },
        { value: 'medium',   label: t('services.priority_medium') },
        { value: 'low',      label: t('services.priority_low') }
    ]

    const categoryOptions = [
        { value: 'maintenance',  label: t('services.cat_maintenance') },
        { value: 'repair',       label: t('services.cat_repair') },
        { value: 'installation', label: t('services.cat_installation') },
        { value: 'inspection',   label: t('services.cat_inspection') },
        { value: 'other',        label: t('services.cat_other') }
    ]

    const costTypeOptions = [
        { value: 'labor',  label: t('services.cost_labor') },
        { value: 'parts',  label: t('services.cost_parts') },
        { value: 'travel', label: t('services.cost_travel') },
        { value: 'other',  label: t('services.cost_other') }
    ]

    const [requests, setRequests] = useState([])
    const [customers, setCustomers] = useState([])
    const [technicians, setTechnicians] = useState([])
    const [stats, setStats] = useState({})
    const [loading, setLoading] = useState(true)
    const [showModal, setShowModal] = useState(false)
    const [editingId, setEditingId] = useState(null)
    const [filterStatus, setFilterStatus] = useState('')
    const [filterPriority, setFilterPriority] = useState('')

    // Detail view
    const [expandedId, setExpandedId] = useState(null)
    const [detail, setDetail] = useState(null)
    const [detailLoading, setDetailLoading] = useState(false)

    // Cost form
    const [showCostModal, setShowCostModal] = useState(false)
    const [costForm, setCostForm] = useState({ cost_type: 'labor', description: '', quantity: '1', unit_cost: '' })

    const emptyForm = {
        title: '', description: '', category: 'maintenance', priority: 'medium',
        customer_id: '', assigned_to: '', estimated_hours: '', estimated_cost: '',
        scheduled_date: '', location: '', notes: ''
    }
    const [formData, setFormData] = useState({ ...emptyForm })

    useEffect(() => {
        fetchRequests()
        fetchCustomers()
        fetchTechnicians()
        fetchStats()
    }, [filterStatus, filterPriority])

    const fetchRequests = async () => {
        try {
            setLoading(true)
            const params = {}
            if (filterStatus) params.status = filterStatus
            if (filterPriority) params.priority = filterPriority
            const res = await servicesAPI.listRequests(params)
            setRequests(Array.isArray(res.data) ? res.data : (res.data?.items ?? []))
        } catch (err) {
            console.error('Failed to fetch requests', err)
        } finally {
            setLoading(false)
        }
    }

    const fetchCustomers = async () => {
        try {
            const res = await salesAPI.listCustomers()
            setCustomers(res.data || [])
        } catch { /* ignore */ }
    }

    const fetchTechnicians = async () => {
        try {
            const res = await servicesAPI.listTechnicians()
            setTechnicians(res.data || [])
        } catch { /* ignore */ }
    }

    const fetchStats = async () => {
        try {
            const res = await servicesAPI.getRequestStats()
            setStats(res.data || {})
        } catch { /* ignore */ }
    }

    const openCreate = () => {
        setFormData({ ...emptyForm })
        setEditingId(null)
        setShowModal(true)
    }

    const openEdit = (req) => {
        setFormData({
            title: req.title || '',
            description: req.description || '',
            category: req.category || 'maintenance',
            priority: req.priority || 'medium',
            customer_id: req.customer_id || '',
            assigned_to: req.assigned_to || '',
            estimated_hours: req.estimated_hours || '',
            estimated_cost: req.estimated_cost || '',
            scheduled_date: req.scheduled_date || '',
            location: req.location || '',
            notes: req.notes || ''
        })
        setEditingId(req.id)
        setShowModal(true)
    }

    const handleChange = (e) => {
        setFormData({ ...formData, [e.target.name]: e.target.value })
    }

    const handleSubmit = async (e) => {
        e.preventDefault()
        try {
            const payload = { ...formData }
            if (!payload.customer_id) payload.customer_id = null
            if (!payload.assigned_to) payload.assigned_to = null
            if (!payload.estimated_hours) payload.estimated_hours = null
            if (!payload.estimated_cost) payload.estimated_cost = null

            if (editingId) {
                await servicesAPI.updateRequest(editingId, payload)
            } else {
                await servicesAPI.createRequest(payload)
            }
            setShowModal(false)
            fetchRequests()
            fetchStats()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        }
    }

    const handleDelete = async (id) => {
        if (!confirm(t('common.confirm_delete'))) return
        try {
            await servicesAPI.deleteRequest(id)
            fetchRequests()
            fetchStats()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        }
    }

    const handleStatusChange = async (id, newStatus) => {
        try {
            await servicesAPI.updateRequest(id, { status: newStatus })
            fetchRequests()
            fetchStats()
            if (expandedId === id) loadDetail(id)
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        }
    }

    const loadDetail = async (id) => {
        if (expandedId === id) {
            setExpandedId(null)
            return
        }
        setExpandedId(id)
        setDetailLoading(true)
        try {
            const res = await servicesAPI.getRequest(id)
            setDetail(res.data)
        } catch {
            setDetail(null)
        } finally {
            setDetailLoading(false)
        }
    }

    // Cost management
    const openCostModal = () => {
        setCostForm({ cost_type: 'labor', description: '', quantity: '1', unit_cost: '' })
        setShowCostModal(true)
    }

    const handleAddCost = async (e) => {
        e.preventDefault()
        try {
            await servicesAPI.addCost(expandedId, costForm)
            setShowCostModal(false)
            loadDetail(null) // collapse first
            setTimeout(() => loadDetail(expandedId), 100) // reload
            fetchRequests()
            fetchStats()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        }
    }

    const handleDeleteCost = async (costId) => {
        try {
            await servicesAPI.deleteCost(expandedId, costId)
            const res = await servicesAPI.getRequest(expandedId)
            setDetail(res.data)
            fetchRequests()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        }
    }

    const getLabelByValue = (options, value) => {
        const opt = options.find(o => o.value === value)
        return opt ? opt.label : value
    }

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">{t('services.requests_title')}</h1>
                    <p className="workspace-subtitle">{t('services.requests_desc')}</p>
                </div>
                <div className="header-actions">
                    <button className="btn btn-primary" onClick={openCreate}>+ {t('services.new_request')}</button>
                </div>
            </div>

            {/* Stats Cards */}
            <div className="stats-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '12px', marginBottom: '20px' }}>
                <div className="stat-card" style={{ padding: '16px', background: 'var(--bg-secondary)', borderRadius: '8px', textAlign: 'center' }}>
                    <div style={{ fontSize: '24px', fontWeight: 700, color: 'var(--primary)' }}>{stats.total || 0}</div>
                    <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>{t('services.stat_total')}</div>
                </div>
                <div className="stat-card" style={{ padding: '16px', background: 'var(--bg-secondary)', borderRadius: '8px', textAlign: 'center' }}>
                    <div style={{ fontSize: '24px', fontWeight: 700, color: '#6b7280' }}>{stats.pending || 0}</div>
                    <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>{t('services.status_pending')}</div>
                </div>
                <div className="stat-card" style={{ padding: '16px', background: 'var(--bg-secondary)', borderRadius: '8px', textAlign: 'center' }}>
                    <div style={{ fontSize: '24px', fontWeight: 700, color: '#eab308' }}>{stats.in_progress || 0}</div>
                    <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>{t('services.status_in_progress')}</div>
                </div>
                <div className="stat-card" style={{ padding: '16px', background: 'var(--bg-secondary)', borderRadius: '8px', textAlign: 'center' }}>
                    <div style={{ fontSize: '24px', fontWeight: 700, color: '#22c55e' }}>{stats.completed || 0}</div>
                    <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>{t('services.status_completed')}</div>
                </div>
                <div className="stat-card" style={{ padding: '16px', background: 'var(--bg-secondary)', borderRadius: '8px', textAlign: 'center' }}>
                    <div style={{ fontSize: '24px', fontWeight: 700, color: '#ef4444' }}>{stats.critical_open || 0}</div>
                    <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>{t('services.stat_critical')}</div>
                </div>
            </div>

            {/* Filters */}
            <div className="toolbar" style={{ display: 'flex', gap: '12px', marginBottom: '16px', flexWrap: 'wrap' }}>
                <select className="form-input" style={{ width: 'auto' }} value={filterStatus} onChange={e => setFilterStatus(e.target.value)}>
                    <option value="">{t('services.all_statuses')}</option>
                    {statusOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
                <select className="form-input" style={{ width: 'auto' }} value={filterPriority} onChange={e => setFilterPriority(e.target.value)}>
                    <option value="">{t('services.all_priorities')}</option>
                    {priorityOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
            </div>

            {/* Table */}
            <div className="data-table-container">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('services.col_number')}</th>
                            <th>{t('services.col_title')}</th>
                            <th>{t('services.col_category')}</th>
                            <th>{t('services.col_priority')}</th>
                            <th>{t('services.col_status')}</th>
                            <th>{t('services.col_customer')}</th>
                            <th>{t('services.col_assigned')}</th>
                            <th>{t('services.col_cost')}</th>
                            <th>{t('services.col_date')}</th>
                            <th>{t('common.actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading ? (
                            <tr><td colSpan="10" style={{ textAlign: 'center', padding: '40px' }}>{t('common.loading')}</td></tr>
                        ) : requests.length === 0 ? (
                            <tr><td colSpan="10" style={{ textAlign: 'center', padding: '40px' }}>{t('common.no_data')}</td></tr>
                        ) : requests.map(req => (
                            <Fragment key={req.id}>
                                <tr style={{ cursor: 'pointer' }} onClick={() => loadDetail(req.id)}>
                                    <td><strong>{req.request_number}</strong></td>
                                    <td>{req.title}</td>
                                    <td>{getLabelByValue(categoryOptions, req.category)}</td>
                                    <td><span className="badge" style={priorityBadgeStyles[req.priority] || {}}>{getLabelByValue(priorityOptions, req.priority)}</span></td>
                                    <td><span className="badge" style={statusBadgeStyles[req.status] || {}}>{getLabelByValue(statusOptions, req.status)}</span></td>
                                    <td>{req.customer_name || '—'}</td>
                                    <td>{req.assigned_to_name || '—'}</td>
                                    <td>{formatNumber(req.actual_cost || '0')}</td>
                                    <td>{formatShortDate(req.created_at)}</td>
                                    <td onClick={e => e.stopPropagation()}>
                                        <div style={{ display: 'flex', gap: '4px' }}>
                                            <button className="btn btn-sm" onClick={() => openEdit(req)} title={t('common.edit')}>✏️</button>
                                            <button className="btn btn-sm btn-danger" onClick={() => handleDelete(req.id)} title={t('common.delete')}>🗑️</button>
                                            {req.status !== 'completed' && req.status !== 'cancelled' && (
                                                <select
                                                    className="form-input"
                                                    style={{ width: 'auto', fontSize: '12px', padding: '2px 6px' }}
                                                    value={req.status}
                                                    onChange={e => handleStatusChange(req.id, e.target.value)}
                                                >
                                                    {statusOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                                                </select>
                                            )}
                                        </div>
                                    </td>
                                </tr>

                                {/* Expanded Detail */}
                                {expandedId === req.id && (
                                    <tr key={`detail-${req.id}`}>
                                        <td colSpan="10" style={{ background: 'var(--bg-secondary)', padding: '20px' }}>
                                            {detailLoading ? (
                                                <div style={{ textAlign: 'center' }}>{t('common.loading')}</div>
                                            ) : detail ? (
                                                <div>
                                                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
                                                        <div>
                                                            <strong>{t('services.description')}:</strong>
                                                            <p>{detail.description || '—'}</p>
                                                        </div>
                                                        <div>
                                                            <strong>{t('services.location')}:</strong> {detail.location || '—'}<br/>
                                                            <strong>{t('services.scheduled')}:</strong> {detail.scheduled_date ? formatShortDate(detail.scheduled_date) : '—'}<br/>
                                                            <strong>{t('services.est_hours')}:</strong> {detail.estimated_hours || '—'} |
                                                            <strong> {t('services.act_hours')}:</strong> {detail.actual_hours || '—'}<br/>
                                                            <strong>{t('services.est_cost')}:</strong> {formatNumber(detail.estimated_cost || '0')} |
                                                            <strong> {t('services.act_cost')}:</strong> {formatNumber(detail.actual_cost || '0')}
                                                        </div>
                                                    </div>
                                                    {detail.notes && <p><strong>{t('services.notes')}:</strong> {detail.notes}</p>}

                                                    {/* Costs Section */}
                                                    <div style={{ marginTop: '16px' }}>
                                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                                                            <h4 style={{ margin: 0 }}>{t('services.costs')}</h4>
                                                            <button className="btn btn-sm btn-primary" onClick={openCostModal}>+ {t('services.add_cost')}</button>
                                                        </div>
                                                        {detail.costs && detail.costs.length > 0 ? (
                                                            <table className="data-table" style={{ fontSize: '13px' }}>
                                                                <thead>
                                                                    <tr>
                                                                        <th>{t('services.cost_type_label')}</th>
                                                                        <th>{t('services.cost_desc')}</th>
                                                                        <th>{t('services.cost_qty')}</th>
                                                                        <th>{t('services.cost_unit')}</th>
                                                                        <th>{t('services.cost_total')}</th>
                                                                        <th></th>
                                                                    </tr>
                                                                </thead>
                                                                <tbody>
                                                                    {detail.costs.map(c => (
                                                                        <tr key={c.id}>
                                                                            <td>{getLabelByValue(costTypeOptions, c.cost_type)}</td>
                                                                            <td>{c.description}</td>
                                                                            <td>{c.quantity}</td>
                                                                            <td>{formatNumber(c.unit_cost || '0')}</td>
                                                                            <td>{formatNumber(c.total_cost || '0')}</td>
                                                                            <td><button className="btn btn-sm btn-danger" onClick={() => handleDeleteCost(c.id)}>🗑️</button></td>
                                                                        </tr>
                                                                    ))}
                                                                </tbody>
                                                            </table>
                                                        ) : (
                                                            <p style={{ color: 'var(--text-secondary)', fontSize: '13px' }}>{t('services.no_costs')}</p>
                                                        )}
                                                    </div>
                                                </div>
                                            ) : null}
                                        </td>
                                    </tr>
                                )}
                            </Fragment>
                        ))}
                    </tbody>
                </table>
            </div>

            {/* Create/Edit Modal */}
            {showModal && (
                <div className="modal-overlay" onClick={() => setShowModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '600px' }}>
                        <div className="modal-header">
                            <h3>{editingId ? t('services.edit_request') : t('services.new_request')}</h3>
                            <button className="modal-close" onClick={() => setShowModal(false)}>×</button>
                        </div>
                        <form onSubmit={handleSubmit}>
                            <div className="modal-body">
                                <div className="form-group mb-3">
                                    <label className="form-label">{t('services.col_title')} *</label>
                                    <input className="form-input" name="title" value={formData.title} onChange={handleChange} required />
                                </div>
                                <div className="form-group mb-3">
                                    <label className="form-label">{t('services.description')}</label>
                                    <textarea className="form-input" name="description" value={formData.description} onChange={handleChange} rows={3} />
                                </div>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                                    <div className="form-group mb-3">
                                        <label className="form-label">{t('services.col_category')}</label>
                                        <select className="form-input" name="category" value={formData.category} onChange={handleChange}>
                                            {categoryOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                                        </select>
                                    </div>
                                    <div className="form-group mb-3">
                                        <label className="form-label">{t('services.col_priority')}</label>
                                        <select className="form-input" name="priority" value={formData.priority} onChange={handleChange}>
                                            {priorityOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                                        </select>
                                    </div>
                                </div>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                                    <div className="form-group mb-3">
                                        <label className="form-label">{t('services.col_customer')}</label>
                                        <select className="form-input" name="customer_id" value={formData.customer_id} onChange={handleChange}>
                                            <option value="">{t('common.select')}</option>
                                            {customers.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                                        </select>
                                    </div>
                                    <div className="form-group mb-3">
                                        <label className="form-label">{t('services.col_assigned')}</label>
                                        <select className="form-input" name="assigned_to" value={formData.assigned_to} onChange={handleChange}>
                                            <option value="">{t('common.select')}</option>
                                            {technicians.map(u => <option key={u.id} value={u.id}>{u.full_name}</option>)}
                                        </select>
                                    </div>
                                </div>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px' }}>
                                    <div className="form-group mb-3">
                                        <label className="form-label">{t('services.est_hours')}</label>
                                        <input className="form-input" name="estimated_hours" type="number" step="0.5" value={formData.estimated_hours} onChange={handleChange} />
                                    </div>
                                    <div className="form-group mb-3">
                                        <label className="form-label">{t('services.est_cost')}</label>
                                        <input className="form-input" name="estimated_cost" type="number" step="0.01" value={formData.estimated_cost} onChange={handleChange} />
                                    </div>
                                    <div className="form-group mb-3">
                                        <label className="form-label">{t('services.scheduled')}</label>
                                        <DateInput className="form-input" name="scheduled_date" value={formData.scheduled_date} onChange={handleChange} />
                                    </div>
                                </div>
                                <div className="form-group mb-3">
                                    <label className="form-label">{t('services.location')}</label>
                                    <input className="form-input" name="location" value={formData.location} onChange={handleChange} />
                                </div>
                                <div className="form-group mb-3">
                                    <label className="form-label">{t('services.notes')}</label>
                                    <textarea className="form-input" name="notes" value={formData.notes} onChange={handleChange} rows={2} />
                                </div>
                            </div>
                            <div className="modal-footer">
                                <button type="button" className="btn btn-secondary" onClick={() => setShowModal(false)}>{t('common.cancel')}</button>
                                <button type="submit" className="btn btn-primary">{editingId ? t('common.save') : t('common.create')}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* Add Cost Modal */}
            {showCostModal && (
                <div className="modal-overlay" onClick={() => setShowCostModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '450px' }}>
                        <div className="modal-header">
                            <h3>{t('services.add_cost')}</h3>
                            <button className="modal-close" onClick={() => setShowCostModal(false)}>×</button>
                        </div>
                        <form onSubmit={handleAddCost}>
                            <div className="modal-body">
                                <div className="form-group mb-3">
                                    <label className="form-label">{t('services.cost_type_label')}</label>
                                    <select className="form-input" value={costForm.cost_type} onChange={e => setCostForm({...costForm, cost_type: e.target.value})}>
                                        {costTypeOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                                    </select>
                                </div>
                                <div className="form-group mb-3">
                                    <label className="form-label">{t('services.cost_desc')}</label>
                                    <input className="form-input" value={costForm.description} onChange={e => setCostForm({...costForm, description: e.target.value})} />
                                </div>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                                    <div className="form-group mb-3">
                                        <label className="form-label">{t('services.cost_qty')}</label>
                                        <input className="form-input" type="number" step="0.01" value={costForm.quantity} onChange={e => setCostForm({...costForm, quantity: e.target.value})} />
                                    </div>
                                    <div className="form-group mb-3">
                                        <label className="form-label">{t('services.cost_unit')}</label>
                                        <input className="form-input" type="number" step="0.01" value={costForm.unit_cost} onChange={e => setCostForm({...costForm, unit_cost: e.target.value})} />
                                    </div>
                                </div>
                            </div>
                            <div className="modal-footer">
                                <button type="button" className="btn btn-secondary" onClick={() => setShowCostModal(false)}>{t('common.cancel')}</button>
                                <button type="submit" className="btn btn-primary">{t('common.add')}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    )
}

export default ServiceRequests
