import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useBranch } from '../../context/BranchContext';
import { getCurrency } from '../../utils/auth';
import { formatNumber } from '../../utils/format';
import { reportsAPI } from '../../utils/api';
import BackButton from '../../components/common/BackButton';
import DateInput from '../../components/common/DateInput';
import { PageLoading } from '../../components/common/LoadingStates'

function CashFlowIAS7() {
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
            const res = await reportsAPI.getCashFlowIAS7({
                branch_id: currentBranch?.id,
                ...dateRange
            });
            setData(res.data || null);
        } catch (err) {
            console.error('Failed to fetch cashflow IAS7', err);
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

    const sections = [
        { key: 'operating', label: t('cashflow_ias7.operating'), icon: '⚙️', color: 'var(--primary)' },
        { key: 'investing', label: t('cashflow_ias7.investing'), icon: '📈', color: 'var(--warning)' },
        { key: 'financing', label: t('cashflow_ias7.financing'), icon: '🏦', color: 'var(--info)' },
    ];

    const operating = data?.operating || { items: [], total: 0 };
    const investing = data?.investing || { items: [], total: 0 };
    const financing = data?.financing || { items: [], total: 0 };
    const sectionData = { operating, investing, financing };
    const netChange = operating.total + investing.total + financing.total;

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">📊 {t('cashflow_ias7.title')}</h1>
                    <p className="workspace-subtitle">{t('cashflow_ias7.subtitle')}</p>
                </div>
                <div className="header-actions">
                    <button className="btn btn-secondary" onClick={() => window.print()}>🖨️ {t('common.print')}</button>
                    <button className="btn btn-primary" onClick={fetchData}>🔄 {t('common.refresh')}</button>
                </div>
            </div>

            {/* Date Filters */}
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
                        {sections.map(sec => (
                            <div key={sec.key} className="metric-card">
                                <div className="metric-label">{sec.icon} {sec.label}</div>
                                <div className={`metric-value ${sectionData[sec.key].total >= 0 ? 'text-success' : 'text-danger'}`}>
                                    {formatNumber(sectionData[sec.key].total)}
                                </div>
                                <div className="metric-change">{currency}</div>
                            </div>
                        ))}
                        <div className="metric-card">
                            <div className="metric-label">{t('cashflow_ias7.net_change')}</div>
                            <div className={`metric-value ${netChange >= 0 ? 'text-success' : 'text-danger'}`}>
                                {formatNumber(netChange)}
                            </div>
                            <div className="metric-change">{currency}</div>
                        </div>
                    </div>

                    {/* Cash Position */}
                    <div className="card" style={{ marginBottom: '16px', padding: '20px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
                            <div>
                                <div className="text-muted" style={{ fontSize: '0.85rem' }}>{t('cashflow_ias7.opening_cash')}</div>
                                <div style={{ fontSize: '1.25rem', fontWeight: 600 }}>{formatNumber(data?.opening_cash || 0)} {currency}</div>
                            </div>
                            <div style={{ fontSize: '2rem', color: 'var(--text-muted)' }}>→</div>
                            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                                <span className={`badge ${netChange >= 0 ? 'badge-success' : 'badge-danger'}`} style={{ fontSize: '0.9rem', padding: '4px 12px' }}>
                                    {netChange >= 0 ? '+' : ''}{formatNumber(netChange)}
                                </span>
                            </div>
                            <div style={{ fontSize: '2rem', color: 'var(--text-muted)' }}>→</div>
                            <div>
                                <div className="text-muted" style={{ fontSize: '0.85rem' }}>{t('cashflow_ias7.closing_cash')}</div>
                                <div style={{ fontSize: '1.25rem', fontWeight: 600, color: 'var(--primary)' }}>{formatNumber(data?.closing_cash || 0)} {currency}</div>
                            </div>
                        </div>
                    </div>

                    {/* Section Details */}
                    {sections.map(sec => (
                        <div key={sec.key} className="card" style={{ marginBottom: '16px' }}>
                            <div className="card-header" style={{ borderLeft: `4px solid ${sec.color}` }}>
                                <h3 className="card-title">{sec.icon} {sec.label}</h3>
                                <span className={`font-medium ${sectionData[sec.key].total >= 0 ? 'text-success' : 'text-danger'}`}>
                                    {formatNumber(sectionData[sec.key].total)} {currency}
                                </span>
                            </div>
                            <div className="data-table-container">
                                <table className="data-table">
                                    <thead>
                                        <tr>
                                            <th>{t('cashflow_ias7.description')}</th>
                                            <th>{t('cashflow_ias7.account')}</th>
                                            <th className="text-end">{t('cashflow_ias7.inflow')}</th>
                                            <th className="text-end">{t('cashflow_ias7.outflow')}</th>
                                            <th className="text-end">{t('cashflow_ias7.net')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {(sectionData[sec.key].items || []).length === 0 ? (
                                            <tr><td colSpan={5} className="text-center text-muted p-4">{t('cashflow_ias7.no_items')}</td></tr>
                                        ) : (sectionData[sec.key].items || []).map((item, i) => (
                                            <tr key={i}>
                                                <td className="font-medium">{item.description || item.account_name}</td>
                                                <td>{item.account_code || '-'}</td>
                                                <td className="text-end text-success">{item.inflow > 0 ? formatNumber(item.inflow) : '-'}</td>
                                                <td className="text-end text-danger">{item.outflow > 0 ? formatNumber(item.outflow) : '-'}</td>
                                                <td className={`text-end font-medium ${item.net >= 0 ? 'text-success' : 'text-danger'}`}>
                                                    {formatNumber(item.net)}
                                                </td>
                                            </tr>
                                        ))}
                                        <tr style={{ borderTop: '2px solid var(--border-color)' }}>
                                            <td colSpan={4} className="text-end font-bold">{t('cashflow_ias7.section_total')}</td>
                                            <td className={`text-end font-bold ${sectionData[sec.key].total >= 0 ? 'text-success' : 'text-danger'}`}>
                                                {formatNumber(sectionData[sec.key].total)} {currency}
                                            </td>
                                        </tr>
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    ))}
                </>
            )}
        </div>
    );
}

export default CashFlowIAS7;
