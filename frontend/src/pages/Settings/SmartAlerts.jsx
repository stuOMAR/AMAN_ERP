import { useState, useEffect, useCallback } from 'react'
import { smartAlertsAPI } from '../../utils/api'
import { toastEmitter } from '../../utils/toastEmitter'
import { useTranslation } from 'react-i18next'
import { Bell, BellRing, Plus, Trash2, X, CheckCircle, Power, PowerOff } from 'lucide-react'

const RULE_TYPES = [
    { value: 'low_stock' },
    { value: 'overdue_invoice' },
    { value: 'cash_balance_low' },
    { value: 'budget_overrun' },
    { value: 'expense_threshold' },
    { value: 'revenue_drop' },
]

const STATUS_LABELS = {
    fired: 'settings.smart_alerts.statuses.fired',
    resolved: 'settings.smart_alerts.statuses.resolved',
    suppressed: 'settings.smart_alerts.statuses.suppressed',
}

function SmartAlerts() {
    const { t, i18n } = useTranslation()
    const isAr = i18n.language === 'ar'
    const [tab, setTab] = useState('rules') // 'rules' | 'fired'
    const [rules, setRules] = useState([])
    const [alerts, setAlerts] = useState([])
    const [loading, setLoading] = useState(false)
    const [showCreate, setShowCreate] = useState(false)
    const [editingRule, setEditingRule] = useState(null)
    const [statusFilter, setStatusFilter] = useState('')
    const [form, setForm] = useState({
        name: '',
        rule_type: 'low_stock',
        threshold: 0,
        enabled: true,
        condition_json: {},
        notify_users: [],
    })

    const loadRules = useCallback(async () => {
        try {
            setLoading(true)
            const res = await smartAlertsAPI.listRules()
            setRules(Array.isArray(res.data) ? res.data : [])
        } catch (err) {
            toastEmitter.show(t('settings.smart_alerts.toast.load_rules_failed'), 'error')
        } finally {
            setLoading(false)
        }
    }, [])

    const loadAlerts = useCallback(async () => {
        try {
            setLoading(true)
            const res = await smartAlertsAPI.listAlerts(statusFilter ? { status: statusFilter } : null)
            setAlerts(Array.isArray(res.data) ? res.data : [])
        } catch (err) {
            toastEmitter.show(t('settings.smart_alerts.toast.load_alerts_failed'), 'error')
        } finally {
            setLoading(false)
        }
    }, [statusFilter])

    useEffect(() => {
        if (tab === 'rules') loadRules()
        else loadAlerts()
    }, [tab, loadRules, loadAlerts])

    const resetForm = () => {
        setForm({
            name: '',
            rule_type: 'low_stock',
            threshold: 0,
            enabled: true,
            condition_json: {},
            notify_users: [],
        })
        setEditingRule(null)
    }

    const openCreate = () => {
        resetForm()
        setShowCreate(true)
    }

    const openEdit = (rule) => {
        setForm({
            name: rule.name || '',
            rule_type: rule.rule_type || 'low_stock',
            threshold: Number(rule.threshold) || 0,
            enabled: rule.enabled ?? true,
            condition_json: rule.condition_json || {},
            notify_users: rule.notify_users || [],
        })
        setEditingRule(rule)
        setShowCreate(true)
    }

    const handleSubmit = async (e) => {
        e?.preventDefault?.()
        if (!form.name.trim()) {
            toastEmitter.show(t('settings.smart_alerts.toast.name_required'), 'error')
            return
        }
        try {
            if (editingRule) {
                await smartAlertsAPI.updateRule(editingRule.id, form)
                toastEmitter.show(t('settings.smart_alerts.toast.updated'), 'success')
            } else {
                await smartAlertsAPI.createRule(form)
                toastEmitter.show(t('settings.smart_alerts.toast.created'), 'success')
            }
            setShowCreate(false)
            resetForm()
            loadRules()
        } catch (err) {
            const msg = err?.response?.data?.detail || t('settings.smart_alerts.toast.operation_failed')
            toastEmitter.show(typeof msg === 'string' ? msg : t('settings.smart_alerts.toast.operation_failed'), 'error')
        }
    }

    const handleToggle = async (rule) => {
        try {
            await smartAlertsAPI.updateRule(rule.id, { enabled: !rule.enabled })
            loadRules()
        } catch (err) {
            toastEmitter.show(t('settings.smart_alerts.toast.toggle_failed'), 'error')
        }
    }

    const handleDelete = async (rule) => {
        if (!window.confirm(t('settings.smart_alerts.confirm_delete').replace('{{name}}', rule.name))) return
        try {
            await smartAlertsAPI.deleteRule(rule.id)
            toastEmitter.show(t('settings.smart_alerts.toast.deleted'), 'success')
            loadRules()
        } catch (err) {
            toastEmitter.show(t('settings.smart_alerts.toast.delete_failed'), 'error')
        }
    }

    const handleResolve = async (alert) => {
        try {
            await smartAlertsAPI.resolveAlert(alert.id)
            toastEmitter.show(t('settings.smart_alerts.toast.resolved'), 'success')
            loadAlerts()
        } catch (err) {
            toastEmitter.show(t('settings.smart_alerts.toast.resolve_failed'), 'error')
        }
    }

    const ruleTypeLabel = (type) => {
        return t('settings.smart_alerts.alert_types.' + type)
    }

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1 className="workspace-title">
                            <Bell size={24} className="me-2" />
                            {t('settings.smart_alerts.title')}
                        </h1>
                        <p className="text-muted small mb-0">{t('settings.smart_alerts.subtitle')}</p>
                    </div>
                </div>
            </div>

            {/* Tabs */}
            <ul className="nav nav-tabs mb-3">
                <li className="nav-item">
                    <button
                        className={`nav-link ${tab === 'rules' ? 'active' : ''}`}
                        onClick={() => setTab('rules')}
                    >
                        {t('settings.smart_alerts.alert_rules')} ({rules.length})
                    </button>
                </li>
                <li className="nav-item">
                    <button
                        className={`nav-link ${tab === 'fired' ? 'active' : ''}`}
                        onClick={() => setTab('fired')}
                    >
                        <BellRing size={16} className="me-1" />
                        {t('settings.smart_alerts.fired_alerts')}
                    </button>
                </li>
            </ul>

            {tab === 'rules' && (
                <div className="card">
                    <div className="card-body">
                        <div className="d-flex justify-content-between align-items-center mb-3">
                            <h5 className="mb-0">{t('settings.smart_alerts.alert_rules')}</h5>
                            <button className="btn btn-primary d-flex align-items-center gap-2" onClick={openCreate}>
                                <Plus size={18} />
                                {t('settings.smart_alerts.buttons.add_rule')}
                            </button>
                        </div>
                        {loading ? (
                            <p className="text-muted">{t('common.loading')}</p>
                        ) : rules.length === 0 ? (
                            <p className="text-muted">{t('settings.smart_alerts.empty_rules')}</p>
                        ) : (
                            <div className="table-responsive">
                                <table className="table table-hover">
                                    <thead>
                                        <tr>
                                            <th>{t('settings.smart_alerts.table.name')}</th>
                                            <th>{t('settings.smart_alerts.table.type')}</th>
                                            <th>{t('settings.smart_alerts.table.threshold')}</th>
                                            <th>{t('settings.smart_alerts.table.status')}</th>
                                            <th>{t('settings.smart_alerts.table.actions')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {rules.map((r) => (
                                            <tr key={r.id}>
                                                <td>{r.name}</td>
                                                <td>{ruleTypeLabel(r.rule_type)}</td>
                                                <td>{Number(r.threshold).toLocaleString()}</td>
                                                <td>
                                                    <span className={`badge ${r.enabled ? 'bg-success' : 'bg-secondary'}`}>
                                                        {r.enabled ? t('settings.smart_alerts.badges.enabled') : t('settings.smart_alerts.badges.disabled')}
                                                    </span>
                                                </td>
                                                <td>
                                                    <div className="d-flex gap-2">
                                                        <button
                                                            className="btn btn-sm btn-outline-primary"
                                                            onClick={() => openEdit(r)}
                                                            title={t('settings.smart_alerts.buttons.edit')}
                                                        >
                                                            {t('settings.smart_alerts.buttons.edit')}
                                                        </button>
                                                        <button
                                                            className={`btn btn-sm ${r.enabled ? 'btn-outline-warning' : 'btn-outline-success'}`}
                                                            onClick={() => handleToggle(r)}
                                                            title={r.enabled ? t('settings.smart_alerts.buttons.disable') : t('settings.smart_alerts.buttons.enable')}
                                                        >
                                                            {r.enabled ? <PowerOff size={14} /> : <Power size={14} />}
                                                        </button>
                                                        <button
                                                            className="btn btn-sm btn-outline-danger"
                                                            onClick={() => handleDelete(r)}
                                                            title={t('settings.smart_alerts.buttons.delete')}
                                                        >
                                                            <Trash2 size={14} />
                                                        </button>
                                                    </div>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>
                </div>
            )}

            {tab === 'fired' && (
                <div className="card">
                    <div className="card-body">
                        <div className="d-flex justify-content-between align-items-center mb-3">
                            <h5 className="mb-0">{t('settings.smart_alerts.fired_alerts')}</h5>
                            <select
                                className="form-select"
                                style={{ width: 200 }}
                                value={statusFilter}
                                onChange={(e) => setStatusFilter(e.target.value)}
                            >
                                <option value="">{t('common.all')}</option>
                                <option value="fired">{t('settings.smart_alerts.statuses.fired')}</option>
                                <option value="resolved">{t('settings.smart_alerts.statuses.resolved')}</option>
                                <option value="suppressed">{t('settings.smart_alerts.statuses.suppressed')}</option>
                            </select>
                        </div>
                        {loading ? (
                            <p className="text-muted">{t('common.loading')}</p>
                        ) : alerts.length === 0 ? (
                            <p className="text-muted">{t('settings.smart_alerts.empty_alerts')}</p>
                        ) : (
                            <div className="table-responsive">
                                <table className="table table-hover">
                                    <thead>
                                        <tr>
                                            <th>{t('settings.smart_alerts.table.rule')}</th>
                                            <th>{t('settings.smart_alerts.table.type')}</th>
                                            <th>{t('settings.smart_alerts.table.fired_at')}</th>
                                            <th>{t('settings.smart_alerts.table.status')}</th>
                                            <th>{t('settings.smart_alerts.table.actions')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {alerts.map((a) => (
                                            <tr key={a.id}>
                                                <td>{a.rule_name}</td>
                                                <td>{ruleTypeLabel(a.rule_type)}</td>
                                                <td>{a.triggered_at ? new Date(a.triggered_at).toLocaleString('ar') : '-'}</td>
                                                <td>
                                                    <span className={`badge ${a.status === 'resolved' ? 'bg-success' : a.status === 'fired' ? 'bg-warning' : 'bg-secondary'}`}>
                                                        {t(STATUS_LABELS[a.status]) || a.status}
                                                    </span>
                                                </td>
                                                <td>
                                                    {a.status === 'fired' && (
                                                        <button
                                                            className="btn btn-sm btn-outline-success"
                                                            onClick={() => handleResolve(a)}
                                                        >
                                                            <CheckCircle size={14} className="me-1" />
                                                            {t('settings.smart_alerts.buttons.resolve')}
                                                        </button>
                                                    )}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>
                </div>
            )}

            {/* Create/Edit Modal */}
            {showCreate && (
                <div className="modal show d-block" tabIndex="-1" style={{ background: 'rgba(0,0,0,0.5)' }}>
                    <div className="modal-dialog modal-lg">
                        <div className="modal-content">
                            <div className="modal-header">
                                <h5 className="modal-title">{editingRule ? t('settings.smart_alerts.modal.edit_rule') : t('settings.smart_alerts.modal.add_rule')}</h5>
                                <button type="button" className="btn-close" onClick={() => { setShowCreate(false); resetForm(); }}><X size={20} /></button>
                            </div>
                            <form onSubmit={handleSubmit}>
                                <div className="modal-body">
                                    <div className="mb-3">
                                        <label className="form-label">{t('settings.smart_alerts.modal.name_label')}</label>
                                        <input
                                            type="text"
                                            className="form-control"
                                            value={form.name}
                                            onChange={(e) => setForm({ ...form, name: e.target.value })}
                                            required
                                        />
                                    </div>
                                    <div className="mb-3">
                                        <label className="form-label">{t('settings.smart_alerts.modal.type_label')}</label>
                                        <select
                                            className="form-select"
                                            value={form.rule_type}
                                            onChange={(e) => setForm({ ...form, rule_type: e.target.value })}
                                        >
                                            {RULE_TYPES.map((r) => (
                                                <option key={r.value} value={r.value}>{t('settings.smart_alerts.alert_types.' + r.value)}</option>
                                            ))}
                                        </select>
                                    </div>
                                    <div className="mb-3">
                                        <label className="form-label">{t('settings.smart_alerts.modal.threshold_label')}</label>
                                        <input
                                            type="number"
                                            step="0.01"
                                            className="form-control"
                                            value={form.threshold}
                                            onChange={(e) => setForm({ ...form, threshold: e.target.value })}
                                        />
                                        <small className="text-muted">{t('settings.smart_alerts.modal.threshold_help')}</small>
                                    </div>
                                    <div className="mb-3">
                                        <label className="form-label">{t('settings.smart_alerts.modal.extra_conditions')}</label>
                                        <textarea
                                            className="form-control"
                                            rows="3"
                                            placeholder='{"branch_id": 1, "category_id": 5}'
                                            value={JSON.stringify(form.condition_json || {})}
                                            onChange={(e) => {
                                                try {
                                                    setForm({ ...form, condition_json: JSON.parse(e.target.value || '{}') })
                                                } catch {
                                                    /* ignore until valid */
                                                }
                                            }}
                                        />
                                    </div>
                                    <div className="form-check mb-3">
                                        <input
                                            className="form-check-input"
                                            type="checkbox"
                                            id="enabled"
                                            checked={form.enabled}
                                            onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
                                        />
                                        <label className="form-check-label" htmlFor="enabled">
                                            {t('settings.smart_alerts.modal.enable_rule')}
                                        </label>
                                    </div>
                                </div>
                                <div className="modal-footer">
                                    <button type="button" className="btn btn-secondary" onClick={() => { setShowCreate(false); resetForm(); }}>
                                        {t('common.cancel')}
                                    </button>
                                    <button type="submit" className="btn btn-primary">
                                        {editingRule ? t('settings.smart_alerts.buttons.update') : t('settings.smart_alerts.buttons.create')}
                                    </button>
                                </div>
                            </form>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}

export default SmartAlerts
