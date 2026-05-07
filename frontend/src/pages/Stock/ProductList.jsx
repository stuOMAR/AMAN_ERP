import React, { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { inventoryAPI, api } from '../../utils/api'
import { getCurrency, hasPermission } from '../../utils/auth'
import { useBranch } from '../../context/BranchContext'
import { formatNumber } from '../../utils/format'
import { ChevronDown, ChevronUp, Info } from 'lucide-react'
import { formatShortDate } from '../../utils/dateUtils'
import DataTable from '../../components/common/DataTable'
import SearchFilter from '../../components/common/SearchFilter'
import BackButton from '../../components/common/BackButton'
import { useToast } from '../../context/ToastContext'
import { Spinner } from '../../components/common/LoadingStates'

function ProductList() {
    const { t } = useTranslation()
    const { showToast } = useToast()
    const navigate = useNavigate()
    const { currentBranch } = useBranch()
    const [products, setProducts] = useState([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)
    const [expandedProductId, setExpandedProductId] = useState(null)
    const [breakdownData, setBreakdownData] = useState(null)
    const [loadingBreakdown, setLoadingBreakdown] = useState(false)
    const [policyType, setPolicyType] = useState('global_wac')
    const [showDeleteModal, setShowDeleteModal] = useState(false)
    const [productToDelete, setProductToDelete] = useState(null)
    const [search, setSearch] = useState('')
    const [typeFilter, setTypeFilter] = useState('')

    const currency = getCurrency()
    const canViewCost = hasPermission('stock.view_cost')
    const canCreate = hasPermission('stock.create_product')
    const canDelete = hasPermission('stock.delete_product')

    const [branchPrices, setBranchPrices] = useState({});
    const [branchCurrency, setBranchCurrency] = useState('SAR');
    const [branchRate, setBranchRate] = useState(1);

    useEffect(() => {
        const fetchData = async () => {
            try {
                setLoading(true)
                const [prodRes, priceRes] = await Promise.all([
                    inventoryAPI.listProducts({ branch_id: currentBranch?.id }),
                    inventoryAPI.getBranchPrices(currentBranch?.id)
                ])
                setProducts(prodRes.data)
                setBranchPrices(priceRes.data?.prices || {})
                setBranchCurrency(priceRes.data?.currency || 'SAR')
                setBranchRate(priceRes.data?.rate || 1)

                try {
                    const policyRes = await api.get('/costing-policies/current')
                    setPolicyType(policyRes.data.policy_type)
                } catch (e) {
                    console.warn("Could not fetch policy, defaulting to global")
                }
            } catch (err) {
                setError(t('stock.products.validation.error_fetch'))
                console.error(err)
            } finally {
                setLoading(false)
            }
        }
        fetchData()
    }, [currentBranch, t])

    const handleExpand = async (e, productId) => {
        e.stopPropagation()

        if (expandedProductId === productId) {
            setExpandedProductId(null)
            setBreakdownData(null)
            return
        }

        setExpandedProductId(productId)
        setLoadingBreakdown(true)
        try {
            const res = await api.get(`/inventory/products/${productId}/cost-breakdown`)
            setBreakdownData(res.data.breakdown)
        } catch (err) {
            console.error("Failed to load breakdown", err)
        } finally {
            setLoadingBreakdown(false)
        }
    }

    const handleDeleteClick = (e, product) => {
        e.stopPropagation()
        setProductToDelete(product)
        setShowDeleteModal(true)
    }

    const handleDeleteConfirm = async () => {
        try {
            await inventoryAPI.deleteProduct(productToDelete.id)
            setProducts(products.filter(p => p.id !== productToDelete.id))
            setShowDeleteModal(false)
            setProductToDelete(null)
        } catch (err) {
            const errorMsg = err.response?.data?.detail || t('stock.products.validation.error_delete')
            showToast(errorMsg, 'error')
        }
    }

    const filteredProducts = useMemo(() => {
        let result = products
        if (search) {
            const q = search.toLowerCase()
            result = result.filter(p =>
                (p.item_name || '').toLowerCase().includes(q) ||
                (p.item_code || '').toLowerCase().includes(q)
            )
        }
        if (typeFilter) {
            result = result.filter(p => p.item_type === typeFilter)
        }
        return result
    }, [products, search, typeFilter])

    const columns = [
        {
            key: '_expand',
            label: '',
            width: '5%',
            render: (_, row) => (
                (policyType !== 'global_wac' && canViewCost) ? (
                    <span onClick={(e) => handleExpand(e, row.id)} style={{ cursor: 'pointer', textAlign: 'center', display: 'block' }}>
                        {expandedProductId === row.id ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                    </span>
                ) : null
            ),
        },
        {
            key: 'item_code',
            label: t('stock.products.table.code'),
            width: '15%',
            style: { fontFamily: 'monospace', fontWeight: 'bold', color: 'var(--text-secondary)' },
        },
        {
            key: 'item_name',
            label: t('stock.products.table.name'),
            width: '25%',
            render: (val) => (
                <div style={{ fontWeight: '600', color: 'var(--text-primary)' }}>{val}</div>
            ),
        },
        {
            key: 'item_type',
            label: t('stock.products.table.type'),
            width: '10%',
            render: (val) => (
                <span className={`badge ${val === 'service' ? 'badge-info' : 'badge-primary'}`}>
                    {t(`stock.products.types.${val}`)}
                </span>
            ),
        },
        {
            key: 'category_name',
            label: t('stock.products.table.category'),
            width: '15%',
            render: (val) => val || '-',
        },
        ...(canViewCost ? [{
            key: 'buying_price',
            label: t('stock.products.table.cost'),
            width: '10%',
            render: (val, row) => {
                const branchCost = row.branch_avg_cost;
                const rawCost = branchCost && parseFloat(branchCost) > 0 ? branchCost : val;
                // Convert from SAR to branch currency
                const displayCost = branchRate !== 1 ? (parseFloat(rawCost) / branchRate) : rawCost;
                return (
                    <div style={{ fontWeight: '600', color: 'var(--text-primary)' }}>
                        {formatNumber(displayCost || 0)} {branchCurrency}
                        {branchCost && parseFloat(branchCost) > 0 && parseFloat(branchCost) !== parseFloat(val) && (
                            <div style={{ fontSize: '10px', color: 'var(--text-secondary)' }}>
                                {t('stock.products.branch_cost', 'Branch Avg')}
                            </div>
                        )}
                    </div>
                );
            },
        }] : []),
        {
            key: 'selling_price',
            label: t('stock.products.table.price'),
            width: '10%',
            render: (val, row) => {
                const branchPrice = branchPrices[row.id]?.price;
                const displayPrice = branchPrice || val;
                const priceCurrency = branchPrice ? (branchPrices[row.id]?.currency || currency) : currency;
                return (
                    <div style={{ fontWeight: '600', color: 'var(--success)' }}>
                        {formatNumber(displayPrice)} {priceCurrency}
                        {branchPrice && (
                            <div style={{ fontSize: '10px', color: 'var(--text-secondary)' }}>
                                {t('stock.products.branch_price', 'Branch Price')}
                            </div>
                        )}
                    </div>
                );
            },
        },
        {
            key: 'reserved_quantity',
            label: t('stock.products.table.reserved'),
            width: '10%',
            render: (val, row) => (
                <div style={{ fontWeight: '500', color: 'var(--warning)' }}>
                    {formatNumber(val)} <span style={{ fontSize: '12px' }}>{row.unit}</span>
                </div>
            ),
        },
        {
            key: 'current_stock',
            label: t('stock.products.table.stock'),
            width: '10%',
            render: (val, row) => (
                <div style={{ fontWeight: '500' }}>
                    {formatNumber(val)} <span style={{ fontSize: '12px' }}>{row.unit}</span>
                </div>
            ),
        },
        ...(canDelete ? [{
            key: '_actions',
            label: t('common.actions'),
            width: '80px',
            render: (_, row) => (
                <button
                    onClick={(e) => handleDeleteClick(e, row)}
                    className="btn-icon"
                    title={t('common.delete')}
                    style={{ color: 'var(--danger)', padding: '4px 8px' }}
                >
                    {'\uD83D\uDDD1\uFE0F'}
                </button>
            ),
        }] : []),
    ]

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1 className="workspace-title">{t('stock.products.title')}</h1>
                        <p className="workspace-subtitle">{t('stock.products.subtitle')}</p>
                    </div>
                    {canCreate && (
                        <button className="btn btn-primary" onClick={() => navigate('/stock/products/new')}>
                            <span style={{ marginLeft: '8px' }}>+</span>
                            {t('stock.products.new_product')}
                        </button>
                    )}
                </div>
            </div>

            {error && <div className="alert alert-error">{error}</div>}

            <SearchFilter
                value={search}
                onChange={setSearch}
                placeholder={t('stock.products.search_placeholder', '\u0628\u062D\u062B \u0628\u0627\u0633\u0645 \u0627\u0644\u0645\u0646\u062A\u062C \u0623\u0648 \u0627\u0644\u0643\u0648\u062F...')}
                filters={[{
                    key: 'type',
                    label: t('stock.products.table.type'),
                    options: [
                        { value: 'goods', label: t('stock.products.types.goods') },
                        { value: 'service', label: t('stock.products.types.service') },
                    ],
                }]}
                filterValues={{ type: typeFilter }}
                onFilterChange={(key, val) => setTypeFilter(val)}
            />

            <DataTable
                columns={columns}
                data={filteredProducts}
                loading={loading}
                onRowClick={(row) => navigate(`/stock/products/${row.id}`)}
                emptyIcon={'\uD83D\uDCE6'}
                emptyTitle={t('stock.products.empty')}
                emptyAction={canCreate ? { label: t('stock.products.add_first'), onClick: () => navigate('/stock/products/new') } : undefined}
            />

            {/* Expanded cost breakdown row — rendered as overlay below the DataTable */}
            {expandedProductId && (
                <div style={{ padding: '16px', background: 'var(--bg-subtle)', border: '1px solid var(--border-color)', borderRadius: '8px', marginTop: '-1px' }}>
                    <h4 style={{ fontSize: '14px', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <Info size={16} /> {t('stock.products.cost_by_warehouse')}
                    </h4>
                    {loadingBreakdown ? (
                        <Spinner size="sm"/>
                    ) : (
                        <table className="table table-sm" style={{ background: 'white', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                            <thead>
                                <tr style={{ background: 'var(--bg-secondary)' }}>
                                    <th>{t("stock.products.warehouse")}</th>
                                    <th>{t("stock.products.available_qty")}</th>
                                    <th>{t("stock.products.avg_cost")}</th>
                                    <th>{t("stock.products.total_value")}</th>
                                    <th>{t("stock.products.last_updated")}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {breakdownData && breakdownData.map((wh, idx) => (
                                    <tr key={idx}>
                                        <td>{wh.warehouse_name}</td>
                                        <td>{formatNumber(wh.quantity)}</td>
                                        <td style={{ fontWeight: 'bold' }}>{formatNumber(wh.average_cost)} {currency}</td>
                                        <td>{formatNumber(wh.total_value)} {currency}</td>
                                        <td style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                                            {wh.last_update ? formatShortDate(wh.last_update) : '-'}
                                        </td>
                                    </tr>
                                ))}
                                {(!breakdownData || breakdownData.length === 0) && (
                                    <tr><td colSpan="5" className="text-center">{t("stock.products.no_stock_data")}</td></tr>
                                )}
                            </tbody>
                        </table>
                    )}
                </div>
            )}

            {/* Delete Confirmation Modal */}
            {showDeleteModal && (
                <div className="modal-overlay" onClick={() => setShowDeleteModal(false)}>
                    <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '450px' }}>
                        <div className="modal-header">
                            <h2 style={{ color: 'var(--danger)' }}>{'\u26A0\uFE0F'} {t('common.confirm_delete')}</h2>
                            <button onClick={() => setShowDeleteModal(false)} className="close-btn">&times;</button>
                        </div>
                        <div style={{ padding: '1rem 0' }}>
                            <p>{t('stock.products.delete_confirm_message', { name: productToDelete?.name })}</p>
                            <p style={{ fontSize: '14px', color: 'var(--text-secondary)', marginTop: '8px' }}>
                                {t('common.action_cannot_be_undone')}
                            </p>
                        </div>
                        <div className="modal-actions" style={{ marginTop: '1.5rem' }}>
                            <button onClick={() => setShowDeleteModal(false)} className="btn btn-secondary">
                                {t('common.cancel')}
                            </button>
                            <button onClick={handleDeleteConfirm} className="btn btn-danger">
                                {t('common.delete')}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            <style>{`
                .modal-overlay {
                    position: fixed;
                    top: 0; left: 0; right: 0; bottom: 0;
                    background: rgba(0,0,0,0.5);
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    z-index: 1000;
                }
                .modal-content {
                    background: white;
                    padding: 1.5rem;
                    border-radius: 12px;
                    box-shadow: 0 4px 20px rgba(0,0,0,0.15);
                }
                .modal-header {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-bottom: 1rem;
                }
                .close-btn {
                    background: none;
                    border: none;
                    font-size: 1.5rem;
                    cursor: pointer;
                    color: var(--text-secondary);
                }
                .modal-actions {
                    display: flex;
                    justify-content: flex-end;
                    gap: 0.75rem;
                }
                .btn-danger {
                    background-color: var(--danger);
                    color: white;
                    border: none;
                    padding: 0.5rem 1.5rem;
                    border-radius: 6px;
                    cursor: pointer;
                    font-weight: 500;
                }
                .btn-danger:hover {
                    opacity: 0.9;
                }
            `}</style>
        </div>
    )
}

export default ProductList
