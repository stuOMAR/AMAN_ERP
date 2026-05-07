import React, { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { accountingAPI } from '../../utils/api'
import { useToast } from '../../context/ToastContext'
import { useBranch } from '../../context/BranchContext'
import { getCurrency } from '../../utils/auth'
import BackButton from '../../components/common/BackButton'

import DateInput from '../../components/common/DateInput';
import { formatDate } from '../../utils/dateUtils';
import { PageLoading } from '../../components/common/LoadingStates'


export default function RecurringTemplates() {
    const { t, i18n } = useTranslation()
    const { showToast } = useToast()
    const { currentBranch } = useBranch()
    const currency = getCurrency()

    const [templates, setTemplates] = useState([])
    const [loading, setLoading] = useState(true)
    const [accounts, setAccounts] = useState([])
    const [showModal, setShowModal] = useState(false)
    const [showDetailModal, setShowDetailModal] = useState(false)
    const [editId, setEditId] = useState(null)
    const [detailData, setDetailData] = useState(null)
    const [generating, setGenerating] = useState(null)
    const [filterActive, setFilterActive] = useState('')

    const [form, setForm] = useState({
        name: '', description: '', reference: '',
        frequency: 'monthly', start_date: '', end_date: '',
        next_run_date: '', is_active: true, auto_post: false,
        currency: getCurrency(), exchange_rate: 1, max_runs: '',
        lines: [
            { account_id: '', debit: '', credit: '', description: '', cost_center_id: '' },
            { account_id: '', debit: '', credit: '', description: '', cost_center_id: '' },
        ],
    })

    const fetchTemplates = useCallback(async () => {
        setLoading(true)
        try {
            const params = {}
            if (filterActive !== '') params.is_active = filterActive === 'true'
            if (currentBranch?.id) params.branch_id = currentBranch.id
            const res = await accountingAPI.listRecurringTemplates(params)
            setTemplates(res.data)
        } catch {
            showToast(t('recurring.error_loading'), 'error')
        } finally {
            setLoading(false)
        }
    }, [filterActive, currentBranch])

    const fetchAccounts = async () => {
        try {
            const res = await accountingAPI.list({}, { skipBranchScope: true })
            setAccounts(Array.isArray(res.data) ? res.data : res.data?.data || [])
        } catch { /* ignore */ }
    }

    useEffect(() => { fetchTemplates() }, [fetchTemplates])
    useEffect(() => { fetchAccounts() }, [])

    const resetForm = () => {
        setForm({
            name: '', description: '', reference: '',
            frequency: 'monthly', start_date: '', end_date: '',
            next_run_date: '', is_active: true, auto_post: false,
            currency: getCurrency(), exchange_rate: 1, max_runs: '',
            lines: [
                { account_id: '', debit: '', credit: '', description: '', cost_center_id: '' },
                { account_id: '', debit: '', credit: '', description: '', cost_center_id: '' },
            ],
        })
        setEditId(null)
    }

    const openCreate = () => { resetForm(); setShowModal(true) }

    const openEdit = async (id) => {
        try {
            const res = await accountingAPI.getRecurringTemplate(id)
            const d = res.data
            setForm({
                name: d.name || '', description: d.description || '', reference: d.reference || '',
                frequency: d.frequency || 'monthly',
                start_date: d.start_date ? d.start_date.slice(0, 10) : '',
                end_date: d.end_date ? d.end_date.slice(0, 10) : '',
                next_run_date: d.next_run_date ? d.next_run_date.slice(0, 10) : '',
                is_active: d.is_active, auto_post: d.auto_post,
                currency: d.currency || getCurrency(), exchange_rate: d.exchange_rate || 1,
                max_runs: d.max_runs || '',
                lines: d.lines.length ? d.lines.map(l => ({
                    account_id: l.account_id,
                    debit: l.debit !== '' && l.debit != null ? parseFloat(l.debit) : '',
                    credit: l.credit !== '' && l.credit != null ? parseFloat(l.credit) : '',
                    description: l.description || '', cost_center_id: l.cost_center_id || ''
                })) : [
                    { account_id: '', debit: '', credit: '', description: '', cost_center_id: '' },
                    { account_id: '', debit: '', credit: '', description: '', cost_center_id: '' },
                ],
            })
            setEditId(id)
            setShowModal(true)
        } catch {
            showToast(t('recurring.error_details'), 'error')
        }
    }

    const openDetail = async (id) => {
        try {
            const res = await accountingAPI.getRecurringTemplate(id)
            setDetailData(res.data)
            setShowDetailModal(true)
        } catch {
            showToast(t('recurring.error'), 'error')
        }
    }

    const handleSubmit = async (e) => {
        e.preventDefault()
        const payload = {
            ...form,
            branch_id: currentBranch?.id || null,
            max_runs: form.max_runs ? parseInt(form.max_runs) : null,
            end_date: form.end_date || null,
            next_run_date: form.next_run_date || form.start_date,
            lines: form.lines.filter(l => l.account_id).map(l => ({
                account_id: parseInt(l.account_id),
                debit: parseFloat(l.debit) || 0,
                credit: parseFloat(l.credit) || 0,
                description: l.description,
                cost_center_id: l.cost_center_id ? parseInt(l.cost_center_id) : null,
            })),
        }

        try {
            if (editId) {
                await accountingAPI.updateRecurringTemplate(editId, payload)
                showToast(t('recurring.template_updated'), 'success')
            } else {
                await accountingAPI.createRecurringTemplate(payload)
                showToast(t('recurring.template_created'), 'success')
            }
            setShowModal(false)
            resetForm()
            fetchTemplates()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        }
    }

    const handleDelete = async (id, name) => {
        if (!confirm(`${t('recurring.delete_confirm')} "${name}"?`)) return
        try {
            await accountingAPI.deleteRecurringTemplate(id)
            showToast(t('recurring.deleted'), 'success')
            fetchTemplates()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        }
    }

    const handleGenerate = async (id) => {
        setGenerating(id)
        try {
            const res = await accountingAPI.generateFromTemplate(id)
            showToast(
                `${t('recurring.generated_entry')} #${res.data.entry_id}`,
                'success'
            )
            fetchTemplates()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        } finally {
            setGenerating(null)
        }
    }

    const handleGenerateAll = async () => {
        try {
            const res = await accountingAPI.generateDueTemplates()
            const d = res.data
            showToast(
                `${t('recurring.generated_count')}: ${d.generated_count}${d.error_count ? ` (${d.error_count} ${t('recurring.errors_count')})` : ''}`,
                d.error_count ? 'warning' : 'success'
            )
            fetchTemplates()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        }
    }

    const addLine = () => {
        setForm(f => ({
            ...f,
            lines: [...f.lines, { account_id: '', debit: '', credit: '', description: '', cost_center_id: '' }]
        }))
    }

    const removeLine = (idx) => {
        if (form.lines.length <= 2) return
        setForm(f => ({ ...f, lines: f.lines.filter((_, i) => i !== idx) }))
    }

    const updateLine = (idx, field, value) => {
        setForm(f => {
            const lines = [...f.lines]
            lines[idx] = { ...lines[idx], [field]: value }
            return { ...f, lines }
        })
    }

    const totalDebit = form.lines.reduce((s, l) => s + (parseFloat(l.debit) || 0), 0)
    const totalCredit = form.lines.reduce((s, l) => s + (parseFloat(l.credit) || 0), 0)
    const isBalanced = Math.abs(totalDebit - totalCredit) < 0.01

    const freqLabel = (f) => t(`recurring.freq_${f}`) || f

    return (
        <div className="workspace fade-in" dir={i18n.dir()}>
            <div className="workspace-header">
                <div className="d-flex justify-content-between align-items-center flex-wrap gap-2">
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                        <BackButton />
                        <div>
                            <h1 className="workspace-title">🔄 {t('recurring.title')}</h1>
                        </div>
                    </div>
                    <div className="d-flex gap-2">
                        <select className="form-input" style={{ width: 'auto' }}
                            value={filterActive} onChange={e => setFilterActive(e.target.value)}>
                            <option value="">{t('recurring.filter_all')}</option>
                            <option value="true">{t('recurring.filter_active')}</option>
                            <option value="false">{t('recurring.filter_inactive')}</option>
                        </select>
                        <button className="btn btn-outline-primary btn-sm" onClick={handleGenerateAll}>
                            ⚡ {t('recurring.generate_due')}
                        </button>
                        <button className="btn btn-primary btn-sm" onClick={openCreate}>
                            + {t('recurring.new_template')}
                        </button>
                    </div>
                </div>
            </div>

            {loading ? (
                <PageLoading />
            ) : templates.length === 0 ? (
                <div className="text-center text-muted p-5">
                    {t('recurring.no_templates')}
                </div>
            ) : (
                <div className="data-table-container">
                    <table className="data-table table-hover">
                        <thead>
                            <tr>
                                <th>#</th>
                                <th>{t('recurring.name')}</th>
                                <th>{t('recurring.frequency')}</th>
                                <th>{t('recurring.next_run')}</th>
                                <th>{t('recurring.last_run')}</th>
                                <th>{t('recurring.runs')}</th>
                                <th>{t('recurring.auto_post')}</th>
                                <th>{t('recurring.status')}</th>
                                <th>{t('recurring.actions')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {templates.map((tmpl, idx) => (
                                <tr key={tmpl.id}>
                                    <td>{idx + 1}</td>
                                    <td>
                                        <a href="#" onClick={(e) => { e.preventDefault(); openDetail(tmpl.id) }}
                                            className="text-primary text-decoration-none fw-bold">
                                            {tmpl.name}
                                        </a>
                                        {tmpl.reference && <div className="text-muted small">{tmpl.reference}</div>}
                                    </td>
                                    <td><span className="badge bg-info">{freqLabel(tmpl.frequency)}</span></td>
                                    <td>{tmpl.next_run_date || '-'}</td>
                                    <td>{tmpl.last_run_date || '-'}</td>
                                    <td>
                                        {tmpl.run_count || 0}
                                        {tmpl.max_runs && <span className="text-muted">/{tmpl.max_runs}</span>}
                                    </td>
                                    <td>{tmpl.auto_post ? '✅' : '❌'}</td>
                                    <td>
                                        <span className={`badge ${tmpl.is_active ? 'bg-success' : 'bg-secondary'}`}>
                                            {tmpl.is_active ? t('recurring.filter_active') : t('recurring.filter_inactive')}
                                        </span>
                                    </td>
                                    <td>
                                        <div className="btn-group btn-group-sm">
                                            <button className="btn btn-outline-success" title={t('recurring.generate_now')}
                                                disabled={generating === tmpl.id} onClick={() => handleGenerate(tmpl.id)}>
                                                {generating === tmpl.id ? '⏳' : '⚡'}
                                            </button>
                                            <button className="btn btn-outline-primary" onClick={() => openEdit(tmpl.id)}>✏️</button>
                                            <button className="btn btn-outline-danger" onClick={() => handleDelete(tmpl.id, tmpl.name)}>🗑</button>
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            {/* Create / Edit Modal */}
            {showModal && (
                <div className="modal-overlay">
                    <div className="modal-content" style={{ maxWidth: '900px' }}>
                        <form onSubmit={handleSubmit}>
                            <div className="modal-header">
                                <h2 className="modal-title">
                                    {editId
                                        ? (t('recurring.edit_template'))
                                        : (t('recurring.new_template_title'))}
                                </h2>
                                <button type="button" className="btn-icon" style={{ background: 'transparent' }} onClick={() => setShowModal(false)}>
                                    ✕
                                </button>
                            </div>
                            <div className="modal-body">
                                <div className="row g-3 mb-3">
                                    <div className="col-md-4">
                                        <label className="form-label">{t('recurring.template_name') + ' *'}</label>
                                        <input className="form-input" required value={form.name}
                                            onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
                                    </div>
                                    <div className="col-md-4">
                                        <label className="form-label">{t('recurring.reference')}</label>
                                        <input className="form-input" value={form.reference}
                                            onChange={e => setForm(f => ({ ...f, reference: e.target.value }))} />
                                    </div>
                                    <div className="col-md-4">
                                        <label className="form-label">{t('recurring.frequency_label') + ' *'}</label>
                                        <select className="form-input" required value={form.frequency}
                                            onChange={e => setForm(f => ({ ...f, frequency: e.target.value }))}>
                                            {['daily','weekly','monthly','quarterly','yearly'].map(k => (
                                                <option key={k} value={k}>{t(`recurring.freq_${k}`)}</option>
                                            ))}
                                        </select>
                                    </div>
                                </div>
                                <div className="row g-3 mb-3">
                                    <div className="col-md-3">
                                        <label className="form-label">{t('recurring.start_date') + ' *'}</label>
                                        <DateInput className="form-input" required value={form.start_date}
                                            onChange={e => setForm(f => ({
                                                ...f, start_date: e.target.value,
                                                next_run_date: f.next_run_date || e.target.value
                                            }))} />
                                    </div>
                                    <div className="col-md-3">
                                        <label className="form-label">{t('recurring.end_date')}</label>
                                        <DateInput className="form-input" value={form.end_date}
                                            onChange={e => setForm(f => ({ ...f, end_date: e.target.value }))} />
                                    </div>
                                    <div className="col-md-3">
                                        <label className="form-label">{t('recurring.next_run_date')}</label>
                                        <DateInput className="form-input" value={form.next_run_date}
                                            onChange={e => setForm(f => ({ ...f, next_run_date: e.target.value }))} />
                                    </div>
                                    <div className="col-md-3">
                                        <label className="form-label">{t('recurring.max_runs')}</label>
                                        <input type="number" className="form-input" min="1" value={form.max_runs}
                                            placeholder={t('recurring.unlimited')}
                                            onChange={e => setForm(f => ({ ...f, max_runs: e.target.value }))} />
                                    </div>
                                </div>
                                <div className="row g-3 mb-3">
                                    <div className="col-md-8">
                                        <label className="form-label">{t('recurring.description')}</label>
                                        <input className="form-input" value={form.description}
                                            onChange={e => setForm(f => ({ ...f, description: e.target.value }))} />
                                    </div>
                                    <div className="col-md-2">
                                        <label className="form-label d-block">&nbsp;</label>
                                        <div className="form-check">
                                            <input type="checkbox" className="form-check-input" id="is_active"
                                                checked={form.is_active}
                                                onChange={e => setForm(f => ({ ...f, is_active: e.target.checked }))} />
                                            <label className="form-check-label" htmlFor="is_active">
                                                {t('recurring.filter_active')}
                                            </label>
                                        </div>
                                    </div>
                                    <div className="col-md-2">
                                        <label className="form-label d-block">&nbsp;</label>
                                        <div className="form-check">
                                            <input type="checkbox" className="form-check-input" id="auto_post"
                                                checked={form.auto_post}
                                                onChange={e => setForm(f => ({ ...f, auto_post: e.target.checked }))} />
                                            <label className="form-check-label" htmlFor="auto_post">
                                                {t('recurring.auto_post')}
                                            </label>
                                        </div>
                                    </div>
                                </div>

                                {/* Lines */}
                                <h6 className="mt-3 mb-2">{t('recurring.journal_lines')}</h6>
                                <div className="data-table-container">
                                    <table className="data-table table-bordered">
                                        <thead className="table-light">
                                            <tr>
                                                <th style={{ width: '35%' }}>{t('recurring.account')}</th>
                                                <th style={{ width: '15%' }}>{t('recurring.debit')}</th>
                                                <th style={{ width: '15%' }}>{t('recurring.credit')}</th>
                                                <th style={{ width: '25%' }}>{t('recurring.line_desc')}</th>
                                                <th style={{ width: '10%' }}></th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {form.lines.map((line, idx) => (
                                                <tr key={idx}>
                                                    <td>
                                                        <select className="form-input" required
                                                            value={line.account_id}
                                                            onChange={e => updateLine(idx, 'account_id', e.target.value)}>
                                                            <option value="">{t('recurring.select_account')}</option>
                                                            {accounts.map(a => (
                                                                <option key={a.id} value={a.id}>{a.account_number} - {a.name}</option>
                                                            ))}
                                                        </select>
                                                    </td>
                                                    <td>
                                                        <input type="number" className="form-input form-input-sm"
                                                            step="0.01" min="0" value={line.debit}
                                                            onChange={e => updateLine(idx, 'debit', e.target.value)} />
                                                    </td>
                                                    <td>
                                                        <input type="number" className="form-input form-input-sm"
                                                            step="0.01" min="0" value={line.credit}
                                                            onChange={e => updateLine(idx, 'credit', e.target.value)} />
                                                    </td>
                                                    <td>
                                                        <input className="form-input form-input-sm" value={line.description}
                                                            onChange={e => updateLine(idx, 'description', e.target.value)} />
                                                    </td>
                                                    <td className="text-center">
                                                        <button type="button" className="btn btn-sm btn-outline-danger"
                                                            disabled={form.lines.length <= 2}
                                                            onClick={() => removeLine(idx)}>✕</button>
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                        <tfoot>
                                            <tr className="fw-bold">
                                                <td className="text-end">{t('recurring.total')}</td>
                                                <td className={!isBalanced ? 'text-danger' : ''}>{totalDebit.toFixed(2)}</td>
                                                <td className={!isBalanced ? 'text-danger' : ''}>{totalCredit.toFixed(2)}</td>
                                                <td colSpan="2">
                                                    <button type="button" className="btn btn-sm btn-outline-primary" onClick={addLine}>
                                                        + {t('recurring.add_line')}
                                                    </button>
                                                </td>
                                            </tr>
                                        </tfoot>
                                    </table>
                                </div>
                                {!isBalanced && (
                                    <div className="alert alert-warning py-1 small">
                                        ⚠️ {t('recurring.not_balanced')} —
                                        {` ${t('recurring.difference')}: `}{Math.abs(totalDebit - totalCredit).toFixed(2)}
                                    </div>
                                )}
                            </div>
                            <div className="modal-footer">
                                <button type="button" className="btn" style={{ background: 'var(--bg-hover)' }} onClick={() => setShowModal(false)}>
                                    {t('recurring.cancel')}
                                </button>
                                <button type="submit" className="btn btn-primary" disabled={!isBalanced || totalDebit === 0}>
                                    {editId ? (t('recurring.update')) : (t('recurring.create'))}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* Detail Modal */}
            {showDetailModal && detailData && (
                <div className="modal-overlay">
                    <div className="modal-content" style={{ maxWidth: '700px' }}>
                        <div className="modal-header">
                            <h2 className="modal-title">🔄 {detailData.name}</h2>
                            <button type="button" className="btn-icon" style={{ background: 'transparent' }} onClick={() => setShowDetailModal(false)}>
                                ✕
                            </button>
                        </div>
                            <div className="modal-body">
                                <div className="row mb-3">
                                    <div className="col-md-4">
                                        <strong>{t('recurring.detail_frequency')}</strong>{' '}
                                        <span className="badge bg-info">{freqLabel(detailData.frequency)}</span>
                                    </div>
                                    <div className="col-md-4">
                                        <strong>{t('recurring.detail_status')}</strong>{' '}
                                        <span className={`badge ${detailData.is_active ? 'bg-success' : 'bg-secondary'}`}>
                                            {detailData.is_active ? (t('recurring.filter_active')) : (t('recurring.filter_inactive'))}
                                        </span>
                                    </div>
                                    <div className="col-md-4">
                                        <strong>{t('recurring.detail_auto_post')}</strong>{' '}
                                        {detailData.auto_post ? '✅' : '❌'}
                                    </div>
                                </div>
                                <div className="row mb-3">
                                    <div className="col-md-3"><strong>{t('recurring.detail_start')}</strong> {formatDate(detailData.start_date)}</div>
                                    <div className="col-md-3"><strong>{t('recurring.detail_end')}</strong> {formatDate(detailData.end_date)}</div>
                                    <div className="col-md-3"><strong>{t('recurring.detail_next')}</strong> {detailData.next_run_date}</div>
                                    <div className="col-md-3"><strong>{t('recurring.detail_last')}</strong> {detailData.last_run_date || '-'}</div>
                                </div>
                                <div className="row mb-3">
                                    <div className="col-md-4">
                                        <strong>{t('recurring.detail_runs')}</strong>{' '}
                                        {detailData.run_count || 0}{detailData.max_runs ? `/${detailData.max_runs}` : ''}
                                    </div>
                                    {detailData.reference && (
                                        <div className="col-md-4"><strong>{t('recurring.detail_ref')}</strong> {detailData.reference}</div>
                                    )}
                                    {detailData.description && (
                                        <div className="col-md-4"><strong>{t('recurring.detail_desc')}</strong> {detailData.description}</div>
                                    )}
                                </div>

                                <h6>{t('recurring.lines')}</h6>
                                <table className="data-table table-bordered">
                                    <thead className="table-light">
                                        <tr>
                                            <th>{t('recurring.account')}</th>
                                            <th>{t('recurring.debit')}</th>
                                            <th>{t('recurring.credit')}</th>
                                            <th>{t('recurring.line_desc')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {detailData.lines.map((l, i) => (
                                            <tr key={i}>
                                                <td>{l.account_code || l.account_number} - {l.account_name}</td>
                                                <td>{parseFloat(l.debit || 0).toFixed(2)}</td>
                                                <td>{parseFloat(l.credit || 0).toFixed(2)}</td>
                                                <td>{l.description || '-'}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                    <tfoot>
                                        <tr className="fw-bold">
                                            <td>{t('recurring.total')}</td>
                                            <td>{detailData.lines.reduce((s, l) => s + parseFloat(l.debit || 0), 0).toFixed(2)}</td>
                                            <td>{detailData.lines.reduce((s, l) => s + parseFloat(l.credit || 0), 0).toFixed(2)}</td>
                                            <td></td>
                                        </tr>
                                    </tfoot>
                                </table>
                            </div>
                            <div className="modal-footer">
                                <button className="btn btn-outline-success btn-sm" onClick={() => { setShowDetailModal(false); handleGenerate(detailData.id) }}>
                                    ⚡ {t('recurring.generate_now')}
                                </button>
                                <button className="btn btn-outline-primary btn-sm" onClick={() => { setShowDetailModal(false); openEdit(detailData.id) }}>
                                    ✏️ {t('recurring.edit')}
                                </button>
                                <button className="btn btn-sm" style={{ background: 'var(--bg-hover)' }} onClick={() => setShowDetailModal(false)}>
                                    {t('recurring.close')}
                                </button>
                            </div>
                    </div>
                </div>
            )}
        </div>
    )
}
