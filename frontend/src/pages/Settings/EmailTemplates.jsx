import { useState, useEffect, useCallback } from 'react'
import { emailTemplatesAPI } from '../../utils/api'
import { toastEmitter } from '../../utils/toastEmitter'
import { useTranslation } from 'react-i18next'
import { Mail, Plus, Trash2, X, Edit2 } from 'lucide-react'

function EmailTemplates() {
    const { t } = useTranslation()
    const [templates, setTemplates] = useState([])
    const [loading, setLoading] = useState(false)
    const [editor, setEditor] = useState(null) // { mode: 'create'|'edit', data }
    const [form, setForm] = useState({
        template_name: '',
        subject: '',
        body: '',
        variables: {},
        is_active: true,
    })

    const load = useCallback(async () => {
        try {
            setLoading(true)
            const res = await emailTemplatesAPI.list()
            setTemplates(Array.isArray(res.data) ? res.data : [])
        } catch (err) {
            toastEmitter.show('فشل تحميل القوالب', 'error')
        } finally {
            setLoading(false)
        }
    }, [])

    useEffect(() => {
        load()
    }, [load])

    const openCreate = () => {
        setForm({
            template_name: '',
            subject: '',
            body: '',
            variables: {},
            is_active: true,
        })
        setEditor({ mode: 'create' })
    }

    const openEdit = async (tpl) => {
        try {
            const res = await emailTemplatesAPI.get(tpl.id)
            const d = res.data
            setForm({
                template_name: d.template_name || '',
                subject: d.subject || '',
                body: d.body || '',
                variables: d.variables || {},
                is_active: d.is_active ?? true,
            })
            setEditor({ mode: 'edit', data: d })
        } catch (err) {
            toastEmitter.show('فشل تحميل القالب', 'error')
        }
    }

    const handleSubmit = async (e) => {
        e?.preventDefault?.()
        if (!form.template_name.trim() || !form.subject.trim() || !form.body.trim()) {
            toastEmitter.show('الاسم والموضوع والمحتوى مطلوبة', 'error')
            return
        }
        try {
            if (editor?.mode === 'create') {
                await emailTemplatesAPI.create(form)
                toastEmitter.show('تم إنشاء القالب', 'success')
            } else {
                // backend update doesn't include template_name
                const { template_name, ...updateData } = form
                await emailTemplatesAPI.update(editor.data.id, updateData)
                toastEmitter.show('تم تحديث القالب', 'success')
            }
            setEditor(null)
            load()
        } catch (err) {
            const msg = err?.response?.data?.detail || 'فشلت العملية'
            toastEmitter.show(typeof msg === 'string' ? msg : 'فشلت العملية', 'error')
        }
    }

    const handleDelete = async (tpl) => {
        if (!window.confirm(`تعطيل القالب "${tpl.template_name}"؟`)) return
        try {
            await emailTemplatesAPI.delete(tpl.id)
            toastEmitter.show('تم تعطيل القالب', 'success')
            load()
        } catch (err) {
            toastEmitter.show('فشل التعطيل', 'error')
        }
    }

    const variablesText = JSON.stringify(form.variables || {}, null, 2)

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1 className="workspace-title">
                            <Mail size={24} className="me-2" />
                            قوالب البريد الإلكتروني
                        </h1>
                        <p className="text-muted small mb-0">إدارة قوالب الرسائل المرسلة من النظام</p>
                    </div>
                    <button className="btn btn-primary d-flex align-items-center gap-2" onClick={openCreate}>
                        <Plus size={18} />
                        قالب جديد
                    </button>
                </div>
            </div>

            <div className="card">
                <div className="card-body">
                    {loading ? (
                        <p className="text-muted">جاري التحميل…</p>
                    ) : templates.length === 0 ? (
                        <p className="text-muted">لا توجد قوالب بعد</p>
                    ) : (
                        <div className="table-responsive">
                            <table className="table table-hover">
                                <thead>
                                    <tr>
                                        <th>الاسم</th>
                                        <th>الموضوع</th>
                                        <th>الحالة</th>
                                        <th>إجراءات</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {templates.map((t) => (
                                        <tr key={t.id}>
                                            <td><code>{t.template_name}</code></td>
                                            <td>{t.subject}</td>
                                            <td>
                                                <span className={`badge ${t.is_active ? 'bg-success' : 'bg-secondary'}`}>
                                                    {t.is_active ? 'مفعّل' : 'معطّل'}
                                                </span>
                                            </td>
                                            <td>
                                                <div className="d-flex gap-2">
                                                    <button
                                                        className="btn btn-sm btn-outline-primary"
                                                        onClick={() => openEdit(t)}
                                                    >
                                                        <Edit2 size={14} />
                                                    </button>
                                                    <button
                                                        className="btn btn-sm btn-outline-danger"
                                                        onClick={() => handleDelete(t)}
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

            {editor && (
                <div className="modal show d-block" tabIndex="-1" style={{ background: 'rgba(0,0,0,0.5)' }}>
                    <div className="modal-dialog modal-xl">
                        <div className="modal-content">
                            <div className="modal-header">
                                <h5 className="modal-title">
                                    {editor.mode === 'create' ? 'قالب جديد' : `تعديل: ${editor.data?.template_name}`}
                                </h5>
                                <button type="button" className="btn-close" onClick={() => setEditor(null)}><X size={20} /></button>
                            </div>
                            <form onSubmit={handleSubmit}>
                                <div className="modal-body">
                                    <div className="mb-3">
                                        <label className="form-label">اسم القالب (مفتاح فريد) *</label>
                                        <input
                                            type="text"
                                            className="form-control"
                                            value={form.template_name}
                                            onChange={(e) => setForm({ ...form, template_name: e.target.value })}
                                            disabled={editor.mode === 'edit'}
                                            placeholder="invoice_due, password_reset, ..."
                                            required
                                        />
                                    </div>
                                    <div className="mb-3">
                                        <label className="form-label">الموضوع *</label>
                                        <input
                                            type="text"
                                            className="form-control"
                                            value={form.subject}
                                            onChange={(e) => setForm({ ...form, subject: e.target.value })}
                                            placeholder="مرحبا {{name}}، فاتورتك رقم {{invoice_number}}"
                                            required
                                        />
                                    </div>
                                    <div className="mb-3">
                                        <label className="form-label">المحتوى (HTML) *</label>
                                        <textarea
                                            className="form-control font-monospace"
                                            rows="12"
                                            value={form.body}
                                            onChange={(e) => setForm({ ...form, body: e.target.value })}
                                            placeholder="<p>عزيزي {{name}}،</p><p>...</p>"
                                            required
                                        />
                                        <small className="text-muted">
                                            استخدم متغيرات مثل <code>&#123;&#123;name&#125;&#125;</code> أو <code>&#123;&#123;invoice_number&#125;&#125;</code>
                                        </small>
                                    </div>
                                    <div className="mb-3">
                                        <label className="form-label">المتغيرات المتاحة (JSON)</label>
                                        <textarea
                                            className="form-control font-monospace"
                                            rows="4"
                                            value={variablesText}
                                            onChange={(e) => {
                                                try {
                                                    setForm({ ...form, variables: JSON.parse(e.target.value || '{}') })
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
                                            id="active"
                                            checked={form.is_active}
                                            onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
                                        />
                                        <label className="form-check-label" htmlFor="active">
                                            مفعّل
                                        </label>
                                    </div>
                                </div>
                                <div className="modal-footer">
                                    <button type="button" className="btn btn-secondary" onClick={() => setEditor(null)}>
                                        إلغاء
                                    </button>
                                    <button type="submit" className="btn btn-primary">
                                        {editor.mode === 'create' ? 'إنشاء' : 'حفظ'}
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

export default EmailTemplates
