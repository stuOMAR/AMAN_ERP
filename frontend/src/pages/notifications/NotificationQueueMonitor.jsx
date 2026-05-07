import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

/**
 * NotificationQueueMonitor — paginated queue with state/channel filter + reprocess.
 */
export default function NotificationQueueMonitor() {
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
      <h2>Notification Queue</h2>

      <div className="filters d-flex gap-2 mb-3">
        <select className="form-control" style={{ width: 150 }} value={state} onChange={(e) => setState(e.target.value)}>
          <option value="">All States</option>
          <option value="pending">Pending</option>
          <option value="sending">Sending</option>
          <option value="sent">Sent</option>
          <option value="failed">Failed</option>
          <option value="dlq">DLQ</option>
        </select>
        <select className="form-control" style={{ width: 150 }} value={channel} onChange={(e) => setChannel(e.target.value)}>
          <option value="">All Channels</option>
          <option value="email">Email</option>
          <option value="sms">SMS</option>
          <option value="push">Push</option>
          <option value="in_app">In-App</option>
          <option value="webhook">Webhook</option>
        </select>
      </div>

      {isLoading ? <p>Loading...</p> : (
        <table className="table table-sm">
          <thead>
            <tr>
              <th>ID</th><th>Event</th><th>Channel</th><th>Recipient</th>
              <th>State</th><th>Attempts</th><th>Created</th><th>Actions</th>
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
                      Retry
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {queue?.length === 0 && <tr><td colSpan={8} className="text-center text-muted">No entries</td></tr>}
          </tbody>
        </table>
      )}
    </div>
  );
}
