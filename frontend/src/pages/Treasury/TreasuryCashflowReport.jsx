import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useBranch } from '../../context/BranchContext';
import { getCurrency } from '../../utils/auth';
import { formatNumber } from '../../utils/format';
import { treasuryAPI } from '../../utils/api';
import CustomDatePicker from '../../components/common/CustomDatePicker';
import { formatDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

function TreasuryCashflowReport() {
    const { t } = useTranslation();
    const { currentBranch } = useBranch();
    const currency = getCurrency();

    const [startDate, setStartDate] = useState(new Date(new Date().getFullYear(), new Date().getMonth(), 1));
    const [endDate, setEndDate] = useState(new Date());
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [error, setError] = useState(null);

    const fetchData = async () => {
        try {
            setLoading(true);
            setError(null);
            const params = {
                start_date: startDate.toISOString().split('T')[0],
                end_date: endDate.toISOString().split('T')[0],
            };
            if (currentBranch) params.branch_id = currentBranch.id;
            const res = await treasuryAPI.getCashflowReport(params);
            setData(res.data);
        } catch (err) {
            console.error('Failed to fetch treasury cashflow', err);
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
    }, [currentBranch, startDate, endDate]);

    const typeLabel = (type) => {
        const map = {
            receipt: t('treasury_reports.types.receipt'),
            deposit: t('treasury_reports.types.deposit'),
            transfer_in: t('treasury_reports.types.transfer_in'),
            pos_sale: t('treasury_reports.types.pos_sale'),
            expense: t('treasury_reports.types.expense'),
            withdrawal: t('treasury_reports.types.withdrawal'),
            transfer_out: t('treasury_reports.types.transfer_out'),
            payment: t('treasury_reports.types.payment'),
        };
        return map[type] || type;
    };

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">💸 {t('treasury_reports.cashflow.title')}</h1>
                    <p className="workspace-subtitle">{t('treasury_reports.cashflow.subtitle')}</p>
                </div>
                <div className="header-actions">
                    <button className="btn btn-secondary" onClick={() => window.print()}>🖨️ {t('common.print')}</button>
                    <button className="btn btn-primary" onClick={fetchData}>🔄 {t('common.refresh')}</button>
                </div>
            </div>

            {/* Date Filters */}
            <div className="card mb-4 mt-4">
                <div className="card-body">
                    <div className="display-flex gap-4 align-center" style={{ flexWrap: 'wrap' }}>
                        <div style={{ width: '200px' }}>
                            <label className="form-label">{t('common.start_date')}</label>
                            <CustomDatePicker selected={startDate} onChange={d => setStartDate(d)} className="form-input" />
                        </div>
                        <div style={{ width: '200px' }}>
                            <label className="form-label">{t('common.end_date')}</label>
                            <CustomDatePicker selected={endDate} onChange={d => setEndDate(d)} className="form-input" />
                        </div>
                    </div>
                </div>
            </div>

            {initialLoad ? (
                <PageLoading />
            ) : error ? (
                <div className="alert alert-danger">{error}</div>
            ) : data && (
                <>
                    {/* Summary */}
                    <div className="metrics-grid" style={{ marginBottom: '24px' }}>
                        <div className="metric-card">
                            <div className="metric-label">{t('treasury_reports.cashflow.total_inflow')}</div>
                            <div className="metric-value text-success">{formatNumber(data.total_inflow)}</div>
                            <div className="metric-change">{currency}</div>
                        </div>
                        <div className="metric-card">
                            <div className="metric-label">{t('treasury_reports.cashflow.total_outflow')}</div>
                            <div className="metric-value text-danger">{formatNumber(data.total_outflow)}</div>
                            <div className="metric-change">{currency}</div>
                        </div>
                        <div className="metric-card">
                            <div className="metric-label">{t('treasury_reports.cashflow.net_flow')}</div>
                            <div className={`metric-value ${data.net_flow >= 0 ? 'text-primary' : 'text-danger'}`}>
                                {formatNumber(data.net_flow)}
                            </div>
                            <div className="metric-change">{currency}</div>
                        </div>
                    </div>

                    <div className="grid-2" style={{ gap: '20px', marginBottom: '24px' }}>
                        {/* Inflows Breakdown */}
                        <div className="card">
                            <div className="card-header">
                                <h3 className="card-title">📥 {t('treasury_reports.cashflow.inflows')}</h3>
                            </div>
                            <div className="data-table-container">
                                <table className="data-table">
                                    <thead>
                                        <tr>
                                            <th>{t('treasury_reports.cashflow.transaction_type')}</th>
                                            <th className="text-center">{t('treasury_reports.cashflow.count')}</th>
                                            <th className="text-end">{t('treasury_reports.cashflow.total')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {data.inflows.map((item, idx) => (
                                            <tr key={idx}>
                                                <td><span className="badge badge-success">{typeLabel(item.type)}</span></td>
                                                <td className="text-center">{item.count}</td>
                                                <td className="text-end" style={{ fontWeight: 600 }}>{formatNumber(item.total)} {currency}</td>
                                            </tr>
                                        ))}
                                        {data.inflows.length === 0 && (
                                            <tr><td colSpan="3" className="text-center text-muted p-4">{t('common.no_data')}</td></tr>
                                        )}
                                    </tbody>
                                    <tfoot>
                                        <tr style={{ fontWeight: 700, background: 'var(--bg-secondary)' }}>
                                            <td colSpan="2">{t('treasury_reports.cashflow.total_inflow')}</td>
                                            <td className="text-end text-success">{formatNumber(data.total_inflow)} {currency}</td>
                                        </tr>
                                    </tfoot>
                                </table>
                            </div>
                        </div>

                        {/* Outflows Breakdown */}
                        <div className="card">
                            <div className="card-header">
                                <h3 className="card-title">📤 {t('treasury_reports.cashflow.outflows')}</h3>
                            </div>
                            <div className="data-table-container">
                                <table className="data-table">
                                    <thead>
                                        <tr>
                                            <th>{t('treasury_reports.cashflow.transaction_type')}</th>
                                            <th className="text-center">{t('treasury_reports.cashflow.count')}</th>
                                            <th className="text-end">{t('treasury_reports.cashflow.total')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {data.outflows.map((item, idx) => (
                                            <tr key={idx}>
                                                <td><span className="badge badge-danger">{typeLabel(item.type)}</span></td>
                                                <td className="text-center">{item.count}</td>
                                                <td className="text-end" style={{ fontWeight: 600 }}>{formatNumber(item.total)} {currency}</td>
                                            </tr>
                                        ))}
                                        {data.outflows.length === 0 && (
                                            <tr><td colSpan="3" className="text-center text-muted p-4">{t('common.no_data')}</td></tr>
                                        )}
                                    </tbody>
                                    <tfoot>
                                        <tr style={{ fontWeight: 700, background: 'var(--bg-secondary)' }}>
                                            <td colSpan="2">{t('treasury_reports.cashflow.total_outflow')}</td>
                                            <td className="text-end text-danger">{formatNumber(data.total_outflow)} {currency}</td>
                                        </tr>
                                    </tfoot>
                                </table>
                            </div>
                        </div>
                    </div>

                    {/* By Account */}
                    <div className="card" style={{ marginBottom: '24px' }}>
                        <div className="card-header">
                            <h3 className="card-title">🏦 {t('treasury_reports.cashflow.by_account')}</h3>
                        </div>
                        <div className="table-responsive">
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>{t('treasury_reports.balances.account_name')}</th>
                                        <th>{t('treasury_reports.balances.type')}</th>
                                        <th className="text-end text-success">{t('treasury_reports.cashflow.inflows')}</th>
                                        <th className="text-end text-danger">{t('treasury_reports.cashflow.outflows')}</th>
                                        <th className="text-end">{t('treasury_reports.cashflow.net')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {data.by_account?.map(acc => (
                                        <tr key={acc.id}>
                                            <td style={{ fontWeight: 600 }}>{acc.name}</td>
                                            <td>
                                                <span className={`badge ${acc.type === 'cash' ? 'badge-warning' : 'badge-info'}`}>
                                                    {acc.type === 'cash' ? t('treasury_reports.types.cash') : t('treasury_reports.types.bank')}
                                                </span>
                                            </td>
                                            <td className="text-end text-success">{formatNumber(acc.inflow)}</td>
                                            <td className="text-end text-danger">{formatNumber(acc.outflow)}</td>
                                            <td className="text-end" style={{ fontWeight: 700 }}>
                                                <span className={acc.net >= 0 ? 'text-primary' : 'text-danger'}>{formatNumber(acc.net)}</span>
                                            </td>
                                        </tr>
                                    ))}
                                    {(!data.by_account || data.by_account.length === 0) && (
                                        <tr><td colSpan="5" className="text-center text-muted p-4">{t('common.no_data')}</td></tr>
                                    )}
                                </tbody>
                            </table>
                        </div>
                    </div>

                    {/* Daily Trend */}
                    {data.daily_trend?.length > 0 && (
                        <div className="card">
                            <div className="card-header">
                                <h3 className="card-title">📊 {t('treasury_reports.cashflow.daily_trend')}</h3>
                            </div>
                            <div className="table-responsive">
                                <table className="data-table">
                                    <thead>
                                        <tr>
                                            <th>{t('common.date')}</th>
                                            <th className="text-end text-success">{t('treasury_reports.cashflow.inflows')}</th>
                                            <th className="text-end text-danger">{t('treasury_reports.cashflow.outflows')}</th>
                                            <th className="text-end">{t('treasury_reports.cashflow.net')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {data.daily_trend.map((d, idx) => (
                                            <tr key={idx}>
                                                <td>{formatDate(d.date)}</td>
                                                <td className="text-end text-success">{formatNumber(d.inflow)}</td>
                                                <td className="text-end text-danger">{formatNumber(d.outflow)}</td>
                                                <td className="text-end" style={{ fontWeight: 600 }}>
                                                    <span className={d.inflow - d.outflow >= 0 ? 'text-primary' : 'text-danger'}>
                                                        {formatNumber(d.inflow - d.outflow)}
                                                    </span>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    )}
                </>
            )}
        </div>
    );
}

export default TreasuryCashflowReport;
