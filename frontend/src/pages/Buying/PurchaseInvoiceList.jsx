import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { purchasesAPI } from '../../utils/api'
import { useTranslation } from 'react-i18next'
import { formatShortDate } from '../../utils/dateUtils'
import { useBranch } from '../../context/BranchContext'
import { useToast } from '../../context/ToastContext'
import { formatNumber } from '../../utils/format'
import { getCurrency } from '../../utils/auth'
import DataTable from '../../components/common/DataTable'
import SearchFilter from '../../components/common/SearchFilter'
import BackButton from '../../components/common/BackButton'

function PurchaseInvoiceList() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { currentBranch } = useBranch()
    const fallbackBaseCurrency = getCurrency()
    const { showToast } = useToast()
    const [invoices, setInvoices] = useState([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)
    const [search, setSearch] = useState('')
    const [statusFilter, setStatusFilter] = useState('')

    useEffect(() => {
        const fetchInvoices = async () => {
            try {
                setLoading(true)
                const response = await purchasesAPI.listInvoices({ branch_id: currentBranch?.id })
                setInvoices(response.data)
            } catch (err) {
                setError(t('common.error_loading'))
                showToast(t('common.error'), 'error')
            } finally {
                setLoading(false)
            }
        }
        fetchInvoices()
    }, [currentBranch, t])

    const filteredInvoices = useMemo(() => {
        let result = invoices
        if (search) {
            const q = search.toLowerCase()
            result = result.filter(inv =>
                (inv.invoice_number || '').toLowerCase().includes(q) ||
                (inv.supplier_name || '').toLowerCase().includes(q)
            )
        }
        if (statusFilter) {
            result = result.filter(inv => inv.status === statusFilter)
        }
        return result
    }, [invoices, search, statusFilter])

    const columns = [
        {
            key: 'invoice_number',
            label: t('buying.purchase_invoices.table.invoice_number'),
            style: { fontWeight: 'bold' },
        },
        {
            key: 'supplier_name',
            label: t('buying.purchase_invoices.table.supplier'),
        },
        {
            key: 'invoice_date',
            label: t('buying.purchase_invoices.table.date'),
            render: (val) => formatShortDate(val),
        },
        {
            key: 'total',
            label: t('buying.purchase_invoices.table.total'),
            style: { fontWeight: 'bold' },
            render: (val, row) => {
                const invoiceCurrency = row.currency || row.base_currency || fallbackBaseCurrency
                const baseCurrency = row.base_currency || fallbackBaseCurrency
                const baseValue = Number(row.total_base ?? (Number(val || 0) * Number(row.exchange_rate || 1)))
                const isSameCurrency = invoiceCurrency === baseCurrency

                return (
                    <div>
                        <div>{formatNumber(val)} <small>{invoiceCurrency}</small></div>
                        {!isSameCurrency && (
                            <div className="text-muted" style={{ fontSize: '12px', fontWeight: 500 }}>
                                {formatNumber(baseValue)} <small>{baseCurrency}</small>
                            </div>
                        )}
                    </div>
                )
            },
        },
        {
            key: 'status',
            label: t('buying.purchase_invoices.table.status'),
            render: (val) => (
                <span className={`badge ${val === 'paid' ? 'badge-success' : val === 'partial' ? 'badge-warning' : 'badge-danger'}`}>
                    {val === 'paid' ? t('buying.purchase_invoices.details.status.paid') :
                        val === 'partial' ? t('buying.purchase_invoices.details.status.partial') :
                            t('buying.purchase_invoices.details.status.unpaid')}
                </span>
            ),
        },
    ]

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1 className="workspace-title">{t('buying.purchase_invoices.title')}</h1>
                        <p className="workspace-subtitle">{t('buying.purchase_invoices.subtitle')}</p>
                    </div>
                    <button className="btn btn-primary" onClick={() => navigate('/buying/invoices/new')}>
                        <span style={{ marginLeft: '8px' }}>+</span>
                        {t('buying.purchase_invoices.new_invoice')}
                    </button>
                </div>
            </div>

            {error && <div className="alert alert-error">{error}</div>}

            <SearchFilter
                value={search}
                onChange={setSearch}
                placeholder={t('buying.purchase_invoices.search_placeholder', '\u0628\u062D\u062B \u0628\u0631\u0642\u0645 \u0627\u0644\u0641\u0627\u062A\u0648\u0631\u0629 \u0623\u0648 \u0627\u0633\u0645 \u0627\u0644\u0645\u0648\u0631\u062F...')}
                filters={[{
                    key: 'status',
                    label: t('buying.purchase_invoices.table.status'),
                    options: [
                        { value: 'paid', label: t('buying.purchase_invoices.details.status.paid') },
                        { value: 'partial', label: t('buying.purchase_invoices.details.status.partial') },
                        { value: 'unpaid', label: t('buying.purchase_invoices.details.status.unpaid') },
                    ],
                }]}
                filterValues={{ status: statusFilter }}
                onFilterChange={(key, val) => setStatusFilter(val)}
            />

            <DataTable
                columns={columns}
                data={filteredInvoices}
                loading={loading}
                onRowClick={(row) => navigate(`/buying/invoices/${row.id}`)}
                emptyTitle={t('buying.purchase_invoices.empty.title')}
                emptyDesc={t('buying.purchase_invoices.empty.desc')}
                emptyAction={{ label: t('buying.purchase_invoices.empty.action'), onClick: () => navigate('/buying/invoices/new') }}
            />
        </div>
    )
}

export default PurchaseInvoiceList
