import { useState, useEffect, useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { inventoryAPI } from '../../utils/api'
import { Edit2, Trash2, Plus, X, Layers } from 'lucide-react'
import { useBranch } from '../../context/BranchContext'
import { useToast } from '../../context/ToastContext'
import BackButton from '../../components/common/BackButton'
import DataTable from '../../components/common/DataTable'
import SearchFilter from '../../components/common/SearchFilter'

function CategoryList() {
    const { t } = useTranslation()
    const { currentBranch } = useBranch()
    const { showToast } = useToast()
    const [categories, setCategories] = useState([])
    const [loading, setLoading] = useState(true)
    const [initialLoad, setInitialLoad] = useState(true)
    const [error, setError] = useState(null)
    const [showModal, setShowModal] = useState(false)
    const [editingItem, setEditingItem] = useState(null)
    const [formData, setFormData] = useState({ name: '', code: '' })
    const [search, setSearch] = useState('')

    const fetchCategories = useCallback(async () => {
        try {
            setLoading(true)
            const res = await inventoryAPI.listCategories({ branch_id: currentBranch?.id })
            setCategories(res.data)
        } catch (err) {
            setError(t('stock.categories.validation.error_fetch'))
        } finally {
            setLoading(false)
            setInitialLoad(false)
        }
    }, [currentBranch, t])

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchCategories()
        }, 300)
        return () => clearTimeout(timer)
    }, [fetchCategories])

    const handleSubmit = async (e) => {
        e.preventDefault()
        try {
            if (editingItem) {
                await inventoryAPI.updateCategory(editingItem.id, { ...formData })
            } else {
                await inventoryAPI.createCategory({ ...formData })
            }
            setShowModal(false)
            setEditingItem(null)
            setFormData({ name: '', code: '' })
            fetchCategories()
        } catch (err) {
            showToast(t('stock.categories.validation.error_save'), 'error')
        }
    }

    const handleDelete = async (id) => {
        if (window.confirm(t('stock.categories.validation.delete_confirm'))) {
            try {
                await inventoryAPI.deleteCategory(id)
                fetchCategories()
            } catch (err) {
                showToast(t('stock.categories.validation.delete_error'), 'error')
            }
        }
    }

    const openModal = async (item = null) => {
        if (item) {
            setEditingItem(item)
            setFormData({ name: item.name, code: item.code })
            setShowModal(true)
        } else {
            setEditingItem(null)
            setFormData({ name: '', code: '...' })
            setShowModal(true)
            try {
                const res = await inventoryAPI.getNextCategoryCode()
                setFormData(prev => ({ ...prev, code: res.data.next_code }))
            } catch (err) {
                showToast(t('stock.categories.validation.error_fetch_code'), 'error')
                setFormData(prev => ({ ...prev, code: '' }))
            }
        }
    }

    const filteredCategories = useMemo(() => {
        if (!search) return categories
        const q = search.toLowerCase()
        return categories.filter(cat =>
            (cat.name || '').toLowerCase().includes(q) ||
            (cat.code || '').toLowerCase().includes(q)
        )
    }, [categories, search])

    const columns = [
        {
            key: 'code',
            label: t('stock.categories.table.code'),
            render: (val) => <span className="font-medium text-primary">{val}</span>,
        },
        {
            key: 'name',
            label: t('stock.categories.table.name'),
            render: (val) => <span style={{ fontWeight: 600 }}>{val}</span>,
        },
        {
            key: '_actions',
            label: t('stock.categories.table.actions'),
            width: '100px',
            render: (_, row) => (
                <div style={{ display: 'flex', gap: '8px' }}>
                    <button
                        onClick={(e) => {
                            e.stopPropagation()
                            openModal(row)
                        }}
                        className="btn-icon"
                        style={{ width: '30px', height: '30px', background: 'var(--bg-secondary)', color: 'var(--text-secondary)' }}
                        title={t('common.edit')}
                    >
                        <Edit2 size={14} />
                    </button>
                    <button
                        onClick={(e) => {
                            e.stopPropagation()
                            handleDelete(row.id)
                        }}
                        className="btn-icon"
                        style={{ width: '30px', height: '30px', background: '#fee2e2', color: '#ef4444' }}
                        title={t('common.delete')}
                    >
                        <Trash2 size={14} />
                    </button>
                </div>
            ),
        },
    ]

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div>
                    <h1 className="workspace-title" style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                        <Layers size={28} className="text-primary" />
                        {t('stock.categories.title')}
                    </h1>
                    <p className="workspace-subtitle">{t('stock.categories.subtitle')}</p>
                </div>
                <button className="btn btn-primary" onClick={() => openModal()}>
                    <Plus size={18} />
                    {t('stock.categories.new_category')}
                </button>
            </div>

            <SearchFilter
                value={search}
                onChange={setSearch}
                placeholder={t('stock.categories.search_placeholder', 'بحث بالاسم أو الكود...')}
            />

            <DataTable
                columns={columns}
                data={filteredCategories}
                loading={loading}
                emptyIcon="📂"
                emptyTitle={t('stock.categories.empty')}
            />

            {/* Modal */}
            {showModal && (
                <div style={{
                    position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
                    background: 'rgba(0,0,0,0.5)', zIndex: 1000,
                    display: 'flex', alignItems: 'center', justifyContent: 'center'
                }}>
                    <div className="fade-in" style={{
                        background: 'var(--bg-card)', padding: '24px', borderRadius: '12px',
                        width: '400px', maxWidth: '90%'
                    }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '20px' }}>
                            <h2 style={{ fontSize: '18px', fontWeight: '700' }}>
                                {editingItem ? t('stock.categories.editing_category') : t('stock.categories.new_category')}
                            </h2>
                            <button onClick={() => setShowModal(false)}><X size={20} /></button>
                        </div>

                        <form onSubmit={handleSubmit}>
                            <div className="form-group">
                                <label className="form-label">{t('stock.categories.form.name')}</label>
                                <input
                                    className="form-input"
                                    value={formData.name}
                                    onChange={e => setFormData({ ...formData, name: e.target.value })}
                                    required
                                    autoFocus
                                />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('stock.categories.form.code')}</label>
                                <input
                                    className="form-input"
                                    value={formData.code}
                                    onChange={e => setFormData({ ...formData, code: e.target.value })}
                                    required
                                />
                            </div>
                            <div style={{ display: 'flex', gap: '10px', marginTop: '24px' }}>
                                <button type="submit" className="btn btn-primary btn-block">{t('stock.categories.form.save')}</button>
                                <button type="button" className="btn" style={{ background: 'var(--bg-secondary)', width: '100%' }} onClick={() => setShowModal(false)}>{t('stock.categories.form.cancel')}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    )
}

export default CategoryList
