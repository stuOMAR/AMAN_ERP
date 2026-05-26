import { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Plus, Landmark, Trash2, CheckCircle, Clock } from 'lucide-react';
import { treasuryAPI, reconciliationAPI } from '../../utils/api';
import { useBranch } from '../../context/BranchContext';
import { getCurrency } from '../../utils/auth';
import { toastEmitter } from '../../utils/toastEmitter';
import BackButton from '../../components/common/BackButton';
import DataTable from '../../components/common/DataTable';
import SearchFilter from '../../components/common/SearchFilter';
import { formatNumber } from '../../utils/format';

const ReconciliationList = () => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const { currentBranch } = useBranch();
    const currency = getCurrency();

    const [accounts, setAccounts] = useState([]);
    const [selectedAccount, setSelectedAccount] = useState('');
    const [reconciliations, setReconciliations] = useState([]);
    const [loading, setLoading] = useState(false);
    const [initialLoad, setInitialLoad] = useState(true);
    const [search, setSearch] = useState('');
    const [statusFilter, setStatusFilter] = useState('');

    useEffect(() => {
        const fetchAccounts = async () => {
            try {
                const branchId = currentBranch?.id || null;
                const res = await treasuryAPI.listAccounts(branchId);
                const banks = res.data.filter(a => a.account_type === 'bank');
                setAccounts(banks);
                if (banks.length > 0 && !selectedAccount) setSelectedAccount(String(banks[0].id));
            } catch (error) {
                console.error("Failed to fetch accounts", error);
            }
        };
        fetchAccounts();
    }, [currentBranch]);

    useEffect(() => {
        if (selectedAccount) {
            const timer = setTimeout(() => {
                fetchReconciliations(selectedAccount);
            }, 300)
            return () => clearTimeout(timer);
        }
    }, [selectedAccount, currentBranch]);

    const fetchReconciliations = async (accountId) => {
        try {
            setLoading(true);
            const res = await reconciliationAPI.list({ account_id: accountId });
            setReconciliations(res.data);
        } catch (error) {
            console.error("Failed to fetch reconciliations", error);
        } finally {
            setLoading(false);
            setInitialLoad(false);
        }
    };

    const handleDelete = async (e, recId) => {
        e.stopPropagation();
        if (!window.confirm(t('common.confirm_delete'))) return;
        try {
            await reconciliationAPI.delete(recId);
            toastEmitter.emit(t('common.deleted_successfully'), 'success');
            fetchReconciliations(selectedAccount);
        } catch (error) {
            toastEmitter.emit(error.response?.data?.detail || t('common.error'), 'error');
        }
    };

    const getProgressBar = (row) => {
        const matched = row.matched_count || 0;
        const total = row.total_lines || 0;
        if (total === 0) return null;
        const pct = row.progress_pct ?? 0;
        const isComplete = row.progress_status === 'complete' || row.is_fully_matched === true;
        return (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <div style={{
                    width: '80px', height: '6px', borderRadius: '3px',
                    backgroundColor: 'var(--border-color)', overflow: 'hidden'
                }}>
                    <div style={{
                        width: `${pct}%`, height: '100%', borderRadius: '3px',
                        backgroundColor: isComplete ? 'var(--success)' : 'var(--primary)',
                        transition: 'width 0.3s ease'
                    }} />
                </div>
                <span className="small text-muted">{matched}/{total}</span>
            </div>
        );
    };

    const filteredReconciliations = useMemo(() => {
        let result = reconciliations;
        if (search) {
            const q = search.toLowerCase();
            result = result.filter(rec =>
                (rec.statement_date || '').toLowerCase().includes(q) ||
                (rec.created_by_name || '').toLowerCase().includes(q)
            );
        }
        if (statusFilter) {
            result = result.filter(rec => rec.status === statusFilter);
        }
        return result;
    }, [reconciliations, search, statusFilter]);

    const columns = [
        {
            key: '_index',
            label: '#',
            render: (_, row) => {
                const idx = filteredReconciliations.indexOf(row);
                return <span className="text-muted small">{idx + 1}</span>;
            },
        },
        {
            key: 'statement_date',
            label: t('common.date'),
            style: { fontWeight: 'bold', color: 'var(--text-dark)' },
        },
        {
            key: 'status',
            label: t('treasury.reconciliation.status'),
            render: (val) => (
                <span className={`badge ${val === 'posted' ? 'badge-success' : 'badge-warning'}`}
                      style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                    {val === 'posted'
                        ? <><CheckCircle size={12} /> {t('treasury.reconciliation.status_posted')}</>
                        : <><Clock size={12} /> {t('treasury.reconciliation.status_draft')}</>
                    }
                </span>
            ),
        },
        {
            key: 'start_balance',
            label: t('treasury.reconciliation.start_bal'),
            render: (val) => <span className="font-monospace fw-bold">{formatNumber(val || '0')} <small>{currency}</small></span>,
        },
        {
            key: 'end_balance',
            label: t('treasury.reconciliation.end_bal'),
            render: (val) => <span className="font-monospace fw-bold">{formatNumber(val || '0')} <small>{currency}</small></span>,
        },
        {
            key: 'matched_count',
            label: t('treasury.reconciliation.progress'),
            render: (_, row) => getProgressBar(row),
        },
        {
            key: 'created_by_name',
            label: t('common.created_by'),
            render: (val) => <span className="small text-muted">{val || 'Admin'}</span>,
        },
        {
            key: '_actions',
            label: '',
            width: 60,
            render: (_, row) => (
                row.status === 'draft' ? (
                    <button
                        className="btn btn-link text-danger p-0"
                        onClick={(e) => handleDelete(e, row.id)}
                        title={t('common.delete')}
                    >
                        <Trash2 size={16} />
                    </button>
                ) : null
            ),
        },
    ];

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div className="d-flex justify-content-between align-items-center">
                    <div>
                        <h1 className="workspace-title">{t('treasury.reconciliation.title')}</h1>
                        <p className="workspace-subtitle">{t('treasury.reconciliation.subtitle')}</p>
                    </div>
                    <button
                        className="btn btn-primary d-flex align-items-center gap-2"
                        onClick={() => navigate('/treasury/reconciliation/new')}
                    >
                        <Plus size={18} />
                        {t('treasury.reconciliation.new')}
                    </button>
                </div>
            </div>

            <div className="card mb-4 p-4">
                <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                    <div style={{
                        width: '40px', height: '40px', borderRadius: '10px',
                        backgroundColor: 'var(--bg-hover)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        color: 'var(--primary)'
                    }}>
                        <Landmark size={20} />
                    </div>
                    <div style={{ flex: 1, maxWidth: '400px' }}>
                        <select
                            className="form-input"
                            value={selectedAccount}
                            onChange={(e) => setSelectedAccount(e.target.value)}
                        >
                            <option value="">{t('treasury.reconciliation.select_account')}</option>
                            {accounts.map(acc => (
                                <option key={acc.id} value={String(acc.id)}>{acc.name} ({acc.currency})</option>
                            ))}
                        </select>
                    </div>
                </div>
            </div>

            <SearchFilter
                value={search}
                onChange={setSearch}
                placeholder={t('common.search')}
                filters={[{
                    key: 'status',
                    label: t('treasury.reconciliation.status'),
                    options: [
                        { value: 'draft', label: t('treasury.reconciliation.status_draft') },
                        { value: 'posted', label: t('treasury.reconciliation.status_posted') },
                    ],
                }]}
                filterValues={{ status: statusFilter }}
                onFilterChange={(_key, val) => setStatusFilter(val)}
            />

            <DataTable
                columns={columns}
                data={filteredReconciliations}
                loading={initialLoad}
                onRowClick={(row) => navigate(`/treasury/reconciliation/${row.id}`)}
                emptyIcon="📑"
                emptyTitle={t('common.no_data')}
                emptyAction={{ label: t('treasury.reconciliation.new'), onClick: () => navigate('/treasury/reconciliation/new') }}
            />
        </div>
    );
};

export default ReconciliationList;
