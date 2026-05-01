import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { hasPermission, getUser } from '../utils/auth'

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
    add('/accounting/budgets/advanced', 'الميزانيات المتقدمة', 'Advanced Budgets', '💹', 'Accounting', 'المحاسبة', 'accounting.view', 'accounting', ['advanced budget', 'متقدم'])
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

    // Intercompany v2
    add('/accounting/intercompany/entities', 'مجموعات الكيانات', 'Entity Groups', '🏢', 'Accounting', 'المحاسبة', 'accounting.view', 'accounting', ['entity', 'كيان', 'مجموعة', 'intercompany', 'بين الشركات'])
    add('/accounting/intercompany/transactions', 'معاملات بين الشركات', 'Intercompany Transactions', '🔄', 'Accounting', 'المحاسبة', 'accounting.view', 'accounting', ['intercompany', 'شركات', 'معاملة'])
    add('/accounting/intercompany/transactions/new', 'معاملة جديدة بين الشركات', 'New Intercompany Transaction', '➕', 'Accounting', 'المحاسبة', 'accounting.edit', 'accounting', ['create', 'إنشاء', 'intercompany'])
    add('/accounting/intercompany/consolidation', 'تجميع القوائم المالية', 'Consolidation', '📊', 'Accounting', 'المحاسبة', 'accounting.view', 'accounting', ['consolidation', 'تجميع', 'موحد'])
    add('/accounting/intercompany/mappings', 'ربط الحسابات بين الشركات', 'Intercompany Account Mappings', '🔗', 'Accounting', 'المحاسبة', 'accounting.view', 'accounting', ['mapping', 'ربط', 'حسابات', 'intercompany'])

    // Sales
    add('/sales', 'المبيعات', 'Sales', '💰', 'Sales', 'المبيعات', 'sales.view', 'sales', ['بيع', 'مبيعات'])
    add('/sales/customers', 'العملاء', 'Customers', '👤', 'Sales', 'المبيعات', 'sales.view', 'sales', ['customer', 'عميل', 'زبون'])
    add('/sales/customers/new', 'عميل جديد', 'New Customer', '➕', 'Sales', 'المبيعات', 'sales.view', 'sales', ['create', 'إنشاء', 'إضافة'])
    add('/sales/invoices', 'فواتير المبيعات', 'Sales Invoices', '🧾', 'Sales', 'المبيعات', 'sales.view', 'sales', ['invoice', 'فاتورة', 'فواتير'])
    add('/sales/invoices/new', 'فاتورة جديدة', 'New Invoice', '➕', 'Sales', 'المبيعات', 'sales.view', 'sales', ['create', 'إنشاء'])
    add('/sales/orders', 'أوامر البيع', 'Sales Orders', '📋', 'Sales', 'المبيعات', 'sales.view', 'sales', ['order', 'أمر', 'طلب'])
    add('/sales/orders/new', 'أمر بيع جديد', 'New Sales Order', '➕', 'Sales', 'المبيعات', 'sales.view', 'sales', ['create', 'إنشاء'])
    add('/sales/quotations', 'عروض الأسعار', 'Quotations', '📄', 'Sales', 'المبيعات', 'sales.view', 'sales', ['quotation', 'عرض سعر', 'تسعير'])
    add('/sales/quotations/new', 'عرض سعر جديد', 'New Quotation', '➕', 'Sales', 'المبيعات', 'sales.view', 'sales', ['create', 'إنشاء'])
    add('/sales/cpq/products', 'التسعير المتقدم', 'Configure-Price-Quote', '🧮', 'Sales', 'المبيعات', 'sales.view', 'cpq', ['cpq', 'configure', 'price', 'quote', 'تسعير متقدم'])
    add('/sales/cpq/quotes', 'عروض التسعير المتقدم', 'CPQ Quotes', '🧾', 'Sales', 'المبيعات', 'sales.view', 'cpq', ['cpq', 'quote', 'تسعير', 'عرض'])
    add('/sales/customer-groups', 'مجموعات العملاء', 'Customer Groups', '👥', 'Sales', 'المبيعات', 'sales.view', 'sales', ['group', 'مجموعة'])
    add('/sales/returns', 'مرتجعات المبيعات', 'Sales Returns', '↩️', 'Sales', 'المبيعات', 'sales.view', 'sales', ['return', 'مرتجع', 'إرجاع'])
    add('/sales/receipts', 'إيصالات القبض', 'Customer Receipts', '🧾', 'Sales', 'المبيعات', 'sales.view', 'sales', ['receipt', 'إيصال', 'قبض', 'تحصيل'])
    add('/sales/contracts', 'العقود', 'Contracts', '📑', 'Sales', 'المبيعات', 'sales.view', 'sales', ['contract', 'عقد'])
    add('/sales/credit-notes', 'إشعارات دائنة', 'Credit Notes', '📝', 'Sales', 'المبيعات', 'sales.view', 'sales', ['credit note', 'إشعار دائن'])
    add('/sales/debit-notes', 'إشعارات مدينة', 'Debit Notes', '📝', 'Sales', 'المبيعات', 'sales.view', 'sales', ['debit note', 'إشعار مدين'])
    add('/sales/commissions', 'العمولات', 'Sales Commissions', '💵', 'Sales', 'المبيعات', 'sales.view', 'sales', ['commission', 'عمولة'])
    add('/sales/delivery-orders', 'أوامر التسليم', 'Delivery Orders', '🚚', 'Sales', 'المبيعات', 'sales.view', 'sales', ['delivery', 'تسليم', 'شحن'])
    add('/sales/reports/analytics', 'تقارير المبيعات', 'Sales Reports', '📈', 'Sales', 'المبيعات', 'sales.reports', 'sales', ['analytics', 'تحليلات'])
    add('/sales/reports/customer-statement', 'كشف حساب العميل', 'Customer Statement', '📋', 'Sales', 'المبيعات', 'sales.reports', 'sales', ['statement', 'كشف حساب'])
    add('/sales/reports/aging', 'تقرير الأعمار', 'Aging Report', '⏰', 'Sales', 'المبيعات', 'sales.reports', 'sales', ['aging', 'أعمار', 'تأخير'])

    // POS
    add('/pos', 'نقاط البيع', 'Point of Sale', '🏪', 'POS', 'نقاط البيع', 'pos.view', 'pos', ['pos', 'كاشير', 'بيع مباشر'])
    add('/pos/interface', 'شاشة البيع', 'POS Interface', '💳', 'POS', 'نقاط البيع', 'pos.sessions', 'pos', ['sell', 'بيع', 'كاشير'])
    add('/pos/promotions', 'العروض والخصومات', 'Promotions', '🎁', 'POS', 'نقاط البيع', 'pos.view', 'pos', ['promotion', 'عرض', 'خصم'])
    add('/pos/loyalty', 'برامج الولاء', 'Loyalty Programs', '⭐', 'POS', 'نقاط البيع', 'pos.view', 'pos', ['loyalty', 'ولاء', 'نقاط'])
    add('/pos/tables', 'إدارة الطاولات', 'Table Management', '🪑', 'POS', 'نقاط البيع', 'pos.view', 'pos', ['table', 'طاولة', 'مطعم'])
    add('/pos/kitchen', 'شاشة المطبخ', 'Kitchen Display', '👨‍🍳', 'POS', 'نقاط البيع', 'pos.view', 'pos', ['kitchen', 'مطبخ'])

    // Buying
    add('/buying', 'المشتريات', 'Purchases', '🛒', 'Buying', 'المشتريات', 'buying.view', 'buying', ['purchase', 'شراء', 'مشتريات'])
    add('/buying/suppliers', 'الموردين', 'Suppliers', '🏭', 'Buying', 'المشتريات', 'buying.view', 'buying', ['supplier', 'مورد', 'موردين'])
    add('/buying/suppliers/new', 'مورد جديد', 'New Supplier', '➕', 'Buying', 'المشتريات', 'buying.view', 'buying', ['create', 'إنشاء'])
    add('/buying/invoices', 'فواتير المشتريات', 'Purchase Invoices', '🧾', 'Buying', 'المشتريات', 'buying.view', 'buying', ['invoice', 'فاتورة'])
    add('/buying/invoices/new', 'فاتورة مشتريات جديدة', 'New Purchase Invoice', '➕', 'Buying', 'المشتريات', 'buying.view', 'buying', ['create', 'إنشاء'])
    add('/buying/orders', 'أوامر الشراء', 'Purchase Orders', '📋', 'Buying', 'المشتريات', 'buying.view', 'buying', ['order', 'أمر شراء', 'طلب'])
    add('/buying/orders/new', 'أمر شراء جديد', 'New Purchase Order', '➕', 'Buying', 'المشتريات', 'buying.create', 'buying', ['create', 'إنشاء'])
    add('/buying/returns', 'مرتجعات المشتريات', 'Purchase Returns', '↩️', 'Buying', 'المشتريات', 'buying.view', 'buying', ['return', 'مرتجع'])
    add('/buying/payments', 'سداد الموردين', 'Supplier Payments', '💳', 'Buying', 'المشتريات', 'buying.view', 'buying', ['payment', 'سداد', 'دفع'])
    add('/buying/supplier-groups', 'مجموعات الموردين', 'Supplier Groups', '👥', 'Buying', 'المشتريات', 'buying.view', 'buying', ['group', 'مجموعة'])
    add('/buying/credit-notes', 'إشعارات دائنة', 'Purchase Credit Notes', '📝', 'Buying', 'المشتريات', 'buying.view', 'buying', ['credit', 'إشعار دائن'])
    add('/buying/debit-notes', 'إشعارات مدينة', 'Purchase Debit Notes', '📝', 'Buying', 'المشتريات', 'buying.view', 'buying', ['debit', 'إشعار مدين'])
    add('/buying/rfq', 'طلبات عروض الأسعار', 'RFQ', '📩', 'Buying', 'المشتريات', 'buying.view', 'buying', ['rfq', 'طلب عرض سعر'])
    add('/buying/supplier-ratings', 'تقييم الموردين', 'Supplier Ratings', '⭐', 'Buying', 'المشتريات', 'buying.view', 'buying', ['rating', 'تقييم'])
    add('/buying/agreements', 'اتفاقيات الشراء', 'Purchase Agreements', '📑', 'Buying', 'المشتريات', 'buying.view', 'buying', ['agreement', 'اتفاقية'])
    add('/buying/blanket-po', 'أوامر الشراء الشاملة', 'Blanket Purchase Orders', '📋', 'Buying', 'المشتريات', 'buying.view', 'buying', ['blanket po', 'blanket', 'أمر شراء شامل', 'شامل'])
    add('/buying/blanket-po/new', 'أمر شراء شامل جديد', 'New Blanket Purchase Order', '➕', 'Buying', 'المشتريات', 'buying.create', 'buying', ['blanket po', 'create', 'إنشاء', 'شامل'])
    add('/buying/landed-costs', 'التكاليف المضافة', 'Landed Costs', '📦', 'Buying', 'المشتريات', 'buying.view', 'buying', ['landed cost', 'تكاليف', 'شحن'])
    add('/buying/reports/analytics', 'تقارير المشتريات', 'Purchase Reports', '📈', 'Buying', 'المشتريات', 'buying.reports', 'buying', ['analytics', 'تحليلات'])
    add('/buying/reports/supplier-statement', 'كشف حساب المورد', 'Supplier Statement', '📋', 'Buying', 'المشتريات', 'buying.reports', 'buying', ['statement', 'كشف حساب'])

    // 3-Way Matching
    add('/buying/matching', 'المطابقة الثلاثية', '3-Way Matching', '✅', 'Buying', 'المشتريات', 'buying.view', 'buying', ['match', 'مطابقة', 'three-way', 'ثلاثي'])
    add('/buying/matching/tolerances', 'حدود التفاوت', 'Tolerance Configuration', '⚙️', 'Buying', 'المشتريات', 'buying.view', 'buying', ['tolerance', 'تفاوت', 'حد', 'threshold'])

    // Stock / Inventory
    add('/stock', 'المخزون', 'Inventory', '📦', 'Inventory', 'المخزون', 'stock.view', 'stock', ['stock', 'مخزون', 'inventory'])
    add('/stock/products', 'المنتجات', 'Products', '🏷️', 'Inventory', 'المخزون', 'stock.view', 'stock', ['product', 'منتج', 'صنف', 'أصناف'])
    add('/stock/products/new', 'منتج جديد', 'New Product', '➕', 'Inventory', 'المخزون', 'stock.view', 'stock', ['create', 'إنشاء'])
    add('/stock/categories', 'فئات المنتجات', 'Product Categories', '📂', 'Inventory', 'المخزون', 'stock.view', 'stock', ['category', 'فئة', 'تصنيف'])
    add('/stock/warehouses', 'المستودعات', 'Warehouses', '🏭', 'Inventory', 'المخزون', 'stock.view', 'stock', ['warehouse', 'مستودع', 'مخزن'])
    add('/stock/transfer', 'تحويل مخزون', 'Stock Transfer', '🔀', 'Inventory', 'المخزون', 'stock.view', 'stock', ['transfer', 'تحويل', 'نقل'])
    add('/stock/adjustments', 'تسويات المخزون', 'Stock Adjustments', '📝', 'Inventory', 'المخزون', 'stock.view', 'stock', ['adjustment', 'تسوية', 'جرد'])
    add('/stock/shipments', 'الشحنات', 'Shipments', '🚛', 'Inventory', 'المخزون', 'stock.view', 'stock', ['shipment', 'شحن', 'شحنة'])
    add('/stock/shipments/incoming', 'الشحنات الواردة', 'Incoming Shipments', '📥', 'Inventory', 'المخزون', 'stock.view', 'stock', ['incoming', 'وارد', 'استلام'])
    add('/stock/price-lists', 'قوائم الأسعار', 'Price Lists', '💲', 'Inventory', 'المخزون', 'stock.view', 'stock', ['price list', 'سعر', 'تسعير'])
    add('/stock/batches', 'الدفعات', 'Batches', '📋', 'Inventory', 'المخزون', 'stock.view', 'stock', ['batch', 'دفعة', 'lot'])
    add('/stock/serials', 'الأرقام التسلسلية', 'Serial Numbers', '🔢', 'Inventory', 'المخزون', 'stock.view', 'stock', ['serial', 'تسلسلي', 'رقم'])
    add('/stock/quality', 'فحص الجودة', 'Quality Inspections', '✅', 'Inventory', 'المخزون', 'stock.view', 'stock', ['quality', 'جودة', 'فحص'])
    add('/stock/cycle-counts', 'العد الدوري', 'Cycle Counts', '🔄', 'Inventory', 'المخزون', 'stock.view', 'stock', ['cycle count', 'عد', 'جرد'])
    add('/stock/reports/balance', 'تقارير المخزون', 'Stock Reports', '📊', 'Inventory', 'المخزون', 'stock.reports', 'stock', ['report', 'تقرير', 'رصيد'])
    add('/stock/reports/movements', 'حركات المخزون', 'Stock Movements', '📊', 'Inventory', 'المخزون', 'stock.reports', 'stock', ['movement', 'حركة'])
    add('/stock/valuation-report', 'تقرير التقييم', 'Inventory Valuation', '💰', 'Inventory', 'المخزون', 'reports.view', 'stock', ['valuation', 'تقييم'])
    add('/inventory/forecast', 'توقعات الطلب', 'Demand Forecasts', '📉', 'Inventory', 'المخزون', 'inventory.forecast_view', 'forecast', ['forecast', 'demand', 'تنبؤ', 'توقعات الطلب'])
    add('/inventory/forecast/generate', 'توليد توقع الطلب', 'Generate Demand Forecast', '➕', 'Inventory', 'المخزون', 'inventory.forecast_generate', 'forecast', ['forecast', 'generate', 'توليد', 'تنبؤ'])

    // Inventory Costing (FIFO/LIFO)
    add('/stock/cost-layers', 'طبقات التكلفة', 'Cost Layers', '📊', 'Inventory', 'المخزون', 'stock.view', 'stock', ['cost layer', 'طبقة', 'FIFO', 'LIFO', 'تكلفة'])
    add('/stock/costing-method', 'طريقة التكلفة', 'Costing Method', '⚙️', 'Inventory', 'المخزون', 'stock.view', 'stock', ['costing method', 'FIFO', 'LIFO', 'متوسط', 'weighted'])
    add('/stock/costing-valuation', 'تقرير تقييم التكلفة', 'Costing Valuation Report', '💰', 'Inventory', 'المخزون', 'stock.reports', 'stock', ['valuation', 'تقييم', 'costing', 'تكلفة'])

    // Manufacturing
    add('/manufacturing', 'التصنيع', 'Manufacturing', '🏭', 'Manufacturing', 'التصنيع', 'manufacturing.view', 'manufacturing', ['production', 'إنتاج', 'تصنيع'])
    add('/manufacturing/work-centers', 'مراكز العمل', 'Work Centers', '⚙️', 'Manufacturing', 'التصنيع', 'manufacturing.view', 'manufacturing', ['work center', 'مركز عمل'])
    add('/manufacturing/routes', 'مسارات التصنيع', 'Routings', '🔀', 'Manufacturing', 'التصنيع', 'manufacturing.view', 'manufacturing', ['routing', 'مسار', 'عملية'])
    add('/manufacturing/boms', 'قوائم المواد', 'Bills of Materials', '📋', 'Manufacturing', 'التصنيع', 'manufacturing.view', 'manufacturing', ['bom', 'مواد', 'تركيب', 'وصفة'])
    add('/manufacturing/orders', 'أوامر الإنتاج', 'Production Orders', '📦', 'Manufacturing', 'التصنيع', 'manufacturing.view', 'manufacturing', ['production order', 'أمر إنتاج', 'تشغيل'])
    add('/manufacturing/job-cards', 'بطاقات العمل', 'Job Cards', '🎫', 'Manufacturing', 'التصنيع', 'manufacturing.view', 'manufacturing', ['job card', 'بطاقة', 'عمل'])
    add('/manufacturing/mrp', 'تخطيط الموارد', 'MRP Planning', '📊', 'Manufacturing', 'التصنيع', 'manufacturing.view', 'manufacturing', ['mrp', 'تخطيط', 'موارد'])
    add('/manufacturing/equipment', 'المعدات والصيانة', 'Equipment', '🔧', 'Manufacturing', 'التصنيع', 'manufacturing.view', 'manufacturing', ['equipment', 'معدة', 'صيانة'])
    add('/manufacturing/schedule', 'جدول الإنتاج', 'Production Schedule', '📅', 'Manufacturing', 'التصنيع', 'manufacturing.view', 'manufacturing', ['schedule', 'جدول', 'موعد'])
    add('/manufacturing/costing', 'تكاليف التصنيع', 'Manufacturing Costing', '💰', 'Manufacturing', 'التصنيع', 'manufacturing.view', 'manufacturing', ['costing', 'تكلفة'])
    add('/manufacturing/shopfloor', 'أرضية الإنتاج', 'Shop Floor', '⚙️', 'Manufacturing', 'التصنيع', 'manufacturing.view', 'shop_floor', ['shop floor', 'shopfloor', 'أرضية الإنتاج'])
    add('/manufacturing/reports/analytics', 'تحليلات الإنتاج', 'Production Analytics', '📈', 'Manufacturing', 'التصنيع', 'manufacturing.view', 'manufacturing', ['analytics', 'تحليلات'])

    // Treasury
    add('/treasury', 'الخزينة', 'Treasury', '🏦', 'Treasury', 'الخزينة', 'treasury.view', 'treasury', ['خزينة', 'treasury'])
    add('/treasury/accounts', 'حسابات الخزينة', 'Treasury Accounts', '🏦', 'Treasury', 'الخزينة', 'treasury.view', 'treasury', ['account', 'حساب', 'بنك'])
    add('/treasury/expense', 'صرف مبلغ', 'Expense', '💸', 'Treasury', 'الخزينة', 'treasury.view', 'treasury', ['expense', 'صرف', 'مصروف'])
    add('/treasury/transfer', 'تحويل بين الحسابات', 'Transfer', '🔄', 'Treasury', 'الخزينة', 'treasury.view', 'treasury', ['transfer', 'تحويل'])
    add('/treasury/reconciliation', 'تسوية البنك', 'Bank Reconciliation', '🏧', 'Treasury', 'الخزينة', 'reconciliation.view', 'treasury', ['reconciliation', 'تسوية', 'بنك'])
    add('/treasury/checks-receivable', 'شيكات القبض', 'Checks Receivable', '📝', 'Treasury', 'الخزينة', 'treasury.view', 'treasury', ['check', 'شيك', 'قبض'])
    add('/treasury/checks-payable', 'شيكات الدفع', 'Checks Payable', '📝', 'Treasury', 'الخزينة', 'treasury.view', 'treasury', ['check', 'شيك', 'دفع'])
    add('/treasury/notes-receivable', 'أوراق القبض', 'Notes Receivable', '📄', 'Treasury', 'الخزينة', 'treasury.view', 'treasury', ['note', 'ورقة', 'قبض', 'كمبيالة'])
    add('/treasury/notes-payable', 'أوراق الدفع', 'Notes Payable', '📄', 'Treasury', 'الخزينة', 'treasury.view', 'treasury', ['note', 'ورقة', 'دفع', 'كمبيالة'])
    add('/treasury/bank-import', 'استيراد البنك', 'Bank Import', '📥', 'Treasury', 'الخزينة', 'treasury.view', 'treasury', ['bank import', 'استيراد', 'كشف بنك'])
    add('/treasury/reports/balances', 'أرصدة الخزينة', 'Treasury Balances', '📊', 'Treasury', 'الخزينة', 'treasury.view', 'treasury', ['balance', 'رصيد'])
    add('/treasury/reports/cashflow', 'التدفق النقدي', 'Cash Flow', '💵', 'Treasury', 'الخزينة', 'treasury.view', 'treasury', ['cashflow', 'تدفق', 'نقدي'])

    // Cash Flow Forecast
    add('/finance/cashflow', 'توقعات التدفق النقدي', 'Cash Flow Forecasts', '🔮', 'Treasury', 'الخزينة', 'finance.cashflow_view', 'treasury', ['forecast', 'توقع', 'تدفق', 'cash flow'])
    add('/finance/cashflow/generate', 'إنشاء توقع تدفق نقدي', 'Generate Forecast', '➕', 'Treasury', 'الخزينة', 'finance.cashflow_generate', 'treasury', ['generate', 'إنشاء', 'forecast', 'توقع'])
    add('/finance/subscriptions', 'الاشتراكات', 'Subscriptions', '🔄', 'Treasury', 'الخزينة', 'finance.subscription_view', 'treasury', ['subscription', 'plan', 'اشتراك', 'اشتراكات'])

    // HR
    add('/hr', 'الموارد البشرية', 'Human Resources', '👥', 'HR', 'الموارد البشرية', 'hr.view', 'hr', ['hr', 'موارد', 'بشرية', 'موظفين'])
    add('/hr/employees', 'الموظفين', 'Employees', '👤', 'HR', 'الموارد البشرية', 'hr.view', 'hr', ['employee', 'موظف'])
    add('/hr/departments', 'الأقسام', 'Departments', '🏢', 'HR', 'الموارد البشرية', 'hr.view', 'hr', ['department', 'قسم'])
    add('/hr/positions', 'المناصب', 'Positions', '💼', 'HR', 'الموارد البشرية', 'hr.view', 'hr', ['position', 'منصب', 'وظيفة'])
    add('/hr/payroll', 'الرواتب', 'Payroll', '💰', 'HR', 'الموارد البشرية', 'hr.view', 'hr', ['payroll', 'راتب', 'أجر', 'مسير'])
    add('/hr/loans', 'السلف', 'Loans', '💳', 'HR', 'الموارد البشرية', 'hr.view', 'hr', ['loan', 'سلفة', 'قرض'])
    add('/hr/leaves', 'الإجازات', 'Leaves', '🌴', 'HR', 'الموارد البشرية', 'hr.view', 'hr', ['leave', 'إجازة', 'غياب'])
    add('/hr/attendance', 'الحضور والانصراف', 'Attendance', '⏰', 'HR', 'الموارد البشرية', 'hr.view', 'hr', ['attendance', 'حضور', 'انصراف'])
    add('/hr/salary-structures', 'هياكل الرواتب', 'Salary Structures', '📊', 'HR', 'الموارد البشرية', 'hr.view', 'hr', ['salary', 'هيكل', 'بدل'])
    add('/hr/overtime', 'العمل الإضافي', 'Overtime', '⏱️', 'HR', 'الموارد البشرية', 'hr.view', 'hr', ['overtime', 'إضافي', 'ساعات'])
    add('/hr/gosi', 'التأمينات الاجتماعية', 'GOSI Settings', '🏥', 'HR', 'الموارد البشرية', 'hr.view', 'hr', ['gosi', 'تأمينات', 'اجتماعية'])
    add('/hr/documents', 'مستندات الموظفين', 'Employee Documents', '📄', 'HR', 'الموارد البشرية', 'hr.view', 'hr', ['document', 'مستند', 'وثيقة'])
    add('/hr/performance', 'تقييم الأداء', 'Performance Reviews', '⭐', 'HR', 'الموارد البشرية', 'hr.performance_view', 'hr', ['performance', 'أداء', 'تقييم'])
    add('/hr/training', 'البرامج التدريبية', 'Training Programs', '📚', 'HR', 'الموارد البشرية', 'hr.view', 'hr', ['training', 'تدريب'])
    add('/hr/violations', 'المخالفات', 'Violations', '⚠️', 'HR', 'الموارد البشرية', 'hr.view', 'hr', ['violation', 'مخالفة', 'جزاء'])
    add('/hr/custody', 'العهد', 'Custody Management', '🔑', 'HR', 'الموارد البشرية', 'hr.view', 'hr', ['custody', 'عهدة'])
    add('/hr/payslips', 'قسائم الرواتب', 'Payslips', '🧾', 'HR', 'الموارد البشرية', 'hr.view', 'hr', ['payslip', 'قسيمة', 'مسير'])
    add('/hr/recruitment', 'التوظيف', 'Recruitment', '🎯', 'HR', 'الموارد البشرية', 'hr.view', 'hr', ['recruitment', 'توظيف', 'مقابلة'])
    add('/hr/wps', 'حماية الأجور', 'WPS Export', '🏧', 'HR', 'الموارد البشرية', 'hr.view', 'hr', ['wps', 'حماية أجور'])
    add('/hr/saudization', 'السعودة', 'Saudization', '🇸🇦', 'HR', 'الموارد البشرية', 'hr.view', 'hr', ['saudization', 'سعودة', 'توطين'])
    add('/hr/end-of-service', 'مكافأة نهاية الخدمة', 'End of Service', '🎓', 'HR', 'الموارد البشرية', 'hr.view', 'hr', ['end of service', 'نهاية خدمة', 'مكافأة'])
    add('/hr/reports', 'تقارير الموارد البشرية', 'HR Reports', '📈', 'HR', 'الموارد البشرية', 'hr.reports', 'hr', ['report', 'تقرير'])

    // Employee Self-Service
    add('/hr/self-service', 'الخدمة الذاتية', 'Self-Service Portal', '👤', 'HR', 'الموارد البشرية', 'hr.self_service', 'hr', ['self-service', 'خدمة ذاتية', 'employee'])
    add('/hr/self-service/leave-request', 'طلب إجازة', 'Leave Request', '🏖️', 'HR', 'الموارد البشرية', 'hr.self_service', 'hr', ['leave', 'إجازة', 'طلب'])
    add('/hr/self-service/payslips', 'قسائم راتبي', 'My Payslips', '💰', 'HR', 'الموارد البشرية', 'hr.self_service', 'hr', ['payslip', 'قسيمة', 'راتب'])
    add('/hr/self-service/profile', 'ملفي الشخصي', 'My Profile', '📝', 'HR', 'الموارد البشرية', 'hr.self_service', 'hr', ['profile', 'ملف', 'شخصي'])
    add('/hr/self-service/team-requests', 'طلبات الفريق', 'Team Requests', '👥', 'HR', 'الموارد البشرية', 'hr.self_service_approve', 'hr', ['team', 'فريق', 'طلبات', 'approve'])

    // Assets
    add('/assets', 'الأصول الثابتة', 'Fixed Assets', '🏗️', 'Assets', 'الأصول', 'assets.view', 'assets', ['asset', 'أصل', 'أصول'])
    add('/assets/new', 'أصل جديد', 'New Asset', '➕', 'Assets', 'الأصول', 'assets.view', 'assets', ['create', 'إنشاء'])
    add('/assets/management', 'إدارة الأصول', 'Asset Management', '⚙️', 'Assets', 'الأصول', 'assets.view', 'assets', ['management', 'إهلاك', 'استهلاك'])

    // Projects
    add('/projects', 'المشاريع', 'Projects', '📐', 'Projects', 'المشاريع', 'projects.view', 'projects', ['project', 'مشروع'])
    add('/projects/new', 'مشروع جديد', 'New Project', '➕', 'Projects', 'المشاريع', 'projects.create', 'projects', ['create', 'إنشاء'])
    add('/projects/resources', 'إدارة الموارد', 'Resource Management', '👥', 'Projects', 'المشاريع', 'projects.view', 'projects', ['resource', 'مورد', 'فريق'])
    add('/projects/timetracking', 'تتبع الوقت', 'Time Tracking', '⏱️', 'Projects', 'المشاريع', 'projects.time_view', 'projects', ['time', 'timesheet', 'تتبع الوقت', 'ساعات'])
    add('/projects/timetracking/team', 'طلبات الوقت للفريق', 'Team Timesheets', '👥', 'Projects', 'المشاريع', 'projects.time_approve', 'projects', ['team', 'approve', 'اعتماد', 'فريق'])
    add('/projects/timetracking/profitability', 'ربحية المشاريع', 'Project Profitability', '💰', 'Projects', 'المشاريع', 'projects.time_view', 'projects', ['profitability', 'ربحية', 'ساعات'])
    add('/projects/resources/availability', 'تخطيط الموارد', 'Resource Planning', '📅', 'Projects', 'المشاريع', 'projects.resource_view', 'projects', ['resource planning', 'availability', 'تخطيط الموارد'])
    add('/projects/resources/allocate', 'تخصيص الموارد', 'Allocate Resource', '🧭', 'Projects', 'المشاريع', 'projects.resource_manage', 'projects', ['allocate', 'تخصيص', 'resource'])
    add('/projects/reports/financials', 'ماليات المشاريع', 'Project Financials', '💰', 'Projects', 'المشاريع', 'projects.view', 'projects', ['financial', 'مالي', 'ربح'])
    add('/projects/reports/resources', 'استخدام الموارد', 'Resource Utilization', '📊', 'Projects', 'المشاريع', 'projects.view', 'projects', ['utilization', 'استخدام'])

    // Expenses
    add('/expenses', 'المصروفات', 'Expenses', '💸', 'Expenses', 'المصروفات', 'expenses.view', 'expenses', ['expense', 'مصروف', 'صرف'])
    add('/expenses/new', 'مصروف جديد', 'New Expense', '➕', 'Expenses', 'المصروفات', 'expenses.create', 'expenses', ['create', 'إنشاء'])

    // Taxes
    add('/taxes', 'الضرائب', 'Taxes', '🧾', 'Taxes', 'الضرائب', 'accounting.view', 'taxes', ['tax', 'ضريبة'])
    add('/taxes/returns/new', 'إقرار ضريبي جديد', 'New Tax Return', '➕', 'Taxes', 'الضرائب', 'taxes.manage', 'taxes', ['return', 'إقرار'])
    add('/taxes/wht', 'ضريبة الاستقطاع', 'Withholding Tax', '📋', 'Taxes', 'الضرائب', 'taxes.view', 'taxes', ['withholding', 'استقطاع'])
    add('/taxes/compliance', 'الامتثال الضريبي', 'Tax Compliance', '✅', 'Taxes', 'الضرائب', 'taxes.view', 'taxes', ['compliance', 'امتثال'])
    add('/taxes/calendar', 'التقويم الضريبي', 'Tax Calendar', '📅', 'Taxes', 'الضرائب', 'taxes.view', 'taxes', ['calendar', 'تقويم', 'مواعيد'])

    // CRM
    add('/crm', 'إدارة العلاقات', 'CRM', '🤝', 'CRM', 'إدارة العلاقات', 'sales.view', 'crm', ['crm', 'علاقات', 'عملاء'])
    add('/crm/opportunities', 'الفرص البيعية', 'Opportunities', '🎯', 'CRM', 'إدارة العلاقات', 'sales.view', 'crm', ['opportunity', 'فرصة', 'بيعية'])
    add('/crm/tickets', 'تذاكر الدعم', 'Support Tickets', '🎫', 'CRM', 'إدارة العلاقات', 'sales.view', 'crm', ['ticket', 'تذكرة', 'دعم'])
    add('/crm/campaigns', 'الحملات التسويقية', 'Marketing Campaigns', '📣', 'CRM', 'إدارة العلاقات', 'crm.campaign_view', 'crm', ['campaign', 'حملة', 'تسويق'])
    add('/crm/knowledge-base', 'قاعدة المعرفة', 'Knowledge Base', '📚', 'CRM', 'إدارة العلاقات', 'sales.view', 'crm', ['knowledge', 'معرفة'])

    // Services
    add('/services', 'الخدمات والصيانة', 'Services', '🔧', 'Services', 'الخدمات', 'services.view', 'services', ['service', 'خدمة', 'صيانة'])
    add('/services/requests', 'طلبات الخدمة', 'Service Requests', '📝', 'Services', 'الخدمات', 'services.view', 'services', ['request', 'طلب'])
    add('/services/documents', 'إدارة المستندات', 'Document Management', '📁', 'Services', 'الخدمات', 'services.view', 'services', ['document', 'مستند', 'ملف'])

    // Reports
    add('/reports', 'مركز التقارير', 'Report Center', '📈', 'Reports', 'التقارير', 'reports.view', 'reports', ['report', 'تقرير'])
    add('/reports/builder', 'منشئ التقارير', 'Report Builder', '🔨', 'Reports', 'التقارير', 'reports.create', 'reports', ['builder', 'بناء', 'إنشاء'])
    add('/reports/scheduled', 'التقارير المجدولة', 'Scheduled Reports', '⏰', 'Reports', 'التقارير', 'reports.view', 'reports', ['scheduled', 'مجدول'])
    add('/reports/detailed-pl', 'الأرباح والخسائر التفصيلي', 'Detailed P&L', '📊', 'Reports', 'التقارير', 'accounting.view', 'reports', ['profit', 'loss', 'أرباح', 'خسائر'])
    add('/reports/shared', 'التقارير المشتركة', 'Shared Reports', '🔗', 'Reports', 'التقارير', 'reports.view', 'reports', ['shared', 'مشترك'])
    add('/reports/consolidation', 'تقارير التجميع', 'Consolidation Reports', '📊', 'Reports', 'التقارير', 'reports.view', 'reports', ['consolidation', 'تجميع'])
    add('/analytics', 'تحليلات IBI', 'BI Analytics', '📊', 'Reports', 'التقارير', 'dashboard.analytics_view', 'reports', ['ibi', 'analytics', 'dashboard', 'تحليلات', 'لوحات'])
    add('/analytics/new', 'لوحة IBI جديدة', 'New BI Dashboard', '➕', 'Reports', 'التقارير', 'dashboard.analytics_manage', 'reports', ['ibi', 'new dashboard', 'analytics', 'جديد'])

    // Admin / Settings
    add('/approvals', 'الاعتمادات', 'Approvals', '✅', 'Admin', 'الإدارة', 'approvals.view', 'approvals', ['approval', 'اعتماد', 'موافقة'])
    add('/data-import', 'استيراد البيانات', 'Data Import', '📥', 'Admin', 'الإدارة', 'data_import.view', 'data_import', ['import', 'استيراد', 'بيانات'])
    add('/admin/audit-logs', 'سجلات المراقبة', 'Audit Logs', '📋', 'Admin', 'الإدارة', 'audit.view', 'audit', ['audit', 'سجل', 'مراقبة'])
    add('/admin/roles', 'إدارة الأدوار', 'Role Management', '🔐', 'Admin', 'الإدارة', 'admin.roles', null, ['role', 'دور', 'صلاحية'])
    add('/settings', 'الإعدادات', 'Settings', '⚙️', 'Admin', 'الإدارة', 'settings.view', null, ['settings', 'إعدادات', 'ضبط'])
    add('/settings/branches', 'الفروع', 'Branches', '🏢', 'Admin', 'الإدارة', 'branches.view', null, ['branch', 'فرع'])
    add('/settings/costing-policy', 'سياسة التكلفة', 'Costing Policy', '💹', 'Admin', 'الإدارة', 'settings.view', null, ['costing', 'تكلفة', 'سياسة'])
    add('/settings/api-keys', 'مفاتيح API', 'API Keys', '🔑', 'Admin', 'الإدارة', 'settings.view', null, ['api', 'key', 'مفتاح'])
    add('/settings/webhooks', 'الويب هوك', 'Webhooks', '🔗', 'Admin', 'الإدارة', 'settings.view', null, ['webhook', 'ويب هوك'])
    add('/settings/sso', 'الدخول الموحد', 'SSO Configuration', '🔑', 'Admin', 'الإدارة', 'settings.view', null, ['sso', 'دخول موحد', 'SAML', 'OAuth'])
    add('/settings/sso/new', 'إعداد SSO جديد', 'New SSO Configuration', '➕', 'Admin', 'الإدارة', 'settings.manage', null, ['sso', 'create', 'إنشاء'])
    add('/settings/print-templates', 'قوالب الطباعة', 'Print Templates', '🖨️', 'Admin', 'الإدارة', 'settings.view', null, ['print', 'طباعة', 'قالب', 'فاتورة'])
    add('/settings/smart-alerts', 'التنبيهات الذكية', 'Smart Alerts', '🔔', 'Admin', 'الإدارة', 'settings.view', null, ['alerts', 'تنبيهات', 'إشعارات', 'smart'])
    add('/settings/email-templates', 'قوالب البريد الإلكتروني', 'Email Templates', '✉️', 'Admin', 'الإدارة', 'settings.view', null, ['email', 'بريد', 'قالب', 'template'])
    add('/settings/integration-dlq', 'قوائم الفشل - DLQ', 'Integration DLQ', '⚠️', 'Admin', 'الإدارة', 'admin', null, ['dlq', 'retry', 'إعادة', 'فشل', 'integration'])
    add('/admin/company-profile', 'ملف الشركة', 'Company Profile', '🏢', 'Admin', 'الإدارة', null, null, ['company', 'شركة', 'ملف'])
    add('/profile', 'الملف الشخصي', 'My Profile', '👤', 'General', 'عام', null, null, ['profile', 'ملف شخصي', 'حساب'])

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
  const inputRef = useRef(null)
  const listRef = useRef(null)
  const isArabic = i18n.language === 'ar'
  const pages = useSearchablePages()

  const results = useMemo(() => {
    if (!query.trim()) {
      // Show recent/popular pages when empty
      const popular = ['/dashboard', '/sales/invoices', '/buying/invoices', '/stock/products', '/accounting/journal-entries', '/hr/employees', '/treasury/accounts', '/sales/customers']
      return pages.filter(p => popular.includes(p.path)).slice(0, 8)
    }

    return pages
      .map(p => ({ ...p, score: matchScore(query, p, isArabic) }))
      .filter(p => p.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 12)
  }, [query, pages, isArabic])

  // Group results by category
  const groupedResults = useMemo(() => {
    const groups = {}
    const flatList = []
    results.forEach((r, idx) => {
      const cat = isArabic ? r.categoryAr : r.category
      if (!groups[cat]) groups[cat] = []
      groups[cat].push({ ...r, flatIndex: flatList.length })
      flatList.push(r)
    })
    return { groups, flatList }
  }, [results, isArabic])

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

  const handleSelect = useCallback((page) => {
    navigate(page.path)
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
            <kbd className="global-search-kbd">ESC</kbd>
          </div>
        </div>

        {/* Results */}
        <div className="global-search-results" ref={listRef}>
          {groupedResults.flatList.length === 0 && query.trim() ? (
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
                      key={item.path}
                      data-index={item.flatIndex}
                      className={`global-search-item ${item.flatIndex === selectedIndex ? 'selected' : ''}`}
                      onClick={() => handleSelect(item)}
                      onMouseEnter={() => setSelectedIndex(item.flatIndex)}
                    >
                      <span className="global-search-item-icon">{item.icon}</span>
                      <div className="global-search-item-text">
                        <span className="global-search-item-label">
                          {isArabic ? item.labelAr : item.labelEn}
                        </span>
                        <span className="global-search-item-path">
                          {isArabic ? item.labelEn : item.labelAr}
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
