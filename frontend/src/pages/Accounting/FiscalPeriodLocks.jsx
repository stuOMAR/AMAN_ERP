import { useState, useEffect } from 'react'
import { fiscalLocksAPI } from '../../utils/api'
import { useTranslation } from 'react-i18next'
import { formatShortDate } from '../../utils/dateUtils'
import { useToast } from '../../context/ToastContext'
import BackButton from '../../components/common/BackButton'
import DateInput from '../../components/common/DateInput';
import { PageLoading } from '../../components/common/LoadingStates'

function FiscalPeriodLocks() {
    const { t } = useTranslation()
    const { showToast } = useToast()
    const [periods, setPeriods] = useState([])
    const [loading, setLoading] = useState(true)
    const [showForm, setShowForm] = useState(false)
    const [form, setForm] = useState({ name: '', start_date: '', end_date: '' })

    const fetchPeriods = async () => {
        try { const r = await fiscalLocksAPI.listPeriods(); setPeriods(r.data) }
        catch (err) { console.error(err) }
        finally { setLoading(false) }
    }

    useEffect(() => { fetchPeriods() }, [])

    const handleCreate = async () => {
        try {
            await fiscalLocksAPI.createPeriod(form)
            showToast(t('fiscal_locks.created'), 'success')
            setShowForm(false)
            setForm({ name: '', start_date: '', end_date: '' })
            fetchPeriods()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        }
    }

    const handleToggleLock = async (id, isLocked) => {
        try {
            if (isLocked) {
                await fiscalLocksAPI.unlockPeriod(id)
                showToast(t('fiscal_locks.unlocked'), 'success')
            } else {
                await fiscalLocksAPI.lockPeriod(id)
                showToast(t('fiscal_locks.locked'), 'success')
            }
            fetchPeriods()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        }
    }

    if (loading) return <PageLoading />

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">🔒 {t('fiscal_locks.title')}</h1>
                    <p className="workspace-subtitle">{t('fiscal_locks.subtitle')}</p>
                </div>
                <div className="header-actions">
                    <button className="btn btn-primary" onClick={() => setShowForm(!showForm)}>
                        + {t('fiscal_locks.create_period')}
                    </button>
                </div>
            </div>

            {showForm && (
                <div className="modal-overlay">
                    <div className="modal-content" style={{ maxWidth: '500px' }}>
                        <div className="modal-header">
                            <h2 className="modal-title">🔒 {t('fiscal_locks.create_period')}</h2>
                            <button type="button" className="btn-icon" style={{ background: 'transparent' }} onClick={() => setShowForm(false)}>
                                ✕
                            </button>
                        </div>
                        <div className="modal-body">
                            <div className="form-group">
                                <label className="form-label">{t('common.name')}</label>
                                <input type="text" className="form-input" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder={t('fiscal_locks.period_name_placeholder')} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('common.start_date')}</label>
                                <DateInput className="form-input" value={form.start_date} onChange={e => setForm(f => ({ ...f, start_date: e.target.value }))} />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('common.end_date')}</label>
                                <DateInput className="form-input" value={form.end_date} onChange={e => setForm(f => ({ ...f, end_date: e.target.value }))} />
                            </div>
                        </div>
                        <div className="modal-footer">
                            <button className="btn" style={{ background: 'var(--bg-hover)' }} onClick={() => setShowForm(false)}>{t('common.cancel')}</button>
                            <button className="btn btn-primary" onClick={handleCreate}>{t('common.save')}</button>
                        </div>
                    </div>
                </div>
            )}

            <div className="card">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('common.name')}</th>
                            <th>{t('common.start_date')}</th>
                            <th>{t('common.end_date')}</th>
                            <th>{t('common.status_title')}</th>
                            <th>{t('common.actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {periods.length === 0 ? (
                            <tr><td colSpan="5" className="text-center py-5 text-muted">{t('fiscal_locks.empty')}</td></tr>
                        ) : periods.map(p => (
                            <tr key={p.id}>
                                <td className="font-medium">{p.name || `${t('fiscal_locks.period')} #${p.id}`}</td>
                                <td>{formatShortDate(p.start_date)}</td>
                                <td>{formatShortDate(p.end_date)}</td>
                                <td>
                                    <span className={`status-badge ${p.is_locked ? 'cancelled' : 'success'}`}>
                                        {p.is_locked ? `🔒 ${t('fiscal_locks.locked_status')}` : `🔓 ${t('fiscal_locks.open_status')}`}
                                    </span>
                                </td>
                                <td>
                                    <button className={`btn btn-sm ${p.is_locked ? 'btn-success' : 'btn-danger'}`} onClick={() => handleToggleLock(p.id, p.is_locked)}>
                                        {p.is_locked ? `🔓 ${t('fiscal_locks.unlock')}` : `🔒 ${t('fiscal_locks.lock')}`}
                                    </button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    )
}

export default FiscalPeriodLocks
