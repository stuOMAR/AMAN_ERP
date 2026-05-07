import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { accountingAPI, currenciesAPI } from '../../utils/api'
import { getCurrency } from '../../utils/auth'
import BackButton from '../../components/common/BackButton'
import FormField from '../../components/common/FormField'
import { useToast } from '../../context/ToastContext'
import { PageLoading } from '../../components/common/LoadingStates'

function EntityGroupTree() {
    const { t } = useTranslation()
    const { showToast } = useToast()
    const [entities, setEntities] = useState([])
    const [currencies, setCurrencies] = useState([])
    const [loading, setLoading] = useState(true)
    const [showForm, setShowForm] = useState(false)
    const [form, setForm] = useState({ name: '', parent_id: '', company_id: '', group_currency: getCurrency() || 'SAR' })
    const [editingId, setEditingId] = useState(null)
    const [editingCurrency, setEditingCurrency] = useState('SAR')

    useEffect(() => {
        fetchEntities()
        currenciesAPI.list()
            .then(res => setCurrencies(Array.isArray(res.data) ? res.data : []))
            .catch(() => {})
    }, [])

    const fetchEntities = async () => {
        try {
            setLoading(true)
            const res = await accountingAPI.listEntityGroups()
            setEntities(Array.isArray(res.data) ? res.data : [])
        } catch (e) {
            showToast(t('intercompany.load_error'), 'error')
        } finally {
            setLoading(false)
        }
    }

    const handleSubmit = async (e) => {
        e.preventDefault()
        try {
            await accountingAPI.createEntityGroup({
                ...form,
                group_currency: String(form.group_currency || 'SAR').toUpperCase(),
                parent_id: form.parent_id ? parseInt(form.parent_id) : null,
            })
            showToast(t('intercompany.entity_created'), 'success')
            setShowForm(false)
            setForm({ name: '', parent_id: '', company_id: '', group_currency: getCurrency() || 'SAR' })
            fetchEntities()
        } catch (e) {
            showToast(e.response?.data?.detail || t('intercompany.create_error'), 'error')
        }
    }

    const startEditCurrency = (node) => {
        setEditingId(node.id)
        setEditingCurrency(String(node.group_currency || 'SAR').toUpperCase())
    }

    const saveCurrency = async (id) => {
        try {
            await accountingAPI.updateEntityGroup(id, {
                group_currency: String(editingCurrency || 'SAR').toUpperCase(),
            })
            showToast(t('intercompany.entity_updated', 'تم تحديث الكيان'), 'success')
            setEditingId(null)
            fetchEntities()
        } catch (e) {
            showToast(e.response?.data?.detail || t('intercompany.update_error', 'تعذر تحديث الكيان'), 'error')
        }
    }

    const buildTree = (items, parentId = null) => {
        return items
            .filter(i => (i.parent_id || null) === parentId)
            .map(item => ({
                ...item,
                children: buildTree(items, item.id),
            }))
    }

    const renderNode = (node, depth = 0) => (
        <div key={node.id} style={{ marginInlineStart: depth * 24 + 'px' }}>
            <div className="card" style={{ marginBottom: 8, padding: '12px 16px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                    <div>
                        <strong>{node.name}</strong>
                        <span className="badge" style={{ marginInlineStart: 8, marginInlineEnd: 8 }}>
                            {t('intercompany.level')} {node.consolidation_level}
                        </span>
                        {editingId === node.id ? (
                            <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
                                <select
                                    className="form-input"
                                    style={{ width: 120, padding: '2px 6px' }}
                                    value={editingCurrency}
                                    onChange={e => setEditingCurrency(e.target.value)}
                                >
                                    {currencies.length === 0 && <option value={editingCurrency}>{editingCurrency}</option>}
                                    {currencies.map(c => (
                                        <option key={c.code} value={c.code}>{c.code}</option>
                                    ))}
                                </select>
                                <button type="button" className="btn btn-success btn-sm" onClick={() => saveCurrency(node.id)}>
                                    {t('common.save')}
                                </button>
                                <button type="button" className="btn btn-secondary btn-sm" onClick={() => setEditingId(null)}>
                                    {t('common.cancel')}
                                </button>
                            </span>
                        ) : (
                            <small className="text-muted" style={{ cursor: 'pointer' }} onClick={() => startEditCurrency(node)}>
                                {node.group_currency} ✎
                            </small>
                        )}
                    </div>
                    <small className="text-muted">{node.company_id}</small>
                </div>
            </div>
            {node.children?.map(child => renderNode(child, depth + 1))}
        </div>
    )

    const tree = buildTree(entities)

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1 className="workspace-title">{t('intercompany.entity_tree_title')}</h1>
                        <p className="workspace-subtitle">{t('intercompany.entity_tree_subtitle')}</p>
                    </div>
                    <button className="btn btn-primary" onClick={() => setShowForm(!showForm)}>
                        {showForm ? t('common.cancel') : t('intercompany.add_entity')}
                    </button>
                </div>
            </div>

            {showForm && (
                <form onSubmit={handleSubmit} className="card" style={{ padding: 16, marginBottom: 16 }}>
                    <div className="form-row">
                        <FormField label={t('intercompany.entity_name')} required>
                            <input type="text" className="form-input" required value={form.name}
                                onChange={e => setForm({ ...form, name: e.target.value })} />
                        </FormField>
                        <FormField label={t('intercompany.company_id')} required>
                            <input type="text" className="form-input" required value={form.company_id}
                                onChange={e => setForm({ ...form, company_id: e.target.value })} />
                        </FormField>
                        <FormField label={t('intercompany.group_currency')}>
                            <select className="form-input" value={form.group_currency}
                                onChange={e => setForm({ ...form, group_currency: e.target.value })}>
                                {currencies.length === 0 && <option value={form.group_currency}>{form.group_currency}</option>}
                                {currencies.map(c => (
                                    <option key={c.code} value={c.code}>{c.code} — {c.name || c.name_en || c.code}</option>
                                ))}
                            </select>
                        </FormField>
                        <FormField label={t('intercompany.parent_entity')}>
                            <select className="form-input" value={form.parent_id} onChange={e => setForm({ ...form, parent_id: e.target.value })}>
                                <option value="">{t('intercompany.root_entity')}</option>
                                {entities.map(ent => (
                                    <option key={ent.id} value={ent.id}>{ent.name}</option>
                                ))}
                            </select>
                        </FormField>
                    </div>
                    <button type="submit" className="btn btn-success">{t('common.save')}</button>
                </form>
            )}

            {loading ? (
                <PageLoading />
            ) : tree.length === 0 ? (
                <div className="card text-center py-5"><p className="text-muted">{t('intercompany.no_entities')}</p></div>
            ) : (
                <div className="ic-tree">{tree.map(node => renderNode(node))}</div>
            )}
        </div>
    )
}

export default EntityGroupTree
