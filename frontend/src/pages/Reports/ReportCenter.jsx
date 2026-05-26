import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { hasPermission, getUser } from '../../utils/auth';
import { resolveIndustryCode } from '../../config/industryModules';
import BackButton from '../../components/common/BackButton';

// Industry-specific report groups mapping
const INDUSTRY_REPORTS_MAP = {
    restaurant: (t) => ({
        title: t('industry_reports.title'),
        icon: '🍽️',
        color: '#EF4444',
        reports: [
            { name: t('industry_reports.food_cost'), path: '/reports/industry/food-cost', desc: t('industry_reports.food_cost_desc') },
        ]
    }),
    manufacturing: (t) => ({
        title: t('industry_reports.title'),
        icon: '🏭',
        color: '#6366f1',
        reports: [
            { name: t('industry_reports.production_cost'), path: '/reports/industry/production-cost', desc: t('industry_reports.production_cost_desc') },
        ]
    }),
    construction: (t) => ({
        title: t('industry_reports.title'),
        icon: '🏗️',
        color: '#F59E0B',
        reports: [
            { name: t('industry_reports.progress_billing'), path: '/reports/industry/progress-billing', desc: t('industry_reports.progress_billing_desc') },
        ]
    }),
    services: (t) => ({
        title: t('industry_reports.title'),
        icon: '💼',
        color: '#8B5CF6',
        reports: [
            { name: t('industry_reports.utilization'), path: '/reports/industry/utilization', desc: t('industry_reports.utilization_desc') },
        ]
    }),
    pharmacy: (t) => ({
        title: t('industry_reports.title'),
        icon: '💊',
        color: '#10B981',
        reports: [
            { name: t('industry_reports.drug_expiry'), path: '/reports/industry/drug-expiry', desc: t('industry_reports.drug_expiry_desc') },
        ]
    }),
    workshop: (t) => ({
        title: t('industry_reports.title'),
        icon: '🔧',
        color: '#6B7280',
        reports: [
            { name: t('industry_reports.workshop_revenue'), path: '/reports/industry/workshop-revenue', desc: t('industry_reports.workshop_revenue_desc') },
        ]
    }),
    ecommerce: (t) => ({
        title: t('industry_reports.title'),
        icon: '🛒',
        color: '#3B82F6',
        reports: [
            { name: t('industry_reports.ecom_returns'), path: '/reports/industry/ecom-returns', desc: t('industry_reports.ecom_returns_desc') },
        ]
    }),
    wholesale: (t) => ({
        title: t('industry_reports.title'),
        icon: '📦',
        color: '#0EA5E9',
        reports: [
            { name: t('industry_reports.agent_performance'), path: '/reports/industry/agent-performance', desc: t('industry_reports.agent_performance_desc') },
        ]
    }),
    logistics: (t) => ({
        title: t('industry_reports.title'),
        icon: '🚛',
        color: '#14B8A6',
        reports: [
            { name: t('industry_reports.fleet_tracking'), path: '/reports/industry/fleet-tracking', desc: t('industry_reports.fleet_tracking_desc') },
        ]
    }),
    agriculture: (t) => ({
        title: t('industry_reports.title'),
        icon: '🌾',
        color: '#65A30D',
        reports: [
            { name: t('industry_reports.crop_yield'), path: '/reports/industry/crop-yield', desc: t('industry_reports.crop_yield_desc') },
        ]
    }),
}

function _getIndustryReportGroup(t, user) {
    // user.industry_type may be key (RT/FB) or code (retail/restaurant) — normalize to code
    const industryCode = resolveIndustryCode(user?.industry_type)
    if (!industryCode || industryCode === 'general' || !INDUSTRY_REPORTS_MAP[industryCode]) return []
    
    const builder = INDUSTRY_REPORTS_MAP[industryCode]
    const group = builder(t)
    return [{
        ...group,
        permission: 'reports.view',
        module: 'reports',
    }]
}

const ReportCenter = () => {
    const { t, i18n } = useTranslation();
    const navigate = useNavigate();

    const reportGroups = [
        {
            title: t('reports_center.groups.sales'),
            icon: '📊',
            color: '#10B981',
            permission: 'sales.reports',
            module: 'sales',
            reports: [
                { name: t('reports_center.reports.sales_analytics'), path: '/sales/reports/analytics', desc: t('reports_center.reports.sales_analytics_desc') },
                { name: t('reports_center.reports.customer_statement'), path: '/sales/reports/customer-statement', desc: t('reports_center.reports.customer_statement_desc') },
                { name: t('reports_center.reports.aging_report'), path: '/sales/reports/aging', desc: t('reports_center.reports.aging_report_desc') },
                { name: t('reports.commissions.title', 'Sales Commission Report'), path: '/sales/commissions', desc: t('reports_center.reports.commissions_desc', 'Track salesperson commissions and payouts') }
            ]
        },
        {
            title: t('reports_center.groups.buying'),
            icon: '🛒',
            color: '#3B82F6',
            permission: 'buying.reports',
            module: 'buying',
            reports: [
                { name: t('reports_center.reports.buying_analytics'), path: '/buying/reports/analytics', desc: t('reports_center.reports.buying_analytics_desc') },
                { name: t('reports_center.reports.supplier_statement'), path: '/buying/reports/supplier-statement', desc: t('reports_center.reports.supplier_statement_desc') },
                { name: t('purchases_aging.title'), path: '/buying/reports/aging', desc: t('purchases_aging.subtitle') }
            ]
        },
        {
            title: t('reports_center.groups.stock'),
            icon: '📦',
            color: '#F59E0B',
            permission: 'stock.reports',
            module: 'stock',
            reports: [
                { name: t('reports_center.reports.stock_balance'), path: '/stock/reports', desc: t('reports_center.reports.stock_balance_desc') },
                { name: t('reports_center.reports.stock_movements'), path: '/stock/reports/movements', desc: t('reports_center.reports.stock_movements_desc') },
                { name: t('reports_center.reports.profitability', 'تقرير الربحية'), path: '/stock/reports/profitability', desc: t('reports_center.reports.profitability_desc', 'تحليل الربح الإجمالي لكل منتج') }
            ]
        },
        {
            title: t('reports_center.groups.accounting'),
            icon: '📒',
            color: '#8B5CF6',
            permission: 'accounting.view',
            module: 'accounting',
            reports: [
                { name: t('reports_center.reports.trial_balance'), path: '/accounting/trial-balance', desc: t('reports_center.reports.trial_balance_desc') },
                { name: t('accounting.home.links.general_ledger'), path: '/accounting/general-ledger', desc: t('accounting.general_ledger.subtitle') },
                { name: t('accounting.home.links.income_statement'), path: '/accounting/income-statement', desc: t('accounting.income_statement.subtitle') },
                { name: t('accounting.home.links.balance_sheet'), path: '/accounting/balance-sheet', desc: t('accounting.balance_sheet.subtitle') },
                { name: t('reports_center.reports.cashflow'), path: '/accounting/cashflow', desc: t('reports_center.reports.cashflow_desc') },
                { name: t('cashflow_ias7.title'), path: '/reports/cashflow-ias7', desc: t('cashflow_ias7.subtitle') },
                { name: t('fx_report.title'), path: '/reports/fx-gain-loss', desc: t('fx_report.subtitle') },
                { name: t('consolidation.title'), path: '/reports/consolidation', desc: t('consolidation.subtitle') },
                { name: t('reports.detailed_pl.title', 'Detailed P&L'), path: '/reports/detailed-pl', desc: t('reports_center.reports.detailed_pl_desc', 'Profit & loss breakdown by customer, product, or category') }
            ]
        },
        {
            title: t('reports_center.groups.treasury'),
            icon: '🏦',
            color: '#06B6D4',
            permission: 'treasury.view',
            module: 'treasury',
            reports: [
                { name: t('reports_center.reports.treasury_balances'), path: '/treasury/reports/balances', desc: t('reports_center.reports.treasury_balances_desc') },
                { name: t('reports_center.reports.treasury_cashflow'), path: '/treasury/reports/cashflow', desc: t('reports_center.reports.treasury_cashflow_desc') },
                { name: t('checks_aging.title'), path: '/treasury/reports/checks-aging', desc: t('checks_aging.subtitle') }
            ]
        },
        {
            title: t('reports_center.groups.manufacturing', 'Manufacturing'),
            icon: '🏭',
            color: '#6366f1',
            permission: 'manufacturing.view',
            module: 'manufacturing',
            reports: [
                { name: t('reports_center.reports.production_analytics', 'Production Analytics'), path: '/manufacturing/reports/analytics', desc: t('reports_center.reports.production_analytics_desc', 'Monitor production output and efficiency') },
                { name: t('reports_center.reports.work_order_status', 'Work Order Status'), path: '/manufacturing/reports/work-orders', desc: t('reports_center.reports.work_order_status_desc', 'Track status and progress of work orders') }
            ]
        },
        {
            title: t('reports_center.groups.assets', 'Fixed Assets'),
            icon: '🏗️',
            color: '#D97706',
            permission: 'assets.view',
            module: 'assets',
            reports: [
                { name: t('asset_reports.title'), path: '/assets/reports', desc: t('asset_reports.subtitle') }
            ]
        },
        {
            title: t('reports_center.groups.projects', 'Projects'),
            icon: '🏗️',
            color: '#8b5cf6',
            permission: 'projects.view',
            module: 'projects',
            reports: [
                { name: t('reports_center.reports.project_financials', 'Project Financials'), path: '/projects/reports/financials', desc: t('reports_center.reports.project_financials_desc', 'Profitability and cost analysis per project') },
                { name: t('reports_center.reports.resource_utilization', 'Resource Utilization'), path: '/projects/reports/resources', desc: t('reports_center.reports.resource_utilization_desc', 'Track employee allocation and workload') }
            ]
        },
        {
            title: t('reports_center.groups.hr'),
            icon: '👥',
            color: '#EC4899',
            permission: 'hr.view',
            module: 'hr',
            reports: [
                { name: t('reports_center.reports.payroll_trend'), path: '/hr/reports', desc: t('reports_center.reports.payroll_trend_desc') },
                { name: t('reports_center.reports.leave_usage'), path: '/hr/reports', desc: t('reports_center.reports.leave_usage_desc') }
            ]
        },
        {
            title: t('reports_center.groups.taxes'),
            icon: '🧾',
            color: '#F97316',
            permission: 'accounting.view',
            module: 'taxes',
            reports: [
                { name: t('reports_center.reports.vat_report'), path: '/taxes', desc: t('reports_center.reports.vat_report_desc') },
                { name: t('reports_center.reports.tax_audit'), path: '/taxes', desc: t('reports_center.reports.tax_audit_desc') }
            ]
        },
        {
            title: t('reports_center.groups.custom', 'Custom Reports'),
            icon: '✨',
            color: '#DB2777',
            permission: 'reports.create',
            module: 'reports',
            reports: [
                { name: t('reports_center.reports.builder', 'Report Builder'), path: '/reports/builder', desc: t('reports_center.reports.builder_desc', 'Create and save custom reports') },
                { name: t('reports.scheduled.title', 'Scheduled Reports'), path: '/reports/scheduled', desc: t('reports_center.reports.scheduled_desc', 'Automate report delivery via email') },
                { name: t('reports.sharing.shared_with_me', 'Shared With Me'), path: '/reports/shared', desc: t('reports_center.reports.shared_desc', 'Reports that colleagues have shared with you') }
            ]
        },
        {
            title: t('analytics.title'),
            icon: '📊',
            color: '#0EA5E9',
            permission: 'dashboard.analytics_view',
            module: 'reports',
            reports: [
                { name: t('analytics.title'), path: '/analytics', desc: t('reports_center.reports.bi_analytics_desc', 'Interactive BI dashboards and KPI exploration') }
            ]
        },
        {
            title: t('reports_center.groups.operations', 'العمليات والصيانة'),
            icon: '⚙️',
            color: '#F59E0B',
            permission: 'reports.view',
            module: 'reports',
            reports: [
                { name: t('kpi_admin.title', 'إدارة مؤشرات الأداء'), path: '/reports/kpi-admin', permission: 'dashboard.analytics_manage', desc: t('kpi_admin.subtitle', 'إنشاء ومراقبة مؤشرات الأداء الرئيسية') },
                { name: t('scheduler.title', 'جدولة العمليات'), path: '/admin/ops/scheduler', permission: 'ops.scheduler.admin', desc: t('scheduler.subtitle', 'مراقبة وإدارة المهام المجدولة') },
                { name: t('health.title', 'صحة النظام'), path: '/health/detailed', desc: t('health.subtitle', 'حالة جميع مكونات النظام') },
            ]
        },
        // ── Industry-specific reports — dynamic ──
        ..._getIndustryReportGroup(t, getUser()),
    ].filter(g => {
        // Permission check
        if (!hasPermission(g.permission || 'reports.view')) return false
        // MODULE-001: Module check — hide report groups for disabled modules
        const user = getUser()
        const enabledModules = user?.enabled_modules || []
        if (enabledModules.length > 0 && g.module) {
            return enabledModules.includes(g.module)
        }
        return true
    }).map(g => ({
        ...g,
        reports: g.reports.filter(report => !report.permission || hasPermission(report.permission)),
    })).filter(g => g.reports.length > 0);

    const totalReports = reportGroups.reduce((sum, g) => sum + g.reports.length, 0);

    return (
        <div className="workspace fade-in">
            {/* Header Section */}
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">📈 {t('reports_center.title')}</h1>
                    <p className="workspace-subtitle">{t('reports_center.subtitle')}</p>
                </div>
            </div>

            {/* Summary Stats */}
            <div className="metrics-grid" style={{ marginBottom: '24px' }}>
                <div className="metric-card">
                    <div className="metric-label">{t('reports_center.metrics.total_reports')}</div>
                    <div className="metric-value text-primary">{totalReports}</div>
                    <div className="metric-change">{t('reports_center.metrics.reports_available')}</div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('reports_center.metrics.main_sections')}</div>
                    <div className="metric-value text-secondary">{reportGroups.length}</div>
                    <div className="metric-change">{t('reports_center.metrics.sections_list')}</div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('reports_center.metrics.system_status')}</div>
                    <div className="metric-value text-success">{t('reports_center.metrics.active')}</div>
                    <div className="metric-change">{t('reports_center.metrics.availability')}</div>
                </div>
            </div>

            {/* Reports Grid */}
            <div className="modules-grid">
                {reportGroups.map((group, idx) => (
                    <div key={idx} className="section-card" style={{ borderTop: `4px solid ${group.color}` }}>
                        <h3 className="section-title" style={{ color: group.color, borderBottom: 'none', paddingBottom: '8px' }}>
                            {group.icon} {group.title}
                        </h3>
                        <div className="links-list">
                            {group.reports.map((report, rIdx) => (
                                <div
                                    key={rIdx}
                                    className="link-item"
                                    onClick={() => navigate(report.path)}
                                    style={{
                                        padding: '14px 12px',
                                        marginBottom: '8px',
                                        background: 'var(--bg-secondary)',
                                        borderRadius: 'var(--radius)',
                                        border: '1px solid var(--border-color)'
                                    }}
                                >
                                    <div style={{ flex: 1 }}>
                                        <div style={{ fontWeight: '600', marginBottom: '4px', color: 'var(--text-primary)' }}>
                                            {report.name}
                                        </div>
                                        <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                                            {report.desc}
                                        </div>
                                    </div>
                                    <span className="link-arrow" style={{ fontSize: '18px' }}>
                                        {i18n.language === 'ar' ? '←' : '→'}
                                    </span>
                                </div>
                            ))}
                        </div>
                    </div>
                ))}
            </div>

            {/* Quick Actions */}
            <div className="section-card" style={{ marginTop: '24px', textAlign: 'center' }}>
                <h3 className="section-title" style={{ textAlign: 'center', borderBottom: 'none' }}>
                    🚀 {t('reports_center.quick_access.title')}
                </h3>
                <div style={{ display: 'flex', gap: '12px', justifyContent: 'center', flexWrap: 'wrap' }}>
                    <button className="btn btn-primary" onClick={() => navigate('/sales/reports/analytics')}>
                        📊 {t('reports_center.reports.sales_analytics')}
                    </button>
                    <button className="btn btn-secondary" onClick={() => navigate('/buying/reports/analytics')}>
                        📈 {t('reports_center.reports.buying_analytics')}
                    </button>
                    <button className="btn btn-secondary" onClick={() => navigate('/sales/reports/aging')}>
                        ⏳ {t('reports_center.reports.aging_report')}
                    </button>
                    <button className="btn btn-secondary" onClick={() => navigate('/treasury/reports/balances')}>
                        🏦 {t('reports_center.reports.treasury_balances')}
                    </button>
                    <button className="btn btn-secondary" onClick={() => navigate('/accounting/cashflow')}>
                        💸 {t('reports_center.reports.cashflow')}
                    </button>
                    <button className="btn btn-secondary" onClick={() => navigate('/reports/scheduled')}>
                        ⏰ {t('reports.scheduled.title', 'Scheduled Reports')}
                    </button>
                    <button className="btn btn-secondary" onClick={() => navigate('/reports/detailed-pl')}>
                        📊 {t('reports.detailed_pl.title', 'Detailed P&L')}
                    </button>
                    <button className="btn btn-secondary" onClick={() => navigate('/sales/commissions')}>
                        💰 {t('reports.commissions.title', 'Commissions')}
                    </button>
                </div>
            </div>
        </div>
    );
};

export default ReportCenter;
