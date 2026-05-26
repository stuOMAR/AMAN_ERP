import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { RefreshCw, RotateCcw, ShieldAlert, ShieldCheck, ScanLine } from 'lucide-react';
import BackButton from '../../components/common/BackButton';
import { dmsAPI } from '../../utils/api';
import { toastEmitter } from '../../utils/toastEmitter';
import QuotaMeter from './QuotaMeter';
import QuarantineAlerts from './QuarantineAlerts';
import '../../components/ModuleStyles.css';

export default function DmsAdmin() {
  const { t } = useTranslation();
  const [refreshKey, setRefreshKey] = useState(0);
  const [stats, setStats] = useState(null);
  const [loadingStats, setLoadingStats] = useState(true);
  const [recalculating, setRecalculating] = useState(false);

  const refresh = () => setRefreshKey((value) => value + 1);

  useEffect(() => {
    let cancelled = false;
    setLoadingStats(true);
    dmsAPI.getScanStats()
      .then((res) => {
        if (!cancelled) setStats(res.data);
      })
      .catch(() => {
        if (!cancelled) setStats(null);
      })
      .finally(() => {
        if (!cancelled) setLoadingStats(false);
      });
    return () => { cancelled = true; };
  }, [refreshKey]);

  const recalculateStorage = async () => {
    setRecalculating(true);
    try {
      await dmsAPI.recalculateStorage();
      toastEmitter.emit(t('dms.admin.recalculated'), 'success');
      refresh();
    } catch (err) {
      toastEmitter.emit(err.response?.data?.detail || t('dms.errors.recalculate_failed'), 'error');
    } finally {
      setRecalculating(false);
    }
  };

  const statTiles = [
    { key: 'total', icon: ScanLine, value: stats?.total ?? 0 },
    { key: 'clean', icon: ShieldCheck, value: stats?.clean ?? 0 },
    { key: 'pending_scan', icon: RefreshCw, value: stats?.pending_scan ?? 0 },
    { key: 'quarantined', icon: ShieldAlert, value: stats?.quarantined ?? 0 },
  ];

  return (
    <div className="workspace fade-in">
      <div className="workspace-header">
        <BackButton />
        <div className="header-title">
          <h1 className="workspace-title">{t('dms.admin.title')}</h1>
          <p className="workspace-subtitle">{t('dms.admin.subtitle')}</p>
        </div>
        <div className="header-actions">
          <button className="btn btn-secondary" type="button" onClick={refresh}>
            <RefreshCw size={16} /> {t('common.refresh')}
          </button>
          <button className="btn btn-primary" type="button" onClick={recalculateStorage} disabled={recalculating}>
            <RotateCcw size={16} /> {recalculating ? t('common.loading') : t('dms.admin.recalculate')}
          </button>
        </div>
      </div>

      <div className="dashboard-grid" style={{ marginBottom: '16px' }}>
        {statTiles.map(({ key, icon: Icon, value }) => (
          <div className="stat-card" key={key}>
            <div className="stat-icon"><Icon size={20} /></div>
            <div className="stat-content">
              <div className="stat-value">{loadingStats ? '-' : value}</div>
              <div className="stat-label">{t(`dms.stats.${key}`)}</div>
            </div>
          </div>
        ))}
      </div>

      <div className="content-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px' }}>
        <section className="section-card card">
          <div className="card-body">
            <QuotaMeter refreshKey={refreshKey} />
          </div>
        </section>
        <section className="section-card card">
          <div className="card-body">
            <QuarantineAlerts refreshKey={refreshKey} onReleased={refresh} />
          </div>
        </section>
      </div>
    </div>
  );
}
