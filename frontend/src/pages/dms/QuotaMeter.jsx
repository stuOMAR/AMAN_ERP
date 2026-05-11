import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

/**
 * QuotaMeter — displays DMS storage quota usage.
 */
export default function QuotaMeter() {
  const { t } = useTranslation();
  const { data, isLoading } = useQuery({
    queryKey: ['dms-quotas'],
    queryFn: async () => {
      const res = await fetch('/api/dms/quotas');
      if (!res.ok) throw new Error('Failed to load');
      return res.json();
    },
  });

  if (isLoading) return <div>{t('dms.quota_meter.loading')}</div>;
  if (!data) return null;

  const pct = data.quota_mb > 0 ? ((data.used_mb / data.quota_mb) * 100).toFixed(1) : 0;
  const barClass = pct > 90 ? 'bg-danger' : pct > 70 ? 'bg-warning' : 'bg-success';

  return (
    <div className="quota-meter card p-3">
      <h4>{t('dms.quota_meter.title')}</h4>
      <div className="d-flex justify-content-between mb-1">
        <span>{data.used_mb} {t('dms.quota_meter.mb_used')}</span>
        <span>{t('dms.quota_meter.mb_remaining', { remaining: data.remaining_mb, total: data.quota_mb })}</span>
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
      <small className="text-muted mt-1">{data.document_count} {t('dms.quota_meter.documents')}</small>
    </div>
  );
}
