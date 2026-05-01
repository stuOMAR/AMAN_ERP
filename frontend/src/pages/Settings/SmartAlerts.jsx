import { useState, useEffect, useCallback } from 'react'
import { smartAlertsAPI } from '../../utils/api'
import { toastEmitter } from '../../utils/toastEmitter'
import { useTranslation } from 'react-i18next'
import { Bell, BellRing, Plus, Trash2, X, CheckCircle, Power, PowerOff } from 'lucide-react'

const RULE_TYPES = [
    { value: 'low_stock', label: 'مخزون منخفض', label_en: 'Low Stock' },
    { value: 'overdue_invoice', label: 'فاتورة متأخرة', label_en: 'Overdue Invoice' },
    { value: 'cash_balance_low', label: 'رصيد نقدي منخفض', label_en: 'Low Cash Balance' },
    { value: 'budget_overrun', label: 'تجاوز الميزانية', label_en: 'Budget Overrun' },
    { value: 'expense_threshold', label: 'حد أقصى للمصروف', label_en: 'Expense Threshold' },
    { value: 'revenue_drop', label: 'انخفاض الإيرادات', label_en: 'Revenue Drop' },
]

const STATUS_LABELS = {
    fired: 'مُطلق',
    resolved: 'محلول',
    suppressed: 'مكبوت',
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
            toastEmitter.show('فشل تحميل قواعد التنبيهات', 'error')
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
            toastEmitter.show('فشل تحميل التنبيهات', 'error')
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
            toastEmitter.show('اسم القاعدة مطلوب', 'error')
            return
        }
        try {
            if (editingRule) {
                await smartAlertsAPI.updateRule(editingRule.id, form)
                toastEmitter.show('تم تحديث القاعدة', 'success')
            } else {
                await smartAlertsAPI.createRule(form)
                toastEmitter.show('تم إنشاء القاعدة', 'success')
            }
            setShowCreate(false)
            resetForm()
            loadRules()
        } catch (err) {
            const msg = err?.response?.data?.detail || 'فشلت العملية'
            toastEmitter.show(typeof msg === 'string' ? msg : 'فشلت العملية', 'error')
        }
    }

    const handleToggle = async (rule) => {
        try {
            await smartAlertsAPI.updateRule(rule.id, { enabled: !rule.enabled })
            loadRules()
        } catch (err) {
            toastEmitter.show('فشل التبديل', 'error')
        }
    }

    const handleDelete = async (rule) => {
        if (!window.confirm(`حذف القاعدة "${rule.name}"؟`)) return
        try {
            await smartAlertsAPI.deleteRule(rule.id)
            toastEmitter.show('تم الحذف', 'success')
            loadRules()
        } catch (err) {
            toastEmitter.show('فشل الحذف', 'error')
        }
    }

    const handleResolve = async (alert) => {
        try {
            await smartAlertsAPI.resolveAlert(alert.id)
            toastEmitter.show('تم حل التنبيه', 'success')
            loadAlerts()
        } catch (err) {
            toastEmitter.show('فشل حل التنبيه', 'error')
        }
    }

    const ruleTypeLabel = (type) => {
        const r = RULE_TYPES.find((x) => x.value === type)
        if (!r) return type
        return isAr ? r.label : r.label_en
    }

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1 className="workspace-title">
                            <Bell size={24} className="me-2" />
                            التنبيهات الذكية
                        </h1>
                        <p className="text-muted small mb-0">إدارة قواعد التنبيهات التلقائية</p>
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
                        قواعد التنبيهات ({rules.length})
                    </button>
                </li>
                <li className="nav-item">
                    <button
                        className={`nav-link ${tab === 'fired' ? 'active' : ''}`}
                        onClick={() => setTab('fired')}
                    >
                        <BellRing size={16} className="me-1" />
                        التنبيهات المُطلقة
                    </button>
                </li>
            </ul>

            {tab === 'rules' && (
                <div className="card">
                    <div className="card-body">
                        <div className="d-flex justify-content-between align-items-center mb-3">
                            <h5 className="mb-0">القواعد</h5>
                            <button className="btn btn-primary d-flex align-items-center gap-2" onClick={openCreate}>
                                <Plus size={18} />
                                إضافة قاعدة
                            </button>
                        </div>
                        {loading ? (
                            <p className="text-muted">جاري التحميل…</p>
                        ) : rules.length === 0 ? (
                            <p className="text-muted">لا توجد قواعد بعد</p>
                        ) : (
                            <div className="table-responsive">
                                <table className="table table-hover">
                                    <thead>
                                        <tr>
                                            <th>الاسم</th>
                                            <th>النوع</th>
                                            <th>العتبة</th>
                                            <th>الحالة</th>
                                            <th>إجراءات</th>
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
                                                        {r.enabled ? 'مفعّلة' : 'معطّلة'}
                                                    </span>
                                                </td>
                                                <td>
                                                    <div className="d-flex gap-2">
                                                        <button
                                                            className="btn btn-sm btn-outline-primary"
                                                            onClick={() => openEdit(r)}
                                                            title="تعديل"
                                                        >
                                                            تعديل
                                                        </button>
                                                        <button
                                                            className={`btn btn-sm ${r.enabled ? 'btn-outline-warning' : 'btn-outline-success'}`}
                                                            onClick={() => handleToggle(r)}
                                                            title={r.enabled ? 'تعطيل' : 'تفعيل'}
                                                        >
                                                            {r.enabled ? <PowerOff size={14} /> : <Power size={14} />}
                                                        </button>
                                                        <button
                                                            className="btn btn-sm btn-outline-danger"
                                                            onClick={() => handleDelete(r)}
                                                            title="حذف"
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
                            <h5 className="mb-0">التنبيهات</h5>
                            <select
                                className="form-select"
                                style={{ width: 200 }}
                                value={statusFilter}
                                onChange={(e) => setStatusFilter(e.target.value)}
                            >
                                <option value="">الكل</option>
                                <option value="fired">مُطلق</option>
                                <option value="resolved">محلول</option>
                                <option value="suppressed">مكبوت</option>
                            </select>
                        </div>
                        {loading ? (
                            <p className="text-muted">جاري التحميل…</p>
                        ) : alerts.length === 0 ? (
                            <p className="text-muted">لا توجد تنبيهات</p>
                        ) : (
                            <div className="table-responsive">
                                <table className="table table-hover">
                                    <thead>
                                        <tr>
                                            <th>القاعدة</th>
                                            <th>النوع</th>
                                            <th>وقت التنبيه</th>
                                            <th>الحالة</th>
                                            <th>إجراءات</th>
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
                                                        {STATUS_LABELS[a.status] || a.status}
                                                    </span>
                                                </td>
                                                <td>
                                                    {a.status === 'fired' && (
                                                        <button
                                                            className="btn btn-sm btn-outline-success"
                                                            onClick={() => handleResolve(a)}
                                                        >
                                                            <CheckCircle size={14} className="me-1" />
                                                            حل
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
                                <h5 className="modal-title">{editingRule ? 'تعديل قاعدة' : 'إضافة قاعدة'}</h5>
                                <button type="button" className="btn-close" onClick={() => { setShowCreate(false); resetForm(); }}><X size={20} /></button>
                            </div>
                            <form onSubmit={handleSubmit}>
                                <div className="modal-body">
                                    <div className="mb-3">
                                        <label className="form-label">اسم القاعدة *</label>
                                        <input
                                            type="text"
                                            className="form-control"
                                            value={form.name}
                                            onChange={(e) => setForm({ ...form, name: e.target.value })}
                                            required
                                        />
                                    </div>
                                    <div className="mb-3">
                                        <label className="form-label">نوع القاعدة *</label>
                                        <select
                                            className="form-select"
                                            value={form.rule_type}
                                            onChange={(e) => setForm({ ...form, rule_type: e.target.value })}
                                        >
                                            {RULE_TYPES.map((r) => (
                                                <option key={r.value} value={r.value}>{isAr ? r.label : r.label_en}</option>
                                            ))}
                                        </select>
                                    </div>
                                    <div className="mb-3">
                                        <label className="form-label">العتبة (Threshold)</label>
                                        <input
                                            type="number"
                                            step="0.01"
                                            className="form-control"
                                            value={form.threshold}
                                            onChange={(e) => setForm({ ...form, threshold: parseFloat(e.target.value) || 0 })}
                                        />
                                        <small className="text-muted">القيمة التي تُطلق التنبيه عند تجاوزها (أو الانخفاض عنها لقواعد المخزون)</small>
                                    </div>
                                    <div className="mb-3">
                                        <label className="form-label">شروط إضافية (JSON اختياري)</label>
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
                                            تفعيل القاعدة
                                        </label>
                                    </div>
                                </div>
                                <div className="modal-footer">
                                    <button type="button" className="btn btn-secondary" onClick={() => { setShowCreate(false); resetForm(); }}>
                                        إلغاء
                                    </button>
                                    <button type="submit" className="btn btn-primary">
                                        {editingRule ? 'تحديث' : 'إنشاء'}
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
