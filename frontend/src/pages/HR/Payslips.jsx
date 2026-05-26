import React, { useState, useEffect, useRef } from 'react';
import Decimal from 'decimal.js';
import { useTranslation } from 'react-i18next';
import DOMPurify from 'dompurify';
import { hrImprovementsAPI, hrAPI } from '../../utils/api';
import { toastEmitter } from '../../utils/toastEmitter';
import { useBranch } from '../../context/BranchContext';
import { getCurrency } from '../../utils/auth';
import { formatNumber } from '../../utils/format';
import { FileText, Calculator, Eye, Printer, X } from 'lucide-react';
import '../../components/ModuleStyles.css';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

const moneySum = (rows, selector) => rows.reduce(
    (sum, row) => sum.plus(new Decimal(selector(row) || '0')),
    new Decimal('0')
).toDecimalPlaces(2).toString();

const isPositiveMoney = (value) => new Decimal(value || '0').gt(0);

const Payslips = () => {
    const { t, i18n } = useTranslation();
    const { currentBranch } = useBranch();
    const currency = getCurrency();
    const isRTL = i18n.language === 'ar';
    const [payslips, setPayslips] = useState([]);
    const [employees, setEmployees] = useState([]);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [showGenerate, setShowGenerate] = useState(false);
    const [showDetail, setShowDetail] = useState(false);
    const [selectedPayslip, setSelectedPayslip] = useState(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [genForm, setGenForm] = useState({ employee_id: '', month: new Date().getMonth() + 1, year: new Date().getFullYear() });
    const [filterEmployee, setFilterEmployee] = useState('');
    const [filterMonth, setFilterMonth] = useState('');
    const [filterYear, setFilterYear] = useState('');
    const printRef = useRef(null);

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchPayslips();
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
        } catch (err) { toastEmitter.emit(t('common.error'), 'error'); }
    };

    const fetchPayslips = async () => {
        try {
            setLoading(true);
            const params = {};
            if (currentBranch?.id) params.branch_id = currentBranch.id;
            const res = await hrImprovementsAPI.listPayslips(params);
            setPayslips(res.data || []);
        } catch (err) { toastEmitter.emit(t('common.error'), 'error'); } finally { setLoading(false); setInitialLoad(false); }
    };

    const handleGenerate = async (e) => {
        e.preventDefault();
        try {
            const payload = {
                employee_id: parseInt(genForm.employee_id),
                month: parseInt(genForm.month),
                year: parseInt(genForm.year),
            };
            const preview = await hrImprovementsAPI.previewPayslip(payload);
            await hrImprovementsAPI.generatePayslip({
                ...payload,
                submitted_grand_total: String(preview.data?.net_salary || '0'),
            });
            toastEmitter.emit(t('hr.payslip_generated'), 'success');
            setShowGenerate(false); fetchPayslips();
        } catch (err) { toastEmitter.emit(err.response?.data?.detail || t('common.error'), 'error'); }
    };

    const viewDetail = async (payslipId) => {
        try {
            setDetailLoading(true);
            setShowDetail(true);
            const res = await hrImprovementsAPI.getPayslip(payslipId);
            setSelectedPayslip(res.data || res);
        } catch (err) {
            toastEmitter.emit(t('common.error'), 'error');
            setShowDetail(false);
        } finally { setDetailLoading(false); }
    };

    const handlePrint = () => {
        if (!printRef.current) return;
        const printWindow = window.open('', '_blank');
        if (!printWindow) return;

        // SEC / TASK-029: build the print document using DOM APIs instead of
        // document.write with template-literal interpolation. Translated title
        // and direction go into the DOM via textContent / setAttribute.
        const doc = printWindow.document;
        doc.open();
        doc.write('<!DOCTYPE html><html><head><meta charset="utf-8"></head><body></body></html>');
        doc.close();
        doc.documentElement.setAttribute('dir', isRTL ? 'rtl' : 'ltr');
        doc.title = String(t('hr.payslip_print_title') || '');

        const style = doc.createElement('style');
        style.textContent =
            '* { margin:0; padding:0; box-sizing:border-box; } ' +
            "body { font-family: 'Segoe UI', Tahoma, sans-serif; padding: 30px; direction: " +
            (isRTL ? 'rtl' : 'ltr') + '; color: #1a1a2e; } ' +
            '.payslip-container { max-width: 700px; margin: auto; border: 2px solid #e0e0e0; border-radius: 12px; padding: 30px; } ' +
            '.payslip-header { text-align: center; border-bottom: 2px solid #2563eb; padding-bottom: 16px; margin-bottom: 20px; } ' +
            '.payslip-header h2 { color: #2563eb; font-size: 22px; margin-bottom: 4px; } ' +
            '.payslip-header p { font-size: 13px; color: #6b7280; } ' +
            '.payslip-info { display: flex; justify-content: space-between; margin-bottom: 20px; padding: 12px; background: #f8fafc; border-radius: 8px; } ' +
            '.payslip-info div { font-size: 13px; } ' +
            '.payslip-info strong { display: block; margin-bottom: 2px; color: #374151; } ' +
            'table { width: 100%; border-collapse: collapse; margin-bottom: 16px; } ' +
            'th { background: #f1f5f9; padding: 10px 12px; text-align: ' + (isRTL ? 'right' : 'left') + '; font-size: 13px; border-bottom: 2px solid #e2e8f0; } ' +
            'td { padding: 8px 12px; border-bottom: 1px solid #f1f5f9; font-size: 13px; } ' +
            '.section-label { font-weight: 600; color: #1e40af; font-size: 14px; margin: 16px 0 8px; padding-bottom: 4px; border-bottom: 1px solid #e2e8f0; } ' +
            '.total-row { background: #eff6ff; font-weight: 700; font-size: 15px; } ' +
            '.total-row td { border-top: 2px solid #2563eb; padding: 12px; } ' +
            '.text-success { color: #16a34a; } ' +
            '.text-danger { color: #dc2626; } ' +
            '.payslip-footer { margin-top: 30px; display: flex; justify-content: space-between; font-size: 12px; color: #9ca3af; border-top: 1px dashed #d1d5db; padding-top: 12px; } ' +
            '@media print { body { padding: 10px; } .payslip-container { border: none; } }';
        doc.head.appendChild(style);

        // SEC-C4a: Sanitize via DOMPurify before injecting into the print window.
        const wrapper = doc.createElement('div');
        wrapper.innerHTML = DOMPurify.sanitize(printRef.current.innerHTML, { USE_PROFILES: { html: true } });
        doc.body.appendChild(wrapper);

        setTimeout(() => { printWindow.print(); }, 300);
    };

    const statusBadge = (status) => {
        const cls = status === 'paid' ? 'bg-green-100 text-green-700' : status === 'approved' ? 'bg-blue-100 text-blue-700' : 'bg-yellow-100 text-yellow-700';
        const label = status === 'paid' ? t('hr.payslip_status_paid') : status === 'approved' ? t('hr.payslip_status_approved') : t('hr.payslip_status_draft');
        return <span className={`badge ${cls}`}>{label}</span>;
    };

    const filteredPayslips = payslips.filter(p => {
        if (filterEmployee && String(p.employee_id) !== String(filterEmployee)) return false;
        if (filterMonth && String(p.month) !== String(filterMonth)) return false;
        if (filterYear && String(p.year) !== String(filterYear)) return false;
        return true;
    });

    const totalNet = moneySum(filteredPayslips, p => p.net_pay || p.net_salary);
    const totalBasic = moneySum(filteredPayslips, p => p.basic_salary);

    const monthNames = [
        t('months.jan'), t('months.feb'), t('months.mar'), t('months.apr'),
        t('months.may'), t('months.jun'), t('months.jul'), t('months.aug'),
        t('months.sep'), t('months.oct'), t('months.nov'), t('months.dec'),
    ];

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1 className="workspace-title"><span className="p-2 rounded-lg bg-emerald-50 text-emerald-600"><FileText size={24} /></span> {t('hr.payslips_title')}</h1>
                        <p className="workspace-subtitle">{t('hr.payslips_subtitle')}</p>
                    </div>
                    <button className="btn btn-primary" onClick={() => setShowGenerate(true)}><Calculator size={18} /> {t('hr.generate_payslip')}</button>
                </div>
            </div>

            {/* Filter Bar */}
            <div className="card section-card" style={{ marginBottom: 24 }}>
                <div className="d-flex gap-3 align-items-end" style={{ flexWrap: 'wrap' }}>
                    <div className="form-group" style={{ flex: 2, minWidth: 180, marginBottom: 0 }}>
                        <label className="form-label">{t('hr.col_employee')}</label>
                        <select className="form-input" value={filterEmployee} onChange={e => setFilterEmployee(e.target.value)}>
                            <option value="">{t('hr.filter_all')}</option>
                            {employees.map(emp => (
                                <option key={emp.id} value={emp.id}>{emp.first_name} {emp.last_name}</option>
                            ))}
                        </select>
                    </div>
                    <div className="form-group" style={{ flex: 1, minWidth: 130, marginBottom: 0 }}>
                        <label className="form-label">{t('hr.col_month')}</label>
                        <select className="form-input" value={filterMonth} onChange={e => setFilterMonth(e.target.value)}>
                            <option value="">{t('hr.filter_all')}</option>
                            {monthNames.map((name, i) => <option key={i + 1} value={i + 1}>{name}</option>)}
                        </select>
                    </div>
                    <div className="form-group" style={{ flex: 1, minWidth: 110, marginBottom: 0 }}>
                        <label className="form-label">{t('hr.year')}</label>
                        <select className="form-input" value={filterYear} onChange={e => setFilterYear(e.target.value)}>
                            <option value="">{t('hr.filter_all')}</option>
                            {[...new Set(payslips.map(p => p.year))].sort((a,b) => b-a).map(y => <option key={y} value={y}>{y}</option>)}
                        </select>
                    </div>
                    {(filterEmployee || filterMonth || filterYear) && (
                        <button className="btn btn-secondary" style={{ marginBottom: 0 }} onClick={() => { setFilterEmployee(''); setFilterMonth(''); setFilterYear(''); }}>
                            {t('common.reset') || 'إعادة تعيين'}
                        </button>
                    )}
                </div>
            </div>

            {/* Summary Cards */}
            <div className="metrics-grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', marginBottom: 24 }}>
                <div className="metric-card">
                    <div className="metric-label">{t('hr.payslip_total_count')}</div>
                    <div className="metric-value" style={{ color: '#2563eb' }}>{filteredPayslips.length}</div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('hr.payslip_total_basic')}</div>
                    <div className="metric-value" style={{ color: '#7c3aed' }}>{formatNumber(totalBasic)} <small style={{ fontSize: 12 }}>{currency}</small></div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('hr.payslip_total_net')}</div>
                    <div className="metric-value" style={{ color: '#16a34a' }}>{formatNumber(totalNet)} <small style={{ fontSize: 12 }}>{currency}</small></div>
                </div>
            </div>

            {/* Payslips Table */}
            <div className="card section-card">
                {initialLoad && !payslips.length ? (
                    <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-muted)' }}>
                        <PageLoading />
                        {t('common.loading')}
                    </div>
                ) : (
                    <div className="data-table-container">
                        <table className="data-table">
                            <thead><tr>
                                <th>{t('hr.col_employee')}</th>
                                <th>{t('hr.col_month')}</th>
                                <th>{t('hr.col_basic_salary')}</th>
                                <th>{t('hr.col_allowances')}</th>
                                <th>{t('hr.col_deductions')}</th>
                                <th>{t('hr.col_net_pay')}</th>
                                <th>{t('hr.col_status')}</th>
                                <th>{t('hr.col_actions')}</th>
                            </tr></thead>
                            <tbody>
                                {filteredPayslips.map(p => (
                                    <tr key={p.id}>
                                        <td className="font-medium">{p.employee_name || `#${p.employee_id}`}</td>
                                        <td>{monthNames[(p.month || 1) - 1]} {p.year}</td>
                                        <td>{formatNumber(p.basic_salary)} {currency}</td>
                                        <td className="text-success">+{formatNumber(p.total_allowances || 0)} {currency}</td>
                                        <td className="text-danger">-{formatNumber(p.total_deductions || 0)} {currency}</td>
                                        <td className="font-bold">{formatNumber(p.net_pay || p.net_salary)} {currency}</td>
                                        <td>{statusBadge(p.status || 'draft')}</td>
                                        <td>
                                            <div className="d-flex gap-1">
                                                <button className="btn btn-sm btn-secondary" title={t('hr.view_payslip')} onClick={() => viewDetail(p.id)}>
                                                    <Eye size={14} />
                                                </button>
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                                {filteredPayslips.length === 0 && <tr><td colSpan="8" className="text-center text-muted p-4">{payslips.length === 0 ? t('hr.no_payslips') : t('common.no_data')}</td></tr>}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>

            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}

            {/* Generate Payslip Modal */}
            {showGenerate && (
                <div className="modal-overlay" onClick={() => setShowGenerate(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 460 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
                            <h3 className="modal-title" style={{ margin: 0 }}>{t('hr.generate_modal_title')}</h3>
                            <button type="button" onClick={() => setShowGenerate(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 20, color: 'var(--text-muted)' }}>✕</button>
                        </div>
                        <form onSubmit={handleGenerate} className="space-y-4">
                            <div className="form-group">
                                <label className="form-label">{t('hr.col_employee')}</label>
                                <select className="form-input" required value={genForm.employee_id} onChange={e => setGenForm({ ...genForm, employee_id: e.target.value })}>
                                    <option value="">{t('hr.select_employee')}</option>
                                    {employees.map(emp => (
                                        <option key={emp.id} value={emp.id}>{emp.first_name} {emp.last_name} ({emp.employee_code || emp.id})</option>
                                    ))}
                                </select>
                            </div>
                            <div className="grid grid-cols-2 gap-3">
                                <div className="form-group"><label className="form-label">{t('hr.col_month')}</label>
                                    <select className="form-input" value={genForm.month} onChange={e => setGenForm({ ...genForm, month: e.target.value })}>
                                        {monthNames.map((name, i) => <option key={i + 1} value={i + 1}>{name}</option>)}
                                    </select></div>
                                <div className="form-group"><label className="form-label">{t('hr.year')}</label>
                                    <input type="number" className="form-input" value={genForm.year} onChange={e => setGenForm({ ...genForm, year: e.target.value })} /></div>
                            </div>
                            <div className="d-flex gap-3 pt-3">
                                <button type="submit" className="btn btn-primary flex-1"><Calculator size={16} /> {t('hr.generate_btn')}</button>
                                <button type="button" className="btn btn-secondary" onClick={() => setShowGenerate(false)}>{t('hr.cancel')}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* Payslip Detail Modal */}
            {showDetail && (
                <div className="modal-overlay" onClick={() => { setShowDetail(false); setSelectedPayslip(null); }}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 700, maxHeight: '90vh', overflow: 'auto' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                            <h3 className="modal-title" style={{ margin: 0 }}><FileText size={20} style={{ display: 'inline', verticalAlign: 'middle' }} /> {t('hr.payslip_detail_title')}</h3>
                            <div className="d-flex gap-2" style={{ alignItems: 'center' }}>
                                {selectedPayslip && (
                                    <button className="btn btn-sm btn-primary" onClick={handlePrint}><Printer size={14} /> {t('hr.print_payslip')}</button>
                                )}
                                <button type="button" onClick={() => { setShowDetail(false); setSelectedPayslip(null); }} style={{ background: 'none', border: 'none', cursor: 'pointer' }}><X size={20} /></button>
                            </div>
                        </div>

                        {detailLoading ? (
                            <div className="text-center p-6">...</div>
                        ) : selectedPayslip ? (
                            <div ref={printRef}>
                                <div className="payslip-container">
                                    {/* Header */}
                                    <div style={{ textAlign: 'center', borderBottom: '2px solid #2563eb', paddingBottom: 16, marginBottom: 20 }}>
                                        <h2 style={{ color: '#2563eb', fontSize: 20, marginBottom: 4 }}>{t('hr.payslip_print_title')}</h2>
                                        <p style={{ fontSize: 13, color: '#6b7280' }}>{monthNames[(selectedPayslip.month || 1) - 1]} {selectedPayslip.year} — {selectedPayslip.period_name || ''}</p>
                                    </div>

                                    {/* Employee Info */}
                                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 20, padding: 12, background: '#f8fafc', borderRadius: 8 }}>
                                        <div>
                                            <strong style={{ fontSize: 12, color: '#6b7280' }}>{t('hr.col_employee')}</strong>
                                            <div style={{ fontWeight: 600 }}>{selectedPayslip.employee_name}</div>
                                        </div>
                                        <div>
                                            <strong style={{ fontSize: 12, color: '#6b7280' }}>{t('hr.employee_id')}</strong>
                                            <div>{selectedPayslip.employee_id}</div>
                                        </div>
                                        <div>
                                            <strong style={{ fontSize: 12, color: '#6b7280' }}>{t('hr.col_status')}</strong>
                                            <div>{selectedPayslip.status || 'draft'}</div>
                                        </div>
                                    </div>

                                    {/* Earnings Table */}
                                    <div style={{ fontWeight: 600, color: '#1e40af', fontSize: 14, marginBottom: 8, paddingBottom: 4, borderBottom: '1px solid #e2e8f0' }}>
                                        {t('hr.payslip_earnings')}
                                    </div>
                                    <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: 16, color: 'var(--text-main)' }}>
                                        <thead>
                                            <tr style={{ background: 'var(--table-header-bg)' }}>
                                                <th style={{ padding: '8px 12px', textAlign: isRTL ? 'right' : 'left', fontSize: 13 }}>{t('hr.payslip_item')}</th>
                                                <th style={{ padding: '8px 12px', textAlign: isRTL ? 'left' : 'right', fontSize: 13 }}>{t('hr.payslip_amount')}</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            <tr><td style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-color)' }}>{t('hr.col_basic_salary')}</td><td style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-color)', textAlign: isRTL ? 'left' : 'right' }}>{formatNumber(selectedPayslip.basic_salary || 0)} {currency}</td></tr>
                                            {isPositiveMoney(selectedPayslip.housing_allowance) && <tr><td style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-color)' }}>{t('hr.payslip_housing')}</td><td style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-color)', textAlign: isRTL ? 'left' : 'right' }}>{formatNumber(selectedPayslip.housing_allowance)} {currency}</td></tr>}
                                            {isPositiveMoney(selectedPayslip.transport_allowance) && <tr><td style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-color)' }}>{t('hr.payslip_transport')}</td><td style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-color)', textAlign: isRTL ? 'left' : 'right' }}>{formatNumber(selectedPayslip.transport_allowance)} {currency}</td></tr>}
                                            {isPositiveMoney(selectedPayslip.other_allowances) && <tr><td style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-color)' }}>{t('hr.payslip_other_allowances')}</td><td style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-color)', textAlign: isRTL ? 'left' : 'right' }}>{formatNumber(selectedPayslip.other_allowances)} {currency}</td></tr>}
                                            {isPositiveMoney(selectedPayslip.salary_components_earning) && <tr><td style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-color)' }}>{t('hr.payslip_comp_earning')}</td><td style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-color)', textAlign: isRTL ? 'left' : 'right' }}>{formatNumber(selectedPayslip.salary_components_earning)} {currency}</td></tr>}
                                            {isPositiveMoney(selectedPayslip.overtime_amount) && <tr><td style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-color)' }}>{t('hr.payslip_overtime')}</td><td style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-color)', textAlign: isRTL ? 'left' : 'right' }}>{formatNumber(selectedPayslip.overtime_amount)} {currency}</td></tr>}
                                        </tbody>
                                    </table>

                                    {/* Deductions Table */}
                                    <div style={{ fontWeight: 600, color: '#dc2626', fontSize: 14, marginBottom: 8, paddingBottom: 4, borderBottom: '1px solid var(--border-color)' }}>
                                        {t('hr.payslip_deductions')}
                                    </div>
                                    <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: 16, color: 'var(--text-main)' }}>
                                        <thead>
                                            <tr style={{ background: 'rgba(239, 68, 68, 0.08)' }}>
                                                <th style={{ padding: '8px 12px', textAlign: isRTL ? 'right' : 'left', fontSize: 13 }}>{t('hr.payslip_item')}</th>
                                                <th style={{ padding: '8px 12px', textAlign: isRTL ? 'left' : 'right', fontSize: 13 }}>{t('hr.payslip_amount')}</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {isPositiveMoney(selectedPayslip.gosi_employee_share) && <tr><td style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-color)' }}>{t('hr.payslip_gosi_employee')}</td><td className="text-danger" style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-color)', textAlign: isRTL ? 'left' : 'right' }}>-{formatNumber(selectedPayslip.gosi_employee_share)} {currency}</td></tr>}
                                            {isPositiveMoney(selectedPayslip.violation_deduction) && <tr><td style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-color)' }}>{t('hr.payslip_violations')}</td><td className="text-danger" style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-color)', textAlign: isRTL ? 'left' : 'right' }}>-{formatNumber(selectedPayslip.violation_deduction)} {currency}</td></tr>}
                                            {isPositiveMoney(selectedPayslip.loan_deduction) && <tr><td style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-color)' }}>{t('hr.payslip_loan')}</td><td className="text-danger" style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-color)', textAlign: isRTL ? 'left' : 'right' }}>-{formatNumber(selectedPayslip.loan_deduction)} {currency}</td></tr>}
                                            {isPositiveMoney(selectedPayslip.salary_components_deduction) && <tr><td style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-color)' }}>{t('hr.payslip_comp_deduction')}</td><td className="text-danger" style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-color)', textAlign: isRTL ? 'left' : 'right' }}>-{formatNumber(selectedPayslip.salary_components_deduction)} {currency}</td></tr>}
                                        </tbody>
                                    </table>

                                    {/* GOSI Employer (Info) */}
                                    {isPositiveMoney(selectedPayslip.gosi_employer_share) && (
                                        <div style={{ background: '#fefce8', padding: '8px 12px', borderRadius: 6, fontSize: 13, marginBottom: 16, border: '1px solid #fef08a' }}>
                                            ℹ️ {t('hr.payslip_gosi_employer')}: <strong>{formatNumber(selectedPayslip.gosi_employer_share)} {currency}</strong> <span style={{ color: '#6b7280' }}>({t('hr.payslip_gosi_employer_note')})</span>
                                        </div>
                                    )}

                                    {/* Net Salary */}
                                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                                        <tbody>
                                            <tr style={{ background: '#eff6ff', fontWeight: 700, fontSize: 16 }}>
                                                <td style={{ padding: 14, borderTop: '2px solid #2563eb' }}>{t('hr.col_net_pay')}</td>
                                                <td style={{ padding: 14, borderTop: '2px solid #2563eb', textAlign: isRTL ? 'left' : 'right', color: '#16a34a' }}>
                                                    {formatNumber(selectedPayslip.net_salary || 0)} {currency}
                                                </td>
                                            </tr>
                                        </tbody>
                                    </table>

                                    <div style={{ marginTop: 24, display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#9ca3af', borderTop: '1px dashed #d1d5db', paddingTop: 10 }}>
                                        <span>{t('hr.payslip_auto_generated')}</span>
                                        <span>{new Date().toLocaleDateString(t('hr.enus'))}</span>
                                    </div>
                                </div>
                            </div>
                        ) : null}
                    </div>
                </div>
            )}
        </div>
    );
};

export default Payslips;
