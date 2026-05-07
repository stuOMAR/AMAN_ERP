import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { salesAPI } from '../../utils/api'
import { getCurrency } from '../../utils/auth'
import { useTranslation } from 'react-i18next'
import { formatNumber } from '../../utils/format'
import { useBranch } from '../../context/BranchContext'
import { formatShortDate } from '../../utils/dateUtils';
import DataTable from '../../components/common/DataTable'
import SearchFilter from '../../components/common/SearchFilter'
import BackButton from '../../components/common/BackButton';


function CustomerList() {
    const { t } = useTranslation()
    const navigate = useNavigate()
    const { currentBranch } = useBranch()
    const [customers, setCustomers] = useState([])
    const [currency] = useState(getCurrency())
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)
    const [search, setSearch] = useState('')
    const [statusFilter, setStatusFilter] = useState('')

    useEffect(() => {
        const fetchCustomers = async () => {
            try {
                setLoading(true)
                const response = await salesAPI.listCustomers({ branch_id: currentBranch?.id })
                setCustomers(response.data)
            } catch (err) {
                setError(t('common.error_loading'))
            } finally {
                setLoading(false)
            }
        }
        fetchCustomers()
    }, [currentBranch, t])

    const filteredCustomers = useMemo(() => {
        let result = customers;
        if (search) {
            const q = search.toLowerCase();
            result = result.filter(c =>
                (c.name || '').toLowerCase().includes(q) ||
                (c.name_en || '').toLowerCase().includes(q) ||
                (c.phone || '').includes(q) ||
                (c.party_code || '').toLowerCase().includes(q)
            );
        }
        if (statusFilter) {
            result = result.filter(c => c.status === statusFilter);
        }
        return result;
    }, [customers, search, statusFilter]);

    const columns = [
        {
            key: 'party_code',
            label: t('sales.customers.table.code'),
            width: '12%',
            render: (val) => (
                <span style={{ fontFamily: 'monospace', fontWeight: 600, color: 'var(--primary)', fontSize: '13px', background: 'rgba(37,99,235,0.08)', padding: '2px 8px', borderRadius: '4px' }}>
                    {val || '\u2014'}
                </span>
            ),
        },
        {
            key: 'name',
            label: t('sales.customers.table.name'),
            width: '25%',
            render: (val, row) => (
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <div style={{
                        width: '36px', height: '36px', borderRadius: '50%', background: 'var(--bg-hover)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '18px',
                    }}>
                        {'\uD83D\uDC64'}
                    </div>
                    <div>
                        <div style={{ fontWeight: '600', color: 'var(--text-primary)' }}>{val}</div>
                        {row.name_en && <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>{row.name_en}</div>}
                    </div>
                </div>
            ),
        },
        {
            key: 'phone',
            label: t('sales.customers.table.contact'),
            width: '20%',
            render: (val, row) => (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    {val && <div style={{ fontSize: '13px', direction: 'ltr' }}>{val}</div>}
                    {row.email && <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>{row.email}</div>}
                    {!val && !row.email && <span style={{ color: 'var(--text-muted)' }}>-</span>}
                </div>
            ),
        },
        {
            key: 'balance_display',
            label: t('sales.customers.table.balance'),
            width: '15%',
            render: (val, row) => (
                <div style={{
                    fontWeight: '600', fontSize: '15px',
                    color: val > 0 ? 'var(--error)' : 'var(--text-primary)',
                    direction: 'ltr', textAlign: 'right',
                }}>
                    {formatNumber(val)} {row.display_currency || currency}
                </div>
            ),
        },
        {
            key: 'status',
            label: t('sales.customers.table.status'),
            width: '10%',
            render: (val) => (
                <span className={`badge ${val === 'active' ? 'badge-success' : 'badge-danger'}`}>
                    {val === 'active' ? t('sales.customers.status.active') : t('sales.customers.status.inactive')}
                </span>
            ),
        },
        {
            key: 'created_at',
            label: t('sales.customers.table.added_date'),
            width: '10%',
            render: (val) => <span style={{ color: 'var(--text-secondary)', fontSize: '13px' }}>{formatShortDate(val)}</span>,
        },
        {
            key: '_actions',
            label: t('common.actions'),
            width: '8%',
            headerStyle: { textAlign: 'center' },
            style: { textAlign: 'center' },
            render: (_, row) => (
                <button
                    className="btn btn-icon"
                    title={t('common.edit', 'Edit')}
                    onClick={(e) => { e.stopPropagation(); navigate(`/sales/customers/${row.id}/edit`); }}
                    style={{ padding: '4px', color: 'var(--primary)' }}
                >
                    {'\u270F\uFE0F'}
                </button>
            ),
        },
    ]

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1 className="workspace-title">{t('sales.customers.title')}</h1>
                        <p className="workspace-subtitle">{t('sales.customers.subtitle')}</p>
                    </div>
                    <button className="btn btn-primary" onClick={() => navigate('/sales/customers/new')}>
                        <span style={{ marginLeft: '8px' }}>+</span>
                        {t('sales.customers.add_new')}
                    </button>
                </div>
            </div>

            {error && <div className="alert alert-error">{error}</div>}

            <SearchFilter
                value={search}
                onChange={setSearch}
                placeholder={t('sales.customers.search_placeholder', 'بحث بالاسم أو الكود أو الهاتف...')}
                filters={[{
                    key: 'status',
                    label: t('sales.customers.table.status'),
                    options: [
                        { value: 'active', label: t('sales.customers.status.active') },
                        { value: 'inactive', label: t('sales.customers.status.inactive') },
                    ],
                }]}
                filterValues={{ status: statusFilter }}
                onFilterChange={(key, val) => setStatusFilter(val)}
            />

            <DataTable
                columns={columns}
                data={filteredCustomers}
                loading={loading}
                onRowClick={(row) => navigate(`/sales/customers/${row.id}`)}
                emptyIcon={'\uD83D\uDC65'}
                emptyTitle={t('sales.customers.no_customers')}
                emptyDesc={t('sales.customers.empty_state_desc')}
                emptyAction={{ label: t('sales.customers.add_first'), onClick: () => navigate('/sales/customers/new') }}
            />
        </div>
    )
}

export default CustomerList
