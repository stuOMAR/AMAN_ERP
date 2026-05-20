import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { salesAPI } from '../../utils/api'
import { useTranslation } from 'react-i18next'
import { useBranch } from '../../context/BranchContext'
import { useToast } from '../../context/ToastContext'
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

function CustomerGroups() {
    const { t } = useTranslation()
    const { currentBranch } = useBranch()
    const { showToast } = useToast()
    const [groups, setGroups] = useState([])
    const [loading, setLoading] = useState(true)
    const [initialLoad, setInitialLoad] = useState(true)
    const [error, setError] = useState(null)
    const [showModal, setShowModal] = useState(false)
    const [currentGroup, setCurrentGroup] = useState(null)
    const [formData, setFormData] = useState({
        group_name: '',
        group_name_en: '',
        description: '',
        discount_percentage: 0,
        effect_type: 'discount',
        application_scope: 'total',
        payment_days: 30,
        status: 'active'
    })

    const fetchGroups = async () => {
        try {
            setLoading(true)
            const response = await salesAPI.listCustomerGroups({ branch_id: currentBranch?.id })
            setGroups(response.data)
            setError(null)
        } catch (err) {
            setError(t('sales.groups.form.errors.fetch_failed'))
        } finally {
            setLoading(false)
            setInitialLoad(false)
        }
    }

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchGroups()
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch])

    const handleOpenModal = (group = null) => {
        if (group) {
            setCurrentGroup(group)
            setFormData({
                group_name: group.group_name,
                group_name_en: group.group_name_en || '',
                description: group.description || '',
                discount_percentage: group.discount_percentage || 0,
                effect_type: group.effect_type || 'discount',
                application_scope: group.application_scope || 'total',
                payment_days: group.payment_days || 30,
                status: group.status || 'active'
            })
        } else {
            setCurrentGroup(null)
            setFormData({
                group_name: '',
                group_name_en: '',
                description: '',
                discount_percentage: 0,
                effect_type: 'discount',
                application_scope: 'total',
                payment_days: 30,
                status: 'active'
            })
        }
        setShowModal(true)
    }

    const handleSubmit = async (e) => {
        e.preventDefault()
        setError(null)
        try {
            const payload = {
                ...formData,
                discount_percentage: String(formData.discount_percentage || '0'),
                payment_days: parseInt(formData.payment_days) || 30,
                branch_id: currentBranch?.id
            }

            if (currentGroup) {
                await salesAPI.updateCustomerGroup(currentGroup.id, payload)
            } else {
                await salesAPI.createCustomerGroup(payload)
            }
            setShowModal(false)
            fetchGroups()
        } catch (err) {
            const detail = err.response?.data?.detail
            if (typeof detail === 'string') setError(detail)
            else if (Array.isArray(detail)) setError(detail.map(e => e.msg).join(', '))
            else setError(t('common.error_occurred'))
        }
    }

    const handleDelete = async (id) => {
        if (!window.confirm(t('sales.groups.actions.delete_confirm'))) return
        try {
            await salesAPI.deleteCustomerGroup(id)
            fetchGroups()
        } catch (err) {
            showToast(t('sales.groups.actions.delete_error'), 'error')
        }
    }

    if (initialLoad && groups.length === 0) return <PageLoading />

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">📁 {t('sales.groups.title')}</h1>
                    <p className="workspace-subtitle">{t('sales.groups.subtitle')}</p>
                </div>
                <div className="header-actions">
                    <button onClick={() => handleOpenModal()} className="btn btn-primary">
                        + {t('sales.groups.create_new')}
                    </button>
                    <Link to="/sales" className="btn btn-secondary">
                        {t('sales.groups.back')}
                    </Link>
                </div>
            </div>

            {error && <div className="alert alert-error mb-4">{error}</div>}

            <div className="card">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('sales.groups.table.name_ar')}</th>
                            <th>{t('sales.groups.table.name_en')}</th>
                            <th>{t('sales.groups.table.discount')}</th>
                            <th>{t('sales.groups.table.payment_days')}</th>
                            <th>{t('sales.groups.table.description')}</th>
                            <th>{t('sales.groups.table.status')}</th>
                            <th>{t('sales.groups.table.actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {groups.length === 0 ? (
                            <tr>
                                <td colSpan="7" className="text-center py-5 text-muted">{t('sales.groups.empty')}</td>
                            </tr>
                        ) : (
                            groups.map(group => (
                                <tr key={group.id}>
                                    <td className="font-medium">{group.group_name}</td>
                                    <td className="text-muted">{group.group_name_en}</td>
                                    <td>
                                        {group.discount_percentage > 0 ? (
                                            <span className="badge badge-success">{group.discount_percentage}%</span>
                                        ) : '-'}
                                    </td>
                                    <td>{group.payment_days} {t('sales.reports.aging.buckets.days')}</td>
                                    <td className="text-small text-muted">{group.description}</td>
                                    <td>
                                        <span className={`status-badge ${group.status}`}>
                                            {group.status === 'active' ? t('sales.groups.status.active') : t('sales.groups.status.inactive')}
                                        </span>
                                    </td>
                                    <td>
                                        <div className="action-buttons">
                                            <button
                                                onClick={() => handleOpenModal(group)}
                                                className="btn-icon"
                                                title={t('sales.groups.actions.edit')}
                                            >
                                                ✏️
                                            </button>
                                            <button
                                                onClick={() => handleDelete(group.id)}
                                                className="btn-icon delete"
                                                title={t('sales.groups.actions.delete')}
                                            >
                                                🗑️
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>

            {showModal && (
                <div className="modal-overlay fade-in">
                    <div className="modal-content" style={{ maxWidth: '600px' }}>
                        <div className="modal-header">
                            <h2>{currentGroup ? t('sales.groups.modal.edit_title') : t('sales.groups.modal.create_title')}</h2>
                            <button onClick={() => setShowModal(false)} className="btn-close">×</button>
                        </div>
                        <form onSubmit={handleSubmit} className="modal-body">
                            <div className="form-row">
                                <div className="form-group">
                                    <label className="form-label">{t('sales.groups.form.name_ar')} *</label>
                                    <input
                                        type="text"
                                        required
                                        className="form-input"
                                        value={formData.group_name}
                                        onChange={e => setFormData({ ...formData, group_name: e.target.value })}
                                        placeholder=""
                                    />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('sales.groups.form.name_en')}</label>
                                    <input
                                        type="text"
                                        className="form-input"
                                        value={formData.group_name_en}
                                        onChange={e => setFormData({ ...formData, group_name_en: e.target.value })}
                                        placeholder=""
                                    />
                                </div>
                            </div>

                            <div className="form-row">
                                <div className="form-group">
                                    <label className="form-label">{t('sales.groups.form.discount')}</label>
                                    <input
                                        type="number"
                                        min="0"
                                        max="100"
                                        step="0.01"
                                        className="form-input"
                                        value={formData.discount_percentage}
                                        onChange={e => setFormData({ ...formData, discount_percentage: e.target.value })}
                                    />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('sales.groups.form.payment_days')}</label>
                                    <input
                                        type="number"
                                        min="0"
                                        className="form-input"
                                        value={formData.payment_days}
                                        onChange={e => setFormData({ ...formData, payment_days: e.target.value })}
                                    />
                                </div>
                            </div>

                            <div className="form-group">
                                <label className="form-label">{t('sales.groups.form.status')}</label>
                                <select
                                    className="form-input"
                                    value={formData.status}
                                    onChange={e => setFormData({ ...formData, status: e.target.value })}
                                >
                                    <option value="active">{t('sales.groups.status.active')}</option>
                                    <option value="inactive">{t('sales.groups.status.inactive')}</option>
                                </select>
                            </div>

                            <div className="form-row">
                                <div className="form-group">
                                    <label className="form-label">{t('sales.effect_type')}</label>
                                    <select
                                        className="form-input"
                                        value={formData.effect_type}
                                        onChange={e => setFormData({ ...formData, effect_type: e.target.value })}
                                    >
                                        <option value="discount">{t('common.discount')}</option>
                                        <option value="markup">{t('common.increase')}</option>
                                    </select>
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('sales.application_scope')}</label>
                                    <select
                                        className="form-input"
                                        value={formData.application_scope}
                                        onChange={e => setFormData({ ...formData, application_scope: e.target.value })}
                                    >
                                        <option value="total">{t('pos.receipt.total')}</option>
                                        <option value="line">{t('common.per_item')}</option>
                                    </select>
                                </div>
                            </div>

                            <div className="form-group">
                                <label className="form-label">{t('sales.groups.form.description')}</label>
                                <textarea
                                    className="form-input"
                                    rows="3"
                                    value={formData.description}
                                    onChange={e => setFormData({ ...formData, description: e.target.value })}
                                    placeholder={t('sales.groups.form.placeholder_desc')}
                                />
                            </div>

                            <div className="modal-actions">
                                <button type="button" onClick={() => setShowModal(false)} className="btn btn-secondary">
                                    {t('sales.groups.actions.cancel')}
                                </button>
                                <button type="submit" className="btn btn-primary">
                                    {t('sales.groups.actions.save')}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    )
}

export default CustomerGroups
