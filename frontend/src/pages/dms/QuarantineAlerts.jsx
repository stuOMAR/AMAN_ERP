import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { dmsAPI } from '../../utils/api';
import { toastEmitter } from '../../utils/toastEmitter';

/**
 * QuarantineAlerts — lists quarantined documents.
 */
export default function QuarantineAlerts({ refreshKey = 0, onReleased }) {
  const { t } = useTranslation();
  const [items, setItems] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [releasingId, setReleasingId] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setError('');
    dmsAPI.listQuarantine({ limit: 100 })
      .then((res) => {
        if (!cancelled) setItems(Array.isArray(res.data) ? res.data : []);
      })
      .catch((err) => {
        if (!cancelled) setError(err.response?.data?.detail || t('dms.errors.load_failed'));
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => { cancelled = true; };
  }, [refreshKey, t]);

  const releaseDocument = async (id) => {
    setReleasingId(id);
    try {
      await dmsAPI.releaseQuarantined(id);
      toastEmitter.emit(t('dms.quarantine.released'), 'success');
      setItems((prev) => prev.filter((item) => item.id !== id));
      onReleased?.();
    } catch (err) {
      toastEmitter.emit(err.response?.data?.detail || t('dms.errors.release_failed'), 'error');
    } finally {
      setReleasingId(null);
    }
  };

  const formatSize = (bytes) => {
    const value = Number(bytes || 0);
    if (value < 1024) return `${value} B`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  };

  if (isLoading) return <div>{t('dms.quarantine.loading')}</div>;
  if (error) return <div className="alert alert-danger">{error}</div>;

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
              <th>{t('common.actions')}</th>
            </tr>
          </thead>
          <tbody>
            {items?.map((item) => (
              <tr key={item.id}>
                <td>{item.id}</td>
                <td>{item.filename}</td>
                <td>{formatSize(item.file_size)}</td>
                <td>{item.scanned_at || '-'}</td>
                <td>{item.scan_engine || '-'}</td>
                <td>
                  <button
                    className="btn btn-sm btn-secondary"
                    type="button"
                    disabled={releasingId === item.id}
                    onClick={() => releaseDocument(item.id)}
                  >
                    {releasingId === item.id ? t('common.loading') : t('dms.quarantine.release')}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
