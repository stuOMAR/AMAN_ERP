import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useBranch } from '../../context/BranchContext';
import { getCurrency } from '../../utils/auth';
import { formatNumber } from '../../utils/format';
import { treasuryAPI } from '../../utils/api';
import BackButton from '../../components/common/BackButton';
import CustomDatePicker from '../../components/common/CustomDatePicker';
import { PageLoading } from '../../components/common/LoadingStates'

function TreasuryBalancesReport() {
    const { t, i18n } = useTranslation();
    const { currentBranch } = useBranch();
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [error, setError] = useState(null);
    const currency = getCurrency();
    const [asOfDate, setAsOfDate] = useState(new Date().toISOString().split('T')[0]);

    const fetchData = async () => {
        try {
            setLoading(true);
            setError(null);
            const params = {};
            if (currentBranch) params.branch_id = currentBranch.id;
            if (asOfDate) params.as_of_date = asOfDate;
            const res = await treasuryAPI.getBalancesReport(params);
            setData(res.data);
        } catch (err) {
            console.error('Failed to fetch treasury balances', err);
            setError(t('errors.fetch_failed'));
        } finally {
            setLoading(false);
            setInitialLoad(false);
        }
    };

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchData();
        }, 300)
        return () => clearTimeout(timer);
    }, [currentBranch, asOfDate]);

    const cashAccounts = data?.accounts?.filter(a => a.account_type === 'cash') || [];
    const bankAccounts = data?.accounts?.filter(a => a.account_type === 'bank') || [];

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">🏦 {t('treasury_reports.balances.title')}</h1>
                    <p className="workspace-subtitle">{t('treasury_reports.balances.subtitle')}</p>
                </div>
                <div className="header-actions">
                    <CustomDatePicker
                        label={t('common.date')}
                        selected={asOfDate}
                        onChange={(d) => setAsOfDate(d)}
                    />
                    <button className="btn btn-secondary" onClick={() => window.print()}>🖨️ {t('common.print')}</button>
                    <button className="btn btn-primary" onClick={fetchData}>🔄 {t('common.refresh')}</button>
                </div>
            </div>

            {initialLoad ? (
                <PageLoading />
            ) : error ? (
                <div className="alert alert-danger">{error}</div>
            ) : data && (
                <>
                    {/* Summary Cards */}
                    <div className="metrics-grid" style={{ marginBottom: '24px' }}>
                        <div className="metric-card">
                            <div className="metric-label">{t('treasury_reports.balances.total_balance')}</div>
                            <div className="metric-value text-primary">{formatNumber(data.summary.total_all)}</div>
                            <div className="metric-change">{currency}</div>
                        </div>
                        <div className="metric-card">
                            <div className="metric-label">{t('treasury_reports.balances.cash_balance')}</div>
                            <div className="metric-value text-success">{formatNumber(data.summary.total_cash)}</div>
                            <div className="metric-change">{data.summary.cash_count} {t('treasury_reports.balances.accounts')}</div>
                        </div>
                        <div className="metric-card">
                            <div className="metric-label">{t('treasury_reports.balances.bank_balance')}</div>
                            <div className="metric-value text-info">{formatNumber(data.summary.total_bank)}</div>
                            <div className="metric-change">{data.summary.bank_count} {t('treasury_reports.balances.accounts')}</div>
                        </div>
                    </div>

                    <div className="grid-2" style={{ gap: '20px', marginBottom: '24px' }}>
                        {/* Cash Accounts */}
                        <div className="card">
                            <div className="card-header">
                                <h3 className="card-title">💵 {t('treasury_reports.balances.cash_accounts')}</h3>
                            </div>
                            <div className="data-table-container">
                                <table className="data-table">
                                    <thead>
                                        <tr>
                                            <th>{t('treasury_reports.balances.account_name')}</th>
                                            <th>{t('treasury_reports.balances.branch')}</th>
                                            <th className="text-end">{t('treasury_reports.balances.balance')}</th>
                                            <th className="text-end">{t('treasury_reports.balances.gl_balance', 'رصيد الأستاذ العام')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {cashAccounts.map(acc => (
                                            <tr key={acc.id}>
                                                <td style={{ fontWeight: 600 }}>{i18n.language === 'ar' ? acc.name : (acc.name_en || acc.name)}</td>
                                                <td>{acc.branch_name || '—'}</td>
                                                <td className="text-end">
                                                    <span className={acc.current_balance >= 0 ? 'text-success' : 'text-danger'} style={{ fontWeight: 600 }}>
                                                        {formatNumber(acc.current_balance)} {currency}
                                                    </span>
                                                </td>
                                                <td className="text-end">
                                                    <span style={{ fontWeight: 600 }}>
                                                        {acc.gl_balance != null ? `${formatNumber(acc.gl_balance)} ${currency}` : '—'}
                                                    </span>
                                                </td>
                                            </tr>
                                        ))}
                                        {cashAccounts.length === 0 && (
                                            <tr><td colSpan="4" className="text-center text-muted p-4">{t('common.no_data')}</td></tr>
                                        )}
                                    </tbody>
                                    {cashAccounts.length > 0 && (
                                        <tfoot>
                                            <tr style={{ fontWeight: 700, background: 'var(--bg-secondary)' }}>
                                                <td colSpan="2">{t('treasury_reports.balances.cash_total')}</td>
                                                <td className="text-end text-success">{formatNumber(data.summary.total_cash)} {currency}</td>
                                                <td className="text-end"></td>
                                            </tr>
                                        </tfoot>
                                    )}
                                </table>
                            </div>
                        </div>

                        {/* Bank Accounts */}
                        <div className="card">
                            <div className="card-header">
                                <h3 className="card-title">🏛️ {t('treasury_reports.balances.bank_accounts')}</h3>
                            </div>
                            <div className="data-table-container">
                                <table className="data-table">
                                    <thead>
                                        <tr>
                                            <th>{t('treasury_reports.balances.account_name')}</th>
                                            <th>{t('treasury_reports.balances.branch')}</th>
                                            <th className="text-end">{t('treasury_reports.balances.balance')}</th>
                                            <th className="text-end">{t('treasury_reports.balances.gl_balance', 'رصيد الأستاذ العام')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {bankAccounts.map(acc => (
                                            <tr key={acc.id}>
                                                <td style={{ fontWeight: 600 }}>{i18n.language === 'ar' ? acc.name : (acc.name_en || acc.name)}</td>
                                                <td>{acc.branch_name || '—'}</td>
                                                <td className="text-end">
                                                    <span className={acc.current_balance >= 0 ? 'text-success' : 'text-danger'} style={{ fontWeight: 600 }}>
                                                        {formatNumber(acc.current_balance)} {currency}
                                                    </span>
                                                    {acc.currency && acc.currency !== currency && (
                                                        <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
                                                            {formatNumber(acc.balance_in_currency)} {acc.currency}
                                                        </div>
                                                    )}
                                                </td>
                                                <td className="text-end">
                                                    <span style={{ fontWeight: 600 }}>
                                                        {acc.gl_balance != null ? `${formatNumber(acc.gl_balance)} ${currency}` : '—'}
                                                    </span>
                                                </td>
                                            </tr>
                                        ))}
                                        {bankAccounts.length === 0 && (
                                            <tr><td colSpan="4" className="text-center text-muted p-4">{t('common.no_data')}</td></tr>
                                        )}
                                    </tbody>
                                    {bankAccounts.length > 0 && (
                                        <tfoot>
                                            <tr style={{ fontWeight: 700, background: 'var(--bg-secondary)' }}>
                                                <td colSpan="2">{t('treasury_reports.balances.bank_total')}</td>
                                                <td className="text-end text-info">{formatNumber(data.summary.total_bank)} {currency}</td>
                                                <td className="text-end"></td>
                                            </tr>
                                        </tfoot>
                                    )}
                                </table>
                            </div>
                        </div>
                    </div>

                    {/* Recent Transactions */}
                    <div className="card">
                        <div className="card-header">
                            <h3 className="card-title">📋 {t('treasury_reports.balances.recent_transactions')}</h3>
                        </div>
                        <div className="data-table-container">
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>{t('common.date')}</th>
                                        <th>{t('treasury_reports.balances.account_name')}</th>
                                        <th>{t('treasury_reports.balances.type')}</th>
                                        <th>{t('treasury_reports.balances.description')}</th>
                                        <th className="text-end">{t('treasury_reports.balances.amount')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {data.recent_transactions?.map(txn => (
                                        <tr key={txn.id}>
                                            <td>{txn.date}</td>
                                            <td>{txn.account_name}</td>
                                            <td>
                                                <span className={`badge ${['receipt','deposit','transfer_in','pos_sale'].includes(txn.type) ? 'badge-success' : 'badge-danger'}`}>
                                                    {t(`treasury_reports.types.${txn.type}`) || txn.type}
                                                </span>
                                            </td>
                                            <td>{txn.description || '—'}</td>
                                            <td className="text-end" style={{ fontWeight: 600 }}>{formatNumber(txn.amount)} {currency}</td>
                                        </tr>
                                    ))}
                                    {(!data.recent_transactions || data.recent_transactions.length === 0) && (
                                        <tr><td colSpan="5" className="text-center text-muted p-4">{t('common.no_data')}</td></tr>
                                    )}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </>
            )}
        </div>
    );
}

export default TreasuryBalancesReport;
