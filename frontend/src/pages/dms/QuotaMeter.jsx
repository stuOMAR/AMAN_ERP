import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { dmsAPI } from '../../utils/api';

/**
 * QuotaMeter — displays DMS storage quota usage.
 */
export default function QuotaMeter({ refreshKey = 0 }) {
  const { t } = useTranslation();
  const [data, setData] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setError('');
    dmsAPI.getQuotas()
      .then((res) => {
        if (!cancelled) setData(res.data);
      })
      .catch((err) => {
        if (!cancelled) setError(err.response?.data?.detail || t('dms.errors.load_failed'));
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => { cancelled = true; };
  }, [refreshKey, t]);

  if (isLoading) return <div>{t('dms.quota_meter.loading')}</div>;
  if (error) return <div className="alert alert-danger">{error}</div>;
  if (!data) return null;

  const pct = data.quota_mb > 0 ? Number(((data.used_mb / data.quota_mb) * 100).toFixed(1)) : 0;
  const barClass = pct > 90 ? 'bg-danger' : pct > 70 ? 'bg-warning' : 'bg-success';

  return (
    <div className="quota-meter">
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
