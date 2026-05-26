import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { crmAPI, salesAPI } from '../../utils/api'
import { getCurrency } from '../../utils/auth'
import { formatNumber } from '../../utils/format'
import '../../components/ModuleStyles.css'
import BackButton from '../../components/common/BackButton';
import DateInput from '../../components/common/DateInput';
import { useToast } from '../../context/ToastContext'
import { PageLoading } from '../../components/common/LoadingStates'

const stageBadgeColors = {
    lead: { background: '#3b82f6', color: '#fff' },
    qualified: { background: '#eab308', color: '#fff' },
    proposal: { background: '#f97316', color: '#fff' },
    negotiation: { background: '#8b5cf6', color: '#fff' },
    won: { background: '#22c55e', color: '#fff' },
    lost: { background: '#ef4444', color: '#fff' }
}

function Opportunities() {
    const { t } = useTranslation()
  const { showToast } = useToast()
    const navigate = useNavigate()
    const currency = getCurrency()

    const stageOptions = [
        { value: 'lead', label: t('crm.stage_lead') },
        { value: 'qualified', label: t('crm.stage_qualified') },
        { value: 'proposal', label: t('crm.stage_proposal') },
        { value: 'negotiation', label: t('crm.stage_negotiation') },
        { value: 'won', label: t('crm.stage_won') },
        { value: 'lost', label: t('crm.stage_lost') }
    ]

    const [opportunities, setOpportunities] = useState([])
    const [customers, setCustomers] = useState([])
    const [loading, setLoading] = useState(true)
    const [showModal, setShowModal] = useState(false)
    const [isEdit, setIsEdit] = useState(false)
    const [selectedId, setSelectedId] = useState(null)
    const [filterStage, setFilterStage] = useState('')
    const [deleteConfirm, setDeleteConfirm] = useState(null)

    const emptyForm = {
        title: '',
        customer_id: '',
        stage: 'lead',
        probability: 50,
        expected_value: '0.00',
        expected_close_date: '',
        source: '',
        notes: ''
    }
    const [formData, setFormData] = useState({ ...emptyForm })

    useEffect(() => {
        fetchOpportunities()
        fetchCustomers()
    }, [filterStage])

    const fetchOpportunities = async () => {
        try {
            setLoading(true)
            const params = {}
            if (filterStage) params.stage = filterStage
            const res = await crmAPI.listOpportunities(params)
            setOpportunities(res.data)
        } catch (err) {
            console.error('Failed to fetch opportunities', err)
        } finally {
            setLoading(false)
        }
    }

    const fetchCustomers = async () => {
        try {
            const res = await salesAPI.listCustomers()
            setCustomers(res.data || [])
        } catch (err) {
            console.error('Failed to fetch customers', err)
        }
    }

    const openCreate = () => {
        setFormData({ ...emptyForm })
        setIsEdit(false)
        setSelectedId(null)
        setShowModal(true)
    }

    const openEdit = (opp) => {
        setFormData({
            title: opp.title || '',
            customer_id: opp.customer_id || '',
            stage: opp.stage || 'lead',
            probability: opp.probability ?? 50,
            expected_value: opp.expected_value || '0.00',
            expected_close_date: opp.expected_close_date || '',
            source: opp.source || '',
            notes: opp.notes || ''
        })
        setIsEdit(true)
        setSelectedId(opp.id)
        setShowModal(true)
    }

    const handleChange = (e) => {
        const { name, value } = e.target
        setFormData(prev => ({ ...prev, [name]: value }))
    }

    const handleSubmit = async (e) => {
        e.preventDefault()
        try {
            const payload = {
                ...formData,
                probability: Number(formData.probability),
                expected_value: formData.expected_value || '0.00',
                customer_id: formData.customer_id ? Number(formData.customer_id) : null
            }
            if (isEdit) {
                await crmAPI.updateOpportunity(selectedId, payload)
            } else {
                await crmAPI.createOpportunity(payload)
            }
            setShowModal(false)
            fetchOpportunities()
        } catch (err) {
            console.error('Failed to save opportunity', err)
            showToast(err.response?.data?.detail || t('crm.save_error', 'error'))
        }
    }

    const handleDelete = async (id) => {
        try {
            await crmAPI.deleteOpportunity(id)
            setDeleteConfirm(null)
            fetchOpportunities()
        } catch (err) {
            console.error('Failed to delete opportunity', err)
            showToast(err.response?.data?.detail || t('crm.delete_error', 'error'))
        }
    }

    const handleConvertToQuotation = async (opp) => {
        if (!opp.customer_id) {
            showToast(t('crm.convert_no_customer', 'يجب تحديد عميل للفرصة قبل التحويل إلى عرض سعر', 'info'))
            return
        }
        try {
            const res = await crmAPI.convertToQuotation(opp.id)
            const quotationId = res.data?.quotation_id
            if (quotationId) {
                navigate(`/sales/quotations/${quotationId}`)
            } else {
                fetchOpportunities()
                showToast(t('crm.convert_success', 'تم تحويل الفرصة إلى عرض سعر بنجاح', 'success'))
            }
        } catch (err) {
            console.error('Failed to convert', err)
            showToast(err.response?.data?.detail || t('crm.convert_error', 'فشل تحويل الفرصة', 'error'))
        }
    }

    const getStageLabel = (stage) => {
        const opt = stageOptions.find(s => s.value === stage)
        return opt ? opt.label : stage
    }

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <h1 className="workspace-title">{t('crm.opportunities_title')}</h1>
                <p className="workspace-subtitle">{t('crm.opportunities_desc')}</p>
            </div>

            {/* Toolbar */}
            <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 16, flexWrap: 'wrap' }}>
                <button className="btn btn-primary" onClick={openCreate}>+ {t('crm.new_opportunity')}</button>
                <select
                    className="form-input"
                    style={{ maxWidth: 200 }}
                    value={filterStage}
                    onChange={e => setFilterStage(e.target.value)}
                >
                    <option value="">{t('crm.all_stages')}</option>
                    {stageOptions.map(s => (
                        <option key={s.value} value={s.value}>{s.label}</option>
                    ))}
                </select>
            </div>

            {/* Table */}
            {loading ? (
                <PageLoading />
            ) : opportunities.length === 0 ? (
                <div className="empty-state">{t('crm.no_opportunities')}</div>
            ) : (
                <div className="data-table-container">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('crm.title_label')}</th>
                            <th>{t('common.customer')}</th>
                            <th>{t('crm.stage')}</th>
                            <th>{t('crm.probability')}</th>
                            <th>{t('crm.expected_value')}</th>
                            <th>{t('crm.expected_close')}</th>
                            <th>{t('crm.responsible')}</th>
                            <th>{t('common.actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {opportunities.map(opp => (
                            <tr key={opp.id}>
                                <td>{opp.title}</td>
                                <td>{opp.customer_name || '-'}</td>
                                <td>
                                    <span
                                        className="badge"
                                        style={stageBadgeColors[opp.stage] || {}}
                                    >
                                        {getStageLabel(opp.stage)}
                                    </span>
                                </td>
                                <td>{opp.probability}%</td>
                                <td>{formatNumber(opp.expected_value)} {currency}</td>
                                <td>{opp.expected_close_date || '-'}</td>
                                <td>{opp.assigned_name || '-'}</td>
                                <td>
                                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                                        <button className="btn btn-secondary btn-sm" onClick={() => openEdit(opp)}>{t('crm.edit')}</button>
                                        {opp.stage !== 'won' && opp.stage !== 'lost' && opp.customer_id && (
                                            <button className="btn btn-primary btn-sm" onClick={() => handleConvertToQuotation(opp)} title={t('crm.convert_to_quotation', 'تحويل لعرض سعر')}>
                                                📋 {t('crm.convert_quotation_short', 'عرض سعر')}
                                            </button>
                                        )}
                                        <button className="btn btn-danger btn-sm" onClick={() => setDeleteConfirm(opp.id)}>{t('common.delete')}</button>
                                    </div>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                </div>
            )}

            {/* Delete Confirmation */}
            {deleteConfirm && (
                <div className="modal-overlay" onClick={() => setDeleteConfirm(null)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 420 }}>
                        <div className="modal-header">
                            <h3>{t('crm.confirm_delete')}</h3>
                        </div>
                        <div className="modal-body">
                            <p>{t('crm.confirm_delete_opportunity')}</p>
                        </div>
                        <div className="modal-footer">
                            <button className="btn btn-danger" onClick={() => handleDelete(deleteConfirm)}>{t('common.delete')}</button>
                            <button className="btn btn-secondary" onClick={() => setDeleteConfirm(null)}>{t('common.cancel')}</button>
                        </div>
                    </div>
                </div>
            )}

            {/* Create/Edit Modal */}
            {showModal && (
                <div className="modal-overlay" onClick={() => setShowModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 600 }}>
                        <div className="modal-header">
                            <h3>{isEdit ? t('crm.edit_opportunity') : t('crm.new_opportunity')}</h3>
                        </div>
                        <div className="modal-body">
                            <form id="opp-form" onSubmit={handleSubmit}>
                                <div className="form-section">
                                    <div className="form-grid">
                                        <div className="form-group">
                                            <label className="form-label">{t('crm.title_label')}</label>
                                            <input
                                                type="text"
                                                name="title"
                                                className="form-input"
                                                value={formData.title}
                                                onChange={handleChange}
                                                required
                                            />
                                        </div>
                                        <div className="form-group">
                                            <label className="form-label">{t('common.customer')}</label>
                                            <select className="form-input" name="customer_id" value={formData.customer_id} onChange={handleChange}>
                                                <option value="">{t('crm.select_customer')}</option>
                                                {customers.map(c => (
                                                    <option key={c.id} value={c.id}>{c.name}</option>
                                                ))}
                                            </select>
                                        </div>
                                        <div className="form-group">
                                            <label className="form-label">{t('crm.stage')}</label>
                                            <select className="form-input" name="stage" value={formData.stage} onChange={handleChange} required>
                                                {stageOptions.map(s => (
                                                    <option key={s.value} value={s.value}>{s.label}</option>
                                                ))}
                                            </select>
                                        </div>
                                        <div className="form-group">
                                            <label className="form-label">{t('crm.probability')} (%)</label>
                                            <input
                                                type="number"
                                                name="probability"
                                                className="form-input"
                                                min="0"
                                                max="100"
                                                value={formData.probability}
                                                onChange={handleChange}
                                            />
                                        </div>
                                        <div className="form-group">
                                            <label className="form-label">{t('crm.expected_value')}</label>
                                            <input
                                                type="number"
                                                name="expected_value"
                                                className="form-input"
                                                min="0"
                                                step="0.01"
                                                value={formData.expected_value}
                                                onChange={handleChange}
                                            />
                                        </div>
                                        <div className="form-group">
                                            <label className="form-label">{t('crm.expected_close')}</label>
                                            <DateInput
                                                name="expected_close_date"
                                                className="form-input"
                                                value={formData.expected_close_date}
                                                onChange={handleChange}
                                            />
                                        </div>
                                        <div className="form-group">
                                            <label className="form-label">{t('crm.source')}</label>
                                            <input
                                                type="text"
                                                name="source"
                                                className="form-input"
                                                value={formData.source}
                                                onChange={handleChange}
                                            />
                                        </div>
                                        <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                                            <label className="form-label">{t('common.notes')}</label>
                                            <textarea
                                                name="notes"
                                                className="form-input"
                                                rows={3}
                                                value={formData.notes}
                                                onChange={handleChange}
                                            />
                                        </div>
                                    </div>
                                </div>
                            </form>
                        </div>
                        <div className="modal-footer">
                            <button type="submit" form="opp-form" className="btn btn-primary">
                                {isEdit ? t('common.update') : t('common.create')}
                            </button>
                            <button type="button" className="btn btn-secondary" onClick={() => setShowModal(false)}>
                                {t('common.cancel')}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}

export default Opportunities
