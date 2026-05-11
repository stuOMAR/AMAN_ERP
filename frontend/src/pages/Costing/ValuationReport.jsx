import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { costingLayerAPI } from '../../services/costing'
import BackButton from '../../components/common/BackButton'
import DataTable from '../../components/common/DataTable'
import { formatNumber } from '../../utils/format'
import { useToast } from '../../context/ToastContext'
import DateInput from '../../components/common/DateInput';

function ValuationReport() {
    const { t } = useTranslation()
    const { showToast } = useToast()
    const [report, setReport] = useState(null)
    const [loading, setLoading] = useState(true)
    const [asOfDate, setAsOfDate] = useState(new Date().toISOString().split('T')[0])

    const fetchReport = async () => {
        try {
            setLoading(true)
            const res = await costingLayerAPI.getValuation({ as_of_date: asOfDate })
            setReport(res.data)
        } catch {
            showToast(t('costing.load_error'), 'error')
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => { fetchReport() }, [])

    const columns = [
        { key: 'product_name', label: t('costing.product'), render: (_, row) => row.product_name || `#${row.product_id}` },
        { key: 'warehouse_name', label: t('costing.warehouse'), render: (_, row) => row.warehouse_name || `#${row.warehouse_id}` },
        { key: 'costing_method', label: t('costing.method'), render: (v) => <span className={`badge ${v === 'fifo' ? 'badge-primary' : 'badge-purple'}`}>{v.toUpperCase()}</span> },
        { key: 'total_quantity', label: t('costing.quantity'), render: (v) => formatNumber(v, 0) },
        { key: 'total_value', label: t('costing.total_value'), render: (v) => formatNumber(v, 2) },
        { key: 'weighted_unit_cost', label: t('costing.weighted_cost'), render: (v) => v ? formatNumber(v, 4) : '-' },
        { key: 'layer_count', label: t('costing.layer_count') },
    ]

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <h1 className="workspace-title">{t('costing.valuation_subtitle')}</h1>
            </div>

            <div className="card" style={{ padding: 16, marginBottom: 16 }}>
                <div className="form-row" style={{ alignItems: 'flex-end', marginBottom: 0 }}>
                    <div className="form-group" style={{ marginBottom: 0, minWidth: 200 }}>
                        <label className="form-label">{t('costing.as_of_date')}</label>
                        <DateInput value={asOfDate} onChange={e => setAsOfDate(e.target.value)} />
                    </div>
                    <button className="btn btn-primary" onClick={fetchReport} disabled={loading}>
                        {loading ? t('common.loading') : t('costing.refresh')}
                    </button>
                </div>
            </div>

            {report && (
                <>
                    <div className="card" style={{ padding: 16, marginBottom: 16, display: 'flex', gap: 24 }}>
                        <div>
                            <strong>{t('costing.grand_total_qty')}:</strong> {formatNumber(report.grand_total_quantity || 0, 0)}
                        </div>
                        <div>
                            <strong>{t('costing.grand_total_value')}:</strong> {formatNumber(report.grand_total_value || 0, 2)}
                        </div>
                    </div>

                    <DataTable
                        columns={columns}
                        data={report.items || []}
                        loading={loading}
                        paginate={false}
                        emptyTitle={t('costing.no_layers')}
                    />
                </>
            )}
        </div>
    )
}

export default ValuationReport
