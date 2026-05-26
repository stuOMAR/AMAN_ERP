import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { companiesAPI, settingsAPI } from '../../utils/api';
import { getUser, updateUser, hasPermission } from '../../utils/auth';
import api from '../../utils/api';
import {
    Settings, Wallet, Palette, ShoppingCart, Truck, Users, Box, FileText,
    Heart, Monitor, Bell, BarChart3, ShieldCheck, Link, Zap, Receipt,
    Briefcase, CheckSquare, Share2, GitBranch, History, Database,
    Sparkles, Key, Globe, Scale, Building2, Upload, Layers, HardDrive
} from 'lucide-react';
import BackButton from '../../components/common/BackButton';
import GeneralSettings from './tabs/GeneralSettings';
import FinancialSettings from './tabs/FinancialSettings';
import BrandingSettings from './tabs/BrandingSettings';
import InvoicingSettings from './tabs/InvoicingSettings';
import InventorySettings from './tabs/InventorySettings';
import AccountingMappingSettings from './tabs/AccountingMappingSettings';
import POSSettings from './tabs/POSSettings';
import SalesSettings from './tabs/SalesSettings';
import PurchasesSettings from './tabs/PurchasesSettings';
import SecuritySettings from './tabs/SecuritySettings';
import NotificationSettings from './tabs/NotificationSettings';
import HRSettings from './tabs/HRSettings';
import CRMSettings from './tabs/CRMSettings';
import IntegrationSettings from './tabs/IntegrationSettings';
import ReportingSettings from './tabs/ReportingSettings';
import PerformanceSettings from './tabs/PerformanceSettings';
import ExpensesSettings from './tabs/ExpensesSettings';
import ProjectsSettings from './tabs/ProjectsSettings';
import ComplianceSettings from './tabs/ComplianceSettings';
import BranchesSettings from './tabs/BranchesSettings';
import WorkflowSettings from './tabs/WorkflowSettings';
import AuditSettings from './tabs/AuditSettings';
import ComingSoon from './tabs/ComingSoon';
import { PageLoading, Spinner } from '../../components/common/LoadingStates'

const CompanySettings = () => {
    const { t, i18n } = useTranslation();
    const [searchParams, setSearchParams] = useSearchParams();
    const navigate = useNavigate();
    const user = getUser();

    // UI State derived from URL
    const activeTab = searchParams.get('tab') || 'general';
    const showDashboard = !searchParams.has('tab');

    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState('');
    const [success, setSuccess] = useState('');

    // Core Data
    const [formData, setFormData] = useState({
        company_name: '', company_name_en: '', email: '', phone: '',
        tax_number: '', commercial_registry: '', address: '', currency: '', plan_type: ''
    });

    // Extended Settings
    const [settingsData, setSettingsData] = useState({});
    const [initialSettingsData, setInitialSettingsData] = useState({});

    // Define allTabs as a constant array (must be defined before useMemo)
    const enabledModules = user?.enabled_modules || [];
    const isModOn = (mod) => !enabledModules.length || enabledModules.includes(mod);

    const allTabs = React.useMemo(() => [
        { id: 'general', label: t('settings.tabs.general'), icon: Settings, gradient: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', desc: t('settings.tabs_desc.general'), permission: 'settings.manage' },
        { id: 'financial', label: t('settings.tabs.financial'), icon: Wallet, gradient: 'linear-gradient(135deg, #11998e 0%, #38ef7d 100%)', desc: t('settings.tabs_desc.financial'), permission: 'settings.manage' },
        { id: 'accounting', label: t('settings.tabs.accounting') || '{t("settings.accounting_link")}', icon: Database, gradient: 'linear-gradient(135deg, #4b6cb7 0%, #182848 100%)', desc: t('settings.tabs_desc.accounting') || '{t("settings.accounting_link_desc")}', permission: 'accounting.manage', module: 'accounting' },
        { id: 'branding', label: t('settings.tabs.branding'), icon: Palette, gradient: 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)', desc: t('settings.tabs_desc.branding'), permission: 'settings.manage' },
        { id: 'sales', label: t('settings.tabs.sales'), icon: ShoppingCart, gradient: 'linear-gradient(135deg, #fa709a 0%, #fee140 100%)', desc: t('settings.tabs_desc.sales'), permission: ['sales.manage', 'sales.edit', 'settings.manage'], module: 'sales' },
        { id: 'purchases', label: t('settings.tabs.purchases'), icon: Truck, gradient: 'linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%)', desc: t('settings.tabs_desc.purchases'), permission: ['buying.manage', 'buying.edit', 'settings.manage'], module: 'buying' },
        { id: 'hr', label: t('settings.tabs.hr'), icon: Users, gradient: 'linear-gradient(135deg, #3a7bd5 0%, #00d2ff 100%)', desc: t('settings.tabs_desc.hr'), permission: 'hr.manage', module: 'hr' },
        { id: 'inventory', label: t('settings.tabs.inventory'), icon: Box, gradient: 'linear-gradient(135deg, #f59e0b 0%, #fbbf24 100%)', desc: t('settings.tabs_desc.inventory'), permission: 'stock.manage', module: 'stock' },
        { id: 'invoicing', label: t('settings.tabs.invoicing'), icon: FileText, gradient: 'linear-gradient(135deg, #ef4444 0%, #dc2626 100%)', desc: t('settings.tabs_desc.invoicing'), permission: 'settings.manage' },
        { id: 'crm', label: t('settings.tabs.crm'), icon: Heart, gradient: 'linear-gradient(135deg, #ec4899 0%, #db2777 100%)', desc: t('settings.tabs_desc.crm'), permission: 'sales.manage', module: 'crm' },
        { id: 'pos', label: t('settings.tabs.pos'), icon: Monitor, gradient: 'linear-gradient(135deg, #10b981 0%, #059669 100%)', desc: t('settings.tabs_desc.pos'), permission: 'settings.manage', module: 'pos' },
        { id: 'notifications', label: t('settings.tabs.notifications'), icon: Bell, gradient: 'linear-gradient(135deg, #f97316 0%, #ea580c 100%)', desc: t('settings.tabs_desc.notifications'), permission: 'settings.manage' },
        { id: 'reporting', label: t('settings.tabs.reporting'), icon: BarChart3, gradient: 'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)', desc: t('settings.tabs_desc.reporting'), permission: 'reports.view' },
        { id: 'security', label: t('settings.tabs.security'), icon: ShieldCheck, gradient: 'linear-gradient(135deg, #64748b 0%, #475569 100%)', desc: t('settings.tabs_desc.security'), permission: 'admin' },
        { id: 'integrations', label: t('settings.tabs.integrations'), icon: Link, gradient: 'linear-gradient(135deg, #14b8a6 0%, #0d9488 100%)', desc: t('settings.tabs_desc.integrations'), permission: 'settings.manage' },
        { id: 'performance', label: t('settings.tabs.performance'), icon: Zap, gradient: 'linear-gradient(135deg, #facc15 0%, #eab308 100%)', desc: t('settings.tabs_desc.performance'), permission: 'settings.manage' },
        { id: 'expenses', label: t('settings.tabs.expenses'), icon: Receipt, gradient: 'linear-gradient(135deg, #f43f5e 0%, #e11d48 100%)', desc: t('settings.tabs_desc.expenses'), permission: 'treasury.manage', module: 'expenses' },
        { id: 'projects', label: t('settings.tabs.projects'), icon: Briefcase, gradient: 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)', desc: t('settings.tabs_desc.projects'), permission: 'settings.manage', module: 'projects' },
        { id: 'compliance', label: t('settings.tabs.compliance'), icon: CheckSquare, gradient: 'linear-gradient(135deg, #10b981 0%, #059669 100%)', desc: t('settings.tabs_desc.compliance'), permission: 'settings.manage' },
        { id: 'branches', label: t('settings.tabs.branches'), icon: Share2, gradient: 'linear-gradient(135deg, #06b6d4 0%, #0891b2 100%)', desc: t('settings.tabs_desc.branches'), permission: 'branches.view' },
        { id: 'workflow', label: t('settings.tabs.workflow'), icon: GitBranch, gradient: 'linear-gradient(135deg, #d946ef 0%, #c026d3 100%)', desc: t('settings.tabs_desc.workflow'), permission: 'settings.manage' },
        { id: 'audit', label: t('settings.tabs.audit'), icon: Database, gradient: 'linear-gradient(135deg, #9ca3af 0%, #6b7280 100%)', desc: t('settings.tabs_desc.audit'), permission: 'audit.view', module: 'audit' },
        { id: 'sso', label: i18n.t('sso.config_title'), icon: Key, gradient: 'linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%)', desc: i18n.language === 'ar' ? 'إدارة موفري تسجيل الدخول الموحد' : 'Manage Single Sign-On providers', permission: 'settings.manage', navigateTo: '/settings/sso' },
    ], [t]);

    const tabs = React.useMemo(() =>
        allTabs.filter(tab => {
            if (tab.permission && !hasPermission(tab.permission)) return false;
            if (tab.module && !isModOn(tab.module)) return false;
            return true;
        }),
        [allTabs]
    );

    const activeTabData = React.useMemo(() =>
        tabs.find(tabItem => tabItem.id === activeTab),
        [tabs, activeTab]
    );

    // If active tab is not accessible, redirect to first available tab
    React.useEffect(() => {
        if (!loading && !showDashboard && !activeTabData && tabs.length > 0) {
            setSearchParams({ tab: tabs[0].id });
        }
    }, [loading, activeTabData, showDashboard, tabs, setSearchParams]);

    // Keep Settings page pinned to top when opening page or switching tabs.
    React.useEffect(() => {
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }, [showDashboard, activeTab]);

    // Fetch Data
    useEffect(() => {
        const fetchData = async () => {
            try {
                if (user?.company_id) {
                    const [companyRes, settingsRes] = await Promise.all([
                        companiesAPI.getCurrentCompany(user.company_id),
                        settingsAPI.get()
                    ]);
                    const data = companyRes.data;
                    setFormData({
                        company_name: data.company_name || '', company_name_en: data.company_name_en || '',
                        email: data.email || '', phone: data.phone || '', tax_number: data.tax_number || '',
                        commercial_registry: data.commercial_registry || '', address: data.address || '',
                        currency: data.currency || '', plan_type: data.plan_type || ''
                    });
                    setSettingsData(settingsRes.data || {});
                    setInitialSettingsData(settingsRes.data || {});
                }
            } catch (err) {
                console.error("Failed to fetch settings", err);
                setError(t('common.error_loading_data') || '{t("common.load_error")}');
            } finally {
                setLoading(false);
            }
        };
        if (user) fetchData();
    }, [user?.company_id, t]);

    // Handlers
    const handleTabSelect = (tabId) => {
        const tab = allTabs.find(t => t.id === tabId);
        if (tab?.navigateTo) {
            navigate(tab.navigateTo);
            return;
        }
        setSearchParams({ tab: tabId });
        setError('');
        setSuccess('');
    };

    const handleFormChange = (e) => {
        const { name, value } = e.target;
        setFormData(prev => ({ ...prev, [name]: value }));
        setError('');
        setSuccess('');
    };

    const handleSettingChange = (key, value) => {
        setSettingsData(prev => ({ ...prev, [key]: value }));
        setError('');
        setSuccess('');
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        setSaving(true);
        setError('');
        setSuccess('');
        try {
            const changedSettings = Object.fromEntries(
                Object.entries(settingsData).filter(([key, value]) => {
                    const initialValue = initialSettingsData[key];
                    return String(value ?? '') !== String(initialValue ?? '');
                })
            );

            await api.put(`/companies/update/${user.company_id}`, formData);
            if (Object.keys(changedSettings).length > 0) {
                await settingsAPI.updateBulk(changedSettings);
                setInitialSettingsData(settingsData);
            }

            // Update local user state for immediate reflection
            updateUser({
                currency: formData.currency,
                decimal_places: settingsData.decimal_places !== undefined ? parseInt(settingsData.decimal_places) : 2
            });

            setSuccess(t('common.success') || '{t("common.save_success")}');

            // Reload page to apply changes globally across all components
            setTimeout(() => {
                window.location.reload();
            }, 1000);
        } catch (err) {
            console.error("Error saving settings:", err);
            setError(t('common.error_save') || '{t("common.save_error")}');
        } finally {
            setSaving(false);
        }
    };

    if (loading) return <PageLoading />;

    // If no tabs accessible at all
    if (tabs.length === 0) {
        return <div className="p-10 text-center"><h2 className="text-xl font-bold">{t('common.no_permission') || '{t("settings.no_permission")}'}</h2></div>;
    }

    return (
        <div className="min-h-screen bg-base-100 p-6 animate-fade-in">
            <div className="max-w-7xl mx-auto">
                {showDashboard ? (
                    /* Dashboard View */
                    <div className="animate-fade-in">
                        {/* Header */}
                        <div className="mb-8 pl-1">
                            <h1 className="text-3xl font-bold text-base-content">{t('settings.company.title') || '{t("settings.company_settings")}'}</h1>
                            <p className="text-base-content/60 mt-2 text-lg">{t('settings.company.subtitle') || '{t("settings.company_settings_desc")}'}</p>
                        </div>



                        {/* Main Grid with Robust CSS */}
                        <div
                            style={{
                                display: 'grid',
                                gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
                                gap: '1.5rem',
                                width: '100%'
                            }}
                        >
                            {tabs.map((tab) => {
                                const Icon = tab.icon;
                                return (
                                    <button
                                        key={tab.id}
                                        onClick={() => handleTabSelect(tab.id)}
                                        data-nav-target={`/settings?tab=${tab.id}`}
                                        className="card bg-base-100 shadow-sm hover:shadow-md transition-all duration-300 border border-base-200 group text-center flex flex-col items-center justify-center p-6 rounded-[2rem]"
                                        style={{
                                            height: '260px',
                                            width: '100%',
                                            display: 'flex',
                                            flexDirection: 'column',
                                            alignItems: 'center',
                                            justifyContent: 'center'
                                        }}
                                    >
                                        <div className="mb-6 transition-transform duration-300 group-hover:scale-110 text-primary">
                                            <Icon size={40} strokeWidth={1.5} />
                                        </div>
                                        <h3 className="text-lg font-bold text-base-content mb-2 group-hover:text-primary transition-colors">
                                            {tab.label}
                                        </h3>
                                        <p className="text-sm text-base-content/60 leading-relaxed max-w-[200px] line-clamp-2">
                                            {tab.desc}
                                        </p>
                                    </button>
                                );
                            })}
                        </div>

                        {/* Advanced Tools */}
                        {(hasPermission('settings.view') || hasPermission('admin.companies') || hasPermission('audit.view') || hasPermission('admin.roles') || hasPermission('data_import.view') || hasPermission('dms.audit_admin') || hasPermission('branches.view')) && (
                            <div style={{ marginTop: '2.5rem' }}>
                                <h2 style={{ fontSize: '18px', fontWeight: '700', marginBottom: '1rem', color: 'var(--text-secondary, #6b7280)' }}>
                                    {t('settings.advanced_tools') || 'أدوات متقدمة'}
                                </h2>
                                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '1.5rem' }}>
                                    {[
                                        { icon: Layers, label: t('nav.moduleCustomization') || 'تخصيص الوحدات', desc: t('settings.advanced_tools_desc.modules') || 'تفعيل وتعطيل الوحدات حسب نوع النشاط', path: '/setup/modules', permission: 'admin.companies' },
                                        { icon: Building2, label: t('nav.branches') || 'الفروع', desc: t('settings.advanced_tools_desc.branches'), path: '/settings/branches', permission: 'branches.view' },
                                        { icon: Scale, label: t('nav.costingPolicy') || 'سياسة التكلفة', desc: t('settings.advanced_tools_desc.costing_policy'), path: '/settings/costing-policy' },
                                        { icon: Upload, label: t('nav.dataImport') || 'استيراد البيانات', desc: t('settings.advanced_tools_desc.data_import'), path: '/data-import', permission: 'data_import.view' },
                                        { icon: HardDrive, label: t('nav.dms') || 'DMS', desc: t('settings.advanced_tools_desc.dms'), path: '/settings/dms', permission: 'dms.audit_admin' },
                                        { icon: History, label: t('nav.auditLogs') || 'سجلات المراقبة', desc: t('settings.advanced_tools_desc.audit_logs') || 'مراجعة وتتبع جميع عمليات النظام', path: '/admin/audit-logs', permission: 'audit.view' },
                                        { icon: ShieldCheck, label: t('nav.roles') || 'إدارة الأدوار', desc: t('settings.advanced_tools_desc.roles') || 'إدارة الأدوار والصلاحيات', path: '/admin/roles', permission: 'admin.roles' },
                                        { icon: Key, label: t('nav.api_keys') || 'مفاتيح API', desc: t('settings.advanced_tools_desc.api_keys'), path: '/settings/api-keys' },
                                        { icon: Globe, label: t('nav.webhooks') || 'الويب هوك', desc: t('settings.advanced_tools_desc.webhooks'), path: '/settings/webhooks' },
                                    ].filter(item => !item.permission || hasPermission(item.permission)).map((item) => {
                                        const Icon = item.icon;
                                        return (
                                            <button
                                                key={item.path}
                                                onClick={() => navigate(item.path)}
                                                data-nav-target={item.path}
                                                className="card bg-base-100 shadow-sm hover:shadow-md transition-all duration-300 border border-base-200 group text-center flex flex-col items-center justify-center p-6 rounded-[2rem]"
                                                style={{ height: '200px', width: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}
                                            >
                                                <div className="mb-4 transition-transform duration-300 group-hover:scale-110" style={{ color: 'var(--primary, #4f46e5)' }}>
                                                    <Icon size={36} strokeWidth={1.5} />
                                                </div>
                                                <h3 className="text-lg font-bold text-base-content mb-1 group-hover:text-primary transition-colors">{item.label}</h3>
                                                <p className="text-sm text-base-content/60 leading-relaxed max-w-[200px]">{item.desc}</p>
                                            </button>
                                        );
                                    })}
                                </div>
                            </div>
                        )}
                    </div>
                ) : (
                    /* Detail View (Full Page) */
                    <div className="animate-slide-up">
                        {/* Navigation Header */}
                        <div className="flex items-center gap-4 mb-8">
                            <BackButton onClick={() => setSearchParams({})} />
                            <div>
                                <h1 className="text-2xl font-bold flex items-center gap-3">
                                    <span className="text-base-content/50 font-normal">{t('settings.company.title')}</span>
                                    <span className="text-base-content/30">/</span>
                                    <span>{activeTabData?.label}</span>
                                </h1>
                            </div>
                        </div>

                        {/* Content Container */}
                        <div className="bg-base-100 rounded-3xl border border-base-200 shadow-sm overflow-hidden">
                            {/* Detail Header */}
                            <div className="px-8 py-6 border-b border-base-100 bg-base-50 flex items-center gap-4">
                                <div className="p-3 rounded-xl bg-primary/10 text-primary">
                                    {activeTabData && <activeTabData.icon size={24} />}
                                </div>
                                <div>
                                    <h2 className="text-lg font-bold">{activeTabData?.label}</h2>
                                    <p className="text-sm text-base-content/60">{activeTabData?.desc}</p>
                                </div>
                            </div>

                            {/* Form Area */}
                            <div className="p-8">
                                <form onSubmit={handleSubmit} className="max-w-4xl mx-auto">
                                    {error && (
                                        <div className="alert alert-error mb-6 rounded-xl">
                                            <ShieldCheck size={20} />
                                            <span>{error}</span>
                                        </div>
                                    )}
                                    {success && (
                                        <div className="alert alert-success mb-6 rounded-xl">
                                            <Sparkles size={20} />
                                            <span>{success}</span>
                                        </div>
                                    )}

                                    <div className="min-h-[400px]">
                                        {activeTab === 'general' && <GeneralSettings formData={formData} handleChange={handleFormChange} />}
                                        {activeTab === 'financial' && <FinancialSettings formData={formData} handleChange={handleFormChange} settings={settingsData} handleSettingChange={handleSettingChange} />}
                                        {activeTab === 'branding' && <BrandingSettings settings={settingsData} handleSettingChange={handleSettingChange} companyId={user.company_id} />}
                                        {activeTab === 'invoicing' && <InvoicingSettings settings={settingsData} handleSettingChange={handleSettingChange} currency={formData.currency} />}
                                        {activeTab === 'inventory' && <InventorySettings settings={settingsData} handleSettingChange={handleSettingChange} />}
                                        {activeTab === 'accounting' && <AccountingMappingSettings settings={settingsData} handleSettingChange={handleSettingChange} />}
                                        {activeTab === 'pos' && <POSSettings settings={settingsData} handleSettingChange={handleSettingChange} />}
                                        {activeTab === 'sales' && <SalesSettings settings={settingsData} handleSettingChange={handleSettingChange} currency={formData.currency} />}
                                        {activeTab === 'purchases' && <PurchasesSettings settings={settingsData} handleSettingChange={handleSettingChange} currency={formData.currency} />}
                                        {activeTab === 'security' && <SecuritySettings settings={settingsData} handleSettingChange={handleSettingChange} />}
                                        {activeTab === 'notifications' && <NotificationSettings settings={settingsData} handleSettingChange={handleSettingChange} />}
                                        {activeTab === 'hr' && <HRSettings settings={settingsData} handleSettingChange={handleSettingChange} />}
                                        {activeTab === 'crm' && <CRMSettings settings={settingsData} handleSettingChange={handleSettingChange} currency={formData.currency} />}
                                        {activeTab === 'integrations' && <IntegrationSettings settings={settingsData} handleSettingChange={handleSettingChange} />}
                                        {activeTab === 'reporting' && <ReportingSettings settings={settingsData} handleSettingChange={handleSettingChange} />}
                                        {activeTab === 'performance' && <PerformanceSettings settings={settingsData} handleSettingChange={handleSettingChange} />}
                                        {activeTab === 'expenses' && <ExpensesSettings settings={settingsData} handleSettingChange={handleSettingChange} currency={formData.currency} />}
                                        {activeTab === 'projects' && <ProjectsSettings settings={settingsData} handleSettingChange={handleSettingChange} />}
                                        {activeTab === 'compliance' && <ComplianceSettings settings={settingsData} handleSettingChange={handleSettingChange} />}
                                        {activeTab === 'branches' && <BranchesSettings settings={settingsData} handleSettingChange={handleSettingChange} />}
                                        {activeTab === 'workflow' && <WorkflowSettings settings={settingsData} handleSettingChange={handleSettingChange} currency={formData.currency} />}
                                        {activeTab === 'audit' && <AuditSettings settings={settingsData} handleSettingChange={handleSettingChange} />}

                                        {!['general', 'financial', 'branding', 'invoicing', 'inventory', 'accounting', 'pos', 'sales', 'purchases', 'security', 'notifications', 'hr', 'crm', 'integrations', 'reporting', 'performance', 'expenses', 'projects', 'compliance', 'branches', 'workflow', 'audit'].includes(activeTab) && <ComingSoon title={activeTabData?.label} />}
                                    </div>

                                    {['general', 'financial', 'branding', 'invoicing', 'inventory', 'accounting', 'pos', 'sales', 'purchases', 'security', 'notifications', 'hr', 'crm', 'integrations', 'reporting', 'performance', 'expenses', 'projects', 'compliance', 'branches', 'workflow', 'audit'].includes(activeTab) && (
                                        <div className="mt-10 pt-6 border-t border-base-100 flex items-center justify-end gap-3">
                                            <button
                                                type="button"
                                                onClick={() => setSearchParams({})}
                                                className="btn btn-ghost"
                                            >
                                                {t('common.cancel')}
                                            </button>
                                            <button
                                                type="submit"
                                                className="btn btn-primary px-8 min-w-[150px]"
                                                disabled={saving}
                                            >
                                                {saving ? (
                                                    <><Spinner size="sm"/> {t('common.saving')}</>
                                                ) : (
                                                    t('common.save')
                                                )}
                                            </button>
                                        </div>
                                    )}
                                </form>
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};

export default CompanySettings;
