import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { hasPermission, getUser } from '../utils/auth'
import useDebounce from '../hooks/useDebounce'
import { searchAPI } from '../services/search'
import { fetchSearchRegistry } from '../services/searchRegistry'

// All searchable pages in the ERP system
function useSearchablePages() {
  const { t } = useTranslation()
  const user = getUser()

  return useMemo(() => {
    const enabledModules = user?.enabled_modules || []
    const isSystemAdmin = user?.role === 'system_admin'
    const isModuleEnabled = (moduleKey) => {
      if (isSystemAdmin) return true
      if (enabledModules.length === 0) return true
      return enabledModules.includes(moduleKey)
    }

    const pages = []

    const add = (path, labelAr, labelEn, icon, category, categoryAr, permission, moduleKey, keywords = []) => {
      if (moduleKey && !isModuleEnabled(moduleKey)) return
      if (permission && !hasPermission(permission)) return
      pages.push({ path, labelAr, labelEn, icon, category, categoryAr, keywords })
    }

    // Dashboard
    add('/dashboard', 'مساحة العمل', 'Dashboard', '🏠', 'General', 'عام', 'dashboard.view', null, ['home', 'الرئيسية', 'لوحة'])

    // Accounting
    add('/accounting', 'المحاسبة', 'Accounting', '📊', 'Accounting', 'المحاسبة', 'accounting.view', 'accounting', ['finance', 'مالية'])
    add('/accounting/coa', 'شجرة الحسابات', 'Chart of Accounts', '📋', 'Accounting', 'المحاسبة', 'accounting.view', 'accounting', ['accounts', 'حسابات', 'دليل'])
    add('/accounting/journal-entries', 'القيود اليومية', 'Journal Entries', '📝', 'Accounting', 'المحاسبة', 'accounting.view', 'accounting', ['entries', 'قيد', 'يومية'])
    add('/accounting/journal-entries/new', 'قيد يومي جديد', 'New Journal Entry', '➕', 'Accounting', 'المحاسبة', 'accounting.view', 'accounting', ['create', 'إنشاء', 'جديد'])
    add('/accounting/fiscal-years', 'السنوات المالية', 'Fiscal Years', '📅', 'Accounting', 'المحاسبة', 'accounting.view', 'accounting', ['سنة', 'مالية', 'fiscal'])
    add('/accounting/recurring-templates', 'القوالب المتكررة', 'Recurring Templates', '🔄', 'Accounting', 'المحاسبة', 'accounting.view', 'accounting', ['تكرار', 'قالب', 'recurring'])
    add('/accounting/period-comparison', 'مقارنة الفترات', 'Period Comparison', '📊', 'Accounting', 'المحاسبة', 'accounting.view', 'accounting', ['compare', 'مقارنة', 'فترة'])
    add('/accounting/opening-balances', 'الأرصدة الافتتاحية', 'Opening Balances', '📂', 'Accounting', 'المحاسبة', 'accounting.manage', 'accounting', ['opening', 'افتتاحي', 'رصيد'])
    add('/accounting/closing-entries', 'قيود الإقفال', 'Closing Entries', '🔒', 'Accounting', 'المحاسبة', 'accounting.manage', 'accounting', ['closing', 'إقفال'])
    add('/accounting/cost-centers', 'مراكز التكلفة', 'Cost Centers', '🎯', 'Accounting', 'المحاسبة', 'accounting.view', 'accounting', ['cost center', 'تكلفة', 'مركز'])
    add('/accounting/budgets', 'الميزانيات', 'Budgets', '💹', 'Accounting', 'المحاسبة', 'accounting.view', 'accounting', ['budget', 'ميزانية', 'موازنة'])
    add('/accounting/vat-report', 'تقرير الضريبة', 'VAT Report', '🧾', 'Accounting', 'المحاسبة', 'accounting.view', 'accounting', ['vat', 'ضريبة', 'القيمة المضافة'])
    add('/accounting/tax-audit', 'تدقيق الضرائب', 'Tax Audit', '🔍', 'Accounting', 'المحاسبة', 'accounting.view', 'accounting', ['tax', 'تدقيق', 'ضريبي'])
    add('/accounting/cashflow', 'التدفق النقدي', 'Cash Flow Report', '💵', 'Accounting', 'المحاسبة', 'accounting.view', 'accounting', ['cash flow', 'نقدي', 'تدفق'])
    add('/accounting/general-ledger', 'دفتر الأستاذ', 'General Ledger', '📖', 'Accounting', 'المحاسبة', 'accounting.view', 'accounting', ['ledger', 'أستاذ', 'دفتر'])
    add('/accounting/trial-balance', 'ميزان المراجعة', 'Trial Balance', '⚖️', 'Accounting', 'المحاسبة', 'accounting.view', 'accounting', ['trial', 'مراجعة', 'ميزان'])
    add('/accounting/income-statement', 'قائمة الدخل', 'Income Statement', '📈', 'Accounting', 'المحاسبة', 'accounting.view', 'accounting', ['income', 'دخل', 'أرباح', 'خسائر'])
    add('/accounting/balance-sheet', 'الميزانية العمومية', 'Balance Sheet', '📊', 'Accounting', 'المحاسبة', 'accounting.view', 'accounting', ['balance sheet', 'عمومية', 'ميزانية'])
    add('/accounting/currencies', 'العملات', 'Currencies', '💱', 'Accounting', 'المحاسبة', 'currencies.view', 'accounting', ['currency', 'عملة', 'صرف'])
    add('/accounting/zakat', 'الزكاة', 'Zakat Calculator', '🕌', 'Accounting', 'المحاسبة', 'accounting.view', 'accounting', ['zakat', 'زكاة'])
    add('/accounting/fiscal-locks', 'أقفال الفترات', 'Fiscal Period Locks', '🔐', 'Accounting', 'المحاسبة', 'accounting.manage', 'accounting', ['lock', 'قفل', 'فترة'])

    // Sales
    add('/sales', 'المبيعات', 'Sales', '💰', 'Sales', 'المبيعات', 'sales.view', 'sales', ['بيع', 'مبيعات'])
    add('/sales/customers', 'العملاء', 'Customers', '👤', 'Sales', 'المبيعات', 'sales.view', 'sales', ['customer', 'عميل', 'زبون'])
    add('/sales/invoices', 'فواتير المبيعات', 'Sales Invoices', '🧾', 'Sales', 'المبيعات', 'sales.view', 'sales', ['invoice', 'فاتورة', 'فواتير'])
    add('/sales/orders', 'أوامر البيع', 'Sales Orders', '📋', 'Sales', 'المبيعات', 'sales.view', 'sales', ['order', 'أمر', 'طلب'])
    add('/sales/quotations', 'عروض الأسعار', 'Quotations', '📄', 'Sales', 'المبيعات', 'sales.view', 'sales', ['quotation', 'عرض سعر', 'تسعير'])
    add('/sales/returns', 'مرتجعات المبيعات', 'Sales Returns', '↩️', 'Sales', 'المبيعات', 'sales.view', 'sales', ['return', 'مرتجع', 'إرجاع'])

    // POS
    add('/pos', 'نقاط البيع', 'Point of Sale', '🏪', 'POS', 'نقاط البيع', 'pos.view', 'pos', ['pos', 'كاشير', 'بيع مباشر'])

    // Buying
    add('/buying', 'المشتريات', 'Purchases', '🛒', 'Buying', 'المشتريات', 'buying.view', 'buying', ['purchase', 'شراء', 'مشتريات'])
    add('/buying/suppliers', 'الموردين', 'Suppliers', '🏭', 'Buying', 'المشتريات', 'buying.view', 'buying', ['supplier', 'مورد', 'موردين'])
    add('/buying/invoices', 'فواتير المشتريات', 'Purchase Invoices', '🧾', 'Buying', 'المشتريات', 'buying.view', 'buying', ['invoice', 'فاتورة'])
    add('/buying/orders', 'أوامر الشراء', 'Purchase Orders', '📋', 'Buying', 'المشتريات', 'buying.view', 'buying', ['order', 'أمر شراء', 'طلب'])

    // Stock / Inventory
    add('/stock', 'المخزون', 'Inventory', '📦', 'Inventory', 'المخزون', 'stock.view', 'stock', ['stock', 'مخزون', 'inventory'])
    add('/stock/products', 'المنتجات', 'Products', '🏷️', 'Inventory', 'المخزون', 'stock.view', 'stock', ['product', 'منتج', 'صنف', 'أصناف'])
    add('/stock/warehouses', 'المستودعات', 'Warehouses', '🏭', 'Inventory', 'المخزون', 'stock.view', 'stock', ['warehouse', 'مستودع', 'مخزن'])
    add('/stock/transfer', 'تحويل مخزون', 'Stock Transfer', '🔀', 'Inventory', 'المخزون', 'stock.view', 'stock', ['transfer', 'تحويل', 'نقل'])

    // Manufacturing
    add('/manufacturing', 'التصنيع', 'Manufacturing', '🏭', 'Manufacturing', 'التصنيع', 'manufacturing.view', 'manufacturing', ['production', 'إنتاج', 'تصنيع'])
    add('/manufacturing/orders', 'أوامر الإنتاج', 'Production Orders', '📦', 'Manufacturing', 'التصنيع', 'manufacturing.view', 'manufacturing', ['production order', 'أمر إنتاج', 'تشغيل'])
    add('/manufacturing/mrp', 'تخطيط الموارد', 'MRP Planning', '📊', 'Manufacturing', 'التصنيع', 'manufacturing.view', 'manufacturing', ['mrp', 'تخطيط', 'موارد'])

    // Treasury
    add('/treasury', 'الخزينة', 'Treasury', '🏦', 'Treasury', 'الخزينة', 'treasury.view', 'treasury', ['خزينة', 'treasury'])
    add('/treasury/accounts', 'حسابات الخزينة', 'Treasury Accounts', '🏦', 'Treasury', 'الخزينة', 'treasury.view', 'treasury', ['account', 'حساب', 'بنك'])
    add('/treasury/reconciliation', 'تسوية البنك', 'Bank Reconciliation', '🏧', 'Treasury', 'الخزينة', 'reconciliation.view', 'treasury', ['reconciliation', 'تسوية', 'بنك'])

    // HR
    add('/hr', 'الموارد البشرية', 'Human Resources', '👥', 'HR', 'الموارد البشرية', 'hr.view', 'hr', ['hr', 'موارد', 'بشرية', 'موظفين'])
    add('/hr/employees', 'الموظفين', 'Employees', '👤', 'HR', 'الموارد البشرية', 'hr.view', 'hr', ['employee', 'موظف'])
    add('/hr/payroll', 'الرواتب', 'Payroll', '💰', 'HR', 'الموارد البشرية', 'hr.view', 'hr', ['payroll', 'راتب', 'أجر', 'مسير'])
    add('/hr/leaves', 'الإجازات', 'Leaves', '🌴', 'HR', 'الموارد البشرية', 'hr.view', 'hr', ['leave', 'إجازة', 'غياب'])

    // Projects
    add('/projects', 'المشاريع', 'Projects', '📐', 'Projects', 'المشاريع', 'projects.view', 'projects', ['project', ' مشروع'])

    // Reports
    add('/reports', 'مركز التقارير', 'Report Center', '📈', 'Reports', 'التقارير', 'reports.view', 'reports', ['report', 'تقرير'])

    // Admin / Settings
    add('/settings', 'الإعدادات', 'Settings', '⚙️', 'Admin', 'الإدارة', 'settings.view', null, ['settings', 'إعدادات', 'ضبط'])
    add('/settings/notifications/queue', 'مراقبة طابور الإشعارات', 'Notification Queue Monitor', '🔔', 'Admin', 'الإدارة', 'notifications.admin', null, ['notifications', 'queue', 'إشعارات', 'طابور'])
    add('/settings/notifications/templates', 'قوالب البريد للإشعارات', 'Notification Email Templates', '✉️', 'Admin', 'الإدارة', 'email_templates.admin', null, ['email', 'templates', 'notifications', 'قوالب', 'بريد', 'إشعارات'])
    add('/admin/audit-logs', 'سجلات المراقبة', 'Audit Logs', '📋', 'Admin', 'الإدارة', 'audit.view', 'audit', ['audit', 'سجل', 'مراقبة'])

    return pages
  }, [user?.username, user?.role, user?.enabled_modules, t])
}

// Fuzzy-ish matching: checks if query words appear in text (order-independent)
function matchScore(query, page, isArabic) {
  const q = query.toLowerCase().trim()
  if (!q) return 0

  const label = isArabic ? page.labelAr : page.labelEn
  const labelLower = label.toLowerCase()
  const catLabel = isArabic ? page.categoryAr : page.category
  const allText = [labelLower, page.labelAr.toLowerCase(), page.labelEn.toLowerCase(), catLabel.toLowerCase(), ...page.keywords.map(k => k.toLowerCase())].join(' ')

  // Exact match on label
  if (labelLower === q) return 100

  // Starts with query
  if (labelLower.startsWith(q)) return 90

  // Label contains query
  if (labelLower.includes(q)) return 80

  // Any keyword/text contains query
  if (allText.includes(q)) return 60

  // Word-by-word matching
  const words = q.split(/\s+/)
  const matchedWords = words.filter(w => allText.includes(w))
  if (matchedWords.length === words.length) return 50
  if (matchedWords.length > 0) return 30 * (matchedWords.length / words.length)

  return 0
}

export default function GlobalSearch({ isOpen, onClose }) {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [registry, setRegistry] = useState(null)
  const [entityResults, setEntityResults] = useState([])
  const [searching, setSearching] = useState(false)
  const inputRef = useRef(null)
  const listRef = useRef(null)
  const isArabic = i18n.language === 'ar'
  const pages = useSearchablePages()
  const debouncedQuery = useDebounce(query, 300)

  // Fetch search registry on mount
  useEffect(() => {
    fetchSearchRegistry()
      .then(entities => setRegistry(entities || []))
      .catch(() => setRegistry(null))
  }, [])

  // Search backend entities when debounced query changes
  useEffect(() => {
    if (!debouncedQuery.trim() || debouncedQuery.trim().length < 2) {
      setEntityResults([])
      return
    }

    let cancelled = false
    setSearching(true)

    searchAPI.search(debouncedQuery.trim(), { limit: 10 })
      .then(res => {
        if (cancelled) return
        const data = res.data?.results || res.data || []
        // Flatten entity results into a list
        const items = []
        for (const entity of data) {
          const entityMeta = registry?.find(e => e.entity_code === entity.entity)
          for (const item of (entity.items || [])) {
            let route = entityMeta?.route_template || ''
            // Replace {id} in route template
            if (item.id && route) {
              route = route.replace('{id}', item.id)
            }
            items.push({
              entityCode: entity.entity,
              label: item.name || item.label || item.title || item.code || `#${item.id}`,
              route,
              icon: entityMeta?.icon || 'FileText',
              entityLabel: entityMeta?.label || entity.entity,
            })
          }
        }
        if (!cancelled) setEntityResults(items)
      })
      .catch(() => { if (!cancelled) setEntityResults([]) })
      .finally(() => { if (!cancelled) setSearching(false) })

    return () => { cancelled = true }
  }, [debouncedQuery, registry])

  const pageResults = useMemo(() => {
    if (!query.trim()) {
      const popular = ['/dashboard', '/sales/invoices', '/buying/invoices', '/stock/products', '/accounting/journal-entries', '/hr/employees', '/treasury/accounts', '/sales/customers']
      return pages.filter(p => popular.includes(p.path)).slice(0, 8)
    }

    return pages
      .map(p => ({ ...p, score: matchScore(query, p, isArabic) }))
      .filter(p => p.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 8)
  }, [query, pages, isArabic])

  // Merge page results and entity results
  const allResults = useMemo(() => {
    const items = []

    // Page results
    if (pageResults.length > 0) {
      for (const p of pageResults) {
        items.push({
          type: 'page',
          path: p.path,
          label: isArabic ? p.labelAr : p.labelEn,
          sublabel: isArabic ? p.labelEn : p.labelAr,
          icon: p.icon,
          category: isArabic ? p.categoryAr : p.category,
        })
      }
    }

    // Entity results from backend
    if (entityResults.length > 0) {
      for (const e of entityResults) {
        items.push({
          type: 'entity',
          path: e.route,
          label: e.label,
          sublabel: e.entityLabel,
          icon: '🔗',
          category: e.entityLabel,
        })
      }
    }

    return items
  }, [pageResults, entityResults, isArabic])

  // Group results by category
  const groupedResults = useMemo(() => {
    const groups = {}
    const flatList = []
    allResults.forEach((r, idx) => {
      const cat = r.category
      if (!groups[cat]) groups[cat] = []
      groups[cat].push({ ...r, flatIndex: flatList.length })
      flatList.push(r)
    })
    return { groups, flatList }
  }, [allResults])

  // Reset selection when results change
  useEffect(() => {
    setSelectedIndex(0)
  }, [query])

  // Focus input when opened
  useEffect(() => {
    if (isOpen && inputRef.current) {
      setTimeout(() => inputRef.current?.focus(), 50)
    }
    if (isOpen) {
      setQuery('')
      setSelectedIndex(0)
    }
  }, [isOpen])

  // Scroll selected item into view
  useEffect(() => {
    if (listRef.current) {
      const el = listRef.current.querySelector(`[data-index="${selectedIndex}"]`)
      el?.scrollIntoView({ block: 'nearest' })
    }
  }, [selectedIndex])

  const handleSelect = useCallback((item) => {
    if (item.path) {
      navigate(item.path)
    }
    onClose()
    setQuery('')
  }, [navigate, onClose])

  const handleKeyDown = useCallback((e) => {
    const { flatList } = groupedResults
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIndex(prev => Math.min(prev + 1, flatList.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex(prev => Math.max(prev - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (flatList[selectedIndex]) {
        handleSelect(flatList[selectedIndex])
      }
    } else if (e.key === 'Escape') {
      e.preventDefault()
      onClose()
    }
  }, [groupedResults, selectedIndex, handleSelect, onClose])

  if (!isOpen) return null

  return (
    <div className="global-search-overlay" onClick={onClose}>
      <div className="global-search-modal" onClick={e => e.stopPropagation()}>
        {/* Search Header */}
        <div className="global-search-header">
          <div className="global-search-input-wrapper">
            <svg className="global-search-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="8" />
              <path d="m21 21-4.35-4.35" />
            </svg>
            <input
              ref={inputRef}
              type="text"
              className="global-search-input"
              placeholder={t('globalsearch.search_pages_reports_settings')}
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              autoComplete="off"
              autoCorrect="off"
              spellCheck="false"
            />
            {searching && <span className="global-search-spinner" style={{fontSize:'12px',opacity:0.5}}>...</span>}
            <kbd className="global-search-kbd">ESC</kbd>
          </div>
        </div>

        {/* Results */}
        <div className="global-search-results" ref={listRef}>
          {groupedResults.flatList.length === 0 && query.trim() && !searching ? (
            <div className="global-search-empty">
              <span style={{ fontSize: 32, opacity: 0.4 }}>🔍</span>
              <p>{t('globalsearch.no_results_for')} "{query}"</p>
            </div>
          ) : (
            <>
              {!query.trim() && (
                <div className="global-search-section-label">
                  {t('globalsearch._quick_access')}
                </div>
              )}
              {Object.entries(groupedResults.groups).map(([category, items]) => (
                <div key={category}>
                  {query.trim() && (
                    <div className="global-search-section-label">{category}</div>
                  )}
                  {items.map(item => (
                    <div
                      key={item.type + ':' + item.path}
                      data-index={item.flatIndex}
                      className={`global-search-item ${item.flatIndex === selectedIndex ? 'selected' : ''}`}
                      onClick={() => handleSelect(item)}
                      onMouseEnter={() => setSelectedIndex(item.flatIndex)}
                    >
                      <span className="global-search-item-icon">{item.icon}</span>
                      <div className="global-search-item-text">
                        <span className="global-search-item-label">
                          {item.label}
                        </span>
                        <span className="global-search-item-path">
                          {item.sublabel}
                        </span>
                      </div>
                      {item.flatIndex === selectedIndex && (
                        <span className="global-search-item-enter">↵</span>
                      )}
                    </div>
                  ))}
                </div>
              ))}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="global-search-footer">
          <span><kbd>↑</kbd> <kbd>↓</kbd> {t('globalsearch.navigate')}</span>
          <span><kbd>↵</kbd> {t('hr.status_open')}</span>
          <span><kbd>ESC</kbd> {t('common.close')}</span>
        </div>
      </div>
    </div>
  )
}
