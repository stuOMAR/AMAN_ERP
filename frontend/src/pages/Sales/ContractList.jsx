import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { contractsAPI } from '../../utils/api'
import { getCurrency } from '../../utils/auth'
import { useTranslation } from 'react-i18next'
import { formatShortDate } from '../../utils/dateUtils'
import { useBranch } from '../../context/BranchContext'
import { formatNumber } from '../../utils/format'
import BackButton from '../../components/common/BackButton'
import DataTable from '../../components/common/DataTable'
import SearchFilter from '../../components/common/SearchFilter'

function ContractList() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { currentBranch } = useBranch()
    const currency = getCurrency()
    const [contracts, setContracts] = useState([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)
    const [search, setSearch] = useState('')
    const [statusFilter, setStatusFilter] = useState('')
    const [typeFilter, setTypeFilter] = useState('')

    useEffect(() => {
        const fetchContracts = async () => {
            try {
                setLoading(true)
                const response = await contractsAPI.listContracts({ branch_id: currentBranch?.id })
                setContracts(response.data)
            } catch (err) {
                setError(t('common.error_loading'))
            } finally {
                setLoading(false)
            }
        }
        fetchContracts()
    }, [currentBranch, t])

    const getStatusBadge = (status) => {
        switch (status) {
            case 'active': return 'badge-success'
            case 'expired': return 'badge-danger'
            case 'cancelled': return 'badge-ghost'
            default: return 'badge-info'
        }
    }

    const filteredContracts = useMemo(() => {
        let result = contracts
        if (search) {
            const q = search.toLowerCase()
            result = result.filter(c =>
                (c.contract_number || '').toLowerCase().includes(q) ||
                (c.party_name || '').toLowerCase().includes(q)
            )
        }
        if (statusFilter) {
            result = result.filter(c => c.status === statusFilter)
        }
        if (typeFilter) {
            result = result.filter(c => c.contract_type === typeFilter)
        }
        return result
    }, [contracts, search, statusFilter, typeFilter])

    const columns = [
        {
            key: 'contract_number',
            label: t('sales.contracts.table.number'),
            style: { fontWeight: 'bold' },
        },
        {
            key: 'party_name',
            label: t('sales.contracts.table.customer'),
        },
        {
            key: 'contract_type',
            label: t('sales.contracts.table.type'),
            render: (val) => val === 'subscription' ? t('sales.contracts.subscription') : t('sales.contracts.fixed'),
        },
        {
            key: 'start_date',
            label: t('sales.contracts.table.start_date'),
            render: (val) => formatShortDate(val),
        },
        {
            key: 'total_amount',
            label: t('sales.contracts.table.total'),
            style: { fontWeight: 'bold' },
            render: (val, row) => formatNumber(val) + ' ' + (row.currency || currency),
        },
        {
            key: 'status',
            label: t('sales.contracts.table.status'),
            render: (val) => (
                <span className={`badge ${getStatusBadge(val)}`}>
                    {val}
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
                        <h1 className="workspace-title">{t('sales.contracts.title')}</h1>
                        <p className="workspace-subtitle">{t('sales.contracts.subtitle')}</p>
                    </div>
                    <button className="btn btn-primary" onClick={() => navigate('/sales/contracts/new')}>
                        + {t('sales.contracts.create_new')}
                    </button>
                </div>
            </div>

            {error && <div className="alert alert-error">{error}</div>}

            <SearchFilter
                value={search}
                onChange={setSearch}
                placeholder={t('common.search')}
                filters={[
                    {
                        key: 'status',
                        label: t('sales.contracts.table.status'),
                        options: [
                            { value: 'active', label: 'Active' },
                            { value: 'expired', label: 'Expired' },
                            { value: 'cancelled', label: 'Cancelled' },
                            { value: 'draft', label: 'Draft' },
                        ],
                    },
                    {
                        key: 'type',
                        label: t('sales.contracts.table.type'),
                        options: [
                            { value: 'subscription', label: t('sales.contracts.subscription') },
                            { value: 'fixed', label: t('sales.contracts.fixed') },
                        ],
                    },
                ]}
                filterValues={{ status: statusFilter, type: typeFilter }}
                onFilterChange={(key, val) => {
                    if (key === 'status') setStatusFilter(val)
                    if (key === 'type') setTypeFilter(val)
                }}
            />

            <DataTable
                columns={columns}
                data={filteredContracts}
                loading={loading}
                onRowClick={(row) => navigate(`/sales/contracts/${row.id}`)}
                emptyTitle={t('sales.contracts.no_contracts')}
                emptyDesc={t('sales.contracts.empty_desc')}
                emptyAction={{ label: t('sales.contracts.create_btn'), onClick: () => navigate('/sales/contracts/new') }}
            />
        </div>
    )
}

export default ContractList
