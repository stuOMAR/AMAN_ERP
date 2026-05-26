import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import useApi from '../../hooks/useApi';
import BackButton from '../../components/common/BackButton';
import api from '../../services/apiClient';

const KPI_COMPARISON_OPS = [
    { value: 'lt', label: '<' },
    { value: 'lte', label: '≤' },
    { value: 'gt', label: '>' },
    { value: 'gte', label: '≥' },
    { value: 'eq', label: '=' },
];

const CHANNEL_OPTIONS = [
    { value: 'email', icon: '📧' },
    { value: 'sms', icon: '📱' },
    { value: 'push', icon: '🔔' },
    { value: 'in_app', icon: '📲' },
    { value: 'webhook', icon: '🔗' },
];

export default function KpiAdmin() {
    const { t, i18n } = useTranslation();
    const navigate = useNavigate();
    const { data: kpis, loading, error, refetch } = useApi('/kpi/definitions');
    const [showForm, setShowForm] = useState(false);
    const [form, setForm] = useState({
        kpi_code: '',
        metric_source: 'report_key',
        metric_reference: '',
        threshold_value: '',
        comparison_op: 'gt',
        channels: ['in_app'],
        evaluation_interval_minutes: 15,
    });

    const handleSubmit = async (e) => {
        e.preventDefault();
        try {
            const response = await api.post('/kpi/definitions', {
                ...form,
                threshold_value: form.threshold_value,
            });
            if (response.status >= 200 && response.status < 300) {
                setShowForm(false);
                refetch();
                setForm({
                    kpi_code: '',
                    metric_source: 'report_key',
                    metric_reference: '',
                    threshold_value: '',
                    comparison_op: 'gt',
                    channels: ['in_app'],
                    evaluation_interval_minutes: 15,
                });
            }
        } catch (err) {
            console.error('Failed to create KPI:', err);
        }
    };

    const kpiList = kpis || [];
    const activeCount = kpiList.filter(k => k.is_active).length;

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">🎯 {t('kpi_admin.title', 'إدارة مؤشرات الأداء')}</h1>
                    <p className="workspace-subtitle">{t('kpi_admin.subtitle', 'إنشاء ومراقبة مؤشرات الأداء الرئيسية')}</p>
                </div>
            </div>

            <div className="metrics-grid" style={{ marginBottom: '24px' }}>
                <div className="metric-card">
                    <div className="metric-label">{t('kpi_admin.metrics.total', 'إجمالي المؤشرات')}</div>
                    <div className="metric-value text-primary">{kpiList.length}</div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('kpi_admin.metrics.active', 'النشطة')}</div>
                    <div className="metric-value text-success">{activeCount}</div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('kpi_admin.metrics.inactive', 'المعطلة')}</div>
                    <div className="metric-value text-secondary">{kpiList.length - activeCount}</div>
                </div>
            </div>

            <div className="section-card" style={{ marginBottom: '24px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '16px' }}>
                    <h3 className="section-title" style={{ margin: 0, borderBottom: 'none', paddingBottom: 0 }}>
                        ⚡ {t('kpi_admin.quick_actions', 'إجراءات سريعة')}
                    </h3>
                    <button
                        className="btn btn-primary"
                        onClick={() => setShowForm(!showForm)}
                    >
                        {showForm ? '✕ ' + t('common.cancel', 'إلغاء') : '+ ' + t('kpi_admin.add_kpi', 'إضافة مؤشر')}
                    </button>
                </div>
            </div>

            {showForm && (
                <div className="section-card" style={{ marginBottom: '24px', borderTop: '4px solid #3B82F6' }}>
                    <h3 className="section-title" style={{ color: '#3B82F6' }}>
                        📝 {t('kpi_admin.new_kpi', 'مؤشر جديد')}
                    </h3>
                    <form onSubmit={handleSubmit} style={{ padding: '0 16px 16px' }}>
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))', gap: '16px' }}>
                            <div className="form-group">
                                <label className="form-label">{t('kpi_admin.form.code', 'رمز المؤشر')} *</label>
                                <input
                                    type="text"
                                    className="form-input"
                                    value={form.kpi_code}
                                    onChange={(e) => setForm({ ...form, kpi_code: e.target.value })}
                                    placeholder="e.g. operating_margin"
                                    pattern="[a-z0-9_]+"
                                    required
                                />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('kpi_admin.form.source', 'مصدر القياس')} *</label>
                                <select
                                    className="form-input"
                                    value={form.metric_source}
                                    onChange={(e) => setForm({ ...form, metric_source: e.target.value })}
                                >
                                    <option value="report_key">📊 {t('kpi_admin.form.report_key', 'مفتاح التقرير')}</option>
                                    <option value="classifier_category">📁 {t('kpi_admin.form.classifier', 'فئة التصنيف')}</option>
                                </select>
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('kpi_admin.form.reference', 'المرجع')} *</label>
                                <input
                                    type="text"
                                    className="form-input"
                                    value={form.metric_reference}
                                    onChange={(e) => setForm({ ...form, metric_reference: e.target.value })}
                                    placeholder="e.g. revenue_total"
                                    required
                                />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('kpi_admin.form.threshold', 'الحد')} *</label>
                                <input
                                    type="number"
                                    step="0.01"
                                    className="form-input"
                                    value={form.threshold_value}
                                    onChange={(e) => setForm({ ...form, threshold_value: e.target.value })}
                                    placeholder="100000"
                                    required
                                />
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('kpi_admin.form.operator', 'المعامل')}</label>
                                <select
                                    className="form-input"
                                    value={form.comparison_op}
                                    onChange={(e) => setForm({ ...form, comparison_op: e.target.value })}
                                >
                                    {KPI_COMPARISON_OPS.map((op) => (
                                        <option key={op.value} value={op.value}>{op.label}</option>
                                    ))}
                                </select>
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('kpi_admin.form.interval', 'فورة التقييم (دقائق)')}</label>
                                <input
                                    type="number"
                                    className="form-input"
                                    value={form.evaluation_interval_minutes}
                                    onChange={(e) => setForm({ ...form, evaluation_interval_minutes: parseInt(e.target.value) })}
                                    min="5"
                                />
                            </div>
                        </div>
                        <div className="form-group" style={{ marginTop: '16px' }}>
                            <label className="form-label">{t('kpi_admin.form.channels', 'قنوات الإشعار')}</label>
                            <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
                                {CHANNEL_OPTIONS.map((ch) => (
                                    <label key={ch.value} style={{
                                        display: 'flex', alignItems: 'center', gap: '6px',
                                        padding: '8px 16px', borderRadius: 'var(--radius)',
                                        border: '1px solid var(--border-color)',
                                        background: form.channels.includes(ch.value) ? 'var(--bg-hover)' : 'var(--bg-surface)',
                                        cursor: 'pointer'
                                    }}>
                                        <input
                                            type="checkbox"
                                            checked={form.channels.includes(ch.value)}
                                            onChange={(e) => {
                                                const channels = e.target.checked
                                                    ? [...form.channels, ch.value]
                                                    : form.channels.filter(c => c !== ch.value);
                                                setForm({ ...form, channels });
                                            }}
                                        />
                                        {ch.icon} {t(`kpi_admin.channels.${ch.value}`)}
                                    </label>
                                ))}
                            </div>
                        </div>
                        <div style={{ display: 'flex', gap: '12px', marginTop: '20px' }}>
                            <button type="submit" className="btn btn-primary">
                                ✅ {t('kpi_admin.form.submit', 'إنشاء المؤشر')}
                            </button>
                            <button type="button" className="btn btn-secondary" onClick={() => setShowForm(false)}>
                                {t('common.cancel', 'إلغاء')}
                            </button>
                        </div>
                    </form>
                </div>
            )}

            <div className="modules-grid">
                <div className="section-card" style={{ borderTop: '4px solid #10B981' }}>
                    <h3 className="section-title" style={{ color: '#10B981' }}>
                        🎯 {t('kpi_admin.list.title', 'مؤشرات الأداء')}
                    </h3>
                    {loading ? (
                        <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                            ⏳ {t('common.loading', 'جاري التحميل...')}
                        </div>
                    ) : error ? (
                        <div style={{ padding: '20px', textAlign: 'center', color: 'var(--danger)' }}>
                            ❌ {error}
                        </div>
                    ) : kpiList.length === 0 ? (
                        <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                            <div style={{ fontSize: '48px', marginBottom: '16px' }}>📊</div>
                            <div>{t('kpi_admin.empty', 'لا توجد مؤشرات بعد')}</div>
                            <button
                                className="btn btn-primary"
                                style={{ marginTop: '16px' }}
                                onClick={() => setShowForm(true)}
                            >
                                + {t('kpi_admin.add_first', 'أضف أول مؤشر')}
                            </button>
                        </div>
                    ) : (
                        <div className="links-list">
                            {kpiList.map((kpi) => (
                                <div key={kpi.id} className="link-item" style={{
                                    padding: '14px 12px',
                                    marginBottom: '8px',
                                    background: 'var(--bg-secondary)',
                                    borderRadius: 'var(--radius)',
                                    border: '1px solid var(--border-color)'
                                }}>
                                    <div style={{ flex: 1 }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                                            <span style={{ fontWeight: '600', color: 'var(--text-primary)' }}>
                                                {kpi.kpi_code}
                                            </span>
                                            <span style={{
                                                padding: '2px 8px', borderRadius: '12px', fontSize: '11px',
                                                background: kpi.is_active ? '#D1FAE5' : '#FEE2E2',
                                                color: kpi.is_active ? '#065F46' : '#991B1B'
                                            }}>
                                                {kpi.is_active ? t('common.active', 'نشط') : t('common.inactive', 'معطل')}
                                            </span>
                                        </div>
                                        <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                                            {kpi.metric_source === 'report_key' ? '📊' : '📁'} {kpi.metric_reference}
                                            {' • '}
                                            {KPI_COMPARISON_OPS.find(o => o.value === kpi.comparison_op)?.label} {kpi.threshold_value}
                                            {' • '}
                                            ⏱️ {kpi.evaluation_interval_minutes} {t('kpi_admin.minutes', 'دقيقة')}
                                        </div>
                                    </div>
                                    <span className="link-arrow" style={{ fontSize: '18px' }}>
                                        {i18n.language === 'ar' ? '←' : '→'}
                                    </span>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
