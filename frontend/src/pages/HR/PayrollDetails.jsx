import React, { useState, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams, useNavigate } from 'react-router-dom';
import {
    Calculator, CheckCircle, Printer, RefreshCw,
    DollarSign, Users
} from 'lucide-react';
import { hrAPI } from '../../utils/api';
import { getCurrency, hasPermission, isAuthReady } from '../../utils/auth';
import { formatNumber } from '../../utils/format';
import { useBranch } from '../../context/BranchContext';
import { toastEmitter } from '../../utils/toastEmitter';
import '../../components/ModuleStyles.css';
import { formatDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

const PayrollDetails = () => {
    const { t } = useTranslation();
    const { id } = useParams();
    const navigate = useNavigate();
    const currency = getCurrency();
    const companyCurrency = currency;
    const { currentBranch } = useBranch();
    const [period, setPeriod] = useState(null);
    const [entries, setEntries] = useState([]);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [processing, setProcessing] = useState(false);

    // Calculate totals grouped by currency
    const totalsByCurrency = useMemo(() => {
        const groups = {};
        entries.forEach(e => {
            const cur = e.currency || companyCurrency;
            if (!groups[cur]) groups[cur] = { net: 0, netBase: 0, basic: 0, housing: 0, transport: 0, other: 0, deductions: 0 };
            groups[cur].net += (e.net_salary || 0);
            groups[cur].netBase += (e.net_salary_base || e.net_salary || 0);
            groups[cur].basic += (e.basic_salary || 0);
            groups[cur].housing += (e.housing_allowance || 0);
            groups[cur].transport += (e.transport_allowance || 0);
            groups[cur].other += (e.other_allowances || 0);
            groups[cur].deductions += (e.deductions || 0);
        });
        return groups;
    }, [entries, companyCurrency]);

    const totalNetBase = useMemo(() => {
        return entries.reduce((sum, e) => sum + (e.net_salary_base || e.net_salary || 0), 0);
    }, [entries]);

    const hasMultiCurrency = useMemo(() => Object.keys(totalsByCurrency).length > 1, [totalsByCurrency]);

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchData();
        }, 300)
        return () => clearTimeout(timer)
    }, [id, currentBranch]);

    const fetchData = async () => {
        setLoading(true);
        try {
            const params = {};
            if (currentBranch?.id) {
                params.branch_id = currentBranch.id;
            }

            // Always fetch period
            const pRes = await hrAPI.getPayrollPeriod(id);
            setPeriod(pRes.data);

            // Only fetch entries if user can manage or view reports
            if (hasPermission('hr.manage') || hasPermission('hr.reports')) {
                const eRes = await hrAPI.getPayrollEntries(id, params);
                setEntries(eRes.data);
            }
        } catch (err) {
            toastEmitter.emit(t('common.error'), 'error');
        } finally {
            setLoading(false);
            setInitialLoad(false);
        }
    };

    const handleGenerate = async () => {
        if (!window.confirm(t('hr.payroll.confirm_generate', "This will recalculate salaries for all active employees. Are you sure?"))) return;

        setProcessing(true);
        try {
            await hrAPI.generatePayroll(id);
            await fetchData(); // Reload
        } catch (err) {
            toastEmitter.emit(t('common.error', 'Error') + ": " + (err.response?.data?.detail || err.message), 'error');
        } finally {
            setProcessing(false);
        }
    };

    const handlePost = async () => {
        if (!window.confirm(t('hr.payroll.confirm_post', "This will post the payroll and create journal entries. This cannot be undone. Are you sure?"))) return;

        setProcessing(true);
        try {
            await hrAPI.postPayroll(id);
            await fetchData(); // Reload status
        } catch (err) {
            toastEmitter.emit(t('common.error', 'Error') + ": " + (err.response?.data?.detail || err.message), 'error');
        } finally {
            setProcessing(false);
        }
    };

    if (initialLoad && !period) return <PageLoading />;
    if (!period) return <div className="page-center text-error">{t('hr.payroll.period_not_found', 'Payroll period not found')}</div>;

    const isDraft = period.status === 'draft';

    return (
        <div className="workspace fade-in">
            {/* Header */}
            <div className="workspace-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                        <BackButton />
                    <div>
                        <h1 className="workspace-title">{period.name}</h1>
                        <div className="workspace-subtitle">
                            <span>{formatDate(period.start_date)}</span>
                            <span className="mx-2">{t('common.to')}</span>
                            <span>{formatDate(period.end_date)}</span>
                        </div>
                    </div>
                </div>

                <div className="action-buttons gap-2" style={{ display: 'flex', alignItems: 'center', marginTop: '16px' }}>
                    {/* Status Badge */}
                    <span className={`badge border ${isDraft ? 'bg-warning-subtle text-warning border-warning-subtle' : 'bg-success-subtle text-success border-success-subtle'} px-3 py-2 d-flex align-items-center gap-2`}>
                        <span className={`spinner-grow spinner-grow-sm ${isDraft ? 'text-warning' : 'd-none'}`} role="status" aria-hidden="true"></span>
                        {isDraft ? t('common.status.draft', 'Draft') : t('common.status.posted', 'Posted')}
                    </span>

                    {isDraft && (
                        <>
                            <button
                                className="btn btn-primary"
                                onClick={handleGenerate}
                                disabled={processing}
                            >
                                <RefreshCw size={18} className={`me-2 ${processing ? 'spin' : ''}`} />
                                {entries.length > 0 ? t('hr.payroll.recalculate', 'Recalculate') : t('hr.payroll.generate', 'Generate Payroll')}
                            </button>

                            {entries.length > 0 && (
                                <button
                                    className="btn btn-success text-white"
                                    onClick={handlePost}
                                    disabled={processing}
                                >
                                    <CheckCircle size={18} className="me-2" />
                                    {t('hr.payroll.post', 'Post & Finalize')}
                                </button>
                            )}
                        </>
                    )}

                    {!isDraft && (
                        <button className="btn btn-secondary" onClick={() => window.print()}>
                            <Printer size={18} className="me-2" />
                            {t('common.print', 'Print')}
                        </button>
                    )}
                </div>
            </div>

            {/* Metrics Section (Consistent with ModuleStyles) */}
            <div className="metrics-grid mb-4">
                <div className="metric-card">
                    <div className="metric-label">{t('hr.payroll.total_net', 'Total Net Salary')}</div>
                    <div className="metric-value text-primary">
                        {!isAuthReady() ? '...' : !hasPermission('hr.reports') ? '***' : formatNumber(totalNetBase)}
                        {hasPermission('hr.reports') && <small> {companyCurrency}</small>}
                    </div>
                    {hasPermission('hr.reports') && hasMultiCurrency && (
                        <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>
                            {Object.entries(totalsByCurrency).map(([cur, totals]) => (
                                <div key={cur}>{formatNumber(totals.net)} {cur}</div>
                            ))}
                        </div>
                    )}
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('hr.payroll.employees_count', 'Employees')}</div>
                    <div className="metric-value text-dark">
                        {entries.length}
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('common.status_title')}</div>
                    <div className={`metric-value ${isDraft ? 'text-warning' : 'text-success'} fs-4`}>{isDraft ? t('status.draft') : t('status.posted')}</div>
                </div>
            </div>

            {/* Entries Table */}
            <div className="card shadow-sm border-0 section-card">
                <h3 className="section-title">{t('hr.payroll.entries', 'Payroll Entries')}</h3>
                <div className="data-table-container">
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>{t('hr.employees.name', 'Employee')}</th>
                                <th>{t('hr.employees.position', 'Position')}</th>
                                <th>{t('hr.payroll.basic', 'Basic')}</th>
                                <th>{t('hr.payroll.housing', 'Housing')}</th>
                                <th>{t('hr.payroll.transport', 'Transport')}</th>
                                <th>{t('hr.payroll.other', 'Other')}</th>
                                <th className="text-danger">{t('hr.payroll.deductions', 'Deductions')}</th>
                                <th className="fw-bold">{t('hr.payroll.net', 'Net Salary')}</th>
                                <th>{t('common.currency', 'Currency')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {entries.length === 0 ? (
                                <tr>
                                    <td colSpan="9" className="start-guide">
                                        <div style={{ padding: '60px 20px', textAlign: 'center' }}>
                                            <div style={{ fontSize: '48px', marginBottom: '16px' }}>💸</div>
                                            <h3 style={{ fontSize: '18px', marginBottom: '8px' }}>{t('hr.payroll.no_entries', 'No payroll entries yet')}</h3>
                                            <p className="text-muted mb-3">{t('hr.payroll.generate_hint', 'Click "Generate Payroll" to calculate salaries.')}</p>
                                            <button className="btn btn-primary" onClick={handleGenerate} disabled={processing}>
                                                <RefreshCw size={18} className={`me-2 ${processing ? 'spin' : ''}`} />
                                                {t('hr.payroll.generate', 'Generate Payroll')}
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                            ) : (
                                <>
                                    {entries.map(entry => {
                                        const entryCurrency = entry.currency || companyCurrency;
                                        return (
                                        <tr key={entry.id}>
                                            <td className="fw-medium text-dark">{entry.employee_name}</td>
                                            <td className="text-muted small">{entry.position || '-'}</td>
                                            <td className="text-muted">{formatNumber(entry.basic_salary)}</td>
                                            <td className="text-muted">{formatNumber(entry.housing_allowance)}</td>
                                            <td className="text-muted">{formatNumber(entry.transport_allowance)}</td>
                                            <td className="text-muted">{formatNumber(entry.other_allowances)}</td>
                                            <td className="text-danger">{formatNumber(entry.deductions)}</td>
                                            <td className="fw-bold text-primary">{formatNumber(entry.net_salary)}</td>
                                            <td className="text-muted small">{entryCurrency}</td>
                                        </tr>
                                        );
                                    })}
                                    {/* Per-currency subtotals if multi-currency */}
                                    {hasMultiCurrency && Object.entries(totalsByCurrency).map(([cur, totals]) => (
                                        <tr key={`subtotal-${cur}`} style={{ fontWeight: 600, backgroundColor: 'var(--bg-hover)', opacity: 0.85 }}>
                                            <td colSpan="2">{t('common.subtotal', 'Subtotal')} ({cur})</td>
                                            <td>{formatNumber(totals.basic)}</td>
                                            <td>{formatNumber(totals.housing)}</td>
                                            <td>{formatNumber(totals.transport)}</td>
                                            <td>{formatNumber(totals.other)}</td>
                                            <td className="text-danger">{formatNumber(totals.deductions)}</td>
                                            <td className="text-primary">{formatNumber(totals.net)} {cur}</td>
                                            <td></td>
                                        </tr>
                                    ))}
                                    {/* Grand total in base currency */}
                                    <tr style={{ fontWeight: 700, backgroundColor: 'var(--bg-hover)' }}>
                                        <td colSpan="2">{t('common.total', 'Total')} {hasMultiCurrency ? `(${companyCurrency})` : ''}</td>
                                        <td>{formatNumber(entries.reduce((sum, e) => sum + ((e.basic_salary || 0) * (e.exchange_rate || 1)), 0))}</td>
                                        <td>{formatNumber(entries.reduce((sum, e) => sum + ((e.housing_allowance || 0) * (e.exchange_rate || 1)), 0))}</td>
                                        <td>{formatNumber(entries.reduce((sum, e) => sum + ((e.transport_allowance || 0) * (e.exchange_rate || 1)), 0))}</td>
                                        <td>{formatNumber(entries.reduce((sum, e) => sum + ((e.other_allowances || 0) * (e.exchange_rate || 1)), 0))}</td>
                                        <td className="text-danger">{formatNumber(entries.reduce((sum, e) => sum + ((e.deductions || 0) * (e.exchange_rate || 1)), 0))}</td>
                                        <td className="text-primary">{formatNumber(totalNetBase)} {companyCurrency}</td>
                                        <td></td>
                                    </tr>
                                </>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>

            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
        </div>
    );
};

export default PayrollDetails;
