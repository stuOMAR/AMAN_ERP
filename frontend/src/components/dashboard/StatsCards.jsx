import React from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowUpRight, ArrowDownRight } from 'lucide-react';
import { formatNumber } from '../../utils/format';

const StatsCard = ({ title, value, trend, trendValue, currency, isLongText }) => {
    return (
        <div className="metric-card">
            <div className="metric-label">{title}</div>
            <div className={`metric-value ${isLongText ? 'text-sm' : ''}`} style={isLongText ? { fontSize: '14px', lineHeight: '1.4' } : {}}>
                {value} {!isLongText && <small>{currency}</small>}
            </div>
            {trend && (
                <div className={`metric-change ${trend === 'up' ? 'text-success' : 'text-danger'}`} style={{ display: 'flex', alignItems: 'center', gap: '4px', marginTop: '8px' }}>
                    {trend === 'up' ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
                    <span style={{ fontSize: '11px', fontWeight: '600' }}>{trendValue}</span>
                </div>
            )}
        </div>
    );
};

const StatsCards = ({ stats, loading, currency = '' }) => {
    const { t } = useTranslation();

    if (loading) {
        return (
            <div className="metrics-grid mb-6">
                {[1, 2, 3, 4].map((i) => (
                    <div key={i} className="metric-card animate-pulse" style={{ height: '100px' }}>
                        <div className="h-3 bg-slate-100 rounded-full w-1/3 mb-4"></div>
                        <div className="h-8 bg-slate-100 rounded-full w-2/3"></div>
                    </div>
                ))}
            </div>
        );
    }

    const cards = [
        {
            title: t('dashboard.total_sales'),
            value: formatNumber(stats?.sales || 0),
            trend: (stats?.sales_change || 0) >= 0 ? "up" : "down",
            trendValue: `${stats?.sales_change > 0 ? "+" : ""}${stats?.sales_change || 0}%`
        },
        {
            title: t('accounting.home.metrics.total_expenses') || t('dashboard.expenses'),
            value: formatNumber(stats?.expenses || 0),
            trend: (stats?.expenses_change || 0) <= 0 ? "down" : "up", // Down is good for expenses usually but icon shows direction
            trendValue: `${stats?.expenses_change > 0 ? "+" : ""}${stats?.expenses_change || 0}%`
        },
        {
            title: t('accounting.home.metrics.net_profit') || t('dashboard.net_profit'),
            value: formatNumber(stats?.profit || 0),
            trend: (stats?.profit_change || 0) >= 0 ? "up" : "down",
            trendValue: `${stats?.profit_change > 0 ? "+" : ""}${stats?.profit_change || 0}%`
        },
        {
            title: t('accounting.home.metrics.cash_balance') || t('dashboard.all_cash'),
            value: formatNumber(stats?.cash || 0),
            trend: (stats?.cash_change || 0) >= 0 ? "up" : "down",
            trendValue: `${stats?.cash_change > 0 ? "+" : ""}${stats?.cash_change || 0}%`
        }
    ];

    return (
        <div className="metrics-grid mb-6">
            {cards.map((card, index) => (
                <StatsCard key={index} {...card} currency={card.currency !== undefined ? card.currency : currency} />
            ))}
        </div>
    );
};

export default StatsCards;
