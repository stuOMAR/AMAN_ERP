import React, { useState, useEffect, useCallback } from 'react';
import { externalAPI } from '../../utils/api';
import '../../components/ModuleStyles.css';

import { formatShortDate } from '../../utils/dateUtils';
import { useTranslation } from 'react-i18next';
import BackButton from '../../components/common/BackButton';
import { useToast } from '../../context/ToastContext'
import { hasPermission } from '../../utils/auth';

const EVENT_LABELS = {
  'invoice.created': 'settings.webhooks.evt_invoice_created',
  'invoice.paid': 'settings.webhooks.evt_invoice_paid',
  'invoice.cancelled': 'settings.webhooks.evt_invoice_cancelled',
  'order.created': 'settings.webhooks.evt_order_created',
  'order.confirmed': 'settings.webhooks.evt_order_confirmed',
  'order.delivered': 'settings.webhooks.evt_order_delivered',
  'payment.received': 'settings.webhooks.evt_payment_received',
  'payment.refunded': 'settings.webhooks.evt_payment_refunded',
  'inventory.low_stock': 'settings.webhooks.evt_inventory_low_stock',
  'inventory.adjustment': 'settings.webhooks.evt_inventory_adjustment',
  'purchase.created': 'settings.webhooks.evt_purchase_created',
  'purchase.approved': 'settings.webhooks.evt_purchase_approved',
  'employee.leave_request': 'settings.webhooks.evt_employee_leave',
  'employee.attendance': 'settings.webhooks.evt_employee_attendance',
  'ticket.created': 'settings.webhooks.evt_ticket_created',
  'ticket.resolved': 'settings.webhooks.evt_ticket_resolved',
  'opportunity.won': 'settings.webhooks.evt_opportunity_won',
  'opportunity.lost': 'settings.webhooks.evt_opportunity_lost',
  'opportunity.stage_changed': 'settings.webhooks.evt_opportunity_stage',
};

const EMPTY_FORM = {
  name: '',
  url: '',
  secret: '',
  events: [],
  retry_count: 3,
  timeout_seconds: 30,
};

export default function Webhooks() {
  const { t } = useTranslation();
  const { showToast } = useToast()
  const [webhooks, setWebhooks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [availableEvents, setAvailableEvents] = useState([]);
  const [showFormModal, setShowFormModal] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [submitting, setSubmitting] = useState(false);
  const [logsWebhook, setLogsWebhook] = useState(null);
  const [logs, setLogs] = useState([]);
  const [logsLoading, setLogsLoading] = useState(false);
  const canManageWebhooks = hasPermission(['settings.manage', 'admin']);

  const fetchWebhooks = useCallback(async () => {
    try {
      setLoading(true);
      const res = await externalAPI.listWebhooks();
      setWebhooks(res.data ?? res);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchEvents = useCallback(async () => {
    try {
      const res = await externalAPI.getWebhookEvents();
      setAvailableEvents(res.data ?? res);
    } catch (e) {
      console.error(e);
    }
  }, []);

  useEffect(() => {
    fetchWebhooks();
    fetchEvents();
  }, [fetchWebhooks, fetchEvents]);

  const openCreate = () => {
    setEditingId(null);
    setForm({ ...EMPTY_FORM });
    setShowFormModal(true);
  };

  const openEdit = (wh) => {
    setEditingId(wh.id);
    setForm({
      name: wh.name || '',
      url: wh.url || '',
      events: wh.events || [],
      retry_count: wh.retry_count ?? 3,
      timeout_seconds: wh.timeout_seconds ?? 30,
    });
    setShowFormModal(true);
  };

  const toggleEvent = (evt) => {
    setForm((prev) => ({
      ...prev,
      events: prev.events.includes(evt)
        ? prev.events.filter((e) => e !== evt)
        : [...prev.events, evt],
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      setSubmitting(true);
      if (editingId) {
        await externalAPI.updateWebhook(editingId, form);
      } else {
        await externalAPI.createWebhook(form);
      }
      setShowFormModal(false);
      setForm({ ...EMPTY_FORM });
      setEditingId(null);
      fetchWebhooks();
    } catch (err) {
      console.error(err);
      showToast(t('settings.webhooks.error_save', 'error'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm(t('settings.webhooks.confirm_delete'))) return;
    try {
      await externalAPI.deleteWebhook(id);
      fetchWebhooks();
    } catch (e) {
      console.error(e);
      showToast(t('settings.webhooks.error_delete', 'error'));
    }
  };

  const handleToggleActive = async (wh) => {
    try {
      await externalAPI.updateWebhook(wh.id, { is_active: !wh.is_active });
      fetchWebhooks();
    } catch (e) {
      console.error(e);
    }
  };

  const openLogs = async (wh) => {
    setLogsWebhook(wh);
    setLogsLoading(true);
    try {
      const res = await externalAPI.getWebhookLogs(wh.id);
      setLogs(res.data ?? res);
    } catch (e) {
      console.error(e);
      setLogs([]);
    } finally {
      setLogsLoading(false);
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
          <h1 className="workspace-title">{t('settings.webhooks.title')}</h1>
          <p className="workspace-subtitle">{t('settings.webhooks.subtitle')}</p>
        </div>
        {canManageWebhooks && (
          <div className="header-actions">
            <button className="btn btn-primary" onClick={openCreate}>
              + {t('settings.webhooks.create_new')}
            </button>
          </div>
        )}
      </div>

      {loading ? (
        <p>{t('common.loading')}</p>
      ) : webhooks.length === 0 ? (
        <div className="empty-state">{t('settings.webhooks.no_webhooks')}</div>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>{t('common.name')}</th>
              <th>{t('settings.webhooks.url')}</th>
              <th>{t('settings.webhooks.events')}</th>
              <th>{t('settings.webhooks.retries')}</th>
              <th>{t('settings.webhooks.timeout')}</th>
              <th>{t('common.status_title')}</th>
              <th>{t('common.actions')}</th>
            </tr>
          </thead>
          <tbody>
            {webhooks.map((wh) => (
              <tr key={wh.id}>
                <td>{wh.name}</td>
                <td style={{ direction: 'ltr', maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {wh.url}
                </td>
                <td>
                  {(wh.events || []).map((ev) => (
                    <span key={ev} className="badge badge-info" style={{ marginInlineEnd: 4, marginBottom: 2, display: 'inline-block' }}>
                      {t(EVENT_LABELS[ev] || `settings.webhooks.evt_${ev.replace('.', '_')}`, ev)}
                    </span>
                  ))}
                </td>
                <td>{wh.retry_count}</td>
                <td>{wh.timeout_seconds}{t('settings.webhooks.seconds_abbr')}</td>
                <td>
                  {wh.is_active ? (
                    <span className="badge badge-success">{t('settings.webhooks.active')}</span>
                  ) : (
                    <span className="badge badge-danger">{t('settings.webhooks.inactive')}</span>
                  )}
                </td>
                <td style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                  {canManageWebhooks && (
                    <button className="btn btn-secondary" onClick={() => openEdit(wh)}>
                      {t('common.edit')}
                    </button>
                  )}
                  <button className="btn btn-secondary" onClick={() => openLogs(wh)}>
                    {t('settings.webhooks.logs')}
                  </button>
                  {canManageWebhooks && (
                    <button
                      className="btn btn-secondary"
                      onClick={() => handleToggleActive(wh)}
                    >
                      {wh.is_active ? t('settings.webhooks.deactivate') : t('settings.webhooks.activate')}
                    </button>
                  )}
                  {canManageWebhooks && (
                    <button className="btn btn-danger" onClick={() => handleDelete(wh.id)}>
                      {t('common.delete')}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* Create / Edit Modal */}
      {showFormModal && (
        <div className="modal-overlay" onClick={() => setShowFormModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>{editingId ? t('settings.webhooks.edit_title') : t('settings.webhooks.create_new')}</h2>
            </div>
            <form onSubmit={handleSubmit}>
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
                  <label className="form-label">{t('settings.webhooks.url_label')}</label>
                  <input
                    className="form-input"
                    type="url"
                    value={form.url}
                    onChange={(e) => setForm({ ...form, url: e.target.value })}
                    required
                    style={{ direction: 'ltr' }}
                  />
                </div>
                <div className="form-group mb-3">
                  <label className="form-label">{t('settings.webhooks.retry_count')}</label>
                  <input
                    className="form-input"
                    type="number"
                    min={0}
                    value={form.retry_count}
                    onChange={(e) => setForm({ ...form, retry_count: Number(e.target.value) })}
                  />
                </div>
                <div className="form-group mb-3">
                  <label className="form-label">{t('settings.webhooks.timeout_seconds')}</label>
                  <input
                    className="form-input"
                    type="number"
                    min={1}
                    value={form.timeout_seconds}
                    onChange={(e) => setForm({ ...form, timeout_seconds: Number(e.target.value) })}
                  />
                </div>
                <div className="form-group mb-3">
                  <label className="form-label">{t('settings.webhooks.events')}</label>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12, marginTop: 8 }}>
                    {availableEvents.length === 0 && <span className="text-base-content/50">{t('settings.webhooks.no_events')}</span>}
                    {availableEvents.map((evt) => {
                      const evtValue = typeof evt === 'string' ? evt : evt.value ?? evt.name ?? evt;
                      return (
                        <label key={evtValue} className="flex items-center gap-2 cursor-pointer">
                          <input
                            type="checkbox"
                            className="checkbox checkbox-primary"
                            checked={form.events.includes(evtValue)}
                            onChange={() => toggleEvent(evtValue)}
                          />
                          <span className="font-medium text-sm">{t(EVENT_LABELS[evtValue] || `settings.webhooks.evt_${evtValue.replace('.', '_')}`, evtValue)}</span>
                        </label>
                      );
                    })}
                  </div>
                </div>
              </div>
              <div className="modal-footer">
                <button type="submit" className="btn btn-primary" disabled={submitting}>
                  {submitting ? t('common.saving') : editingId ? t('common.update') : t('common.create')}
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setShowFormModal(false)}
                >
                  {t('common.cancel')}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Logs Modal */}
      {logsWebhook && (
        <div className="modal-overlay" onClick={() => setLogsWebhook(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 800 }}>
            <div className="modal-header">
              <h2>{t('settings.webhooks.logs_for')}: {logsWebhook.name}</h2>
            </div>
            <div className="modal-body">
              {logsLoading ? (
                <p>{t('common.loading')}</p>
              ) : logs.length === 0 ? (
                <div className="empty-state">{t('settings.webhooks.no_logs')}</div>
              ) : (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>{t('settings.webhooks.event')}</th>
                      <th>{t('settings.webhooks.status_code')}</th>
                      <th>{t('settings.webhooks.result')}</th>
                      <th>{t('settings.webhooks.attempt')}</th>
                      <th>{t('common.date')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {logs.map((log, idx) => (
                      <tr key={log.id ?? idx}>
                        <td>{log.event}</td>
                        <td style={{ direction: 'ltr' }}>{log.status_code ?? '—'}</td>
                        <td>
                          {log.success ? (
                            <span className="badge badge-success">{t('settings.webhooks.success')}</span>
                          ) : (
                            <span className="badge badge-danger">{t('settings.webhooks.failed')}</span>
                          )}
                        </td>
                        <td>{log.attempt ?? '—'}</td>
                        <td>{formatDate(log.created_at ?? log.timestamp)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setLogsWebhook(null)}>
                {t('common.close')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
