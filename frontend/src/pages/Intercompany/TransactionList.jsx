import { useState, useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { accountingAPI } from '../../utils/api'
import { formatNumber } from '../../utils/format'
import BackButton from '../../components/common/BackButton'
import DataTable from '../../components/common/DataTable'
import SearchFilter from '../../components/common/SearchFilter'
import { useToast } from '../../context/ToastContext'

function TransactionList() {
    const { t } = useTranslation()
    const { showToast } = useToast()
    const navigate = useNavigate()
    const [transactions, setTransactions] = useState([])
    const [loading, setLoading] = useState(true)
    const [statusFilter, setStatusFilter] = useState('')
    const [search, setSearch] = useState('')

    useEffect(() => { fetchData() }, [statusFilter])

    const fetchData = async () => {
        try {
            setLoading(true)
            const params = {}
            if (statusFilter) params.status = statusFilter
            const res = await accountingAPI.listICTransactionsV2(params)
            setTransactions(Array.isArray(res.data) ? res.data : [])
        } catch (e) {
            showToast(t('intercompany.load_error'), 'error')
        } finally {
            setLoading(false)
        }
    }

    const filtered = useMemo(() => {
        if (!search) return transactions
        const q = search.toLowerCase()
        return transactions.filter(txn =>
            (txn.source_entity_name || '').toLowerCase().includes(q) ||
            (txn.target_entity_name || '').toLowerCase().includes(q) ||
            (txn.reference_document || '').toLowerCase().includes(q) ||
            String(txn.id).includes(q)
        )
    }, [transactions, search])

    const statusClass = { pending: 'badge-warning', eliminated: 'badge-success', partial: 'badge-info' }

    const columns = [
        { key: 'id', label: '#', width: '60px' },
        { key: 'source_entity_name', label: t('intercompany.source_entity'), render: (_, txn) => txn.source_entity_name || txn.source_entity_id },
        { key: 'target_entity_name', label: t('intercompany.target_entity'), render: (_, txn) => txn.target_entity_name || txn.target_entity_id },
        { key: 'transaction_type', label: t('intercompany.type'), render: (v) => t(`intercompany.type_${v}`) },
        { key: 'source_amount', label: t('intercompany.source_amount'), render: (v, txn) => <>{formatNumber(v)} {txn.source_currency}</> },
        { key: 'target_amount', label: t('intercompany.target_amount'), render: (v, txn) => <>{formatNumber(v)} {txn.target_currency}</> },
        {
            key: 'elimination_status', label: t('intercompany.status'), render: (v) => (
                <span className={`badge ${statusClass[v] || 'badge-secondary'}`}>{t(`intercompany.status_${v}`)}</span>
            ),
        },
        { key: 'reference_document', label: t('intercompany.reference'), render: (v) => v || '-' },
    ]

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1 className="workspace-title">{t('intercompany.transactions_title')}</h1>
                        <p className="workspace-subtitle">{t('intercompany.transactions_subtitle')}</p>
                    </div>
                    <div style={{ display: 'flex', gap: '8px' }}>
                        <button className="btn btn-secondary" onClick={() => navigate('/accounting/intercompany/entities')}>
                            🏢 {t('intercompany.add_entity')}
                        </button>
                        <button className="btn btn-primary" onClick={() => navigate('/accounting/intercompany/transactions/new')}>
                            {t('intercompany.new_transaction')}
                        </button>
                    </div>
                </div>
            </div>

            <SearchFilter
                value={search}
                onChange={setSearch}
                placeholder={t('intercompany.search_placeholder')}
                filters={[{
                    key: 'status',
                    label: t('intercompany.status'),
                    options: [
                        { value: 'pending', label: t('intercompany.status_pending') },
                        { value: 'eliminated', label: t('intercompany.status_eliminated') },
                        { value: 'partial', label: t('intercompany.status_partial') },
                    ],
                }]}
                filterValues={{ status: statusFilter }}
                onFilterChange={(key, val) => setStatusFilter(val)}
            />

            <DataTable
                columns={columns}
                data={filtered}
                loading={loading}
                emptyIcon="🔄"
                emptyTitle={t('intercompany.no_transactions')}
                rowKey="id"
            />
        </div>
    )
}

export default TransactionList
