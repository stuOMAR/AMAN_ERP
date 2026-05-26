import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Mail, Bell, Server, CheckCircle, Sliders } from 'lucide-react';
import api from '../../../utils/api';
import { notificationsAPI } from '../../../utils/api';
import { useToast } from '../../../context/ToastContext';
import DataTable from '../../../components/common/DataTable';
import { Spinner } from '../../../components/common/LoadingStates'

// ── Notification Preferences (per-user event × channel toggles) ─────────────
const EVENT_TYPES = [
    'leave_approved', 'leave_rejected', 'invoice_held', 'invoice_approved',
    'purchase_approved', 'review_reminder', 'subscription_expiring',
    'performance_review_due', 'time_off_reminder', 'task_assigned',
    'shipment_delayed', 'payment_received', 'approval_requested',
];

const CHANNELS = [
    { key: 'email_enabled', label: 'notification_preferences.channel_email' },
    { key: 'in_app_enabled', label: 'notification_preferences.channel_in_app' },
    { key: 'push_enabled', label: 'notification_preferences.channel_push' },
];

function buildPrefMap(rows) {
    const map = {};
    EVENT_TYPES.forEach((evt) => {
        map[evt] = { email_enabled: true, in_app_enabled: true, push_enabled: true };
    });
    rows.forEach((r) => {
        if (map[r.event_type] !== undefined) {
            map[r.event_type] = {
                email_enabled: r.email_enabled,
                in_app_enabled: r.in_app_enabled,
                push_enabled: r.push_enabled,
            };
        }
    });
    return map;
}

const NotificationSettings = ({ settings, handleSettingChange }) => {
    const { t } = useTranslation();
    const { showToast } = useToast();
    const [testing, setTesting] = useState(false);

    // ── User notification preferences state ──
    const [prefs, setPrefs] = useState(() => buildPrefMap([]));
    const [prefsLoading, setPrefsLoading] = useState(true);
    const [prefSaving, setPrefSaving] = useState(null);

    useEffect(() => {
        notificationsAPI
            .getPreferences()
            .then((res) => setPrefs(buildPrefMap(res.data || [])))
            .catch(() => {/* use defaults */})
            .finally(() => setPrefsLoading(false));
    }, []);

    const handlePrefToggle = async (eventType, channel) => {
        const current = prefs[eventType];
        const updated = { ...current, [channel]: !current[channel] };
        setPrefs((p) => ({ ...p, [eventType]: updated }));
        setPrefSaving(eventType);
        try {
            await notificationsAPI.updatePreference({ event_type: eventType, ...updated });
        } catch {
            setPrefs((p) => ({ ...p, [eventType]: current }));
        } finally {
            setPrefSaving(null);
        }
    };

    // Test email connection via backend
    const testEmailConnection = async () => {
        setTesting(true);
        try {
            const response = await notificationsAPI.testEmail();
            showToast(response.data.message || t('settings.notifications.test_success'), 'success');
        } catch (err) {
            console.error("Email test failed", err);
            showToast(err.response?.data?.detail || t('settings.notifications.test_failed'), 'error');
        } finally {
            setTesting(false);
        }
    };

    return (
        <div className="space-y-8">
            {/* SMTP Configuration */}
            <div className="bg-base-50 p-6 rounded-2xl border border-base-200">
                <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
                    <Server size={20} className="text-primary" />
                    {t('settings.notifications.smtp_title')}
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div className="form-group">
                        <label className="form-label">{t('settings.notifications.smtp_host')}</label>
                        <input
                            type="text"
                            className="form-input ltr"
                            value={settings.smtp_host || ''}
                            onChange={(e) => handleSettingChange('smtp_host', e.target.value)}
                            placeholder="smtp.gmail.com"
                        />
                    </div>
                    <div className="form-group">
                        <label className="form-label">{t('settings.notifications.smtp_port')}</label>
                        <input
                            type="number"
                            className="form-input ltr"
                            value={settings.smtp_port || '587'}
                            onChange={(e) => handleSettingChange('smtp_port', e.target.value)}
                            placeholder="587"
                        />
                    </div>
                    <div className="form-group">
                        <label className="form-label">{t('settings.notifications.smtp_user')}</label>
                        <input
                            type="email"
                            className="form-input ltr"
                            value={settings.smtp_username || ''}
                            onChange={(e) => handleSettingChange('smtp_username', e.target.value)}
                        />
                    </div>
                    <div className="form-group">
                        <label className="form-label">{t('settings.notifications.smtp_pass')}</label>
                        <input
                            type="password"
                            className="form-input ltr"
                            value={settings.smtp_password || ''}
                            onChange={(e) => handleSettingChange('smtp_password', e.target.value)}
                        />
                    </div>
                </div>

                <div className="mt-6 flex justify-end">
                    <button
                        type="button"
                        className="btn btn-ghost gap-2 border-base-300"
                        onClick={testEmailConnection}
                        disabled={testing}
                    >
                        {testing ? <Spinner size="sm"/> : <CheckCircle size={18} />}
                        {t('settings.notifications.test_conn')}
                    </button>
                </div>
            </div>

            {/* SMS Gateway Configuration */}
            <div className="bg-base-50 p-6 rounded-2xl border border-base-200">
                <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
                    <Mail size={20} className="text-primary" />
                    {t('settings.notifications.sms_title')}
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div className="form-group">
                        <label className="form-label">{t('settings.notifications.sms_provider_label')}</label>
                        <select
                            className="form-input"
                            value={settings.sms_provider || ''}
                            onChange={(e) => handleSettingChange('sms_provider', e.target.value)}
                        >
                            <option value="">{t('settings.notifications.select_provider')}</option>
                            <option value="twilio">Twilio</option>
                            <option value="infobip">Infobip</option>
                        </select>
                    </div>
                    <div className="form-group">
                        <label className="form-label">{t('settings.notifications.sms_account_sid')}</label>
                        <input
                            type="text"
                            className="form-input ltr"
                            value={settings.sms_account_sid || ''}
                            onChange={(e) => handleSettingChange('sms_account_sid', e.target.value)}
                        />
                    </div>
                    <div className="form-group">
                        <label className="form-label">{t('settings.notifications.sms_auth_token')}</label>
                        <input
                            type="password"
                            className="form-input ltr"
                            value={settings.sms_auth_token || ''}
                            onChange={(e) => handleSettingChange('sms_auth_token', e.target.value)}
                        />
                    </div>
                    <div className="form-group">
                        <label className="form-label">{t('settings.notifications.sms_sender_name')}</label>
                        <input
                            type="text"
                            className="form-input ltr"
                            value={settings.sms_sender_name || ''}
                            onChange={(e) => handleSettingChange('sms_sender_name', e.target.value)}
                            placeholder="AMAN_ERP"
                        />
                    </div>
                </div>
            </div>

            {/* Alerts */}
            <div className="bg-base-50 p-6 rounded-2xl border border-base-200">
                <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
                    <Bell size={20} className="text-primary" />
                    {t('settings.notifications.alerts_title')}
                </h3>
                <div className="space-y-4">
                    <div className="flex items-center gap-3">
                        <input
                            type="checkbox"
                            className="checkbox checkbox-primary"
                            id="notify_low_stock"
                            checked={settings.notify_low_stock === 'true'}
                            onChange={(e) => handleSettingChange('notify_low_stock', e.target.checked.toString())}
                        />
                        <label className="cursor-pointer font-medium" htmlFor="notify_low_stock">
                            {t('settings.notifications.notify_low_stock')}
                        </label>
                    </div>

                    <div className="flex items-center gap-3">
                        <input
                            type="checkbox"
                            className="checkbox checkbox-primary"
                            id="notify_new_invoice"
                            checked={settings.notify_new_invoice === 'true'}
                            onChange={(e) => handleSettingChange('notify_new_invoice', e.target.checked.toString())}
                        />
                        <label className="cursor-pointer font-medium" htmlFor="notify_new_invoice">
                            {t('settings.notifications.notify_new_invoice')}
                        </label>
                    </div>
                </div>
            </div>

            {/* ── User Notification Preferences (event × channel toggles) ── */}
            <div className="bg-base-50 p-6 rounded-2xl border border-base-200">
                <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
                    <Sliders size={20} className="text-primary" />
                    {t('notification_preferences.title')}
                </h3>
                <p className="text-sm text-base-content/60 mb-4">{t('notification_preferences.subtitle')}</p>

                {prefsLoading ? (
                    <div style={{ padding: 20, textAlign: 'center', color: 'var(--muted)' }}>
                        {t('notification_preferences.loading')}
                    </div>
                ) : (
                    <div style={{ overflowX: 'auto' }}>
                        <DataTable
                            data={EVENT_TYPES.map((evt) => ({ event_type: evt, ...prefs[evt] }))}
                            columns={[
                                {
                                    key: 'event_type',
                                    label: t('notification_preferences.event_type'),
                                    render: (val) => (
                                        <span style={{ fontWeight: 500 }}>
                                            {t('notification_preferences.event_' + val)}
                                            {prefSaving === val && (
                                                <span style={{ marginInlineStart: 8, fontSize: '0.7rem', color: 'var(--muted)' }}>⏳</span>
                                            )}
                                        </span>
                                    ),
                                },
                                ...CHANNELS.map((ch) => ({
                                    key: ch.key,
                                    label: t(ch.label),
                                    render: (val, row) => (
                                        <label style={{ display: 'inline-flex', alignItems: 'center', cursor: 'pointer' }}>
                                            <input
                                                type="checkbox"
                                                checked={val ?? true}
                                                onChange={() => handlePrefToggle(row.event_type, ch.key)}
                                                style={{ width: 16, height: 16, cursor: 'pointer' }}
                                            />
                                        </label>
                                    ),
                                })),
                            ]}
                            rowKey="event_type"
                        />
                    </div>
                )}
            </div>
        </div>
    );
};

export default NotificationSettings;
