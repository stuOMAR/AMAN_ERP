import React, { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { timesheetAPI, projectsAPI } from '../../utils/api';
import Decimal from 'decimal.js';
import { toastEmitter } from '../../utils/toastEmitter';
import { CheckCircle, Plus, Trash2, Send } from 'lucide-react';
import '../../index.css';
import '../../components/ModuleStyles.css';
import BackButton from '../../components/common/BackButton';
import DateInput from '../../components/common/DateInput';

// Generate the 7 dates of the week starting from weekStart (ISO date string "YYYY-MM-DD")
function getWeekDates(weekStart) {
    const start = new Date(weekStart + 'T00:00:00');
    return Array.from({ length: 7 }, (_, i) => {
        const d = new Date(start);
        d.setDate(start.getDate() + i);
        return d.toISOString().slice(0, 10);
    });
}

function getMondayOfCurrentWeek() {
    const today = new Date();
    const day = today.getDay(); // 0=Sun, 1=Mon...
    const diff = day === 0 ? -6 : 1 - day;
    const monday = new Date(today);
    monday.setDate(today.getDate() + diff);
    return monday.toISOString().slice(0, 10);
}

const emptyRow = () => ({
    _key: Math.random(),
    project_id: '',
    task_id: '',
    is_billable: true,
    billing_rate: '',
    description: '',
    hours: {},   // keyed by date
});

const TimesheetWeek = () => {
    const { t, i18n } = useTranslation();
    const isRTL = i18n.language === 'ar';

    const [weekStart, setWeekStart] = useState(getMondayOfCurrentWeek());
    const [rows, setRows] = useState([emptyRow()]);
    const [projects, setProjects] = useState([]);
    const [tasksByProject, setTasksByProject] = useState({});
    const [currentUser, setCurrentUser] = useState(null);
    const [saving, setSaving] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [savedEntries, setSavedEntries] = useState([]);
    const [successMsg, setSuccessMsg] = useState('');

    const weekDates = getWeekDates(weekStart);

    useEffect(() => {
        projectsAPI.list().then(res => setProjects(res.data || [])).catch(() => {});
        // Try to get current user employee_id from profile
        import('../../utils/api').then(({ authAPI }) => {
            if (authAPI?.me) {
                authAPI.me().then(res => setCurrentUser(res.data)).catch(() => {});
            }
        }).catch(() => {});
    }, []);

    useEffect(() => {
        // Load existing entries for the week
        timesheetAPI.listOwn({
            date_from: weekStart,
            date_to: weekDates[6],
        }).then(res => setSavedEntries(res.data || [])).catch(() => {});
    }, [weekStart]);

    const loadTasks = useCallback((projectId) => {
        if (!projectId || tasksByProject[projectId]) return;
        projectsAPI.getTasks(projectId)
            .then(res => setTasksByProject(prev => ({ ...prev, [projectId]: res.data || [] })))
            .catch(() => {});
    }, [tasksByProject]);

    const updateRow = (key, field, value) => {
        setRows(prev => prev.map(r => r._key === key ? { ...r, [field]: value } : r));
        if (field === 'project_id') loadTasks(value);
    };

    const updateHours = (key, date, value) => {
        setRows(prev => prev.map(r =>
            r._key === key ? { ...r, hours: { ...r.hours, [date]: value } } : r
        ));
    };

    const addRow = () => setRows(prev => [...prev, emptyRow()]);
    const removeRow = (key) => setRows(prev => prev.filter(r => r._key !== key));

    const handleSave = async () => {
        setSaving(true);
        setSuccessMsg('');
        try {
            const entries = [];
            for (const row of rows) {
                if (!row.project_id) continue;
                for (const [date, hrs] of Object.entries(row.hours)) {
                    if (!hrs || Number(hrs) <= 0) continue;
                    entries.push({
                        project_id: parseInt(row.project_id),
                        task_id: row.task_id ? parseInt(row.task_id) : null,
                        date,
                        hours: hrs,
                        is_billable: row.is_billable,
                        billing_rate: row.billing_rate || null,
                        description: row.description || null,
                        employee_id: currentUser?.employee_id || 1,
                    });
                }
            }
            await Promise.all(entries.map(e => timesheetAPI.logEntry(e)));
            setSuccessMsg(t('timetracking.saved_successfully'));
            // Refresh saved entries
            const res = await timesheetAPI.listOwn({ date_from: weekStart, date_to: weekDates[6] });
            setSavedEntries(res.data || []);
        } catch (err) {
            toastEmitter.emit(t('common.error'), 'error');
        } finally {
            setSaving(false);
        }
    };

    const handleSubmitWeek = async () => {
        setSubmitting(true);
        setSuccessMsg('');
        try {
            const res = await timesheetAPI.submitWeek({
                week_start: weekStart,
                employee_id: currentUser?.employee_id || 1,
            });
            setSuccessMsg(t('timetracking.submitted_count', { count: res.data?.submitted_count || 0 }));
            const refresh = await timesheetAPI.listOwn({ date_from: weekStart, date_to: weekDates[6] });
            setSavedEntries(refresh.data || []);
        } catch (err) {
            toastEmitter.emit(t('common.error'), 'error');
        } finally {
            setSubmitting(false);
        }
    };

    const totalHours = (date) =>
        rows.reduce((sum, r) => sum.plus(new Decimal(r.hours[date] || '0')), new Decimal('0'));

    const grandTotal = weekDates.reduce((s, d) => s.plus(totalHours(d)), new Decimal('0'));

    const dayLabels = weekDates.map(d => {
        const dt = new Date(d + 'T00:00:00');
        return { date: d, label: dt.toLocaleDateString(i18n.language, { weekday: 'short', month: 'short', day: 'numeric' }) };
    });

    return (
        <div className="module-container" dir={isRTL ? 'rtl' : 'ltr'}>
            <BackButton />
            <div className="module-header">
                <h1>{t('timetracking.weekly_timesheet')}</h1>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <label>{t('timetracking.week_starting')}</label>
                    <DateInput
                        className="form-control"
                        value={weekStart}
                        onChange={e => setWeekStart(e.target.value)}
                        style={{ maxWidth: 160 }}
                    />
                    <button className="btn btn-secondary" onClick={handleSave} disabled={saving}>
                        {saving ? t('common.saving') : t('common.save')}
                    </button>
                    <button className="btn btn-primary" onClick={handleSubmitWeek} disabled={submitting}>
                        <Send size={14} /> {submitting ? t('common.submitting') : t('timetracking.submit_week')}
                    </button>
                </div>
            </div>

            {successMsg && (
                <div className="alert alert-success" style={{ marginBottom: 12 }}>
                    <CheckCircle size={16} /> {successMsg}
                </div>
            )}

            <div style={{ overflowX: 'auto' }}>
                <table className="data-table" style={{ minWidth: 900 }}>
                    <thead>
                        <tr>
                            <th style={{ minWidth: 160 }}>{t('timetracking.project')}</th>
                            <th style={{ minWidth: 140 }}>{t('timetracking.task')}</th>
                            <th style={{ minWidth: 90 }}>{t('timetracking.billable')}</th>
                            <th style={{ minWidth: 90 }}>{t('timetracking.rate')}</th>
                            {dayLabels.map(d => (
                                <th key={d.date} style={{ minWidth: 80, textAlign: 'center' }}>{d.label}</th>
                            ))}
                            <th style={{ minWidth: 70, textAlign: 'center' }}>{t('timetracking.total')}</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows.map(row => {
                            const rowTotal = weekDates.reduce((s, d) => s.plus(new Decimal(row.hours[d] || '0')), new Decimal('0'));
                            return (
                                <tr key={row._key}>
                                    <td>
                                        <select
                                            className="form-control"
                                            value={row.project_id}
                                            onChange={e => updateRow(row._key, 'project_id', e.target.value)}
                                        >
                                            <option value="">{t('timetracking.select_project')}</option>
                                            {projects.map(p => (
                                                <option key={p.id} value={p.id}>{p.project_name}</option>
                                            ))}
                                        </select>
                                    </td>
                                    <td>
                                        <select
                                            className="form-control"
                                            value={row.task_id}
                                            onChange={e => updateRow(row._key, 'task_id', e.target.value)}
                                            disabled={!row.project_id}
                                        >
                                            <option value="">{t('timetracking.no_task')}</option>
                                            {(tasksByProject[row.project_id] || []).map(t2 => (
                                                <option key={t2.id} value={t2.id}>{t2.task_name}</option>
                                            ))}
                                        </select>
                                    </td>
                                    <td style={{ textAlign: 'center' }}>
                                        <input
                                            type="checkbox"
                                            checked={row.is_billable}
                                            onChange={e => updateRow(row._key, 'is_billable', e.target.checked)}
                                        />
                                    </td>
                                    <td>
                                        <input
                                            type="number"
                                            className="form-control"
                                            min="0"
                                            step="0.01"
                                            placeholder="0.00"
                                            value={row.billing_rate}
                                            onChange={e => updateRow(row._key, 'billing_rate', e.target.value)}
                                            disabled={!row.is_billable}
                                        />
                                    </td>
                                    {weekDates.map(date => (
                                        <td key={date} style={{ textAlign: 'center' }}>
                                            <input
                                                type="number"
                                                className="form-control"
                                                min="0"
                                                max="24"
                                                step="0.5"
                                                placeholder="0"
                                                value={row.hours[date] || ''}
                                                onChange={e => updateHours(row._key, date, e.target.value)}
                                                style={{ width: 64, textAlign: 'center' }}
                                            />
                                        </td>
                                    ))}
                                    <td style={{ textAlign: 'center', fontWeight: 600 }}>
                                        {rowTotal.toFixed(1)}
                                    </td>
                                    <td>
                                        <button
                                            className="btn btn-sm btn-ghost"
                                            onClick={() => removeRow(row._key)}
                                            title={t('common.remove')}
                                        >
                                            <Trash2 size={14} />
                                        </button>
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                    <tfoot>
                        <tr style={{ fontWeight: 700 }}>
                            <td colSpan={4}>{t('timetracking.daily_total')}</td>
                            {weekDates.map(d => (
                                <td key={d} style={{ textAlign: 'center' }}>{totalHours(d).toFixed(1)}</td>
                            ))}
                            <td style={{ textAlign: 'center' }}>{grandTotal.toFixed(1)}</td>
                            <td></td>
                        </tr>
                    </tfoot>
                </table>
            </div>

            <button className="btn btn-secondary" style={{ marginTop: 12 }} onClick={addRow}>
                <Plus size={14} /> {t('timetracking.add_row')}
            </button>

            {savedEntries.length > 0 && (
                <div style={{ marginTop: 24 }}>
                    <h3>{t('timetracking.saved_entries')}</h3>
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>{t('timetracking.date')}</th>
                                <th>{t('timetracking.project')}</th>
                                <th>{t('timetracking.task')}</th>
                                <th>{t('timetracking.hours')}</th>
                                <th>{t('timetracking.billable')}</th>
                                <th>{t('timetracking.status')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {savedEntries.map(e => (
                                <tr key={e.id}>
                                    <td>{e.date}</td>
                                    <td>{e.project_name}</td>
                                    <td>{e.task_name || '—'}</td>
                                    <td>{e.hours}</td>
                                    <td>
                                        <span className={`badge ${e.is_billable ? 'badge-success' : 'badge-secondary'}`}>
                                            {e.is_billable ? t('timetracking.billable') : t('timetracking.non_billable')}
                                        </span>
                                    </td>
                                    <td>
                                        <span className={`badge badge-${
                                            e.status === 'approved' ? 'success' :
                                            e.status === 'submitted' ? 'warning' :
                                            e.status === 'rejected' ? 'danger' : 'secondary'
                                        }`}>
                                            {t(`timetracking.status_${e.status}`)}
                                        </span>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
};

export default TimesheetWeek;
