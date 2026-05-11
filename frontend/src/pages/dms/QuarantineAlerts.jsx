import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

/**
 * QuarantineAlerts — lists quarantined documents.
 */
export default function QuarantineAlerts() {
  const { t } = useTranslation();
  const { data: items, isLoading } = useQuery({
    queryKey: ['dms-quarantine'],
    queryFn: async () => {
      const res = await fetch('/api/dms/quarantine');
      if (!res.ok) throw new Error('Failed to load');
      return res.json();
    },
  });

  if (isLoading) return <div>{t('dms.quarantine.loading')}</div>;

  return (
    <div className="quarantine-alerts">
      <h3>{t('dms.quarantine.title')}</h3>
      {items?.length === 0 ? (
        <p className="text-muted">{t('dms.quarantine.no_documents')}</p>
      ) : (
        <table className="table table-sm table-danger">
          <thead>
            <tr>
              <th>{t('dms.quarantine.table.id')}</th>
              <th>{t('dms.quarantine.table.filename')}</th>
              <th>{t('dms.quarantine.table.size')}</th>
              <th>{t('dms.quarantine.table.scanned')}</th>
              <th>{t('dms.quarantine.table.engine')}</th>
            </tr>
          </thead>
          <tbody>
            {items?.map((item) => (
              <tr key={item.id}>
                <td>{item.id}</td>
                <td>{item.filename}</td>
                <td>{(item.file_size / 1024).toFixed(1)} KB</td>
                <td>{item.scanned_at || '—'}</td>
                <td>{item.scan_engine || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
