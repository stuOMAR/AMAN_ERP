import React from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowUpRight, ArrowDownRight, Minus } from 'lucide-react';
import { formatNumber } from '../../utils/format';
import { useTheme } from '../../context/ThemeContext';

/**
 * KPICard — displays a single KPI metric with trend, status, and optional sparkline.
 * بطاقة مؤشر أداء مع اتجاه وحالة
 *
 * Props:
 *   kpi.label / kpi.label_ar — title
 *   kpi.value — numeric value
 *   kpi.formatted — pre-formatted display string (optional)
 *   kpi.unit — %, SAR, days, etc.
 *   kpi.trend — up | down | flat
 *   kpi.trend_pct — percentage change
 *   kpi.status — good | warning | danger | neutral
 *   kpi.target — target value (optional)
 *   kpi.category — grouping label
 */

const STATUS_COLORS_LIGHT = {
    good:    { bg: '#f0fdf4', border: '#bbf7d0', text: '#15803d', dot: '#22c55e' },
    warning: { bg: '#fffbeb', border: '#fde68a', text: '#a16207', dot: '#f59e0b' },
    danger:  { bg: '#fef2f2', border: '#fecaca', text: '#b91c1c', dot: '#ef4444' },
    neutral: { bg: '#f8fafc', border: '#e2e8f0', text: '#475569', dot: '#94a3b8' },
};

const STATUS_COLORS_DARK = {
    good:    { bg: '#132a1f', border: '#1f6b4a', text: '#86efac', dot: '#22c55e' },
    warning: { bg: '#2f2413', border: '#7c5c1a', text: '#fcd34d', dot: '#f59e0b' },
    danger:  { bg: '#32191c', border: '#8a2e39', text: '#fca5a5', dot: '#ef4444' },
    neutral: { bg: '#1b2a41', border: '#334155', text: '#cbd5e1', dot: '#94a3b8' },
};

const KPICard = ({ kpi, currency = '', compact = false }) => {
    const { t, i18n } = useTranslation();
    const { darkMode } = useTheme();
    const isRTL = i18n.dir() === 'rtl';

    if (!kpi) return null;

    const status = kpi.status || 'neutral';
    const palette = darkMode ? STATUS_COLORS_DARK : STATUS_COLORS_LIGHT;
    const colors = palette[status] || palette.neutral;
    const label = isRTL ? (kpi.label_ar || kpi.label) : (kpi.label || kpi.label_ar);
    const displayValue = kpi.formatted || formatNumber(kpi.value ?? 0);
    // Use the unit from KPI if it's a currency code (like SAR, EGP), otherwise use passed currency
    const unit = kpi.unit === 'currency' ? currency : (kpi.unit && kpi.unit.length === 3 ? kpi.unit : (kpi.unit || ''));

    const TrendIcon = kpi.trend === 'up' ? ArrowUpRight
        : kpi.trend === 'down' ? ArrowDownRight
        : Minus;

    const trendColor = kpi.trend === 'up'
        ? (status === 'danger' ? '#ef4444' : '#22c55e')
        : kpi.trend === 'down'
        ? (status === 'good' ? '#22c55e' : '#ef4444')
        : '#94a3b8';

    return (
        <div
            className="kpi-card"
            style={{
                background: colors.bg,
                border: `1px solid ${colors.border}`,
                borderRadius: compact ? '10px' : '12px',
                padding: compact ? '12px 14px' : '16px 20px',
                minWidth: compact ? '160px' : '200px',
                transition: 'box-shadow .2s, transform .2s',
                cursor: 'default',
                position: 'relative',
            }}
            onMouseEnter={e => {
                e.currentTarget.style.boxShadow = '0 4px 16px rgba(0,0,0,.08)';
                e.currentTarget.style.transform = 'translateY(-1px)';
            }}
            onMouseLeave={e => {
                e.currentTarget.style.boxShadow = '';
                e.currentTarget.style.transform = '';
            }}
        >
            {/* Status dot */}
            <div style={{
                position: 'absolute', top: compact ? 8 : 12,
                [isRTL ? 'left' : 'right']: compact ? 8 : 12,
                width: 8, height: 8, borderRadius: '50%',
                background: colors.dot,
            }} />

            {/* Label */}
            <div style={{
                fontSize: compact ? '0.72rem' : '0.78rem',
                fontWeight: 600,
                color: colors.text,
                opacity: 0.85,
                marginBottom: compact ? 4 : 6,
                paddingInlineEnd: 16,
                lineHeight: 1.4,
            }}>
                {label}
            </div>

            {/* Value */}
            <div style={{
                fontSize: compact ? '1.2rem' : '1.5rem',
                fontWeight: 700,
                color: 'var(--text-main, #1e293b)',
                lineHeight: 1.2,
                marginBottom: compact ? 4 : 8,
                display: 'flex',
                alignItems: 'baseline',
                gap: '0.3rem',
            }}>
                <span>{displayValue}</span>
                {unit && <small style={{ fontSize: '0.65em', fontWeight: 500, color: 'var(--text-secondary, #64748b)' }}>{unit}</small>}
            </div>

            {/* Trend */}
            {kpi.trend && (
                <div style={{
                    display: 'flex', alignItems: 'center', gap: '4px',
                    fontSize: '0.72rem', fontWeight: 600, color: trendColor,
                }}>
                    <TrendIcon size={13} />
                    <span>
                        {kpi.trend_pct != null
                            ? `${kpi.trend_pct > 0 ? '+' : ''}${kpi.trend_pct}%`
                            : kpi.trend === 'up' ? '↑' : kpi.trend === 'down' ? '↓' : '—'}
                    </span>
                </div>
            )}

            {/* Target bar */}
            {kpi.target != null && kpi.value != null && (
                <div style={{ marginTop: 8 }}>
                    <div style={{
                        display: 'flex', justifyContent: 'space-between',
                        fontSize: '0.65rem', color: 'var(--text-muted, #94a3b8)', marginBottom: 3,
                    }}>
                        <span>{t('kpi.target')}</span>
                        <span>{formatNumber(kpi.target)} {unit}</span>
                    </div>
                    <div style={{
                        height: 4, background: darkMode ? '#334155' : '#e2e8f0', borderRadius: 2, overflow: 'hidden',
                    }}>
                        <div style={{
                            height: '100%',
                            width: `${Math.min((kpi.value / kpi.target) * 100, 100)}%`,
                            background: colors.dot,
                            borderRadius: 2,
                            transition: 'width .5s ease',
                        }} />
                    </div>
                </div>
            )}
        </div>
    );
};

export default KPICard;
