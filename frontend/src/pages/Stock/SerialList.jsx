import { useState, useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { inventoryAPI } from '../../utils/api'
import { useBranch } from '../../context/BranchContext'
import { formatShortDate } from '../../utils/dateUtils'
import BackButton from '../../components/common/BackButton'
import DataTable from '../../components/common/DataTable'
import SearchFilter from '../../components/common/SearchFilter'

function SerialList() {
    const { t } = useTranslation()
    const { currentBranch } = useBranch()
    const [serials, setSerials] = useState([])
    const [loading, setLoading] = useState(true)
    const [initialLoad, setInitialLoad] = useState(true)
    const [search, setSearch] = useState('')
    const [statusFilter, setStatusFilter] = useState('')
    const [products, setProducts] = useState([])
    const [warehouses, setWarehouses] = useState([])
    const [productFilter, setProductFilter] = useState('')
    const [showCreateModal, setShowCreateModal] = useState(false)
    const [showBulkModal, setShowBulkModal] = useState(false)
    const [total, setTotal] = useState(0)

    const [form, setForm] = useState({
        product_id: '',
        warehouse_id: '',
        serial_number: '',
        batch_id: '',
        notes: ''
    })

    const [bulkForm, setBulkForm] = useState({
        product_id: '',
        warehouse_id: '',
        prefix: '',
        start_number: 1,
        count: 10,
        batch_id: ''
    })

    const [saving, setSaving] = useState(false)
    const [error, setError] = useState(null)
    const [lookupSerial, setLookupSerial] = useState('')
    const [lookupResult, setLookupResult] = useState(null)
    const [showLookup, setShowLookup] = useState(false)

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchSerials()
            fetchProducts()
            fetchWarehouses()
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch, search, statusFilter, productFilter])

    const fetchSerials = async () => {
        try {
            setLoading(true)
            const params = { limit: 100 }
            if (search) params.search = search
            if (statusFilter) params.status = statusFilter
            if (productFilter) params.product_id = productFilter
            const res = await inventoryAPI.listSerials(params)
            setSerials(res.data.items || [])
            setTotal(res.data.total || 0)
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
            await inventoryAPI.createSerial({
                ...form,
                product_id: parseInt(form.product_id),
                warehouse_id: parseInt(form.warehouse_id),
                batch_id: form.batch_id ? parseInt(form.batch_id) : null
            })
            setShowCreateModal(false)
            setForm({ product_id: '', warehouse_id: '', serial_number: '', batch_id: '', notes: '' })
            fetchSerials()
        } catch (err) {
            setError(err.response?.data?.detail || t('common.error_occurred'))
        } finally {
            setSaving(false)
        }
    }

    const handleBulkCreate = async (e) => {
        e.preventDefault()
        setSaving(true)
        setError(null)
        try {
            await inventoryAPI.createSerialsBulk({
                product_id: parseInt(bulkForm.product_id),
                warehouse_id: parseInt(bulkForm.warehouse_id),
                prefix: bulkForm.prefix,
                start_number: parseInt(bulkForm.start_number),
                count: parseInt(bulkForm.count),
                batch_id: bulkForm.batch_id ? parseInt(bulkForm.batch_id) : null
            })
            setShowBulkModal(false)
            setBulkForm({ product_id: '', warehouse_id: '', prefix: '', start_number: 1, count: 10, batch_id: '' })
            fetchSerials()
        } catch (err) {
            setError(err.response?.data?.detail || t('common.error_occurred'))
        } finally {
            setSaving(false)
        }
    }

    const handleLookup = async () => {
        if (!lookupSerial.trim()) return
        try {
            const res = await inventoryAPI.lookupSerial(lookupSerial.trim())
            setLookupResult(res.data)
        } catch (err) {
            setLookupResult({ error: t('stock.serial.not_found') })
        }
    }

    const getStatusBadge = (status) => {
        const map = {
            available: { label: t('stock.serial.available'), cls: 'badge-success' },
            sold: { label: t('stock.serial.sold'), cls: 'badge-primary' },
            reserved: { label: t('stock.serial.reserved'), cls: 'badge-warning' },
            defective: { label: t('stock.serial.defective'), cls: 'badge-danger' },
            returned: { label: t('stock.serial.returned'), cls: 'badge-secondary' },
            in_warranty: { label: t('stock.serial.in_warranty'), cls: 'badge-info' }
        }
        const s = map[status] || { label: status, cls: 'badge-secondary' }
        return <span className={`badge ${s.cls}`}>{s.label}</span>
    }

    const filteredSerials = useMemo(() => serials, [serials])

    const handleFilterChange = (key, value) => {
        if (key === 'status') setStatusFilter(value)
        if (key === 'product') setProductFilter(value)
    }

    const columns = [
        {
            key: 'serial_number',
            label: t('stock.serial.serial_number'),
            width: '15%',
            render: (val) => <strong>{val}</strong>,
        },
        {
            key: 'product_name',
            label: t('common.product'),
            width: '20%',
        },
        {
            key: 'warehouse_name',
            label: t('stock.serial.warehouse'),
            width: '15%',
        },
        {
            key: 'batch_number',
            label: t('stock.serial.batch_number'),
            width: '12%',
            render: (val) => val || '-',
        },
        {
            key: 'warranty_expiry',
            label: t('stock.serial.expiry_date'),
            width: '12%',
            render: (val) => val || '-',
        },
        {
            key: 'status',
            label: t('common.status_title'),
            width: '10%',
            render: (val) => getStatusBadge(val),
        },
        {
            key: 'created_at',
            label: t('stock.serial.created_date'),
            width: '16%',
            render: (val) => val ? formatShortDate(val) : '-',
        },
    ]

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div>
                    <h1 className="workspace-title">{t('stock.serials.title')}</h1>
                    <p className="workspace-subtitle">{t('stock.serials.subtitle')}</p>
                </div>
                <div style={{ display: 'flex', gap: '10px' }}>
                    <button className="btn btn-secondary" onClick={() => setShowLookup(!showLookup)}>
                        {t('stock.serial.quick_search')}
                    </button>
                    <button className="btn btn-secondary" onClick={() => setShowBulkModal(true)}>
                        {t('stock.serial.bulk_create')}
                    </button>
                    <button className="btn btn-primary" onClick={() => setShowCreateModal(true)}>
                        + {t('stock.serial.add_serial')}
                    </button>
                </div>
            </div>

            {/* Quick Lookup */}
            {showLookup && (
                <div className="card mb-4" style={{ background: 'var(--bg-secondary)' }}>
                    <h3 style={{ marginBottom: '12px' }}>{t('stock.serial.quick_search_title')}</h3>
                    <div style={{ display: 'flex', gap: '12px' }}>
                        <input type="text" className="form-input" style={{ maxWidth: '350px' }}
                            placeholder={t('stock.serial.enter_serial')}
                            value={lookupSerial} onChange={(e) => setLookupSerial(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && handleLookup()} />
                        <button className="btn btn-primary" onClick={handleLookup}>{t('common.search')}</button>
                    </div>
                    {lookupResult && (
                        <div style={{ marginTop: '16px', padding: '12px', background: 'var(--bg-primary)', borderRadius: '8px' }}>
                            {lookupResult.error ? (
                                <p style={{ color: 'var(--danger)' }}>{lookupResult.error}</p>
                            ) : (
                                <div className="modules-grid" style={{ gap: '12px' }}>
                                    <div><strong>{t('stock.serial.number_label')}</strong> {lookupResult.serial_number}</div>
                                    <div><strong>{t('stock.serial.product_label')}</strong> {lookupResult.product_name}</div>
                                    <div><strong>{t('stock.serial.warehouse_label')}</strong> {lookupResult.warehouse_name}</div>
                                    <div><strong>{t('stock.serial.status_label')}</strong> {getStatusBadge(lookupResult.status)}</div>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            )}

            {/* Stats */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', marginBottom: '24px' }}>
                <div className="card p-3 text-center">
                    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mx-auto mb-2 text-primary">
                        <path d="M3 7V5a2 2 0 0 1 2-2h2"/>
                        <path d="M17 3h2a2 2 0 0 1 2 2v2"/>
                        <path d="M21 17v2a2 2 0 0 1-2 2h-2"/>
                        <path d="M7 21H5a2 2 0 0 1-2-2v-2"/>
                        <path d="M7 12h10"/>
                    </svg>
                    <div className="small text-muted">{t('stock.serial.total_serials')}</div>
                    <div className="fw-bold fs-4">{total}</div>
                </div>
                <div className="card p-3 text-center">
                    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mx-auto mb-2 text-success">
                        <path d="M21.801 10A10 10 0 1 1 17 3.335"/>
                        <path d="m9 11 3 3L22 4"/>
                    </svg>
                    <div className="small text-muted">{t('stock.serial.available')}</div>
                    <div className="fw-bold fs-4 text-success">
                        {serials.filter(s => s.status === 'available').length}
                    </div>
                </div>
                <div className="card p-3 text-center">
                    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mx-auto mb-2 text-primary">
                        <circle cx="12" cy="12" r="10"/>
                        <path d="m15 9-6 6"/>
                        <path d="m9 9 6 6"/>
                    </svg>
                    <div className="small text-muted">{t('stock.serial.sold')}</div>
                    <div className="fw-bold fs-4 text-primary">
                        {serials.filter(s => s.status === 'sold').length}
                    </div>
                </div>
                <div className="card p-3 text-center">
                    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mx-auto mb-2 text-danger">
                        <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/>
                        <path d="M12 9v4"/>
                        <path d="M12 17h.01"/>
                    </svg>
                    <div className="small text-muted">{t('stock.serial.defective')}</div>
                    <div className="fw-bold fs-4 text-danger">
                        {serials.filter(s => s.status === 'defective').length}
                    </div>
                </div>
            </div>

            <SearchFilter
                value={search}
                onChange={setSearch}
                placeholder={t('stock.serial.search_placeholder')}
                filters={[
                    {
                        key: 'status',
                        label: t('common.all_statuses'),
                        options: [
                            { value: 'available', label: t('stock.serial.available') },
                            { value: 'sold', label: t('stock.serial.sold') },
                            { value: 'reserved', label: t('stock.serial.reserved') },
                            { value: 'defective', label: t('stock.serial.defective') },
                            { value: 'returned', label: t('stock.serial.returned') },
                        ],
                    },
                    {
                        key: 'product',
                        label: t('stock.serial.all_products'),
                        options: products.filter(p => p.item_type === 'product').map(p => ({
                            value: String(p.id),
                            label: p.item_name,
                        })),
                    },
                ]}
                filterValues={{ status: statusFilter, product: productFilter }}
                onFilterChange={handleFilterChange}
            />

            <DataTable
                columns={columns}
                data={filteredSerials}
                loading={loading}
                emptyIcon={'\uD83C\uDFF7\uFE0F'}
                emptyTitle={t('stock.serial.no_serials')}
            />

            {/* Create Single Modal */}
            {showCreateModal && (
                <div className="modal-overlay" onClick={() => setShowCreateModal(false)}>
                    <div className="modal-content" onClick={(e) => e.stopPropagation()}
                        style={{ maxWidth: '600px', width: '90%' }}>
                        <div className="modal-header">
                            <h2>{t('stock.serial.add_serial')}</h2>
                            <button className="modal-close" onClick={() => setShowCreateModal(false)}>✕</button>
                        </div>
                        <form onSubmit={handleCreate}>
                            {error && <div className="alert alert-error mb-4">{error}</div>}
                            <div className="form-row">
                                <div className="form-group">
                                    <label className="form-label">{t('common.product')} *</label>
                                    <select className="form-input" required value={form.product_id}
                                        onChange={(e) => setForm({ ...form, product_id: e.target.value })}>
                                        <option value="">{t('stock.serial.select_product')}</option>
                                        {products.filter(p => p.item_type === 'product').map(p => (
                                            <option key={p.id} value={p.id}>{p.item_name} ({p.item_code})</option>
                                        ))}
                                    </select>
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('stock.serial.warehouse')} *</label>
                                    <select className="form-input" required value={form.warehouse_id}
                                        onChange={(e) => setForm({ ...form, warehouse_id: e.target.value })}>
                                        <option value="">{t('stock.serial.select_warehouse')}</option>
                                        {warehouses.map(w => (
                                            <option key={w.id} value={w.id}>{w.warehouse_name}</option>
                                        ))}
                                    </select>
                                </div>
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('stock.serial.serial_number')} *</label>
                                <input type="text" className="form-input" required value={form.serial_number}
                                    onChange={(e) => setForm({ ...form, serial_number: e.target.value })}
                                    placeholder={t('stock.serial.serial_placeholder')} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('common.notes')}</label>
                                <input type="text" className="form-input" value={form.notes}
                                    onChange={(e) => setForm({ ...form, notes: e.target.value })} />
                            </div>
                            <div style={{ display: 'flex', gap: '12px', marginTop: '20px' }}>
                                <button type="submit" className="btn btn-primary" disabled={saving}>
                                    {saving ? t('common.saving') : t('common.create')}
                                </button>
                                <button type="button" className="btn btn-secondary" onClick={() => setShowCreateModal(false)}>
                                    {t('common.cancel')}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* Bulk Create Modal */}
            {showBulkModal && (
                <div className="modal-overlay" onClick={() => setShowBulkModal(false)}>
                    <div className="modal-content" onClick={(e) => e.stopPropagation()}
                        style={{ maxWidth: '600px', width: '90%' }}>
                        <div className="modal-header">
                            <h2>{t('stock.serial.bulk_create')}</h2>
                            <button className="modal-close" onClick={() => setShowBulkModal(false)}>✕</button>
                        </div>
                        <form onSubmit={handleBulkCreate}>
                            {error && <div className="alert alert-error mb-4">{error}</div>}
                            <div className="form-row">
                                <div className="form-group">
                                    <label className="form-label">{t('common.product')} *</label>
                                    <select className="form-input" required value={bulkForm.product_id}
                                        onChange={(e) => setBulkForm({ ...bulkForm, product_id: e.target.value })}>
                                        <option value="">{t('stock.serial.select_product')}</option>
                                        {products.filter(p => p.item_type === 'product').map(p => (
                                            <option key={p.id} value={p.id}>{p.item_name}</option>
                                        ))}
                                    </select>
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('stock.serial.warehouse')} *</label>
                                    <select className="form-input" required value={bulkForm.warehouse_id}
                                        onChange={(e) => setBulkForm({ ...bulkForm, warehouse_id: e.target.value })}>
                                        <option value="">{t('stock.serial.select_warehouse')}</option>
                                        {warehouses.map(w => (
                                            <option key={w.id} value={w.id}>{w.warehouse_name}</option>
                                        ))}
                                    </select>
                                </div>
                            </div>
                            <div className="form-row">
                                <div className="form-group">
                                    <label className="form-label">{t('stock.serial.prefix')} *</label>
                                    <input type="text" className="form-input" required value={bulkForm.prefix}
                                        onChange={(e) => setBulkForm({ ...bulkForm, prefix: e.target.value })}
                                        placeholder={t('stock.serial.prefix_placeholder')} />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('stock.serial.start_number')}</label>
                                    <input type="number" className="form-input" min="1"
                                        value={bulkForm.start_number}
                                        onChange={(e) => setBulkForm({ ...bulkForm, start_number: e.target.value })} />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('stock.serial.count')}</label>
                                    <input type="number" className="form-input" min="1" max="1000"
                                        value={bulkForm.count}
                                        onChange={(e) => setBulkForm({ ...bulkForm, count: e.target.value })} />
                                </div>
                            </div>
                            <div style={{ padding: '12px', background: 'var(--bg-secondary)', borderRadius: '8px', marginTop: '8px' }}>
                                <strong>{t('stock.serial.preview')}</strong> {bulkForm.prefix}{String(bulkForm.start_number).padStart(6, '0')} → {bulkForm.prefix}{String(parseInt(bulkForm.start_number) + parseInt(bulkForm.count) - 1).padStart(6, '0')}
                                <br /><small>{t('stock.serial.will_create', { count: bulkForm.count })}</small>
                            </div>
                            <div style={{ display: 'flex', gap: '12px', marginTop: '20px' }}>
                                <button type="submit" className="btn btn-primary" disabled={saving}>
                                    {saving ? t('common.creating') : t('stock.serial.create_n', { count: bulkForm.count })}
                                </button>
                                <button type="button" className="btn btn-secondary" onClick={() => setShowBulkModal(false)}>
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

export default SerialList
