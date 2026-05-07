import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { salesAPI } from '../../utils/api'
import { useTranslation } from 'react-i18next'
import { formatShortDate } from '../../utils/dateUtils'
import { useBranch } from '../../context/BranchContext'
import { formatNumber } from '../../utils/format'
import { getCurrency } from '../../utils/auth'
import DataTable from '../../components/common/DataTable'
import SearchFilter from '../../components/common/SearchFilter'
import BackButton from '../../components/common/BackButton';

function InvoiceList() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { currentBranch } = useBranch()
    const fallbackBaseCurrency = getCurrency()
    const [invoices, setInvoices] = useState([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)
    const [search, setSearch] = useState('')
    const [statusFilter, setStatusFilter] = useState('')

    useEffect(() => {
        const fetchInvoices = async () => {
            try {
                setLoading(true)
                const response = await salesAPI.listInvoices({ branch_id: currentBranch?.id })
                const payload = response.data
                const normalizedInvoices = Array.isArray(payload)
                    ? payload
                    : (Array.isArray(payload?.items) ? payload.items : [])
                setInvoices(normalizedInvoices)
            } catch (err) {
                setError(t('common.error_loading'))
            } finally {
                setLoading(false)
            }
        }
        fetchInvoices()
    }, [currentBranch, t])

    const filteredInvoices = useMemo(() => {
        let result = Array.isArray(invoices) ? invoices : [];
        if (search) {
            const q = search.toLowerCase();
            result = result.filter(inv =>
                (inv.invoice_number || '').toLowerCase().includes(q) ||
                (inv.customer_name || '').toLowerCase().includes(q)
            );
        }
        if (statusFilter) {
            result = result.filter(inv => inv.status === statusFilter);
        }
        return result;
    }, [invoices, search, statusFilter]);

    const columns = [
        {
            key: 'invoice_number',
            label: t('sales.invoices.table.number'),
            style: { fontWeight: 'bold' },
        },
        {
            key: 'customer_name',
            label: t('sales.invoices.table.customer'),
        },
        {
            key: 'invoice_date',
            label: t('sales.invoices.table.date'),
            render: (val) => formatShortDate(val),
        },
        {
            key: 'total',
            label: t('sales.invoices.table.total'),
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
            label: t('sales.invoices.table.status'),
            render: (val) => (
                <span className={`badge ${val === 'paid' ? 'badge-success' : val === 'partial' ? 'badge-warning' : 'badge-danger'}`}>
                    {val === 'paid' ? t('sales.invoices.status.paid') :
                        val === 'partial' ? t('sales.invoices.status.partial') :
                            t('sales.invoices.status.unpaid')}
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
                        <h1 className="workspace-title">{t('sales.invoices.title')}</h1>
                        <p className="workspace-subtitle">{t('sales.invoices.subtitle')}</p>
                    </div>
                    <button className="btn btn-primary" onClick={() => navigate('/sales/invoices/new')}>
                        + {t('sales.invoices.create_new')}
                    </button>
                </div>
            </div>

            {error && <div className="alert alert-error">{error}</div>}

            <SearchFilter
                value={search}
                onChange={setSearch}
                placeholder={t('sales.invoices.search_placeholder', 'بحث برقم الفاتورة أو اسم العميل...')}
                filters={[{
                    key: 'status',
                    label: t('sales.invoices.table.status'),
                    options: [
                        { value: 'paid', label: t('sales.invoices.status.paid') },
                        { value: 'partial', label: t('sales.invoices.status.partial') },
                        { value: 'unpaid', label: t('sales.invoices.status.unpaid') },
                    ],
                }]}
                filterValues={{ status: statusFilter }}
                onFilterChange={(key, val) => setStatusFilter(val)}
            />

            <DataTable
                columns={columns}
                data={filteredInvoices}
                loading={loading}
                onRowClick={(row) => navigate(`/sales/invoices/${row.id}`)}
                emptyTitle={t('sales.invoices.no_invoices')}
                emptyDesc={t('sales.invoices.empty_desc')}
                emptyAction={{ label: t('sales.invoices.create_btn'), onClick: () => navigate('/sales/invoices/new') }}
            />
        </div>
    )
}

export default InvoiceList
