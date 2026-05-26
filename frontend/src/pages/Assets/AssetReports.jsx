import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import Decimal from 'decimal.js';
import { useBranch } from '../../context/BranchContext';
import { getCurrency } from '../../utils/auth';
import { formatNumber } from '../../utils/format';
import { assetsAPI } from '../../utils/api';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

function AssetReports() {
    const { t } = useTranslation();
    const { currentBranch } = useBranch();
    const [activeTab, setActiveTab] = useState('register');
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [error, setError] = useState(null);
    const currency = getCurrency();

    const tabs = [
        { key: 'register', label: t('asset_reports.register'), icon: '📋' },
        { key: 'depreciation', label: t('asset_reports.depreciation_summary'), icon: '📉' },
        { key: 'nbv', label: t('asset_reports.net_book_value'), icon: '💰' },
    ];

    const fetchData = async () => {
        try {
            setLoading(true);
            setError(null);
            let res;
            const params = { branch_id: currentBranch?.id };
            if (activeTab === 'register') {
                res = await assetsAPI.getRegisterReport(params);
            } else if (activeTab === 'depreciation') {
                res = await assetsAPI.getDepreciationSummary(params);
            } else {
                res = await assetsAPI.getNetBookValueReport(params);
            }
            setData(res.data?.items || res.data || []);
        } catch (err) {
            console.error('Failed to fetch asset reports', err);
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
    }, [currentBranch, activeTab]);

    // Calculate totals using absolute Decimal precision
    const totalCost = data.reduce((s, r) => s.plus(new Decimal(r.cost || r.original_cost || '0')), new Decimal('0')).toString();
    const totalDepreciation = data.reduce((s, r) => s.plus(new Decimal(r.accumulated_depreciation || r.total_depreciation || '0')), new Decimal('0')).toString();
    const totalNBV = data.reduce((s, r) => s.plus(new Decimal(r.net_book_value || r.nbv || '0')), new Decimal('0')).toString();

    const renderRegisterTable = () => (
        <table className="data-table">
            <thead>
                <tr>
                    <th>{t('asset_reports.asset_code')}</th>
                    <th>{t('asset_reports.asset_name')}</th>
                    <th>{t('asset_reports.category')}</th>
                    <th>{t('asset_reports.acquisition_date')}</th>
                    <th>{t('asset_reports.location')}</th>
                    <th>{t('asset_reports.status')}</th>
                    <th className="text-end">{t('asset_reports.original_cost')}</th>
                    <th className="text-end">{t('asset_reports.accum_depr')}</th>
                    <th className="text-end">{t('asset_reports.nbv')}</th>
                </tr>
            </thead>
            <tbody>
                {data.length === 0 ? (
                    <tr><td colSpan={9} className="text-center text-muted p-4">{t('asset_reports.no_data')}</td></tr>
                ) : data.map((row, i) => (
                    <tr key={i}>
                        <td className="font-medium">{row.asset_code || row.code}</td>
                        <td>{row.asset_name || row.name}</td>
                        <td>{row.category}</td>
                        <td>{row.acquisition_date || row.purchase_date}</td>
                        <td>{row.location || '-'}</td>
                        <td>
                            <span className={`badge ${row.status === 'active' ? 'badge-success' : row.status === 'disposed' ? 'badge-danger' : 'badge-secondary'}`}>
                                {row.status}
                            </span>
                        </td>
                        <td className="text-end">{formatNumber(row.cost || row.original_cost)} <small>{currency}</small></td>
                        <td className="text-end">{formatNumber(row.accumulated_depreciation || 0)} <small>{currency}</small></td>
                        <td className="text-end font-medium">{formatNumber(row.net_book_value || row.nbv || 0)} <small>{currency}</small></td>
                    </tr>
                ))}
                {data.length > 0 && (
                    <tr className="font-bold" style={{ borderTop: '2px solid var(--border-color)' }}>
                        <td colSpan={6} className="text-end">{t('common.total')}</td>
                        <td className="text-end">{formatNumber(totalCost)} <small>{currency}</small></td>
                        <td className="text-end">{formatNumber(totalDepreciation)} <small>{currency}</small></td>
                        <td className="text-end">{formatNumber(totalNBV)} <small>{currency}</small></td>
                    </tr>
                )}
            </tbody>
        </table>
    );

    const renderDepreciationTable = () => (
        <table className="data-table">
            <thead>
                <tr>
                    <th>{t('asset_reports.category')}</th>
                    <th>{t('asset_reports.asset_count')}</th>
                    <th className="text-end">{t('asset_reports.original_cost')}</th>
                    <th className="text-end">{t('asset_reports.period_depreciation')}</th>
                    <th className="text-end">{t('asset_reports.accum_depr')}</th>
                    <th className="text-end">{t('asset_reports.nbv')}</th>
                    <th className="text-end">{t('asset_reports.depr_rate')}</th>
                </tr>
            </thead>
            <tbody>
                {data.length === 0 ? (
                    <tr><td colSpan={7} className="text-center text-muted p-4">{t('asset_reports.no_data')}</td></tr>
                ) : data.map((row, i) => (
                    <tr key={i}>
                        <td className="font-medium">{row.category}</td>
                        <td>{row.asset_count || row.count}</td>
                        <td className="text-end">{formatNumber(row.original_cost || row.total_cost)} <small>{currency}</small></td>
                        <td className="text-end">{formatNumber(row.period_depreciation || 0)} <small>{currency}</small></td>
                        <td className="text-end">{formatNumber(row.total_depreciation || row.accumulated_depreciation)} <small>{currency}</small></td>
                        <td className="text-end font-medium">{formatNumber(row.net_book_value || row.nbv)} <small>{currency}</small></td>
                        <td className="text-end">{row.depreciation_rate || row.rate ? `${formatNumber(row.depreciation_rate || row.rate)}%` : '-'}</td>
                    </tr>
                ))}
            </tbody>
        </table>
    );

    const renderNBVTable = () => (
        <table className="data-table">
            <thead>
                <tr>
                    <th>{t('asset_reports.asset_name')}</th>
                    <th>{t('asset_reports.category')}</th>
                    <th>{t('asset_reports.useful_life')}</th>
                    <th>{t('asset_reports.remaining_life')}</th>
                    <th className="text-end">{t('asset_reports.original_cost')}</th>
                    <th className="text-end">{t('asset_reports.accum_depr')}</th>
                    <th className="text-end">{t('asset_reports.nbv')}</th>
                    <th className="text-end">{t('asset_reports.nbv_percent')}</th>
                </tr>
            </thead>
            <tbody>
                {data.length === 0 ? (
                    <tr><td colSpan={8} className="text-center text-muted p-4">{t('asset_reports.no_data')}</td></tr>
                ) : data.map((row, i) => {
                    const costDec = new Decimal(row.cost || row.original_cost || '0');
                    const nbvDec = new Decimal(row.net_book_value || row.nbv || '0');
                    const nbvPct = costDec.gt(0)
                        ? nbvDec.dividedBy(costDec).times(100).toNumber()
                        : 0;
                    return (
                        <tr key={i}>
                            <td className="font-medium">{row.asset_name || row.name}</td>
                            <td>{row.category}</td>
                            <td>{row.useful_life || '-'}</td>
                            <td>{row.remaining_life || '-'}</td>
                            <td className="text-end">{formatNumber(row.cost || row.original_cost)} <small>{currency}</small></td>
                            <td className="text-end">{formatNumber(row.accumulated_depreciation || row.total_depreciation || 0)} <small>{currency}</small></td>
                            <td className="text-end font-medium">{formatNumber(row.net_book_value || row.nbv || 0)} <small>{currency}</small></td>
                            <td className="text-end">
                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '8px' }}>
                                    <div className="progress-bar-container" style={{ width: '60px', height: '6px', background: 'var(--bg-secondary)', borderRadius: '3px' }}>
                                        <div style={{ width: `${Math.min(nbvPct, 100)}%`, height: '100%', background: nbvPct > 50 ? 'var(--success)' : nbvPct > 20 ? 'var(--warning)' : 'var(--danger)', borderRadius: '3px' }}></div>
                                    </div>
                                    {formatNumber(nbvPct, 1)}%
                                </div>
                            </td>
                        </tr>
                    );
                })}
            </tbody>
        </table>
    );

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">🏗️ {t('asset_reports.title')}</h1>
                    <p className="workspace-subtitle">{t('asset_reports.subtitle')}</p>
                </div>
                <div className="header-actions">
                    <button className="btn btn-secondary" onClick={() => window.print()}>🖨️ {t('common.print')}</button>
                    <button className="btn btn-primary" onClick={fetchData}>🔄 {t('common.refresh')}</button>
                </div>
            </div>

            {/* Summary Cards */}
            <div className="metrics-grid" style={{ marginBottom: '24px' }}>
                <div className="metric-card">
                    <div className="metric-label">{t('asset_reports.total_cost')}</div>
                    <div className="metric-value text-primary">{formatNumber(totalCost)}</div>
                    <div className="metric-change">{currency}</div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('asset_reports.total_depreciation')}</div>
                    <div className="metric-value text-warning">{formatNumber(totalDepreciation)}</div>
                    <div className="metric-change">{currency}</div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('asset_reports.total_nbv')}</div>
                    <div className="metric-value text-success">{formatNumber(totalNBV)}</div>
                    <div className="metric-change">{currency}</div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('asset_reports.asset_count')}</div>
                    <div className="metric-value">
                        {activeTab === 'depreciation'
                            ? data.reduce((sum, row) => sum.plus(new Decimal(row.asset_count || row.count || 0)), new Decimal(0)).toNumber()
                            : data.length}
                    </div>
                    <div className="metric-change">{t('asset_reports.assets')}</div>
                </div>
            </div>

            {/* Report Type Selector */}
            <div className="card p-4" style={{ marginBottom: '16px' }}>
                <div className="form-grid-4">
                    <div className="form-group">
                        <label>{t('asset_reports.report_type')}</label>
                        <select className="form-select" value={activeTab} onChange={e => setActiveTab(e.target.value)}>
                            {tabs.map(tab => (
                                <option key={tab.key} value={tab.key}>{tab.label}</option>
                            ))}
                        </select>
                    </div>
                    <div className="form-group" style={{ display: 'flex', alignItems: 'flex-end' }}>
                        <button className="btn btn-primary" onClick={fetchData} disabled={loading}>
                            {loading ? t('common.loading') : t('common.generate')}
                        </button>
                    </div>
                </div>
            </div>

            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            {initialLoad && loading ? (
                <PageLoading />
            ) : error ? (
                <div className="alert alert-danger">{error}</div>
            ) : (
                <div className="card">
                    <div className="card-header">
                        <h3 className="card-title">{tabs.find(t => t.key === activeTab)?.label}</h3>
                    </div>
                    <div className="data-table-container">
                        {activeTab === 'register' && renderRegisterTable()}
                        {activeTab === 'depreciation' && renderDepreciationTable()}
                        {activeTab === 'nbv' && renderNBVTable()}
                    </div>
                </div>
            )}
        </div>
    );
}

export default AssetReports;
