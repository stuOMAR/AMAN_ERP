import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useBranch } from '../../context/BranchContext';
import { getCurrency } from '../../utils/auth';
import { formatNumber } from '../../utils/format';
import { checksAPI } from '../../utils/api';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

function ChecksAgingReport() {
    const { t } = useTranslation();
    const { currentBranch } = useBranch();
    const [data, setData] = useState({ receivable: [], payable: [], summary: {} });
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [error, setError] = useState(null);
    const [activeTab, setActiveTab] = useState('receivable');
    const currency = getCurrency();

    const fetchData = async () => {
        try {
            setLoading(true);
            setError(null);
            const res = await checksAPI.getAgingReport({ branch_id: currentBranch?.id });
            setData(res.data || { receivable: [], payable: [], summary: {} });
        } catch (err) {
            console.error('Failed to fetch checks aging', err);
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
    }, [currentBranch]);

    const tabs = [
        { key: 'receivable', label: t('checks_aging.receivable'), icon: '📥' },
        { key: 'payable', label: t('checks_aging.payable'), icon: '📤' },
    ];

    const activeData = data[activeTab] || [];
    const buckets = ['0-30', '31-60', '61-90', '90+'];
    const summary = data.bucket_summary || data.summary || {};

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">📋 {t('checks_aging.title')}</h1>
                    <p className="workspace-subtitle">{t('checks_aging.subtitle')}</p>
                </div>
                <div className="header-actions">
                    <button className="btn btn-secondary" onClick={() => window.print()}>🖨️ {t('common.print')}</button>
                    <button className="btn btn-primary" onClick={fetchData}>🔄 {t('common.refresh')}</button>
                </div>
            </div>

            {initialLoad ? (
                <PageLoading />
            ) : error ? (
                <div className="alert alert-danger">{error}</div>
            ) : (
                <>
                    {/* Summary Cards */}
                    <div className="metrics-grid" style={{ marginBottom: '24px' }}>
                        {buckets.map(bucket => (
                            <div key={bucket} className="metric-card">
                                <div className="metric-label">{bucket} {t('checks_aging.days')}</div>
                                <div className={`metric-value ${bucket === '90+' ? 'text-danger' : bucket === '61-90' ? 'text-warning' : 'text-success'}`}>
                                    {formatNumber(summary[bucket]?.receivable || 0)}
                                </div>
                                <div className="metric-change">{t('checks_aging.receivable')}</div>
                            </div>
                        ))}
                    </div>

                    {/* Tabs */}
                    <div className="tabs-container" style={{ marginBottom: '16px' }}>
                        {tabs.map(tab => (
                            <button
                                key={tab.key}
                                className={`tab-btn ${activeTab === tab.key ? 'active' : ''}`}
                                onClick={() => setActiveTab(tab.key)}
                            >
                                {tab.icon} {tab.label}
                            </button>
                        ))}
                    </div>

                    {/* Detail Table */}
                    <div className="card">
                        <div className="card-header">
                            <h3 className="card-title">{tabs.find(t => t.key === activeTab)?.label} — {t('checks_aging.details')}</h3>
                        </div>
                        <div className="data-table-container">
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>{t('checks_aging.check_number')}</th>
                                        <th>{t('checks_aging.party')}</th>
                                        <th>{t('checks_aging.bank')}</th>
                                        <th>{t('checks_aging.date')}</th>
                                        <th>{t('checks_aging.due_date')}</th>
                                        <th>{t('checks_aging.days_old')}</th>
                                        <th>{t('checks_aging.bucket')}</th>
                                        <th>{t('checks_aging.status')}</th>
                                        <th className="text-end">{t('checks_aging.amount')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {activeData.length === 0 ? (
                                        <tr><td colSpan={9} className="text-center text-muted p-4">{t('checks_aging.no_data')}</td></tr>
                                    ) : activeData.map((row, i) => (
                                        <tr key={i}>
                                            <td className="font-medium">{row.check_number}</td>
                                            <td>{row.party}</td>
                                            <td>{row.bank}</td>
                                            <td>{row.date}</td>
                                            <td>{row.due_date}</td>
                                            <td>
                                                <span className={`badge ${row.days > 90 ? 'badge-danger' : row.days > 60 ? 'badge-warning' : 'badge-success'}`}>
                                                    {row.days}
                                                </span>
                                            </td>
                                            <td>{row.bucket}</td>
                                            <td>
                                                <span className={`badge ${row.status === 'bounced' ? 'badge-danger' : row.status === 'deposited' ? 'badge-info' : 'badge-secondary'}`}>
                                                    {row.status}
                                                </span>
                                            </td>
                                            <td className="text-end font-medium">{formatNumber(row.amount)} {currency}</td>
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

export default ChecksAgingReport;
