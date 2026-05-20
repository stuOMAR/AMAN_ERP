import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Save, Search, AlertTriangle, Lock } from 'lucide-react';
import { useParams } from 'react-router-dom';
import { useToast } from '../../context/ToastContext';
import { useBranch } from '../../context/BranchContext';
import { budgetsAPI, accountingAPI } from '../../utils/api';
import { getCurrency, hasPermission } from '../../utils/auth';
import BackButton from '../../components/common/BackButton';
import { Spinner } from '../../components/common/LoadingStates'

const BudgetItems = () => {
    const { t } = useTranslation();
    const { showToast } = useToast();
    const { id } = useParams();

    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [accounts, setAccounts] = useState([]);
    const [budgetItems, setBudgetItems] = useState({});
    const [budgetMonths, setBudgetMonths] = useState(12);
    const [searchTerm, setSearchTerm] = useState('');
    const [saving, setSaving] = useState(false);
    const [budgetBranchId, setBudgetBranchId] = useState(null);
    const [budgetBranchName, setBudgetBranchName] = useState('');
    const [budgetCurrency, setBudgetCurrency] = useState('');
    const currency = getCurrency() || '';
    const { currentBranch, branches, setBranch } = useBranch();
    const canManageBudgets = hasPermission('accounting.budgets.manage');
    const permissionDenied = () => showToast(t('common.permission_denied', 'ليس لديك صلاحية تنفيذ هذا الإجراء'), 'error');

    // Lock branch to budget's branch - warn if user tries to switch
    useEffect(() => {
        if (budgetBranchId && currentBranch?.id && currentBranch.id !== budgetBranchId) {
            showToast(`⚠️ لا يمكن تغيير الفرع أثناء تعديل بنود الميزانية. هذه الميزانية خاصة بفرع: ${budgetBranchName}`, 'error');
            // Force back to budget's branch
            if (branches?.length) {
                const budgetBranch = branches.find(b => b.id === budgetBranchId);
                if (budgetBranch) {
                    setBranch(budgetBranch);
                }
            }
        }
    }, [currentBranch, budgetBranchId]);

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchData();
        }, 300)
        return () => clearTimeout(timer)
    }, [id, currentBranch]);

    const countMonths = (start, end) => {
        const s = new Date(start);
        const e = new Date(end);
        return (e.getFullYear() - s.getFullYear()) * 12 + (e.getMonth() - s.getMonth()) + 1;
    };

    const fetchData = async () => {
        setLoading(true);
        try {
            // Fetch budget details to get duration and branch
            const budgetRes = await budgetsAPI.get(id);
            const budget = budgetRes.data;
            if (budget?.start_date && budget?.end_date) {
                setBudgetMonths(countMonths(budget.start_date, budget.end_date));
            }
            if (budget?.branch_id) {
                setBudgetBranchId(budget.branch_id);
                // Find branch name from branches list
                const branch = branches?.find(b => b.id === budget.branch_id);
                if (branch) {
                    setBudgetBranchName(branch.branch_name || branch.name);
                    setBudgetCurrency(branch.default_currency || currency);
                }
            }

            // Fetch Accounts (company-wide for budget purposes - skip branch scope)
            const accountsRes = await accountingAPI.list({}, { skipBranchScope: true });
            const allAccounts = accountsRes.data || [];
            const budgetableAccounts = allAccounts.filter(a => ['expense', 'revenue', 'asset'].includes(a.account_type));
            setAccounts(budgetableAccounts);

            // Fetch Existing Items via getItems endpoint
            const itemsRes = await budgetsAPI.getItems(id);
            const itemsMap = {};
            (itemsRes.data || []).forEach(item => {
                itemsMap[item.account_id] = {
                    planned: item.planned_amount,
                    notes: item.notes || ''
                };
            });
            setBudgetItems(itemsMap);

        } catch (error) {
            console.error(error);
            showToast(t('common.error_loading'), 'error');
        } finally {
            setLoading(false);
            setInitialLoad(false);
        }
    };

    const handleAmountChange = (accountId, field, value) => {
        if (!canManageBudgets) return;
        const floatValue = parseFloat(value) || 0;
        setBudgetItems(prev => {
            const currentItem = prev[accountId] || { planned: 0, notes: '' };
            if (field === 'monthly') {
                return {
                    ...prev,
                    [accountId]: {
                        ...currentItem,
                        planned: floatValue * budgetMonths,
                        monthly: floatValue
                    }
                };
            } else {
                return {
                    ...prev,
                    [accountId]: {
                        ...currentItem,
                        planned: floatValue,
                        monthly: floatValue / budgetMonths
                    }
                };
            }
        });
    };

    const handleSave = async () => {
        if (!canManageBudgets) {
            permissionDenied();
            return;
        }
        // Prevent saving if branch doesn't match budget's branch
        if (budgetBranchId && currentBranch?.id && currentBranch.id !== budgetBranchId) {
            showToast(`⚠️ لا يمكن الحفظ! هذه الميزانية خاصة بفرع ${budgetBranchName}. يرجى التبديل لفرع ${budgetBranchName} أولاً.`, 'error');
            return;
        }
        setSaving(true);
        try {
            const items = Object.entries(budgetItems)
                .filter(([_, val]) => val.planned > 0)
                .map(([accountId, val]) => ({
                    account_id: parseInt(accountId),
                    planned_amount: val.planned,
                    notes: val.notes || ''
                }));

            if (items.length === 0) {
                showToast(t('accounting.budgets.no_items'), 'error');
                return;
            }

            await budgetsAPI.setItems(id, items);
            showToast(t('accounting.budgets.items_saved'), 'success');
        } catch (error) {
            console.error(error);
            showToast(t('common.error_saving'), 'error');
        } finally {
            setSaving(false);
        }
    };

    const filteredAccounts = accounts.filter(acc =>
        acc.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        acc.account_number.includes(searchTerm)
    );

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header mb-4">
                <div className="d-flex align-items-center gap-3">
                        <BackButton />
                    <div>
                        <h1 className="workspace-title mb-0">{t('accounting.budgets.items', 'Budget Items')}</h1>
                        {budgetBranchId && (
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '4px' }}>
                                <Lock size={12} style={{ color: 'var(--primary)' }} />
                                <span style={{ fontSize: '12px', color: 'var(--primary)', fontWeight: 600 }}>
                                    فرع: {budgetBranchName} ({budgetCurrency})
                                </span>
                            </div>
                        )}
                    </div>
                </div>
                <div className="header-actions">
                    <button onClick={handleSave} className="btn btn-primary shadow-sm" disabled={saving || !canManageBudgets}>
                        <Save size={18} className="me-2" />
                        {saving ? t('common.saving') : t('common.save')}
                    </button>
                </div>
            </div>

            {/* Branch lock warning */}
            {budgetBranchId && currentBranch?.id && currentBranch.id !== budgetBranchId && (
                <div style={{ 
                    display: 'flex', alignItems: 'center', gap: '10px', padding: '12px 16px', 
                    background: '#fef2f2', border: '1px solid #fecaca', borderRadius: '8px', 
                    marginBottom: '16px', fontSize: '13px', color: '#dc2626' 
                }}>
                    <AlertTriangle size={18} />
                    <div>
                        <strong>تحذير:</strong> هذه الميزانية خاصة بفرع <strong>{budgetBranchName}</strong>. 
                        لا يمكن حفظ البنود على فرع آخر. يرجى العودة لفرع {budgetBranchName} أولاً.
                    </div>
                </div>
            )}

            <div className="card card-flush shadow-sm">
                <div className="card-header border-0 pt-4 pb-2">
                    <div className="search-box w-100 max-w-400px">
                        <div className="input-group input-group-solid">
                            <span className="input-group-text"><Search size={18} className="text-gray-500" /></span>
                            <input
                                type="text"
                                className="form-input"
                                placeholder={t('common.search')}
                                value={searchTerm}
                                onChange={(e) => setSearchTerm(e.target.value)}
                                autoComplete="off"
                            />
                        </div>
                    </div>
                </div>
                <div className="card-body p-0">
                    <div className="data-table-container">
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th className="ps-4">{t('accounting.account_number')}</th>
                                    <th>{t('accounting.account_name')}</th>
                                    <th>{t('accounting.account_type')}</th>
                                    <th width="180" className="text-center">{t('accounting.budgets.monthly_amount', 'Monthly Amount')} <span className="text-muted small">({currency})</span></th>
                                    <th width="180" className="text-center">{t('accounting.budgets.planned_amount', 'Annual Amount')} <span className="text-muted small">({currency})</span></th>
                                </tr>
                            </thead>
                            <tbody>
                                {loading ? (
                                    <tr><td colSpan="5" className="text-center p-8">
                                        <Spinner size="sm"/>
                                        {t('common.loading')}
                                    </td></tr>
                                ) : filteredAccounts.length === 0 ? (
                                    <tr><td colSpan="5" className="text-center p-8 text-muted">{t('common.no_data')}</td></tr>
                                ) : (
                                    filteredAccounts.map((acc) => (
                                        <tr key={acc.id}>
                                            <td className="ps-4">
                                                <code className="text-primary fw-medium">{acc.account_number}</code>
                                            </td>
                                            <td>
                                                <div className="fw-bold text-gray-800">{acc.name}</div>
                                            </td>
                                            <td>
                                                <span className={`badge badge-light-${acc.account_type === 'expense' ? 'danger' : acc.account_type === 'revenue' ? 'success' : 'primary'} fw-bold`}>
                                                    {t(`accounting.coa.types.${acc.account_type}`) || acc.account_type}
                                                </span>
                                            </td>
                                            <td>
                                                <div className="input-group input-group-sm input-group-solid">
                                                    <input
                                                        type="number"
                                                        className="form-input text-center"
                                                        value={budgetItems[acc.id]?.monthly || (budgetItems[acc.id]?.planned / budgetMonths) || ''}
                                                        onChange={(e) => handleAmountChange(acc.id, 'monthly', e.target.value)}
                                                        placeholder="0.00"
                                                        autoComplete="off"
                                                        disabled={!canManageBudgets}
                                                    />
                                                </div>
                                            </td>
                                            <td>
                                                <div className="input-group input-group-sm input-group-solid">
                                                    <input
                                                        type="number"
                                                        className="form-input text-center fw-bold text-primary"
                                                        value={budgetItems[acc.id]?.planned || ''}
                                                        onChange={(e) => handleAmountChange(acc.id, 'annual', e.target.value)}
                                                        placeholder="0.00"
                                                        autoComplete="off"
                                                        disabled={!canManageBudgets}
                                                    />
                                                </div>
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

export default BudgetItems;
