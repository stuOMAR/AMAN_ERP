import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

/**
 * NotificationQueueMonitor — paginated queue with state/channel filter + reprocess.
 */
export default function NotificationQueueMonitor() {
  const { t } = useTranslation();
  const [state, setState] = useState('');
  const [channel, setChannel] = useState('');
  const queryClient = useQueryClient();

  const { data: queue, isLoading } = useQuery({
    queryKey: ['notif-queue', state, channel],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (state) params.set('state', state);
      if (channel) params.set('channel', channel);
      const res = await fetch(`/api/notifications/queue?${params}`);
      if (!res.ok) throw new Error('Failed to load');
      return res.json();
    },
  });

  const retryMutation = useMutation({
    mutationFn: async (id) => {
      const res = await fetch(`/api/notifications/queue/${id}/retry`, { method: 'POST' });
      if (!res.ok) throw new Error('Retry failed');
      return res.json();
    },
    onSuccess: () => queryClient.invalidateQueries(['notif-queue']),
  });

  return (
    <div className="notif-queue-monitor">
      <h2>{t('notifications.queue_monitor.title')}</h2>

      <div className="filters d-flex gap-2 mb-3">
        <select className="form-control" style={{ width: 150 }} value={state} onChange={(e) => setState(e.target.value)}>
          <option value="">{t('notifications.queue_monitor.filters.all_states')}</option>
          <option value="pending">{t('notifications.queue_monitor.filters.pending')}</option>
          <option value="sending">{t('notifications.queue_monitor.filters.sending')}</option>
          <option value="sent">{t('notifications.queue_monitor.filters.sent')}</option>
          <option value="failed">{t('notifications.queue_monitor.filters.failed')}</option>
          <option value="dlq">{t('notifications.queue_monitor.filters.dlq')}</option>
        </select>
        <select className="form-control" style={{ width: 150 }} value={channel} onChange={(e) => setChannel(e.target.value)}>
          <option value="">{t('notifications.queue_monitor.filters.all_channels')}</option>
          <option value="email">{t('notifications.queue_monitor.filters.email')}</option>
          <option value="sms">{t('notifications.queue_monitor.filters.sms')}</option>
          <option value="push">{t('notifications.queue_monitor.filters.push')}</option>
          <option value="in_app">{t('notifications.queue_monitor.filters.in_app')}</option>
          <option value="webhook">{t('notifications.queue_monitor.filters.webhook')}</option>
        </select>
      </div>

      {isLoading ? <p>{t('notifications.queue_monitor.loading')}</p> : (
        <table className="table table-sm">
          <thead>
            <tr>
              <th>{t('notifications.queue_monitor.table.id')}</th><th>{t('notifications.queue_monitor.table.event')}</th><th>{t('notifications.queue_monitor.table.channel')}</th><th>{t('notifications.queue_monitor.table.recipient')}</th>
              <th>{t('notifications.queue_monitor.table.state')}</th><th>{t('notifications.queue_monitor.table.attempts')}</th><th>{t('notifications.queue_monitor.table.created')}</th><th>{t('notifications.queue_monitor.table.actions')}</th>
            </tr>
          </thead>
          <tbody>
            {queue?.map((n) => (
              <tr key={n.id} className={n.state === 'dlq' ? 'table-danger' : ''}>
                <td>{n.id}</td>
                <td>{n.event_type}</td>
                <td>{n.channel}</td>
                <td>{n.recipient}</td>
                <td><span className={`badge bg-${n.state === 'sent' ? 'success' : n.state === 'dlq' ? 'danger' : 'warning'}`}>{n.state}</span></td>
                <td>{n.attempts}</td>
                <td>{n.created_at}</td>
                <td>
                  {(n.state === 'failed' || n.state === 'dlq') && (
                    <button className="btn btn-sm btn-outline-primary" onClick={() => retryMutation.mutate(n.id)}>
                      {t('notifications.queue_monitor.buttons.retry')}
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {queue?.length === 0 && <tr><td colSpan={8} className="text-center text-muted">{t('notifications.queue_monitor.no_entries')}</td></tr>}
          </tbody>
        </table>
      )}
    </div>
  );
}
