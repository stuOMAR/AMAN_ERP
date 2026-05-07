import React from 'react';
import { useQuery } from '@tanstack/react-query';

/**
 * QuotaMeter — displays DMS storage quota usage.
 */
export default function QuotaMeter() {
  const { data, isLoading } = useQuery({
    queryKey: ['dms-quotas'],
    queryFn: async () => {
      const res = await fetch('/api/dms/quotas');
      if (!res.ok) throw new Error('Failed to load');
      return res.json();
    },
  });

  if (isLoading) return <div>Loading quota...</div>;
  if (!data) return null;

  const pct = data.quota_mb > 0 ? ((data.used_mb / data.quota_mb) * 100).toFixed(1) : 0;
  const barClass = pct > 90 ? 'bg-danger' : pct > 70 ? 'bg-warning' : 'bg-success';

  return (
    <div className="quota-meter card p-3">
      <h4>Storage Quota</h4>
      <div className="d-flex justify-content-between mb-1">
        <span>{data.used_mb} MB used</span>
        <span>{data.remaining_mb} MB remaining of {data.quota_mb} MB</span>
      </div>
      <div className="progress" style={{ height: 20 }}>
        <div
          className={`progress-bar ${barClass}`}
          role="progressbar"
          style={{ width: `${Math.min(pct, 100)}%` }}
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          {pct}%
        </div>
      </div>
      <small className="text-muted mt-1">{data.document_count} documents</small>
    </div>
  );
}
