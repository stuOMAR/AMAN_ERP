import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { accountingAPI } from '../../utils/api'
import { useBranch } from '../../context/BranchContext'
import { getCurrency, hasPermission } from '../../utils/auth'
import { formatNumber } from '../../utils/format'
import BackButton from '../../components/common/BackButton'
import '../../components/ModuleStyles.css'
import DateInput from '../../components/common/DateInput';
import { useToast } from '../../context/ToastContext'
import { PageLoading } from '../../components/common/LoadingStates'

function RevenueRecognition() {
    const { t } = useTranslation()
  const { showToast } = useToast()
    const { currentBranch } = useBranch()
    const currency = getCurrency()
    const [schedules, setSchedules] = useState([])
    const [summary, setSummary] = useState(null)
    const [selectedSchedule, setSelectedSchedule] = useState(null)
    const [loading, setLoading] = useState(true)
    const [initialLoad, setInitialLoad] = useState(true)
    const [tab, setTab] = useState('list')
    const [showForm, setShowForm] = useState(false)
    const [form, setForm] = useState({
        invoice_id: '', contract_id: '', total_amount: '',
        start_date: '', end_date: '', method: 'straight_line'
    })
    const canEditAccounting = hasPermission('accounting.edit')
    const permissionDenied = () => showToast(t('common.permission_denied', 'ليس لديك صلاحية تنفيذ هذا الإجراء'), 'error')

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchData()
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch])

    const fetchData = async () => {
        try {
            setLoading(true)
            const params = {};
            if (currentBranch?.id) params.branch_id = currentBranch.id;
            const [schedRes, sumRes] = await Promise.all([
                accountingAPI.listRevenueSchedules(params),
                accountingAPI.getRevenueSummary(params)
            ])
            setSchedules(schedRes.data)
            setSummary(sumRes.data)
        } catch (err) {
            console.error('Failed to fetch revenue data', err)
        } finally {
            setLoading(false)
            setInitialLoad(false)
        }
    }

    const handleSubmit = async (e) => {
        e.preventDefault()
        if (!canEditAccounting) {
            permissionDenied()
            return
        }
        try {
            await accountingAPI.createRevenueSchedule({
                invoice_id: form.invoice_id ? parseInt(form.invoice_id) : null,
                contract_id: form.contract_id ? parseInt(form.contract_id) : null,
                total_amount: parseFloat(form.total_amount),
                start_date: form.start_date,
                end_date: form.end_date,
                method: form.method
            })
            setShowForm(false)
            setForm({ invoice_id: '', contract_id: '', total_amount: '', start_date: '', end_date: '', method: 'straight_line' })
            fetchData()
        } catch (err) {
            showToast(err.response?.data?.detail || 'Error', 'error')
        }
    }

    const handleViewSchedule = async (id) => {
        try {
            const res = await accountingAPI.getRevenueSchedule(id)
            setSelectedSchedule(res.data)
            setTab('detail')
        } catch (err) {
            showToast(err.response?.data?.detail || 'Error', 'error')
        }
    }

    const handleRecognize = async (scheduleId, periodIndex) => {
        if (!canEditAccounting) {
            permissionDenied()
            return
        }
        if (!confirm(t('accounting.confirm_recognize'))) return
        try {
            const res = await accountingAPI.recognizeRevenue(scheduleId, periodIndex)
            showToast(res.data.message, 'success')
            handleViewSchedule(scheduleId)
            fetchData()
        } catch (err) {
            showToast(err.response?.data?.detail || 'Error', 'error')
        }
    }

    const getStatusBadge = (status) => {
        const map = { active: 'badge-info', completed: 'badge-success', draft: 'badge-secondary' }
        return map[status] || 'badge-secondary'
    }

    const getMethodLabel = (method) => {
        const map = {
            straight_line: t('accounting.straight_line'),
            percentage_completion: t('accounting.percentage_completion'),
            milestone: t('accounting.milestone')
        }
        return map[method] || method
    }

    if (initialLoad) return <PageLoading />

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div>
                    <h1 className="workspace-title">{t('accounting.revenue_recognition')}</h1>
                    <p className="workspace-subtitle">{t('accounting.revenue_desc')}</p>
                </div>
            </div>

            {/* Summary Cards */}
            {summary && (
                <div className="metrics-grid">
                    <div className="metric-card">
                        <div className="metric-label">{t('accounting.total_contract_value')}</div>
                        <div className="metric-value text-primary">{formatNumber(summary.total_contract_value || 0)} <small>{currency}</small></div>
                    </div>
                    <div className="metric-card">
                        <div className="metric-label">{t('accounting.recognized_revenue')}</div>
                        <div className="metric-value text-success">{formatNumber(summary.total_recognized || 0)} <small>{currency}</small></div>
                    </div>
                    <div className="metric-card">
                        <div className="metric-label">{t('accounting.deferred_revenue')}</div>
                        <div className="metric-value text-warning">{formatNumber(summary.total_deferred || 0)} <small>{currency}</small></div>
                    </div>
                    <div className="metric-card">
                        <div className="metric-label">{t('accounting.recognition_pct')}</div>
                        <div className="metric-value" style={{ color: '#8b5cf6' }}>{summary.recognition_pct || 0}%</div>
                    </div>
                    <div className="metric-card">
                        <div className="metric-label">{t('accounting.active_schedules')}</div>
                        <div className="metric-value text-primary">{summary.active_schedules || 0}</div>
                    </div>
                    <div className="metric-card">
                        <div className="metric-label">{t('accounting.completed_schedules')}</div>
                        <div className="metric-value text-success">{summary.completed_schedules || 0}</div>
                    </div>
                </div>
            )}

            {/* Tabs + Actions */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, marginTop: 16 }}>
                <div className="tabs">
                    <button className={`tab ${tab === 'list' ? 'active' : ''}`}
                        onClick={() => { setTab('list'); setSelectedSchedule(null) }}>
                        {t('accounting.schedules')}
                    </button>
                    {selectedSchedule && (
                        <button className={`tab ${tab === 'detail' ? 'active' : ''}`} onClick={() => setTab('detail')}>
                            {t('common.details')}
                        </button>
                    )}
                </div>
                {canEditAccounting && (
                    <button className="btn btn-primary btn-sm" onClick={() => setShowForm(!showForm)}>
                        {showForm ? t('common.cancel') : t('accounting.add_schedule')}
                    </button>
                )}
            </div>

            {/* Create Form */}
            {showForm && canEditAccounting && (
                <div className="section-card" style={{ marginBottom: 16 }}>
                    <h3 className="section-title">{t('accounting.new_schedule')}</h3>
                    <form onSubmit={handleSubmit}>
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
                            <div className="form-group">
                                <label className="form-label">{t('accounting.invoice_id', 'رقم الفاتورة')}</label>
                                <input className="form-input" type="number" value={form.invoice_id}
                                    onChange={e => setForm({ ...form, invoice_id: e.target.value })}
                                    placeholder={t('common.optional', 'اختياري')} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('accounting.contract_id', 'رقم العقد')}</label>
                                <input className="form-input" type="number" value={form.contract_id}
                                    onChange={e => setForm({ ...form, contract_id: e.target.value })}
                                    placeholder={t('common.optional', 'اختياري')} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('common.amount', 'المبلغ الإجمالي')} *</label>
                                <input className="form-input" type="number" step="0.01" required value={form.total_amount}
                                    onChange={e => setForm({ ...form, total_amount: e.target.value })} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('accounting.method', 'طريقة الاعتراف')}</label>
                                <select className="form-input" value={form.method}
                                    onChange={e => setForm({ ...form, method: e.target.value })}>
                                    <option value="straight_line">{t('accounting.straight_line', 'خطي (شهري)')}</option>
                                    <option value="percentage_completion">{t('accounting.percentage_completion', 'نسبة الإنجاز')}</option>
                                    <option value="milestone">{t('accounting.milestone', 'عند الإنجاز الكامل')}</option>
                                </select>
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('common.start_date', 'تاريخ البدء')} *</label>
                                <DateInput className="form-input" required value={form.start_date}
                                    onChange={e => setForm({ ...form, start_date: e.target.value })} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('common.end_date', 'تاريخ الانتهاء')} *</label>
                                <DateInput className="form-input" required value={form.end_date}
                                    onChange={e => setForm({ ...form, end_date: e.target.value })} />
                            </div>
                        </div>
                        <div style={{ marginTop: 12 }}>
                            <button type="submit" className="btn btn-primary btn-sm">{t('common.save', 'حفظ')}</button>
                        </div>
                    </form>
                </div>
            )}

            {/* Detail View */}
            {tab === 'detail' && selectedSchedule && (
                <div className="section-card">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                        <div>
                            <h3 className="section-title" style={{ marginBottom: 4 }}>
                                {t('accounting.schedule', 'جدول')} #{selectedSchedule.id}
                            </h3>
                            <div style={{ display: 'flex', gap: 16, fontSize: '0.85rem', color: '#6b7280' }}>
                                <span>{t('accounting.method', 'الطريقة')}: <strong>{getMethodLabel(selectedSchedule.method)}</strong></span>
                                <span>{t('common.amount', 'المبلغ')}: <strong>{formatNumber(selectedSchedule.total_amount)} {currency}</strong></span>
                                <span>{t('accounting.recognized_amount', 'معترف به')}: <strong style={{ color: '#22c55e' }}>{formatNumber(selectedSchedule.recognized_amount || 0)} {currency}</strong></span>
                            </div>
                        </div>
                        <span className={`badge ${getStatusBadge(selectedSchedule.status)}`}>
                            {selectedSchedule.status}
                        </span>
                    </div>

                    {/* Progress Bar */}
                    <div style={{ marginBottom: 16 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', marginBottom: 4 }}>
                            <span>{t('accounting.progress', 'التقدم')}</span>
                            <span>{selectedSchedule.total_amount > 0 ? Math.round((selectedSchedule.recognized_amount || 0) / selectedSchedule.total_amount * 100) : 0}%</span>
                        </div>
                        <div style={{ background: '#f3f4f6', borderRadius: 8, height: 12, overflow: 'hidden' }}>
                            <div style={{
                                width: `${selectedSchedule.total_amount > 0 ? Math.min(100, (selectedSchedule.recognized_amount || 0) / selectedSchedule.total_amount * 100) : 0}%`,
                                height: '100%', borderRadius: 8,
                                background: 'linear-gradient(90deg, #22c55e, #16a34a)',
                                transition: 'width 0.5s'
                            }} />
                        </div>
                    </div>

                    {/* Schedule Lines */}
                    {selectedSchedule.schedule_lines && (
                        <div className="data-table-container">
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>#</th>
                                        <th>{t('common.period', 'الفترة')}</th>
                                        <th>{t('common.amount', 'المبلغ')}</th>
                                        <th>{t('common.status_title', 'الحالة')}</th>
                                        <th>{t('common.actions', 'إجراءات')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {(Array.isArray(selectedSchedule.schedule_lines)
                                        ? selectedSchedule.schedule_lines
                                        : JSON.parse(selectedSchedule.schedule_lines || '[]')
                                    ).map((line, i) => (
                                        <tr key={i}>
                                            <td>{i + 1}</td>
                                            <td style={{ fontWeight: 600 }}>
                                                {line.period || line.milestone || `${t('common.period', 'فترة')} ${i + 1}`}
                                            </td>
                                            <td>{formatNumber(line.amount)} {currency}</td>
                                            <td>
                                                {line.recognized ? (
                                                    <span className="badge badge-success">{t('accounting.recognized', 'معترف به')}</span>
                                                ) : (
                                                    <span className="badge badge-secondary">{t('accounting.pending', 'معلق')}</span>
                                                )}
                                            </td>
                                            <td>
                                                {!line.recognized && selectedSchedule.status === 'active' && canEditAccounting && (
                                                    <button className="btn btn-success btn-sm"
                                                        onClick={() => handleRecognize(selectedSchedule.id, i)}>
                                                        {t('accounting.recognize', 'اعتراف')}
                                                    </button>
                                                )}
                                                {line.recognized && line.recognized_at && (
                                                    <span style={{ color: '#9ca3af', fontSize: '0.8rem' }}>
                                                        {new Date(line.recognized_at).toLocaleDateString('ar-SA')}
                                                    </span>
                                                )}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            )}

            {/* Schedules List */}
            {tab === 'list' && (
                <div className="section-card">
                    <h3 className="section-title">{t('accounting.schedules', 'جداول الاعتراف')} ({schedules.length})</h3>
                    {schedules.length === 0 ? (
                        <p style={{ color: '#9ca3af', textAlign: 'center', padding: 24 }}>
                            {t('common.no_data', 'لا توجد جداول بعد')}
                        </p>
                    ) : (
                        <div className="data-table-container">
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>#</th>
                                        <th>{t('accounting.method', 'الطريقة')}</th>
                                        <th>{t('common.amount', 'المبلغ')}</th>
                                        <th>{t('accounting.recognized_amount', 'معترف به')}</th>
                                        <th>{t('common.status_title', 'الحالة')}</th>
                                        <th>{t('accounting.progress', 'التقدم')}</th>
                                        <th>{t('common.period', 'الفترة')}</th>
                                        <th>{t('common.actions', 'إجراءات')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {schedules.map(s => {
                                        const pct = s.total_amount > 0 ? Math.round((s.recognized_amount || 0) / s.total_amount * 100) : 0
                                        return (
                                            <tr key={s.id}>
                                                <td>{s.id}</td>
                                                <td><span className="badge badge-info">{getMethodLabel(s.method)}</span></td>
                                                <td>{formatNumber(s.total_amount)} {currency}</td>
                                                <td style={{ color: '#22c55e', fontWeight: 600 }}>
                                                    {formatNumber(s.recognized_amount || 0)} {currency}
                                                </td>
                                                <td><span className={`badge ${getStatusBadge(s.status)}`}>{s.status}</span></td>
                                                <td>
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                                        <div style={{ background: '#f3f4f6', borderRadius: 4, height: 8, flex: 1, maxWidth: 100, overflow: 'hidden' }}>
                                                            <div style={{ width: `${pct}%`, height: '100%', background: '#22c55e', borderRadius: 4 }} />
                                                        </div>
                                                        <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>{pct}%</span>
                                                    </div>
                                                </td>
                                                <td style={{ fontSize: '0.85rem', color: '#6b7280' }}>
                                                    {s.start_date} → {s.end_date}
                                                </td>
                                                <td>
                                                    <button className="btn btn-info btn-sm" onClick={() => handleViewSchedule(s.id)}>
                                                        {t('common.view', 'عرض')}
                                                    </button>
                                                </td>
                                            </tr>
                                        )
                                    })}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}

export default RevenueRecognition
