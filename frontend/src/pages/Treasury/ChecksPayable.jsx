import { useState, useEffect, useCallback } from 'react'
import { checksAPI, inventoryAPI, treasuryAPI } from '../../utils/api'
import { useTranslation } from 'react-i18next'
import { formatShortDate } from '../../utils/dateUtils'
import { useBranch } from '../../context/BranchContext'
import { formatNumber } from '../../utils/format'
import { getCurrency } from '../../utils/auth'
import { FileText, CheckCircle, XCircle, AlertTriangle } from 'lucide-react'
import '../../components/ModuleStyles.css'

import DateInput from '../../components/common/DateInput';
import BackButton from '../../components/common/BackButton';
import { useToast } from '../../context/ToastContext'
import { PageLoading } from '../../components/common/LoadingStates'
function ChecksPayable() {
    const { t } = useTranslation()
  const { showToast } = useToast()
    const { currentBranch } = useBranch()
    const currency = getCurrency()

    const [items, setItems] = useState([])
    const [loading, setLoading] = useState(true)
    const [total, setTotal] = useState(0)
    const [page, setPage] = useState(1)
    const [search, setSearch] = useState('')
    const [statusFilter, setStatusFilter] = useState('')
    const [stats, setStats] = useState(null)

    // Create modal
    const [showCreate, setShowCreate] = useState(false)
    const [suppliers, setSuppliers] = useState([])
    const [treasuryAccounts, setTreasuryAccounts] = useState([])
    const [form, setForm] = useState({
        check_number: '', beneficiary_name: '', bank_name: '', branch_name: '',
        amount: '', currency: getCurrency(), issue_date: new Date().toISOString().split('T')[0],
        due_date: '', party_id: '', treasury_account_id: '', notes: ''
    })
    const [saving, setSaving] = useState(false)

    // Detail modal
    const [detailItem, setDetailItem] = useState(null)
    const [showDetail, setShowDetail] = useState(false)

    // Action modals
    const [showClear, setShowClear] = useState(false)
    const [showBounce, setShowBounce] = useState(false)
    const [showRepresent, setShowRepresent] = useState(false)
    const [actionForm, setActionForm] = useState({})

    const fetchList = useCallback(async () => {
        try {
            setLoading(true)
            const params = { page, limit: 50, branch_id: currentBranch?.id }
            if (search) params.search = search
            if (statusFilter) params.status = statusFilter
            const res = await checksAPI.listPayable(params)
            setItems(res.data.items || [])
            setTotal(res.data.total || 0)
        } catch (err) { console.error(err) }
        finally { setLoading(false) }
    }, [page, search, statusFilter, currentBranch])

    const fetchStats = useCallback(async () => {
        try {
            const res = await checksAPI.payableStats({ branch_id: currentBranch?.id })
            setStats(res.data)
        } catch (err) { console.error(err) }
    }, [currentBranch])

    useEffect(() => { fetchList(); fetchStats() }, [fetchList, fetchStats])

    const loadCreateData = async () => {
        try {
            const [suppRes, treasRes] = await Promise.all([
                inventoryAPI.listSuppliers({ limit: 500 }),
                treasuryAPI.listAccounts(currentBranch?.id)
            ])
            setSuppliers(suppRes.data?.data || suppRes.data || [])
            setTreasuryAccounts(treasRes.data?.items || treasRes.data || [])
        } catch (err) { console.error(err) }
    }

    const openCreate = () => {
        setForm({
            check_number: '', beneficiary_name: '', bank_name: '', branch_name: '',
            amount: '', currency: getCurrency(), issue_date: new Date().toISOString().split('T')[0],
            due_date: '', party_id: '', treasury_account_id: '', notes: ''
        })
        loadCreateData()
        setShowCreate(true)
    }

    const handleCreate = async () => {
        if (!form.check_number || !form.amount || !form.due_date || !form.issue_date) return showToast(t('checks.payable.requiredFields', 'warning'))
        try {
            setSaving(true)
            await checksAPI.createPayable({
                ...form,
                amount: parseFloat(form.amount),
                party_id: form.party_id ? parseInt(form.party_id) : null,
                treasury_account_id: form.treasury_account_id ? parseInt(form.treasury_account_id) : null,
                branch_id: currentBranch?.id,
            })
            setShowCreate(false)
            fetchList(); fetchStats()
        } catch (err) {
            showToast(err.response?.data?.detail || t('checks.payable.error', 'error'))
        } finally { setSaving(false) }
    }

    const viewDetail = async (id) => {
        try {
            const res = await checksAPI.getPayable(id)
            setDetailItem(res.data)
            setShowDetail(true)
        } catch (err) { console.error(err) }
    }

    const handleClear = async () => {
        try {
            setSaving(true)
            await checksAPI.clearPayable(detailItem.id, {
                clearance_date: actionForm.clearance_date || new Date().toISOString().split('T')[0],
                treasury_account_id: actionForm.treasury_account_id ? parseInt(actionForm.treasury_account_id) : null,
            })
            setShowClear(false); setShowDetail(false)
            fetchList(); fetchStats()
        } catch (err) {
            showToast(err.response?.data?.detail || t('checks.payable.error', 'error'))
        } finally { setSaving(false) }
    }

    const handleBounce = async () => {
        try {
            setSaving(true)
            await checksAPI.bouncePayable(detailItem.id, {
                bounce_date: actionForm.bounce_date || new Date().toISOString().split('T')[0],
                bounce_reason: actionForm.bounce_reason || '',
            })
            setShowBounce(false); setShowDetail(false)
            fetchList(); fetchStats()
        } catch (err) {
            showToast(err.response?.data?.detail || t('checks.payable.error', 'error'))
        } finally { setSaving(false) }
    }

    const openClear = () => {
        loadCreateData()
        setActionForm({ clearance_date: new Date().toISOString().split('T')[0], treasury_account_id: detailItem.treasury_account_id || '' })
        setShowClear(true)
    }

    const openBounce = () => {
        setActionForm({ bounce_date: new Date().toISOString().split('T')[0], bounce_reason: '' })
        setShowBounce(true)
    }

    const openRepresent = () => {
        setActionForm({ represent_date: new Date().toISOString().split('T')[0] })
        setShowRepresent(true)
    }

    const handleRepresent = async () => {
        try {
            setSaving(true)
            await checksAPI.representPayable(detailItem.id, {
                represent_date: actionForm.represent_date || new Date().toISOString().split('T')[0],
            })
            setShowRepresent(false); setShowDetail(false)
            fetchList(); fetchStats()
        } catch (err) {
            showToast(err.response?.data?.detail || t('checks.payable.error', 'error'))
        } finally { setSaving(false) }
    }

    const statusBadge = (s) => {
        const map = { issued: 'badge-warning', cleared: 'badge-success', bounced: 'badge-danger' }
        const labels = { issued: t('checks.payable.issued'), cleared: t('checks.payable.cleared'), bounced: t('checks.payable.bounced') }
        return <span className={`badge ${map[s] || 'badge-secondary'}`}>{labels[s] || s}</span>
    }

    const isOverdue = (dueDate, status) => {
        if (status !== 'issued') return false
        return new Date(dueDate) <= new Date()
    }

    if (loading && !items.length) return <PageLoading />

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
                    <div>
                        <h1 className="workspace-title">📤 {t('checks.payable.title')}</h1>
                        <p className="workspace-subtitle">{t('checks.payable.subtitle')}</p>
                    </div>
                    <button className="btn btn-primary" onClick={openCreate}>+ {t('checks.payable.create')}</button>
                </div>
            </div>

            {/* Stats Cards */}
            {stats && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', marginBottom: '24px' }}>
                    <div className="card p-3 text-center">
                        <FileText size={24} className="text-warning mb-2" />
                        <div className="small text-muted">{t('checks.payable.issued')}</div>
                        <div className="fw-bold fs-4">{stats.issued.count}</div>
                        <div className="small text-muted">{formatNumber(stats.issued.amount)} {currency}</div>
                    </div>
                    <div className="card p-3 text-center">
                        <CheckCircle size={24} className="text-success mb-2" />
                        <div className="small text-muted">{t('checks.payable.cleared')}</div>
                        <div className="fw-bold fs-4 text-success">{stats.cleared.count}</div>
                        <div className="small text-muted">{formatNumber(stats.cleared.amount)} {currency}</div>
                    </div>
                    <div className="card p-3 text-center">
                        <XCircle size={24} className="text-danger mb-2" />
                        <div className="small text-muted">{t('checks.payable.bounced')}</div>
                        <div className="fw-bold fs-4 text-danger">{stats.bounced.count}</div>
                        <div className="small text-muted">{formatNumber(stats.bounced.amount)} {currency}</div>
                    </div>
                    <div className="card p-3 text-center">
                        <AlertTriangle size={24} className="text-danger mb-2" />
                        <div className="small text-muted">{t('checks.payable.overdueToday')}</div>
                        <div className="fw-bold fs-4 text-danger">{stats.overdue.count}</div>
                        <div className="small text-muted">{formatNumber(stats.overdue.amount)} {currency}</div>
                    </div>
                </div>
            )}

            {/* Filters */}
            <div className="card" style={{ padding: 16, display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
                <input className="form-input" placeholder={t('checks.payable.searchPlaceholder')} value={search}
                    onChange={e => setSearch(e.target.value)} style={{ maxWidth: 280 }} />
                <select className="form-input" value={statusFilter} onChange={e => setStatusFilter(e.target.value)} style={{ maxWidth: 160 }}>
                    <option value="">{t('checks.payable.allStatuses')}</option>
                    <option value="issued">{t('checks.payable.issued')}</option>
                    <option value="cleared">{t('checks.payable.cleared')}</option>
                    <option value="bounced">{t('checks.payable.bounced')}</option>
                </select>
                <div style={{ marginRight: 'auto', fontWeight: 600, alignSelf: 'center' }}>{t('checks.payable.total')}: {total}</div>
            </div>

            {/* Table */}
            <div className="card card-flush" style={{ overflow: 'auto' }}>
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('checks.payable.checkNumber')}</th>
                            <th>{t('checks.payable.beneficiary')}</th>
                            <th>{t('checks.payable.bank')}</th>
                            <th>{t('checks.payable.amount')}</th>
                            <th>{t('checks.payable.dueDate')}</th>
                            <th>{t('checks.payable.status')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {items.length === 0 ? (
                            <tr><td colSpan="6" style={{ textAlign: 'center', padding: 40 }}>{t('checks.payable.noChecks')}</td></tr>
                        ) : items.map(item => (
                            <tr key={item.id} onClick={() => viewDetail(item.id)}
                                style={{ cursor: 'pointer', background: isOverdue(item.due_date, item.status) ? 'rgba(220,53,69,0.05)' : undefined }}>
                                <td style={{ fontWeight: 'bold' }}>{item.check_number}</td>
                                <td>{item.beneficiary_name || item.party_name || '—'}</td>
                                <td>{item.bank_name || '—'}</td>
                                <td style={{ fontWeight: 'bold' }}>{formatNumber(item.amount)} {currency}</td>
                                <td style={{ color: isOverdue(item.due_date, item.status) ? '#dc3545' : undefined, fontWeight: isOverdue(item.due_date, item.status) ? 'bold' : undefined }}>
                                    {formatShortDate(item.due_date)}
                                    {isOverdue(item.due_date, item.status) && ' ⚠️'}
                                </td>
                                <td>{statusBadge(item.status)}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {/* Create Modal */}
            {showCreate && (
                <div className="modal-overlay" onClick={() => setShowCreate(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 780, maxHeight: '90vh', overflow: 'auto' }}>
                        <div className="modal-header">
                            <h2>{t('checks.payable.create')}</h2>
                            <button className="modal-close" onClick={() => setShowCreate(false)}>✕</button>
                        </div>
                        <div style={{ padding: 20 }}>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                                <div>
                                    <label className="form-label">{t('checks.payable.checkNumber')} *</label>
                                    <input className="form-input" value={form.check_number} onChange={e => setForm(f => ({ ...f, check_number: e.target.value }))} />
                                </div>
                                <div>
                                    <label className="form-label">{t('checks.payable.amount')} *</label>
                                    <input className="form-input" type="number" min="0" step="0.01" value={form.amount} onChange={e => setForm(f => ({ ...f, amount: e.target.value }))} />
                                </div>
                                <div>
                                    <label className="form-label">{t('checks.payable.beneficiary')}</label>
                                    <input className="form-input" value={form.beneficiary_name} onChange={e => setForm(f => ({ ...f, beneficiary_name: e.target.value }))} />
                                </div>
                                <div>
                                    <label className="form-label">{t('checks.payable.bank')}</label>
                                    <input className="form-input" value={form.bank_name} onChange={e => setForm(f => ({ ...f, bank_name: e.target.value }))} />
                                </div>
                                <div>
                                    <label className="form-label">{t('checks.payable.issueDate')} *</label>
                                    <DateInput className="form-input" value={form.issue_date} onChange={e => setForm(f => ({ ...f, issue_date: e.target.value }))} />
                                </div>
                                <div>
                                    <label className="form-label">{t('checks.payable.dueDate')} *</label>
                                    <DateInput className="form-input" value={form.due_date} onChange={e => setForm(f => ({ ...f, due_date: e.target.value }))} />
                                </div>
                                <div>
                                    <label className="form-label">{t('checks.payable.supplier')}</label>
                                    <select className="form-input" value={form.party_id} onChange={e => setForm(f => ({ ...f, party_id: e.target.value }))}>
                                        <option value="">{t('checks.payable.selectSupplier')}</option>
                                        {suppliers.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                                    </select>
                                </div>
                                <div>
                                    <label className="form-label">{t('checks.payable.treasuryAccount')}</label>
                                    <select className="form-input" value={form.treasury_account_id} onChange={e => setForm(f => ({ ...f, treasury_account_id: e.target.value }))}>
                                        <option value="">{t('checks.payable.selectTreasury')}</option>
                                        {treasuryAccounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                                    </select>
                                </div>
                                <div style={{ gridColumn: '1 / -1' }}>
                                    <label className="form-label">{t('checks.payable.notes')}</label>
                                    <input className="form-input" value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} />
                                </div>
                            </div>
                            <div style={{ marginTop: 24, display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
                                <button className="btn btn-secondary" onClick={() => setShowCreate(false)}>{t('notesReceivable.cancel')}</button>
                                <button className="btn btn-primary" onClick={handleCreate} disabled={saving}>
                                    {saving ? t('checks.payable.saving') : t('checks.payable.issueCheck')}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Detail Modal */}
            {showDetail && detailItem && (
                <div className="modal-overlay" onClick={() => setShowDetail(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 700, maxHeight: '90vh', overflow: 'auto' }}>
                        <div className="modal-header">
                            <h2>{t('checks.payable.checkNumberTitle')} {detailItem.check_number}</h2>
                            <button className="modal-close" onClick={() => setShowDetail(false)}>✕</button>
                        </div>
                        <div style={{ padding: 20 }}>
                            <div className="metrics-grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', marginBottom: 20 }}>
                                <div className="metric-card"><div className="metric-label">{t('checks.payable.amount')}</div><div className="metric-value text-primary" style={{ fontSize: 20 }}>{formatNumber(detailItem.amount)} {currency}</div></div>
                                <div className="metric-card"><div className="metric-label">{t('checks.payable.status')}</div><div className="metric-value" style={{ fontSize: 16 }}>{statusBadge(detailItem.status)}</div></div>
                                <div className="metric-card"><div className="metric-label">{t('checks.payable.dueDateShort')}</div><div className="metric-value" style={{ fontSize: 14 }}>{formatShortDate(detailItem.due_date)}</div></div>
                            </div>

                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 20 }}>
                                <div><strong>{t('checks.payable.beneficiary')}:</strong> {detailItem.beneficiary_name || '—'}</div>
                                <div><strong>{t('checks.payable.bank')}:</strong> {detailItem.bank_name || '—'}</div>
                                <div><strong>{t('checks.payable.supplier')}:</strong> {detailItem.party_name || '—'}</div>
                                <div><strong>{t('checks.payable.treasuryAccount')}:</strong> {detailItem.treasury_name || '—'}</div>
                                <div><strong>{t('checks.payable.issueDate')}:</strong> {formatShortDate(detailItem.issue_date)}</div>
                                {detailItem.clearance_date && <div><strong>{t('checks.payable.clearanceDate')}:</strong> {formatShortDate(detailItem.clearance_date)}</div>}
                                {detailItem.bounce_date && <div><strong>{t('checks.payable.bounceDate')}:</strong> {formatShortDate(detailItem.bounce_date)}</div>}
                                {detailItem.bounce_reason && <div style={{ gridColumn: '1 / -1' }}><strong>{t('checks.payable.bounceReason')}:</strong> {detailItem.bounce_reason}</div>}
                            </div>

                            {detailItem.notes && <p style={{ color: '#666', marginBottom: 16 }}>📝 {detailItem.notes}</p>}

                            {/* Actions */}
                            {detailItem.status === 'issued' && (
                                <div style={{ display: 'flex', gap: 12, marginTop: 20 }}>
                                    <button className="btn btn-primary" onClick={openClear}>✅ {t('checks.payable.clear')}</button>
                                    <button className="btn" style={{ background: '#dc3545', color: '#fff' }} onClick={openBounce}>❌ {t('checks.payable.bounce')}</button>
                                </div>
                            )}
                            {detailItem.status === 'bounced' && (
                                <div style={{ display: 'flex', gap: 12, marginTop: 20 }}>
                                    <button className="btn btn-warning" onClick={openRepresent}>🔄 {t('checks.payable.represent', 'إعادة تقديم')}</button>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            )}

            {/* Clear Modal */}
            {showClear && (
                <div className="modal-overlay" onClick={() => setShowClear(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 500 }}>
                        <div className="modal-header">
                            <h2>{t('checks.payable.clear')}</h2>
                            <button className="modal-close" onClick={() => setShowClear(false)}>✕</button>
                        </div>
                        <div style={{ padding: 20 }}>
                            <div style={{ marginBottom: 16 }}>
                                <label className="form-label">{t('checks.payable.clearanceDate')}</label>
                                <DateInput className="form-input" value={actionForm.clearance_date}
                                    onChange={e => setActionForm(f => ({ ...f, clearance_date: e.target.value }))} />
                            </div>
                            <div style={{ marginBottom: 16 }}>
                                <label className="form-label">{t('checks.payable.treasuryBank')}</label>
                                <select className="form-input" value={actionForm.treasury_account_id || ''}
                                    onChange={e => setActionForm(f => ({ ...f, treasury_account_id: e.target.value }))}>
                                    <option value="">{t('checks.payable.selectTreasury')}</option>
                                    {treasuryAccounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                                </select>
                            </div>
                            <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
                                <button className="btn btn-secondary" onClick={() => setShowClear(false)}>{t('notesReceivable.cancel')}</button>
                                <button className="btn btn-primary" onClick={handleClear} disabled={saving}>
                                    {saving ? t('checks.payable.processing') : t('checks.payable.confirmClear')}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Bounce Modal */}
            {showBounce && (
                <div className="modal-overlay" onClick={() => setShowBounce(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 500 }}>
                        <div className="modal-header">
                            <h2>{t('checks.payable.bounce')}</h2>
                            <button className="modal-close" onClick={() => setShowBounce(false)}>✕</button>
                        </div>
                        <div style={{ padding: 20 }}>
                            <div style={{ marginBottom: 16 }}>
                                <label className="form-label">{t('checks.payable.bounceDate')}</label>
                                <DateInput className="form-input" value={actionForm.bounce_date}
                                    onChange={e => setActionForm(f => ({ ...f, bounce_date: e.target.value }))} />
                            </div>
                            <div style={{ marginBottom: 16 }}>
                                <label className="form-label">{t('checks.payable.bounceReason')}</label>
                                <textarea className="form-input" rows="3" value={actionForm.bounce_reason || ''}
                                    onChange={e => setActionForm(f => ({ ...f, bounce_reason: e.target.value }))}
                                    placeholder={t('checks.payable.bouncePlaceholder')} />
                            </div>
                            <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
                                <button className="btn btn-secondary" onClick={() => setShowBounce(false)}>{t('notesReceivable.cancel')}</button>
                                <button className="btn" style={{ background: '#dc3545', color: '#fff' }} onClick={handleBounce} disabled={saving}>
                                    {saving ? t('checks.payable.processing') : t('checks.payable.confirmBounce')}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Represent Modal */}
            {showRepresent && (
                <div className="modal-overlay" onClick={() => setShowRepresent(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 500 }}>
                        <div className="modal-header">
                            <h2>{t('checks.payable.represent', 'إعادة تقديم')}</h2>
                            <button className="modal-close" onClick={() => setShowRepresent(false)}>✕</button>
                        </div>
                        <div style={{ padding: 20 }}>
                            <div style={{ marginBottom: 16 }}>
                                <label className="form-label">{t('checks.payable.representDate', 'تاريخ إعادة التقديم')}</label>
                                <DateInput className="form-input" value={actionForm.represent_date}
                                    onChange={e => setActionForm(f => ({ ...f, represent_date: e.target.value }))} />
                            </div>
                            <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
                                <button className="btn btn-secondary" onClick={() => setShowRepresent(false)}>{t('notesReceivable.cancel')}</button>
                                <button className="btn btn-warning" onClick={handleRepresent} disabled={saving}>
                                    {saving ? t('checks.payable.processing') : t('checks.payable.confirmRepresent', 'تأكيد إعادة التقديم')}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}

export default ChecksPayable
