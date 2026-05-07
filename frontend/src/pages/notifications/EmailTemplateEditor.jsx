import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

/**
 * EmailTemplateEditor — CRUD for email templates with Jinja preview + locale tabs.
 */
export default function EmailTemplateEditor() {
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
      <h2>Email Templates</h2>

      <button className="btn btn-primary mb-3" onClick={() => setShowForm(!showForm)}>
        {showForm ? 'Cancel' : 'New Template'}
      </button>

      {showForm && (
        <form className="card p-3 mb-3" onSubmit={(e) => { e.preventDefault(); createMutation.mutate(form); }}>
          <div className="row">
            <div className="col-md-4">
              <label>Code</label>
              <input className="form-control" value={form.code} required
                onChange={(e) => setForm({ ...form, code: e.target.value })} />
            </div>
            <div className="col-md-2">
              <label>Locale</label>
              <select className="form-control" value={form.locale}
                onChange={(e) => setForm({ ...form, locale: e.target.value })}>
                <option value="en">English</option>
                <option value="ar">Arabic</option>
              </select>
            </div>
            <div className="col-md-6">
              <label>Subject</label>
              <input className="form-control" value={form.subject}
                onChange={(e) => setForm({ ...form, subject: e.target.value })} />
            </div>
          </div>
          <div className="mt-2">
            <label>Body HTML (Jinja2)</label>
            <textarea className="form-control font-monospace" rows={8} value={form.body_html}
              onChange={(e) => setForm({ ...form, body_html: e.target.value })} />
          </div>
          <div className="mt-2">
            <label>Body Text (Jinja2)</label>
            <textarea className="form-control font-monospace" rows={4} value={form.body_text}
              onChange={(e) => setForm({ ...form, body_text: e.target.value })} />
          </div>
          {createMutation.isError && <div className="alert alert-danger mt-2">{createMutation.error.message}</div>}
          <button type="submit" className="btn btn-success mt-2" disabled={createMutation.isLoading}>
            {createMutation.isLoading ? 'Saving...' : 'Save Template'}
          </button>
        </form>
      )}

      {isLoading ? <p>Loading...</p> : (
        <table className="table table-sm">
          <thead><tr><th>Code</th><th>Locale</th><th>Subject</th><th>Version</th><th>Actions</th></tr></thead>
          <tbody>
            {templates?.map((t) => (
              <tr key={t.id}>
                <td>{t.code}</td>
                <td>{t.locale}</td>
                <td>{t.subject}</td>
                <td>{t.version}</td>
                <td>
                  <button className="btn btn-sm btn-outline-danger"
                    onClick={() => deleteMutation.mutate(t.id)}>Delete</button>
                </td>
              </tr>
            ))}
            {templates?.length === 0 && <tr><td colSpan={5} className="text-muted text-center">No templates</td></tr>}
          </tbody>
        </table>
      )}
    </div>
  );
}
