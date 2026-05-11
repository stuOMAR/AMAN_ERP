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
            toastEmitter.show(t('settings.email_templates.toast.load_failed'), 'error')
        } finally {
            setLoading(false)
        }
    }, [t])

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
            toastEmitter.show(t('settings.email_templates.toast.load_single_failed'), 'error')
        }
    }

    const handleSubmit = async (e) => {
        e?.preventDefault?.()
        if (!form.template_name.trim() || !form.subject.trim() || !form.body.trim()) {
            toastEmitter.show(t('settings.email_templates.toast.fields_required'), 'error')
            return
        }
        try {
            if (editor?.mode === 'create') {
                await emailTemplatesAPI.create(form)
                toastEmitter.show(t('settings.email_templates.toast.created_success'), 'success')
            } else {
                // backend update doesn't include template_name
                const { template_name, ...updateData } = form
                await emailTemplatesAPI.update(editor.data.id, updateData)
                toastEmitter.show(t('settings.email_templates.toast.updated_success'), 'success')
            }
            setEditor(null)
            load()
        } catch (err) {
            const msg = err?.response?.data?.detail || t('settings.email_templates.toast.operation_failed')
            toastEmitter.show(typeof msg === 'string' ? msg : t('settings.email_templates.toast.operation_failed'), 'error')
        }
    }

    const handleDelete = async (tpl) => {
        if (!window.confirm(`${t('settings.email_templates.toast.confirm_disable')} "${tpl.template_name}"؟`)) return
        try {
            await emailTemplatesAPI.delete(tpl.id)
            toastEmitter.show(t('settings.email_templates.toast.disabled_success'), 'success')
            load()
        } catch (err) {
            toastEmitter.show(t('settings.email_templates.toast.disable_failed'), 'error')
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
                            {t('settings.email_templates.title')}
                        </h1>
                        <p className="text-muted small mb-0">{t('settings.email_templates.subtitle')}</p>
                    </div>
                    <button className="btn btn-primary d-flex align-items-center gap-2" onClick={openCreate}>
                        <Plus size={18} />
                        {t('settings.email_templates.new_template')}
                    </button>
                </div>
            </div>

            <div className="card">
                <div className="card-body">
                    {loading ? (
                        <p className="text-muted">{t('settings.email_templates.loading')}</p>
                    ) : templates.length === 0 ? (
                        <p className="text-muted">{t('settings.email_templates.no_templates')}</p>
                    ) : (
                        <div className="table-responsive">
                            <table className="table table-hover">
                                <thead>
                                    <tr>
                                        <th>{t('settings.email_templates.table.name')}</th>
                                        <th>{t('settings.email_templates.table.subject')}</th>
                                        <th>{t('settings.email_templates.table.status')}</th>
                                        <th>{t('settings.email_templates.table.actions')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {templates.map((t) => (
                                        <tr key={t.id}>
                                            <td><code>{t.template_name}</code></td>
                                            <td>{t.subject}</td>
                                            <td>
                                                <span className={`badge ${t.is_active ? 'bg-success' : 'bg-secondary'}`}>
                                                    {t.is_active ? t('settings.email_templates.status.enabled') : t('settings.email_templates.status.disabled')}
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
                                    {editor.mode === 'create' ? t('settings.email_templates.modal.new_template') : `${t('settings.email_templates.modal.edit_prefix')}${editor.data?.template_name}`}
                                </h5>
                                <button type="button" className="btn-close" onClick={() => setEditor(null)}><X size={20} /></button>
                            </div>
                            <form onSubmit={handleSubmit}>
                                <div className="modal-body">
                                    <div className="mb-3">
                                        <label className="form-label">{t('settings.email_templates.modal.name_label')}</label>
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
                                        <label className="form-label">{t('settings.email_templates.modal.subject_label')}</label>
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
                                        <label className="form-label">{t('settings.email_templates.modal.body_html_label')}</label>
                                        <textarea
                                            className="form-control font-monospace"
                                            rows="12"
                                            value={form.body}
                                            onChange={(e) => setForm({ ...form, body: e.target.value })}
                                            placeholder="<p>عزيزي {{name}}،</p><p>...</p>"
                                            required
                                        />
                                        <small className="text-muted">
                                            {t('settings.email_templates.modal.body_html_help')}
                                        </small>
                                    </div>
                                    <div className="mb-3">
                                        <label className="form-label">{t('settings.email_templates.modal.variables_label')}</label>
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
                                            {t('settings.email_templates.modal.enabled_label')}
                                        </label>
                                    </div>
                                </div>
                                <div className="modal-footer">
                                    <button type="button" className="btn btn-secondary" onClick={() => setEditor(null)}>
                                        {t('settings.email_templates.modal.cancel')}
                                    </button>
                                    <button type="submit" className="btn btn-primary">
                                        {editor.mode === 'create' ? t('settings.email_templates.modal.create') : t('settings.email_templates.modal.save')}
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
