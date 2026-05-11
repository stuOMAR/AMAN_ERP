import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

/**
 * EmailTemplateEditor — CRUD for email templates with Jinja preview + locale tabs.
 */
export default function EmailTemplateEditor() {
  const { t } = useTranslation();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    code: '', locale: 'en', subject: '', body_html: '', body_text: '',
  });
  const queryClient = useQueryClient();

  const { data: templates, isLoading } = useQuery({
    queryKey: ['email-templates'],
    queryFn: async () => {
      const res = await fetch('/api/notifications/templates');
      if (!res.ok) throw new Error('Failed to load');
      return res.json();
    },
  });

  const createMutation = useMutation({
    mutationFn: async (data) => {
      const res = await fetch('/api/notifications/templates', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed');
      }
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries(['email-templates']);
      setShowForm(false);
      setForm({ code: '', locale: 'en', subject: '', body_html: '', body_text: '' });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (id) => {
      const res = await fetch(`/api/notifications/templates/${id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('Delete failed');
      return res.json();
    },
    onSuccess: () => queryClient.invalidateQueries(['email-templates']),
  });

  return (
    <div className="email-template-editor">
      <h2>{t('notifications.email_template_editor.title')}</h2>

      <button className="btn btn-primary mb-3" onClick={() => setShowForm(!showForm)}>
        {showForm ? t('notifications.email_template_editor.buttons.cancel') : t('notifications.email_template_editor.buttons.new_template')}
      </button>

      {showForm && (
        <form className="card p-3 mb-3" onSubmit={(e) => { e.preventDefault(); createMutation.mutate(form); }}>
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
          {createMutation.isError && <div className="alert alert-danger mt-2">{createMutation.error.message}</div>}
          <button type="submit" className="btn btn-success mt-2" disabled={createMutation.isLoading}>
            {createMutation.isLoading ? t('notifications.email_template_editor.buttons.saving') : t('notifications.email_template_editor.buttons.save')}
          </button>
        </form>
      )}

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
                    onClick={() => deleteMutation.mutate(tpl.id)}>{t('notifications.email_template_editor.buttons.delete')}</button>
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
