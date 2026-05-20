import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { GitMerge, Landmark, ShoppingCart, Receipt, Factory, Users, Briefcase, CreditCard, ArrowLeftRight, RefreshCw } from 'lucide-react';
import api, { accountingAPI } from '../../../utils/api';
import { toastEmitter } from '../../../utils/toastEmitter';
import { Spinner } from '../../../components/common/LoadingStates'

const AccountingMappingSettings = ({ settings, handleSettingChange }) => {
    const { t } = useTranslation();
    const [accounts, setAccounts] = useState([]);
    const [loading, setLoading] = useState(true);

    // Advanced Tools State
    const [fxProcessing, setFxProcessing] = useState(false);
    const [fxCurrencyCode, setFxCurrencyCode] = useState('');
    const [fxNewRate, setFxNewRate] = useState('');
    const [badDebtProcessing, setBadDebtProcessing] = useState(false);
    const [badDebtAmount, setBadDebtAmount] = useState('');
    const [leaveProvProcessing, setLeaveProvProcessing] = useState(false);

    useEffect(() => {
        const fetchAccounts = async () => {
            try {
                const response = await api.get('/accounting/accounts');
                setAccounts(response.data || []);
            } catch (err) {
                console.error("Failed to fetch accounts", err);
            } finally {
                setLoading(false);
            }
        };
        fetchAccounts();
    }, []);

    const renderAccountSelect = (label, settingKey, description) => (
        <div className="form-group">
            <label className="form-label text-sm font-medium" htmlFor={settingKey}>{label}</label>
            <select
                id={settingKey}
                className="form-select select select-bordered w-full"
                value={settings[settingKey] || ''}
                onChange={(e) => handleSettingChange(settingKey, e.target.value)}
            >
                <option value="">{t('common.select_account')}</option>
                {accounts.map(acc => (
                    <option key={acc.id} value={acc.id.toString()}>
                        {acc.account_number} - {acc.name}
                    </option>
                ))}
            </select>
            {description && <p className="text-xs text-base-content/40 mt-1">{description}</p>}
        </div>
    );

    const m = (key) => t(`settings.accounting_mapping.${key}`);

    // --- Advanced Tools Handlers ---
    const handleFxRevaluation = async () => {
        if (!fxCurrencyCode.trim() || !fxNewRate || Number(fxNewRate) <= 0) {
            toastEmitter.emit(t('common.fill_required', 'Please fill required fields'), 'error');
            return;
        }
        if (!window.confirm(m('confirm_fx_revaluation'))) return;
        setFxProcessing(true);
        try {
            await accountingAPI.fxRevaluation({
                currency_code: fxCurrencyCode.trim().toUpperCase(),
                new_rate: String(fxNewRate),
            });
            toastEmitter.emit(m('fx_revaluation_success'), 'success');
        } catch (err) {
            console.error("FX Revaluation failed", err);
        } finally {
            setFxProcessing(false);
        }
    };

    const handleBadDebtProvision = async () => {
        if (!badDebtAmount || Number(badDebtAmount) <= 0) {
            toastEmitter.emit(t('common.fill_required', 'Please fill required fields'), 'error');
            return;
        }
        if (!window.confirm(m('confirm_bad_debt'))) return;
        setBadDebtProcessing(true);
        try {
            await accountingAPI.createBadDebtProvision({ amount: String(badDebtAmount) });
            toastEmitter.emit(m('bad_debt_success'), 'success');
        } catch (err) {
            console.error("Bad debt provision failed", err);
        } finally {
            setBadDebtProcessing(false);
        }
    };

    const handleLeaveProvision = async () => {
        if (!window.confirm(m('confirm_leave_provision'))) return;
        setLeaveProvProcessing(true);
        try {
            await accountingAPI.createLeaveProvision({});
            toastEmitter.emit(m('leave_provision_success'), 'success');
        } catch (err) {
            console.error("Leave provision failed", err);
        } finally {
            setLeaveProvProcessing(false);
        }
    };

    if (loading) return <div className="p-4 text-center"><Spinner size="sm"/></div>;

    return (
        <div className="space-y-8">

            {/* ── Sales & Revenue ───────────────────────────── */}
            <div className="bg-base-50 p-6 rounded-2xl border border-base-200">
                <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
                    <ShoppingCart size={20} className="text-primary" />
                    {m('section_sales')}
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {renderAccountSelect(m('sales_revenue_account'), 'acc_map_sales_rev', m('sales_revenue_account_desc'))}
                    {renderAccountSelect(m('cogs_account'), 'acc_map_cogs', m('cogs_account_desc'))}
                    {renderAccountSelect(m('accounts_receivable'), 'acc_map_ar', m('accounts_receivable_desc'))}
                    {renderAccountSelect(m('sales_discount'), 'acc_map_sales_discount', m('sales_discount_desc'))}
                </div>
            </div>

            {/* ── Purchases & AP ────────────────────────────── */}
            <div className="bg-base-50 p-6 rounded-2xl border border-base-200">
                <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
                    <CreditCard size={20} className="text-primary" />
                    {m('section_purchases')}
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {renderAccountSelect(m('accounts_payable'), 'acc_map_ap', m('accounts_payable_desc'))}
                    {renderAccountSelect(m('purchase_expense'), 'acc_map_purchase_exp', m('purchase_expense_desc'))}
                    {renderAccountSelect(m('purchase_discount'), 'acc_map_purchase_discount', m('purchase_discount_desc'))}
                </div>
            </div>

            {/* ── Treasury & Cash ───────────────────────────── */}
            <div className="bg-base-50 p-6 rounded-2xl border border-base-200">
                <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
                    <Landmark size={20} className="text-primary" />
                    {m('section_treasury')}
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {renderAccountSelect(m('main_cash_box'), 'acc_map_cash_main', m('main_cash_box_desc'))}
                    {renderAccountSelect(m('main_bank'), 'acc_map_bank', m('main_bank_desc'))}
                    {renderAccountSelect(m('fx_difference'), 'acc_map_fx_difference', m('fx_difference_desc'))}
                    {renderAccountSelect(m('intercompany_account'), 'acc_map_intercompany', m('intercompany_account_desc'))}
                </div>
            </div>

            {/* ── Inventory ─────────────────────────────────── */}
            <div className="bg-base-50 p-6 rounded-2xl border border-base-200">
                <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
                    <Receipt size={20} className="text-primary" />
                    {m('section_inventory_tax')}
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {renderAccountSelect(m('inventory_account'), 'acc_map_inventory', m('inventory_account_desc'))}
                    {renderAccountSelect(m('inventory_adjustment'), 'acc_map_inventory_adjustment', m('inventory_adjustment_desc'))}
                    {renderAccountSelect(m('vat_output'), 'acc_map_vat_out', m('vat_output_desc'))}
                    {renderAccountSelect(m('vat_input'), 'acc_map_vat_in', m('vat_input_desc'))}
                    {renderAccountSelect(m('withholding_tax_account'), 'acc_map_withholding_tax', m('withholding_tax_account_desc'))}
                </div>
            </div>

            {/* ── Manufacturing ─────────────────────────────── */}
            <div className="bg-base-50 p-6 rounded-2xl border border-base-200">
                <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
                    <Factory size={20} className="text-primary" />
                    {m('section_manufacturing')}
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {renderAccountSelect(m('raw_materials'), 'acc_map_raw_materials', m('raw_materials_desc'))}
                    {renderAccountSelect(m('wip'), 'acc_map_wip', m('wip_desc'))}
                    {renderAccountSelect(m('finished_goods'), 'acc_map_finished_goods', m('finished_goods_desc'))}
                    {renderAccountSelect(m('labor_cost'), 'acc_map_labor_cost', m('labor_cost_desc'))}
                    {renderAccountSelect(m('manufacturing_overhead'), 'acc_map_mfg_overhead', m('manufacturing_overhead_desc'))}
                </div>
            </div>

            {/* ── HR & Payroll ──────────────────────────────── */}
            <div className="bg-base-50 p-6 rounded-2xl border border-base-200">
                <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
                    <Users size={20} className="text-primary" />
                    {m('section_hr_payroll')}
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {renderAccountSelect(m('salaries_expense'), 'acc_map_salaries_exp', m('salaries_expense_desc'))}
                    {renderAccountSelect(m('accrued_salaries'), 'acc_map_accrued_salaries', m('accrued_salaries_desc'))}
                    {renderAccountSelect(m('eosb'), 'acc_map_eosb', m('eosb_desc'))}
                    {renderAccountSelect(m('social_insurance'), 'acc_map_social_insurance', m('social_insurance_desc'))}
                </div>
            </div>

            {/* ── Projects ──────────────────────────────────── */}
            <div className="bg-base-50 p-6 rounded-2xl border border-base-200">
                <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
                    <Briefcase size={20} className="text-primary" />
                    {m('section_projects')}
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {renderAccountSelect(m('project_pl'), 'acc_map_project_pl', m('project_pl_desc'))}
                </div>
            </div>

            {/* ── Fixed Assets ──────────────────────────────── */}
            <div className="bg-base-50 p-6 rounded-2xl border border-base-200">
                <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
                    <ArrowLeftRight size={20} className="text-primary" />
                    {m('section_fixed_assets')}
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {renderAccountSelect(m('fixed_assets_account'), 'acc_map_fixed_assets', m('fixed_assets_account_desc'))}
                    {renderAccountSelect(m('depreciation_expense'), 'acc_map_depreciation_exp', m('depreciation_expense_desc'))}
                    {renderAccountSelect(m('accumulated_depreciation'), 'acc_map_acc_depreciation', m('accumulated_depreciation_desc'))}
                </div>
            </div>

            {/* ── Advanced Accounting Tools ────────────────── */}
            <div className="bg-base-50 p-6 rounded-2xl border border-base-200" style={{ borderColor: 'var(--warning, #f59e0b)', borderWidth: 2 }}>
                <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
                    <RefreshCw size={20} style={{ color: 'var(--warning, #f59e0b)' }} />
                    {m('advanced_tools_title')}
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    {/* FX Revaluation */}
                    <div style={{ background: 'var(--bg-card)', borderRadius: 16, padding: 20, border: '1px solid var(--border-color)' }}>
                        <div style={{ fontWeight: 700, marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
                            💱 {m('fx_revaluation')}
                        </div>
                        <p style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 12 }}>
                            {m('fx_revaluation_desc')}
                        </p>
                        <div className="mb-2">
                            <label style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{t('common.currency', 'Currency')}</label>
                            <input
                                type="text"
                                className="form-input"
                                value={fxCurrencyCode}
                                onChange={e => setFxCurrencyCode(e.target.value.toUpperCase())}
                                maxLength={10}
                                style={{ fontSize: 13 }}
                            />
                        </div>
                        <div className="mb-2">
                            <label style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{t('common.exchange_rate', 'Exchange rate')}</label>
                            <input
                                type="number"
                                className="form-input"
                                value={fxNewRate}
                                onChange={e => setFxNewRate(e.target.value)}
                                min="0"
                                step="0.000001"
                                style={{ fontSize: 13 }}
                            />
                        </div>
                        <button className="btn btn-primary btn-sm btn-block" onClick={handleFxRevaluation} disabled={fxProcessing}>
                            {fxProcessing ? <Spinner size="sm"/> : m('run')}
                        </button>
                    </div>

                    {/* Bad Debt Provision */}
                    <div style={{ background: 'var(--bg-card)', borderRadius: 16, padding: 20, border: '1px solid var(--border-color)' }}>
                        <div style={{ fontWeight: 700, marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
                            ⚠️ {m('bad_debt_provision')}
                        </div>
                        <p style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 12 }}>
                            {m('bad_debt_provision_desc')}
                        </p>
                        <div className="mb-2">
                            <label style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{t('common.amount', 'Amount')}</label>
                            <input
                                type="number"
                                className="form-input"
                                value={badDebtAmount}
                                onChange={e => setBadDebtAmount(e.target.value)}
                                min="0"
                                step="0.01"
                                style={{ fontSize: 13 }}
                            />
                        </div>
                        <button className="btn btn-warning btn-sm btn-block" onClick={handleBadDebtProvision} disabled={badDebtProcessing}>
                            {badDebtProcessing ? <Spinner size="sm"/> : m('create_provision')}
                        </button>
                    </div>

                    {/* Leave Provision */}
                    <div style={{ background: 'var(--bg-card)', borderRadius: 16, padding: 20, border: '1px solid var(--border-color)' }}>
                        <div style={{ fontWeight: 700, marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
                            🏖️ {m('leave_provision')}
                        </div>
                        <p style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 12 }}>
                            {m('leave_provision_desc')}
                        </p>
                        <button className="btn btn-secondary btn-sm btn-block" onClick={handleLeaveProvision} disabled={leaveProvProcessing} style={{ marginTop: 32 }}>
                            {leaveProvProcessing ? <Spinner size="sm"/> : m('create_provision')}
                        </button>
                    </div>
                </div>
            </div>

            <div className="alert alert-info rounded-xl">
                <GitMerge size={20} />
                <div className="text-sm">
                    {m('mapping_warning')}
                </div>
            </div>
        </div>
    );
};

export default AccountingMappingSettings;
