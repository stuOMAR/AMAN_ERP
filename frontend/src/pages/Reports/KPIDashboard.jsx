import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { reportsAPI } from '../../utils/api';
import { getCurrency } from '../../utils/auth';
import { formatNumber as formatDecimal } from '../../utils/format';
import { useToast } from '../../context/ToastContext';
import { BarChart3, TrendingUp, TrendingDown, DollarSign, Package, Users, Wallet, ArrowUpRight, ArrowDownRight, RefreshCw } from 'lucide-react';
import BackButton from '../../components/common/BackButton';
import '../../components/ModuleStyles.css';
import { PageLoading } from '../../components/common/LoadingStates'

const KPIDashboard = () => {
    const { t } = useTranslation();
    const currency = getCurrency() || 'SAR';
    const { showToast } = useToast();
    const [kpiData, setKpiData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [lastRefresh, setLastRefresh] = useState(null);

    useEffect(() => { fetchKPIs(); }, []);

    const fetchKPIs = async () => {
        try {
            setLoading(true);
            const res = await reportsAPI.getKPIDashboard();
            setKpiData(res.data);
            setLastRefresh(new Date());
        } catch (err) {
            showToast(err.response?.data?.detail || (t('reports.error_loading_kpis')), 'error');
            console.error(err);
        } finally { setLoading(false); }
    };

    const amountAbs = (value) => {
        const raw = String(value || '0').trim();
        return raw.startsWith('-') ? raw.slice(1) : raw;
    };

    const isZeroAmount = (value) => /^[-+]?0+(\.0+)?$/.test(String(value || '0').trim());
    const isNegativeAmount = (value) => String(value || '0').trim().startsWith('-') && !isZeroAmount(value);
    const isAtLeastOne = (value) => {
        const raw = String(value || '0').trim();
        if (raw.startsWith('-')) return false;
        return !/^0*(\.|$)/.test(raw);
    };

    const formatCurrency = (val) => {
        if (val === null || val === undefined || val === '') return '—';
        return `${formatDecimal(val)} ${currency}`;
    };

    const formatCount = (val) => {
        if (val === null || val === undefined || val === '') return '—';
        return formatDecimal(String(val), 0);
    };

    const changeIndicator = (val) => {
        if (!val || isZeroAmount(val)) return null;
        const isPositive = !isNegativeAmount(val);
        return (
            <span className="d-flex align-items-center gap-1" style={{ fontSize: '0.8rem', color: isPositive ? '#2e7d32' : '#c62828' }}>
                {isPositive ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
                {amountAbs(val)}%
            </span>
        );
    };

    const kpiCards = kpiData ? [
        {
            label: t('reports.revenue'),
            value: formatCurrency(kpiData.revenue),
            change: kpiData.revenue_change,
            icon: <DollarSign size={24} />,
            iconBg: '#e8f5e9', iconColor: '#2e7d32',
            accounting: t('reports.total_recognized_revenue_cr_4xxx')
        },
        {
            label: t('reports.expenses'),
            value: formatCurrency(kpiData.expenses),
            change: kpiData.expenses_change,
            icon: <TrendingDown size={24} />,
            iconBg: '#fce4ec', iconColor: '#c62828',
            accounting: t('reports.total_expenses_dr_5xxx6xxx'),
            invertColor: true
        },
        {
            label: t('reports.accounts_receivable'),
            value: formatCurrency(kpiData.accounts_receivable),
            change: kpiData.ar_change,
            icon: <TrendingUp size={24} />,
            iconBg: '#e3f2fd', iconColor: '#1565c0',
            accounting: t('reports.ar_balance_dr_1200')
        },
        {
            label: t('reports.accounts_payable'),
            value: formatCurrency(kpiData.accounts_payable),
            change: kpiData.ap_change,
            icon: <Wallet size={24} />,
            iconBg: '#fff3e0', iconColor: '#e65100',
            accounting: t('reports.ap_balance_cr_2100')
        },
        {
            label: t('reports.cash_balance'),
            value: formatCurrency(kpiData.cash_balance),
            change: kpiData.cash_change,
            icon: <DollarSign size={24} />,
            iconBg: '#f3e5f5', iconColor: '#7b1fa2',
            accounting: t('reports.cash_bank_balances_10001100')
        },
        {
            label: t('reports.inventory_value'),
            value: formatCurrency(kpiData.inventory_value),
            change: kpiData.inventory_change,
            icon: <Package size={24} />,
            iconBg: '#e0f2f1', iconColor: '#00695c',
            accounting: t('reports.ending_inventory_dr_1400')
        },
        {
            label: t('reports.employee_count'),
            value: formatCount(kpiData.employee_count),
            change: kpiData.employee_change,
            icon: <Users size={24} />,
            iconBg: '#fce4ec', iconColor: '#ad1457',
            accounting: t('reports.active_headcount')
        }
    ] : [];

    const ratios = kpiData?.financial_ratios || null;

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="d-flex align-items-center justify-content-between w-100">
                    <div>
                        <h1 className="workspace-title">
                            <BarChart3 size={24} className="me-2" />
                            {t('reports.key_performance_indicators')}
                        </h1>
                        <p className="workspace-subtitle">
                            {t('reports.live_financial_operational_kpis_with_accounting_ra')}
                            {lastRefresh && <span className="ms-2 text-muted" style={{ fontSize: '0.8rem' }}>
                                ({t('reports.last')}{lastRefresh.toLocaleTimeString()})
                            </span>}
                        </p>
                    </div>
                    <button className="btn btn-outline-primary" onClick={fetchKPIs} disabled={loading}>
                        <RefreshCw size={16} className={loading ? 'spin' : ''} /> <span className="ms-1">{t('reports.refresh')}</span>
                    </button>
                </div>
            </div>

            {loading && !kpiData ? (
                <PageLoading />
            ) : (
                <>
                    {/* KPI Cards */}
                    <div className="metrics-grid mb-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))' }}>
                        {kpiCards.map((kpi, idx) => (
                            <div key={idx} className="metric-card" style={{ position: 'relative' }}>
                                <div className="metric-icon" style={{ background: kpi.iconBg, color: kpi.iconColor }}>
                                    {kpi.icon}
                                </div>
                                <div className="metric-info">
                                    <div className="d-flex align-items-center gap-2">
                                        <span className="metric-value">{kpi.value}</span>
                                        {changeIndicator(kpi.change)}
                                    </div>
                                    <span className="metric-label">{kpi.label}</span>
                                    <small className="text-muted" style={{ fontSize: '0.7rem' }}>{kpi.accounting}</small>
                                </div>
                            </div>
                        ))}
                    </div>

                    {/* Financial Ratios */}
                    {ratios && (
                        <div className="section-card mb-4">
                            <h4 className="mb-3">{t('reports.key_financial_ratios')}</h4>
                            <div className="row g-3">
                                <div className="col-md-3">
                                    <div className="p-3 rounded" style={{ background: !isNegativeAmount(ratios.net_income) ? '#e8f5e9' : '#fce4ec', textAlign: 'center' }}>
                                        <div style={{ fontSize: '1.4rem', fontWeight: 700, color: !isNegativeAmount(ratios.net_income) ? '#2e7d32' : '#c62828' }}>
                                            {formatCurrency(ratios.net_income)}
                                        </div>
                                        <div style={{ fontWeight: 600 }}>{t('reports.net_income')}</div>
                                        <small className="text-muted">{t('reports.revenue_expenses')}</small>
                                    </div>
                                </div>
                                <div className="col-md-3">
                                    <div className="p-3 rounded" style={{ background: '#f3f4f6', textAlign: 'center' }}>
                                        <div style={{ fontSize: '1.4rem', fontWeight: 700, color: !isNegativeAmount(ratios.profit_margin) ? '#2e7d32' : '#c62828' }}>
                                            {ratios.profit_margin}%
                                        </div>
                                        <div style={{ fontWeight: 600 }}>{t('reports.profit_margin')}</div>
                                        <small className="text-muted">{t('reports.net_income_revenue')}</small>
                                    </div>
                                </div>
                                <div className="col-md-3">
                                    <div className="p-3 rounded" style={{ background: isAtLeastOne(ratios.current_ratio) ? '#e8f5e9' : '#fff3e0', textAlign: 'center' }}>
                                        <div style={{ fontSize: '1.4rem', fontWeight: 700 }}>
                                            {ratios.current_ratio}x
                                        </div>
                                        <div style={{ fontWeight: 600 }}>{t('reports.current_ratio')}</div>
                                        <small className="text-muted">{t('reports.current_assets_current_liabilities')}</small>
                                    </div>
                                </div>
                                <div className="col-md-3">
                                    <div className="p-3 rounded" style={{ background: '#f3f4f6', textAlign: 'center' }}>
                                        <div style={{ fontSize: '1.4rem', fontWeight: 700 }}>
                                            {ratios.ar_turnover}x
                                        </div>
                                        <div style={{ fontWeight: 600 }}>{t('reports.ar_turnover')}</div>
                                        <small className="text-muted">{t('reports.sales_avg_ar')}</small>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Accounting Reference */}
                    <div className="section-card" style={{ background: '#f0f7ff', border: '1px dashed #90caf9' }}>
                        <h5 style={{ color: '#1565c0' }}>{t('reports.accounting_reference')}</h5>
                        <div className="row g-3">
                            <div className="col-md-6">
                                <table className="data-table" style={{ fontSize: '0.85rem' }}>
                                    <thead>
                                        <tr>
                                            <th>{t('reports.kpi')}</th>
                                            <th>{t('reports.standard')}</th>
                                            <th>{t('reports.gl_accounts')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        <tr><td>{t('reports.revenue')}</td><td>IFRS 15</td><td>4000-4999</td></tr>
                                        <tr><td>{t('reports.expenses')}</td><td>IAS 1</td><td>5000-6999</td></tr>
                                        <tr><td>{t('reports.accounts_receivable_abbr')}</td><td>IFRS 9</td><td>1200-1299</td></tr>
                                        <tr><td>{t('reports.accounts_payable_abbr')}</td><td>IAS 37</td><td>2100-2199</td></tr>
                                    </tbody>
                                </table>
                            </div>
                            <div className="col-md-6">
                                <table className="data-table" style={{ fontSize: '0.85rem' }}>
                                    <thead>
                                        <tr>
                                            <th>{t('reports.kpi')}</th>
                                            <th>{t('reports.standard')}</th>
                                            <th>{t('reports.gl_accounts')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        <tr><td>{t('reports.cash')}</td><td>IAS 7</td><td>1000-1100</td></tr>
                                        <tr><td>{t('reports.inventory')}</td><td>IAS 2</td><td>1400-1499</td></tr>
                                        <tr><td>{t('reports.payroll')}</td><td>IAS 19</td><td>5100-5199</td></tr>
                                        <tr><td>{t('reports.leases')}</td><td>IFRS 16</td><td>1600, 2300</td></tr>
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                </>
            )}
        </div>
    );
};

export default KPIDashboard;
