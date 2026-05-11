import { useState, useEffect } from 'react';
import { reportsAPI, salesAPI } from '../../utils/api';
import { getCurrency, hasPermission } from '../../utils/auth';
import { useTranslation } from 'react-i18next';
import CustomDatePicker from '../../components/common/CustomDatePicker';
import { useBranch } from '../../context/BranchContext';
import { useToast } from '../../context/ToastContext';
import { formatNumber } from '../../utils/format';
import { formatDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';

const CustomerStatement = () => {
    const { t } = useTranslation();
    const { showToast } = useToast();
    const [customers, setCustomers] = useState([]);
    const [selectedCustomer, setSelectedCustomer] = useState('');
    const [statement, setStatement] = useState(null);
    const [loading, setLoading] = useState(false);
    const [initialLoad, setInitialLoad] = useState(true);
    const currency = getCurrency();
    const [dates, setDates] = useState({
        start: new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().split('T')[0],
        end: new Date().toISOString().split('T')[0]
    });
    const { currentBranch } = useBranch();

    useEffect(() => {
        const timer = setTimeout(() => {
            salesAPI.listCustomers().then(res => { setCustomers(res.data); setInitialLoad(false); }).catch(() => setInitialLoad(false));
        }, 300)
        return () => clearTimeout(timer)
    }, []);

    const fetchStatement = async () => {
        if (!selectedCustomer) return;
        if (!hasPermission('reports.view') && !hasPermission('sales.reports')) {
            return;
        }
        setLoading(true);
        try {
            const res = await reportsAPI.getCustomerStatement(selectedCustomer, {
                start_date: dates.start,
                end_date: dates.end,
                branch_id: currentBranch ? currentBranch.id : null
            });
            setStatement(res.data);
        } catch (err) {
            showToast(t('common.error'), 'error');
        } finally {
            setLoading(false);
        }
    };

    const selectedCustomerData = customers.find(c => c.id == selectedCustomer);

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">📜 {t('sales.reports.statement.title')}</h1>
                    <p className="workspace-subtitle">{t('sales.reports.statement.subtitle')}</p>
                </div>
            </div>

            {/* Filter Card */}
            <div className="section-card" style={{ marginBottom: '24px' }}>
                <h3 className="section-title">🔍 {t('sales.reports.statement.filters.title')}</h3>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', alignItems: 'end' }}>
                    <div className="form-group">
                        <label className="form-label">{t('sales.reports.statement.filters.customer')} *</label>
                        <select
                            className="form-input"
                            value={selectedCustomer}
                            onChange={e => setSelectedCustomer(e.target.value)}
                        >
                            <option value="">{t('sales.reports.statement.filters.customer_placeholder')}</option>
                            {customers.map(c => (
                                <option key={c.id} value={c.id}>{c.name}</option>
                            ))}
                        </select>
                    </div>
                    <div className="form-group">
                        <CustomDatePicker
                            label={t('sales.reports.statement.filters.from')}
                            selected={dates.start}
                            onChange={(dateStr) => setDates({ ...dates, start: dateStr })}
                        />
                    </div>
                    <div className="form-group">
                        <CustomDatePicker
                            label={t('sales.reports.statement.filters.to')}
                            selected={dates.end}
                            onChange={(dateStr) => setDates({ ...dates, end: dateStr })}
                        />
                    </div>
                    <button
                        className="btn btn-primary"
                        onClick={fetchStatement}
                        disabled={loading || !selectedCustomer}
                        style={{ height: '42px' }}
                    >
                        {loading ? t('sales.reports.statement.filters.loading') : `📄 ${t('sales.reports.statement.filters.view_btn')}`}
                    </button>
                </div>
            </div>

            {/* Statement Results */}
            {statement && (
                <>
                    {/* Balance Summary */}
                    <div className="metrics-grid" style={{ marginBottom: '24px' }}>
                        <div className="metric-card">
                            <div className="metric-label">{t('sales.reports.statement.summary.customer')}</div>
                            <div className="metric-value text-primary" style={{ fontSize: '18px' }}>
                                {selectedCustomerData?.name || '-'}
                            </div>
                        </div>
                        <div className="metric-card">
                            <div className="metric-label">{t('sales.reports.statement.summary.opening_balance')}</div>
                            <div className="metric-value text-secondary">
                                {formatNumber(statement.opening_balance || 0)} {hasPermission('reports.view') && <small>{currency}</small>}
                            </div>
                        </div>
                        <div className="metric-card">
                            <div className="metric-label">{t('sales.reports.statement.summary.closing_balance')}</div>
                            <div className="metric-value" style={{ color: statement.closing_balance > 0 ? 'var(--error)' : 'var(--success)' }}>
                                {formatNumber(statement.closing_balance || 0)} {hasPermission('reports.view') && <small>{currency}</small>}
                            </div>
                        </div>
                    </div>

                    {/* Transactions Table */}
                    <div className="card">
                        <div style={{ padding: '16px', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <h3 style={{ fontWeight: '600', margin: 0 }}>{t('sales.reports.statement.transactions.title')}</h3>
                            <span className="badge" style={{ background: 'var(--bg-secondary)', color: 'var(--text-primary)' }}>
                                {statement.transactions.length} {t('sales.reports.statement.transactions.count')}
                            </span>
                        </div>
                        <div className="data-table-container">
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>{t('sales.reports.statement.table.date')}</th>
                                        <th>{t('sales.reports.statement.table.ref')}</th>
                                        <th>{t('sales.reports.statement.table.type')}</th>
                                        <th>{t('sales.reports.statement.table.debit')}</th>
                                        <th>{t('sales.reports.statement.table.credit')}</th>
                                        <th>{t('sales.reports.statement.table.balance')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {statement.transactions.length === 0 && (
                                        <tr>
                                            <td colSpan="6" className="text-center py-5 text-muted">
                                                {t('sales.reports.statement.empty_table')}
                                            </td>
                                        </tr>
                                    )}
                                    {statement.transactions.map((t_item, idx) => (
                                        <tr key={idx}>
                                            <td>{formatDate(t_item.date)}</td>
                                            <td className="font-medium text-primary">{t_item.ref}</td>
                                            <td>
                                                <span className={`badge ${t_item.type === 'invoice' ? 'badge-warning' : 'badge-success'}`}>
                                                    {t_item.type === 'invoice' ? t('sales.reports.statement.types.invoice') : t('sales.reports.statement.types.payment')}
                                                </span>
                                            </td>
                                            <td style={{ color: 'var(--error)', fontWeight: t_item.debit > 0 ? '600' : '400' }}>
                                                {(t_item.debit > 0 ? formatNumber(t_item.debit) : '-')}
                                            </td>
                                            <td style={{ color: 'var(--success)', fontWeight: t_item.credit > 0 ? '600' : '400' }}>
                                                {(t_item.credit > 0 ? formatNumber(t_item.credit) : '-')}
                                            </td>
                                            <td className="font-medium">{formatNumber(t_item.balance)}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </>
            )}

            {/* Empty State */}
            {!statement && !loading && (
                <div className="section-card" style={{ textAlign: 'center', padding: '48px' }}>
                    <div style={{ fontSize: '48px', marginBottom: '16px', opacity: 0.3 }}>📋</div>
                    <h3 style={{ fontWeight: '600', marginBottom: '8px', color: 'var(--text-secondary)' }}>{t('sales.reports.statement.filters.select_hint_title')}</h3>
                    <p className="text-muted">{t('sales.reports.statement.filters.select_hint_desc')}</p>
                </div>
            )}
        </div>
    );
};

export default CustomerStatement;
