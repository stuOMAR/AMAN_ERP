import { useState, useEffect } from 'react';
import { reportsAPI, inventoryAPI } from '../../utils/api';
import { getCurrency, hasPermission } from '../../utils/auth';
import { useTranslation } from 'react-i18next';
import CustomDatePicker from '../../components/common/CustomDatePicker';
import { useBranch } from '../../context/BranchContext';
import { useToast } from '../../context/ToastContext';
import { formatDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';

const SupplierStatement = () => {
    const { t } = useTranslation();
    const [suppliers, setSuppliers] = useState([]);
    const [selectedSupplier, setSelectedSupplier] = useState('');
    const [statement, setStatement] = useState(null);
    const [loading, setLoading] = useState(false);
    const [initialLoad, setInitialLoad] = useState(true);
    const baseCurrency = getCurrency();
    const [dates, setDates] = useState({
        start: new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().split('T')[0],
        end: new Date().toISOString().split('T')[0]
    });
    const { currentBranch } = useBranch();
    const { showToast } = useToast();

    useEffect(() => {
        inventoryAPI.listSuppliers().then(res => setSuppliers(res.data));
    }, []);

    const fetchStatement = async () => {
        if (!selectedSupplier) return;
        if (!hasPermission('reports.view') && !hasPermission('buying.reports')) {
            return;
        }
        setLoading(true);
        try {
            const res = await reportsAPI.getSupplierStatement(selectedSupplier, {
                start_date: dates.start,
                end_date: dates.end,
                branch_id: currentBranch ? currentBranch.id : null
            });
            setStatement(res.data);
        } catch (err) {
            showToast(t('common.error'), 'error');
        } finally {
            setLoading(false);
            setInitialLoad(false);
        }
    };

    const selectedSupplierData = suppliers.find(s => s.id == selectedSupplier);

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">📜 {t('buying.reports.statement.title')}</h1>
                    <p className="workspace-subtitle">{t('buying.reports.statement.subtitle')}</p>
                </div>
            </div>

            {/* Filter Card */}
            <div className="section-card" style={{ marginBottom: '24px' }}>
                <h3 className="section-title">🔍 {t('buying.reports.statement.filters.title')}</h3>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', alignItems: 'end' }}>
                    <div className="form-group">
                        <label className="form-label">{t('buying.reports.statement.filters.supplier')} *</label>
                        <select
                            className="form-input"
                            value={selectedSupplier}
                            onChange={e => setSelectedSupplier(e.target.value)}
                        >
                            <option value="">{t('buying.reports.statement.filters.supplier_placeholder')}</option>
                            {suppliers.map(s => (
                                <option key={s.id} value={s.id}>{s.name}</option>
                            ))}
                        </select>
                    </div>
                    <div className="form-group">
                        <CustomDatePicker
                            label={t('buying.reports.statement.filters.start_date')}
                            selected={dates.start}
                            onChange={(dateStr) => setDates({ ...dates, start: dateStr })}
                        />
                    </div>
                    <div className="form-group">
                        <CustomDatePicker
                            label={t('buying.reports.statement.filters.end_date')}
                            selected={dates.end}
                            onChange={(dateStr) => setDates({ ...dates, end: dateStr })}
                        />
                    </div>
                    <button
                        className="btn btn-primary"
                        onClick={fetchStatement}
                        disabled={loading || !selectedSupplier}
                        style={{ height: '42px' }}
                    >
                        {loading ? t('buying.reports.statement.filters.loading') : `📄 ${t('buying.reports.statement.filters.view_btn')}`}
                    </button>
                </div>
            </div>

            {/* Statement Results */}
            {statement && (
                <>
                    {/* Balance Summary */}
                    <div className="metrics-grid" style={{ marginBottom: '24px' }}>
                        <div className="metric-card">
                            <div className="metric-label">{t('buying.reports.statement.summary.supplier')}</div>
                            <div className="metric-value text-primary" style={{ fontSize: '18px' }}>
                                {selectedSupplierData?.name || '-'}
                            </div>
                        </div>
                        <div className="metric-card">
                            <div className="metric-label">{t('buying.reports.statement.summary.opening_balance')}</div>
                            <div className="metric-value text-secondary">
                                {hasPermission('reports.view') ? statement.opening_balance?.toLocaleString() : '***'} {hasPermission('reports.view') && <small>{selectedSupplierData?.currency || baseCurrency}</small>}
                            </div>
                        </div>
                        <div className="metric-card">
                            <div className="metric-label">{t('buying.reports.statement.summary.closing_balance')}</div>
                            <div className="metric-value" style={{ color: statement.closing_balance > 0 ? 'var(--error)' : 'var(--success)' }}>
                                {hasPermission('reports.view') ? statement.closing_balance?.toLocaleString() : '***'} {hasPermission('reports.view') && <small>{selectedSupplierData?.currency || baseCurrency}</small>}
                            </div>
                        </div>
                    </div>

                    {/* Transactions Table */}
                    <div className="card">
                        <div style={{ padding: '16px', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <h3 style={{ fontWeight: '600', margin: 0 }}>{t('buying.reports.statement.table.title')}</h3>
                            <span className="badge" style={{ background: 'var(--bg-secondary)', color: 'var(--text-primary)' }}>
                                {statement.transactions.length} {t('buying.reports.statement.table.count')}
                            </span>
                        </div>
                        <div className="data-table-container">
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>{t('buying.reports.statement.table.date')}</th>
                                        <th>{t('buying.reports.statement.table.ref')}</th>
                                        <th>{t('buying.reports.statement.table.type')}</th>
                                        <th>{t('buying.reports.statement.table.debit')}</th>
                                        <th>{t('buying.reports.statement.table.credit')}</th>
                                        <th>{t('buying.reports.statement.table.balance')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {statement.transactions.length === 0 && (
                                        <tr>
                                            <td colSpan="6" className="text-center py-5 text-muted">
                                                {t('buying.reports.statement.table.empty')}
                                            </td>
                                        </tr>
                                    )}
                                    {statement.transactions.map((t, idx) => (
                                        <tr key={idx}>
                                            <td>{formatDate(t.date)}</td>
                                            <td className="font-medium text-primary">{t.ref}</td>
                                            <td>
                                                <span className={`badge ${t.type === 'invoice' ? 'badge-danger' : 'badge-success'}`}>
                                                    {t.type === 'invoice' ? t('buying.reports.statement.types.invoice') : t('buying.reports.statement.types.payment')}
                                                </span>
                                            </td>
                                            <td style={{ color: 'var(--success)', fontWeight: t.debit > 0 ? '600' : '400' }}>
                                                {hasPermission('reports.view') ? (t.debit > 0 ? t.debit?.toLocaleString() : '-') : '***'}
                                            </td>
                                            <td style={{ color: 'var(--error)', fontWeight: t.credit > 0 ? '600' : '400' }}>
                                                {hasPermission('reports.view') ? (t.credit > 0 ? t.credit?.toLocaleString() : '-') : '***'}
                                            </td>
                                            <td className="font-medium">{hasPermission('reports.view') ? t.balance?.toLocaleString() : '***'}</td>
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
                    <h3 style={{ fontWeight: '600', marginBottom: '8px', color: 'var(--text-secondary)' }}>{t('buying.reports.statement.empty_state.title')}</h3>
                    <p className="text-muted">{t('buying.reports.statement.empty_state.desc')}</p>
                </div>
            )}
        </div>
    );
};

export default SupplierStatement;
