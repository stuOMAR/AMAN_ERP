import React, { useState, useEffect, useCallback } from 'react';
import { externalAPI } from '../../utils/api';
import '../../components/ModuleStyles.css';

import { formatShortDate } from '../../utils/dateUtils';
import { useTranslation } from 'react-i18next';
import BackButton from '../../components/common/BackButton';
import DateInput from '../../components/common/DateInput';
import { useToast } from '../../context/ToastContext'

const PERMISSION_OPTIONS = [
  { value: 'read', labelKey: 'settings.api_keys.perm_read' },
  { value: 'write', labelKey: 'settings.api_keys.perm_write' },
  { value: 'invoices', labelKey: 'settings.api_keys.perm_invoices' },
  { value: 'reports', labelKey: 'settings.api_keys.perm_reports' },
  { value: 'inventory', labelKey: 'settings.api_keys.perm_inventory' },
];

export default function ApiKeys() {
  const { t } = useTranslation();
  const { showToast } = useToast()
  const [keys, setKeys] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newKeyResult, setNewKeyResult] = useState(null);
  const [form, setForm] = useState({
    name: '',
    permissions: [],
    rate_limit_per_minute: 60,
    expires_at: '',
  });
  const [submitting, setSubmitting] = useState(false);

  const fetchKeys = useCallback(async () => {
    try {
      setLoading(true);
      const res = await externalAPI.listApiKeys();
      setKeys(res.data ?? res);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchKeys();
  }, [fetchKeys]);

  const togglePermission = (perm) => {
    setForm((prev) => ({
      ...prev,
      permissions: prev.permissions.includes(perm)
        ? prev.permissions.filter((p) => p !== perm)
        : [...prev.permissions, perm],
    }));
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    try {
      setSubmitting(true);
      let expiresInDays = null;
      if (form.expires_at) {
        const selected = new Date(`${form.expires_at}T00:00:00`);
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        if (!Number.isNaN(selected.getTime())) {
          expiresInDays = Math.max(1, Math.ceil((selected - today) / (1000 * 60 * 60 * 24)));
        }
      }
      const payload = {
        name: form.name.trim(),
        permissions: form.permissions,
        rate_limit_per_minute: Number(form.rate_limit_per_minute) || 60,
        expires_in_days: expiresInDays,
      };
      const res = await externalAPI.createApiKey(payload);
      const result = res.data ?? res;
      setNewKeyResult(result);
      setShowCreateModal(false);
      setForm({ name: '', permissions: [], rate_limit_per_minute: 60, expires_at: '' });
      fetchKeys();
    } catch (e) {
      console.error(e);
      showToast(t('settings.api_keys.error_create', 'error'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm(t('settings.api_keys.confirm_delete'))) return;
    try {
      await externalAPI.deleteApiKey(id);
      fetchKeys();
    } catch (e) {
      console.error(e);
      showToast(t('settings.api_keys.error_delete', 'error'));
    }
  };

  const formatDate = (d) => {
    if (!d) return '—';
    return formatShortDate(d);
  };

  return (
    <div className="workspace fade-in">
      <div className="workspace-header">
        <BackButton />
        <div className="header-title">
          <h1 className="workspace-title">{t('settings.api_keys.title')}</h1>
          <p className="workspace-subtitle">{t('settings.api_keys.subtitle')}</p>
        </div>
        <div className="header-actions">
          <button className="btn btn-primary" onClick={() => setShowCreateModal(true)}>
            + {t('settings.api_keys.create_new')}
          </button>
        </div>
      </div>

      {newKeyResult?.key && (
        <div
          style={{
            background: '#d4edda',
            border: '2px solid #28a745',
            borderRadius: 8,
            padding: 16,
            marginBottom: 16,
          }}
        >
          <strong>⚠️ {t('settings.api_keys.key_created_warning')}</strong>
          <pre
            style={{
              background: '#fff',
              padding: 12,
              borderRadius: 4,
              marginTop: 8,
              wordBreak: 'break-all',
              whiteSpace: 'pre-wrap',
              direction: 'ltr',
              textAlign: 'left',
            }}
          >
            {newKeyResult.key}
          </pre>
          <button className="btn btn-secondary" onClick={() => setNewKeyResult(null)}>
            {t('common.close')}
          </button>
        </div>
      )}

      {loading ? (
        <p>{t('common.loading')}</p>
      ) : keys.length === 0 ? (
        <div className="empty-state">{t('settings.api_keys.no_keys')}</div>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>{t('common.name')}</th>
              <th>{t('settings.api_keys.prefix')}</th>
              <th>{t('settings.api_keys.permissions')}</th>
              <th>{t('settings.api_keys.rate_limit')}</th>
              <th>{t('settings.api_keys.expiry_date')}</th>
              <th>{t('settings.api_keys.last_used')}</th>
              <th>{t('settings.api_keys.usage_count')}</th>
              <th>{t('common.status_title')}</th>
              <th>{t('common.actions')}</th>
            </tr>
          </thead>
          <tbody>
            {keys.map((k) => (
              <tr key={k.id}>
                <td>{k.name}</td>
                <td style={{ direction: 'ltr', fontFamily: 'monospace' }}>{k.key_prefix}</td>
                <td>
                  {(k.permissions || []).map((p) => (
                    <span key={p} className="badge badge-info" style={{ marginInlineEnd: 4 }}>
                      {t(`settings.api_keys.perm_${p}`)}
                    </span>
                  ))}
                </td>
                <td>{k.rate_limit_per_minute}</td>
                <td>{formatDate(k.expires_at)}</td>
                <td>{formatDate(k.last_used_at)}</td>
                <td>{k.usage_count ?? 0}</td>
                <td>
                  {k.is_active ? (
                    <span className="badge badge-success">{t('settings.api_keys.active')}</span>
                  ) : (
                    <span className="badge badge-danger">{t('settings.api_keys.inactive')}</span>
                  )}
                </td>
                <td>
                  <button className="btn btn-danger" onClick={() => handleDelete(k.id)}>
                    {t('common.delete')}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {showCreateModal && (
        <div className="modal-overlay" onClick={() => setShowCreateModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>{t('settings.api_keys.create_modal_title')}</h2>
            </div>
            <form onSubmit={handleCreate}>
              <div className="modal-body">
                <div className="form-group mb-3">
                  <label className="form-label">{t('common.name')}</label>
                  <input
                    className="form-input"
                    type="text"
                    value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                    required
                  />
                </div>
                <div className="form-group mb-3">
                  <label className="form-label">{t('settings.api_keys.rate_limit_per_minute')}</label>
                  <input
                    className="form-input"
                    type="number"
                    min={1}
                    value={form.rate_limit_per_minute}
                    onChange={(e) =>
                      setForm({ ...form, rate_limit_per_minute: Number(e.target.value) })
                    }
                  />
                </div>
                <div className="form-group mb-3">
                  <label className="form-label">{t('settings.api_keys.expiry_date_optional')}</label>
                  <DateInput
                    className="form-input"
                    value={form.expires_at}
                    onChange={(e) => setForm({ ...form, expires_at: e.target.value })}
                  />
                </div>
                <div className="form-group mb-3">
                  <label className="form-label">{t('settings.api_keys.permissions')}</label>
                  <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginTop: 8 }}>
                    {PERMISSION_OPTIONS.map((perm) => (
                      <label key={perm.value} className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          className="checkbox checkbox-primary"
                          checked={form.permissions.includes(perm.value)}
                          onChange={() => togglePermission(perm.value)}
                        />
                        <span className="font-medium">{t(perm.labelKey)}</span>
                      </label>
                    ))}
                  </div>
                </div>
              </div>
              <div className="modal-footer">
                <button type="submit" className="btn btn-primary" disabled={submitting}>
                  {submitting ? t('settings.api_keys.creating') : t('common.create')}
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setShowCreateModal(false)}
                >
                  {t('common.cancel')}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
