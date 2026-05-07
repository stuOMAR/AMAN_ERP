import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Settings, Save, RefreshCw } from 'lucide-react';
import BackButton from '../../components/common/BackButton';
import '../../components/ModuleStyles.css';

const POLICY_KEYS = [
    { key: 'reconciliation_tolerance', label: 'policy_settings.drift_tolerance', type: 'number', step: '0.01', group: 'finance' },
    { key: 'gl.je_epsilon', label: 'policy_settings.je_epsilon', type: 'number', step: '0.001', group: 'finance' },
    { key: 'fiscal.allow_drafts_in_closed_period', label: 'policy_settings.allow_drafts_closed', type: 'boolean', group: 'finance' },
    { key: 'expenses.auto_approve_threshold', label: 'policy_settings.auto_approve_threshold', type: 'number', step: '0.01', group: 'expenses' },
    { key: 'expenses.cost_center_policy', label: 'policy_settings.cost_center_policy', type: 'select', options: ['required', 'optional', 'disabled'], group: 'expenses' },
    { key: 'webhook.rate_limit_rpm', label: 'policy_settings.webhook_rate_limit', type: 'number', step: '1', group: 'integrations' },
    { key: 'audit.sla_hours', label: 'policy_settings.audit_sla_hours', type: 'number', step: '1', group: 'audit' },
    { key: 'recurring.review_threshold_default', label: 'policy_settings.recurring_review_threshold', type: 'number', step: '0.01', group: 'finance' },
];

const PolicySettings = () => {
    const { t } = useTranslation();
    const [settings, setSettings] = useState({});
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState('');
    const [success, setSuccess] = useState('');

    useEffect(() => { fetchSettings(); }, []);

    const fetchSettings = async () => {
        try {
            setLoading(true);
            setError('');
            const res = await fetch('/api/settings');
            if (!res.ok) throw new Error('Failed to fetch');
            const data = await res.json();
            const mapped = {};
            POLICY_KEYS.forEach(pk => {
                const raw = data[pk.key];
                if (raw !== undefined) {
                    mapped[pk.key] = pk.type === 'boolean' ? (raw === true || raw === 'true') : raw;
                } else {
                    mapped[pk.key] = pk.type === 'boolean' ? false : '';
                }
            });
            setSettings(mapped);
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    };

    const handleSave = async () => {
        try {
            setSaving(true);
            setError('');
            setSuccess('');
            const res = await fetch('/api/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settings),
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Save failed');
            }
            setSuccess(t('policy_settings.save_success'));
            setTimeout(() => setSuccess(''), 3000);
        } catch (e) {
            setError(e.message);
        } finally {
            setSaving(false);
        }
    };

    const updateSetting = (key, value) => {
        setSettings(prev => ({ ...prev, [key]: value }));
    };

    const grouped = POLICY_KEYS.reduce((acc, pk) => {
        (acc[pk.group] = acc[pk.group] || []).push(pk);
        return acc;
    }, {});

    const renderInput = (pk) => {
        const val = settings[pk.key];
        if (pk.type === 'boolean') {
            return (
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                    <input
                        type="checkbox"
                        checked={!!val}
                        onChange={e => updateSetting(pk.key, e.target.checked)}
                        style={{ width: 18, height: 18 }}
                    />
                    <span>{t(pk.label)}</span>
                </label>
            );
        }
        if (pk.type === 'select') {
            return (
                <select value={val || ''} onChange={e => updateSetting(pk.key, e.target.value)} style={inputStyle}>
                    <option value="">{t('common.select')}</option>
                    {pk.options.map(o => <option key={o} value={o}>{o}</option>)}
                </select>
            );
        }
        return (
            <input
                type="number"
                step={pk.step}
                value={val ?? ''}
                onChange={e => updateSetting(pk.key, e.target.value)}
                style={inputStyle}
            />
        );
    };

    return (
        <div style={{ padding: 24, direction: 'rtl' }}>
            <BackButton />
            <h1 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Settings size={24} /> {t('policy_settings.title')}
            </h1>

            {error && <div style={{ color: '#ef4444', marginBottom: 12 }}>{error}</div>}
            {success && <div style={{ color: '#10b981', marginBottom: 12 }}>{success}</div>}

            <div style={{ marginBottom: 16 }}>
                <button onClick={fetchSettings} style={{ ...btnStyle, background: '#6b7280' }}>
                    <RefreshCw size={16} /> {t('common.refresh')}
                </button>
                <button onClick={handleSave} disabled={saving} style={{ ...btnStyle, background: '#10b981', marginRight: 8 }}>
                    <Save size={16} /> {saving ? t('common.saving') : t('common.save')}
                </button>
            </div>

            {loading ? <p>{t('common.loading')}</p> : (
                Object.entries(grouped).map(([group, keys]) => (
                    <div key={group} style={{ background: '#f9fafb', padding: 16, borderRadius: 8, marginBottom: 16 }}>
                        <h3 style={{ marginBottom: 12, textTransform: 'capitalize' }}>
                            {t(`policy_settings.group_${group}`)}
                        </h3>
                        <div style={{ display: 'grid', gap: 12 }}>
                            {keys.map(pk => (
                                <div key={pk.key} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                                    <label style={{ minWidth: 220, fontSize: 14, fontWeight: 500 }}>
                                        {t(pk.label)}
                                    </label>
                                    {renderInput(pk)}
                                </div>
                            ))}
                        </div>
                    </div>
                ))
            )}
        </div>
    );
};

const btnStyle = { padding: '8px 16px', borderRadius: 6, border: 'none', color: '#fff', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 14 };
const inputStyle = { padding: '8px 12px', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 14, width: 200 };

export default PolicySettings;
