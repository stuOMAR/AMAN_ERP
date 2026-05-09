import { useState, useEffect, useMemo } from 'react';
import { expensesAPI } from '../../utils/api';
import { useToast } from '../../context/ToastContext';
import { useBranch } from '../../context/BranchContext';
import { Plus, Receipt, Search, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { formatNumber } from '../../utils/format';
import { getCurrency } from '../../utils/auth';
import CustomDatePicker from '../../components/common/CustomDatePicker';
import { formatShortDate } from '../../utils/dateUtils';
import DataTable from '../../components/common/DataTable';
import BackButton from '../../components/common/BackButton';


export default function ExpenseList() {
  const { t, i18n } = useTranslation();
  const { showToast } = useToast();
  const navigate = useNavigate();
  const { currentBranch, loading: branchLoading } = useBranch();
  const isRTL = i18n.language === 'ar';
  const currency = getCurrency() || '';

  const [expenses, setExpenses] = useState([]);
  const [summary, setSummary] = useState({});
  const [loading, setLoading] = useState(true);
  const [initialLoad, setInitialLoad] = useState(true);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [filters, setFilters] = useState({
    expense_type: '',
    approval_status: '',
    start_date: '',
    end_date: ''
  });

  useEffect(() => {
    if (!branchLoading) {
      const timer = setTimeout(() => {
        loadData()
      }, 300)
      return () => clearTimeout(timer)
    }
  }, [currentBranch, branchLoading, filters]);

  const loadData = async () => {
    try {
      setLoading(true);
      const params = { ...filters };
      if (currentBranch) params.branch_id = currentBranch.id;
      if (statusFilter) params.approval_status = statusFilter;
      if (typeFilter) params.expense_type = typeFilter;

      const [expensesRes, summaryRes] = await Promise.all([
        expensesAPI.list(params),
        expensesAPI.summary(params)
      ]);
      setExpenses(expensesRes.data || []);
      setSummary(summaryRes.data || []);
    } catch (error) {
      showToast(t('expenses.errors.loadFailed'), 'error');
    } finally {
      setLoading(false);
      setInitialLoad(false);
    }
  };

  const getStatusBadge = (status) => {
    const styles = {
      pending: { bg: '#fef3c7', color: '#d97706', icon: '\u23F3' },
      approved: { bg: '#dcfce7', color: '#16a34a', icon: '\u2705' },
      rejected: { bg: '#fee2e2', color: '#dc2626', icon: '\u274C' }
    };
    const s = styles[status] || styles.pending;
    return (
      <span style={{ background: s.bg, color: s.color, padding: '4px 12px', borderRadius: '20px', fontSize: '12px', fontWeight: '600', whiteSpace: 'nowrap' }}>
        {s.icon} {t(`expenses.status.${status}`)}
      </span>
    );
  };

  const getTypeBadge = (type) => {
    const colors = {
      materials: '#3b82f6', labor: '#8b5cf6', services: '#06b6d4',
      travel: '#f59e0b', rent: '#ec4899', utilities: '#10b981',
      salaries: '#6366f1', other: '#6b7280'
    };
    const color = colors[type] || '#6b7280';
    return (
      <span style={{ background: `${color}15`, color, padding: '4px 10px', borderRadius: '6px', fontSize: '12px', fontWeight: '600' }}>
        {t(`expenses.types.${type}`, type)}
      </span>
    );
  };

  const filteredExpenses = useMemo(() => {
    let result = expenses;
    if (search) {
      const q = search.toLowerCase();
      result = result.filter(exp =>
        (exp.expense_number || '').toLowerCase().includes(q) ||
        (exp.description || '').toLowerCase().includes(q) ||
        (exp.vendor_name || '').toLowerCase().includes(q)
      );
    }
    return result;
  }, [expenses, search]);

  const columns = [
    {
      key: 'expense_number',
      label: t('expenses.fields.number'),
      render: (val) => (
        <span style={{ fontWeight: 'bold', color: 'var(--primary)' }}>{val}</span>
      ),
    },
    {
      key: 'expense_date',
      label: t('expenses.fields.date'),
      render: (val) => <span style={{ whiteSpace: 'nowrap' }}>{formatShortDate(val)}</span>,
    },
    {
      key: 'expense_type',
      label: t('expenses.fields.type'),
      render: (val) => getTypeBadge(val),
    },
    {
      key: 'vendor_name',
      label: t('expenses.fields.vendor'),
      render: (val) => val || <span className="text-muted">{'\u2014'}</span>,
    },
    {
      key: 'description',
      label: t('expenses.fields.description'),
      render: (val) => (
        <div className="text-truncate" style={{ maxWidth: '180px' }}>
          {val || <span className="text-muted">{'\u2014'}</span>}
        </div>
      ),
    },
    {
      key: 'amount',
      label: t('expenses.fields.amount'),
      style: { textAlign: isRTL ? 'left' : 'right', fontWeight: '700', whiteSpace: 'nowrap' },
      headerStyle: { textAlign: isRTL ? 'left' : 'right' },
      render: (val) => (
        <>{formatNumber(val)} <span className="text-muted fw-normal small">{currency}</span></>
      ),
    },
    {
      key: 'approval_status',
      label: t('expenses.fields.status'),
      render: (val) => getStatusBadge(val),
    },
    {
      key: '_actions',
      label: t('common.actions'),
      render: (_, row) => (
        <button
          className="btn btn-sm btn-outline-primary"
          onClick={(e) => { e.stopPropagation(); navigate(`/expenses/${row.id}`); }}
          style={{ borderRadius: '8px', fontSize: '12px' }}
        >
          {t('common.view')}
        </button>
      ),
    },
  ];

  return (
    <div className="workspace fade-in">
      {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
      {/* Header */}
      <div className="workspace-header">
        <BackButton />
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <div style={{ background: 'linear-gradient(135deg, #f43f5e 0%, #e11d48 100%)', width: '42px', height: '42px', borderRadius: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Receipt size={22} color="#fff" />
            </div>
            <div>
              <h1 className="workspace-title">{t('expenses.title')}</h1>
              <p className="text-muted small mb-0">{t('expenses.subtitle')}</p>
            </div>
          </div>
          <button className="btn btn-primary d-flex align-items-center gap-2" onClick={() => navigate('/expenses/new')}>
            <Plus size={18} />
            {t('expenses.addNew')}
          </button>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="metrics-grid mb-4">
        <div className="metric-card">
          <div className="metric-label">{t('expenses.metrics.total')}</div>
          <div className="metric-value text-primary">
            {formatNumber(summary.total_amount || 0)} <small>{currency}</small>
          </div>
          <div className="metric-change text-muted">{summary.total_expenses || 0} {t('expenses.metrics.totalLabel')}</div>
        </div>

        <div className="metric-card">
          <div className="metric-label">{t('expenses.metrics.pending')}</div>
          <div className="metric-value text-warning">
            {formatNumber(summary.pending_amount || 0)} <small>{currency}</small>
          </div>
          <div className="metric-change text-muted">{summary.pending_approval || 0} {t('expenses.metrics.pendingCount')}</div>
        </div>

        <div className="metric-card">
          <div className="metric-label">{t('expenses.metrics.approved')}</div>
          <div className="metric-value text-success">
            {formatNumber(summary.approved_amount || 0)} <small>{currency}</small>
          </div>
          <div className="metric-change text-muted">{summary.approved || 0} {t('expenses.metrics.approvedCount')}</div>
        </div>

        <div className="metric-card">
          <div className="metric-label">{t('expenses.metrics.rejected')}</div>
          <div className="metric-value text-danger">
            {summary.rejected || 0}
          </div>
        </div>
      </div>

      {/* Quick Navigation Cards - Only Status Summary is kept */}
      <div className="modules-grid" style={{ gap: '16px', marginBottom: '16px' }}>
        {/* Status Summary */}
        <div className="card">
          <h3 className="section-title" style={{ display: 'flex', alignItems: 'center', gap: '8px', margin: 0 }}>
            {'\uD83D\uDCCA'} {t('expenses.status_summary', '\u0645\u0644\u062E\u0635 \u0627\u0644\u062D\u0627\u0644\u0629')}
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px', marginTop: '12px' }}>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '2px' }}>{t('expenses.status.pending')}</div>
              <div style={{ fontSize: '20px', fontWeight: '700', color: '#d97706' }}>{summary.pending_approval || 0}</div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '2px' }}>{t('expenses.status.approved')}</div>
              <div style={{ fontSize: '20px', fontWeight: '700', color: '#16a34a' }}>{summary.approved || 0}</div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '2px' }}>{t('expenses.status.rejected')}</div>
              <div style={{ fontSize: '20px', fontWeight: '700', color: '#dc2626' }}>{summary.rejected || 0}</div>
            </div>
          </div>
        </div>
      </div>

      {/* Main Consolidated Filter Section */}
      <div className="card mb-4" style={{ paddingBottom: '16px' }}>
        <h3 className="section-title" style={{ display: 'flex', alignItems: 'center', gap: '8px', margin: '0 0 16px 0' }}>
          {'\uD83D\uDD0D'} {t('common.filter', '\u062A\u0635\u0641\u064A\u0629')}
        </h3>
        
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* Top Row: Search and Text Filters */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
            {/* Search */}
            <div style={{ position: 'relative', flex: '2 1 300px', minWidth: '250px' }}>
              <Search size={16} style={{ position: 'absolute', right: isRTL ? '12px' : 'auto', left: isRTL ? 'auto' : '12px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)', pointerEvents: 'none' }} />
              <input
                type="text"
                className="form-input w-full"
                placeholder={t('expenses.searchPlaceholder', '\u0628\u062D\u062B \u0628\u0631\u0642\u0645 \u0627\u0644\u0645\u0635\u0631\u0648\u0641...')}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                style={isRTL ? { paddingRight: '36px' } : { paddingLeft: '36px' }}
              />
              {search && (
                <button
                  onClick={() => setSearch('')}
                  style={{ position: 'absolute', left: isRTL ? '12px' : 'auto', right: isRTL ? 'auto' : '12px', top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)', padding: '2px' }}
                >
                  <X size={14} />
                </button>
              )}
            </div>

            {/* Type Dropdown */}
            <select className="form-input" style={{ flex: '1 1 200px', minWidth: '150px' }} value={typeFilter} onChange={(e) => { setTypeFilter(e.target.value); setFilters(prev => ({...prev, expense_type: e.target.value})); }}>
              <option value="">{t('expenses.fields.type', '\u0646\u0648\u0639 \u0627\u0644\u0645\u0635\u0631\u0648\u0641')}</option>
              <option value="materials">{t('expenses.types.materials')}</option>
              <option value="labor">{t('expenses.types.labor')}</option>
              <option value="services">{t('expenses.types.services')}</option>
              <option value="travel">{t('expenses.types.travel')}</option>
              <option value="rent">{t('expenses.types.rent')}</option>
              <option value="utilities">{t('expenses.types.utilities')}</option>
              <option value="salaries">{t('expenses.types.salaries')}</option>
              <option value="other">{t('expenses.types.other')}</option>
            </select>

            {/* Status Dropdown */}
            <select className="form-input" style={{ flex: '1 1 200px', minWidth: '150px' }} value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setFilters(prev => ({...prev, approval_status: e.target.value})); }}>
              <option value="">{t('expenses.fields.status', '\u0627\u0644\u062D\u0627\u0644\u0629')}</option>
              <option value="pending">{t('expenses.status.pending')}</option>
              <option value="approved">{t('expenses.status.approved')}</option>
              <option value="rejected">{t('expenses.status.rejected')}</option>
            </select>
          </div>

          {/* Bottom Row: Dates and Actions */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
            {/* Start Date */}
            <div style={{ flex: '1 1 180px', minWidth: '140px', maxWidth: '250px' }}>
              <CustomDatePicker
                selected={filters.start_date}
                onChange={(val) => setFilters({ ...filters, start_date: val })}
                placeholder={t('common.start_date', '\u062A\u0627\u0631\u064A\u062E \u0627\u0644\u0628\u062F\u0621')}
                isClearable
              />
            </div>

            {/* End Date */}
            <div style={{ flex: '1 1 180px', minWidth: '140px', maxWidth: '250px' }}>
              <CustomDatePicker
                selected={filters.end_date}
                onChange={(val) => setFilters({ ...filters, end_date: val })}
                placeholder={t('common.end_date', '\u062A\u0627\u0631\u064A\u062E \u0627\u0644\u0627\u0646\u062A\u0647\u0627\u0621')}
                isClearable
              />
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flex: '1 1 auto', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
              {/* Quick Buttons */}
              <button className="btn btn-outline" onClick={() => { setFilters({ expense_type: '', approval_status: '', start_date: '', end_date: '' }); setSearch(''); setStatusFilter(''); setTypeFilter(''); }} style={{ fontSize: '13px', padding: '9px 8px', whiteSpace: 'nowrap' }}>
                {'\u2715'} {t('common.clear_filters', '\u0645\u0633\u062D \u0627\u0644\u0641\u0644\u0627\u062A\u0631')}
              </button>
              
              <button className="btn btn-outline" onClick={() => { setStatusFilter('approved'); setFilters({ ...filters, approval_status: 'approved' }); }} style={{ fontSize: '13px', padding: '9px 8px', whiteSpace: 'nowrap' }}>
                {'\u2705'} {t('expenses.status.approved', '\u0645\u0648\u0627\u0641\u0642 \u0639\u0644\u064A\u0647')}
              </button>

              <button className="btn btn-primary btn-sm" style={{ height: '38px', whiteSpace: 'nowrap', padding: '0 20px' }} onClick={loadData}>
                {t('common.filter', '\u062A\u0635\u0641\u064A\u0629')}
              </button>
            </div>
          </div>
        </div>
      </div>

      <DataTable
        columns={columns}
        data={filteredExpenses}
        loading={loading}
        onRowClick={(row) => navigate(`/expenses/${row.id}`)}
        emptyIcon={'\uD83D\uDCCB'}
        emptyTitle={t('expenses.noExpenses')}
        emptyAction={{ label: t('expenses.addNew'), onClick: () => navigate('/expenses/new') }}
      />
    </div>
  );
}
