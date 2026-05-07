import React, { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../utils/api';
import StatsCards from '../components/dashboard/StatsCards';
import FinancialChart from '../components/dashboard/FinancialChart';
import TopProductsChart from '../components/dashboard/TopProductsChart';
import SalesSummaryWidget from '../components/dashboard/SalesSummaryWidget';
import LowStockWidget from '../components/dashboard/LowStockWidget';
import PendingTasksWidget from '../components/dashboard/PendingTasksWidget';
import CashFlowWidget from '../components/dashboard/CashFlowWidget';
import IndustryWidgets from '../components/dashboard/IndustryWidgets';
import Card from '../components/common/Card';
import {
    RefreshCw, Calendar, Wallet, TrendingUp, Package, Users,
    Building2, FileText, ShieldCheck,
} from 'lucide-react';
import { useBranch } from '../context/BranchContext';
import { getUser } from '../utils/auth';
import { formatShortDate } from '../utils/dateUtils';


/* ── Dashboard ───────────────────────────────────────── */
const Dashboard = () => {
    const { t, i18n } = useTranslation();
    const { currentBranch, displayCurrency } = useBranch();
    const user = getUser();
    const isRTL = i18n.dir() === 'rtl';

    const [stats, setStats]      = useState(null);
    const [finData, setFin]      = useState([]);
    const [prodData, setProds]   = useState([]);
    const [loading, setLoading]  = useState(true);
    const currency = stats?.display_currency || displayCurrency?.currency || user?.currency || '';

    const fetchAll = useCallback(async () => {
        if (user?.role === 'system_admin') {
            try { const r = await api.get('/dashboard/system-stats'); setStats(r.data); }
            catch (_) {}
            finally { setLoading(false); }
            return;
        }
        setLoading(true);
        try {
            const p = currentBranch ? { branch_id: currentBranch.id } : {};
            const [sR, fR, pR] = await Promise.all([
                api.get('/dashboard/stats', { params: p }),
                api.get('/dashboard/charts/financial', { params: p }),
                api.get('/dashboard/charts/products', { params: p }),
            ]);
            setStats(sR.data);
            setFin(fR.data);
            setProds(pR.data);
        } catch (_) {}
        finally { setLoading(false); }
    }, [currentBranch, user?.role]);

    useEffect(() => { fetchAll(); }, [fetchAll]);

    const greeting = () => {
        const h = new Date().getHours();
        if (h < 12) return t('dashboard.good_morning');
        if (h < 18) return t('dashboard.good_afternoon');
        return t('dashboard.good_evening');
    };

    /* ── System-Admin ───────────────────────────────── */
    if (user?.role === 'system_admin') {
        return (
            <div className="workspace fade-in">
                <div className="workspace-header">
                    <h1 className="workspace-title">{t('dashboard.system_admin_title')}</h1>
                    <p className="workspace-subtitle">{t('dashboard.system_admin_welcome')}</p>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px,1fr))', gap: '1rem', marginBottom: '2rem' }}>
                    {[
                        { label: t('dashboard.apps.companies'), val: stats?.total_companies },
                        { label: t('dashboard.total_users'),     val: stats?.total_users },
                        { label: t('dashboard.active_users'),    val: stats?.active_users },
                        { label: t('dashboard.system_status'),   val: stats?.system_status, green: stats?.system_status === 'Healthy' },
                    ].map(m => (
                        <Card key={m.label}>
                            <div style={{ fontSize: '0.75rem', color: '#94a3b8', marginBottom: '0.3rem' }}>{m.label}</div>
                            <div style={{ fontSize: '1.6rem', fontWeight: 700, color: m.green ? '#16a34a' : '#1e293b' }}>
                                {loading ? <span style={{ display: 'inline-block', width: 60, height: 28, borderRadius: 6, background: '#f1f5f9' }} /> : (m.val ?? '—')}
                            </div>
                        </Card>
                    ))}
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px,1fr))', gap: '1.5rem' }}>
                    <AdminCard icon={<Building2 size={36} strokeWidth={1.5}/>} title={t('dashboard.apps.companies')} desc={t('dashboard.apps.companies_desc')} link="/admin/companies" />
                    <AdminCard icon={<FileText   size={36} strokeWidth={1.5}/>} title={t('audit.title')}             desc={t('audit.subtitle')}             link="/admin/audit-logs" />
                    <AdminCard icon={<ShieldCheck size={36} strokeWidth={1.5}/>}title={t('nav.roles')}              desc={t('dashboard.apps.security_desc')}link="/admin/roles" />
                </div>
            </div>
        );
    }

    /* ── Company user ───────────────────────────────── */
    const gap = '1rem';

    // MODULE-001: Check which modules are enabled
    const enabledModules = user?.enabled_modules || []
    const isModOn = (m) => !enabledModules.length || enabledModules.includes(m)

    return (
        <div className="workspace fade-in">

            {/* Header */}
            <div className="workspace-header" style={{ marginBottom: '1.5rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.75rem' }}>
                    <div>
                        <h1 className="workspace-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            {t('dashboard.dashboard')}
                            {currentBranch && (
                                <span style={{ fontSize: '0.78rem', fontWeight: 400, color: '#64748b', background: '#f1f5f9', border: '1px solid #e2e8f0', borderRadius: '0.4rem', padding: '2px 8px' }}>
                                    {currentBranch.branch_name}
                                </span>
                            )}
                        </h1>
                        <p className="workspace-subtitle">{greeting()}, {user?.full_name || user?.username}.</p>
                    </div>
                    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center' }}>
                        <span style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', padding: '6px 12px', background: '#fff', border: '1px solid #e2e8f0', borderRadius: '0.6rem', fontSize: '0.8rem', color: '#64748b' }}>
                            <Calendar size={14} />
                            {formatShortDate(new Date())}
                        </span>
                        <button onClick={fetchAll} disabled={loading}
                            style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', padding: '6px 14px', background: '#fff', border: '1px solid #e2e8f0', borderRadius: '0.6rem', fontSize: '0.8rem', cursor: 'pointer', color: '#475569' }}>
                            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
                            {t('dashboard.refresh')}
                        </button>
                    </div>
                </div>
            </div>

            {/* Row 1 — Key metrics */}
            <div style={{ marginBottom: gap }}>
                <StatsCards stats={stats} loading={loading} currency={currency} />
            </div>

            {/* Industry-specific widgets */}
            <IndustryWidgets />

            {/* Row 2 — Sales summary × 3 */}
            {isModOn('sales') && (
            <div className="modules-grid" style={{ gap, marginBottom: gap }}>
                <Card title={t('dashboard.today')} style={{ minHeight: 120 }}>
                    <SalesSummaryWidget config={{ period: 'today' }} currency={currency} />
                </Card>
                <Card title={t('dashboard.this_week')} style={{ minHeight: 120 }}>
                    <SalesSummaryWidget config={{ period: 'week' }} currency={currency} />
                </Card>
                <Card title={t('dashboard.this_month')} style={{ minHeight: 120 }}>
                    <SalesSummaryWidget config={{ period: 'month' }} currency={currency} />
                </Card>
            </div>
            )}

            {/* Row 3 — Financial chart + Quick actions */}
            <div className="dashboard-row-2col" style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap, marginBottom: gap }}>
                <Card title={t('dashboard.financial_overview')} style={{ minHeight: 320 }}>
                    <FinancialChart data={finData} loading={loading} currency={currency} />
                </Card>
                <Card title={t('dashboard.quick_actions')} style={{ minHeight: 320 }}>
                    <QuickActions t={t} isRTL={isRTL} enabledModules={enabledModules} />
                </Card>
            </div>

            {/* Row 4 — Top products + Low stock (only if stock module enabled) */}
            {isModOn('stock') && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap, marginBottom: gap }}>
                <Card title={t('dashboard.top_products')} style={{ minHeight: 280 }}>
                    <TopProductsChart data={prodData} loading={loading} currency={currency} />
                </Card>
                <Card title={t('dashboard.low_stock')} style={{ minHeight: 280 }}>
                    <LowStockWidget config={{ limit: 8 }} currency={currency} />
                </Card>
            </div>
            )}

            {/* Row 5 — Cash flow */}
            <div style={{ marginBottom: gap }}>
                <Card title={t('dashboard.cash_flow_last_30_days')} style={{ minHeight: 280 }}>
                    <CashFlowWidget config={{ days: 30 }} currency={currency} />
                </Card>
            </div>

            {/* Row 6 — Pending tasks */}
            <div style={{ marginBottom: gap }}>
                <Card title={t('dashboard.pending_tasks')}>
                    <PendingTasksWidget config={{ limit: 10 }} currency={currency} />
                </Card>
            </div>

        </div>
    );
};

/* ── AdminCard ───────────────────────────────────────── */
const AdminCard = ({ icon, title, desc, link }) => (
    <button onClick={() => window.location.href = link}
        className="card"
        style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: 230, width: '100%', cursor: 'pointer', textAlign: 'center' }}
        onMouseEnter={e => { e.currentTarget.style.boxShadow='0 6px 20px rgba(59,130,246,.15)'; e.currentTarget.style.borderColor='#93c5fd'; }}
        onMouseLeave={e => { e.currentTarget.style.boxShadow=''; e.currentTarget.style.borderColor=''; }}>
        <div style={{ marginBottom: '0.9rem', color: '#3b82f6' }}>{icon}</div>
        <div style={{ fontWeight: 700, fontSize: '1rem', color: 'var(--text-main)', marginBottom: '0.35rem' }}>{title}</div>
        <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', lineHeight: 1.5 }}>{desc}</div>
    </button>
);

/* ── QuickActions ────────────────────────────────────── */
const ACTIONS = [
    { icon: <TrendingUp size={20}/>, key: 'nav.sales',       link: '/sales/invoices/new',            bg: '#dbeafe', fg: '#2563eb', module: 'sales' },
    { icon: <Package    size={20}/>, key: 'nav.inventory',   link: '/stock/products/new',            bg: '#dcfce7', fg: '#16a34a', module: 'stock' },
    { icon: <Wallet     size={20}/>, key: 'nav.accounting',  link: '/accounting/journal-entries/new',bg: '#fef9c3', fg: '#ca8a04', module: 'accounting' },
    { icon: <Users      size={20}/>, key: 'nav.hr',          link: '/hr/employees',                  bg: '#fae8ff', fg: '#9333ea', module: 'hr' },
];

const QuickActions = ({ t, isRTL, enabledModules }) => {
    const filtered = enabledModules?.length
        ? ACTIONS.filter(a => enabledModules.includes(a.module))
        : ACTIONS;

    return (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(110px, 1fr))', gap: '0.7rem', height: '100%' }}>
            {filtered.map(a => (
            <button key={a.key} onClick={() => window.location.href = a.link}
                style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '0.4rem', padding: '0.9rem', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '0.75rem', cursor: 'pointer', fontSize: '0.8rem', fontWeight: 600, color: '#475569', transition: 'all .15s' }}
                onMouseEnter={e => { e.currentTarget.style.background=a.bg; e.currentTarget.style.borderColor=a.fg+'66'; e.currentTarget.style.color=a.fg; }}
                onMouseLeave={e => { e.currentTarget.style.background='#f8fafc'; e.currentTarget.style.borderColor='#e2e8f0'; e.currentTarget.style.color='#475569'; }}>
                <span style={{ padding: '0.45rem', background: a.bg, borderRadius: '0.5rem', color: a.fg, display: 'flex' }}>
                    {a.icon}
                </span>
                {t(a.key)}
            </button>
        ))}
    </div>
    );
};

export default Dashboard;
