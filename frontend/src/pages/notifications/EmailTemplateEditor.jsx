import React, { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { notificationsAPI } from '../../services/notifications';

/**
 * EmailTemplateEditor — CRUD for email templates with Jinja preview + locale tabs.
 */
export default function EmailTemplateEditor() {
  const { t } = useTranslation();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    code: '', locale: 'en', subject: '', body_html: '', body_text: '',
  });
  const [templates, setTemplates] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState(null);
  const [error, setError] = useState('');

  const loadTemplates = useCallback(async () => {
    setIsLoading(true);
    setError('');
    try {
      const res = await notificationsAPI.getEmailTemplates();
      const payload = res.data?.items ?? res.data ?? [];
      setTemplates(Array.isArray(payload) ? payload : []);
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || t('common.error'));
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    loadTemplates();
  }, [loadTemplates]);

  const handleCreate = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError('');
    try {
      await notificationsAPI.createEmailTemplate(form);
      await loadTemplates();
      setShowForm(false);
      setForm({ code: '', locale: 'en', subject: '', body_html: '', body_text: '' });
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || t('common.error'));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id) => {
    setDeletingId(id);
    setError('');
    try {
      await notificationsAPI.deleteEmailTemplate(id);
      await loadTemplates();
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || t('common.error'));
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="email-template-editor">
      <h2>{t('notifications.email_template_editor.title')}</h2>

      <button className="btn btn-primary mb-3" onClick={() => setShowForm(!showForm)}>
        {showForm ? t('notifications.email_template_editor.buttons.cancel') : t('notifications.email_template_editor.buttons.new_template')}
      </button>

      {showForm && (
        <form className="card p-3 mb-3" onSubmit={handleCreate}>
          <div className="row">
            <div className="col-md-4">
              <label>{t('notifications.email_template_editor.form.code')}</label>
              <input className="form-control" value={form.code} required
                onChange={(e) => setForm({ ...form, code: e.target.value })} />
            </div>
            <div className="col-md-2">
              <label>{t('notifications.email_template_editor.form.locale')}</label>
              <select className="form-control" value={form.locale}
                onChange={(e) => setForm({ ...form, locale: e.target.value })}>
                <option value="en">{t('notifications.email_template_editor.form.locale_en')}</option>
                <option value="ar">{t('notifications.email_template_editor.form.locale_ar')}</option>
              </select>
            </div>
            <div className="col-md-6">
              <label>{t('notifications.email_template_editor.form.subject')}</label>
              <input className="form-control" value={form.subject}
                onChange={(e) => setForm({ ...form, subject: e.target.value })} />
            </div>
          </div>
          <div className="mt-2">
            <label>{t('notifications.email_template_editor.form.body_html')}</label>
            <textarea className="form-control font-monospace" rows={8} value={form.body_html}
              onChange={(e) => setForm({ ...form, body_html: e.target.value })} />
          </div>
          <div className="mt-2">
            <label>{t('notifications.email_template_editor.form.body_text')}</label>
            <textarea className="form-control font-monospace" rows={4} value={form.body_text}
              onChange={(e) => setForm({ ...form, body_text: e.target.value })} />
          </div>
          <button type="submit" className="btn btn-success mt-2" disabled={saving}>
            {saving ? t('notifications.email_template_editor.buttons.saving') : t('notifications.email_template_editor.buttons.save')}
          </button>
        </form>
      )}

      {error && <div className="alert alert-danger">{error}</div>}

      {isLoading ? <p>{t('notifications.email_template_editor.loading')}</p> : (
        <table className="table table-sm">
          <thead><tr><th>{t('notifications.email_template_editor.table.key')}</th><th>{t('notifications.email_template_editor.table.locale')}</th><th>{t('notifications.email_template_editor.table.subject')}</th><th>{t('notifications.email_template_editor.table.version')}</th><th>{t('notifications.email_template_editor.table.actions')}</th></tr></thead>
          <tbody>
            {templates?.map((tpl) => (
              <tr key={tpl.id}>
                <td>{tpl.code}</td>
                <td>{tpl.locale}</td>
                <td>{tpl.subject}</td>
                <td>{tpl.version}</td>
                <td>
                  <button className="btn btn-sm btn-outline-danger"
                    disabled={deletingId === tpl.id}
                    onClick={() => handleDelete(tpl.id)}>{t('notifications.email_template_editor.buttons.delete')}</button>
                </td>
              </tr>
            ))}
            {templates?.length === 0 && <tr><td colSpan={5} className="text-muted text-center">{t('notifications.email_template_editor.no_templates')}</td></tr>}
          </tbody>
        </table>
      )}
    </div>
  );
}
