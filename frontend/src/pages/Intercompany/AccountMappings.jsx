import { useState, useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { accountingAPI } from '../../utils/api'
import BackButton from '../../components/common/BackButton'
import DataTable from '../../components/common/DataTable'
import SearchFilter from '../../components/common/SearchFilter'
import { useToast } from '../../context/ToastContext'

function AccountMappings() {
    const { t } = useTranslation()
    const { showToast } = useToast()
    const [mappings, setMappings] = useState([])
    const [entities, setEntities] = useState([])
    const [loading, setLoading] = useState(true)
    const [showForm, setShowForm] = useState(false)
    const [search, setSearch] = useState('')
    const [form, setForm] = useState({
        source_entity_id: '',
        target_entity_id: '',
        source_account_id: '',
        target_account_id: '',
    })

    const fetchData = async () => {
        try {
            setLoading(true)
            const [mappingRes, entityRes] = await Promise.all([
                accountingAPI.listAccountMappings(),
                accountingAPI.listEntityGroups(),
            ])
            setMappings(Array.isArray(mappingRes.data) ? mappingRes.data : [])
            setEntities(Array.isArray(entityRes.data) ? entityRes.data : [])
        } catch {
            showToast(t('intercompany.load_error'), 'error')
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => { fetchData() }, [])

    const handleSubmit = async (e) => {
        e.preventDefault()
        try {
            await accountingAPI.createAccountMapping({
                source_entity_id: parseInt(form.source_entity_id),
                target_entity_id: parseInt(form.target_entity_id),
                source_account_id: parseInt(form.source_account_id),
                target_account_id: parseInt(form.target_account_id),
            })
            showToast(t('intercompany.mapping_created'), 'success')
            setShowForm(false)
            setForm({ source_entity_id: '', target_entity_id: '', source_account_id: '', target_account_id: '' })
            fetchData()
        } catch (e) {
            showToast(e.response?.data?.detail || t('intercompany.create_error'), 'error')
        }
    }

    const entityName = (id) => {
        const ent = entities.find(e => e.id === id)
        return ent ? ent.name : `#${id}`
    }

    const filteredMappings = useMemo(() => {
        if (!search.trim()) return mappings
        const q = search.toLowerCase()
        return mappings.filter(m => {
            const srcName = entityName(m.source_entity_id).toLowerCase()
            const tgtName = entityName(m.target_entity_id).toLowerCase()
            const srcAcct = String(m.source_account_id)
            const tgtAcct = String(m.target_account_id)
            return srcName.includes(q) || tgtName.includes(q) || srcAcct.includes(q) || tgtAcct.includes(q)
        })
    }, [mappings, entities, search])

    const columns = [
        { key: 'id', label: '#' },
        { key: 'source_entity_id', label: t('intercompany.source_entity'), render: (value) => entityName(value) },
        { key: 'target_entity_id', label: t('intercompany.target_entity'), render: (value) => entityName(value) },
        { key: 'source_account_id', label: t('intercompany.source_account') },
        { key: 'target_account_id', label: t('intercompany.target_account') },
    ]

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div>
                    <h1 className="workspace-title">{t('intercompany.mappings_subtitle')}</h1>
                </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBlockEnd: 16 }}>
                <SearchFilter value={search} onChange={setSearch} placeholder={t('common.search')} />
                <button className="btn btn-primary" onClick={() => setShowForm(!showForm)}>
                    {showForm ? t('common.cancel') : t('intercompany.add_mapping')}
                </button>
            </div>

            {showForm && (
                <form onSubmit={handleSubmit} className="card" style={{ padding: 16, marginBlockEnd: 16 }}>
                    <div className="form-row">
                        <div className="form-group">
                            <label>{t('intercompany.source_entity')} *</label>
                            <select required value={form.source_entity_id}
                                onChange={e => setForm({ ...form, source_entity_id: e.target.value })}>
                                <option value="">{t('common.select')}</option>
                                {entities.map(ent => <option key={ent.id} value={ent.id}>{ent.name}</option>)}
                            </select>
                        </div>
                        <div className="form-group">
                            <label>{t('intercompany.target_entity')} *</label>
                            <select required value={form.target_entity_id}
                                onChange={e => setForm({ ...form, target_entity_id: e.target.value })}>
                                <option value="">{t('common.select')}</option>
                                {entities.map(ent => <option key={ent.id} value={ent.id}>{ent.name}</option>)}
                            </select>
                        </div>
                    </div>
                    <div className="form-row">
                        <div className="form-group">
                            <label>{t('intercompany.source_account')} * (ID)</label>
                            <input type="number" required value={form.source_account_id}
                                onChange={e => setForm({ ...form, source_account_id: e.target.value })} />
                        </div>
                        <div className="form-group">
                            <label>{t('intercompany.target_account')} * (ID)</label>
                            <input type="number" required value={form.target_account_id}
                                onChange={e => setForm({ ...form, target_account_id: e.target.value })} />
                        </div>
                    </div>
                    <button type="submit" className="btn btn-success">{t('common.save')}</button>
                </form>
            )}

            <DataTable
                data={filteredMappings}
                columns={columns}
                loading={loading}
                emptyTitle={t('intercompany.no_mappings')}
                emptyAction={null}
            />
        </div>
    )
}

export default AccountMappings
