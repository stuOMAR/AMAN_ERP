import React, { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams, useNavigate } from 'react-router-dom';
import { RefreshCw, ChevronDown, BarChart3, ArrowLeft, ArrowRight } from 'lucide-react';
import { roleDashboardAPI } from '../../services/roleDashboard';
import { KPICard, KPIChart, AlertBanner, PeriodSelector } from '../../components/kpi';
import Card from '../../components/common/Card';
import BackButton from '../../components/common/BackButton';
import { useBranch } from '../../context/BranchContext';
import { getCurrency } from '../../utils/auth';

/**
 * RoleDashboard — universal role-based KPI dashboard page.
 * لوحة تحكم وظيفية شاملة بمؤشرات أداء حسب الدور
 *
 * Uses URL param :roleKey to determine which endpoint to hit.
 * If roleKey === 'auto', uses the auto-detect endpoint.
 */

const ROLE_CONFIG = {
    auto:          { titleAr: 'لوحتي',                   titleEn: 'My Dashboard',              color: '#6366f1', icon: '🎯' },
    executive:     { titleAr: 'لوحة المدير التنفيذي',    titleEn: 'Executive Dashboard',       color: '#7c3aed', icon: '👑' },
    financial:     { titleAr: 'لوحة المدير المالي',      titleEn: 'Financial Dashboard',       color: '#2563eb', icon: '💰' },
    sales:         { titleAr: 'لوحة المبيعات',          titleEn: 'Sales Dashboard',           color: '#059669', icon: '📈' },
    procurement:   { titleAr: 'لوحة المشتريات',        titleEn: 'Procurement Dashboard',     color: '#d97706', icon: '🛒' },
    warehouse:     { titleAr: 'لوحة المخازن',          titleEn: 'Warehouse Dashboard',       color: '#0891b2', icon: '📦' },
    hr:            { titleAr: 'لوحة الموارد البشرية',   titleEn: 'HR Dashboard',              color: '#7c3aed', icon: '👥' },
    manufacturing: { titleAr: 'لوحة التصنيع',          titleEn: 'Manufacturing Dashboard',   color: '#ea580c', icon: '🏭' },
    projects:      { titleAr: 'لوحة المشاريع',         titleEn: 'Projects Dashboard',        color: '#4f46e5', icon: '📐' },
    pos:           { titleAr: 'لوحة نقاط البيع',       titleEn: 'POS Dashboard',             color: '#0d9488', icon: '🏪' },
    crm:           { titleAr: 'لوحة العلاقات',          titleEn: 'CRM Dashboard',             color: '#e11d48', icon: '🤝' },
    industry:      { titleAr: 'مؤشرات القطاع',          titleEn: 'Industry KPIs',             color: '#8b5cf6', icon: '🏢' },
};

const API_MAP = {
    auto:          roleDashboardAPI.getAuto,
    executive:     roleDashboardAPI.getExecutive,
    financial:     roleDashboardAPI.getFinancial,
    sales:         roleDashboardAPI.getSales,
    procurement:   roleDashboardAPI.getProcurement,
    warehouse:     roleDashboardAPI.getWarehouse,
    hr:            roleDashboardAPI.getHR,
    manufacturing: roleDashboardAPI.getManufacturing,
    projects:      roleDashboardAPI.getProjects,
    pos:           roleDashboardAPI.getPOS,
    crm:           roleDashboardAPI.getCRM,
    industry:      roleDashboardAPI.getIndustry,
};

const RoleDashboard = ({ fixedRoleKey, backPath }) => {
    const { roleKey } = useParams();
    const navigate = useNavigate();
    const { t, i18n } = useTranslation();
    const { currentBranch } = useBranch();
    const isRTL = i18n.dir() === 'rtl';
    const fallbackCurrency = getCurrency() || 'SAR';
    const isEmbedded = !!fixedRoleKey;

    const key = fixedRoleKey || roleKey || 'auto';
    const config = ROLE_CONFIG[key] || ROLE_CONFIG.auto;

    const [period, setPeriod] = useState(key === 'pos' ? 'today' : 'mtd');
    const [startDate, setStartDate] = useState('');
    const [endDate, setEndDate] = useState('');
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    // Available dashboards menu
    const [availableDashboards, setAvailableDashboards] = useState([]);
    const [showMenu, setShowMenu] = useState(false);

    const fetchData = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const params = { period };
            if (currentBranch) params.branch_id = currentBranch.id;
            if (period === 'custom' && startDate) params.start_date = startDate;
            if (period === 'custom' && endDate) params.end_date = endDate;

            const apiFn = API_MAP[key] || API_MAP.auto;
            const res = await apiFn(params);
            setData(res.data);
        } catch (err) {
            console.error('Dashboard fetch error:', err);
            setError(err?.response?.data?.detail || (t('kpi.error_loading_data')));
        } finally {
            setLoading(false);
        }
    }, [key, period, startDate, endDate, currentBranch]);

    const fetchAvailable = useCallback(async () => {
        try {
            const res = await roleDashboardAPI.getAvailable();
            setAvailableDashboards(res.data?.dashboards || []);
        } catch (_) {}
    }, []);

    useEffect(() => { fetchData(); }, [fetchData]);
    useEffect(() => { fetchAvailable(); }, [fetchAvailable]);

    const handlePeriodChange = (p, s, e) => {
        setPeriod(p);
        if (s !== undefined) setStartDate(s || '');
        if (e !== undefined) setEndDate(e || '');
    };

    const kpis = data?.kpis || data?.role_kpis || [];
    const charts = data?.charts || data?.role_charts || [];
    const alerts = data?.alerts || data?.role_alerts || [];
    const currency = data?.display_currency || fallbackCurrency;

    // Group KPIs by category
    const grouped = {};
    kpis.forEach(k => {
        const cat = k.category || 'general';
        if (!grouped[cat]) grouped[cat] = [];
        grouped[cat].push(k);
    });
    const categories = Object.keys(grouped);

    const title = isRTL ? config.titleAr : config.titleEn;

    return (
        <div className="workspace fade-in">
            {/* Header */}
            <div className="workspace-header" style={{ marginBottom: '1.2rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '0.75rem' }}>
                    <div>
                        <h1 className="workspace-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <span>{config.icon}</span>
                            {title}
                            {currentBranch && (
                                <span style={{ fontSize: '0.78rem', fontWeight: 400, color: 'var(--text-secondary)', background: 'var(--bg-hover)', border: '1px solid var(--border-color)', borderRadius: '0.4rem', padding: '2px 8px' }}>
                                    {currentBranch.branch_name}
                                </span>
                            )}
                        </h1>
                        {data?.industry && (
                            <p className="workspace-subtitle" style={{ marginTop: 4 }}>
                                {t('kpi.industry')} {data.industry}
                            </p>
                        )}
                    </div>

                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
                        {/* Standalone back button (when NOT embedded in a module) */}
                        {!isEmbedded && <BackButton />}
                        {/* Back button (when embedded in module) */}
                        {isEmbedded && backPath && (
                            <button
                                onClick={() => navigate(backPath)}
                                style={{
                                    display: 'flex', alignItems: 'center', gap: '4px',
                                    padding: '6px 12px', background: 'var(--bg-card)', border: '1px solid var(--border-color)',
                                    borderRadius: '8px', fontSize: '0.8rem', cursor: 'pointer', color: 'var(--text-secondary)',
                                }}
                            >
                                {isRTL ? <ArrowRight size={14} /> : <ArrowLeft size={14} />}
                                {t('kpi.back')}
                            </button>
                        )}

                        {/* Dashboard switcher (only in standalone /kpi mode) */}
                        {!isEmbedded && (
                        <div style={{ position: 'relative' }}>
                            <button
                                onClick={() => setShowMenu(!showMenu)}
                                style={{
                                    display: 'flex', alignItems: 'center', gap: '4px',
                                    padding: '6px 12px', background: 'var(--bg-card)', border: '1px solid var(--border-color)',
                                    borderRadius: '8px', fontSize: '0.8rem', cursor: 'pointer', color: 'var(--text-secondary)',
                                }}
                            >
                                <BarChart3 size={14} />
                                {t('kpi.switch')}
                                <ChevronDown size={12} />
                            </button>
                            {showMenu && (
                                <div style={{
                                    position: 'absolute', top: '100%', [isRTL ? 'right' : 'left']: 0,
                                    marginTop: 4, background: 'var(--bg-card)', border: '1px solid var(--border-color)',
                                    borderRadius: '10px', boxShadow: 'var(--shadow-md)',
                                    zIndex: 50, minWidth: 200, padding: '6px',
                                    maxHeight: 300, overflowY: 'auto',
                                }}>
                                    {availableDashboards.map(d => (
                                        <button
                                            key={d.key}
                                            onClick={() => {
                                                setShowMenu(false);
                                                navigate(`/kpi/${d.key}`);
                                            }}
                                            style={{
                                                display: 'block', width: '100%', textAlign: isRTL ? 'right' : 'left',
                                                padding: '8px 12px', border: 'none', background: d.key === key ? 'var(--bg-hover)' : 'transparent',
                                                borderRadius: '6px', fontSize: '0.8rem', cursor: 'pointer',
                                                color: d.key === key ? config.color : 'var(--text-secondary)',
                                                fontWeight: d.key === key ? 700 : 500,
                                            }}
                                        >
                                            {isRTL ? d.label_ar : d.label}
                                        </button>
                                    ))}
                                </div>
                            )}
                        </div>
                        )}

                        <button onClick={fetchData} disabled={loading}
                            style={{
                                display: 'flex', alignItems: 'center', gap: '4px',
                                padding: '6px 12px', background: 'var(--bg-card)', border: '1px solid var(--border-color)',
                                borderRadius: '8px', fontSize: '0.8rem', cursor: 'pointer', color: 'var(--text-secondary)',
                            }}
                        >
                            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
                            {t('dashboard.refresh') || (t('kpi.refresh'))}
                        </button>
                    </div>
                </div>

                {/* Period selector */}
                <div style={{ marginTop: '0.8rem' }}>
                    <PeriodSelector
                        value={period}
                        onChange={handlePeriodChange}
                        startDate={startDate}
                        endDate={endDate}
                    />
                </div>
            </div>

            {/* Error state */}
            {error && (
                <div style={{
                    padding: '16px 20px', background: '#fef2f2', border: '1px solid #fca5a5',
                    borderRadius: '10px', color: '#991b1b', fontSize: '0.85rem', marginBottom: '1rem',
                }}>
                    {error}
                </div>
            )}

            {/* Loading skeleton */}
            {loading && !data && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: '1rem', marginBottom: '1.5rem' }}>
                    {[1, 2, 3, 4, 5, 6].map(i => (
                        <div key={i} className="card animate-pulse" style={{ height: 120 }}>
                            <div style={{ height: 12, background: '#f1f5f9', borderRadius: 6, width: '60%', marginBottom: 12 }} />
                            <div style={{ height: 28, background: '#f1f5f9', borderRadius: 6, width: '40%', marginBottom: 8 }} />
                            <div style={{ height: 10, background: '#f1f5f9', borderRadius: 6, width: '30%' }} />
                        </div>
                    ))}
                </div>
            )}

            {/* Alerts */}
            {alerts.length > 0 && (
                <div style={{ marginBottom: '1rem' }}>
                    <AlertBanner alerts={alerts} />
                </div>
            )}

            {/* KPI Cards by category */}
            {categories.map(cat => (
                <div key={cat} style={{ marginBottom: '1.5rem' }}>
                    {categories.length > 1 && (
                        <h3 style={{
                            fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-secondary)',
                            textTransform: 'uppercase', letterSpacing: '0.06em',
                            marginBottom: '0.6rem', paddingBottom: '0.4rem',
                            borderBottom: '1px solid var(--border-color)',
                        }}>
                            {cat}
                        </h3>
                    )}
                    <div style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
                        gap: '0.8rem',
                    }}>
                        {grouped[cat].map((kpi, idx) => (
                            <KPICard key={idx} kpi={kpi} currency={currency} />
                        ))}
                    </div>
                </div>
            ))}

            {/* Charts */}
            {charts.length > 0 && (
                <div style={{
                    display: 'grid',
                    gridTemplateColumns: charts.length === 1 ? '1fr' : 'repeat(auto-fit, minmax(400px, 1fr))',
                    gap: '1rem',
                    marginBottom: '1.5rem',
                }}>
                    {charts.map((chart, idx) => (
                        <Card key={idx}>
                            <KPIChart chart={chart} currency={currency} />
                        </Card>
                    ))}
                </div>
            )}

            {/* Industry section for combined view */}
            {data?.industry_kpis && data.industry_kpis.length > 0 && (
                <div style={{ marginTop: '2rem' }}>
                    <h2 style={{
                        fontSize: '0.9rem', fontWeight: 700, color: 'var(--text-secondary)',
                        textTransform: 'uppercase', letterSpacing: '0.05em',
                        marginBottom: '1rem', paddingBottom: '0.5rem',
                        borderBottom: '2px solid var(--border-color)',
                        display: 'flex', alignItems: 'center', gap: '0.4rem',
                    }}>
                        🏢 {t('kpi.industry_kpis')}
                        {data.industry && <span style={{ fontWeight: 400, color: 'var(--text-muted)' }}>— {data.industry}</span>}
                    </h2>
                    <div style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
                        gap: '0.8rem',
                        marginBottom: '1rem',
                    }}>
                        {data.industry_kpis.map((kpi, idx) => (
                            <KPICard key={idx} kpi={kpi} currency={currency} />
                        ))}
                    </div>
                    {data.industry_charts && data.industry_charts.length > 0 && (
                        <div style={{
                            display: 'grid',
                            gridTemplateColumns: 'repeat(auto-fit, minmax(400px, 1fr))',
                            gap: '1rem',
                        }}>
                            {data.industry_charts.map((chart, idx) => (
                                <Card key={idx}>
                                    <KPIChart chart={chart} currency={currency} />
                                </Card>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

export default RoleDashboard;
