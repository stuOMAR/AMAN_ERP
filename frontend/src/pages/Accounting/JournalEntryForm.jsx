
import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Save, Plus, Trash2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'react-hot-toast';
import { accountingAPI, costCentersAPI } from '../../utils/api';
import { useBranch } from '../../context/BranchContext';
import { getCurrency } from '../../utils/auth';
import { formatNumber } from '../../utils/format';
import CurrencySelector from '../../components/common/CurrencySelector';
import CustomDatePicker from '../../components/common/CustomDatePicker';
import BackButton from '../../components/common/BackButton';
import FormField from '../../components/common/FormField';
const JournalEntryForm = () => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const [loading, setLoading] = useState(false);
    const [initialLoad, setInitialLoad] = useState(true);
    const [accounts, setAccounts] = useState([]);
    const [costCenters, setCostCenters] = useState([]);
    const { currentBranch } = useBranch();
    const currency = getCurrency();

    const [formData, setFormData] = useState({
        date: new Date().toISOString().split('T')[0],
        reference: '',
        description: '',
        currency: '',
        exchange_rate: 1.0,
        lines: [
            { account_id: '', debit: 0, credit: 0, description: '', cost_center_id: '' },
            { account_id: '', debit: 0, credit: 0, description: '', cost_center_id: '' }
        ]
    });
    const [idempotencyKey, setIdempotencyKey] = useState(crypto.randomUUID());

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchAccounts();
            fetchCostCenters();
            setInitialLoad(false);
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch]);

    const fetchAccounts = async () => {
        try {
            const response = await accountingAPI.list();
            setAccounts(response.data || []);
        } catch (error) {
            console.error(error);
            toast.error(t('accounting.coa.errors.fetch_failed'));
        }
    };

    const fetchCostCenters = async () => {
        try {
            const response = await costCentersAPI.list();
            setCostCenters(response.data || []);
        } catch (error) {
            console.error(error);
        }
    };

    const handleLineChange = (index, field, value) => {
        const newLines = [...formData.lines];
        // Prevent negative debit/credit values
        if ((field === 'debit' || field === 'credit') && parseFloat(value) < 0) {
            value = 0;
        }
        newLines[index][field] = value;
        setFormData({ ...formData, lines: newLines });
    };

    const addLine = () => {
        setFormData({
            ...formData,
            lines: [...formData.lines, { account_id: '', debit: 0, credit: 0, description: '', cost_center_id: '' }]
        });
    };

    const removeLine = (index) => {
        if (formData.lines.length <= 2) {
            toast.error(t('accounting.journal.min_lines_error', 'At least 2 lines are required'));
            return;
        }
        const newLines = formData.lines.filter((_, i) => i !== index);
        setFormData({ ...formData, lines: newLines });
    };

    const calculateTotals = () => {
        const totalDebit = formData.lines.reduce((sum, line) => sum + parseFloat(line.debit || 0), 0);
        const totalCredit = formData.lines.reduce((sum, line) => sum + parseFloat(line.credit || 0), 0);
        const difference = totalDebit - totalCredit;
        return { totalDebit, totalCredit, difference };
    };

    const handleSubmit = async (e, entryStatus = 'posted') => {
        if (e) e.preventDefault();
        const { totalDebit, totalCredit, difference } = calculateTotals();

        if (Math.abs(difference) > 0.01) {
            toast.error(t('accounting.journal.unbalanced_error', 'Journal Entry must be balanced'));
            return;
        }

        if (totalDebit === 0) {
            toast.error(t('accounting.journal.zero_amount_error', 'Total amount cannot be zero'));
            return;
        }

        if (formData.lines.some(l => !l.account_id)) {
            toast.error(t('accounting.journal.account_required', 'All lines must have an account selected'));
            return;
        }

        const hasDebit = formData.lines.some(l => parseFloat(l.debit || 0) > 0);
        const hasCredit = formData.lines.some(l => parseFloat(l.credit || 0) > 0);
        if (!hasDebit || !hasCredit) {
            toast.error(t('accounting.journal.debit_credit_required', 'Each entry must have at least one debit line and one credit line'));
            return;
        }

        const invalidLines = formData.lines.filter(l => parseFloat(l.debit || 0) > 0 && parseFloat(l.credit || 0) > 0);
        if (invalidLines.length > 0) {
            toast.error(t('accounting.journal.both_debit_credit', 'A line cannot have both debit and credit amounts. Please use separate lines.'));
            return;
        }

        setLoading(true);
        try {
            const payload = {
                ...formData,
                status: entryStatus,
                branch_id: currentBranch?.id
            };
            const res = await accountingAPI.createJournalEntry(payload, {
                headers: { 'Idempotency-Key': idempotencyKey }
            });
            toast.success(res.data?.message || t('common.success'));
            setIdempotencyKey(crypto.randomUUID());
            navigate('/accounting/journal-entries');
        } catch (error) {
            console.error(error);
            toast.error(error.response?.data?.detail || t('common.error_occurred'));
        } finally {
            setLoading(false);
        }
    };

    const { totalDebit, totalCredit, difference } = calculateTotals();

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                        <BackButton />
                        <div>
                            <h1 className="workspace-title">{t('accounting.home.links.journal_entry')}</h1>
                            <p className="workspace-subtitle">{t('accounting.journal.subtitle')}</p>
                        </div>
                    </div>
                    <div style={{ display: 'flex', gap: '8px' }}>
                        <button onClick={(e) => handleSubmit(e, 'draft')} className="btn btn-secondary" disabled={loading}>
                            {loading ? '...' : (t('accounting.journal.save_draft'))}
                        </button>
                        <button onClick={(e) => handleSubmit(e, 'posted')} className="btn btn-primary" disabled={loading}>
                            <Save size={18} style={{ marginLeft: '8px' }} />
                            {loading ? t('common.saving') : t('accounting.journal.post')}
                        </button>
                    </div>
                </div>
            </div>

            <div className="workspace-content">
                <div className="card mb-4">
                    <div >
                        <div className="row">
                            <div className="col-md-2 mb-3">
                                <CurrencySelector
                                    label={t('common.currency')}
                                    value={formData.currency}
                                    onChange={(code, rate) => setFormData({ ...formData, currency: code, exchange_rate: rate })}
                                />
                            </div>
                            <div className="col-md-2 mb-3">
                                <FormField label={t('common.exchange_rate')}>
                                    <input
                                        type="number"
                                        step="0.000001"
                                        className="form-input"
                                        value={formData.exchange_rate || 1.0}
                                        onChange={(e) => setFormData({ ...formData, exchange_rate: parseFloat(e.target.value) || 1 })}
                                    />
                                </FormField>
                            </div>
                            <div className="col-md-2 mb-3">
                                <FormField label={t('common.date')}>
                                    <CustomDatePicker
                                        selected={formData.date}
                                        onChange={(dateStr) => setFormData({ ...formData, date: dateStr })}
                                        required
                                    />
                                </FormField>
                            </div>
                            <div className="col-md-2 mb-3">
                                <FormField label={t('common.reference')}>
                                    <input
                                        type="text"
                                        className="form-input"
                                        value={formData.reference}
                                        onChange={(e) => setFormData({ ...formData, reference: e.target.value })}
                                    />
                                </FormField>
                            </div>
                            <div className="col-md-4 mb-3">
                                <FormField label={t('common.description')} required>
                                    <input
                                        type="text"
                                        className="form-input"
                                        value={formData.description}
                                        onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                                        required
                                        placeholder={t("accounting.journal.desc_placeholder")}
                                    />
                                </FormField>
                            </div>
                        </div>
                    </div>
                </div>

                <div className="card">
                    <div className="data-table-container">
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th style={{ width: '30%' }}>{t('accounting.account_name')}</th>
                                    <th>{t('common.description')}</th>
                                    <th style={{ width: '15%' }}>{t('cost_centers.title')}</th>
                                    <th style={{ width: '12%' }}>{t('accounting.table.debit')}</th>
                                    <th style={{ width: '12%' }}>{t('accounting.table.credit')}</th>
                                    <th style={{ width: '50px' }}></th>
                                </tr>
                            </thead>
                            <tbody>
                                {formData.lines.map((line, index) => (
                                    <tr key={index}>
                                        <td>
                                            <select
                                                className="form-input"
                                                style={{ border: 'none', background: 'transparent', padding: '0' }}
                                                value={line.account_id}
                                                onChange={(e) => handleLineChange(index, 'account_id', e.target.value)}
                                            >
                                                <option value="">{t('common.select_account')}</option>
                                                {accounts.filter(acc => !acc.is_header).map(acc => (
                                                    <option key={acc.id} value={acc.id}>
                                                        {acc.account_number} - {acc.name}
                                                    </option>
                                                ))}
                                            </select>
                                        </td>
                                        <td>
                                            <input
                                                type="text"
                                                className="form-input"
                                                style={{ border: 'none', background: 'transparent', padding: '0' }}
                                                value={line.description}
                                                onChange={(e) => handleLineChange(index, 'description', e.target.value)}
                                                placeholder={formData.description || t('accounting.journal.line_desc_placeholder')}
                                            />
                                        </td>
                                        <td>
                                            <select
                                                className="form-input"
                                                style={{ border: 'none', background: 'transparent', padding: '0' }}
                                                value={line.cost_center_id || ''}
                                                onChange={(e) => handleLineChange(index, 'cost_center_id', e.target.value)}
                                            >
                                                <option value="">-</option>
                                                {costCenters.map(cc => (
                                                    <option key={cc.id} value={cc.id}>{cc.center_name}</option>
                                                ))}
                                            </select>
                                        </td>
                                        <td>
                                            <input
                                                type="number"
                                                className="form-input text-end"
                                                style={{ border: 'none', background: 'transparent', padding: '0' }}
                                                min="0"
                                                value={line.debit}
                                                onChange={(e) => handleLineChange(index, 'debit', e.target.value)}
                                                onFocus={(e) => e.target.select()}
                                            />
                                        </td>
                                        <td>
                                            <input
                                                type="number"
                                                className="form-input text-end"
                                                style={{ border: 'none', background: 'transparent', padding: '0' }}
                                                min="0"
                                                value={line.credit}
                                                onChange={(e) => handleLineChange(index, 'credit', e.target.value)}
                                                onFocus={(e) => e.target.select()}
                                            />
                                        </td>
                                        <td className="text-center">
                                            <button
                                                className="table-action-btn"
                                                style={{ color: 'var(--danger)' }}
                                                onClick={() => removeLine(index)}
                                                tabIndex="-1"
                                            >
                                                <Trash2 size={16} />
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                            <tfoot className="fw-bold bg-light">
                                <tr>
                                    <td colSpan="3" className="text-end py-3">{t('common.total')}</td>
                                    <td className={`text-end py-3 ${totalDebit !== totalCredit ? 'text-danger' : 'text-success'}`}>
                                        {formatNumber(totalDebit)} <small>{currency}</small>
                                    </td>
                                    <td className={`text-end py-3 ${totalDebit !== totalCredit ? 'text-danger' : 'text-success'}`}>
                                        {formatNumber(totalCredit)} <small>{currency}</small>
                                    </td>
                                    <td></td>
                                </tr>
                            </tfoot>
                        </table>
                    </div>
                </div>

                <div className="mt-3 d-flex justify-content-between align-items-center">
                    <button className="btn btn-outline-primary btn-sm" style={{ borderRadius: '8px' }} onClick={addLine}>
                        <Plus size={16} style={{ marginLeft: '4px' }} />
                        {t('common.add_line')}
                    </button>

                    {Math.abs(difference) > 0.01 && (
                        <div className="badge bg-danger-subtle text-danger p-2" style={{ borderRadius: '8px' }}>
                            {t('accounting.trial_balance.metrics.difference')}: {formatNumber(difference)} <small>{currency}</small>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default JournalEntryForm;
