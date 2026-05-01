import React from 'react';
import { useTranslation } from 'react-i18next';
import { MessageSquare, Phone } from 'lucide-react';
import IntegrationKeysVault from './IntegrationKeysVault';

const IntegrationSettings = ({ settings, handleSettingChange }) => {
    const { t } = useTranslation();

    return (
        <div className="space-y-8">
            {/* SMS Gateway */}
            <div className="bg-base-50 p-6 rounded-2xl border border-base-200">
                <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
                    <MessageSquare size={20} className="text-primary" />
                    {t('settings.integrations.sms_title')}
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div className="form-group">
                        <label className="form-label">{t('settings.integrations.provider')}</label>
                        <select
                            className="form-select"
                            value={settings.sms_provider || ''}
                            onChange={(e) => handleSettingChange('sms_provider', e.target.value)}
                        >
                            <option value="">{t('common.select')}</option>
                            <option value="twilio">Twilio</option>
                            <option value="unifonic">Unifonic</option>
                            <option value="yamamah">Yamamah</option>
                        </select>
                    </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-4">
                    <div className="form-group">
                        <label className="form-label">{t('settings.integrations.api_key')}</label>
                        <input
                            type="password"
                            className="form-input ltr"
                            value={settings.sms_api_key || ''}
                            onChange={(e) => handleSettingChange('sms_api_key', e.target.value)}
                        />
                    </div>
                    <div className="form-group">
                        <label className="form-label">{t('settings.integrations.sender_id')}</label>
                        <input
                            type="text"
                            className="form-input ltr"
                            value={settings.sms_sender_id || ''}
                            onChange={(e) => handleSettingChange('sms_sender_id', e.target.value)}
                        />
                    </div>
                </div>
            </div>

            {/* Whatsapp */}
            <div className="bg-base-50 p-6 rounded-2xl border border-base-200">
                <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
                    <Phone size={20} className="text-primary" />
                    {t('settings.integrations.whatsapp_title')}
                </h3>
                <div className="alert alert-warning">
                    <span>{t('settings.integrations.coming_soon')}</span>
                </div>
            </div>

            {/* Integration Keys Vault */}
            <IntegrationKeysVault />
        </div>
    );
};

export default IntegrationSettings;
