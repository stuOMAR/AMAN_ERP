import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import BackButton from '../../components/common/BackButton';

export default function HealthDetailed() {
    const { t, i18n } = useTranslation();
    const [health, setHealth] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const fetchHealth = async () => {
        setLoading(true);
        try {
            const response = await fetch('/health/detailed');
            const data = await response.json();
            setHealth(data);
            setError(null);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchHealth();
        const interval = setInterval(fetchHealth, 15000);
        return () => clearInterval(interval);
    }, []);

    const getStatusColor = (status) => {
        switch (status) {
            case 'ok': return '#10B981';
            case 'degraded': return '#F59E0B';
            case 'down': return '#EF4444';
            default: return '#6B7280';
        }
    };

    const getStatusIcon = (status) => {
        switch (status) {
            case 'ok': return '✅';
            case 'degraded': return '⚠️';
            case 'down': return '❌';
            default: return '❓';
        }
    };

    const adapters = health?.adapters || {};
    const adapterList = Object.entries(adapters);

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">🏥 {t('health.title', 'صحة النظام')}</h1>
                    <p className="workspace-subtitle">{t('health.subtitle', 'حالة جميع مكونات النظام')}</p>
                </div>
                <button className="btn btn-secondary" onClick={fetchHealth}>
                    🔄 {t('common.refresh', 'تحديث')}
                </button>
            </div>

            <div className="metrics-grid" style={{ marginBottom: '24px' }}>
                <div className="metric-card" style={{ borderLeft: `4px solid ${getStatusColor(health?.status)}` }}>
                    <div className="metric-label">{t('health.metrics.overall', 'الحالة العامة')}</div>
                    <div className="metric-value" style={{ color: getStatusColor(health?.status) }}>
                        {getStatusIcon(health?.status)} {health?.status?.toUpperCase() || '---'}
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('health.metrics.adapters', 'المكونات')}</div>
                    <div className="metric-value text-primary">{adapterList.length}</div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('health.metrics.healthy', 'السليمة')}</div>
                    <div className="metric-value text-success">
                        {adapterList.filter(([, a]) => a.status === 'ok').length}
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('health.metrics.issues', 'المشاكل')}</div>
                    <div className="metric-value text-danger">
                        {adapterList.filter(([, a]) => a.status !== 'ok').length}
                    </div>
                </div>
            </div>

            {loading && !health ? (
                <div className="section-card" style={{ padding: '40px', textAlign: 'center' }}>
                    ⏳ {t('common.loading', 'جاري التحميل...')}
                </div>
            ) : error ? (
                <div className="section-card" style={{ padding: '20px', textAlign: 'center', color: 'var(--danger)' }}>
                    ❌ {error}
                </div>
            ) : (
                <div className="modules-grid">
                    {adapterList.map(([name, adapter]) => (
                        <div key={name} className="section-card" style={{
                            borderTop: `4px solid ${getStatusColor(adapter.status)}`
                        }}>
                            <h3 className="section-title" style={{ color: getStatusColor(adapter.status) }}>
                                {getStatusIcon(adapter.status)} {name.toUpperCase()}
                            </h3>
                            <div style={{ padding: '0 16px 16px' }}>
                                <div style={{
                                    display: 'grid',
                                    gridTemplateColumns: '1fr 1fr',
                                    gap: '12px'
                                }}>
                                    <div>
                                        <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '4px' }}>
                                            {t('health.adapter.status', 'الحالة')}
                                        </div>
                                        <div style={{
                                            fontWeight: '600',
                                            color: getStatusColor(adapter.status)
                                        }}>
                                            {adapter.status?.toUpperCase()}
                                        </div>
                                    </div>
                                    <div>
                                        <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '4px' }}>
                                            {t('health.adapter.latency', 'زمن الاستجابة')}
                                        </div>
                                        <div style={{ fontWeight: '600' }}>
                                            {adapter.latency_ms?.toFixed(2)} ms
                                        </div>
                                    </div>
                                    <div>
                                        <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '4px' }}>
                                            {t('health.adapter.last_success', 'آخر نجاح')}
                                        </div>
                                        <div style={{ fontSize: '13px' }}>
                                            {adapter.last_success_at
                                                ? new Date(adapter.last_success_at).toLocaleString(i18n.language === 'ar' ? 'ar-SA' : 'en-US')
                                                : '---'
                                            }
                                        </div>
                                    </div>
                                    <div>
                                        <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '4px' }}>
                                            {t('health.adapter.last_error', 'آخر خطأ')}
                                        </div>
                                        <div style={{
                                            fontSize: '13px',
                                            color: adapter.last_error ? 'var(--danger)' : 'var(--text-secondary)'
                                        }}>
                                            {adapter.last_error || t('health.adapter.none', 'لا يوجد')}
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
