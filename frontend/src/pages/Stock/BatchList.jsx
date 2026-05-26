import { useState, useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { inventoryAPI } from '../../utils/api'
import { useBranch } from '../../context/BranchContext'
import { formatNumber } from '../../utils/format'
import DateInput from '../../components/common/DateInput'
import BackButton from '../../components/common/BackButton'
import DataTable from '../../components/common/DataTable'
import SearchFilter from '../../components/common/SearchFilter'

function BatchList() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { currentBranch } = useBranch()
    const [batches, setBatches] = useState([])
    const [loading, setLoading] = useState(true)
    const [initialLoad, setInitialLoad] = useState(true)
    const [search, setSearch] = useState('')
    const [statusFilter, setStatusFilter] = useState('')
    const [products, setProducts] = useState([])
    const [warehouses, setWarehouses] = useState([])
    const [productFilter, setProductFilter] = useState('')
    const [warehouseFilter, setWarehouseFilter] = useState('')
    const [showCreateModal, setShowCreateModal] = useState(false)
    const [total, setTotal] = useState(0)
    const [summary, setSummary] = useState({})

    const [form, setForm] = useState({
        product_id: '',
        warehouse_id: '',
        batch_number: '',
        manufacturing_date: '',
        expiry_date: '',
        quantity: '',
        unit_cost: '',
        notes: ''
    })
    const [saving, setSaving] = useState(false)
    const [error, setError] = useState(null)

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchBatches()
            fetchProducts()
            fetchWarehouses()
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch, search, statusFilter, productFilter, warehouseFilter])

    const fetchBatches = async () => {
        try {
            setLoading(true)
            const params = { limit: 100 }
            if (search) params.search = search
            if (statusFilter) params.status = statusFilter
            if (productFilter) params.product_id = productFilter
            if (warehouseFilter) params.warehouse_id = warehouseFilter
            const res = await inventoryAPI.listBatches(params)
            setBatches(res.data.items || [])
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

    const handleCreate = async (e) => {
        e.preventDefault()
        setSaving(true)
        setError(null)
        try {
            await inventoryAPI.createBatch({
                ...form,
                product_id: parseInt(form.product_id),
                warehouse_id: parseInt(form.warehouse_id),
                quantity: String(form.quantity || 0)
            })
            setShowCreateModal(false)
            setForm({ product_id: '', warehouse_id: '', batch_number: '', manufacturing_date: '', expiry_date: '', quantity: '', unit_cost: '', notes: '' })
            fetchBatches()
        } catch (err) {
            setError(err.response?.data?.detail || t('common.error_occurred'))
        } finally {
            setSaving(false)
        }
    }

    const getStatusBadge = (status) => {
        const map = {
            active: { label: t('stock.batch.active'), cls: 'badge-success' },
            expired: { label: t('stock.batch.expired'), cls: 'badge-danger' },
            consumed: { label: t('stock.batch.consumed'), cls: 'badge-secondary' },
            recalled: { label: t('stock.batch.recalled'), cls: 'badge-warning' }
        }
        const s = map[status] || { label: status, cls: 'badge-secondary' }
        return <span className={`badge ${s.cls}`}>{s.label}</span>
    }

    const getDaysRemaining = (row) => {
        if (!row.expiry_status || row.expiry_status === 'no_expiry') return null
        if (row.expiry_status === 'expired') {
            return <span style={{ color: 'var(--danger)' }}>{t('stock.batch.expired_since', { days: row.days_remaining_abs })}</span>
        }
        if (row.expiry_status === 'near_expiry') {
            return <span style={{ color: 'var(--warning)' }}>{t('stock.batch.days_remaining', { days: row.days_remaining })}</span>
        }
        return <span style={{ color: 'var(--success)' }}>{t('stock.batch.days_remaining', { days: row.days_remaining })}</span>
    }

    const filteredBatches = useMemo(() => batches, [batches])

    const handleFilterChange = (key, value) => {
        if (key === 'status') setStatusFilter(value)
        if (key === 'warehouse') setWarehouseFilter(value)
    }

    const columns = [
        {
            key: 'batch_number',
            label: t('stock.batch.batch_number'),
            width: '12%',
            render: (val) => <strong>{val}</strong>,
        },
        {
            key: 'product_name',
            label: t('common.product'),
            width: '20%',
        },
        {
            key: 'warehouse_name',
            label: t('stock.batch.warehouse'),
            width: '12%',
        },
        {
            key: 'quantity',
            label: t('common.quantity'),
            width: '10%',
            render: (val) => formatNumber(val || 0),
        },
        {
            key: 'manufacturing_date',
            label: t('stock.batch.manufacturing_date'),
            width: '12%',
            render: (val) => val || '-',
        },
        {
            key: 'expiry_date',
            label: t('stock.batch.expiry_date'),
            width: '12%',
            render: (val) => val || '-',
        },
        {
            key: '_remaining',
            label: t('stock.batch.remaining'),
            width: '12%',
            render: (_, row) => getDaysRemaining(row) || '-',
        },
        {
            key: 'status',
            label: t('common.status_title'),
            width: '10%',
            render: (val) => getStatusBadge(val),
        },
    ]

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div>
                    <h1 className="workspace-title">{t('stock.batches.title')}</h1>
                    <p className="workspace-subtitle">{t('stock.batches.subtitle')}</p>
                </div>
                <button className="btn btn-primary" onClick={() => setShowCreateModal(true)}>
                    + {t('stock.batches.add')}
                </button>
            </div>

            {/* Stats */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', marginBottom: '24px' }}>
                <div className="card p-3 text-center">
                    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mx-auto mb-2 text-primary">
                        <path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z"/>
                        <path d="M3 6h18"/>
                        <path d="M16 10a4 4 0 0 1-8 0"/>
                    </svg>
                    <div className="small text-muted">{t('stock.batch.total_batches')}</div>
                    <div className="fw-bold fs-4">{total}</div>
                </div>
                <div className="card p-3 text-center">
                    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mx-auto mb-2 text-success">
                        <path d="M21.801 10A10 10 0 1 1 17 3.335"/>
                        <path d="m9 11 3 3L22 4"/>
                    </svg>
                    <div className="small text-muted">{t('stock.batch.active_batches')}</div>
                    <div className="fw-bold fs-4 text-success">{summary.active_count || 0}</div>
                </div>
                <div className="card p-3 text-center">
                    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mx-auto mb-2 text-warning">
                        <circle cx="12" cy="12" r="10"/>
                        <path d="M12 6v6l4 2"/>
                    </svg>
                    <div className="small text-muted">{t('stock.batch.near_expiry')}</div>
                    <div className="fw-bold fs-4 text-warning">
                        {summary.near_expiry_count || 0}
                    </div>
                </div>
                <div className="card p-3 text-center">
                    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mx-auto mb-2 text-danger">
                        <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/>
                        <path d="M12 9v4"/>
                        <path d="M12 17h.01"/>
                    </svg>
                    <div className="small text-muted">{t('stock.batch.expired_items')}</div>
                    <div className="fw-bold fs-4 text-danger">
                        {summary.expired_count || 0}
                    </div>
                </div>
            </div>

            <SearchFilter
                value={search}
                onChange={setSearch}
                placeholder={t('stock.batch.search_placeholder')}
                filters={[
                    {
                        key: 'status',
                        label: t('common.all_statuses'),
                        options: [
                            { value: 'active', label: t('stock.batch.active') },
                            { value: 'expired', label: t('stock.batch.expired') },
                            { value: 'consumed', label: t('stock.batch.consumed') },
                        ],
                    },
                    {
                        key: 'warehouse',
                        label: t('stock.batch.all_warehouses'),
                        options: warehouses.map(w => ({ value: String(w.id), label: w.warehouse_name })),
                    },
                ]}
                filterValues={{ status: statusFilter, warehouse: warehouseFilter }}
                onFilterChange={handleFilterChange}
            />

            <DataTable
                columns={columns}
                data={filteredBatches}
                loading={loading}
                onRowClick={(row) => navigate(`/stock/batches/${row.id}`)}
                emptyIcon={'\uD83D\uDCE6'}
                emptyTitle={t('stock.batch.no_batches')}
            />

            {/* Create Modal */}
            {showCreateModal && (
                <div className="modal-overlay" onClick={() => setShowCreateModal(false)}>
                    <div className="modal-content" onClick={(e) => e.stopPropagation()}
                        style={{ maxWidth: '700px', width: '90%' }}>
                        <div className="modal-header">
                            <h2>{t('stock.batch.add_batch')}</h2>
                            <button className="modal-close" onClick={() => setShowCreateModal(false)}>✕</button>
                        </div>
                        <form onSubmit={handleCreate}>
                            {error && <div className="alert alert-error mb-4">{error}</div>}
                            <div className="form-row">
                                <div className="form-group">
                                    <label className="form-label">{t('common.product')} *</label>
                                    <select className="form-input" required value={form.product_id}
                                        onChange={(e) => setForm({ ...form, product_id: e.target.value })}>
                                        <option value="">{t('stock.batch.select_product')}</option>
                                        {products.filter(p => p.item_type === 'product').map(p => (
                                            <option key={p.id} value={p.id}>{p.item_name} ({p.item_code})</option>
                                        ))}
                                    </select>
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('stock.batch.warehouse')} *</label>
                                    <select className="form-input" required value={form.warehouse_id}
                                        onChange={(e) => setForm({ ...form, warehouse_id: e.target.value })}>
                                        <option value="">{t('stock.batch.select_warehouse')}</option>
                                        {warehouses.map(w => (
                                            <option key={w.id} value={w.id}>{w.warehouse_name}</option>
                                        ))}
                                    </select>
                                </div>
                            </div>
                            <div className="form-row">
                                <div className="form-group">
                                    <label className="form-label">{t('stock.batch.batch_number')} *</label>
                                    <input type="text" className="form-input" required value={form.batch_number}
                                        onChange={(e) => setForm({ ...form, batch_number: e.target.value })}
                                        placeholder={t('stock.batch.batch_number_placeholder')} />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('common.quantity')}</label>
                                    <input type="number" className="form-input" min="0" step="0.01"
                                        value={form.quantity}
                                        onChange={(e) => setForm({ ...form, quantity: e.target.value })} />
                                </div>
                            </div>
                            <div className="form-row">
                                <div className="form-group">
                                    <label className="form-label">{t('stock.batch.manufacturing_date')}</label>
                                    <DateInput className="form-input" value={form.manufacturing_date}
                                        onChange={(e) => setForm({ ...form, manufacturing_date: e.target.value })} />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('stock.batch.expiry_date')}</label>
                                    <DateInput className="form-input" value={form.expiry_date}
                                        onChange={(e) => setForm({ ...form, expiry_date: e.target.value })} />
                                </div>
                            </div>
                            <div className="form-row">
                                <div className="form-group">
                                    <label className="form-label">{t('stock.batch.unit_cost')}</label>
                                    <input type="number" className="form-input" min="0" step="0.01"
                                        value={form.unit_cost}
                                        onChange={(e) => setForm({ ...form, unit_cost: e.target.value })} />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('common.notes')}</label>
                                    <input type="text" className="form-input" value={form.notes}
                                        onChange={(e) => setForm({ ...form, notes: e.target.value })} />
                                </div>
                            </div>
                            <div style={{ display: 'flex', gap: '12px', marginTop: '20px' }}>
                                <button type="submit" className="btn btn-primary" disabled={saving}>
                                    {saving ? t('common.saving') : t('stock.batch.create_batch')}
                                </button>
                                <button type="button" className="btn btn-secondary" onClick={() => setShowCreateModal(false)}>
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

export default BatchList
