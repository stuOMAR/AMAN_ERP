import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { inventoryAPI, companiesAPI } from '../../utils/api'
import { useTranslation } from 'react-i18next'
import { useBranch } from '../../context/BranchContext'
import { useToast } from '../../context/ToastContext'
import { formatShortDate } from '../../utils/dateUtils'
import DataTable from '../../components/common/DataTable'
import SearchFilter from '../../components/common/SearchFilter'
import BackButton from '../../components/common/BackButton'

function SupplierList() {
    const { t, i18n } = useTranslation()
    const navigate = useNavigate()
    const { currentBranch } = useBranch()
    const { showToast } = useToast()
    const [suppliers, setSuppliers] = useState([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)
    const [currency, setCurrency] = useState('')
    const [search, setSearch] = useState('')
    const [statusFilter, setStatusFilter] = useState('')

    useEffect(() => {
        const fetchData = async () => {
            try {
                setLoading(true)
                const userStr = localStorage.getItem('user')
                const user = userStr ? JSON.parse(userStr) : null
                const companyId = user?.company_id || localStorage.getItem('company_id')

                const [suppliersRes, companyRes] = await Promise.all([
                    inventoryAPI.listSuppliers({ branch_id: currentBranch?.id }),
                    companyId ? companiesAPI.getCurrentCompany(companyId) : Promise.resolve({ data: { currency: '' } })
                ])

                setSuppliers(suppliersRes.data)
                if (companyRes.data && companyRes.data.currency) {
                    setCurrency(companyRes.data.currency)
                }
            } catch (err) {
                setError(t('common.error_loading'))
                showToast(t('common.error'), 'error')
            } finally {
                setLoading(false)
            }
        }
        fetchData()
    }, [t, currentBranch])

    const filteredSuppliers = useMemo(() => {
        let result = suppliers
        if (search) {
            const q = search.toLowerCase()
            result = result.filter(s =>
                (s.name || '').toLowerCase().includes(q) ||
                (s.name_en || '').toLowerCase().includes(q) ||
                (s.party_code || '').toLowerCase().includes(q) ||
                (s.phone || '').includes(q)
            )
        }
        if (statusFilter) {
            if (statusFilter === 'active') {
                result = result.filter(s => s.is_active)
            } else if (statusFilter === 'inactive') {
                result = result.filter(s => !s.is_active)
            }
        }
        return result
    }, [suppliers, search, statusFilter])

    const columns = [
        {
            key: 'party_code',
            label: t('buying.suppliers.table.code'),
            width: '12%',
            render: (val) => (
                <span style={{ fontFamily: 'monospace', fontWeight: 600, color: 'var(--primary)', fontSize: '13px', background: 'rgba(37,99,235,0.08)', padding: '2px 8px', borderRadius: '4px' }}>
                    {val || '\u2014'}
                </span>
            ),
        },
        {
            key: 'name',
            label: t('buying.suppliers.table.name'),
            width: '25%',
            render: (val, row) => (
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <div style={{
                        width: '36px', height: '36px', borderRadius: '50%', background: 'var(--bg-hover)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '18px',
                    }}>
                        {'\uD83C\uDFE2'}
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
            label: t('buying.suppliers.table.contact'),
            width: '20%',
            render: (val, row) => (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    {val && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px' }}>
                            <span>{'\uD83D\uDCDE'}</span>
                            <span style={{ direction: 'ltr' }}>{val}</span>
                        </div>
                    )}
                    {row.email && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', color: 'var(--text-secondary)' }}>
                            <span>{'\u2709\uFE0F'}</span>
                            <span>{row.email}</span>
                        </div>
                    )}
                    {!val && !row.email && <span style={{ color: 'var(--text-muted)' }}>-</span>}
                </div>
            ),
        },
        {
            key: 'balance_display',
            label: t('buying.suppliers.table.balance'),
            width: '15%',
            render: (val, row) => (
                <div style={{
                    fontWeight: '600', fontSize: '15px',
                    color: val > 0 ? 'var(--error)' : 'var(--text-primary)',
                    direction: 'ltr',
                    textAlign: i18n.language === 'ar' ? 'right' : 'left',
                }}>
                    {(val || 0).toLocaleString()} {row.display_currency || currency}
                </div>
            ),
        },
        {
            key: 'is_active',
            label: t('buying.suppliers.table.status'),
            width: '10%',
            render: (val) => (
                <span className={`badge ${val ? 'badge-success' : 'badge-danger'}`}>
                    {val ? t('common.active') : t('common.inactive')}
                </span>
            ),
        },
        {
            key: 'created_at',
            label: t('buying.suppliers.table.created_at'),
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
                    onClick={(e) => { e.stopPropagation(); navigate(`/buying/suppliers/${row.id}/edit`); }}
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
                        <h1 className="workspace-title">{t('buying.suppliers.title')}</h1>
                        <p className="workspace-subtitle">{t('buying.suppliers.subtitle')}</p>
                    </div>
                    <button className="btn btn-primary" onClick={() => navigate('/buying/suppliers/new')}>
                        <span style={{ marginLeft: '8px' }}>+</span>
                        {t('buying.suppliers.new_supplier')}
                    </button>
                </div>
            </div>

            {error && <div className="alert alert-error">{error}</div>}

            <SearchFilter
                value={search}
                onChange={setSearch}
                placeholder={t('buying.suppliers.search_placeholder', '\u0628\u062D\u062B \u0628\u0627\u0644\u0627\u0633\u0645 \u0623\u0648 \u0627\u0644\u0643\u0648\u062F \u0623\u0648 \u0627\u0644\u0647\u0627\u062A\u0641...')}
                filters={[{
                    key: 'status',
                    label: t('buying.suppliers.table.status'),
                    options: [
                        { value: 'active', label: t('common.active') },
                        { value: 'inactive', label: t('common.inactive') },
                    ],
                }]}
                filterValues={{ status: statusFilter }}
                onFilterChange={(key, val) => setStatusFilter(val)}
            />

            <DataTable
                columns={columns}
                data={filteredSuppliers}
                loading={loading}
                onRowClick={(row) => navigate(`/buying/suppliers/${row.id}`)}
                emptyIcon={'\uD83C\uDFEC'}
                emptyTitle={t('buying.suppliers.empty.title')}
                emptyDesc={t('buying.suppliers.empty.desc')}
                emptyAction={{ label: t('buying.suppliers.empty.action'), onClick: () => navigate('/buying/suppliers/new') }}
            />
        </div>
    )
}

export default SupplierList
