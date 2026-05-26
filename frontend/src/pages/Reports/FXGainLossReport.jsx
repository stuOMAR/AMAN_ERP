import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useBranch } from '../../context/BranchContext';
import { getCurrency } from '../../utils/auth';
import { formatNumber } from '../../utils/format';
import { fxReportAPI } from '../../utils/api';
import BackButton from '../../components/common/BackButton';
import DateInput from '../../components/common/DateInput';
import { PageLoading } from '../../components/common/LoadingStates'

const isNegativeAmount = (value) => String(value ?? '').trim().startsWith('-');

function FXGainLossReport() {
    const { t } = useTranslation();
    const { currentBranch } = useBranch();
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [error, setError] = useState(null);
    const [dateRange, setDateRange] = useState({
        start_date: new Date(new Date().getFullYear(), 0, 1).toISOString().split('T')[0],
        end_date: new Date().toISOString().split('T')[0]
    });
    const currency = getCurrency();

    const fetchData = async () => {
        try {
            setLoading(true);
            setError(null);
            const res = await fxReportAPI.getGainLoss({
                branch_id: currentBranch?.id,
                ...dateRange
            });
            setData(res.data || null);
        } catch (err) {
            console.error('Failed to fetch FX gain/loss', err);
            setError(t('errors.fetch_failed'));
        } finally {
            setLoading(false);
            setInitialLoad(false);
        }
    };

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchData()
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch]);

    const realized = Array.isArray(data?.realized?.entries) ? data.realized.entries : Array.isArray(data?.realized) ? data.realized : [];
    const unrealized = Array.isArray(data?.unrealized?.invoices) ? data.unrealized.invoices : Array.isArray(data?.unrealized) ? data.unrealized : [];
    const summary = data?.summary || {};
    const realizedTotals = typeof data?.realized === 'object' && !Array.isArray(data?.realized) ? data.realized : {};
    const unrealizedTotals = typeof data?.unrealized === 'object' && !Array.isArray(data?.unrealized) ? data.unrealized : {};
    const realizedNet = summary.total_fx_gain ?? realizedTotals.net ?? '0';
    const unrealizedNet = unrealizedTotals.net ?? unrealizedTotals.net_unrealized ?? '0';
    const totalNet = summary.net_fx ?? '0';

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">💱 {t('fx_report.title')}</h1>
                    <p className="workspace-subtitle">{t('fx_report.subtitle')}</p>
                </div>
                <div className="header-actions">
                    <button className="btn btn-secondary" onClick={() => window.print()}>🖨️ {t('common.print')}</button>
                    <button className="btn btn-primary" onClick={fetchData}>🔄 {t('common.refresh')}</button>
                </div>
            </div>

            {/* Filters */}
            <div className="card" style={{ marginBottom: '16px', padding: '16px' }}>
                <div style={{ display: 'flex', gap: '16px', alignItems: 'flex-end', flexWrap: 'wrap' }}>
                    <div className="form-group" style={{ margin: 0 }}>
                        <label className="form-label">{t('common.start_date')}</label>
                        <DateInput className="form-control" value={dateRange.start_date}
                            onChange={e => setDateRange(d => ({ ...d, start_date: e.target.value }))} />
                    </div>
                    <div className="form-group" style={{ margin: 0 }}>
                        <label className="form-label">{t('common.end_date')}</label>
                        <DateInput className="form-control" value={dateRange.end_date}
                            onChange={e => setDateRange(d => ({ ...d, end_date: e.target.value }))} />
                    </div>
                    <button className="btn btn-primary" onClick={fetchData}>{t('common.apply')}</button>
                </div>
            </div>

            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            {initialLoad && loading ? (
                <PageLoading />
            ) : error ? (
                <div className="alert alert-danger">{error}</div>
            ) : (
                <>
                    {/* Summary Cards */}
                    <div className="metrics-grid" style={{ marginBottom: '24px' }}>
                        <div className="metric-card">
                            <div className="metric-label">{t('fx_report.realized_gain')}</div>
                            <div className={`metric-value ${isNegativeAmount(realizedNet) ? 'text-danger' : 'text-success'}`}>
                                {formatNumber(realizedNet)}
                            </div>
                            <div className="metric-change">{currency}</div>
                        </div>
                        <div className="metric-card">
                            <div className="metric-label">{t('fx_report.unrealized_gain')}</div>
                            <div className={`metric-value ${isNegativeAmount(unrealizedNet) ? 'text-danger' : 'text-success'}`}>
                                {formatNumber(unrealizedNet)}
                            </div>
                            <div className="metric-change">{currency}</div>
                        </div>
                        <div className="metric-card">
                            <div className="metric-label">{t('fx_report.net_gain_loss')}</div>
                            <div className={`metric-value ${isNegativeAmount(totalNet) ? 'text-danger' : 'text-success'}`}>
                                {formatNumber(totalNet)}
                            </div>
                            <div className="metric-change">{currency}</div>
                        </div>
                    </div>

                    {/* Realized Gains Table */}
                    <div className="card" style={{ marginBottom: '16px' }}>
                        <div className="card-header">
                            <h3 className="card-title">✅ {t('fx_report.realized_section')}</h3>
                        </div>
                        <div className="data-table-container">
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>{t('fx_report.reference')}</th>
                                        <th>{t('common.date')}</th>
                                        <th>{t('fx_report.currency')}</th>
                                        <th>{t('common.account')}</th>
                                        <th className="text-end">{t('common.debit')}</th>
                                        <th className="text-end">{t('common.credit')}</th>
                                        <th className="text-end">{t('fx_report.gain_loss')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {realized.length === 0 ? (
                                        <tr><td colSpan={7} className="text-center text-muted p-4">{t('fx_report.no_realized')}</td></tr>
                                    ) : realized.map((row, i) => {
                                        const rowNet = row.net ?? row.fx_gain_loss ?? '0';
                                        return (
                                            <tr key={i}>
                                                <td className="font-medium">{row.ref || row.reference}</td>
                                                <td>{row.date || row.entry_date}</td>
                                                <td>{row.currency}</td>
                                                <td>{row.account || row.account_name}</td>
                                                <td className="text-end">{formatNumber(row.debit ?? row.debit_amount ?? 0)}</td>
                                                <td className="text-end">{formatNumber(row.credit ?? row.credit_amount ?? 0)}</td>
                                                <td className={`text-end font-medium ${isNegativeAmount(rowNet) ? 'text-danger' : 'text-success'}`}>
                                                    {formatNumber(rowNet)}
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    </div>

                    {/* Unrealized Gains Table */}
                    <div className="card">
                        <div className="card-header">
                            <h3 className="card-title">⏳ {t('fx_report.unrealized_section')}</h3>
                        </div>
                        <div className="data-table-container">
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>{t('fx_report.reference')}</th>
                                        <th>{t('fx_report.party')}</th>
                                        <th>{t('fx_report.currency')}</th>
                                        <th className="text-end">{t('fx_report.book_rate')}</th>
                                        <th className="text-end">{t('fx_report.current_rate')}</th>
                                        <th className="text-end">{t('fx_report.foreign_amount')}</th>
                                        <th className="text-end">{t('fx_report.unrealized_gl')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {unrealized.length === 0 ? (
                                        <tr><td colSpan={7} className="text-center text-muted p-4">{t('fx_report.no_unrealized')}</td></tr>
                                    ) : unrealized.map((row, i) => (
                                        <tr key={i}>
                                            <td className="font-medium">{row.invoice_number || row.reference}</td>
                                            <td>{row.party || row.party_name}</td>
                                            <td>{row.currency}</td>
                                            <td className="text-end">{formatNumber(row.booked_rate ?? row.book_rate ?? 0, 4)}</td>
                                            <td className="text-end">{formatNumber(row.current_rate ?? 0, 4)}</td>
                                            <td className="text-end">{formatNumber(row.open_fc_amount ?? row.foreign_amount ?? 0)}</td>
                                            <td className={`text-end font-medium ${isNegativeAmount(row.unrealized_fx ?? row.unrealized_gl ?? 0) ? 'text-danger' : 'text-success'}`}>
                                                {formatNumber(row.unrealized_fx ?? row.unrealized_gl ?? 0)}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </>
            )}
        </div>
    );
}

export default FXGainLossReport;
