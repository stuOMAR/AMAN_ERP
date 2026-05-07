import React, { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronUp, RefreshCw } from 'lucide-react';
import { roleDashboardAPI } from '../../services/roleDashboard';
import { KPICard, KPIChart, AlertBanner, PeriodSelector } from './index';
import Card from '../common/Card';
import { useBranch } from '../../context/BranchContext';
import { getCurrency } from '../../utils/auth';

/**
 * ModuleKPISection — embeddable KPI section for any module's analytics page.
 * قسم مؤشرات الأداء القابل للتضمين في صفحات التحليلات
 *
 * Props:
 *   roleKey: string — 'sales' | 'procurement' | 'warehouse' | 'hr' | 'manufacturing' | 'projects' | 'pos' | 'crm' | 'financial'
 *   color: string — accent color for the section
 *   defaultOpen: boolean — whether the section is expanded by default
 */

const ROLE_LABELS = {
    sales:         { ar: 'مؤشرات أداء المبيعات', en: 'Sales KPIs' },
    procurement:   { ar: 'مؤشرات أداء المشتريات', en: 'Procurement KPIs' },
    warehouse:     { ar: 'مؤشرات أداء المخازن', en: 'Warehouse KPIs' },
    hr:            { ar: 'مؤشرات أداء الموارد البشرية', en: 'HR KPIs' },
    manufacturing: { ar: 'مؤشرات أداء التصنيع', en: 'Manufacturing KPIs' },
    projects:      { ar: 'مؤشرات أداء المشاريع', en: 'Projects KPIs' },
    pos:           { ar: 'مؤشرات أداء نقاط البيع', en: 'POS KPIs' },
    crm:           { ar: 'مؤشرات أداء العلاقات', en: 'CRM KPIs' },
    financial:     { ar: 'مؤشرات الأداء المالي', en: 'Financial KPIs' },
};

const API_MAP = {
    sales:         roleDashboardAPI.getSales,
    procurement:   roleDashboardAPI.getProcurement,
    warehouse:     roleDashboardAPI.getWarehouse,
    hr:            roleDashboardAPI.getHR,
    manufacturing: roleDashboardAPI.getManufacturing,
    projects:      roleDashboardAPI.getProjects,
    pos:           roleDashboardAPI.getPOS,
    crm:           roleDashboardAPI.getCRM,
    financial:     roleDashboardAPI.getFinancial,
};

const ModuleKPISection = ({ roleKey, color = '#6366f1', defaultOpen = true }) => {
    const { t, i18n } = useTranslation();
    const { currentBranch } = useBranch();
    const isRTL = i18n.dir() === 'rtl';
    const fallbackCurrency = getCurrency() || 'SAR';

    const [open, setOpen] = useState(defaultOpen);
    const [period, setPeriod] = useState(roleKey === 'pos' ? 'today' : 'mtd');
    const [startDate, setStartDate] = useState('');
    const [endDate, setEndDate] = useState('');
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const label = ROLE_LABELS[roleKey] || { ar: 'مؤشرات الأداء', en: 'KPIs' };

    const fetchData = useCallback(async () => {
        if (!open) return;
        setLoading(true);
        setError(null);
        try {
            const params = { period };
            if (currentBranch) params.branch_id = currentBranch.id;
            if (period === 'custom' && startDate) params.start_date = startDate;
            if (period === 'custom' && endDate) params.end_date = endDate;

            const apiFn = API_MAP[roleKey];
            if (!apiFn) throw new Error('Unknown role key');
            const res = await apiFn(params);
            setData(res.data);
        } catch (err) {
            console.error('KPI fetch error:', err);
            setError(err?.response?.data?.detail || t('kpi.error_loading'));
        } finally {
            setLoading(false);
        }
    }, [roleKey, period, startDate, endDate, currentBranch, open, isRTL]);

    useEffect(() => { if (open) fetchData(); }, [fetchData, open]);

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

    return (
        <div style={{ marginBottom: '1.5rem' }}>
            {/* Section Header — collapsible */}
            <div
                onClick={() => setOpen(!open)}
                style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '12px 16px',
                    background: `linear-gradient(135deg, ${color}08, ${color}14)`,
                    border: `1px solid ${color}30`,
                    borderRadius: open ? '12px 12px 0 0' : '12px',
                    cursor: 'pointer',
                    transition: 'all 0.2s',
                }}
            >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span style={{
                        width: 8, height: 8, borderRadius: '50%',
                        background: color, display: 'inline-block',
                    }} />
                    <h3 style={{
                        margin: 0, fontSize: '0.88rem', fontWeight: 700,
                        color: color,
                    }}>
                        📈 {isRTL ? label.ar : label.en}
                    </h3>
                    {alerts.length > 0 && (
                        <span style={{
                            background: 'rgba(239, 68, 68, 0.12)', color: 'var(--danger)',
                            fontSize: '0.7rem', fontWeight: 600,
                            padding: '2px 8px', borderRadius: '10px',
                        }}>
                            {alerts.length} {t('common.alert')}
                        </span>
                    )}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    {open && (
                        <button
                            onClick={(e) => { e.stopPropagation(); fetchData(); }}
                            disabled={loading}
                            style={{
                                display: 'flex', alignItems: 'center', gap: '4px',
                                padding: '4px 10px', background: 'var(--bg-card)', border: '1px solid var(--border-color)',
                                borderRadius: '6px', fontSize: '0.75rem', cursor: 'pointer', color: 'var(--text-secondary)',
                            }}
                        >
                            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
                        </button>
                    )}
                    {open ? <ChevronUp size={18} color={color} /> : <ChevronDown size={18} color={color} />}
                </div>
            </div>

            {/* Section Body */}
            {open && (
                <div style={{
                    border: `1px solid ${color}20`,
                    borderTop: 'none',
                    borderRadius: '0 0 12px 12px',
                    padding: '16px',
                    background: 'var(--bg-card)',
                }}>
                    {/* Period selector */}
                    <div style={{ marginBottom: '1rem' }}>
                        <PeriodSelector
                            value={period}
                            onChange={handlePeriodChange}
                            startDate={startDate}
                            endDate={endDate}
                        />
                    </div>

                    {/* Error */}
                    {error && (
                        <div style={{
                            padding: '12px 16px', background: '#fef2f2', border: '1px solid #fca5a5',
                            borderRadius: '8px', color: '#991b1b', fontSize: '0.82rem', marginBottom: '1rem',
                        }}>
                            {error}
                        </div>
                    )}

                    {/* Loading skeleton */}
                    {loading && !data && (
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '0.8rem', marginBottom: '1rem' }}>
                            {[1, 2, 3, 4].map(i => (
                                <div key={i} className="card animate-pulse" style={{ height: 100 }}>
                                    <div style={{ height: 10, background: '#f1f5f9', borderRadius: 4, width: '60%', marginBottom: 10 }} />
                                    <div style={{ height: 24, background: '#f1f5f9', borderRadius: 4, width: '40%' }} />
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
                        <div key={cat} style={{ marginBottom: '1rem' }}>
                            {categories.length > 1 && (
                                <h4 style={{
                                    fontSize: '0.78rem', fontWeight: 700, color: 'var(--text-secondary)',
                                    textTransform: 'uppercase', letterSpacing: '0.05em',
                                    marginBottom: '0.5rem', paddingBottom: '0.3rem',
                                    borderBottom: '1px solid var(--border-color)',
                                }}>
                                    {cat}
                                </h4>
                            )}
                            <div style={{
                                display: 'grid',
                                gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
                                gap: '0.7rem',
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
                            gridTemplateColumns: charts.length === 1 ? '1fr' : 'repeat(auto-fit, minmax(380px, 1fr))',
                            gap: '1rem',
                            marginTop: '0.5rem',
                        }}>
                            {charts.map((chart, idx) => (
                                <Card key={idx}>
                                    <KPIChart chart={chart} currency={currency} />
                                </Card>
                            ))}
                        </div>
                    )}

                    {/* Industry KPIs if present */}
                    {data?.industry_kpis && data.industry_kpis.length > 0 && (
                        <div style={{ marginTop: '1rem' }}>
                            <h4 style={{
                                fontSize: '0.78rem', fontWeight: 700, color: 'var(--text-secondary)',
                                textTransform: 'uppercase', letterSpacing: '0.05em',
                                marginBottom: '0.5rem', paddingBottom: '0.3rem',
                                borderBottom: '1px solid var(--border-color)',
                                display: 'flex', alignItems: 'center', gap: '0.3rem',
                            }}>
                                🏢 {t('kpi.industry_kpis')}
                            </h4>
                            <div style={{
                                display: 'grid',
                                gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
                                gap: '0.7rem',
                            }}>
                                {data.industry_kpis.map((kpi, idx) => (
                                    <KPICard key={idx} kpi={kpi} currency={currency} />
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

export default ModuleKPISection;
