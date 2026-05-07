import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { profitabilityAPI } from '../../services/inventory';
import { useBranch } from '../../context/BranchContext';
import { useToast } from '../../context/ToastContext';
import { formatNumber } from '../../utils/format';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates';

const ProfitabilityReport = () => {
    const { t } = useTranslation();
    const { currentBranch } = useBranch();
    const { showToast } = useToast();
    const [loading, setLoading] = useState(true);
    const [data, setData] = useState(null);
    const [summary, setSummary] = useState(null);
    const [startDate, setStartDate] = useState(() => {
        const d = new Date();
        d.setMonth(d.getMonth() - 3);
        return d.toISOString().split('T')[0];
    });
    const [endDate, setEndDate] = useState(() => new Date().toISOString().split('T')[0]);

    useEffect(() => {
        fetchData();
    }, [currentBranch, startDate, endDate]);

    const fetchData = async () => {
        try {
            setLoading(true);
            const params = {
                branch_id: currentBranch?.id,
                start_date: startDate,
                end_date: endDate,
            };
            const [reportRes, summaryRes] = await Promise.all([
                profitabilityAPI.getReport(params),
                profitabilityAPI.getSummary(params),
            ]);
            setData(reportRes.data);
            setSummary(summaryRes.data);
        } catch (err) {
            showToast(t('common.error'), 'error');
        } finally {
            setLoading(false);
        }
    };

    const displayCurrency = data?.currency || summary?.currency || 'SAR';

    if (loading) return <PageLoading />;

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div>
                    <h1 className="workspace-title">
                        📊 {t('stock.profitability.title', 'تقرير ربحية المنتجات')}
                    </h1>
                    <p className="workspace-subtitle">
                        {t('stock.profitability.subtitle', 'تحليل الربح الإجمالي لكل منتج')}
                    </p>
                </div>
            </div>

            {/* Filters */}
            <div className="section-card" style={{ marginBottom: '24px', padding: '16px' }}>
                <div style={{ display: 'flex', gap: '16px', alignItems: 'center', flexWrap: 'wrap' }}>
                    <div>
                        <label style={{ display: 'block', fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '4px' }}>
                            {t('common.from_date', 'من تاريخ')}
                        </label>
                        <input
                            type="date"
                            value={startDate}
                            onChange={(e) => setStartDate(e.target.value)}
                            className="form-input"
                            style={{ padding: '8px 12px' }}
                        />
                    </div>
                    <div>
                        <label style={{ display: 'block', fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '4px' }}>
                            {t('common.to_date', 'إلى تاريخ')}
                        </label>
                        <input
                            type="date"
                            value={endDate}
                            onChange={(e) => setEndDate(e.target.value)}
                            className="form-input"
                            style={{ padding: '8px 12px' }}
                        />
                    </div>
                </div>
            </div>

            {/* Summary Cards */}
            {summary && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', marginBottom: '24px' }}>
                    <div className="section-card" style={{ padding: '16px', textAlign: 'center' }}>
                        <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '8px' }}>
                            {t('stock.profitability.total_revenue', 'إجمالي الإيرادات')}
                        </div>
                        <div style={{ fontSize: '24px', fontWeight: '700', color: 'var(--primary)' }}>
                            {formatNumber(summary.total_revenue)} {displayCurrency}
                        </div>
                    </div>
                    <div className="section-card" style={{ padding: '16px', textAlign: 'center' }}>
                        <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '8px' }}>
                            {t('stock.profitability.total_cogs', 'تكلفة المبيعات')}
                        </div>
                        <div style={{ fontSize: '24px', fontWeight: '700', color: 'var(--warning)' }}>
                            {formatNumber(summary.total_cogs)} {displayCurrency}
                        </div>
                    </div>
                    <div className="section-card" style={{ padding: '16px', textAlign: 'center' }}>
                        <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '8px' }}>
                            {t('stock.profitability.gross_profit', 'الربح الإجمالي')}
                        </div>
                        <div style={{ fontSize: '24px', fontWeight: '700', color: summary.gross_profit >= 0 ? 'var(--success)' : 'var(--danger)' }}>
                            {formatNumber(summary.gross_profit)} {displayCurrency}
                        </div>
                    </div>
                    <div className="section-card" style={{ padding: '16px', textAlign: 'center' }}>
                        <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '8px' }}>
                            {t('stock.profitability.margin', 'هامش الربح')}
                        </div>
                        <div style={{ fontSize: '24px', fontWeight: '700', color: summary.margin_pct >= 0 ? 'var(--success)' : 'var(--danger)' }}>
                            {summary.margin_pct}%
                        </div>
                    </div>
                    <div className="section-card" style={{ padding: '16px', textAlign: 'center' }}>
                        <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '8px' }}>
                            {t('stock.profitability.invoice_count', 'عدد الفواتير')}
                        </div>
                        <div style={{ fontSize: '24px', fontWeight: '700' }}>
                            {summary.invoice_count}
                        </div>
                    </div>
                </div>
            )}

            {/* Products Table */}
            {data && data.items && (
                <div className="section-card">
                    <div style={{ overflowX: 'auto' }}>
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th>{t('stock.profitability.table.product', 'المنتج')}</th>
                                    <th>{t('stock.profitability.table.sku', 'الكود')}</th>
                                    <th style={{ textAlign: 'right' }}>{t('stock.profitability.table.qty', 'الكمية')}</th>
                                    <th style={{ textAlign: 'right' }}>{t('stock.profitability.table.revenue', 'الإيراد')}</th>
                                    <th style={{ textAlign: 'right' }}>{t('stock.profitability.table.cogs', 'التكلفة')}</th>
                                    <th style={{ textAlign: 'right' }}>{t('stock.profitability.table.profit', 'الربح')}</th>
                                    <th style={{ textAlign: 'right' }}>{t('stock.profitability.table.margin', 'الهامش %')}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {data.items.map((item, idx) => (
                                    <tr key={idx}>
                                        <td style={{ fontWeight: '600' }}>{item.product_name}</td>
                                        <td>{item.sku || '-'}</td>
                                        <td style={{ textAlign: 'right' }}>{formatNumber(item.sold_qty)}</td>
                                        <td style={{ textAlign: 'right', fontWeight: '600' }}>
                                            {formatNumber(item.revenue)} {displayCurrency}
                                        </td>
                                        <td style={{ textAlign: 'right' }}>
                                            {formatNumber(item.cogs)} {displayCurrency}
                                        </td>
                                        <td style={{
                                            textAlign: 'right',
                                            fontWeight: '700',
                                            color: item.gross_profit >= 0 ? 'var(--success)' : 'var(--danger)'
                                        }}>
                                            {formatNumber(item.gross_profit)} {displayCurrency}
                                        </td>
                                        <td style={{
                                            textAlign: 'right',
                                            fontWeight: '600',
                                            color: item.margin_pct >= 0 ? 'var(--success)' : 'var(--danger)'
                                        }}>
                                            {item.margin_pct}%
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                            <tfoot>
                                <tr style={{ fontWeight: '700', background: 'var(--bg-secondary)' }}>
                                    <td colSpan="2">{t('common.total', 'الإجمالي')}</td>
                                    <td style={{ textAlign: 'right' }}>{formatNumber(data.totals?.revenue ? data.items.reduce((s, i) => s + i.sold_qty, 0) : 0)}</td>
                                    <td style={{ textAlign: 'right' }}>{formatNumber(data.totals?.revenue)} {displayCurrency}</td>
                                    <td style={{ textAlign: 'right' }}>{formatNumber(data.totals?.cogs)} {displayCurrency}</td>
                                    <td style={{ textAlign: 'right', color: data.totals?.gross_profit >= 0 ? 'var(--success)' : 'var(--danger)' }}>
                                        {formatNumber(data.totals?.gross_profit)} {displayCurrency}
                                    </td>
                                    <td style={{ textAlign: 'right', color: data.totals?.margin_pct >= 0 ? 'var(--success)' : 'var(--danger)' }}>
                                        {data.totals?.margin_pct}%
                                    </td>
                                </tr>
                            </tfoot>
                        </table>
                    </div>
                </div>
            )}

            {data && data.items && data.items.length === 0 && (
                <div className="section-card" style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)' }}>
                    <p>{t('stock.profitability.no_data', 'لا توجد بيانات لهذه الفترة')}</p>
                </div>
            )}
        </div>
    );
};

export default ProfitabilityReport;
