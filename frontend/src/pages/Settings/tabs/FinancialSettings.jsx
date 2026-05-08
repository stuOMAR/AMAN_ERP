import React from 'react';
import { useTranslation } from 'react-i18next';

const FinancialSettings = ({ formData, handleChange, settings, handleSettingChange }) => {
    const { t } = useTranslation();

    return (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="form-group">
                <label className="form-label" htmlFor="tax_number">{t('settings.company.tax_number')}</label>
                <input
                    type="text"
                    id="tax_number"
                    name="tax_number"
                    className="form-input font-mono"
                    value={formData.tax_number || ''}
                    onChange={handleChange}
                    autoComplete="off"
                />
            </div>

            <div className="form-group">
                <label className="form-label" htmlFor="commercial_registry">{t('settings.company.cr_number')}</label>
                <input
                    type="text"
                    id="commercial_registry"
                    name="commercial_registry"
                    className="form-input font-mono"
                    value={formData.commercial_registry || ''}
                    onChange={handleChange}
                    autoComplete="off"
                />
            </div>

            <div className="form-group">
                <label className="form-label" htmlFor="currency">{t('settings.company.currency')}</label>
                <input
                    type="text"
                    id="currency"
                    name="currency"
                    className="form-input"
                    value={formData.currency || ''}
                    onChange={handleChange}
                    maxLength="3"
                    autoComplete="transaction-currency"
                />
            </div>

            <div className="divider col-span-2"></div>

            <div className="form-group">
                <label className="form-label" htmlFor="vat_enabled">{t('settings.financial.vat_enabled')}</label>
                <select
                    name="vat_enabled"
                    id="vat_enabled"
                    className="form-input"
                    value={settings.vat_enabled || 'true'}
                    onChange={(e) => handleSettingChange('vat_enabled', e.target.value)}
                >
                    <option value="true">{t('common.yes')}</option>
                    <option value="false">{t('common.no')}</option>
                </select>
            </div>

            <div className="form-group">
                <label className="form-label" htmlFor="vat_rate">{t('settings.financial.vat_rate')}</label>
                <input
                    type="number"
                    name="vat_rate"
                    id="vat_rate"
                    className="form-input"
                    value={settings.vat_rate || ''}
                    onChange={(e) => handleSettingChange('vat_rate', e.target.value)}
                />
            </div>

            <div className="form-group">
                <label className="form-label" htmlFor="fiscal_year_start">{t('settings.financial.fiscal_year_start')}</label>
                <select
                    name="fiscal_year_start"
                    id="fiscal_year_start"
                    className="form-input"
                    value={settings.fiscal_year_start || '01-01'}
                    onChange={(e) => handleSettingChange('fiscal_year_start', e.target.value)}
                >
                    <option value="01-01">January (01)</option>
                    <option value="04-01">April (04)</option>
                    <option value="07-01">July (07)</option>
                    <option value="10-01">October (10)</option>
                </select>
            </div>

            <div className="form-group">
                <label className="form-label" htmlFor="decimal_places">{t('settings.financial.decimal_places')}</label>
                <select
                    name="decimal_places"
                    id="decimal_places"
                    className="form-input"
                    value={settings.decimal_places || '2'}
                    onChange={(e) => handleSettingChange('decimal_places', e.target.value)}
                >
                    <option value="0">0</option>
                    <option value="1">1</option>
                    <option value="2">2</option>
                    <option value="3">3</option>
                    <option value="4">4</option>
                </select>
            </div>
        </div>
    );
};

export default FinancialSettings;
