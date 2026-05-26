import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { format, startOfWeek, addDays, eachDayOfInterval } from 'date-fns';
import { arSA, enUS } from 'date-fns/locale';
import { ChevronRight, ChevronLeft, Calendar as CalendarIcon, User } from 'lucide-react';
import { projectsAPI } from '../../utils/api';
import './ResourceManagement.css';
import BackButton from '../../components/common/BackButton';

const ResourceManagement = () => {
    const { t, i18n } = useTranslation();
    const locale = i18n.language === 'ar' ? arSA : enUS;

    // State
    const [currentWeekStart, setCurrentWeekStart] = useState(startOfWeek(new Date(), { weekStartsOn: 6 }));
    const [loading, setLoading] = useState(false);
    const [resources, setResources] = useState([]);

    useEffect(() => {
        fetchAllocation();
    }, [currentWeekStart]);

    const fetchAllocation = async () => {
        setLoading(true);
        try {
            const start = format(currentWeekStart, 'yyyy-MM-dd');
            const end = format(addDays(currentWeekStart, 6), 'yyyy-MM-dd');
            const res = await projectsAPI.getResourceAllocation({ start_date: start, end_date: end });
            setResources(res.data || []);
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    const changeWeek = (direction) => {
        setCurrentWeekStart(prev => addDays(prev, direction * 7));
    };

    const weekDays = eachDayOfInterval({
        start: currentWeekStart,
        end: addDays(currentWeekStart, 6)
    });

    const getDailyLoad = (resource, date) => {
        const dateStr = format(date, 'yyyy-MM-dd');
        return resource.daily_load.find(d => d.date === dateStr) || { hours: '0.00', load_status: 'none' };
    };

    const getCellColor = (status) => {
        if (status === 'light') return 'bg-success-subtle';
        if (status === 'optimal') return 'bg-success text-white';
        if (status === 'heavy') return 'bg-warning text-dark';
        if (status === 'overload') return 'bg-danger text-white';
        return '';
    };

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div>
                    <h1 className="workspace-title">{t('projects.resource_allocation')}</h1>
                    <p className="workspace-subtitle">{t('projects.resource_subtitle')}</p>
                </div>

                {/* Date Navigation */}
                <div className="d-flex align-items-center bg-white p-2 rounded shadow-sm border">
                    <button className="btn btn-icon btn-sm" onClick={() => changeWeek(-1)}>
                        {i18n.dir() === 'rtl' ? <ChevronRight size={20} /> : <ChevronLeft size={20} />}
                    </button>
                    <div className="mx-3 d-flex align-items-center fw-bold text-primary">
                        <CalendarIcon size={18} className="me-2" />
                        {format(currentWeekStart, 'd MMM', { locale })} - {format(addDays(currentWeekStart, 6), 'd MMM yyyy', { locale })}
                    </div>
                    <button className="btn btn-icon btn-sm" onClick={() => changeWeek(1)}>
                        {i18n.dir() === 'rtl' ? <ChevronLeft size={20} /> : <ChevronRight size={20} />}
                    </button>
                    <button
                        className="btn btn-outline-secondary btn-sm ms-2"
                        onClick={() => setCurrentWeekStart(startOfWeek(new Date(), { weekStartsOn: 6 }))}
                    >
                        {t('common.current_week')}
                    </button>
                </div>
            </div>

            {/* Legend */}
            <div className="d-flex gap-3 mb-3 text-small">
                <div className="d-flex align-items-center gap-1"><span className="badge bg-success-subtle text-dark border p-1 rounded-circle" style={{ width: 12, height: 12 }}></span> {t('projects.load_light')}</div>
                <div className="d-flex align-items-center gap-1"><span className="badge bg-success border p-1 rounded-circle" style={{ width: 12, height: 12 }}></span> {t('projects.load_optimal')}</div>
                <div className="d-flex align-items-center gap-1"><span className="badge bg-warning border p-1 rounded-circle" style={{ width: 12, height: 12 }}></span> {t('projects.load_heavy')}</div>
                <div className="d-flex align-items-center gap-1"><span className="badge bg-danger border p-1 rounded-circle" style={{ width: 12, height: 12 }}></span> {t('projects.load_overload')}</div>
            </div>

            {/* Allocation Matrix */}
            <div className="card shadow-sm border-0">
                <div className="card-body p-0">
                    <div className="table-responsive">
                        <table className="table table-hover align-middle mb-0 resource-matrix">
                            <thead className="bg-light">
                                <tr>
                                    <th style={{ width: '250px' }} className="ps-4 py-3">{t('common.employee')}</th>
                                    {weekDays.map(day => (
                                        <th key={day.toISOString()} className="text-center py-3" style={{ minWidth: '100px' }}>
                                            <div className="small text-muted text-uppercase">{format(day, 'EEE', { locale })}</div>
                                            <div className="fw-bold">{format(day, 'd', { locale })}</div>
                                        </th>
                                    ))}
                                    <th className="text-center py-3">{t('common.total')}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {loading ? (
                                    <tr><td colSpan={9} className="text-center py-5 text-muted">{t('common.loading')}</td></tr>
                                ) : resources.length === 0 ? (
                                    <tr><td colSpan={9} className="text-center py-5 text-muted">{t('common.no_data')}</td></tr>
                                ) : (
                                    resources.map(res => (
                                            <tr key={res.id}>
                                                <td className="ps-4 py-3">
                                                    <div className="d-flex align-items-center gap-3">
                                                        <div className="avatar bg-primary-subtle text-primary rounded-circle d-flex align-items-center justify-content-center" style={{ width: 36, height: 36 }}>
                                                            <User size={18} />
                                                        </div>
                                                        <div>
                                                            <div className="fw-bold text-dark">{res.name}</div>
                                                            <div className="small text-muted text-truncate" style={{ maxWidth: '180px' }}>
                                                                {res.projects.join(', ')}
                                                            </div>
                                                        </div>
                                                    </div>
                                                </td>
                                                {weekDays.map(day => {
                                                    const load = getDailyLoad(res, day);
                                                    return (
                                                        <td key={day.toISOString()} className="text-center p-1">
                                                            <div className={`allocation-cell rounded py-2 fw-bold ${getCellColor(load.load_status)}`}>
                                                                {load.load_status !== 'none' ? load.hours : '-'}
                                                            </div>
                                                        </td>
                                                    );
                                                })}
                                                <td className="text-center fw-bold text-primary">
                                                    {res.weekly_total_load}
                                                </td>
                                            </tr>
                                    ))
                                )}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default ResourceManagement;
