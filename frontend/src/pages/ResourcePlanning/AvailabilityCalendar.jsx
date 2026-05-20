import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import Decimal from 'decimal.js';
import { resourceAPI } from '../../utils/api';
import { AlertTriangle } from 'lucide-react';
import '../../index.css';
import '../../components/ModuleStyles.css';
import BackButton from '../../components/common/BackButton';
import DateInput from '../../components/common/DateInput';
import { PageLoading } from '../../components/common/LoadingStates'

// Color by allocation percentage
function allocColor(pct) {
    if (pct === 0) return '#e9ecef';
    if (pct <= 50) return '#d4edda';
    if (pct <= 80) return '#fff3cd';
    if (pct <= 100) return '#ffeeba';
    return '#f8d7da';
}

function getWeekStarts(dateFrom, dateTo) {
    const weeks = [];
    const cur = new Date(dateFrom + 'T00:00:00');
    const day = cur.getDay();
    const diff = day === 0 ? -6 : 1 - day;
    cur.setDate(cur.getDate() + diff);
    const end = new Date(dateTo + 'T00:00:00');
    while (cur <= end) {
        weeks.push(cur.toISOString().slice(0, 10));
        cur.setDate(cur.getDate() + 7);
    }
    return weeks;
}

function isOverlapping(allocStart, allocEnd, weekStart) {
    const ws = new Date(weekStart + 'T00:00:00');
    const we = new Date(ws);
    we.setDate(ws.getDate() + 6);
    const as2 = new Date(allocStart + 'T00:00:00');
    const ae = new Date(allocEnd + 'T00:00:00');
    return as2 <= we && ae >= ws;
}

const AvailabilityCalendar = () => {
    const { t, i18n } = useTranslation();
    const isRTL = i18n.language === 'ar';

    const today = new Date();
    const threeMonths = new Date(today);
    threeMonths.setDate(today.getDate() + 90);

    const [dateFrom, setDateFrom] = useState(today.toISOString().slice(0, 10));
    const [dateTo, setDateTo] = useState(threeMonths.toISOString().slice(0, 10));
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);

    const load = () => {
        setLoading(true);
        resourceAPI.getAvailability({ date_from: dateFrom, date_to: dateTo })
            .then(res => setData(res.data))
            .catch(e => console.error(e))
            .finally(() => setLoading(false));
    };

    useEffect(() => { load(); }, [dateFrom, dateTo]);

    const weeks = getWeekStarts(dateFrom, dateTo);

    return (
        <div className="module-container" dir={isRTL ? 'rtl' : 'ltr'}>
            <BackButton />
            <div className="module-header">
                <h1>{t('resource.availability_calendar')}</h1>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <DateInput className="form-control" value={dateFrom}
                           onChange={e => setDateFrom(e.target.value)} style={{ maxWidth: 160 }} />
                    <span>→</span>
                    <DateInput className="form-control" value={dateTo}
                           onChange={e => setDateTo(e.target.value)} style={{ maxWidth: 160 }} />
                </div>
            </div>

            {/* Legend */}
            <div style={{ display: 'flex', gap: 16, marginBottom: 16, fontSize: 13 }}>
                {[
                    { label: t('resource.free'), color: '#e9ecef' },
                    { label: '≤50%', color: '#d4edda' },
                    { label: '51-80%', color: '#fff3cd' },
                    { label: '81-100%', color: '#ffeeba' },
                    { label: '>100%', color: '#f8d7da' },
                ].map(l => (
                    <span key={l.label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                        <span style={{ width: 14, height: 14, background: l.color, borderRadius: 3, border: '1px solid #ccc' }} />
                        {l.label}
                    </span>
                ))}
            </div>

            {loading ? (
                <PageLoading />
            ) : !data || data.employees.length === 0 ? (
                <div className="empty-state">{t('resource.no_allocations')}</div>
            ) : (
                <div style={{ overflowX: 'auto' }}>
                    <table className="data-table" style={{ minWidth: 600 }}>
                        <thead>
                            <tr>
                                <th style={{ minWidth: 160, position: 'sticky', left: 0, background: '#fff', zIndex: 1 }}>
                                    {t('resource.employee')}
                                </th>
                                <th style={{ width: 70 }}>{t('resource.total')}</th>
                                {weeks.map(w => {
                                    const d = new Date(w + 'T00:00:00');
                                    return (
                                        <th key={w} style={{ textAlign: 'center', minWidth: 60, fontSize: 11 }}>
                                            {d.toLocaleDateString(i18n.language, { month: 'short', day: 'numeric' })}
                                        </th>
                                    );
                                })}
                            </tr>
                        </thead>
                        <tbody>
                            {data.employees.map(emp => (
                                <tr key={emp.employee_id}>
                                    <td style={{ position: 'sticky', left: 0, background: '#fff', zIndex: 1 }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                            {emp.employee_name}
                                            {emp.is_over_allocated && (
                                                <AlertTriangle size={14} color="#dc3545" title={t('resource.over_allocated')} />
                                            )}
                                        </div>
                                    </td>
                                    <td style={{
                                        fontWeight: 700,
                                        color: emp.is_over_allocated ? '#dc3545' : '#28a745',
                                        textAlign: 'center',
                                    }}>
                                        {emp.total_allocation.toFixed(0)}%
                                    </td>
                                    {weeks.map(w => {
                                        const weekAllocs = emp.allocations.filter(a =>
                                            isOverlapping(a.start_date, a.end_date, w)
                                        );
                                        const weekPct = weekAllocs.reduce((s, a) => s.plus(new Decimal(a.allocation_percent || '0')), new Decimal('0'));
                                        const weekPctNum = weekPct.toNumber();
                                        return (
                                            <td key={w} style={{
                                                background: allocColor(weekPctNum),
                                                textAlign: 'center',
                                                fontWeight: 600,
                                                fontSize: 12,
                                                color: weekPctNum > 100 ? '#dc3545' : '#333',
                                            }}
                                            title={weekAllocs.map(a => `${a.project_name}: ${a.allocation_percent}%`).join('\n')}
                                            >
                                                {weekPctNum > 0 ? `${weekPct.toFixed(0)}%` : ''}
                                            </td>
                                        );
                                    })}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
};

export default AvailabilityCalendar;
