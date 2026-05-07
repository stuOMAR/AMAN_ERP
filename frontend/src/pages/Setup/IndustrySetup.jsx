import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useIndustryType } from '../../hooks/useIndustryType'
import { getIndustryTypesList, getEnabledModulesForIndustry, ALWAYS_ENABLED_MODULES, VARIABLE_MODULES } from '../../config/industryModules'
import { useNavigate } from 'react-router-dom'
import BackButton from '../../components/common/BackButton'

function IndustrySetup() {
  const { t, i18n } = useTranslation()
  const { setIndustryType, loading } = useIndustryType()
  const [selected, setSelected] = useState(null)
  const [error, setError] = useState('')
  const [step, setStep] = useState(1)
  const navigate = useNavigate()

  const isRTL = i18n.language === 'ar'
  const industries = getIndustryTypesList()

  const toggleLanguage = () => {
    i18n.changeLanguage(isRTL ? 'en' : 'ar')
  }

  const handleNext = () => {
    if (!selected) {
      setError(t('setup.please_select_a_business_type'))
      return
    }
    setError('')
    setStep(2)
  }

  const handleBack = () => {
    setStep(1)
    setError('')
  }

  const handleConfirm = async () => {
    setError('')
    const success = await setIndustryType(selected)
    if (success) {
      window.location.href = '/setup/modules'
    } else {
      setError(t('setup.failed_to_save_please_try_again'))
    }
  }

  const selectedIndustry = industries.find(i => i.key === selected)
  const enabledModules = selected ? getEnabledModulesForIndustry(selected) : []

  const MODULE_LABELS = {
    dashboard: { ar: 'مساحة العمل', en: 'Dashboard', icon: '🏠' },
    kpi: { ar: 'لوحات الأداء', en: 'KPI Dashboards', icon: '📊' },
    accounting: { ar: 'المحاسبة', en: 'Accounting', icon: '📒' },
    assets: { ar: 'الأصول الثابتة', en: 'Fixed Assets', icon: '🏗️' },
    treasury: { ar: 'الخزينة', en: 'Treasury', icon: '🏦' },
    sales: { ar: 'المبيعات', en: 'Sales', icon: '💰' },
    pos: { ar: 'نقاط البيع', en: 'Point of Sale', icon: '🏪' },
    buying: { ar: 'المشتريات', en: 'Purchases', icon: '🛒' },
    stock: { ar: 'المخزون', en: 'Inventory', icon: '📦' },
    manufacturing: { ar: 'التصنيع', en: 'Manufacturing', icon: '🏭' },
    projects: { ar: 'المشاريع', en: 'Projects', icon: '📐' },
    crm: { ar: 'إدارة العلاقات', en: 'CRM', icon: '🤝' },
    services: { ar: 'الخدمات والصيانة', en: 'Services', icon: '🔧' },
    expenses: { ar: 'المصاريف', en: 'Expenses', icon: '💸' },
    taxes: { ar: 'الضرائب', en: 'Taxes', icon: '🧾' },
    approvals: { ar: 'الاعتمادات', en: 'Approvals', icon: '✅' },
    reports: { ar: 'التقارير', en: 'Reports', icon: '📈' },
    hr: { ar: 'الموارد البشرية', en: 'HR', icon: '👥' },
    audit: { ar: 'سجلات المراقبة', en: 'Audit Logs', icon: '📋' },
    roles: { ar: 'الأدوار والصلاحيات', en: 'Roles', icon: '🔐' },
    settings: { ar: 'الإعدادات', en: 'Settings', icon: '⚙️' },
    data_import: { ar: 'استيراد البيانات', en: 'Data Import', icon: '📥' },
  }

  const variableModulesOnly = Object.entries(MODULE_LABELS).filter(([key]) => VARIABLE_MODULES.includes(key))
  const alwaysModulesOnly = Object.entries(MODULE_LABELS).filter(([key]) => ALWAYS_ENABLED_MODULES.includes(key))

  return (
    <>
      <style>{`
        .setup-layout {
          height: 100vh;
          overflow-y: auto;
          display: flex;
          align-items: flex-start;
          justify-content: center;
          background: var(--bg-main, #f8fafc);
          padding: 24px 16px;
          direction: ${isRTL ? 'rtl' : 'ltr'};
        }
        .setup-card {
          background: var(--bg-card, #fff);
          padding: 40px 36px;
          border-radius: 16px;
          box-shadow: var(--shadow-lg, 0 10px 15px -3px rgba(0,0,0,0.1));
          border: 1px solid var(--border-color, #e2e8f0);
          width: 100%;
          max-width: ${step === 1 ? '960px' : '640px'};
          transition: max-width 0.35s ease;
          animation: fadeUp 0.35s ease-out;
        }
        .setup-lang-btn {
          position: fixed;
          top: 16px;
          ${isRTL ? 'left' : 'right'}: 16px;
          z-index: 50;
        }
        .setup-header {
          text-align: center;
          margin-bottom: 28px;
        }
        .setup-header-icon {
          width: 56px;
          height: 56px;
          border-radius: 14px;
          background: #eff6ff;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 28px;
          margin: 0 auto 16px;
        }
        .setup-header h1 {
          font-size: 24px;
          font-weight: 700;
          color: var(--text-main, #1e293b);
          margin-bottom: 6px;
        }
        .setup-header p {
          font-size: 14px;
          color: var(--text-secondary, #64748b);
        }

        /* Stepper */
        .setup-stepper {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 12px;
          margin-bottom: 28px;
        }
        .setup-step {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .setup-step-num {
          width: 30px;
          height: 30px;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 13px;
          font-weight: 700;
          transition: all 0.3s;
        }
        .setup-step-num.active {
          background: var(--primary, #2563eb);
          color: #fff;
        }
        .setup-step-num.done {
          background: var(--success, #10b981);
          color: #fff;
        }
        .setup-step-num.inactive {
          background: #f1f5f9;
          color: var(--text-muted, #94a3b8);
        }
        .setup-step-label {
          font-size: 13px;
          font-weight: 600;
          color: var(--text-secondary, #64748b);
        }
        .setup-step-label.active {
          color: var(--primary, #2563eb);
        }
        .setup-step-line {
          width: 40px;
          height: 2px;
          border-radius: 1px;
          transition: background 0.3s;
        }

        /* Industry Grid */
        .setup-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
          gap: 12px;
          margin-bottom: 28px;
        }
        .setup-item {
          position: relative;
          background: var(--bg-card, #fff);
          border: 2px solid var(--border-color, #e2e8f0);
          border-radius: 12px;
          padding: 20px 14px;
          cursor: pointer;
          transition: all 0.2s ease;
          display: flex;
          flex-direction: column;
          align-items: center;
          text-align: center;
          gap: 8px;
        }
        .setup-item:hover {
          background: var(--bg-hover, #f1f5f9);
          border-color: var(--primary-light, #60a5fa);
          transform: translateY(-2px);
          box-shadow: var(--shadow-sm);
        }
        .setup-item.selected {
          background: #eff6ff;
          border-color: var(--primary, #2563eb);
          box-shadow: 0 4px 12px -4px rgba(37,99,235,0.25);
          transform: translateY(-2px);
        }
        .setup-item-icon {
          width: 48px;
          height: 48px;
          border-radius: 10px;
          background: #f1f5f9;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 24px;
          transition: all 0.2s;
        }
        .setup-item.selected .setup-item-icon {
          background: var(--primary, #2563eb);
          box-shadow: 0 4px 10px -2px rgba(37,99,235,0.3);
        }
        .setup-item-name {
          font-weight: 700;
          font-size: 14px;
          color: var(--text-main, #1e293b);
          line-height: 1.3;
        }
        .setup-item.selected .setup-item-name {
          color: var(--primary, #2563eb);
        }
        .setup-item-desc {
          font-size: 11px;
          color: var(--text-muted, #94a3b8);
          line-height: 1.5;
        }
        .setup-item-check {
          position: absolute;
          top: 8px;
          ${isRTL ? 'left' : 'right'}: 8px;
          background: var(--primary, #2563eb);
          color: #fff;
          width: 22px;
          height: 22px;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 12px;
          font-weight: bold;
          animation: scaleIn 0.2s ease;
        }

        /* Step 2 - Banner */
        .setup-banner {
          display: flex;
          align-items: center;
          gap: 16px;
          background: #eff6ff;
          border: 1px solid #bfdbfe;
          border-radius: 12px;
          padding: 16px 20px;
          margin-bottom: 24px;
        }
        .setup-banner-icon {
          font-size: 36px;
          flex-shrink: 0;
        }
        .setup-banner-name {
          font-weight: 700;
          font-size: 16px;
          color: var(--primary, #2563eb);
        }
        .setup-banner-desc {
          font-size: 12px;
          color: var(--text-secondary, #64748b);
          margin-top: 3px;
        }

        /* Modules */
        .setup-section-label {
          font-size: 12px;
          font-weight: 700;
          color: var(--text-muted, #94a3b8);
          text-transform: uppercase;
          letter-spacing: 1px;
          margin-bottom: 10px;
          display: flex;
          align-items: center;
          gap: 10px;
        }
        .setup-section-label::after {
          content: '';
          flex: 1;
          height: 1px;
          background: var(--border-color, #e2e8f0);
        }
        .setup-module-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
          gap: 8px;
          margin-bottom: 20px;
        }
        .setup-module {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 8px 12px;
          border-radius: 8px;
          font-size: 13px;
          border: 1px solid;
          transition: all 0.15s;
        }
        .setup-module.enabled {
          background: #f0fdf4;
          border-color: #bbf7d0;
          color: #166534;
        }
        .setup-module.disabled {
          background: #fef2f2;
          border-color: #fecaca;
          color: var(--text-muted, #94a3b8);
        }
        .setup-module.core {
          background: #f8fafc;
          border-color: var(--border-color, #e2e8f0);
          color: var(--text-secondary, #64748b);
        }
        .setup-module-icon { font-size: 16px; flex-shrink: 0; }
        .setup-module-name { flex: 1; font-weight: 600; font-size: 12px; }
        .setup-module-badge { font-size: 14px; flex-shrink: 0; }

        .setup-note {
          background: #fffbeb;
          border: 1px solid #fde68a;
          border-radius: 8px;
          padding: 10px 16px;
          margin-bottom: 20px;
          font-size: 13px;
          color: #92400e;
          text-align: center;
        }
        .setup-btn-row {
          display: flex;
          gap: 10px;
        }

        @keyframes scaleIn {
          from { transform: scale(0); opacity: 0; }
          to { transform: scale(1); opacity: 1; }
        }
        @keyframes fadeUp {
          from { opacity: 0; transform: translateY(20px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @media (max-width: 600px) {
          .setup-card { padding: 24px 18px; }
          .setup-grid { grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 8px; }
          .setup-item { padding: 14px 10px; }
          .setup-module-grid { grid-template-columns: 1fr 1fr; }
          .setup-header h1 { font-size: 20px; }
          .setup-step-label { display: none; }
        }
      `}</style>

      <div className="setup-layout">
        {/* Language Toggle */}
        <div className="setup-lang-btn">
          <button className="btn btn-outline btn-sm" onClick={toggleLanguage}>
            🌐 {t('setup.عربي')}
          </button>
        </div>

        <div className="setup-card">
          {/* Header */}
          <div className="setup-header">
            <div className="setup-header-icon">
              {step === 1 ? '🏢' : '⚙️'}
            </div>
            <h1>
              {step === 1
                ? (t('setup.choose_your_business_type'))
                : (t('setup.review_enabled_modules'))
              }
            </h1>
            <p>
              {step === 1
                ? (t('setup.the_system_will_be_automatically_customized_for_yo'))
                : (isRTL
                  ? `الوحدات التي ستُفعّل لـ "${selectedIndustry?.nameAr}"`
                  : `Modules enabled for "${selectedIndustry?.nameEn}"`)
              }
            </p>
          </div>
          <div style={{ marginBottom: '12px' }}>
            <BackButton onClick={step === 2 ? handleBack : () => navigate(-1)} />
          </div>

          {/* Stepper */}
          <div className="setup-stepper">
            <div className="setup-step">
              <div className={`setup-step-num ${step > 1 ? 'done' : 'active'}`}>
                {step > 1 ? '✓' : '1'}
              </div>
              <span className={`setup-step-label ${step === 1 ? 'active' : ''}`}>
                {t('setup.select_industry')}
              </span>
            </div>
            <div className="setup-step-line" style={{ background: step >= 2 ? 'var(--primary, #2563eb)' : '#e2e8f0' }} />
            <div className="setup-step">
              <div className={`setup-step-num ${step >= 2 ? 'active' : 'inactive'}`}>2</div>
              <span className={`setup-step-label ${step === 2 ? 'active' : ''}`}>
                {t('setup.confirm_modules')}
              </span>
            </div>
          </div>

          {/* Error */}
          {error && <div className="alert alert-error">{error}</div>}

          {/* ─── Step 1: اختيار النشاط ─── */}
          {step === 1 && (
            <>
              <div className="setup-grid">
                {industries.map(ind => (
                  <div
                    key={ind.key}
                    className={`setup-item ${selected === ind.key ? 'selected' : ''}`}
                    onClick={() => { setSelected(ind.key); setError('') }}
                  >
                    <div className="setup-item-icon">{ind.icon}</div>
                    <div className="setup-item-name">
                      {isRTL ? ind.nameAr : ind.nameEn}
                    </div>
                    <div className="setup-item-desc">
                      {isRTL ? ind.descriptionAr : ind.descriptionEn}
                    </div>
                    {selected === ind.key && (
                      <div className="setup-item-check">✓</div>
                    )}
                  </div>
                ))}
              </div>

              <button
                className="btn btn-primary btn-block"
                onClick={handleNext}
                disabled={!selected}
              >
                {t('common.next')}
              </button>
            </>
          )}

          {/* ─── Step 2: تأكيد الوحدات ─── */}
          {step === 2 && selectedIndustry && (
            <>
              {/* Selected Industry Banner */}
              <div className="setup-banner">
                <div className="setup-banner-icon">{selectedIndustry.icon}</div>
                <div>
                  <div className="setup-banner-name">
                    {isRTL ? selectedIndustry.nameAr : selectedIndustry.nameEn}
                  </div>
                  <div className="setup-banner-desc">
                    {isRTL ? selectedIndustry.descriptionAr : selectedIndustry.descriptionEn}
                  </div>
                </div>
              </div>

              {/* Specialized Modules */}
              <div className="setup-section-label">
                {t('setup.specialized_modules_vary_by_industry')}
              </div>
              <div className="setup-module-grid">
                {variableModulesOnly.map(([key, label]) => {
                  const isEnabled = enabledModules.includes(key)
                  return (
                    <div key={key} className={`setup-module ${isEnabled ? 'enabled' : 'disabled'}`}>
                      <span className="setup-module-icon">{label.icon}</span>
                      <span className="setup-module-name">{isRTL ? label.ar : label.en}</span>
                      <span className="setup-module-badge">{isEnabled ? '✅' : '—'}</span>
                    </div>
                  )
                })}
              </div>

              {/* Core Modules */}
              <div className="setup-section-label">
                {t('setup.core_modules_always_enabled')}
              </div>
              <div className="setup-module-grid" style={{ marginBottom: '20px' }}>
                {alwaysModulesOnly.map(([key, label]) => (
                  <div key={key} className="setup-module core">
                    <span className="setup-module-icon">{label.icon}</span>
                    <span className="setup-module-name">{isRTL ? label.ar : label.en}</span>
                    <span className="setup-module-badge">✅</span>
                  </div>
                ))}
              </div>

              {/* Note */}
              <div className="setup-note">
                💡 {t('setup.you_can_modify_enabled_modules_later_from_settings')}
              </div>

              {/* Actions */}
              <div className="setup-btn-row">
                <button className="btn btn-secondary" onClick={handleBack} style={{ flex: 1 }}>
                  {t('common.back')}
                </button>
                <button
                  className="btn btn-success"
                  onClick={handleConfirm}
                  disabled={loading}
                  style={{ flex: 2 }}
                >
                  {loading
                    ? (t('setup.saving'))
                    : (t('setup.confirm_start'))
                  }
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </>
  )
}

export default IndustrySetup
