import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { inventoryAPI } from '../../utils/api';
import { useBranch } from '../../context/BranchContext';
import { useToast } from '../../context/ToastContext';
import { formatNumber } from '../../utils/format';
import BackButton from '../../components/common/BackButton';
import { ModuleKPISection } from '../../components/kpi';
import { PageLoading } from '../../components/common/LoadingStates'

const StockReports = () => {
    const { t } = useTranslation();
    const { currentBranch } = useBranch();
    const { showToast } = useToast();
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [warehouseStock, setWarehouseStock] = useState([]);
    const [filter, setFilter] = useState('');

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchData();
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch]);

    const fetchData = async () => {
        try {
            const res = await inventoryAPI.getInventoryBalance({ branch_id: currentBranch?.id });
            setWarehouseStock(res.data);
        } catch (err) {
            showToast(t('errors.fetch_failed'), 'error');
        } finally {
            setLoading(false);
            setInitialLoad(false);
        }
    };

    // Group by Warehouse
    const groupedStock = warehouseStock.reduce((acc, item) => {
        const wh = item.warehouse || t('stock.reports.balance.unassigned');
        if (!acc[wh]) acc[wh] = [];
        acc[wh].push(item);
        return acc;
    }, {});

    if (initialLoad) return <PageLoading />;

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div>
                    <h1 className="workspace-title">{t('stock.reports.balance.title')}</h1>
                    <p className="workspace-subtitle">{t('stock.reports.balance.subtitle')}</p>
                </div>
            </div>

            <ModuleKPISection roleKey="warehouse" color="#0891b2" defaultOpen={false} />

            {/* Filter */}
            <div className="section-card mb-6" style={{ marginBottom: '24px' }}>
                <input
                    type="text"
                    placeholder={t('stock.reports.balance.search_placeholder')}
                    className="form-input"
                    value={filter}
                    onChange={e => setFilter(e.target.value)}
                />
            </div>

            {/* Warehouse Tables */}
            <div style={{ display: 'grid', gap: '24px' }}>
                {filteredWarehouses.map(wh => (
                    <div key={wh} className="section-card">
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', borderBottom: '1px solid var(--border-color)', paddingBottom: '12px' }}>
                            <h3 className="section-title" style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <span style={{ fontSize: '1.2em' }}>📍</span> {wh}
                            </h3>
                            <span className="badge badge-secondary">
                                {groupedStock[wh].filter(item =>
                                    item.item_name.includes(filter) || item.item_code.includes(filter)
                                ).length} {t('stock.reports.balance.items_count')}
                            </span>
                        </div>

                        <div className="overflow-x-auto">
                            <table className="data-table">
                                <thead>
                                    <tr>
                                        <th>{t('stock.reports.balance.table.code')}</th>
                                        <th>{t('stock.reports.balance.table.name')}</th>
                                        <th>{t('stock.reports.balance.table.unit')}</th>
                                        <th>{t('stock.reports.balance.table.quantity')}</th>
                                        <th>{t('stock.reports.balance.table.status')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {groupedStock[wh]
                                        .filter(item =>
                                            item.item_name.includes(filter) || item.item_code.includes(filter)
                                        )
                                        .map((item, idx) => (
                                            <tr key={idx} style={{
                                                background: item.quantity <= 0 ? '#FEF2F2' : 'transparent'
                                            }}>
                                                <td className="font-mono text-sm text-muted">{item.item_code}</td>
                                                <td className="font-medium">{item.item_name}</td>
                                                <td className="text-sm">{item.unit}</td>
                                                <td className="font-bold" style={{
                                                    color: item.quantity < 0 ? '#DC2626' : 'inherit'
                                                }}>
                                                    {formatNumber(item.quantity)}
                                                </td>
                                                <td>
                                                    {item.quantity <= 0 ? (
                                                        <span className="badge badge-danger">{t('stock.reports.balance.stock_status.out_of_stock')}</span>
                                                    ) : item.quantity < 10 ? (
                                                        <span className="badge badge-warning">{t('stock.reports.balance.stock_status.low')}</span>
                                                    ) : (
                                                        <span className="badge badge-success">{t('stock.reports.balance.stock_status.good')}</span>
                                                    )}
                                                </td>
                                            </tr>
                                        ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                ))}

                {filteredWarehouses.length === 0 && (
                    <div className="text-center py-12 text-muted">
                        {t('stock.reports.balance.no_results')}
                    </div>
                )}
            </div>
        </div>
    );
};

export default StockReports;
