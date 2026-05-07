import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ALWAYS_ENABLED_MODULES, VARIABLE_MODULES, INDUSTRY_TYPES, getEnabledModulesForIndustry } from '../../config/industryModules'
import { getIndustryType } from '../../hooks/useIndustryType'
import { getUser, updateUser } from '../../utils/auth'
import api from '../../services/apiClient'
import BackButton from '../../components/common/BackButton'

const MODULE_LABELS = {
  dashboard:   { ar: 'مساحة العمل',         en: 'Dashboard',       icon: '🏠', category: 'core' },
  kpi:         { ar: 'لوحات الأداء',         en: 'KPI Dashboards',  icon: '📊', category: 'core' },
  accounting:  { ar: 'المحاسبة',             en: 'Accounting',      icon: '📒', category: 'finance' },
  assets:      { ar: 'الأصول الثابتة',       en: 'Fixed Assets',    icon: '🏗️', category: 'finance' },
  treasury:    { ar: 'الخزينة',              en: 'Treasury',        icon: '🏦', category: 'finance' },
  sales:       { ar: 'المبيعات',             en: 'Sales',           icon: '💰', category: 'sales' },
  buying:      { ar: 'المشتريات',            en: 'Purchases',       icon: '🛒', category: 'sales' },
  crm:         { ar: 'إدارة العلاقات',       en: 'CRM',             icon: '🤝', category: 'sales' },
  expenses:    { ar: 'المصاريف',             en: 'Expenses',        icon: '💸', category: 'finance' },
  taxes:       { ar: 'الضرائب',              en: 'Taxes',           icon: '🧾', category: 'finance' },
  approvals:   { ar: 'الاعتمادات',           en: 'Approvals',       icon: '✅', category: 'core' },
  reports:     { ar: 'التقارير',             en: 'Reports',         icon: '📈', category: 'core' },
  hr:          { ar: 'الموارد البشرية',      en: 'HR & Payroll',    icon: '👥', category: 'hr' },
  audit:       { ar: 'سجلات المراقبة',       en: 'Audit Logs',      icon: '📋', category: 'core' },
  roles:       { ar: 'الأدوار والصلاحيات',   en: 'Roles',           icon: '🔐', category: 'core' },
  settings:    { ar: 'الإعدادات',            en: 'Settings',        icon: '⚙️', category: 'core' },
  data_import: { ar: 'استيراد البيانات',     en: 'Data Import',     icon: '📥', category: 'core' },
  pos:           { ar: 'نقاط البيع',         en: 'Point of Sale',   icon: '🏪', category: 'variable' },
  stock:         { ar: 'المخزون',            en: 'Inventory',       icon: '📦', category: 'variable' },
  manufacturing: { ar: 'التصنيع',            en: 'Manufacturing',   icon: '🏭', category: 'variable' },
  projects:      { ar: 'المشاريع',           en: 'Projects',        icon: '📐', category: 'variable' },
  services:      { ar: 'الخدمات والصيانة',   en: 'Services',        icon: '🔧', category: 'variable' },
}

const CATEGORY_META = {
  core:     { color: '#3b82f6', key: 'cat_core' },
  finance:  { color: '#8b5cf6', key: 'cat_finance' },
  sales:    { color: '#06b6d4', key: 'cat_sales' },
  hr:       { color: '#f59e0b', key: 'cat_hr' },
  variable: { color: '#10b981', key: 'cat_variable' },
}

function ModuleCustomization() {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const isRTL = i18n.language === 'ar'

  const industryKey = getIndustryType()
  const industry = industryKey ? INDUSTRY_TYPES[industryKey] : null

  const user = getUser()
  const initialEnabled = user?.enabled_modules || (industryKey ? getEnabledModulesForIndustry(industryKey) : [])

  const [variableState, setVariableState] = useState(() => {
    const state = {}
    VARIABLE_MODULES.forEach(m => { state[m] = initialEnabled.includes(m) })
    return state
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const finalModules = [
    ...ALWAYS_ENABLED_MODULES,
    ...VARIABLE_MODULES.filter(m => variableState[m]),
  ]
  const enabledCount = finalModules.length
  const totalCount = ALWAYS_ENABLED_MODULES.length + VARIABLE_MODULES.length
  const progressPct = Math.round((enabledCount / totalCount) * 100)

  const handleToggle = (key) => {
    if (ALWAYS_ENABLED_MODULES.includes(key)) return
    setVariableState(prev => ({ ...prev, [key]: !prev[key] }))
  }

  const handleSave = async () => {
    setSaving(true); setError('')
    try {
      await api.put('/companies/modules', finalModules)
      updateUser({ enabled_modules: finalModules })
      window.location.href = '/dashboard'
    } catch (err) {
      console.error('Save failed:', err)
      setError(t('module_setup.save_error'))
      setSaving(false)
    }
  }

  const handleSkip = () => { window.location.href = '/dashboard' }

  // Group modules by category
  const grouped = {}
  Object.entries(MODULE_LABELS).forEach(([key, label]) => {
    const cat = label.category
    if (!grouped[cat]) grouped[cat] = []
    grouped[cat].push({ key, ...label })
  })

  return (
    <>
      <style>{`
        .mc2-layout {
          height: 100vh;
          overflow-y: auto;
          background: var(--bg-main, #f8fafc);
          display: flex;
          align-items: flex-start;
          justify-content: center;
          padding: 32px 16px 60px;
          direction: ${isRTL ? 'rtl' : 'ltr'};
        }
        .mc2-card {
          background: var(--bg-card, #fff);
          border: 1px solid var(--border-color, #e2e8f0);
          border-radius: 20px;
          box-shadow: 0 10px 25px -5px rgba(0,0,0,0.08);
          padding: 36px 32px;
          width: 100%;
          max-width: 980px;
          animation: mc2FadeUp 0.3s ease-out;
        }

        /* Header */
        .mc2-header-icon {
          width: 56px; height: 56px; border-radius: 14px;
          background: #eff6ff;
          display: flex; align-items: center; justify-content: center;
          font-size: 28px; margin: 0 auto 14px;
        }
        .mc2-card h1 {
          font-size: 22px; font-weight: 800;
          color: var(--text-main, #1e293b);
          text-align: center; margin-bottom: 6px;
        }
        .mc2-card .mc2-subtitle {
          font-size: 13px; color: var(--text-secondary, #64748b);
          text-align: center; margin-bottom: 28px; line-height: 1.6; max-width: 540px; margin-left: auto; margin-right: auto;
        }

        /* Stepper */
        .mc2-stepper {
          display: flex; align-items: center; justify-content: center; gap: 12px; margin-bottom: 28px;
        }
        .mc2-step { display: flex; align-items: center; gap: 8px; }
        .mc2-step-num {
          width: 30px; height: 30px; border-radius: 50%;
          display: flex; align-items: center; justify-content: center;
          font-size: 13px; font-weight: 700;
        }
        .mc2-step-num.done    { background: var(--success, #10b981); color: #fff; }
        .mc2-step-num.active  { background: var(--primary, #2563eb); color: #fff; }
        .mc2-step-num.inactive{ background: #f1f5f9; color: var(--text-muted, #94a3b8); }
        .mc2-step-label { font-size: 13px; font-weight: 600; color: var(--text-secondary, #64748b); }
        .mc2-step-label.active { color: var(--primary, #2563eb); }
        .mc2-step-line { width: 40px; height: 2px; border-radius: 1px; background: var(--border-color, #e2e8f0); }
        .mc2-step-line.done { background: var(--primary, #2563eb); }

        /* Back button */
        .mc2-back-btn {
          display: inline-flex; align-items: center; gap: 6px;
          background: transparent; border: 1px solid var(--border-color, #e2e8f0);
          color: var(--text-secondary, #64748b); padding: 7px 14px;
          border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 600;
          margin-bottom: 20px; transition: all 0.15s;
        }
        .mc2-back-btn:hover { background: var(--bg-hover, #f1f5f9); color: var(--text-main, #1e293b); }

        /* Industry badge */
        .mc2-industry-badge {
          display: flex; align-items: center; gap: 14px;
          background: #eff6ff; border: 1px solid #bfdbfe;
          border-radius: 12px; padding: 14px 18px; margin-bottom: 20px;
        }
        .mc2-industry-label { font-size: 11px; color: #3b82f6; font-weight: 600; margin-bottom: 2px; }
        .mc2-industry-name  { font-size: 16px; font-weight: 800; color: var(--text-main, #1e293b); }
        .mc2-industry-desc  { font-size: 12px; color: var(--text-secondary, #64748b); }

        /* Counter */
        .mc2-counter {
          background: var(--bg-main, #f8fafc); border: 1px solid var(--border-color, #e2e8f0);
          border-radius: 12px; padding: 14px 18px; margin-bottom: 20px;
          display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
        }
        .mc2-counter-badge {
          background: linear-gradient(135deg, #22c55e, #16a34a); color: white;
          font-weight: 800; font-size: 20px; width: 48px; height: 48px;
          border-radius: 10px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;
        }
        .mc2-counter-title { color: var(--text-main, #1e293b); font-weight: 700; font-size: 14px; }
        .mc2-counter-sub   { color: var(--text-secondary, #64748b); font-size: 12px; }
        .mc2-progress-wrap { flex: 1; min-width: 140px; }
        .mc2-progress-bar  { background: var(--border-color, #e2e8f0); border-radius: 999px; height: 7px; overflow: hidden; }
        .mc2-progress-fill { height: 100%; background: linear-gradient(90deg, #3b82f6, #22c55e); border-radius: 999px; transition: width 0.3s; }

        /* Groups */
        .mc2-group { border: 1px solid var(--border-color, #e2e8f0); border-radius: 12px; overflow: hidden; margin-bottom: 14px; }
        .mc2-group-header {
          display: flex; align-items: center; justify-content: space-between; gap: 12px;
          padding: 12px 16px; background: var(--bg-main, #f8fafc);
          border-bottom: 1px solid var(--border-color, #e2e8f0);
        }
        .mc2-group-title { font-weight: 700; font-size: 14px; color: var(--text-main, #1e293b); }
        .mc2-group-desc  { font-size: 11px; color: var(--text-secondary, #64748b); margin-top: 1px; }
        .mc2-group-pill  { padding: 3px 10px; border-radius: 999px; font-size: 11px; font-weight: 700; white-space: nowrap; flex-shrink: 0; }

        /* Module grid */
        .mc2-mods-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); }
        .mc2-mod {
          display: flex; align-items: center; gap: 9px; padding: 11px 14px;
          border-bottom: 1px solid var(--border-color, #e2e8f0);
          border-${isRTL ? 'left' : 'right'}: 1px solid var(--border-color, #e2e8f0);
          transition: background 0.15s; background: var(--bg-card, #fff);
          cursor: pointer;
        }
        .mc2-mod:hover { background: var(--bg-hover, #f8fafc); }
        .mc2-mod.locked { cursor: default; }
        .mc2-mod.locked:hover { background: var(--bg-card, #fff); }
        .mc2-mod-icon {
          width: 32px; height: 32px; border-radius: 8px;
          display: flex; align-items: center; justify-content: center;
          font-size: 16px; flex-shrink: 0; transition: background 0.2s;
        }
        .mc2-mod-name { flex: 1; font-weight: 600; font-size: 12px; color: var(--text-main, #1e293b); line-height: 1.3; min-width: 0; }
        .mc2-mod-sub  { font-size: 10px; color: var(--text-muted, #94a3b8); margin-top: 1px; }
        .mc2-toggle {
          width: 34px; height: 19px; border-radius: 999px; position: relative;
          transition: background 0.2s; flex-shrink: 0;
        }
        .mc2-toggle-knob {
          width: 13px; height: 13px; background: white; border-radius: 50%;
          position: absolute; top: 3px; transition: left 0.2s;
          box-shadow: 0 1px 3px rgba(0,0,0,0.25);
        }

        /* Error */
        .mc2-error {
          background: #fef2f2; border: 1px solid #fecaca; color: #dc2626;
          padding: 11px 16px; border-radius: 9px; text-align: center; margin-top: 10px; font-size: 13px;
        }

        /* Footer */
        .mc2-footer { display: flex; gap: 10px; margin-top: 22px; flex-wrap: wrap; }
        .mc2-btn-skip {
          flex: 1; min-width: 130px; background: var(--bg-card, #fff);
          border: 1px solid var(--border-color, #e2e8f0); color: var(--text-secondary, #64748b);
          padding: 13px; border-radius: 10px; font-size: 14px; font-weight: 600; cursor: pointer; transition: all 0.15s;
        }
        .mc2-btn-skip:hover { background: var(--bg-hover, #f1f5f9); }
        .mc2-btn-save {
          flex: 3; min-width: 180px;
          background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
          color: white; padding: 13px; border-radius: 10px; border: none;
          font-size: 15px; font-weight: 700; cursor: pointer;
          box-shadow: 0 6px 18px -4px rgba(37,99,235,0.4); transition: opacity 0.15s;
        }
        .mc2-btn-save:disabled { opacity: 0.6; cursor: wait; }
        .mc2-btn-save:hover:not(:disabled) { opacity: 0.9; }

        @keyframes mc2FadeUp {
          from { opacity: 0; transform: translateY(14px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @media (max-width: 640px) {
          .mc2-card { padding: 24px 16px; }
          .mc2-mods-grid { grid-template-columns: 1fr 1fr; }
          .mc2-step-label { display: none; }
        }
      `}</style>

      <div className="mc2-layout">
        <div className="mc2-card">

          {/* Header icon */}
          <div className="mc2-header-icon">⚙️</div>
          <h1>{t('module_setup.title')}</h1>
          <p className="mc2-subtitle">{t('module_setup.subtitle')}</p>

          {/* Stepper */}
          <div className="mc2-stepper">
            <div className="mc2-step">
              <div className="mc2-step-num done">✓</div>
              <span className="mc2-step-label">{t('module_setup.step1_label')}</span>
            </div>
            <div className="mc2-step-line done" />
            <div className="mc2-step">
              <div className="mc2-step-num active">2</div>
              <span className="mc2-step-label active">{t('module_setup.step2_label')}</span>
            </div>
          </div>

          {/* Back */}
          <div style={{ marginBottom: '12px' }}>
            <BackButton onClick={() => navigate('/setup/industry')} />
          </div>

          {/* Industry badge */}
          {industry && (
            <div className="mc2-industry-badge">
              <div style={{ fontSize: '36px', flexShrink: 0 }}>{industry.icon}</div>
              <div>
                <div className="mc2-industry-label">{t('module_setup.selected_type')}</div>
                <div className="mc2-industry-name">{isRTL ? industry.nameAr : industry.nameEn}</div>
                <div className="mc2-industry-desc">{isRTL ? industry.descriptionAr : industry.descriptionEn}</div>
              </div>
            </div>
          )}

          {/* Counter */}
          <div className="mc2-counter">
            <div className="mc2-counter-badge">{enabledCount}</div>
            <div>
              <div className="mc2-counter-title">
                {t('module_setup.enabled_of_total', { total: totalCount })}
              </div>
              <div className="mc2-counter-sub">
                {t('module_setup.fixed_plus_variable', {
                  fixed: ALWAYS_ENABLED_MODULES.length,
                  variable: VARIABLE_MODULES.filter(m => variableState[m]).length
                })}
              </div>
            </div>
            <div className="mc2-progress-wrap">
              <div className="mc2-progress-bar">
                <div className="mc2-progress-fill" style={{ width: `${progressPct}%` }} />
              </div>
            </div>
          </div>

          {/* Variable modules first */}
          <ModuleGroup
            title={t('module_setup.variable_group_title')}
            description={t('module_setup.variable_group_desc')}
            color={CATEGORY_META['variable'].color}
            modules={grouped['variable'] || []}
            variableState={variableState}
            onToggle={handleToggle}
            isRTL={isRTL}
            locked={false}
            t={t}
          />

          {/* Fixed categories */}
          {['finance', 'sales', 'hr', 'core'].map(cat => (
            <ModuleGroup
              key={cat}
              title={t(`module_setup.${CATEGORY_META[cat].key}`)}
              description={t('module_setup.fixed_group_desc')}
              color={CATEGORY_META[cat].color}
              modules={grouped[cat] || []}
              variableState={{}}
              onToggle={() => {}}
              isRTL={isRTL}
              locked={true}
              t={t}
            />
          ))}

          {error && <div className="mc2-error">{error}</div>}

          {/* Footer */}
          <div className="mc2-footer">
            <button className="mc2-btn-skip" onClick={handleSkip}>
              {t('module_setup.skip_btn')}
            </button>
            <button className="mc2-btn-save" onClick={handleSave} disabled={saving}>
              {saving
                ? t('module_setup.saving')
                : t('module_setup.save_btn', { count: enabledCount })}
            </button>
          </div>

        </div>
      </div>
    </>
  )
}

function ModuleGroup({ title, description, color, modules, variableState, onToggle, isRTL, locked, t }) {
  if (!modules.length) return null
  const onCount = locked ? modules.length : modules.filter(m => variableState[m.key]).length
  const borderSide = isRTL ? 'borderRight' : 'borderLeft'

  return (
    <div className="mc2-group">
      <div className="mc2-group-header" style={{ [borderSide]: `4px solid ${color}` }}>
        <div>
          <div className="mc2-group-title">{title}</div>
          <div className="mc2-group-desc">{description}</div>
        </div>
        <div className="mc2-group-pill" style={{ background: `${color}15`, color, border: `1px solid ${color}30` }}>
          {locked
            ? t('module_setup.fixed_badge', { count: modules.length })
            : t('module_setup.modules_enabled', { count: onCount, total: modules.length })}
        </div>
      </div>
      <div className="mc2-mods-grid">
        {modules.map(mod => {
          const isOn = locked ? true : (variableState[mod.key] ?? false)
          return (
            <div
              key={mod.key}
              className={`mc2-mod${locked ? ' locked' : ''}`}
              onClick={() => !locked && onToggle(mod.key)}
            >
              <div className="mc2-mod-icon" style={{ background: isOn ? `${color}15` : 'var(--bg-main, #f8fafc)' }}>
                {mod.icon}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="mc2-mod-name">{isRTL ? mod.ar : mod.en}</div>
                {locked && <div className="mc2-mod-sub">🔒 {t('module_setup.fixed_label')}</div>}
              </div>
              {!locked && (
                <div className="mc2-toggle" style={{ background: isOn ? color : 'var(--border-color, #e2e8f0)' }}>
                  <div className="mc2-toggle-knob" style={{ left: isOn ? '18px' : '3px' }} />
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default ModuleCustomization
