import { useState, useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { costingLayerAPI } from '../../services/costing'
import BackButton from '../../components/common/BackButton'
import DataTable from '../../components/common/DataTable'
import SearchFilter from '../../components/common/SearchFilter'
import { formatNumber } from '../../utils/format'
import { useToast } from '../../context/ToastContext'

function CostLayerList() {
    const { t } = useTranslation()
    const { showToast } = useToast()
    const [layers, setLayers] = useState([])
    const [loading, setLoading] = useState(true)
    const [search, setSearch] = useState('')
    const [productId, setProductId] = useState('')
    const [warehouseId, setWarehouseId] = useState('')
    const [includeExhausted, setIncludeExhausted] = useState(false)

    const fetchLayers = async () => {
        try {
            setLoading(true)
            const params = {}
            if (productId) params.product_id = productId
            if (warehouseId) params.warehouse_id = warehouseId
            if (includeExhausted) params.include_exhausted = true
            const res = await costingLayerAPI.listLayers(params)
            setLayers(Array.isArray(res.data) ? res.data : [])
        } catch {
            showToast(t('costing.load_error'), 'error')
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => { fetchLayers() }, [])

    const handleFilter = (e) => {
        e.preventDefault()
        fetchLayers()
    }

    const filteredLayers = useMemo(() => {
        if (!search) return layers
        const s = search.toLowerCase()
        return layers.filter(l =>
            String(l.product_id).includes(s) ||
            String(l.warehouse_id).includes(s) ||
            (l.costing_method || '').toLowerCase().includes(s) ||
            (l.source_document_type || '').toLowerCase().includes(s) ||
            (l.purchase_date || '').includes(s)
        )
    }, [layers, search])

    const columns = [
        { key: 'product_id', label: t('costing.product_id') },
        { key: 'warehouse_id', label: t('costing.warehouse_id') },
        { key: 'costing_method', label: t('costing.method'), render: (val, row) => (
            <span className={`badge ${val === 'fifo' ? 'badge-primary' : 'badge-purple'}`}>{val?.toUpperCase()}</span>
        )},
        { key: 'purchase_date', label: t('costing.purchase_date') },
        { key: 'original_quantity', label: t('costing.original_qty'), render: (val) => formatNumber(val) },
        { key: 'remaining_quantity', label: t('costing.remaining_qty'), render: (val) => formatNumber(val) },
        { key: 'unit_cost', label: t('costing.unit_cost'), render: (val) => formatNumber(val, 2) },
        { key: 'total_value', label: t('costing.total_value'), render: (_, row) => formatNumber(row.total_value != null ? row.total_value : '', 2) },
        { key: 'source_document_type', label: t('costing.source') },
        { key: 'is_exhausted', label: t('costing.exhausted'), render: (val) => val ? '✓' : '' },
    ]

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div>
                    <h1 className="workspace-title">{t('costing.layers_subtitle')}</h1>
                </div>
            </div>

            <form onSubmit={handleFilter} className="card" style={{ padding: 16, marginBlockEnd: 16 }}>
                <div className="form-row" style={{ alignItems: 'flex-end', marginBottom: 0 }}>
                    <div className="form-group" style={{ marginBottom: 0, minWidth: 160 }}>
                        <label className="form-label">{t('costing.product_id')}</label>
                        <input type="number" className="form-input" value={productId} onChange={e => setProductId(e.target.value)} placeholder="ID" />
                    </div>
                    <div className="form-group" style={{ marginBottom: 0, minWidth: 160 }}>
                        <label className="form-label">{t('costing.warehouse_id')}</label>
                        <input type="number" className="form-input" value={warehouseId} onChange={e => setWarehouseId(e.target.value)} placeholder="ID" />
                    </div>
                    <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginBottom: 8, color: 'var(--text-main)', cursor: 'pointer' }}>
                        <input type="checkbox" checked={includeExhausted} onChange={e => setIncludeExhausted(e.target.checked)} />
                        {t('costing.include_exhausted')}
                    </label>
                    <button type="submit" className="btn btn-primary">{t('common.search')}</button>
                </div>
            </form>

            <div className="card" style={{ padding: 16 }}>
                <div style={{ marginBottom: 12 }}>
                    <SearchFilter value={search} onChange={setSearch} placeholder={t('common.search')} />
                </div>
                <DataTable
                    data={filteredLayers}
                    columns={columns}
                    loading={loading}
                    emptyTitle={t('costing.no_layers')}
                />
            </div>
        </div>
    )
}

export default CostLayerList
