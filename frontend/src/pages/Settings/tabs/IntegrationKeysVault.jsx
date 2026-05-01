import { useState, useEffect, useCallback } from 'react'
import { integrationKeysAPI } from '../../utils/api'
import { toastEmitter } from '../../utils/toastEmitter'
import { useTranslation } from 'react-i18next'
import { Key, RefreshCcw, ShieldOff, Plus, Activity, X } from 'lucide-react'

const STATUS_COLORS = {
    active: 'text-success',
    rotated: 'text-warning',
    revoked: 'text-danger',
    pending: 'text-muted',
}

function IntegrationKeysVault() {
    const { t } = useTranslation()
    const [keys, setKeys] = useState([])
    const [breakers, setBreakers] = useState([])
    const [loading, setLoading] = useState(false)
    const [showCreate, setShowCreate] = useState(false)
    const [includeRevoked, setIncludeRevoked] = useState(false)
    const [form, setForm] = useState({
        integration_type: '',
        provider: '',
        key_name: '',
        plaintext_value: '',
        valid_to: '',
        activate: true,
    })

    const loadKeys = useCallback(async () => {
        try {
            const res = await integrationKeysAPI.list({ include_revoked: includeRevoked })
            setKeys(res.data)
        } catch { /* silently handled by toast */ }
    }, [includeRevoked])

    const loadBreakers = useCallback(async () => {
        try {
            const res = await integrationKeysAPI.listCircuitBreakers()
            setBreakers(res.data?.persisted || [])
        } catch { /* silently handled */ }
    }, [])

    useEffect(() => {
        setLoading(true)
        Promise.all([loadKeys(), loadBreakers()]).finally(() => setLoading(false))
    }, [loadKeys, loadBreakers])

    const handleCreate = async (e) => {
        e.preventDefault()
        try {
            await integrationKeysAPI.create({
                ...form,
                valid_to: form.valid_to || null,
            })
            toastEmitter.emit('تم حفظ المفتاح', 'success')
            setShowCreate(false)
            setForm({ integration_type: '', provider: '', key_name: '', plaintext_value: '', valid_to: '', activate: true })
            loadKeys()
        } catch (err) {
            toastEmitter.emit(err.response?.data?.detail || 'فشل الحفظ', 'error')
        }
    }

    const handleRevoke = async (id, keyName) => {
        if (!window.confirm(`هل تريد إلغاء المفتاح "${keyName}"؟`)) return
        try {
            await integrationKeysAPI.revoke(id)
            toastEmitter.emit('تم إلغاء المفتاح', 'success')
            loadKeys()
        } catch (err) {
            toastEmitter.emit(err.response?.data?.detail || 'فشل الإلغاء', 'error')
        }
    }

    const handleResetBreaker = async (id, label) => {
        if (!window.confirm(`إعادة ضبط القاطع "${label}"؟`)) return
        try {
            await integrationKeysAPI.resetCircuitBreaker(id)
            toastEmitter.emit('تم إعادة ضبط القاطع', 'success')
            loadBreakers()
        } catch (err) {
            toastEmitter.emit(err.response?.data?.detail || 'فشل الإعادة', 'error')
        }
    }

    return (
        <div className="space-y-8">
            {/* ── Integration Keys ────────────────────────────── */}
            <div className="bg-base-50 p-6 rounded-2xl border border-base-200">
                <div className="flex items-center justify-between mb-4">
                    <h3 className="text-lg font-bold flex items-center gap-2">
                        <Key size={20} className="text-primary" />
                        مخزن مفاتيح التكاملات
                    </h3>
                    <div className="flex gap-2 items-center">
                        <label className="flex items-center gap-1 text-sm text-muted cursor-pointer">
                            <input type="checkbox" checked={includeRevoked}
                                onChange={e => setIncludeRevoked(e.target.checked)} />
                            عرض الملغية
                        </label>
                        <button className="btn btn-primary btn-sm" onClick={() => setShowCreate(true)}>
                            <Plus size={14} /> مفتاح جديد / تدوير
                        </button>
                    </div>
                </div>

                {showCreate && (
                    <form onSubmit={handleCreate} className="card p-4 mb-4 border border-primary-200">
                        <div className="flex justify-between mb-3">
                            <strong>إضافة / تدوير مفتاح</strong>
                            <button type="button" onClick={() => setShowCreate(false)}><X size={16} /></button>
                        </div>
                        <div className="grid grid-cols-2 gap-3">
                            <div className="form-group">
                                <label>نوع التكامل</label>
                                <input className="form-input ltr" required value={form.integration_type}
                                    placeholder="payment / sms / einvoice …"
                                    onChange={e => setForm(f => ({ ...f, integration_type: e.target.value }))} />
                            </div>
                            <div className="form-group">
                                <label>المزود (Provider)</label>
                                <input className="form-input ltr" required value={form.provider}
                                    placeholder="stripe / twilio / eta …"
                                    onChange={e => setForm(f => ({ ...f, provider: e.target.value }))} />
                            </div>
                            <div className="form-group">
                                <label>اسم المفتاح</label>
                                <input className="form-input ltr" required value={form.key_name}
                                    placeholder="api_key / client_secret …"
                                    onChange={e => setForm(f => ({ ...f, key_name: e.target.value }))} />
                            </div>
                            <div className="form-group">
                                <label>القيمة (ستُشفَّر)</label>
                                <input className="form-input ltr" type="password" required value={form.plaintext_value}
                                    onChange={e => setForm(f => ({ ...f, plaintext_value: e.target.value }))} />
                            </div>
                            <div className="form-group">
                                <label>صالح حتى (اختياري)</label>
                                <input className="form-input ltr" type="datetime-local" value={form.valid_to}
                                    onChange={e => setForm(f => ({ ...f, valid_to: e.target.value }))} />
                            </div>
                            <div className="form-group flex items-end">
                                <label className="flex items-center gap-2 cursor-pointer">
                                    <input type="checkbox" checked={form.activate}
                                        onChange={e => setForm(f => ({ ...f, activate: e.target.checked }))} />
                                    تفعيل فوري (يُلغي القديم)
                                </label>
                            </div>
                        </div>
                        <div className="flex justify-end gap-2 mt-3">
                            <button type="button" className="btn btn-secondary btn-sm" onClick={() => setShowCreate(false)}>إلغاء</button>
                            <button type="submit" className="btn btn-primary btn-sm">حفظ وتشفير</button>
                        </div>
                    </form>
                )}

                {loading ? (
                    <div className="text-center py-4 text-muted">جارٍ التحميل…</div>
                ) : keys.length === 0 ? (
                    <div className="text-center py-6 text-muted">لا توجد مفاتيح مسجّلة</div>
                ) : (
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>النوع</th>
                                <th>المزود</th>
                                <th>المفتاح</th>
                                <th>الحالة</th>
                                <th>صالح من</th>
                                <th>صالح حتى</th>
                                <th>إجراء</th>
                            </tr>
                        </thead>
                        <tbody>
                            {keys.map(k => (
                                <tr key={k.id}>
                                    <td><code>{k.integration_type}</code></td>
                                    <td><code>{k.provider}</code></td>
                                    <td><code>{k.key_name}</code></td>
                                    <td>
                                        <span className={STATUS_COLORS[k.key_status] || ''}>
                                            {k.key_status}
                                        </span>
                                    </td>
                                    <td className="text-xs">{k.valid_from?.slice(0, 16) || '—'}</td>
                                    <td className="text-xs">{k.valid_to?.slice(0, 16) || '∞'}</td>
                                    <td>
                                        {k.key_status === 'active' && (
                                            <button
                                                className="btn btn-sm btn-danger"
                                                onClick={() => handleRevoke(k.id, k.key_name)}
                                                title="إلغاء"
                                            >
                                                <ShieldOff size={13} />
                                            </button>
                                        )}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </div>

            {/* ── Circuit Breakers ────────────────────────────── */}
            <div className="bg-base-50 p-6 rounded-2xl border border-base-200">
                <div className="flex items-center justify-between mb-4">
                    <h3 className="text-lg font-bold flex items-center gap-2">
                        <Activity size={20} className="text-warning" />
                        حالة قواطع الدوائر (Circuit Breakers)
                    </h3>
                    <button className="btn btn-secondary btn-sm" onClick={loadBreakers}>
                        <RefreshCcw size={14} /> تحديث
                    </button>
                </div>

                {breakers.length === 0 ? (
                    <div className="text-center py-4 text-muted">لا توجد قواطع نشطة — كل التكاملات تعمل بشكل طبيعي ✅</div>
                ) : (
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>التكامل</th>
                                <th>المزود</th>
                                <th>الحالة</th>
                                <th>عدد الأخطاء</th>
                                <th>مفتوح حتى</th>
                                <th>آخر خطأ</th>
                                <th>إجراء</th>
                            </tr>
                        </thead>
                        <tbody>
                            {breakers.map(b => (
                                <tr key={b.id}>
                                    <td><code>{b.integration_type}</code></td>
                                    <td><code>{b.provider}</code></td>
                                    <td>
                                        <span className={
                                            b.state === 'open' ? 'text-danger font-bold' :
                                            b.state === 'half_open' ? 'text-warning' : 'text-success'
                                        }>
                                            {b.state === 'open' ? '🔴 مفتوح' :
                                             b.state === 'half_open' ? '🟡 نصف مفتوح' : '🟢 مغلق'}
                                        </span>
                                    </td>
                                    <td>{b.failure_count}</td>
                                    <td className="text-xs">{b.opens_until?.slice(0, 16) || '—'}</td>
                                    <td className="text-xs text-truncate" style={{ maxWidth: 180 }}
                                        title={b.last_error}>{b.last_error || '—'}</td>
                                    <td>
                                        {b.state !== 'closed' && (
                                            <button
                                                className="btn btn-sm btn-warning"
                                                onClick={() => handleResetBreaker(b.id, `${b.integration_type}/${b.provider}`)}
                                                title="إعادة ضبط"
                                            >
                                                <RefreshCcw size={13} />
                                            </button>
                                        )}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </div>
        </div>
    )
}

export default IntegrationKeysVault
