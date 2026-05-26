import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useBranch } from '../../context/BranchContext';
import { useToast } from '../../context/ToastContext';
import { getCurrency } from '../../utils/auth';
import { formatNumber } from '../../utils/format';
import { reportsAPI } from '../../utils/api';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

function PurchasesAgingReport() {
    const { t } = useTranslation();
    const { currentBranch } = useBranch();
    const { showToast } = useToast();
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [error, setError] = useState(null);
    const currency = getCurrency();

    const fetchData = async () => {
        try {
            setLoading(true);
            setError(null);
            const res = await reportsAPI.getPurchasesAgingSummary(currentBranch?.id);
            setData(res.data || { items: [], buckets: [], total_due: '0' });
        } catch (err) {
            showToast(t('common.error'), 'error');
            setError(t('errors.fetch_failed'));
        } finally {
            setLoading(false);
            setInitialLoad(false);
        }
    };

    useEffect(() => {
        const timer = setTimeout(() => { fetchData(); }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch]);

    const buckets = data.buckets || [];
    const items = data.items || [];

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">⏳ {t('purchases_aging.title')}</h1>
                    <p className="workspace-subtitle">{t('purchases_aging.subtitle')}</p>
                </div>
                <div className="header-actions">
                    <button className="btn btn-secondary" onClick={() => window.print()}>🖨️ {t('common.print')}</button>
                    <button className="btn btn-primary" onClick={fetchData}>🔄 {t('common.refresh')}</button>
                </div>
            </div>

            {initialLoad && !items.length ? (
                <PageLoading />
            ) : error ? (
                <div className="alert alert-danger">{error}</div>
            ) : (
                <>
                    {/* Bucket Summary Cards */}
                    <div className="metrics-grid" style={{ marginBottom: '24px' }}>
                        {buckets.map(bucket => (
                            <div key={bucket.name} className="metric-card">
                                <div className="metric-label">{bucket.name} {t('purchases_aging.days')}</div>
                                <div className={`metric-value ${bucket.name === '90+' ? 'text-danger' : bucket.name === '61-90' ? 'text-warning' : 'text-success'}`}>
                                    {formatNumber(bucket.amount)}
                                </div>
                                <div className="metric-change">{currency}</div>
                            </div>
                        ))}
                        <div className="metric-card">
                            <div className="metric-label">{t('common.total')}</div>
                            <div className="metric-value text-primary">{formatNumber(data.total_due)}</div>
                            <div className="metric-change">{items.length} {t('purchases_aging.invoices')}</div>
                        </div>
                    </div>

                    {/* Detail Table */}
                    <div className="card">
                        <div className="card-header">
                            <h3 className="card-title">{t('purchases_aging.details')}</h3>
                        </div>
                        <div className="data-table-container">
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>{t('purchases_aging.supplier')}</th>
                                        <th>{t('purchases_aging.invoice')}</th>
                                        <th>{t('purchases_aging.date')}</th>
                                        <th>{t('purchases_aging.due_date')}</th>
                                        <th>{t('purchases_aging.days_old')}</th>
                                        <th>{t('purchases_aging.bucket')}</th>
                                        <th className="text-end">{t('purchases_aging.amount')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {items.length === 0 ? (
                                        <tr><td colSpan={7} className="text-center text-muted p-4">{t('purchases_aging.no_data')}</td></tr>
                                    ) : items.map((row, i) => (
                                        <tr key={i}>
                                            <td className="font-medium">{row.supplier}</td>
                                            <td>{row.invoice}</td>
                                            <td>{row.date}</td>
                                            <td>{row.due_date}</td>
                                            <td>
                                                <span className={`badge ${row.days > 90 ? 'badge-danger' : row.days > 60 ? 'badge-warning' : 'badge-success'}`}>
                                                    {row.days} {t('purchases_aging.day')}
                                                </span>
                                            </td>
                                            <td>{row.bucket}</td>
                                            <td className="text-end font-medium">{formatNumber(row.amount)} {row.currency !== currency ? row.currency : ''}</td>
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

export default PurchasesAgingReport;
