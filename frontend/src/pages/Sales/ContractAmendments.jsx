import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { contractsAPI } from '../../utils/api';
import { getCurrency } from '../../utils/auth';
import { useBranch } from '../../context/BranchContext';
import { useToast } from '../../context/ToastContext';
import { FileText, Plus, Save, X, BarChart3, Calendar, DollarSign, TrendingUp } from 'lucide-react';
import BackButton from '../../components/common/BackButton';
import '../../components/ModuleStyles.css';
import DateInput from '../../components/common/DateInput';
import { formatNumber } from '../../utils/format';
import { PageLoading } from '../../components/common/LoadingStates'

const ContractAmendments = () => {
    const { t } = useTranslation();
    const { showToast } = useToast();
    const { currentBranch } = useBranch();
    const [activeTab, setActiveTab] = useState('amendments');
    const [contracts, setContracts] = useState([]);
    const [selectedContract, setSelectedContract] = useState('');
    const [amendments, setAmendments] = useState([]);
    const [kpis, setKpis] = useState(null);
    const [loading, setLoading] = useState(true);
    const [showForm, setShowForm] = useState(false);
    const [form, setForm] = useState({
        amendment_type: 'scope_change', description: '',
        old_value: '', new_value: '', effective_date: '', approved_by: ''
    });

    useEffect(() => { fetchContracts(); }, [currentBranch]);
    useEffect(() => { if (selectedContract) fetchData(); }, [selectedContract, activeTab]);

    const fetchContracts = async () => {
        try {
            const res = await contractsAPI.listContracts({ branch_id: currentBranch?.id });
            const list = res.data?.contracts || res.data || [];
            setContracts(list);
            if (list.length > 0) setSelectedContract(list[0].id);
        } catch (err) { showToast(t('common.error'), 'error'); }
    };

    const fetchData = async () => {
        try {
            setLoading(true);
            if (activeTab === 'amendments') {
                const res = await contractsAPI.listAmendments(selectedContract);
                setAmendments(res.data || []);
            } else {
                const res = await contractsAPI.getContractKPIs(selectedContract);
                setKpis(res.data);
            }
        } catch (err) { showToast(t('common.error'), 'error'); } finally { setLoading(false); }
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        try {
            await contractsAPI.createAmendment(selectedContract, form);
            showToast(t('sales.amendment_added'), 'success');
            setShowForm(false);
            setForm({ amendment_type: 'scope_change', description: '', old_value: '', new_value: '', effective_date: '', approved_by: '' });
            fetchData();
        } catch (err) { showToast(err.response?.data?.detail || 'Error', 'error'); }
    };

    const amendmentTypes = {
        scope_change: { label: t('sales.scope_change'), color: '#1565c0' },
        price_adjustment: { label: t('sales.price_adjustment'), color: '#2e7d32' },
        term_extension: { label: t('sales.term_extension'), color: '#f57f17' },
        term_reduction: { label: t('sales.term_reduction'), color: '#e65100' },
        clause_modification: { label: t('sales.clause_modification'), color: '#7b1fa2' },
        party_change: { label: t('sales.party_change'), color: '#00838f' },
        termination: { label: t('sales.termination'), color: '#c62828' }
    };

    const formatCurrency = (val) => {
        if (!val && val !== 0) return '—';
        return new Intl.NumberFormat(t('sales.ensa'), { style: 'currency', currency: getCurrency() || 'SAR', maximumFractionDigits: 0 }).format(val);
    };

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div>
                    <h1 className="workspace-title">
                        <FileText size={24} className="me-2" />
                        {t('sales.contract_amendments_kpis')}
                    </h1>
                    <p className="workspace-subtitle">
                        {t('sales.track_contract_amendments_and_performance_indicato')}
                    </p>
                </div>
            </div>

            {/* Contract Selector */}
            <div className="d-flex gap-3 mb-4 align-items-center">
                <label className="form-label mb-0" style={{ whiteSpace: 'nowrap' }}>{t('sales.contract')}</label>
                <select className="form-input" style={{ maxWidth: 400 }} value={selectedContract}
                    onChange={e => setSelectedContract(e.target.value)}>
                    {contracts.map(c => <option key={c.id} value={c.id}>{c.title || c.contract_number || `#${c.id}`}</option>)}
                </select>
            </div>

            {/* Tabs */}
            <div className="tabs mb-4">
                <button className={`tab ${activeTab === 'amendments' ? 'active' : ''}`} onClick={() => setActiveTab('amendments')}>
                    <FileText size={16} /> <span className="ms-1">{t('sales.amendments')}</span>
                </button>
                <button className={`tab ${activeTab === 'kpis' ? 'active' : ''}`} onClick={() => setActiveTab('kpis')}>
                    <BarChart3 size={16} /> <span className="ms-1">{t('sales.kpis')}</span>
                </button>
            </div>

            {loading ? (
                <PageLoading />
            ) : activeTab === 'amendments' ? (
                <>
                    <div className="mb-3">
                        <button className="btn btn-primary" onClick={() => setShowForm(true)}>
                            <Plus size={16} className="me-1" /> {t('sales.add_amendment')}
                        </button>
                    </div>

                    {/* Amendment Form */}
                    {showForm && (
                        <div className="section-card mb-4">
                            <h4 className="mb-3">{t('sales.new_amendment')}</h4>
                            <form onSubmit={handleSubmit}>
                                <div className="row g-3">
                                    <div className="col-md-4">
                                        <div className="form-group">
                                            <label className="form-label">{t('sales.type')} *</label>
                                            <select className="form-input" required value={form.amendment_type}
                                                onChange={e => setForm(p => ({ ...p, amendment_type: e.target.value }))}>
                                                {Object.entries(amendmentTypes).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
                                            </select>
                                        </div>
                                    </div>
                                    <div className="col-md-4">
                                        <div className="form-group">
                                            <label className="form-label">{t('sales.effective_date')}</label>
                                            <DateInput className="form-input" value={form.effective_date}
                                                onChange={e => setForm(p => ({ ...p, effective_date: e.target.value }))} />
                                        </div>
                                    </div>
                                    <div className="col-md-4">
                                        <div className="form-group">
                                            <label className="form-label">{t('sales.approved_by')}</label>
                                            <input className="form-input" value={form.approved_by}
                                                onChange={e => setForm(p => ({ ...p, approved_by: e.target.value }))} />
                                        </div>
                                    </div>
                                    <div className="col-md-6">
                                        <div className="form-group">
                                            <label className="form-label">{t('sales.old_value')}</label>
                                            <input className="form-input" value={form.old_value}
                                                onChange={e => setForm(p => ({ ...p, old_value: e.target.value }))} />
                                        </div>
                                    </div>
                                    <div className="col-md-6">
                                        <div className="form-group">
                                            <label className="form-label">{t('sales.new_value')}</label>
                                            <input className="form-input" value={form.new_value}
                                                onChange={e => setForm(p => ({ ...p, new_value: e.target.value }))} />
                                        </div>
                                    </div>
                                    <div className="col-md-12">
                                        <div className="form-group">
                                            <label className="form-label">{t('sales.description')} *</label>
                                            <textarea className="form-input" rows={3} required value={form.description}
                                                onChange={e => setForm(p => ({ ...p, description: e.target.value }))} />
                                        </div>
                                    </div>
                                </div>
                                <div className="d-flex gap-2 mt-3">
                                    <button type="submit" className="btn btn-primary"><Save size={16} className="me-1" /> {t('sales.save')}</button>
                                    <button type="button" className="btn btn-outline-secondary" onClick={() => setShowForm(false)}><X size={16} className="me-1" /> {t('sales.cancel')}</button>
                                </div>
                            </form>
                        </div>
                    )}

                    {/* Amendments list */}
                    <div className="section-card">
                        <div className="data-table-container">
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>#</th>
                                        <th>{t('sales.type_2')}</th>
                                        <th>{t('sales.description')}</th>
                                        <th>{t('sales.old_value')}</th>
                                        <th>{t('sales.new_value')}</th>
                                        <th>{t('sales.effective_date_2')}</th>
                                        <th>{t('sales.approved_by')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {amendments.length === 0 ? (
                                        <tr><td colSpan={7} className="text-center p-4">{t('sales.no_amendments_yet')}</td></tr>
                                    ) : amendments.map((a, idx) => (
                                        <tr key={a.id}>
                                            <td>{idx + 1}</td>
                                            <td>
                                                <span className="badge" style={{ background: amendmentTypes[a.amendment_type]?.color || '#6c757d', color: '#fff' }}>
                                                    {amendmentTypes[a.amendment_type]?.label || a.amendment_type}
                                                </span>
                                            </td>
                                            <td>{a.description}</td>
                                            <td>{a.old_value || '—'}</td>
                                            <td>{a.new_value || '—'}</td>
                                            <td>{a.effective_date ? new Date(a.effective_date).toLocaleDateString() : '—'}</td>
                                            <td>{a.approved_by || '—'}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>

                    {/* Accounting Note */}
                    <div className="section-card mt-4" style={{ background: '#f0f7ff', border: '1px dashed #90caf9' }}>
                        <h5 style={{ color: '#1565c0' }}>{t('sales.accounting_impact')}</h5>
                        <ul style={{ fontSize: '0.9rem', lineHeight: 1.8 }}>
                            <li><strong>{t('sales.price_adjustment_2')}</strong> {t('sales.adjusts_remaining_revenuecost_prospectively_ias_8')}</li>
                            <li><strong>{t('sales.scope_change_2')}</strong> {t('sales.recalculates_completion_per_ifrs_1518')}</li>
                            <li><strong>{t('sales.early_termination')}</strong> {t('sales.records_penalty_provision_dr_penalty_expense_cr_pr')}</li>
                        </ul>
                    </div>
                </>
            ) : (
                <>
                    {/* KPIs Dashboard */}
                    {kpis && (
                        <div className="metrics-grid mb-4">
                            <div className="metric-card">
                                <div className="metric-icon" style={{ background: '#e3f2fd' }}><TrendingUp size={22} color="#1565c0" /></div>
                                <div className="metric-info">
                                    <span className="metric-value">{formatNumber(kpis.utilization_pct || 0, 1)}%</span>
                                    <span className="metric-label">{t('sales.utilization')}</span>
                                </div>
                            </div>
                            <div className="metric-card">
                                <div className="metric-icon" style={{ background: '#fff3e0' }}><Calendar size={22} color="#ef6c00" /></div>
                                <div className="metric-info">
                                    <span className="metric-value">{kpis.days_remaining || 0}</span>
                                    <span className="metric-label">{t('sales.days_remaining')}</span>
                                </div>
                            </div>
                            <div className="metric-card">
                                <div className="metric-icon" style={{ background: '#e8f5e9' }}><DollarSign size={22} color="#2e7d32" /></div>
                                <div className="metric-info">
                                    <span className="metric-value">{kpis.invoice_count || 0}</span>
                                    <span className="metric-label">{t('sales.invoice_count')}</span>
                                </div>
                            </div>
                            <div className="metric-card">
                                <div className="metric-icon" style={{ background: '#fce4ec' }}><DollarSign size={22} color="#c62828" /></div>
                                <div className="metric-info">
                                    <span className="metric-value">{formatCurrency(kpis.outstanding_amount)}</span>
                                    <span className="metric-label">{t('sales.outstanding_amount')}</span>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Contract financial summary */}
                    {kpis && (
                        <div className="section-card">
                            <h4 className="mb-3">{t('sales.financial_summary')}</h4>
                            <div className="row g-3">
                                <div className="col-md-6">
                                    <table className="data-table">
                                        <tbody>
                                            <tr><td><strong>{t('sales.contract_value')}</strong></td><td>{formatCurrency(kpis.contract_value)}</td></tr>
                                            <tr><td><strong>{t('sales.invoiced_amount')}</strong></td><td>{formatCurrency(kpis.invoiced_amount)}</td></tr>
                                            <tr><td><strong>{t('sales.collected_amount')}</strong></td><td>{formatCurrency(kpis.collected_amount)}</td></tr>
                                            <tr><td><strong>{t('sales.outstanding')}</strong></td><td style={{ color: '#c62828' }}>{formatCurrency(kpis.outstanding_amount)}</td></tr>
                                        </tbody>
                                    </table>
                                </div>
                                <div className="col-md-6">
                                    <table className="data-table">
                                        <tbody>
                                            <tr><td><strong>{t('sales.start_date')}</strong></td><td>{kpis.start_date || '—'}</td></tr>
                                            <tr><td><strong>{t('sales.end_date')}</strong></td><td>{kpis.end_date || '—'}</td></tr>
                                            <tr><td><strong>{t('sales.amendments_2')}</strong></td><td>{kpis.amendment_count || 0}</td></tr>
                                            <tr><td><strong>{t('sales.profit_margin')}</strong></td><td>{formatNumber(kpis.profit_margin || 0, 1)}%</td></tr>
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </div>
                    )}
                </>
            )}
        </div>
    );
};

export default ContractAmendments;
