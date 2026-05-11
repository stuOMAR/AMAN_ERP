import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { hasPermission } from '../../utils/auth';
import { hrAPI, hrAdvancedAPI, attendanceAPI } from '../../utils/api';
import { formatNumber } from '../../utils/format';
import { toastEmitter } from '../../utils/toastEmitter';
import {
    Users,
    DollarSign,
    FileText,
    Activity,
} from 'lucide-react';
import '../../index.css';
import '../../components/ModuleStyles.css';
import { getIndustryFeature } from '../../hooks/useIndustryType';
import { Spinner } from '../../components/common/LoadingStates'

const HRHome = () => {
    const { t, i18n } = useTranslation();
    const navigate = useNavigate();
    const [stats, setStats] = useState({ employees: 0, present: 0, payroll: 0, leaves: 0 });

    // End of Service Calculator
    const [showEOSModal, setShowEOSModal] = useState(false);
    const [eosData, setEosData] = useState({ employee_id: '', resignation_type: 'resignation' });
    const [eosResult, setEosResult] = useState(null);
    const [eosLoading, setEosLoading] = useState(false);
    const [employees, setEmployees] = useState([]);

    // GOSI Export
    const [exportingGOSI, setExportingGOSI] = useState(false);

    useEffect(() => {
        const fetchStats = async () => {
            try {
                const [empRes, attRes] = await Promise.all([
                    hrAPI.listEmployees({ limit: 1 }),
                    attendanceAPI.getHistory({ limit: 1 })
                ]);
                setStats(prev => ({
                    ...prev,
                    employees: empRes.data?.total || empRes.data?.length || 0,
                    present: attRes.data?.today_count || attRes.data?.length || 0
                }));
            } catch (err) {
                toastEmitter.emit(t('common.error'), 'error');
            }
        };
        if (hasPermission('hr.view')) fetchStats();
    }, []);

    const openEOSCalculator = async () => {
        try {
            const res = await hrAPI.listEmployees({ limit: 500 });
            setEmployees(res.data?.items || res.data || []);
        } catch (err) { toastEmitter.emit(t('common.error'), 'error'); }
        setEosResult(null);
        setShowEOSModal(true);
    };

    const handleCalculateEOS = async () => {
        if (!eosData.employee_id) return;
        setEosLoading(true);
        try {
            const res = await hrAPI.calculateEndOfService(eosData);
            setEosResult(res.data);
        } catch (error) {
            toastEmitter.emit(t('common.error'), 'error');
        } finally {
            setEosLoading(false);
        }
    };

    const handleExportGOSI = async () => {
        setExportingGOSI(true);
        try {
            const res = await hrAdvancedAPI.exportGOSI({});
            const url = window.URL.createObjectURL(new Blob([res.data]));
            const link = document.createElement('a');
            link.href = url;
            link.setAttribute('download', `GOSI_Export_${new Date().toISOString().split('T')[0]}.xlsx`);
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.URL.revokeObjectURL(url);
            toastEmitter.emit(t('hr.gosi_file_exported_successfully'), 'success');
        } catch (error) {
            toastEmitter.emit(t('hr.export_failed'), 'error');
        } finally {
            setExportingGOSI(false);
        }
    };

    // Dashboard metrics
    const metrics = [
        { title: t('hr.home.total_employees'), value: String(stats.employees), icon: Users, color: "#2563eb", bg: "#dbeafe" },
        { title: t('hr.home.present_today'), value: String(stats.present), icon: Activity, color: "#16a34a", bg: "#dcfce7" },
        { title: t('hr.home.salaries_due'), value: String(stats.payroll), icon: DollarSign, color: "#d97706", bg: "#fef3c7" },
        { title: t('hr.home.leaves'), value: String(stats.leaves), icon: FileText, color: "#7c3aed", bg: "#ede9fe" },
    ];

    return (
        <div className="workspace fade-in">
            {/* Header */}
            <div className="workspace-header">
                <div className="header-title">
                    <h1 className="workspace-title">{t('hr.home.title')}</h1>
                    <p className="workspace-subtitle">{t('hr.home.subtitle')}</p>
                </div>
            </div>

            {/* Metrics Grid */}
            <div className="metrics-grid">
                {metrics.map((metric, index) => (
                    <div key={index} className="metric-card">
                        <div className="metric-label">{metric.title}</div>
                        <div className="metric-value" style={{ color: metric.color }}>
                            {metric.value}
                        </div>
                    </div>
                ))}
            </div>

            {/* Modules Grid - Consistent with Sales/Stock */}
            <div className="modules-grid">

                {/* Employee Management Section */}
                <div className="card section-card">
                    <h3 className="section-title">{t('hr.home.employee_mgmt')}</h3>
                    <div className="links-list">
                        <div className="link-item" onClick={() => navigate('/hr/employees')}>
                            <span className="link-icon">👥</span>
                            {t('hr.home.employee_list')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/hr/employees', { state: { openModal: true } })}>
                            <span className="link-icon">➕</span>
                            {t('hr.home.new_employee')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/hr/positions')}>
                            <span className="link-icon">👔</span>
                            {t('hr.home.positions')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/hr/departments')}>
                            <span className="link-icon">🏢</span>
                            {t('hr.home.departments')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                    </div>
                </div>

                {/* Payroll & Attendance Section */}
                <div className="card section-card">
                    <h3 className="section-title">{t('hr.home.payroll_attendance')}</h3>
                    <div className="links-list">
                        <div className="link-item" onClick={() => navigate('/hr/payroll')}>
                            <span className="link-icon">💰</span>
                            {t('hr.home.payroll_sheet')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/hr/loans')}>
                            <span className="link-icon">💸</span>
                            {t('hr.home.loans')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/hr/attendance')}>
                            <span className="link-icon">⏰</span>
                            {t('hr.home.attendance_log')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/hr/leaves')}>
                            <span className="link-icon">🏖️</span>
                            {t('hr.leaves.title')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                    </div>
                </div>

                {/* Reports Section */}
                {/* Reports Section */}
                {hasPermission('hr.reports') && (
                    <div className="card section-card">
                        <h3 className="section-title">{t('hr.home.reports')}</h3>
                        <div className="links-list">
                            <div className="link-item" onClick={() => navigate('/hr/reports')}>
                                <span className="link-icon">📊</span>
                                {t('reports_center.hr_reports.payroll', 'Payroll Analytics')}
                                <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                            </div>
                            <div className="link-item" onClick={() => navigate('/hr/reports', { state: { tab: 'leaves' } })}>
                                <span className="link-icon">📉</span>
                                {t('reports_center.hr_reports.leaves', 'Leave Usage')}
                                <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                            </div>
                        </div>
                    </div>
                )}

                {/* Advanced Payroll Section */}
                <div className="card section-card">
                    <h3 className="section-title">{t('hr.advanced_payroll')}</h3>
                    <div className="links-list">
                        <div className="link-item" onClick={() => navigate('/hr/salary-structures')}>
                            <span className="link-icon">🏗️</span>
                            {t('hr.salary_structures.title')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/hr/overtime')}>
                            <span className="link-icon">⏱️</span>
                            {t('hr.overtime_requests')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/hr/gosi')}>
                            <span className="link-icon">🛡️</span>
                            {t('hr.gosi_social_insurance')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={openEOSCalculator}>
                            <span className="link-icon">🧮</span>
                            {t('hr.end_of_service_calculator')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={handleExportGOSI}>
                            <span className="link-icon">{exportingGOSI ? '⏳' : '📥'}</span>
                            {t('hr.export_gosi_file')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                    </div>
                </div>

                {/* HR Management Section */}
                <div className="card section-card">
                    <h3 className="section-title">{t('hr.hr_management')}</h3>
                    <div className="links-list">
                        <div className="link-item" onClick={() => navigate('/hr/documents')}>
                            <span className="link-icon">📄</span>
                            {t('hr.employee_documents')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        {hasPermission('hr.performance_view') && (
                            <div className="link-item" onClick={() => navigate('/hr/performance')}>
                                <span className="link-icon">⭐</span>
                                {t('hr.performance_reviews')}
                                <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                            </div>
                        )}
                        <div className="link-item" onClick={() => navigate('/hr/training')}>
                            <span className="link-icon">🎓</span>
                            {t('hr.training_programs')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/hr/violations')}>
                            <span className="link-icon">⚠️</span>
                            {t('hr.violations_penalties')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        {getIndustryFeature('hr.custody') && (
                            <div className="link-item" onClick={() => navigate('/hr/custody')}>
                                <span className="link-icon">📦</span>
                                {t('hr.custody_management')}
                                <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                            </div>
                        )}
                        <div className="link-item" onClick={() => navigate('/hr/payslips')}>
                            <span className="link-icon">🧾</span>
                            {t('hr.payslips')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/hr/leave-carryover')}>
                            <span className="link-icon">🔄</span>
                            {t('hr.leave_carryover')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        <div className="link-item" onClick={() => navigate('/hr/recruitment')}>
                            <span className="link-icon">💼</span>
                            {t('hr.recruitment_title')}
                            <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                        </div>
                        {hasPermission('hr.self_service') && (
                            <div className="link-item" onClick={() => navigate('/hr/self-service')}>
                                <span className="link-icon">🧑‍💼</span>
                                {t('nav.self_service')}
                                <span className="link-arrow">{i18n.language === 'ar' ? '←' : '→'}</span>
                            </div>
                        )}
                    </div>
                </div>

            </div>

            {/* ========== End of Service Calculator Modal ========== */}
            {showEOSModal && (
                <div className="modal-overlay" style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.45)', zIndex: 1050, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => setShowEOSModal(false)}>
                    <div className="card" style={{ minWidth: 450, maxWidth: 550 }} onClick={e => e.stopPropagation()}>
                        <h3 className="section-title mb-4" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            🧮 {t('hr.eos.calculator_title')}
                        </h3>
                        <div className="mb-3">
                            <label className="form-label">{t('hr.employee')}</label>
                            <select className="form-input" value={eosData.employee_id}
                                onChange={e => setEosData(p => ({ ...p, employee_id: e.target.value }))}>
                                <option value="">{t('hr.eos.select_employee')}</option>
                                {employees.map(emp => (
                                    <option key={emp.id} value={emp.id}>{emp.full_name || emp.name}</option>
                                ))}
                            </select>
                        </div>
                        <div className="mb-4">
                            <label className="form-label">{t('hr.termination_type')}</label>
                            <select className="form-input" value={eosData.resignation_type}
                                onChange={e => setEosData(p => ({ ...p, resignation_type: e.target.value }))}>
                                <option value="resignation">{t('hr.eos.resignation')}</option>
                                <option value="termination">{t('hr.eos.termination')}</option>
                                <option value="end_of_contract">{t('hr.eos.end_of_contract')}</option>
                            </select>
                        </div>
                        <button className="btn btn-primary btn-block mb-3" onClick={handleCalculateEOS} disabled={eosLoading || !eosData.employee_id}>
                            {eosLoading ? <Spinner size="sm"/> : t('hr.eos.calculate')}
                        </button>

                        {eosResult && (
                            <div style={{ background: 'var(--bg-hover, #f9fafb)', borderRadius: 12, padding: 20, marginTop: 8 }}>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, fontSize: 14 }}>
                                    <div><span style={{ color: 'var(--text-secondary)' }}>{t('hr.service_years')}</span></div>
                                    <div style={{ fontWeight: 700 }}>{eosResult.service_years || eosResult.years || '-'}</div>
                                    <div><span style={{ color: 'var(--text-secondary)' }}>{t('hr.base_salary')}</span></div>
                                    <div style={{ fontWeight: 700 }}>{formatNumber(eosResult.base_salary || eosResult.salary || 0)}</div>
                                    <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: 8 }}><span style={{ fontWeight: 700, color: 'var(--primary)' }}>{t('hr.eos_amount')}</span></div>
                                    <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: 8, fontWeight: 700, fontSize: 18, color: 'var(--primary)' }}>{formatNumber(eosResult.total_amount || eosResult.amount || 0)}</div>
                                </div>
                            </div>
                        )}

                        <div className="d-flex gap-2 justify-content-end mt-4">
                            <button className="btn btn-ghost" onClick={() => setShowEOSModal(false)}>{t('common.close', 'Close')}</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default HRHome;
