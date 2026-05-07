import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { salesAPI } from '../../utils/api';
import { useBranch } from '../../context/BranchContext';
import { useToast } from '../../context/ToastContext';
import { getCurrency } from '../../utils/auth';
import { formatNumber } from '../../utils/format';
import { Plus, DollarSign, Calculator } from 'lucide-react';
import '../../components/ModuleStyles.css';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

const SalesCommissions = () => {
    const { t } = useTranslation();
    const { showToast } = useToast();
    const { currentBranch } = useBranch();
    const currency = getCurrency();
    const [commissions, setCommissions] = useState([]);
    const [rules, setRules] = useState([]);
    const [summary, setSummary] = useState(null);
    const [loading, setLoading] = useState(true);
    const [activeTab, setActiveTab] = useState('commissions');
    const [showRuleModal, setShowRuleModal] = useState(false);
    const [ruleForm, setRuleForm] = useState({ salesperson_id: '', rate: '', min_amount: '' });

    useEffect(() => { fetchAll(); }, [currentBranch]);

    const fetchAll = async () => {
        try {
            setLoading(true);
            const [commRes, rulesRes, summRes] = await Promise.all([
                salesAPI.listCommissions({ branch_id: currentBranch?.id }).catch(() => ({ data: [] })),
                salesAPI.listCommissionRules({ branch_id: currentBranch?.id }).catch(() => ({ data: [] })),
                salesAPI.getCommissionSummary({ branch_id: currentBranch?.id }).catch(() => ({ data: null })),
            ]);
            setCommissions(commRes.data || []);
            setRules(rulesRes.data || []);
            setSummary(summRes.data);
        } catch (err) { showToast(t('common.error'), 'error'); } finally { setLoading(false); }
    };

    const handleCreateRule = async (e) => {
        e.preventDefault();
        try {
            await salesAPI.createCommissionRule({ salesperson_id: parseInt(ruleForm.salesperson_id), rate: Number(ruleForm.rate), min_amount: Number(ruleForm.min_amount) || 0, branch_id: currentBranch?.id });
            showToast(t('sales.rule_created'), 'success');
            setShowRuleModal(false); fetchAll();
        } catch (err) { showToast(err.response?.data?.detail || t('common.error'), 'error'); }
    };

    const handleCalculate = async () => {
        try {
            const res = await salesAPI.calculateCommissions({ branch_id: currentBranch?.id });
            showToast(t('sales.calculated_commissions') + ` (${res.data?.count || 0})`, 'success');
            fetchAll();
        } catch (err) { showToast(err.response?.data?.detail || t('common.error'), 'error'); }
    };

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1 className="workspace-title"><span className="p-2 rounded-lg bg-emerald-50 text-emerald-600"><DollarSign size={24} /></span> {t('sales.commissions_title')}</h1>
                        <p className="workspace-subtitle">{t('sales.commissions_subtitle')}</p>
                    </div>
                    <div className="d-flex gap-2">
                        <button className="btn btn-warning" onClick={handleCalculate}><Calculator size={18} /> {t('sales.calculate')}</button>
                        <button className="btn btn-primary" onClick={() => setShowRuleModal(true)}><Plus size={18} /> {t('sales.new_rule')}</button>
                    </div>
                </div>
            </div>

            {/* Summary */}
            {summary && (
                <div className="metrics-grid mb-4">
                    <div className="metric-card"><div className="metric-label">{t('sales.total_commissions')}</div><div className="metric-value text-primary">{formatNumber(summary.total_commissions || 0)} <small>{currency}</small></div></div>
                    <div className="metric-card"><div className="metric-label">{t('sales.paid_metric')}</div><div className="metric-value text-success">{formatNumber(summary.total_paid || 0)} <small>{currency}</small></div></div>
                    <div className="metric-card"><div className="metric-label">{t('sales.pending_metric')}</div><div className="metric-value text-warning">{formatNumber(summary.total_pending || 0)} <small>{currency}</small></div></div>
                </div>
            )}

            {/* Tabs */}
            <div className="d-flex gap-2 mb-4">
                <button onClick={() => setActiveTab('commissions')} className={`btn ${activeTab === 'commissions' ? 'btn-primary' : 'btn-secondary'}`}>{t('sales.commissions_title')}</button>
                <button onClick={() => setActiveTab('rules')} className={`btn ${activeTab === 'rules' ? 'btn-primary' : 'btn-secondary'}`}>{t('sales.tab_rules')}</button>
            </div>

            <div className="card section-card">
                {loading ? <PageLoading /> : activeTab === 'commissions' ? (
                    <div className="data-table-container">
                        <table className="data-table">
                            <thead><tr>
                                <th>{t('sales.col_salesperson')}</th>
                                <th>{t('sales.col_invoice')}</th>
                                <th>{t('sales.col_amount')}</th>
                                <th>{t('sales.col_rate')}</th>
                                <th>{t('sales.col_commission')}</th>
                                <th>{t('sales.col_status')}</th>
                            </tr></thead>
                            <tbody>
                                {commissions.map(c => (
                                    <tr key={c.id}>
                                        <td>{c.salesperson_name || `#${c.salesperson_id}`}</td>
                                        <td>#{c.invoice_id}</td>
                                        <td>{formatNumber(c.invoice_amount)} {currency}</td>
                                        <td>{c.commission_rate}%</td>
                                        <td className="font-bold">{formatNumber(c.commission_amount)} {currency}</td>
                                        <td><span className={`badge ${c.status === 'paid' ? 'bg-green-100 text-green-700' : 'bg-yellow-100 text-yellow-700'}`}>{c.status === 'paid' ? (t('sales.status_paid')) : (t('sales.status_pending'))}</span></td>
                                    </tr>
                                ))}
                                {commissions.length === 0 && <tr><td colSpan="6" className="text-center text-muted p-4">{t('sales.no_commissions')}</td></tr>}
                            </tbody>
                        </table>
                    </div>
                ) : (
                    <div className="data-table-container">
                        <table className="data-table">
                            <thead><tr>
                                <th>{t('sales.col_salesperson')}</th>
                                <th>{t('sales.col_rate')}</th>
                                <th>{t('sales.col_min_amount')}</th>
                            </tr></thead>
                            <tbody>
                                {rules.map(r => (
                                    <tr key={r.id}>
                                        <td>{r.salesperson_name || `#${r.salesperson_id}`}</td>
                                        <td className="font-bold">{r.rate}%</td>
                                        <td>{formatNumber(r.min_amount || 0)} {currency}</td>
                                    </tr>
                                ))}
                                {rules.length === 0 && <tr><td colSpan="3" className="text-center text-muted p-4">{t('sales.no_rules')}</td></tr>}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>

            {showRuleModal && (
                <div className="modal-overlay" onClick={() => setShowRuleModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 400 }}>
                        <h3 className="modal-title">{t('sales.new_commission_rule')}</h3>
                        <form onSubmit={handleCreateRule} className="space-y-4">
                            <div className="form-group"><label className="form-label">{t('sales.salesperson_id')}</label>
                                <input type="number" className="form-input" required value={ruleForm.salesperson_id} onChange={e => setRuleForm({ ...ruleForm, salesperson_id: e.target.value })} /></div>
                            <div className="form-group"><label className="form-label">{t('sales.rate_percent')}</label>
                                <input type="number" step="0.1" className="form-input" required value={ruleForm.rate} onChange={e => setRuleForm({ ...ruleForm, rate: e.target.value })} /></div>
                            <div className="form-group"><label className="form-label">{t('sales.min_amount_form')}</label>
                                <input type="number" className="form-input" value={ruleForm.min_amount} onChange={e => setRuleForm({ ...ruleForm, min_amount: e.target.value })} /></div>
                            <div className="d-flex gap-3 pt-3">
                                <button type="submit" className="btn btn-primary flex-1">{t('sales.create')}</button>
                                <button type="button" className="btn btn-secondary" onClick={() => setShowRuleModal(false)}>{t('sales.cancel')}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
};

export default SalesCommissions;
