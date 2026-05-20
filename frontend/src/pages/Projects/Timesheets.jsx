import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation } from 'react-router-dom';
import Decimal from 'decimal.js';
import { format, startOfWeek, addDays, eachDayOfInterval } from 'date-fns';
import { ar, enUS } from 'date-fns/locale';
import { ChevronRight, ChevronLeft, Save, CheckCircle2 } from 'lucide-react';
import { projectsAPI } from '../../utils/api';
import { toastEmitter } from '../../utils/toastEmitter';
import BackButton from '../../components/common/BackButton';
import './Timesheets.css';

export default function Timesheets({ projectId, tasks = [] }) {
    const { t, i18n } = useTranslation();
    const isRTL = i18n.language === 'ar';
    const locale = isRTL ? ar : enUS;
    const location = useLocation();
    const isStandalone = location.pathname === '/projects/timesheets';

    const [currentWeekStart, setCurrentWeekStart] = useState(startOfWeek(new Date(), { weekStartsOn: 6 })); // Week starts Saturday
    const [timesheets, setTimesheets] = useState([]);
    const [loading, setLoading] = useState(false);
    const [gridData, setGridData] = useState({});
    const [selectedIds, setSelectedIds] = useState([]);
    const [approving, setApproving] = useState(false);
    const [submitting, setSubmitting] = useState(false);

    useEffect(() => {
        fetchTimesheets();
    }, [projectId, currentWeekStart]);

    const fetchTimesheets = async () => {
        setLoading(true);
        try {
            const res = await projectsAPI.listTimesheets(projectId);
            setTimesheets(res.data || []);
            setSelectedIds([]); // Clear selection on reload
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    const weekDays = eachDayOfInterval({
        start: currentWeekStart,
        end: addDays(currentWeekStart, 6)
    });

    // Group timesheets by Task + Date
    const getEntry = (taskId, date) => {
        const dateStr = format(date, 'yyyy-MM-dd');
        return timesheets.find(ts => ts.task_id === taskId && ts.date === dateStr);
    };

    const getHours = (taskId, date) => {
        const dateStr = format(date, 'yyyy-MM-dd');
        // Check local state first
        if (gridData[taskId] && gridData[taskId][dateStr] !== undefined) {
            return gridData[taskId][dateStr];
        }
        // Then check fetched data
        const entry = getEntry(taskId, date);
        return entry ? entry.hours : '';
    };

    const handleInputChange = (taskId, date, value) => {
        const entry = getEntry(taskId, date);
        if (entry && entry.status === 'approved') return;

        const dateStr = format(date, 'yyyy-MM-dd');
        setGridData(prev => ({
            ...prev,
            [taskId]: {
                ...(prev[taskId] || {}),
                [dateStr]: value
            }
        }));
    };

    const toggleSelect = (id) => {
        setSelectedIds(prev =>
            prev.includes(id) ? prev.filter(i => i !== id) : [...prev, id]
        );
    };

    const handleSave = async () => {
        setSubmitting(true);
        try {
            // Process gridData changes
            const promises = [];
            for (const taskId in gridData) {
                for (const dateStr in gridData[taskId]) {
                    const rawValue = gridData[taskId][dateStr];
                    const hours = rawValue !== '' ? rawValue : null;
                    if (hours === null && rawValue !== '') continue;

                    // Find existing entry
                    const existing = timesheets.find(ts => ts.task_id == taskId && ts.date === dateStr);

                    if (existing) {
                        if (rawValue === '' || rawValue === '0') {
                            // Delete if cleared
                            promises.push(projectsAPI.deleteTimesheet(existing.id));
                        } else if (rawValue !== String(existing.hours)) {
                            // Update
                            promises.push(projectsAPI.updateTimesheet(existing.id, { hours: rawValue }));
                        }
                    } else if (hours && new Decimal(hours).gt(0)) {
                        // Create
                        promises.push(projectsAPI.createTimesheet(projectId, {
                            task_id: parseInt(taskId),
                            date: dateStr,
                            hours: rawValue,
                            description: 'Logged via grid',
                            status: 'draft'
                        }));
                    }
                }
            }

            await Promise.all(promises);
            toastEmitter.emit(t('common.save_success'), 'success');
            setGridData({}); // Clear local changes
            fetchTimesheets(); // Reload
        } catch (err) {
            toastEmitter.emit(t('common.save_error'), 'error');
        } finally {
            setSubmitting(false);
        }
    };

    const handleApprove = async () => {
        if (selectedIds.length === 0) return;
        setApproving(true);
        try {
            await projectsAPI.approveTimesheets(projectId, { timesheet_ids: selectedIds });
            toastEmitter.emit(t('projects.approve_success'), 'success');
            fetchTimesheets();
        } catch (err) {
            console.error(err);
        } finally {
            setApproving(false);
        }
    };

    const changeWeek = (direction) => {
        setCurrentWeekStart(prev => addDays(prev, direction * 7));
    };

    return (
        <div className="workspace fade-in timesheet-container">
            {isStandalone && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
                    <BackButton />
                    <h1 className="workspace-title" style={{ margin: 0 }}>{t('projects.timesheets', 'Timesheets')}</h1>
                </div>
            )}
            {/* Toolbar */}
            <div className="d-flex align-items-center justify-content-between mb-3">
                <div className="d-flex align-items-center gap-3">
                    <div className="btn-group">
                        <button className="btn btn-outline-secondary btn-sm" onClick={() => changeWeek(-1)}>
                            <ChevronRight size={16} />
                        </button>
                        <button className="btn btn-outline-secondary btn-sm" onClick={() => setCurrentWeekStart(startOfWeek(new Date(), { weekStartsOn: 6 }))}>
                            {t('common.today')}
                        </button>
                        <button className="btn btn-outline-secondary btn-sm" onClick={() => changeWeek(1)}>
                            <ChevronLeft size={16} /> {/* RTL logic: Left is Next in styling usually, but let's assume standard icon direction needs fix if RTL */}
                        </button>
                    </div>
                    <h5 className="mb-0">
                        {format(currentWeekStart, 'd MMM', { locale })} - {format(addDays(currentWeekStart, 6), 'd MMM yyyy', { locale })}
                    </h5>
                </div>
                <div className="d-flex gap-2">
                    {selectedIds.length > 0 && (
                        <button className="btn btn-success" onClick={handleApprove} disabled={approving}>
                            <CheckCircle2 size={16} /> {approving ? t('common.loading') : `${t('common.approve')} (${selectedIds.length})`}
                        </button>
                    )}
                    <button className="btn btn-primary" onClick={handleSave} disabled={submitting}>
                        <Save size={16} /> {submitting ? t('common.saving') : t('common.save_changes')}
                    </button>
                </div>
            </div>

            {/* Grid */}
            <div className="table-responsive">
                <table className="data-table timesheet-table">
                    <thead>
                        <tr>
                            <th style={{ width: '25%' }}>{t('projects.task')}</th>
                            {weekDays.map(day => (
                                <th key={day.toISOString()} className="text-center" style={{ width: '10%' }}>
                                    <div className="small text-muted">{format(day, 'EEE', { locale })}</div>
                                    <div>{format(day, 'd')}</div>
                                </th>
                            ))}
                            <th className="text-center" style={{ width: '5%' }}>{t('projects.total')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {tasks.map(task => (
                            <tr key={task.id}>
                                <td className="align-middle">
                                    <div className="fw-medium">{task.task_name}</div>
                                    <small className="text-muted">{task.status}</small>
                                </td>
                                {weekDays.map(day => {
                                    const entry = getEntry(task.id, day);
                                    const isApproved = entry?.status === 'approved';
                                    const isSelected = entry && selectedIds.includes(entry.id);

                                    return (
                                        <td key={day.toISOString()} className={`p-1 position-relative ${isApproved ? 'bg-light-success' : ''}`}>
                                            <input
                                                type="number"
                                                className={`form-input form-input-sm text-center border-0 ${isApproved ? 'bg-transparent text-success fw-bold' : ''}`}
                                                value={getHours(task.id, day)}
                                                onChange={(e) => handleInputChange(task.id, day, e.target.value)}
                                                disabled={isApproved}
                                                min="0" max="24" step="0.5"
                                            />
                                            {entry && !isApproved && (
                                                <div className="selection-overlay" onClick={() => toggleSelect(entry.id)}>
                                                    <input type="checkbox" checked={isSelected} readOnly />
                                                </div>
                                            )}
                                            {isApproved && (
                                                <div className="approved-indicator">
                                                    <CheckCircle2 size={10} />
                                                </div>
                                            )}
                                        </td>
                                    );
                                })}
                                <td className="text-center align-middle fw-bold timesheet-total-cell">
                                    {/* Calculated Total for Row */}
                                    {weekDays.reduce((acc, day) => acc.plus(new Decimal(getHours(task.id, day) || '0')), new Decimal('0')).toString()}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {tasks.length === 0 && (
                <div className="text-center py-4 text-muted">
                    {t('projects.no_tasks_timesheet')}
                </div>
            )}
        </div>
    );
}
