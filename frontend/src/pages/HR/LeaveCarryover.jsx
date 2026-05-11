import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { hrImprovementsAPI, hrAPI } from '../../utils/api';
import { toastEmitter } from '../../utils/toastEmitter';
import { useBranch } from '../../context/BranchContext';
import { Calendar, RotateCcw, CheckCircle, AlertCircle, Clock } from 'lucide-react';
import '../../components/ModuleStyles.css';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

const LeaveCarryover = () => {
    const { t } = useTranslation();
    const { currentBranch } = useBranch();
    const [balances, setBalances] = useState([]);
    const [employees, setEmployees] = useState([]);
    const [loading, setLoading] = useState(false);
    const [initialLoad, setInitialLoad] = useState(true);
    const [employeeId, setEmployeeId] = useState('');
    const [showCarryover, setShowCarryover] = useState(false);
    const [carryoverLoading, setCarryoverLoading] = useState(false);
    const [carryForm, setCarryForm] = useState({ employee_id: '', year: new Date().getFullYear() - 1 });
    const [selectedEmployee, setSelectedEmployee] = useState(null);

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchEmployees();
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch]);

    const fetchEmployees = async () => {
        try {
            const params = { limit: 500 };
            if (currentBranch?.id) params.branch_id = currentBranch.id;
            const res = await hrAPI.listEmployees(params);
            setEmployees(res.data?.items || res.data || []);
        } catch (err) { toastEmitter.emit(t('common.error'), 'error'); } finally { setInitialLoad(false); }
    };

    const fetchBalance = async (empId) => {
        if (!empId) return;
        try {
            setLoading(true);
            const res = await hrImprovementsAPI.getLeaveBalance(empId);
            setBalances(res.data?.balances || []);
            const emp = employees.find(e => String(e.id) === String(empId));
            setSelectedEmployee(emp || null);
        } catch (err) {
            toastEmitter.emit(t('hr.error_fetching_balances'), 'error');
            setBalances([]);
        } finally { setLoading(false); }
    };

    const handleCarryover = async (e) => {
        e.preventDefault();
        try {
            setCarryoverLoading(true);
            await hrImprovementsAPI.calculateLeaveCarryover({
                employee_id: parseInt(carryForm.employee_id),
                year: parseInt(carryForm.year)
            });
            toastEmitter.emit(t('hr.leave_carried_success'), 'success');
            setShowCarryover(false);
            if (employeeId) fetchBalance(employeeId);
        } catch (err) {
            toastEmitter.emit(err.response?.data?.detail || t('common.error'), 'error');
        } finally { setCarryoverLoading(false); }
    };

    const handleEmployeeChange = (empId) => {
        setEmployeeId(empId);
        if (empId) fetchBalance(empId);
        else { setBalances([]); setSelectedEmployee(null); }
    };

    const totalEntitled = balances.reduce((s, b) => s + (b.entitled_days || 0), 0);
    const totalUsed = balances.reduce((s, b) => s + (b.used_days || 0), 0);
    const totalRemaining = balances.reduce((s, b) => s + (b.remaining_days || 0), 0);
    const totalCarried = balances.reduce((s, b) => s + (b.carried_days || 0), 0);

    const leaveTypeLabel = (type) => {
        const map = {
            annual: t('hr.annual_leave'),
            sick: t('hr.leave_type_sick'),
            unpaid: t('hr.leave_type_unpaid'),
            emergency: t('hr.leave_type_emergency'),
            maternity: t('hr.leave_type_maternity'),
        };
        return map[type] || type;
    };

    const getBalanceColor = (remaining, entitled) => {
        if (!entitled || entitled <= 0) return '#6b7280';
        const pct = remaining / entitled;
        if (pct > 0.5) return '#16a34a';
        if (pct > 0.2) return '#d97706';
        return '#dc2626';
    };

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1 className="workspace-title"><span className="p-2 rounded-lg bg-blue-50 text-blue-600"><Calendar size={24} /></span> {t('hr.leave_balance_title')}</h1>
                        <p className="workspace-subtitle">{t('hr.leave_balance_subtitle')}</p>
                    </div>
                    <button className="btn btn-primary" onClick={() => setShowCarryover(true)}><RotateCcw size={18} /> {t('hr.carry_over_btn')}</button>
                </div>
            </div>

            {/* Employee Selector */}
            <div className="card section-card" style={{ marginBottom: 24 }}>
                <div className="d-flex gap-3 align-items-end">
                    <div className="form-group" style={{ flex: 1, marginBottom: 0 }}>
                        <label className="form-label">{t('hr.col_employee')}</label>
                        <select className="form-input" value={employeeId} onChange={e => handleEmployeeChange(e.target.value)}>
                            <option value="">{t('hr.select_employee')}</option>
                            {employees.map(emp => (
                                <option key={emp.id} value={emp.id}>{emp.first_name} {emp.last_name} ({emp.employee_code || emp.id})</option>
                            ))}
                        </select>
                    </div>
                </div>
            </div>

            {/* Summary Metrics */}
            {balances.length > 0 && (
                <>
                    <div className="metrics-grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', marginBottom: 24 }}>
                        <div className="metric-card">
                            <div className="metric-label">{t('hr.leave_total_entitled')}</div>
                            <div className="metric-value" style={{ color: '#2563eb' }}>{totalEntitled}</div>
                        </div>
                        <div className="metric-card">
                            <div className="metric-label">{t('hr.leave_total_used')}</div>
                            <div className="metric-value" style={{ color: '#dc2626' }}>{totalUsed}</div>
                        </div>
                        <div className="metric-card">
                            <div className="metric-label">{t('hr.leave_total_remaining')}</div>
                            <div className="metric-value" style={{ color: '#16a34a' }}>{totalRemaining}</div>
                        </div>
                        {totalCarried > 0 && (
                            <div className="metric-card">
                                <div className="metric-label">{t('hr.leave_total_carried')}</div>
                                <div className="metric-value" style={{ color: '#7c3aed' }}>{totalCarried}</div>
                            </div>
                        )}
                    </div>

                    {/* Balance Cards */}
                    <div className="metrics-grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))' }}>
                        {balances.map((b, i) => {
                            const remaining = b.remaining_days ?? 0;
                            const entitled = b.entitled_days || 0;
                            const used = b.used_days || 0;
                            const carried = b.carried_days || 0;
                            const pct = entitled > 0 ? Math.round((remaining / entitled) * 100) : 0;
                            const color = getBalanceColor(remaining, entitled);

                            return (
                                <div key={i} className="card section-card" style={{ padding: 20 }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                                        <span style={{ fontWeight: 600, fontSize: 14 }}>{leaveTypeLabel(b.leave_type)}</span>
                                        {remaining > 5 ? <CheckCircle size={18} style={{ color: '#16a34a' }} /> :
                                         remaining > 0 ? <Clock size={18} style={{ color: '#d97706' }} /> :
                                         <AlertCircle size={18} style={{ color: '#dc2626' }} />}
                                    </div>

                                    {/* Progress Bar */}
                                    <div style={{ background: '#f1f5f9', borderRadius: 20, height: 10, marginBottom: 12, overflow: 'hidden' }}>
                                        <div style={{ width: `${Math.min(pct, 100)}%`, background: color, height: '100%', borderRadius: 20, transition: 'width 0.5s ease' }} />
                                    </div>

                                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 4 }}>
                                        <span style={{ color: '#6b7280' }}>{t('hr.days_remaining')}</span>
                                        <span style={{ fontWeight: 700, color, fontSize: 18 }}>{remaining}</span>
                                    </div>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: '#9ca3af' }}>
                                        <span>{t('hr.leave_entitled_label')}: {entitled}</span>
                                        <span>{t('hr.leave_used_label')}: {used}</span>
                                    </div>
                                    {carried > 0 && (
                                        <div style={{ fontSize: 12, color: '#7c3aed', marginTop: 6, display: 'flex', alignItems: 'center', gap: 4 }}>
                                            <RotateCcw size={12} /> {t('hr.carried_over', { count: carried })}
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                </>
            )}

            {!loading && balances.length === 0 && employeeId && (
                <div className="card section-card text-center p-6 text-muted">{t('hr.no_leave_balances')}</div>
            )}

            {initialLoad && !employees.length && (
                <div className="card section-card" style={{ textAlign: 'center', padding: 40, color: 'var(--text-muted)' }}>
                    <PageLoading />
                    {t('common.loading')}
                </div>
            )}

            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}

            {/* Carryover Modal */}
            {showCarryover && (
                <div className="modal-overlay" onClick={() => setShowCarryover(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 460 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
                            <h3 className="modal-title" style={{ margin: 0 }}><RotateCcw size={20} style={{ display: 'inline', verticalAlign: 'middle' }} /> {t('hr.carry_over_btn')}</h3>
                            <button type="button" onClick={() => setShowCarryover(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 20, color: 'var(--text-muted)' }}>✕</button>
                        </div>

                        <div style={{ background: '#eff6ff', padding: 12, borderRadius: 8, marginBottom: 16, fontSize: 13, color: '#1e40af', border: '1px solid #bfdbfe' }}>
                            ℹ️ {t('hr.carry_over_info')}
                        </div>

                        <form onSubmit={handleCarryover} className="space-y-4">
                            <div className="form-group">
                                <label className="form-label">{t('hr.col_employee')}</label>
                                <select className="form-input" required value={carryForm.employee_id} onChange={e => setCarryForm({ ...carryForm, employee_id: e.target.value })}>
                                    <option value="">{t('hr.select_employee')}</option>
                                    {employees.map(emp => (
                                        <option key={emp.id} value={emp.id}>{emp.first_name} {emp.last_name} ({emp.employee_code || emp.id})</option>
                                    ))}
                                </select>
                            </div>
                            <div className="form-group">
                                <label className="form-label">{t('hr.from_year')}</label>
                                <input type="number" className="form-input" required value={carryForm.year}
                                    onChange={e => setCarryForm({ ...carryForm, year: e.target.value })}
                                    min="2020" max={new Date().getFullYear()} />
                                <small style={{ color: '#6b7280', fontSize: 12 }}>{t('hr.carry_over_year_hint')}</small>
                            </div>
                            <div className="d-flex gap-3 pt-3">
                                <button type="submit" className="btn btn-primary flex-1" disabled={carryoverLoading}>
                                    <RotateCcw size={16} /> {carryoverLoading ? '...' : t('hr.carry_over_submit')}
                                </button>
                                <button type="button" className="btn btn-secondary" onClick={() => setShowCarryover(false)}>{t('hr.cancel')}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
};

export default LeaveCarryover;
